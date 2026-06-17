"""Facade unique sur les dependances optionnelles (pyautogui / psutil / pyperclip).

But : un SEUL endroit importe ces libs et les expose via des wrappers qui ne
LEVENT jamais. C'est aussi le seul point a monkeypatcher dans les tests (au lieu
de mocker pyautogui partout). Boot headless/CI OK : si une lib manque, les
predicats `has_*` renvoient False et les capacites se degradent proprement.
"""

from __future__ import annotations

import os
import platform
from typing import Any

IS_WINDOWS = os.name == "nt"
IS_MAC = platform.system() == "Darwin"

try:
    import pyautogui  # type: ignore
except Exception:  # noqa: BLE001 - headless / pas de display
    pyautogui = None  # type: ignore

try:
    import psutil  # type: ignore
except Exception:  # noqa: BLE001
    psutil = None  # type: ignore

try:
    import pyperclip  # type: ignore
except Exception:  # noqa: BLE001
    pyperclip = None  # type: ignore


# ── Disponibilites ──
def has_pyautogui() -> bool:
    return pyautogui is not None


def has_psutil() -> bool:
    return psutil is not None


def has_pyperclip() -> bool:
    return pyperclip is not None


# ── Wrappers clavier / souris / capture (never-throw) ──
def press(touche: str, n: int = 1) -> bool:
    """Appuie n fois sur une touche. False si indisponible ou erreur."""
    if pyautogui is None:
        return False
    try:
        for _ in range(max(1, n)):
            pyautogui.press(touche)
        return True
    except Exception:  # noqa: BLE001
        return False


def hotkey(*touches: str) -> bool:
    if pyautogui is None:
        return False
    try:
        pyautogui.hotkey(*touches)
        return True
    except Exception:  # noqa: BLE001
        return False


def write(texte: str, interval: float = 0.02) -> bool:
    if pyautogui is None:
        return False
    try:
        pyautogui.write(texte, interval=interval)
        return True
    except Exception:  # noqa: BLE001
        return False


def screenshot(chemin: str) -> bool:
    if pyautogui is None:
        return False
    try:
        pyautogui.screenshot(chemin)
        return True
    except Exception:  # noqa: BLE001
        return False


# ── Presse-papier ──
def paste() -> str | None:
    """Contenu du presse-papier, ou None si indisponible/erreur."""
    if pyperclip is None:
        return None
    try:
        return pyperclip.paste() or ""
    except Exception:  # noqa: BLE001
        return None


# ── Accesseurs psutil (renvoient None si indispo, jamais d'exception) ──
def battery() -> Any | None:
    if psutil is None:
        return None
    try:
        return psutil.sensors_battery()
    except Exception:  # noqa: BLE001 - non implemente sur certaines plateformes
        return None


def cpu_percent(interval: float = 0.15) -> float | None:
    # interval court : limite le blocage du thread/loop appelant (contexte vocal).
    if psutil is None:
        return None
    try:
        return psutil.cpu_percent(interval=interval)
    except Exception:  # noqa: BLE001
        return None


def virtual_memory() -> Any | None:
    if psutil is None:
        return None
    try:
        return psutil.virtual_memory()
    except Exception:  # noqa: BLE001
        return None


def disk_usage(racine: str) -> Any | None:
    if psutil is None:
        return None
    try:
        return psutil.disk_usage(racine)
    except Exception:  # noqa: BLE001
        return None


def boot_time() -> float | None:
    if psutil is None:
        return None
    try:
        return psutil.boot_time()
    except Exception:  # noqa: BLE001
        return None


def process_iter(attrs: list[str]) -> list[dict] | None:
    """Liste de dicts {attr: valeur} pour les processus, ou None si indispo."""
    if psutil is None:
        return None
    try:
        return [p.info for p in psutil.process_iter(attrs)]
    except Exception:  # noqa: BLE001
        return None
