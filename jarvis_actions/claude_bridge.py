"""Pont entre Jarvis et Claude Code.

- Surveille la mtime des sessions Claude Code dans `~/.claude/projects/`
- Permet d'invoquer Claude Code en mode non-interactif depuis Jarvis
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from jarvis_config import USER_NAME


CLAUDE_PROJECTS_DIR = Path(os.path.expanduser("~/.claude/projects"))


def derniere_activite_claude_code() -> datetime | None:
    """mtime du fichier le plus recent dans ~/.claude/projects/. None si rien."""
    if not CLAUDE_PROJECTS_DIR.exists():
        return None
    latest: float = 0.0
    for path in CLAUDE_PROJECTS_DIR.rglob("*"):
        if path.is_file():
            try:
                m = path.stat().st_mtime
                if m > latest:
                    latest = m
            except Exception:
                continue
    if latest == 0.0:
        return None
    return datetime.fromtimestamp(latest)


def jours_depuis_derniere_session() -> float | None:
    last = derniere_activite_claude_code()
    if last is None:
        return None
    delta = datetime.now() - last
    return delta.total_seconds() / 86400.0


def lancer_claude_code(prompt: str, timeout_s: float = 60.0) -> tuple[str, bool]:
    """Lance Claude Code en mode non-interactif et renvoie sa reponse texte."""
    cli = shutil.which("claude")
    if not cli:
        return f"Claude Code n'est pas installe ou n'est pas dans le PATH, {USER_NAME}.", False
    try:
        result = subprocess.run(
            [cli, "--print", prompt],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            shell=False,
        )
        if result.returncode == 0:
            return result.stdout.strip() or "(reponse vide)", True
        return f"Claude Code a renvoye une erreur : {result.stderr.strip()[:200]}", False
    except subprocess.TimeoutExpired:
        return f"Claude Code a depasse {int(timeout_s)} secondes, j'abandonne.", False
    except Exception as e:
        return f"Echec invocation Claude Code : {e}", False


async def surveiller_inactivite(
    seuil_jours: float,
    callback,
    intervalle_check_s: float = 3600.0,
):
    """Tache de fond : appelle callback(jours) si > seuil_jours. Notifie une fois par seuil franchi."""
    deja_notifie_seuil: float | None = None
    while True:
        try:
            jours = jours_depuis_derniere_session()
            if jours is not None and jours >= seuil_jours:
                seuil_arrondi = float(int(jours))
                if deja_notifie_seuil != seuil_arrondi:
                    try:
                        await callback(jours)
                        deja_notifie_seuil = seuil_arrondi
                    except Exception as e:
                        print(f"[CLAUDE-WATCH] callback erreur : {e}")
            elif jours is not None and jours < seuil_jours:
                deja_notifie_seuil = None
        except Exception as e:
            print(f"[CLAUDE-WATCH] erreur : {e}")
        await asyncio.sleep(intervalle_check_s)
