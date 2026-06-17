"""Capacite LAUNCHER : ouvrir une app ou un site web par son nom.

Migration fidele de `pc_actions._ouvrir_app` + `_bring_to_front` (et des dicts
`_APP_ALIASES` / `_WEB_SHORTCUTS`). Ordre de resolution : raccourcis WEB AVANT
les apps, puis repli .lnk (Start Menu) -> PATH -> URL/chemin.

PIEGE COMPAT : si rien ne matche, on renvoie `ActionResult.unhandled()` (et NON
`.fail`) pour reproduire l'ancien `if rep and ok` qui laissait filer la commande
vers l'IA. On ne vocalise donc PAS d'echec quand l'app est introuvable.
"""

from __future__ import annotations

import os
import subprocess
import time
import webbrowser
from pathlib import Path
from shutil import which

from jarvis_config import USER_NAME

from .. import deps
from ..core import DOM_LAUNCHER, ActionResult, Intention, get_logger
from .base import Capability, never_throw

# ── Tables de resolution (migrees telles quelles de pc_actions) ──
_APP_ALIASES = {
    "chrome": ["chrome.exe", "google chrome", "Google Chrome"],
    "firefox": ["firefox.exe", "Firefox"],
    "edge": ["msedge.exe", "microsoft-edge:", "Microsoft Edge"],
    "vscode": ["code.cmd", "code", "Visual Studio Code"],
    "vs code": ["code.cmd", "code", "Visual Studio Code"],
    "discord": ["Discord.exe", "discord", "Discord"],
    "spotify": ["Spotify.exe", "spotify:", "Spotify"],
    "steam": ["steam.exe", "steam:", "Steam"],
    "obsidian": ["Obsidian.exe", "obsidian", "Obsidian"],
    "notepad": ["notepad.exe"],
    "bloc-notes": ["notepad.exe"],
    "calculatrice": ["calc.exe"],
    "calc": ["calc.exe"],
    "explorateur": ["explorer.exe"],
    "explorer": ["explorer.exe"],
    "fichiers": ["explorer.exe"],
    "terminal": ["wt.exe", "powershell.exe"],
    "powershell": ["powershell.exe"],
    "cmd": ["cmd.exe"],
    "task manager": ["taskmgr.exe"],
    "gestionnaire de taches": ["taskmgr.exe"],
    "gestionnaire": ["taskmgr.exe"],
    "paint": ["mspaint.exe"],
}

# Sites webs ouverts dans le navigateur par defaut — priorite haute.
_WEB_SHORTCUTS = {
    "google maps": "https://www.google.com/maps",
    "google map": "https://www.google.com/maps",
    "maps": "https://www.google.com/maps",
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "drive": "https://drive.google.com",
    "google drive": "https://drive.google.com",
    "calendrier": "https://calendar.google.com",
    "google calendar": "https://calendar.google.com",
    "github": "https://github.com",
    "claude": "https://claude.ai",
    "chatgpt": "https://chat.openai.com",
    "twitter": "https://twitter.com",
    "x": "https://twitter.com",
    "linkedin": "https://www.linkedin.com",
    "stackoverflow": "https://stackoverflow.com",
    "stack overflow": "https://stackoverflow.com",
    "reddit": "https://www.reddit.com",
    "amazon": "https://www.amazon.fr",
    "wikipedia": "https://fr.wikipedia.org",
    "deepl": "https://www.deepl.com/translator",
    "traducteur": "https://www.deepl.com/translator",
    "leboncoin": "https://www.leboncoin.fr",
    "twitch": "https://www.twitch.tv",
    "netflix": "https://www.netflix.com",
    "instagram": "https://www.instagram.com",
}

_START_MENU_DIRS = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
]


