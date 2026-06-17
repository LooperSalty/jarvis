"""Primitives partagees du package pc_control (toutes PURES, sans dependance OS).

- `Status` / `ActionResult` : resultat structure d'une action, converti en
  `(str|None, bool)` pour main2 via `to_legacy()`.
- `Intention` : ce que le routeur produit (domaine + action + arguments).
- `SafetyPolicy` : garde-fous configurables (extinction, kill) lus depuis l'env.
- `get_logger` / `Runner` : tracabilite + execution subprocess INJECTABLE
  (rend les actions power/process testables sans toucher l'OS).

Immutabilite (CLAUDE.md) : `ActionResult`, `Intention`, `SafetyPolicy` sont
`frozen=True`. Les constructeurs renvoient toujours un NOUVEL objet.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

# ── Domaines d'intention (constantes partagees routeur <-> capacites) ──
DOM_POWER = "power"
DOM_WINDOW = "window"
DOM_PROCESS = "process"
DOM_SYSINFO = "sysinfo"
DOM_MEDIA = "media"
DOM_VOLUME = "volume"
DOM_CLIPBOARD = "clipboard"
DOM_SCREEN = "screen"
DOM_LAUNCHER = "launcher"
DOM_SETTINGS = "settings"
DOM_FILES = "files"


class Status(str, Enum):
    """Issue d'une action. `UNHANDLED` = ce n'etait pas pour nous (laisser l'IA)."""

    UNHANDLED = "unhandled"  # pas reconnu ici -> la chaine continue vers l'IA
    OK = "ok"               # action prise avec succes
    FAILED = "failed"       # reconnue mais echouee (dep absente / OS / erreur)
    REFUSED = "refused"     # bloquee par un garde-fou de securite


@dataclass(frozen=True)
class ActionResult:
    """Resultat structure d'une action. Immuable."""

    status: Status
    message: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)

    @staticmethod
    def unhandled() -> "ActionResult":
        return ActionResult(Status.UNHANDLED, None)

    @staticmethod
    def ok(message: str, **data: Any) -> "ActionResult":
        return ActionResult(Status.OK, message, dict(data))

    @staticmethod
    def fail(message: str, **data: Any) -> "ActionResult":
        return ActionResult(Status.FAILED, message, dict(data))

    @staticmethod
    def refused(message: str, **data: Any) -> "ActionResult":
        return ActionResult(Status.REFUSED, message, dict(data))

    @property
    def is_handled(self) -> bool:
        return self.status is not Status.UNHANDLED

    def to_legacy(self) -> tuple[str | None, bool]:
        """Convertit au contrat main2 `(reponse, succes)`.

        UNHANDLED -> (None, False) : la chaine continue vers l'IA.
        OK        -> (message, True).
        FAILED/REFUSED -> (message, False) : vocalise l'echec ET stoppe la chaine
        (semantique de system_actions, la plus informative).
        """
        if self.status is Status.UNHANDLED:
            return None, False
        return self.message, self.status is Status.OK


@dataclass(frozen=True)
class Intention:
    """Sortie du routeur : quoi faire (pas comment). Immuable."""

    domaine: str
    action: str
    args: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SafetyPolicy:
    """Garde-fous configurables. Defauts surs (tout autorise, delai d'arret 30s)."""

    allow_power: bool = True
    allow_kill: bool = True
    shutdown_delay_s: int = 30

    @staticmethod
    def from_env() -> "SafetyPolicy":
        return SafetyPolicy(
            allow_power=_env_bool("JARVIS_PC_ALLOW_POWER", True),
            allow_kill=_env_bool("JARVIS_PC_ALLOW_KILL", True),
            shutdown_delay_s=_env_int("JARVIS_PC_SHUTDOWN_DELAY", 30),
        )


def _env_bool(nom: str, defaut: bool) -> bool:
    brut = os.environ.get(nom)
    if brut is None:
        return defaut
    return brut.strip().lower() not in ("0", "false", "no", "non", "off", "")


def _env_int(nom: str, defaut: int) -> int:
    try:
        return int(os.environ.get(nom, defaut))
    except (TypeError, ValueError):
        return defaut


# ── Tracabilite ──
def get_logger() -> logging.Logger:
    """Logger dedie 'jarvis.pc_control' (prefixe [PCCTL] cote handlers)."""
    return logging.getLogger("jarvis.pc_control")


# ── Execution subprocess INJECTABLE (testable sans OS) ──
@dataclass(frozen=True)
class Runner:
    """Enveloppe `subprocess.run` (shell=False impose). Injectable -> les actions
    power/process se testent en passant un faux Runner qui capture l'argv."""

    def run(self, args: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess:
        kwargs.setdefault("check", False)
        kwargs.setdefault("shell", False)  # NE JAMAIS passer a True (injection).
        return subprocess.run(list(args), **kwargs)
