"""02_dspy_optimiser_prompt.py — optimiser automatiquement le system prompt de Jarvis.

Objectif : au lieu d'ecrire le prompt a la main et d'esperer que ce soit bon,
on laisse DSPy proposer plusieurs versions du prompt, les evaluer sur de vraies
conversations passees de Jarvis, et garder la meilleure.

C'est ca, le ML applique aux LLMs : tu ne touches PAS aux poids du modele,
tu optimises l'INPUT (le prompt) pour maximiser une metrique sur tes donnees.

Usage :
    pip install dspy-ai
    python apprendre/02_dspy_optimiser_prompt.py

Ce script suppose que tu as Ollama qui tourne (localhost:11434) avec qwen2.5:7b.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

# DSPy — framework d'optimisation declarative de prompts
import dspy


# =============================================================================
# 0. CONFIGURATION
# =============================================================================

ROOT = Path(__file__).parent.parent
HISTORIQUE_PATH = ROOT / "jarvis_historique.json"
PROMPT_OPTIMISE_PATH = Path(__file__).parent / "prompt_optimise.txt"

OLLAMA_URL = "http://localhost:11434"
MODELE = "qwen2.5:7b"


# =============================================================================
# 1. CHARGER LES DONNEES — tes conversations passees comme dataset d'optimisation
# =============================================================================

def charger_conversations() -> List[dspy.Example]:
    """Lit jarvis_historique.json et le convertit en exemples DSPy.

    Chaque exemple = (question_user, reponse_attendue).
    On garde seulement les paires propres (user puis assistant).
    """
    if not HISTORIQUE_PATH.exists():
        print(f"[data] Pas de jarvis_historique.json a {HISTORIQUE_PATH}")
        print("[data] Utilisation d'un mini dataset de demo a la place.")
        return _dataset_demo()

    raw = json.loads(HISTORIQUE_PATH.read_text(encoding="utf-8"))
    # jarvis_historique.json a un format custom — on l'adapte
    # En general : {"history": [{"role": "user|model", "text": "..."}, ...]}
    if isinstance(raw, dict):
        items = raw.get("history") or raw.get("messages") or []
    elif isinstance(raw, list):
        items = raw
    else:
        return _dataset_demo()

    examples: List[dspy.Example] = []
    pending_user = None
    for item in items:
        role = item.get("role", "")
        text = item.get("text") or item.get("content") or ""
        if not text:
            continue
        if role in ("user", "human"):
            pending_user = text
        elif role in ("model", "assistant") and pending_user is not None:
            ex = dspy.Example(question=pending_user, reponse_attendue=text)
            ex = ex.with_inputs("question")
            examples.append(ex)
            pending_user = None

    if len(examples) < 5:
        print(f"[data] Seulement {len(examples)} exemples reels, ajout du dataset demo.")
        examples += _dataset_demo()

    print(f"[data] {len(examples)} exemples (user, assistant) charges.")
    return examples


def _dataset_demo() -> List[dspy.Example]:
    """Mini dataset pour tester sans historique reel."""
    pairs = [
        ("Quelle heure il est ?", "Je n'ai pas l'heure systeme, mais demande-moi un timer si besoin."),
        ("Salut Jarvis, ca va ?", "Oui Monsieur, pret a coder. Sur quoi on bosse ?"),
        ("Donne-moi un exemple de fonction Python qui inverse une chaine.", "def inverser(s): return s[::-1]"),
        ("C'est quoi un decorateur en Python ?", "Une fonction qui en prend une autre et la wrap pour ajouter du comportement, sans modifier son code."),
        ("C'est quoi une list comprehension ?", "Une syntaxe concise pour construire une liste : [x*2 for x in range(5)]."),
        ("Allume la lumiere.", "(Je delegue a l'action Meross — pas une question pour moi.)"),
        ("Donne-moi un fait random sur le foot.", "Pele a marque son 1000e but le 19 novembre 1969."),
        ("Comment je debug un None type error ?", "Print la variable juste avant la ligne qui plante. Souvent c'est un .get() qui retourne None."),
    ]
    return [
        dspy.Example(question=q, reponse_attendue=r).with_inputs("question")
        for q, r in pairs
    ]


# =============================================================================
# 2. SIGNATURE — declaration de ce que le modele doit faire
# =============================================================================
#
# DSPy fonctionne par "signatures" : tu declares les inputs et outputs, et DSPy
# genere le prompt automatiquement (et l'optimise plus tard).

class JarvisSignature(dspy.Signature):
    """Tu es JARVIS, assistant dev personnel de Monsieur. Reponds en francais, concis,
    direct, sans phrase creuse. Pas de 'je suis ravi de t'aider'. Va a l'essentiel."""

    question: str = dspy.InputField(desc="Question ou commande de Monsieur")
    reponse: str = dspy.OutputField(desc="Reponse courte, francaise, utile")


class JarvisModule(dspy.Module):
    """Le 'programme' a optimiser : prend une question, renvoie une reponse."""

    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(JarvisSignature)

    def forward(self, question: str):
        return self.predict(question=question)


# =============================================================================
# 3. METRIQUE — comment mesurer la qualite d'une reponse
# =============================================================================
#
# DSPy a besoin d'un score 0..1 par exemple pour comparer les variantes du prompt.
# Ici on combine 3 criteres simples : francais, concis, pas de pollution.
# Pour un vrai projet, tu peux utiliser un LLM-juge (Gemini par exemple).

def metrique_jarvis(exemple, pred, trace=None) -> float:
    """Note la reponse predite. Retourne 0..1."""
    rep = (pred.reponse or "").strip().lower()
    if not rep:
        return 0.0

    score = 0.0

    # Critere 1 : reponse non vide (deja gere par check au-dessus)
    score += 0.2

    # Critere 2 : francais (heuristique simple : presence de mots francais courants)
    mots_fr = ("le", "la", "les", "un", "une", "tu", "je", "ne", "pas", "est", "et", "de", "que", "qui")
    if sum(1 for m in mots_fr if f" {m} " in f" {rep} ") >= 2:
        score += 0.2

    # Critere 3 : concis (max 200 chars pour une reponse normale)
    if len(rep) <= 200:
        score += 0.2
    elif len(rep) <= 400:
        score += 0.1

    # Critere 4 : pas de phrase creuse / sycophancy
    polluants = (
        "je suis ravi", "avec plaisir", "n'hesite pas", "je suis la pour",
        "i'm happy to", "as an ai", "en tant qu'ia",
    )
    if not any(p in rep for p in polluants):
        score += 0.2

    # Critere 5 : pas de balise/markdown excessif (le TTS deteste)
    if rep.count("**") < 2 and rep.count("```") < 1 and rep.count("#") < 3:
        score += 0.2

    return score


# =============================================================================
# 4. CONFIGURATION DSPy + OPTIMISATION
# =============================================================================

def main():
    # Configurer DSPy pour qu'il parle a Ollama local
    print(f"[init] connexion a {OLLAMA_URL} ({MODELE})")
    lm = dspy.LM(
        model=f"ollama_chat/{MODELE}",
        api_base=OLLAMA_URL,
        api_key="ollama",  # placeholder
    )
    dspy.configure(lm=lm)

    # Charger les donnees
    examples = charger_conversations()
    if len(examples) < 4:
        print("[err] trop peu d'exemples pour optimiser, abandon.")
        return

    # Split train / dev (DSPy a besoin des deux pour BootstrapFewShot)
    cut = max(2, int(len(examples) * 0.5))
    trainset, devset = examples[:cut], examples[cut:]
    print(f"[data] train={len(trainset)} dev={len(devset)}")

    # Module non optimise = baseline
    module = JarvisModule()

    print("\n[baseline] evaluation du module non-optimise sur le dev set")
    scores_avant = [metrique_jarvis(ex, module(question=ex.question)) for ex in devset]
    score_avant = sum(scores_avant) / len(scores_avant)
    print(f"[baseline] score moyen = {score_avant:.3f}")

    # Optimiseur : BootstrapFewShot essaie d'inserer des "demonstrations"
    # (paires question/reponse exemplaires) dans le prompt pour guider le modele.
    print("\n[optim] lancement de BootstrapFewShot")
    from dspy.teleprompt import BootstrapFewShot

    optimiseur = BootstrapFewShot(metric=metrique_jarvis, max_bootstrapped_demos=4)
    module_optim = optimiseur.compile(module, trainset=trainset)

    # Evaluation post-optim
    print("\n[optim] evaluation du module optimise sur le dev set")
    scores_apres = [metrique_jarvis(ex, module_optim(question=ex.question)) for ex in devset]
    score_apres = sum(scores_apres) / len(scores_apres)
    print(f"[optim] score moyen = {score_apres:.3f}")
    print(f"[optim] amelioration : {score_apres - score_avant:+.3f}")

    # Sauver le programme optimise (les demos selectionnees + la signature)
    PROMPT_OPTIMISE_PATH.write_text(
        f"# Module DSPy optimise pour Jarvis\n"
        f"# Score baseline : {score_avant:.3f}\n"
        f"# Score optimise : {score_apres:.3f}\n\n"
        f"## Signature\n{JarvisSignature.__doc__}\n\n"
        f"## Demos selectionnees (a integrer en few-shot dans le prompt)\n\n"
        + _format_demos(module_optim),
        encoding="utf-8",
    )
    print(f"\n[save] {PROMPT_OPTIMISE_PATH}")
    print(
        "\n[next step] tu peux integrer ces demos dans _prompt_ollama_systeme()\n"
        "de main2.py sous forme d'exemples 'Q:/R:' avant les regles, ou utiliser\n"
        "directement DSPy en runtime via dspy.configure() + JarvisModule.\n"
    )


def _format_demos(module) -> str:
    """Extrait les demos generees par BootstrapFewShot pour les afficher."""
    out = []
    for name, predictor in module.named_predictors():
        demos = getattr(predictor, "demos", []) or []
        out.append(f"### {name} ({len(demos)} demos)\n")
        for i, d in enumerate(demos, 1):
            q = getattr(d, "question", "?")
            r = getattr(d, "reponse", "?")
            out.append(f"Demo {i}\nQ: {q}\nR: {r}\n")
    return "\n".join(out)


if __name__ == "__main__":
    main()
