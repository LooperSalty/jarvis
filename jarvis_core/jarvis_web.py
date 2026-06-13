"""Jarvis Web — lance le backend + ouvre l'interface dans le navigateur par defaut.

Comportement :
- Mode dev (.py)  : lance main2.py en sous-process
- Mode .exe       : importe main2 et le lance en thread du meme process
- Sert le bundle frontend/dist/ sur :5173 (pas besoin de Node.js)
- Ouvre http://localhost:5173 dans le navigateur par defaut
- Reste vivant (sans ca, le thread daemon meurt avec le process)
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
# Frozen : ROOT = _MEIPASS. Dev : ce fichier est dans jarvis_core/, ROOT pointe
# la RACINE du repo (remonte d'un cran) ; main2.py est dans jarvis_core/.
ROOT = Path(getattr(sys, "_MEIPASS", str(Path(__file__).parent.parent.resolve())))
JARVIS_URL = "http://localhost:5173"
LOG_PATH = Path(tempfile.gettempdir()) / "jarvis_web.log"


def _log(msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    print(line, end="", flush=True)


def _wait_for_port(port: int = 5173, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.4)
    return False


def main():
    _log(f"Demarrage (frozen={FROZEN}, root={ROOT})")
    os.environ["JARVIS_NO_BROWSER"] = "1"  # main2 sert dist/ sur 5173 et n'ouvre pas Chrome
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    backend_proc = None
    if FROZEN:
        os.chdir(str(ROOT))
        sys.path.insert(0, str(ROOT))
        import main2
        threading.Thread(target=main2.main, daemon=True).start()
    else:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        backend_proc = subprocess.Popen(
            [sys.executable, "-u", str(ROOT / "jarvis_core" / "main2.py")],
            cwd=str(ROOT), env=env,
        )

    if _wait_for_port(5173):
        _log(f"Frontend pret. Ouverture {JARVIS_URL}")
    else:
        _log("Frontend pas pret apres 30s, ouverture quand meme.")
    webbrowser.open(JARVIS_URL)

    # Garde le process vivant
    try:
        if backend_proc:
            backend_proc.wait()
        else:
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        _log("Arret demande.")
        if backend_proc:
            backend_proc.terminate()


if __name__ == "__main__":
    main()
