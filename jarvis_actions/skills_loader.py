"""Chargeur de skills auto-decouverts pour Jarvis.

Chaque skill est un fichier .py dans jarvis_skills/ (racine du repo, ou a
cote de l'exe en mode PyInstaller frozen) qui definit :
- SKILL = {"nom": str, "description": str, "version": str}
- executer(cmd: str) -> tuple[str | None, bool]            (sync)
  et/ou async_executer(cmd: str) -> tuple[str | None, bool] (async)

API publique :
- charger_skills(force_reload=False) : scanne et importe les skills
- lister_skills()                    : [{nom, description, fichier, active}]
- activer_skill(nom, enabled)        : active/desactive (persiste en JSON)
- executer_skills(cmd)               : essaie les skills sync, premier match
- async_executer_skills(cmd)         : pareil pour les skills async

Un skill qui plante (a l'import ou a l'execution) est loggue et ignore :
jamais de crash qui remonterait jusqu'a main2.py.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Iterator

_CONFIG_NOM = "skills_config.json"

# Registre des skills charges :
# {nom: {"nom", "description", "version", "fichier", "executer", "async_executer"}}
_SKILLS: dict[str, dict[str, Any]] = {}
_LOADED = False


# ============================================================
# Localisation du dossier jarvis_skills/
# ============================================================

def _dossier_skills() -> Path:
    """Localise le dossier jarvis_skills/ (mode dev ou PyInstaller frozen)."""
    if getattr(sys, "frozen", False):
        # .exe PyInstaller : dossier modifiable a cote de l'exe en priorite
        cote_exe = Path(sys.executable).parent / "jarvis_skills"
        if cote_exe.is_dir():
            return cote_exe
        # Repli : skills embarques dans le bundle (--add-data dans le .spec)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / "jarvis_skills"
        return cote_exe
    # En dev : skills_loader.py est dans jarvis_actions/, la racine est au-dessus
    return Path(__file__).resolve().parent.parent / "jarvis_skills"


# ============================================================
# Import + validation d'un fichier skill
# ============================================================

def _importer_skill(fichier: Path) -> tuple[str, dict[str, Any]] | None:
    """Importe un fichier skill et valide son contrat. None si invalide."""
    try:
        spec = importlib.util.spec_from_file_location(
            f"jarvis_skill_{fichier.stem}", fichier
        )
        if spec is None or spec.loader is None:
            print(f"[SKILLS] Spec d'import introuvable pour {fichier.name}")
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as e:
        print(f"[SKILLS] Echec import {fichier.name} : {e}")
        return None

    skill = getattr(module, "SKILL", None)
    if not isinstance(skill, dict) or not str(skill.get("nom", "")).strip():
        print(f"[SKILLS] {fichier.name} ignore : SKILL absent ou sans 'nom'")
        return None

    fn_sync = getattr(module, "executer", None)
    fn_async = getattr(module, "async_executer", None)
    if not callable(fn_sync) and not callable(fn_async):
        print(f"[SKILLS] {fichier.name} ignore : ni executer() ni async_executer()")
        return None

    nom = str(skill["nom"]).strip()
    return nom, {
        "nom": nom,
        "description": str(skill.get("description", "")),
        "version": str(skill.get("version", "0.0.0")),
        "fichier": fichier.name,
        "executer": fn_sync if callable(fn_sync) else None,
        "async_executer": fn_async if callable(fn_async) else None,
    }


def charger_skills(force_reload: bool = False) -> None:
    """Scanne jarvis_skills/*.py et charge les skills valides.

    Idempotent : ne recharge pas si deja fait, sauf force_reload=True.
    Les fichiers commencant par _ sont ignores. Ne leve jamais d'exception.
    """
    global _SKILLS, _LOADED
    if _LOADED and not force_reload:
        return

    dossier = _dossier_skills()
    nouveaux: dict[str, dict[str, Any]] = {}
    if not dossier.is_dir():
        print(f"[SKILLS] Dossier introuvable : {dossier} (aucun skill charge)")
        _SKILLS, _LOADED = nouveaux, True
        return

    try:
        fichiers = sorted(p for p in dossier.glob("*.py") if not p.name.startswith("_"))
    except Exception as e:
        print(f"[SKILLS] Echec du scan de {dossier} : {e}")
        _SKILLS, _LOADED = nouveaux, True
        return

    for fichier in fichiers:
        resultat = _importer_skill(fichier)
        if resultat is None:
            continue
        nom, entree = resultat
        if nom in nouveaux:
            print(
                f"[SKILLS] Doublon '{nom}' ({fichier.name}) ignore, "
                f"deja fourni par {nouveaux[nom]['fichier']}"
            )
            continue
        nouveaux[nom] = entree

    _SKILLS, _LOADED = nouveaux, True
    noms = ", ".join(sorted(nouveaux)) or "aucun"
    print(f"[SKILLS] {len(nouveaux)} skill(s) charge(s) : {noms}")


# ============================================================
# Config de (des)activation — jarvis_skills/skills_config.json
# ============================================================

def _chemin_config() -> Path:
    # En .exe, les skills peuvent venir du bundle (_MEIPASS, temporaire et efface
    # a la sortie) : on ecrit alors la config a COTE de l'exe pour qu'elle persiste
    # entre deux lancements. En dev, c'est le meme dossier que les skills.
    if getattr(sys, "frozen", False):
        cote_exe = Path(sys.executable).parent / "jarvis_skills"
        try:
            cote_exe.mkdir(parents=True, exist_ok=True)
            return cote_exe / _CONFIG_NOM
        except Exception:
            pass
    return _dossier_skills() / _CONFIG_NOM


def _lire_disabled() -> set[str]:
    """Lit l'ensemble des skills desactives depuis skills_config.json."""
    chemin = _chemin_config()
    try:
        if not chemin.is_file():
            return set()
        data = json.loads(chemin.read_text(encoding="utf-8"))
        disabled = data.get("disabled") if isinstance(data, dict) else None
        if isinstance(disabled, list):
            return {str(n) for n in disabled}
        return set()
    except Exception as e:
        print(f"[SKILLS] Config illisible ({chemin.name}) : {e}")
        return set()


def _ecrire_disabled(disabled: set[str]) -> bool:
    """Persiste {"disabled": [...]} de maniere atomique (.tmp puis os.replace)."""
    chemin = _chemin_config()
    tmp = chemin.parent / (chemin.name + ".tmp")
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        contenu = json.dumps({"disabled": sorted(disabled)}, ensure_ascii=False, indent=2)
        tmp.write_text(contenu, encoding="utf-8")
        os.replace(tmp, chemin)
        return True
    except Exception as e:
        print(f"[SKILLS] Echec ecriture config : {e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False


# ============================================================
# API publique : listing, activation, execution
# ============================================================

def lister_skills() -> list[dict[str, Any]]:
    """Retourne [{nom, description, fichier, active}] tries par nom."""
    charger_skills()
    disabled = _lire_disabled()
    return [
        {
            "nom": nom,
            "description": entree["description"],
            "fichier": entree["fichier"],
            "active": nom not in disabled,
        }
        for nom, entree in sorted(_SKILLS.items())
    ]


def activer_skill(nom: str, enabled: bool) -> bool:
    """Active ou desactive un skill par nom. Persiste dans skills_config.json.

    Retourne False si le skill est inconnu ou si l'ecriture echoue.
    """
    charger_skills()
    if nom not in _SKILLS:
        print(f"[SKILLS] Skill inconnu : '{nom}'")
        return False
    ancien = _lire_disabled()
    # Pas de mutation : on construit un nouvel ensemble
    nouveau = ancien - {nom} if enabled else ancien | {nom}
    if nouveau == ancien:
        return True  # deja dans l'etat demande
    return _ecrire_disabled(nouveau)


def _skills_actifs(cle_fn: str) -> Iterator[tuple[str, Callable[..., Any]]]:
    """Genere (nom, fonction) des skills actifs exposant cle_fn, ordre alphabetique."""
    disabled = _lire_disabled()
    for nom in sorted(_SKILLS):
        if nom in disabled:
            continue
        fn = _SKILLS[nom].get(cle_fn)
        if fn is not None:
            yield nom, fn


def _valider_retour(nom: str, resultat: Any) -> tuple[str | None, bool] | None:
    """Verifie que le skill a bien retourne (reponse, succes). None si invalide."""
    if (
        isinstance(resultat, tuple)
        and len(resultat) == 2
        and (resultat[0] is None or isinstance(resultat[0], str))
    ):
        return resultat[0], bool(resultat[1])
    print(f"[SKILLS] Retour invalide du skill '{nom}' : {resultat!r}")
    return None


def executer_skills(cmd: str) -> tuple[str | None, bool]:
    """Essaie chaque skill actif (sync) dans l'ordre alphabetique.

    Premier match (reponse non None) gagne, meme si succes=False.
    Retourne (None, False) si aucun skill ne reconnait la commande.
    Un skill qui leve une exception est loggue et ignore.
    """
    if not cmd or not cmd.strip():
        return None, False
    charger_skills()
    for nom, fn in _skills_actifs("executer"):
        try:
            resultat = _valider_retour(nom, fn(cmd))
        except Exception as e:
            print(f"[SKILLS] Skill '{nom}' a plante : {e}")
            continue
        if resultat is not None and resultat[0] is not None:
            return resultat
    return None, False


async def async_executer_skills(cmd: str) -> tuple[str | None, bool]:
    """Pareil que executer_skills() mais pour les skills async (async_executer)."""
    if not cmd or not cmd.strip():
        return None, False
    charger_skills()
    for nom, fn in _skills_actifs("async_executer"):
        try:
            resultat = _valider_retour(nom, await fn(cmd))
        except Exception as e:
            print(f"[SKILLS] Skill async '{nom}' a plante : {e}")
            continue
        if resultat is not None and resultat[0] is not None:
            return resultat
    return None, False
