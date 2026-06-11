"""Actions executables sur le PC depuis une commande en langage naturel.

Approche : detection locale par mots-cles, sans appel a l'IA.
Retourne (None, False) si la commande n'est pas reconnue ; sinon (reponse_vocale, succes).
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import pyautogui
from jarvis_config import USER_NAME

HOME = Path.home()
IS_MAC = platform.system() == "Darwin"


def _bring_to_front(title_hint: str, max_wait_s: float = 3.0) -> bool:
    """Attend qu'une fenetre dont le titre contient title_hint apparaisse
    apres un launch, puis la met au premier plan.

    Sous Windows, SetForegroundWindow refuse souvent silencieusement quand
    l'app appelante ne possede pas le foreground. On utilise AttachThreadInput
    (le thread appelant s'attache au thread de la fenetre cible -> il herite
    de ses droits de focus). Pas de touche fantome -> pas de menu qui s'ouvre.
    """
    if os.name != "nt":
        return False
    hint = title_hint.lower().strip()
    if not hint:
        return False

    deadline = time.time() + max_wait_s
    win = None
    while time.time() < deadline:
        try:
            import pygetwindow as gw
            for w in gw.getAllWindows():
                title = (w.title or "").strip()
                if title and hint in title.lower():
                    win = w
                    break
        except Exception:
            pass
        if win:
            break
        time.sleep(0.15)

    if not win:
        return False

    try:
        import ctypes
        import win32con
        import win32gui
        from ctypes import wintypes

        hwnd = int(win._hWnd)
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        # GetWindowThreadProcessId : DWORD (thread id), 2eme arg = process id (NULL ok)
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        target_thread = user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), None)
        current_thread = kernel32.GetCurrentThreadId()

        # Bind the calling thread input to the target's input queue : SetForegroundWindow accepte
        attached = False
        try:
            if target_thread and target_thread != current_thread:
                attached = bool(user32.AttachThreadInput(current_thread, target_thread, True))
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
            win32gui.SetActiveWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(current_thread, target_thread, False)
        return True
    except Exception:
        try:
            win.activate()
            return True
        except Exception:
            return False


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

# Sites webs ouverts dans le navigateur par defaut
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


def _trouver_lnk(nom: str) -> Path | None:
    """Cherche un raccourci .lnk correspondant dans le menu demarrer."""
    nom_clean = nom.lower().strip()
    for base in _START_MENU_DIRS:
        if not base.exists():
            continue
        try:
            for lnk in base.rglob("*.lnk"):
                if nom_clean in lnk.stem.lower():
                    return lnk
        except Exception:
            continue
    return None


def _try_launch(candidats: list[str]) -> bool:
    for c in candidats:
        try:
            if c.endswith(":") or "://" in c:
                if os.name == "nt":
                    os.startfile(c)  # type: ignore[attr-defined]
                else:
                    webbrowser.open(c)
                return True
            if shutil.which(c):
                subprocess.Popen([c], shell=False)
                return True
            if IS_MAC and not c.lower().endswith((".exe", ".cmd")):
                subprocess.Popen(["open", "-a", c], shell=False)
                return True
        except Exception:
            continue
    return False


def _ouvrir_app(nom: str) -> tuple[str | None, bool]:
    nom_clean = nom.strip().lower()
    if not nom_clean:
        return None, False

    # 0. Sites webs (Google Maps, YouTube, etc.) — priorite haute
    for alias, url in _WEB_SHORTCUTS.items():
        if alias in nom_clean:
            try:
                webbrowser.open(url)
                # Ramene le navigateur au premier plan apres ouverture de l'onglet
                _bring_to_front(alias)
                return f"J'ouvre {alias} dans le navigateur.", True
            except Exception:
                pass

    # 1. Alias connus
    for alias, cands in _APP_ALIASES.items():
        if alias in nom_clean:
            if _try_launch(cands):
                _bring_to_front(alias)
                return f"{alias.capitalize()} ouvert, {USER_NAME}.", True
            # On continue : on essaiera lnk + start

    # 2. Raccourci dans le menu demarrer
    lnk = _trouver_lnk(nom_clean)
    if lnk:
        try:
            os.startfile(str(lnk))  # type: ignore[attr-defined]
            _bring_to_front(lnk.stem)
            return f"{lnk.stem} ouvert.", True
        except Exception:
            pass

    # 3. Executable dans le PATH
    if shutil.which(nom_clean):
        try:
            subprocess.Popen([nom_clean], shell=False)
            _bring_to_front(nom_clean)
            return f"{nom_clean} ouvert.", True
        except Exception:
            pass

    # 4. Si ca ressemble a une URL ou un fichier
    # Garde anti-injection d'argument : open/xdg-open interpreteraient un
    # argument commencant par "-" comme une option.
    if nom_clean.startswith("-"):
        return None, False
    if "/" in nom_clean or "\\" in nom_clean or nom_clean.startswith("http"):
        try:
            if nom_clean.startswith("http"):
                webbrowser.open(nom_clean)
            elif IS_MAC:
                subprocess.Popen(["open", nom_clean], shell=False)
            elif os.name == "nt":
                os.startfile(nom_clean)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", nom_clean], shell=False)
            return f"Ouvert : {nom_clean}", True
        except Exception:
            pass

    return f"Je n'ai pas trouve l'application '{nom}' sur ton PC, {USER_NAME}.", False


def _fermer_fenetre_active() -> tuple[str, bool]:
    if IS_MAC:
        pyautogui.hotkey("command", "w")
    else:
        pyautogui.hotkey("alt", "f4")
    return "Fenetre fermee.", True


def _verrouiller() -> tuple[str, bool]:
    if os.name == "nt":
        try:
            subprocess.run(
                ["rundll32.exe", "user32.dll,LockWorkStation"],
                check=False,
                shell=False,
            )
            return f"PC verrouille, {USER_NAME}.", True
        except Exception as e:
            return f"Echec du verrouillage : {e}", False
    if IS_MAC:
        try:
            # CGSession n'existe plus sur les macOS recents (11+). Ctrl+Cmd+Q
            # est le raccourci natif de verrouillage (permission Accessibilite requise).
            pyautogui.hotkey("ctrl", "command", "q")
            return f"Session verrouillee, {USER_NAME}.", True
        except Exception as e:
            return f"Echec du verrouillage : {e}", False
    return "Verrouillage non supporte sur cet OS.", False


def _capture_ecran(dossier: str) -> tuple[str, bool]:
    Path(dossier).mkdir(parents=True, exist_ok=True)
    nom = f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    chemin = Path(dossier) / nom
    pyautogui.screenshot(str(chemin))
    return f"Capture sauvegardee : {chemin.name}", True


def _volume(action: str) -> tuple[str, bool]:
    if action == "up":
        for _ in range(5):
            pyautogui.press("volumeup")
        return "Volume augmente.", True
    if action == "down":
        for _ in range(5):
            pyautogui.press("volumedown")
        return "Volume baisse.", True
    if action == "mute":
        pyautogui.press("volumemute")
        return "Son coupe.", True
    return "Action volume inconnue.", False


def _media(action: str) -> tuple[str, bool]:
    mapping = {
        "play": "playpause",
        "pause": "playpause",
        "next": "nexttrack",
        "prev": "prevtrack",
    }
    key = mapping.get(action)
    if not key:
        return "Action media inconnue.", False
    pyautogui.press(key)
    return f"Media : {action}.", True


def _taper(texte: str) -> tuple[str, bool]:
    pyautogui.write(texte, interval=0.02)
    return "Texte saisi.", True


def _copier_coller(action: str) -> tuple[str, bool]:
    mod = "command" if IS_MAC else "ctrl"
    if action == "copy":
        pyautogui.hotkey(mod, "c")
        return "Copie.", True
    if action == "paste":
        pyautogui.hotkey(mod, "v")
        return "Colle.", True
    if action == "cut":
        pyautogui.hotkey(mod, "x")
        return "Coupe.", True
    return "Action presse-papier inconnue.", False


_OUVRIR_RE = re.compile(r"\b(ouvre|lance|demarre|demarrer|ouvrir|lancer)\s+(.+)", re.I)


def executer(cmd: str) -> tuple[str | None, bool]:
    """Tente d'executer la commande. Retourne (reponse, succes) ou (None, False) si non reconnue."""
    if not cmd:
        return None, False
    c = cmd.lower().strip()

    if any(p in c for p in ("ferme cette fenetre", "ferme la fenetre", "ferme l'application", "ferme l application")):
        return _fermer_fenetre_active()
    if any(p in c for p in ("verrouille", "verrouiller", "lock le pc", "ferme la session")):
        return _verrouiller()

    if any(p in c for p in ("screenshot", "capture d'ecran", "capture ecran", "capture l'ecran", "prends une capture")):
        dossier = str(HOME / "Pictures" / "Jarvis")
        return _capture_ecran(dossier)

    if "volume" in c or "son" in c:
        if any(p in c for p in ("monte", "augmente", "plus fort")):
            return _volume("up")
        if any(p in c for p in ("baisse", "diminue", "moins fort")):
            return _volume("down")
        if any(p in c for p in ("coupe", "mute", "silence")):
            return _volume("mute")

    if any(p in c for p in ("mets pause", "pause la musique", "pause la video", "appuie sur pause")):
        return _media("pause")
    if any(p in c for p in ("reprends la musique", "reprends la video", "joue la musique", "remets la musique")):
        return _media("play")
    if any(p in c for p in ("piste suivante", "musique suivante", "chanson suivante", "next morceau")):
        return _media("next")
    if any(p in c for p in ("piste precedente", "morceau precedent", "musique precedente")):
        return _media("prev")

    if "copie" in c and "ce" in c:
        return _copier_coller("copy")
    if "colle" in c:
        return _copier_coller("paste")

    m = re.match(r"\s*(tape|saisis|ecris)\s+(.+)", c, re.I)
    if m:
        texte_original = re.split(r"\s*(tape|saisis|ecris)\s+", cmd, maxsplit=1, flags=re.I)[-1]
        return _taper(texte_original)

    m = _OUVRIR_RE.search(c)
    if m:
        return _ouvrir_app(m.group(2))

    return None, False
