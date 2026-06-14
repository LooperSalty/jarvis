"""Pont vers free-claude-code (proxy `fcc-server`) pour l'onglet Code du dashboard.

free-claude-code expose une Admin UI (providers, modeles, messaging) sur
http://127.0.0.1:8082/admin. L'onglet Code de Jarvis l'embarque dans une iframe.
Ce module sert a savoir si le proxy tourne et a le demarrer au besoin.

`statut()` ne fait qu'un GET /health (stdlib urllib, aucune dependance). Toutes
les fonctions degradent proprement (jamais d'exception propagee).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import urllib.request

PORT = 8082
ADMIN_URL = f"http://127.0.0.1:{PORT}/admin"
_HEALTH_URL = f"http://127.0.0.1:{PORT}/health"

# Flags Windows : process detache (survit a la fermeture de Jarvis) + groupe neuf.
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200


def en_marche(timeout: float = 2.0) -> bool:
    """True si le proxy fcc-server repond sur /health."""
    try:
        with urllib.request.urlopen(_HEALTH_URL, timeout=timeout) as r:  # noqa: S310 - URL locale fixe
            return 200 <= getattr(r, "status", r.getcode()) < 300
    except Exception:  # noqa: BLE001 - proxy down / refus de connexion
        return False


def installe() -> bool:
    """True si la commande fcc-server est dans le PATH."""
    return shutil.which("fcc-server") is not None


def demarrer() -> tuple[bool, str]:
    """Demarre fcc-server (detache) s'il ne tourne pas deja. (succes, message)."""
    if en_marche():
        return True, "Le proxy free-claude-code est deja demarre."
    cli = shutil.which("fcc-server")
    if not cli:
        return False, "free-claude-code (fcc-server) n'est pas installe."
    try:
        if os.name == "nt":
            subprocess.Popen(
                [cli],
                creationflags=_DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
        else:
            subprocess.Popen([cli], start_new_session=True)
        return True, "Demarrage du proxy lance (quelques secondes)."
    except Exception as e:  # noqa: BLE001
        return False, f"Echec du demarrage : {e}"


def assurer_demarre(timeout: float = 15.0) -> bool:
    """Garantit que le proxy tourne : True si deja/maintenant healthy.

    Le demarre s'il est absent puis attend /health jusqu'a `timeout`. Bloquant
    (a appeler dans un executor, jamais sur l'event loop)."""
    if en_marche():
        return True
    ok, _ = demarrer()
    if not ok:
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if en_marche(timeout=2.0):
            return True
        time.sleep(1.0)
    return en_marche()


def statut() -> dict:
    """Statut pour le dashboard : {installe, en_marche, url_admin, port}."""
    return {
        "installe": installe(),
        "en_marche": en_marche(),
        "url_admin": ADMIN_URL,
        "port": PORT,
    }