class AppLauncher(Capability):
    """Ouvre apps Windows + raccourcis web. Toujours dispo (pas de dep clavier)."""

    domain = DOM_LAUNCHER

    def __init__(self, runner=None) -> None:
        # Runner injecte pour les Popen testables (shell=False impose).
        self._runner = runner

    def available(self) -> bool:
        # Le launcher fonctionne meme sans pyautogui (subprocess/startfile).
        return True

    @never_throw
    def handle(self, intent: Intention) -> ActionResult:
        if intent.action != "open_app":
            return ActionResult.unhandled()
        nom = (intent.args.get("name") or "").strip()
        return self._ouvrir_app(nom)

    # ── Cœur : resolution multi-niveaux (web -> alias -> lnk -> PATH -> url) ──
    def _ouvrir_app(self, nom: str) -> ActionResult:
        nom_clean = nom.strip().lower()
        if not nom_clean:
            return ActionResult.unhandled()
        # ANTI-INJECTION : un nom commencant par '-' serait pris pour une option.
        if nom_clean.startswith("-"):
            return ActionResult.refused(
                f"Je ne peux pas ouvrir '{nom}' : nom invalide, {USER_NAME}."
            )

        # 0. Sites webs (priorite haute) — webbrowser.open.
        web = self._essayer_web(nom_clean)
        if web is not None:
            return web

        # 1. Alias d'app connus.
        for alias, cands in _APP_ALIASES.items():
            if alias in nom_clean and self._try_launch(cands):
                self.bring_to_front(alias)
                return ActionResult.ok(f"{alias.capitalize()} ouvert, {USER_NAME}.")

        # 2. Raccourci .lnk du menu demarrer.
        lnk = self._trouver_lnk(nom_clean)
        if lnk and self._startfile(str(lnk)):
            self.bring_to_front(lnk.stem)
            return ActionResult.ok(f"{lnk.stem} ouvert.")

        # 3. Executable dans le PATH.
        if which(nom_clean) and self._popen([nom_clean]):
            self.bring_to_front(nom_clean)
            return ActionResult.ok(f"{nom_clean} ouvert.")

        # 4. URL ou chemin explicite.
        cible = self._essayer_url_ou_chemin(nom_clean)
        if cible is not None:
            return cible

        # Introuvable : UNHANDLED -> la commande file vers l'IA (compat ancienne).
        return ActionResult.unhandled()

    def _essayer_web(self, nom_clean: str) -> ActionResult | None:
        """Ouvre un raccourci web si l'alias matche. None si aucun match."""
        for alias, url in _WEB_SHORTCUTS.items():
            if alias in nom_clean:
                try:
                    webbrowser.open(url)
                    self.bring_to_front(alias)
                    return ActionResult.ok(f"J'ouvre {alias} dans le navigateur.")
                except Exception:  # noqa: BLE001 - on tente le suivant
                    get_logger().warning("[PCCTL] echec ouverture web %s", url)
        return None

    def _essayer_url_ou_chemin(self, nom_clean: str) -> ActionResult | None:
        """URL http(s) -> navigateur ; chemin (/ ou \\) -> startfile/open."""
        if not (
            "/" in nom_clean or "\\" in nom_clean or nom_clean.startswith("http")
        ):
            return None
        try:
            if nom_clean.startswith("http"):
                webbrowser.open(nom_clean)
            elif deps.IS_MAC:
                self._popen(["open", nom_clean])
            elif os.name == "nt":
                self._startfile(nom_clean)
            else:
                self._popen(["xdg-open", nom_clean])
            return ActionResult.ok(f"Ouvert : {nom_clean}")
        except Exception:  # noqa: BLE001
            get_logger().warning("[PCCTL] echec ouverture cible %s", nom_clean)
            return None

    # ── Lancement bas niveau ──
    def _try_launch(self, candidats: list[str]) -> bool:
        """Tente chaque candidat : URI (:// ou se terminant par :), PATH, mac -a."""
        for c in candidats:
            try:
                if c.endswith(":") or "://" in c:
                    if os.name == "nt":
                        if self._startfile(c):
                            return True
                    elif webbrowser.open(c):
                        return True
                    continue
                if which(c) and self._popen([c]):
                    return True
                if deps.IS_MAC and not c.lower().endswith((".exe", ".cmd")):
                    if self._popen(["open", "-a", c]):
                        return True
            except Exception:  # noqa: BLE001 - on tente le candidat suivant
                continue
        return False

    def _popen(self, args: list[str]) -> bool:
        """Lance un process detache (shell=False impose). False si echec."""
        try:
            if self._runner is not None:
                self._runner.run(args)
            else:
                subprocess.Popen(args, shell=False)
            return True
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _startfile(cible: str) -> bool:
        """os.startfile (Windows seulement). False ailleurs ou en cas d'echec."""
        if os.name != "nt":
            return False
        try:
            os.startfile(cible)  # type: ignore[attr-defined]
            return True
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _trouver_lnk(nom: str) -> Path | None:
        """Cherche un .lnk du menu demarrer dont le nom contient `nom`."""
        nom_clean = nom.lower().strip()
        for base in _START_MENU_DIRS:
            if not base.exists():
                continue
            try:
                for lnk in base.rglob("*.lnk"):
                    if nom_clean in lnk.stem.lower():
                        return lnk
            except Exception:  # noqa: BLE001
                continue
        return None

    # ── Mise au premier plan (expose pour main2 : Spotify, tools) ──
    def bring_to_front(self, hint: str, max_wait_s: float = 2.0) -> bool:
        """Attend une fenetre dont le titre contient `hint` puis la met devant.

        Sous Windows, SetForegroundWindow refuse souvent quand l'appelant n'a pas
        le foreground : on s'attache au thread de la fenetre cible
        (AttachThreadInput) pour heriter de ses droits de focus. Best-effort,
        degradation propre si les libs Win32 manquent.
        """
        if os.name != "nt":
            return False
        hint = (hint or "").lower().strip()
        if not hint:
            return False

        win = self._attendre_fenetre(hint, max_wait_s)
        if not win:
            return False
        return self._focus_win32(win)

    @staticmethod
    def _attendre_fenetre(hint: str, max_wait_s: float):
        """Boucle d'attente : renvoie la 1re fenetre dont le titre contient hint."""
        deadline = time.time() + max_wait_s
        while time.time() < deadline:
            try:
                import pygetwindow as gw  # type: ignore

                for w in gw.getAllWindows():
                    title = (w.title or "").strip()
                    if title and hint in title.lower():
                        return w
            except Exception:  # noqa: BLE001 - pas de pygetwindow / headless
                pass
            time.sleep(0.15)
        return None

    @staticmethod
    def _focus_win32(win) -> bool:
        """Met `win` au premier plan via AttachThreadInput. Repli win.activate()."""
        try:
            import ctypes
            from ctypes import wintypes

            import win32con  # type: ignore
            import win32gui  # type: ignore

            hwnd = int(win._hWnd)
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            user32.GetWindowThreadProcessId.restype = wintypes.DWORD
            target = user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), None)
            current = kernel32.GetCurrentThreadId()

            attached = False
            try:
                if target and target != current:
                    attached = bool(
                        user32.AttachThreadInput(current, target, True)
                    )
                win32gui.BringWindowToTop(hwnd)
                win32gui.SetForegroundWindow(hwnd)
                win32gui.SetActiveWindow(hwnd)
            finally:
                if attached:
                    user32.AttachThreadInput(current, target, False)
            return True
        except Exception:  # noqa: BLE001 - repli best-effort
            try:
                win.activate()
                return True
            except Exception:  # noqa: BLE001
                return False
