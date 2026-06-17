"""Capacites de controle PC (une classe Capability par domaine) + factory.

`default_capabilities` instancie toutes les capacites et les indexe par domaine
(la clef de routage du Controller). Injecte le Runner et la SafetyPolicy partout
ou ils sont necessaires (power/process/settings/launcher).
"""

from __future__ import annotations

from ..core import Runner, SafetyPolicy
from .apps import AppLauncher
from .base import Capability, never_throw
from .io import ClipboardManager, MediaController, ScreenManager, VolumeController
from .system import (
    FileManager,
    PowerManager,
    ProcessManager,
    SettingsPanel,
    SystemInfo,
    WindowManager,
)

__all__ = [
    "Capability", "never_throw", "default_capabilities",
    "PowerManager", "WindowManager", "ProcessManager", "SystemInfo",
    "SettingsPanel", "FileManager", "MediaController", "VolumeController",
    "ClipboardManager", "ScreenManager", "AppLauncher",
]


def default_capabilities(runner: Runner, policy: SafetyPolicy) -> dict[str, Capability]:
    """Toutes les capacites, indexees par domaine."""
    caps: list[Capability] = [
        PowerManager(runner, policy),
        WindowManager(),
        ProcessManager(runner, policy),
        SystemInfo(),
        SettingsPanel(runner),
        FileManager(),
        MediaController(),
        VolumeController(),
        ClipboardManager(),
        ScreenManager(),
        AppLauncher(runner),
    ]
    return {cap.domain: cap for cap in caps}
