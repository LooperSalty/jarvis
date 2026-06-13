"""Configuration UI persistante de Jarvis : apparence + Cowork.

Lu/ecrit a cote de l'exe en mode PyInstaller (meme pattern _dossier_donnees que
jarvis_profile, sinon racine du repo). Fichier gitignore (jarvis_ui_config.json),
modele versionne jarvis_ui_config_example.json.

Champs :
  theme         : id du theme du dashboard (cle de THEMES) ou "custom"
  accent        : couleur d'accent du dashboard "#rrggbb" (utilisee si theme=custom)
  orb_style     : id de la palette de l'orbe (cle de ORB_STYLES) ou "custom"
  orb_color     : couleur de base de l'orbe "#rrggbb" (utilisee si orb_style=custom)
  cowork_folder : chemin absolu du dossier de travail Cowork ("" si non defini)

Toutes les valeurs sont VALIDEES a la lecture comme a l'ecriture (liste blanche
pour les ids, regex pour les couleurs, existence pour le dossier) : aucune
donnee non fiable n'est jamais renvoyee au frontend ni reinjectee dans le .exe.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any


def _dossier_donnees() -> Path:
    """A cote de l'exe en mode frozen (persistance), sinon racine du repo."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


CONFIG_PATH: Path = _dossier_donnees() / "jarvis_ui_config.json"

# Listes blanches : tout id hors de ces tuples retombe sur le defaut.
THEMES: tuple[str, ...] = ("cyan", "violet", "emeraude", "ambre", "rose", "rouge", "custom")
ORB_STYLES: tuple[str, ...] = ("classique", "ironman", "nebuleuse", "emeraude", "givre", "custom")

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

DEFAUTS: dict[str, Any] = {
    "theme": "cyan",
    "accent": "#4be1ff",
    "orb_style": "classique",
    "orb_color": "#4ca8e8",
    "cowork_folder": "",
}


def _hex_valide(valeur: Any, defaut: str) -> str:
    """Couleur '#rrggbb' valide, sinon le defaut."""
    v = str(valeur or "").strip()
    return v if _HEX_RE.match(v) else defaut


def _choix_valide(valeur: Any, choix: tuple[str, ...], defaut: str) -> str:
    """Id present dans la liste blanche (casse ignoree), sinon le defaut."""
    v = str(valeur or "").strip().lower()
    return v if v in choix else defaut


def _dossier_valide(valeur: Any) -> str:
    """Chemin de dossier EXISTANT (str absolu), sinon "". Jamais d'exception.

    Un chemin inexistant ou illisible est rejete : le frontend affichera le
    dossier comme non defini plutot que de pointer vers un emplacement fantome.
    """
    chemin = str(valeur or "").strip().strip('"').strip("'")
    if not chemin:
        return ""
    try:
        p = Path(chemin).expanduser()
        if p.is_dir():
            return str(p.resolve())
    except Exception:
        pass
    return ""


def _normaliser(brut: Any) -> dict[str, Any]:
    """Construit une config complete et VALIDE a partir d'un dict potentiellement
    partiel ou corrompu (chaque champ retombe sur son defaut si invalide)."""
    src = brut if isinstance(brut, dict) else {}
    return {
        "theme": _choix_valide(src.get("theme"), THEMES, DEFAUTS["theme"]),
        "accent": _hex_valide(src.get("accent"), DEFAUTS["accent"]),
        "orb_style": _choix_valide(src.get("orb_style"), ORB_STYLES, DEFAUTS["orb_style"]),
        "orb_color": _hex_valide(src.get("orb_color"), DEFAUTS["orb_color"]),
        "cowork_folder": _dossier_valide(src.get("cowork_folder")),
    }


def charger() -> dict[str, Any]:
    """Config UI complete et validee (defauts si fichier absent/illisible)."""
    if not CONFIG_PATH.exists():
        return dict(DEFAUTS)
    try:
        brut = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[UI-CONFIG] Lecture {CONFIG_PATH.name} echouee : {e}")
        return dict(DEFAUTS)
    return _normaliser(brut)


def sauvegarder(updates: Any) -> dict[str, Any]:
    """Fusionne un dict PARTIEL `updates` avec la config existante, valide et
    ecrit atomiquement (.tmp + os.replace). Retourne la config complete
    resultante. Ne leve jamais : un echec d'ecriture est logge, la config
    validee est tout de meme renvoyee (etat memoire coherent)."""
    courant = charger()
    if isinstance(updates, dict):
        # Immutabilite : on construit un nouveau dict, on ne mute pas l'entree.
        courant = {**courant, **{k: v for k, v in updates.items() if k in DEFAUTS}}
    config = _normaliser(courant)
    try:
        tmp = CONFIG_PATH.with_name(CONFIG_PATH.name + ".tmp")
        tmp.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, CONFIG_PATH)
    except Exception as e:
        print(f"[UI-CONFIG] Ecriture {CONFIG_PATH.name} echouee : {e}")
    return config


if __name__ == "__main__":
    print(json.dumps(charger(), indent=2, ensure_ascii=False))
