"""Jarvis en tant qu'icone system tray Windows.

- Icone bleue dans la zone de notification
- Click gauche : ouvre l'orbe dans le navigateur
- Click droit : menu (Ouvrir, Redemarrer, Quitter)
- Lance / surveille / arrete le backend Jarvis
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

# Ce script est dans jarvis/scripts/, le projet est dans son parent
ROOT = Path(__file__).parent.parent.resolve()
BACKEND_SCRIPT = ROOT / "main2.py"
ICON_PATH = ROOT / "jarvis_tray.ico"
LOG_PATH = ROOT / "jarvis.log"
ERR_PATH = ROOT / "jarvis.log.err"
JARVIS_URL = "http://localhost:5173"


def make_icon(size: int = 64) -> Image.Image:
    """Genere une orbe bleue stylisee : cercle bleu cyan avec halo."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = cy = size // 2
    # Halo externe
    for r, alpha in ((size // 2, 40), (size // 2 - 4, 70), (size // 2 - 8, 110)):
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(76, 168, 232, alpha))
    # Cercle principal
    main_r = size // 2 - 14
    draw.ellipse([cx - main_r, cy - main_r, cx + main_r, cy + main_r], fill=(93, 208, 255, 230))
    # Reflet central
    inner_r = size // 4
    draw.ellipse([cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r], fill=(255, 255, 255, 230))
    return img


def ensure_icon_file() -> str:
    if not ICON_PATH.exists():
        img = make_icon(64)
        img.save(str(ICON_PATH), format="ICO", sizes=[(64, 64), (32, 32), (16, 16)])
    return str(ICON_PATH)


_proc: subprocess.Popen | None = None


def backend_alive() -> bool:
    return _proc is not None and _proc.poll() is None


def start_backend() -> bool:
    global _proc
    if backend_alive():
        return True
    try:
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("FORCE_OLLAMA", "1")
        creation = 0
        if os.name == "nt":
            creation = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        _proc = subprocess.Popen(
            [sys.executable, "-u", str(BACKEND_SCRIPT)],
            cwd=str(ROOT),
            env=env,
            stdout=open(LOG_PATH, "w", encoding="utf-8", buffering=1),
            stderr=open(ERR_PATH, "w", encoding="utf-8", buffering=1),
            creationflags=creation,
        )
        return True
    except Exception as e:
        print(f"[TRAY] Echec demarrage backend : {e}")
        return False


def stop_backend() -> None:
    global _proc
    if not _proc:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(_proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                shell=False,
            )
        else:
            _proc.terminate()
        _proc.wait(timeout=5)
    except Exception:
        try:
            _proc.kill()
        except Exception:
            pass
    _proc = None


def open_orb(_icon=None, _item=None) -> None:
    if not backend_alive():
        start_backend()
        time.sleep(2.5)
    webbrowser.open(JARVIS_URL)


def restart_backend(_icon=None, _item=None) -> None:
    stop_backend()
    time.sleep(0.5)
    start_backend()


def open_logs(_icon=None, _item=None) -> None:
    if LOG_PATH.exists():
        try:
            if os.name == "nt":
                os.startfile(str(LOG_PATH))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(LOG_PATH)], shell=False)
            else:
                subprocess.Popen(["xdg-open", str(LOG_PATH)], shell=False)
        except Exception:
            pass


def quit_app(icon: pystray.Icon, _item=None) -> None:
    stop_backend()
    icon.stop()


def build_menu() -> pystray.Menu:
    return pystray.Menu(
        pystray.MenuItem("Ouvrir l'orbe", open_orb, default=True),
        pystray.MenuItem("Redemarrer Jarvis", restart_backend),
        pystray.MenuItem("Voir les logs", open_logs),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quitter", quit_app),
    )


def _watchdog(icon: pystray.Icon) -> None:
    """Si le backend meurt, on reflete l'etat dans l'icone."""
    while True:
        time.sleep(5)
        try:
            if not backend_alive():
                icon.title = "Jarvis (arrete)"
            else:
                icon.title = "Jarvis (actif)"
        except Exception:
            return


def main() -> None:
    img = make_icon(64)
    ensure_icon_file()

    icon = pystray.Icon(
        "jarvis",
        icon=img,
        title="Jarvis (demarrage...)",
        menu=build_menu(),
    )

    def setup(icon_obj):
        icon_obj.visible = True
        threading.Thread(target=_watchdog, args=(icon_obj,), daemon=True).start()
        start_backend()

    icon.run(setup=setup)


if __name__ == "__main__":
    main()
