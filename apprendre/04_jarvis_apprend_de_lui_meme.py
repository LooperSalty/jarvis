"""04_jarvis_apprend_de_lui_meme.py — boucle d'auto-amelioration.

Objectif : connecter ce que les 3 etapes precedentes t'ont appris, et faire
en sorte que Jarvis s'AMELIORE TOUT SEUL au fil de tes conversations, sans
qu'il faille relancer DSPy ou LoRA a la main.

Principe :
1. Chaque conversation Jarvis va dans `jarvis_historique.json`.
2. Ce script surveille le fichier en arriere-plan.
3. Tous les N nouveaux echanges, il :
    - Re-genere un dataset propre depuis l'historique
    - Note chaque reponse passee avec la metrique de qualite (qualite_score)
    - Garde uniquement les "bonnes" reponses (top X%) pour l'apprentissage
    - Optimise le system prompt avec DSPy (rapide)
    - Optionnellement, declenche un fine-tune LoRA (lourd, sur seuil plus haut)
4. Le nouveau prompt est ecrit dans `apprendre/prompt_actif.txt`.
5. main2.py peut le lire au prochain demarrage (ou a chaud avec un /reload).

Usage :
    python apprendre/04_jarvis_apprend_de_lui_meme.py        # boucle continue
    python apprendre/04_jarvis_apprend_de_lui_meme.py --once # une seule passe

Aucune dep ML obligatoire pour la passe "scoring + dataset". DSPy est appele
seulement si dispo, et LoRA seulement sur seuil haut + GPU dispo.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("jarvis-learn")


# =============================================================================
# 0. CONFIGURATION
# =============================================================================

ROOT = Path(__file__).parent.parent
HISTORIQUE_PATH = ROOT / "jarvis_historique.json"

OUT_DIR = Path(__file__).parent
DATASET_PATH = OUT_DIR / "dataset_propre.jsonl"
PROMPT_ACTIF_PATH = OUT_DIR / "prompt_actif.txt"
STATE_PATH = OUT_DIR / "_learn_state.json"

# Seuils
SEUIL_DSPY = 20            # nouvelles paires depuis dernier optim DSPy
SEUIL_LORA = 200           # nouvelles paires depuis dernier LoRA (lourd, rare)
TOP_FRACTION = 0.5         # garde la moitie superieure (par score)
INTERVALLE_POLLING = 60    # secondes entre 2 checks du fichier


# =============================================================================
# 1. METRIQUE DE QUALITE — meme idee qu'au module 02
# =============================================================================

def qualite_score(reponse: str) -> float:
    """Note 0..1 d'une reponse Jarvis. Plus haut = mieux."""
    rep = (reponse or "").strip().lower()
    if not rep:
        return 0.0
    s = 0.0
    s += 0.2  # non vide

    mots_fr = ("le", "la", "les", "un", "une", "tu", "je", "ne", "pas",
               "est", "et", "de", "que", "qui", "ca", "c'est", "j'ai")
    if sum(1 for m in mots_fr if f" {m} " in f" {rep} ") >= 2:
        s += 0.2

    if len(rep) <= 200:
        s += 0.2
    elif len(rep) <= 400:
        s += 0.1

    polluants = (
        "je suis ravi", "avec plaisir", "n'hesite pas", "i'm happy",
        "as an ai", "en tant qu'ia", "en tant qu'assistant",
    )
    if not any(p in rep for p in polluants):
        s += 0.2

    if rep.count("**") < 2 and rep.count("```") < 1 and rep.count("#") < 3:
        s += 0.2
    return s


# =============================================================================
# 2. EXTRACTION + NETTOYAGE DU DATASET
# =============================================================================

@dataclass
class Echange:
    user: str
    assistant: str
    score: float = 0.0


