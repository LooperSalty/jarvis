"""Profil personnel de l'utilisateur, injecte dans le prompt systeme de Jarvis.

Stocke des informations personnelles (famille, adresse, habitudes, gouts...)
dans jarvis_profil.json — GITIGNORE, jamais committe, comme jarvis_memoire.json.
Edite via la page Parametres de l'interface (onglet Profil).

But : que Jarvis "connaisse" son utilisateur et personnalise ses reponses, a la
maniere d'un profil de personnalisation (comme la description de soi sur Claude).
"""

from __future__ import annotations

import json
from pathlib import Path

try:
    from jarvis_config import USER_NAME
except Exception:  # pragma: no cover - repli si import casse
    USER_NAME = "Monsieur"

PROFIL_FILE = Path(__file__).parent / "jarvis_profil.json"

# Champs reconnus, dans l'ordre d'affichage.
# (cle, libelle UI, placeholder, multiligne)
CHAMPS_PROFIL: list[tuple[str, str, str, bool]] = [
    ("nom",          "Nom / comment t'appeler",   "Ex : Paul, Monsieur Stark...",                      False),
    ("famille",      "Famille & proches",         "Ex : conjoint Marie, fille Lea (8 ans), chien Rex", True),
    ("adresse",      "Adresse / localisation",    "Ex : Lyon, France",                                  False),
    ("travail",      "Travail & etudes",          "Ex : developpeur, etudiant en ecole d'ingenieur",   False),
    ("habitudes",    "Habitudes & routines",      "Ex : reveil 7h, sport le soir, cafe sans sucre",    True),
    ("gouts",        "Gouts & preferences",       "Ex : aime la SF, deteste le bruit, supporte l'OL",  True),
    ("sante",        "Sante & contraintes",       "Ex : allergie arachides, vegetarien",                False),
    ("objectifs",    "Objectifs du moment",       "Ex : apprendre l'espagnol, finir mon projet Jarvis", True),
    ("a_propos",     "A propos de moi (libre)",   "Tout ce que Jarvis devrait savoir sur toi",          True),
    ("instructions", "Instructions pour Jarvis",  "Ex : tutoie-moi, reponses courtes, humour sec",      True),
]

_CLES = {c[0] for c in CHAMPS_PROFIL}
_LABELS = {c[0]: c[1] for c in CHAMPS_PROFIL}


def charger_profil() -> dict:
    """Charge jarvis_profil.json. Retourne {} si absent ou illisible."""
    try:
        if PROFIL_FILE.exists():
            data = json.loads(PROFIL_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as e:
        print(f"[PROFIL] Lecture echouee : {e}")
    return {}


def sauvegarder_profil(data: dict) -> dict:
    """Ne conserve que les cles connues, valeurs texte strippees, non vides.
    Retourne le profil reellement enregistre."""
    propre: dict[str, str] = {}
    if isinstance(data, dict):
        for cle in _CLES:
            val = data.get(cle, "")
            if not isinstance(val, str):
                val = str(val)
            val = val.strip()
            if val:
                propre[cle] = val
    try:
        PROFIL_FILE.write_text(
            json.dumps(propre, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"[PROFIL] Sauvegarde echouee : {e}")
    return propre


def profil_pour_ui() -> dict:
    """Structure consommee par la page Parametres :
    {"champs": [{cle, label, hint, multiligne, valeur}, ...], "rempli": bool}."""
    data = charger_profil()
    champs = [
        {
            "cle": cle,
            "label": label,
            "hint": hint,
            "multiligne": multiligne,
            "valeur": data.get(cle, ""),
        }
        for (cle, label, hint, multiligne) in CHAMPS_PROFIL
    ]
    return {"champs": champs, "rempli": bool(data)}


def construire_contexte_profil() -> str:
    """Bloc texte injecte dans le prompt systeme. Vide si aucun champ rempli."""
    data = charger_profil()
    if not data:
        return ""
    lignes = [
        f"PROFIL DE {USER_NAME} (informations personnelles a connaitre et "
        "utiliser naturellement, sans les reciter) :"
    ]
    for cle, label, _hint, _multi in CHAMPS_PROFIL:
        val = data.get(cle)
        if val:
            lignes.append(f"  - {label} : {val}")
    return "\n".join(lignes)
