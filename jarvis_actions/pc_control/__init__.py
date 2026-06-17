"""Controle PC profond de Jarvis — package propre, par domaines.

Remplace pc_actions + system_actions par une architecture testable :
- `router.py`  : texte -> Intention (PUR, 100% testable).
- `capabilities/` : une classe par domaine (power, window, process, sysinfo,
  media, volume, clipboard, screen, launcher, settings, files).
- `controller.py` : assemble routeur + capacites.

Facade publique pour main2 :
- `executer(texte) -> (str|None, bool)` : contrat identique aux anciens modules
  (None = non gere ici, la chaine continue vers l'IA).
- `controller_par_defaut()` : le Controller singleton (pour acceder a une capacite,
  ex. `.capabilities['launcher'].bring_to_front(...)`).

Rollback : `JARVIS_PC_LEGACY=1` -> `executer` renvoie toujours (None, False), main2
retombe sur les anciens modules.
"""

from __future__ import annotations

import os

from .capabilities import default_capabilities
from .controller import Controller
from .core import (
    ActionResult,
    Intention,
    Runner,
    SafetyPolicy,
    Status,
)
from .router import Router

__all__ = [
    "executer", "controller_par_defaut",
    "ActionResult", "Status", "Intention", "Controller", "Router", "SafetyPolicy",
]

_singleton: Controller | None = None


def controller_par_defaut() -> Controller:
    """Le Controller par defaut (lazy singleton) : Runner reel + SafetyPolicy.from_env."""
    global _singleton
    if _singleton is None:
        runner = Runner()
        policy = SafetyPolicy.from_env()
        caps = default_capabilities(runner, policy)
        _singleton = Controller(Router(), caps)
    return _singleton


def executer(texte: str) -> tuple[str | None, bool]:
    """Execute une commande de controle PC. (reponse, succes) ou (None, False)."""
    if os.environ.get("JARVIS_PC_LEGACY") == "1":
        return None, False
    return controller_par_defaut().executer(texte)