def extraire_echanges() -> List[Echange]:
    """Lit l'historique brut de Jarvis et le convertit en paires user/assistant."""
    if not HISTORIQUE_PATH.exists():
        log.warning("pas d'historique a %s", HISTORIQUE_PATH)
        return []
    raw = json.loads(HISTORIQUE_PATH.read_text(encoding="utf-8"))
    items = raw.get("history") if isinstance(raw, dict) else raw
    if not items:
        return []

    echanges: List[Echange] = []
    pending = None
    for it in items:
        role = it.get("role", "")
        text = it.get("text") or it.get("content") or ""
        if not text:
            continue
        if role in ("user", "human"):
            pending = text
        elif role in ("model", "assistant") and pending is not None:
            ech = Echange(user=pending, assistant=text)
            ech.score = qualite_score(text)
            echanges.append(ech)
            pending = None
    return echanges


def filtrer_top(echanges: List[Echange], fraction: float) -> List[Echange]:
    """Garde la moitie/X% superieure par score."""
    if not echanges:
        return []
    triee = sorted(echanges, key=lambda e: e.score, reverse=True)
    cut = max(1, int(len(triee) * fraction))
    return triee[:cut]


def ecrire_dataset(echanges: List[Echange]) -> None:
    """Ecrit le dataset au format JSONL ChatML (compatible HuggingFace)."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with DATASET_PATH.open("w", encoding="utf-8") as f:
        for ech in echanges:
            sample = {
                "messages": [
                    {"role": "system", "content": "Tu es Jarvis, assistant dev de Monsieur. Francais, concis, direct."},
                    {"role": "user", "content": ech.user},
                    {"role": "assistant", "content": ech.assistant},
                ],
                "score": round(ech.score, 3),
            }
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")
    log.info("dataset ecrit : %s (%d exemples)", DATASET_PATH, len(echanges))


# =============================================================================
# 3. OPTIMISATION DSPy (rapide) — declenchee tous les SEUIL_DSPY exemples
# =============================================================================

def optimiser_prompt_dspy(echanges: List[Echange]) -> Optional[str]:
    """Lance DSPy sur les bons exemples si DSPy dispo. Retourne le prompt optim."""
    try:
        import dspy
        from dspy.teleprompt import BootstrapFewShot
    except ImportError:
        log.info("dspy non installe, skip optim prompt (pip install dspy-ai)")
        return None

    if len(echanges) < 4:
        log.info("trop peu d'exemples pour DSPy")
        return None

    log.info("DSPy : optim sur %d exemples", len(echanges))

    class Sig(dspy.Signature):
        """Tu es JARVIS, assistant dev personnel de Monsieur. Reponds en francais,
        concis, direct, sans phrase creuse. Va a l'essentiel."""

        question: str = dspy.InputField()
        reponse: str = dspy.OutputField()

    class Mod(dspy.Module):
        def __init__(self):
            super().__init__()
            self.predict = dspy.Predict(Sig)

        def forward(self, question):
            return self.predict(question=question)

    try:
        lm = dspy.LM(
            model="ollama_chat/qwen2.5:7b",
            api_base="http://localhost:11434",
            api_key="ollama",
        )
        dspy.configure(lm=lm)
    except Exception as exc:
        log.warning("dspy.configure ko : %s", exc)
        return None

    examples = [
        dspy.Example(question=e.user, reponse_attendue=e.assistant).with_inputs("question")
        for e in echanges
    ]

    def _metric(ex, pred, trace=None):
        return qualite_score(getattr(pred, "reponse", ""))

    bootstrapper = BootstrapFewShot(metric=_metric, max_bootstrapped_demos=4)
    try:
        compiled = bootstrapper.compile(Mod(), trainset=examples[: int(len(examples) * 0.7)])
    except Exception as exc:
        log.warning("compile DSPy ko : %s", exc)
        return None

    # Extraction des demos selectionnees pour les injecter dans le prompt
    demos_text = []
    for _, predictor in compiled.named_predictors():
        for d in getattr(predictor, "demos", []) or []:
            q = getattr(d, "question", "")
            r = getattr(d, "reponse", "")
            if q and r:
                demos_text.append(f"Q: {q}\nR: {r}")

    if not demos_text:
        return None

    prompt = (
        "Tu es JARVIS, assistant dev personnel de Monsieur. Reponds en francais, "
        "concis, direct, sans phrase creuse. Va a l'essentiel.\n\n"
        "Exemples du style attendu :\n\n"
        + "\n\n".join(demos_text)
    )
    return prompt


