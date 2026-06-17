"""Capacites entrees/sorties : media, volume, presse-papier, ecran.

Quatre capacites migrees depuis `pc_actions.py` (media/volume/screen/type) et
`system_actions.py` (vol_* + clipboard_read). Toutes passent par les wrappers
`deps` (jamais pyautogui/psutil en direct) et renvoient TOUJOURS un ActionResult.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from jarvis_config import USER_NAME

from ..core import (
    ActionResult,
    DOM_CLIPBOARD,
    DOM_MEDIA,
    DOM_SCREEN,
    DOM_VOLUME,
    Intention,
)
from .. import deps
from .base import Capability, never_throw

# Message commun quand le clavier (pyautogui) n'est pas disponible.
_KBD_INDISPO = "Le controle clavier n'est pas disponible sur cet environnement."
_APERCU_MAX = 300  # troncature de l'apercu du presse-papier


# ============================================================
# 1) MEDIA — play/pause/next/prev (touches multimedia)
# ============================================================

# Action -> (touche multimedia, message vocal court).
_MEDIA_TOUCHES = {
    "play": ("playpause", "C'est reparti."),
    "pause": ("playpause", "Pause."),
    "next": ("nexttrack", "Piste suivante."),
    "prev": ("prevtrack", "Piste precedente."),
}


class MediaController(Capability):
    """Lecture media via les touches multimedia du clavier."""

    domain = DOM_MEDIA

    def available(self) -> bool:
        return deps.has_pyautogui()

    @never_throw
    def handle(self, intent: Intention) -> ActionResult:
        entree = _MEDIA_TOUCHES.get(intent.action)
        if entree is None:
            return ActionResult.unhandled()
        touche, message = entree
        if deps.press(touche):
            return ActionResult.ok(message)
        return ActionResult.fail(_KBD_INDISPO)


# ============================================================
# 2) VOLUME — up/down/mute/max/min/set
# ============================================================

_VOLUME_INDISPO = "Le controle du volume n'est pas disponible ici."

# Action simple -> (touche, nombre de pas, message). up/down par pas de 5,
# max/min forcent l'extreme (50 pas de +/-2% garantissent le plafond/plancher).
_VOLUME_PAS = {
    "up": ("volumeup", 5, "Volume augmente."),
    "down": ("volumedown", 5, "Volume baisse."),
    "mute": ("volumemute", 1, "Son coupe."),
    "max": ("volumeup", 50, f"Volume au maximum, {USER_NAME}."),
    "min": ("volumedown", 50, f"Volume au minimum, {USER_NAME}."),
}


class VolumeController(Capability):
    """Reglage du volume systeme via les touches volume du clavier."""

    domain = DOM_VOLUME

    def available(self) -> bool:
        return deps.has_pyautogui()

    @never_throw
    def handle(self, intent: Intention) -> ActionResult:
        if intent.action == "set":
            return self._set(intent.args.get("level"))
        entree = _VOLUME_PAS.get(intent.action)
        if entree is None:
            return ActionResult.unhandled()
        touche, n, message = entree
        if deps.press(touche, n):
            return ActionResult.ok(message)
        return ActionResult.fail(_VOLUME_INDISPO)

    def _set(self, brut: str | None) -> ActionResult:
        """Regle le volume a ~level%. Force a 0 puis remonte par pas de 2%."""
        try:
            pct = max(0, min(100, int(brut)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return ActionResult.fail("Je n'ai pas compris le niveau de volume.")
        if not deps.press("volumedown", 50):
            return ActionResult.fail(_VOLUME_INDISPO)
        deps.press("volumeup", round(pct / 2))
        return ActionResult.ok(f"Volume regle a environ {pct} pour cent, {USER_NAME}.")


# ============================================================
# 3) CLIPBOARD — read/copy/paste
# ============================================================

def _clipboard_via_subprocess() -> str | None:
    """Repli de lecture du presse-papier sans pyperclip (Windows/mac)."""
    if deps.IS_WINDOWS:
        cmd = ["powershell", "-NoProfile", "-Command", "Get-Clipboard"]
    elif deps.IS_MAC:
        cmd = ["pbpaste"]
    else:
        return None
    try:
        r = subprocess.run(cmd, check=False, shell=False,
                           capture_output=True, text=True)
        return r.stdout
    except Exception:  # noqa: BLE001 - outil absent / erreur OS
        return None


class ClipboardManager(Capability):
    """Lecture et copier/coller du presse-papier."""

    domain = DOM_CLIPBOARD

    def available(self) -> bool:
        # read fonctionne toujours (repli subprocess) ; copy/paste verifies au handle.
        return True

    @never_throw
    def handle(self, intent: Intention) -> ActionResult:
        if intent.action == "read":
            return self._read()
        mod = "command" if deps.IS_MAC else "ctrl"
        if intent.action == "copy":
            return self._hotkey(mod, "c", "Copie.")
        if intent.action == "paste":
            return self._hotkey(mod, "v", "Colle.")
        return ActionResult.unhandled()

    def _read(self) -> ActionResult:
        contenu = deps.paste()
        if contenu is None:
            contenu = _clipboard_via_subprocess()
        if contenu is None:
            return ActionResult.fail(
                "Je ne peux pas lire le presse-papier sur cet environnement."
            )
        contenu = contenu.strip()
        if not contenu:
            return ActionResult.ok(f"Le presse-papier est vide, {USER_NAME}.")
        apercu = contenu if len(contenu) <= _APERCU_MAX else contenu[:_APERCU_MAX] + "..."
        return ActionResult.ok(f"Presse-papier : {apercu}")

    def _hotkey(self, *args: str) -> ActionResult:
        *touches, message = args
        if deps.hotkey(*touches):
            return ActionResult.ok(message)
        return ActionResult.fail(_KBD_INDISPO)


# ============================================================
# 4) SCREEN — screenshot, type_text, raccourcis clavier
# ============================================================

# Action -> (touches hotkey, message vocal court).
_SCREEN_HOTKEYS = {
    "new_tab": (("ctrl", "t"), "Nouvel onglet."),
    "reopen_tab": (("ctrl", "shift", "t"), "J'ai rouvert le dernier onglet."),
    "close_tab": (("ctrl", "w"), "Onglet ferme."),
    "refresh": (("f5",), "Page actualisee."),
    "fullscreen": (("f11",), "Plein ecran."),
    "zoom_in": (("ctrl", "="), "Zoom avant."),
    "zoom_out": (("ctrl", "-"), "Zoom arriere."),
    "zoom_reset": (("ctrl", "0"), "Zoom reinitialise."),
    "find": (("ctrl", "f"), "Recherche dans la page."),
}


class ScreenManager(Capability):
    """Capture d'ecran, saisie de texte et raccourcis clavier navigateur/edition."""

    domain = DOM_SCREEN

    def available(self) -> bool:
        return deps.has_pyautogui()

    @never_throw
    def handle(self, intent: Intention) -> ActionResult:
        if intent.action == "screenshot":
            return self._screenshot()
        if intent.action == "type_text":
            return self._type(intent.args.get("text", ""))
        entree = _SCREEN_HOTKEYS.get(intent.action)
        if entree is None:
            return ActionResult.unhandled()
        touches, message = entree
        if deps.hotkey(*touches):
            return ActionResult.ok(message)
        return ActionResult.fail("Ce raccourci n'est pas disponible sur cet environnement.")

    def _screenshot(self) -> ActionResult:
        dossier = Path.home() / "Pictures" / "Jarvis"
        dossier.mkdir(parents=True, exist_ok=True)
        nom = f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        chemin = dossier / nom
        if deps.screenshot(str(chemin)):
            return ActionResult.ok(f"Capture sauvegardee : {chemin}")
        return ActionResult.fail("La capture d'ecran n'est pas disponible ici.")

    def _type(self, texte: str) -> ActionResult:
        if not texte:
            return ActionResult.fail("Je n'ai rien a taper.")
        if deps.write(texte):
            return ActionResult.ok(f"Je tape: {texte}")
        return ActionResult.fail(_KBD_INDISPO)
