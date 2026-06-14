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


def lancer_claude_code(
    prompt: str, timeout_s: float = 60.0, cwd: str | None = None
) -> tuple[str, bool]:
    """Lance Claude Code en mode non-interactif et renvoie sa reponse texte.

    `cwd` (optionnel) : dossier de travail dans lequel executer Claude Code —
    utilise par le mode Cowork pour confier une tache dans un projet precis.
    Un cwd inexistant est ignore (Claude tourne alors dans le dossier courant).
    """
    cli = shutil.which("claude")
    if not cli:
        return f"Claude Code n'est pas installe ou n'est pas dans le PATH, {USER_NAME}.", False
    dossier = cwd if (cwd and os.path.isdir(cwd)) else None
    try:
        result = subprocess.run(
            [cli, "--print", prompt],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            shell=False,
            cwd=dossier,
        )
        if result.returncode == 0:
            return result.stdout.strip() or "(reponse vide)", True
        return f"Claude Code a renvoye une erreur : {result.stderr.strip()[:200]}", False
    except subprocess.TimeoutExpired:
        return f"Claude Code a depasse {int(timeout_s)} secondes, j'abandonne.", False
    except Exception as e:
        return f"Echec invocation Claude Code : {e}", False


# Indicateur Windows CreateProcess : ouvrir une NOUVELLE console pour le process.
_CREATE_NEW_CONSOLE = 0x00000010

# Modes de permission Claude Code (--permission-mode). Liste BLANCHE : on n'injecte
# jamais une valeur arbitraire du client. "default" = comportement normal (demande).
_PERMISSION_MODES = {"default", "plan", "acceptEdits", "bypassPermissions"}


def _args_mode(permission_mode: str) -> list[str]:
    """Args `--permission-mode` valides (liste blanche), [] sinon ou si 'default'."""
    if permission_mode in _PERMISSION_MODES and permission_mode != "default":
        return ["--permission-mode", permission_mode]
    return []


def ouvrir_session_terminal(cwd: str | None = None,
                            permission_mode: str = "default") -> tuple[str, bool]:
    """Ouvre une session Claude Code INTERACTIVE dans une nouvelle fenetre terminal.

    Contrairement a lancer_claude_code (one-shot `claude --print`), ouvre un vrai
    terminal ou l'utilisateur dialogue avec Claude Code (tous les outils) dans
    `cwd`. C'est l'equivalent in-app de la commande `jcode`.

    `permission_mode` (liste blanche) : "default" (demande), "plan", "acceptEdits"
    (automatique), "bypassPermissions". Passe a Claude Code via --permission-mode.

    Windows : nouvelle console (`cmd /k claude`). Autres OS : best-effort.
    """
    cli = shutil.which("claude")
    if not cli:
        return f"Claude Code n'est pas installe ou pas dans le PATH, {USER_NAME}.", False
    dossier = cwd if (cwd and os.path.isdir(cwd)) else None
    mode_args = _args_mode(permission_mode)
    try:
        if os.name == "nt":
            # `cmd /k` garde la console ouverte apres le lancement de claude.
            subprocess.Popen(
                ["cmd", "/k", cli, *mode_args],
                cwd=dossier,
                creationflags=_CREATE_NEW_CONSOLE,
                shell=False,
            )
        elif shutil.which("x-terminal-emulator"):  # Linux best-effort
            subprocess.Popen(["x-terminal-emulator", "-e", cli, *mode_args], cwd=dossier, shell=False)
        elif shutil.which("osascript"):  # macOS best-effort
            cible = dossier or os.getcwd()
            # SECURITE : le chemin est passe en ARGV a osascript (aucune
            # interpolation dans le script) et echappe par `quoted form of`
            # cote shell. mode_args vient d'une liste blanche -> sur.
            suffixe = (" " + " ".join(mode_args)) if mode_args else ""
            script = (
                'on run argv\n'
                '  tell application "Terminal" to do script '
                f'("cd " & quoted form of (item 1 of argv) & " && claude{suffixe}")\n'
                'end run'
            )
            subprocess.Popen(["osascript", "-e", script, cible], shell=False)
        else:
            return ("L'ouverture d'un terminal de code n'est pas supportee sur cet OS.", False)
        return f"Session de code ouverte dans un terminal, {USER_NAME}.", True
    except Exception as e:  # noqa: BLE001
        return f"Echec ouverture de la session de code : {e}", False


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