# =============================================================================
# 4. FINE-TUNE LoRA (lourd) — declenche tous les SEUIL_LORA exemples + GPU
# =============================================================================

def lancer_lora_si_pertinent(nb_nouveaux: int) -> None:
    """Optionnel : lance le fine-tune LoRA en background si seuil + GPU dispo."""
    if nb_nouveaux < SEUIL_LORA:
        return
    try:
        import torch  # noqa: F401
    except ImportError:
        log.info("torch non installe, skip LoRA (pip install torch transformers peft trl)")
        return

    import torch as _t
    if not _t.cuda.is_available():
        log.info("pas de GPU CUDA, skip LoRA")
        return

    log.info("seuil LoRA atteint, lancement de 03_lora_finetune_qwen.py en sous-process")
    import subprocess

    script = Path(__file__).parent / "03_lora_finetune_qwen.py"
    subprocess.Popen([sys.executable, str(script)])


# =============================================================================
# 5. ETAT PERSISTANT
# =============================================================================

def charger_etat() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def sauver_etat(etat: dict) -> None:
    STATE_PATH.write_text(json.dumps(etat, ensure_ascii=False, indent=2), encoding="utf-8")


# =============================================================================
# 6. UNE PASSE D'APPRENTISSAGE
# =============================================================================

def une_passe() -> dict:
    """Lit historique, score, filtre, ecrit dataset, optimise prompt si seuil."""
    etat = charger_etat()
    nb_vu_avant = etat.get("nb_total", 0)

    echanges = extraire_echanges()
    nb_total = len(echanges)
    nb_nouveaux = nb_total - nb_vu_avant

    log.info("historique : %d echanges (%d nouveaux depuis dernier check)",
             nb_total, nb_nouveaux)

    if nb_total == 0:
        return etat

    # Filtre qualite et ecrit le dataset propre (utile pour LoRA + inspection)
    bons = filtrer_top(echanges, TOP_FRACTION)
    log.info("apres filtre top %.0f%% : %d 'bons' exemples (score moyen %.2f)",
             TOP_FRACTION * 100, len(bons),
             sum(e.score for e in bons) / max(1, len(bons)))
    ecrire_dataset(bons)

    # Trigger DSPy si seuil
    if nb_nouveaux >= SEUIL_DSPY or not PROMPT_ACTIF_PATH.exists():
        prompt = optimiser_prompt_dspy(bons)
        if prompt:
            PROMPT_ACTIF_PATH.write_text(prompt, encoding="utf-8")
            log.info("nouveau prompt actif ecrit : %s", PROMPT_ACTIF_PATH)
            etat["dernier_dspy_at"] = time.time()
    else:
        log.info("seuil DSPy non atteint (%d/%d), skip", nb_nouveaux, SEUIL_DSPY)

    # Trigger LoRA si seuil tres haut
    nouveaux_depuis_lora = nb_total - etat.get("nb_au_dernier_lora", 0)
    if nouveaux_depuis_lora >= SEUIL_LORA:
        lancer_lora_si_pertinent(nouveaux_depuis_lora)
        etat["nb_au_dernier_lora"] = nb_total

    etat["nb_total"] = nb_total
    etat["last_run"] = time.time()
    sauver_etat(etat)
    return etat


# =============================================================================
# 7. MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true",
                        help="Une seule passe puis quitte")
    parser.add_argument("--intervalle", type=int, default=INTERVALLE_POLLING,
                        help="Secondes entre 2 checks (mode boucle)")
    args = parser.parse_args()

    log.info("Jarvis apprend de lui-meme — historique=%s", HISTORIQUE_PATH)
    if args.once:
        une_passe()
        return

    log.info("mode boucle, intervalle = %ds", args.intervalle)
    while True:
        try:
            une_passe()
        except KeyboardInterrupt:
            log.info("stop demande")
            break
        except Exception as exc:
            log.exception("erreur dans une_passe : %s", exc)
        time.sleep(args.intervalle)


if __name__ == "__main__":
    main()
