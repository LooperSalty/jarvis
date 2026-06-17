"""Socle des capacites : l'ABC `Capability` et le decorateur `never_throw`.

Chaque capacite gere UN domaine (power, window, sysinfo...). Elle expose :
- `domain` : le domaine qu'elle gere (clef de routage) ;
- `available()` : True si ses dependances sont la (sinon le controleur degrade) ;
- `handle(intent)` : execute l'action, renvoie TOUJOURS un `ActionResult`.

`never_throw` garantit qu'aucun handler ne fait remonter d'exception : la 1re
barriere de fiabilite (la 2e est le try/except global du Controller).
"""

from __future__ import annotations

import functools
from abc import ABC, abstractmethod
from typing import Callable

from jarvis_config import USER_NAME

from ..core import ActionResult, Intention, get_logger


class Capability(ABC):
    """Une capacite de controle PC pour un domaine donne."""

    #: domaine gere (constante DOM_* de core.py). A definir par la sous-classe.
    domain: str = ""

    def available(self) -> bool:
        """True si la capacite peut s'executer ici (deps presentes). Defaut True."""
        return True

    @abstractmethod
    def handle(self, intent: Intention) -> ActionResult:
        """Execute l'action de `intent`. Ne LEVE jamais (cf. @never_throw)."""
        raise NotImplementedError


def never_throw(fn: Callable[..., ActionResult]) -> Callable[..., ActionResult]:
    """Decorateur : attrape toute exception d'un handler, la logge et renvoie un
    `ActionResult.fail` propre (jamais d'echec silencieux ni de crash)."""

    @functools.wraps(fn)
    def wrapper(self: Capability, intent: Intention, *args, **kwargs) -> ActionResult:
        try:
            return fn(self, intent, *args, **kwargs)
        except Exception:  # noqa: BLE001 - barriere de fiabilite voulue
            get_logger().exception(
                "[PCCTL] %s.handle a leve sur %s/%s",
                type(self).__name__, intent.domaine, intent.action,
            )
            return ActionResult.fail(
                f"Une erreur interne m'a empeche de faire ca, {USER_NAME}."
            )

    return wrapper
