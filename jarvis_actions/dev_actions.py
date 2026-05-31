"""Actions dev/productivite pour Jarvis.

Gain de temps quotidien : ouverture rapide de projets, git, notes, timer, presse-papier, terminal.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from jarvis_config import USER_NAME


_PROJECT_ROOTS = [
    Path(os.environ.get("USERPROFILE", "")) / "Downloads",
    Path(os.environ.get("USERPROFILE", "")) / "Documents",
    Path(os.environ.get("USERPROFILE", "")) / "Desktop",
    Path(os.environ.get("USERPROFILE", "")) / "Projects",
    Path(os.environ.get("USERPROFILE", "")) / "Code",
    Path(os.environ.get("USERPROFILE", "")) / "dev",
]
_PROJECT_MARKERS = (".git", "package.json", "pyproject.toml", "Cargo.toml", "go.mod", "pom.xml")
_MAX_DEPTH = 4


def _trouver_projet(nom: str) -> Path | None:
    """Cherche un dossier de projet par nom (insensible a la casse, fuzzy-light)."""
    nom_clean = nom.lower().strip()
    if not nom_clean:
        return None
    matches: list[tuple[int, Path]] = []
    for root in _PROJECT_ROOTS:
        if not root.exists():
            continue
        for path in _walk_limited(root, _MAX_DEPTH):
            if not path.is_dir():
                continue
            stem = path.name.lower()
            if nom_clean == stem:
                return path
            if nom_clean in stem and any((path / m).exists() for m in _PROJECT_MARKERS):
                matches.append((len(stem), path))
    if matches:
        matches.sort()
        return matches[0][1]
    return None


def _walk_limited(root: Path, max_depth: int):
    base_depth = len(root.parts)
    try:
        for current, dirs, _files in os.walk(root):
            depth = len(Path(current).parts) - base_depth
            if depth >= max_depth:
                dirs.clear()
                continue
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "venv", "__pycache__", "dist", "build", "target")]
            yield Path(current)
    except Exception:
        return


def _ouvrir_projet_vscode(nom: str) -> tuple[str, bool]:
    p = _trouver_projet(nom)
    if not p:
        return f"Je n'ai pas trouve le projet '{nom}'.", False
    cli = shutil.which("code") or shutil.which("code.cmd")
    if cli:
        try:
            subprocess.Popen([cli, str(p)], shell=False)
            return f"Projet {p.name} ouvert dans VSCode.", True
        except Exception:
            pass
    try:
        os.startfile(str(p))
        return f"Dossier {p.name} ouvert dans l'explorateur (VSCode introuvable).", True
    except Exception as e:
        return f"Echec ouverture {p.name} : {e}", False


def _ouvrir_terminal(dossier: str | None) -> tuple[str, bool]:
    chemin: Path | None = None
    if dossier:
        chemin = _trouver_projet(dossier) or Path(os.path.expanduser(dossier))
        if not chemin.exists():
            chemin = None
    chemin = chemin or Path(os.environ.get("USERPROFILE", "."))

    wt = shutil.which("wt.exe") or shutil.which("wt")
    try:
        if wt:
            subprocess.Popen([wt, "-d", str(chemin)], shell=False)
        else:
            # Le dossier est passe via cwd (jamais concatene dans la commande)
            # pour eviter toute injection cmd.exe via un chemin piege.
            subprocess.Popen(
                ["cmd.exe", "/K"],
                cwd=str(chemin),
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
        return f"Terminal ouvert dans {chemin.name}.", True
    except Exception as e:
        return f"Echec ouverture terminal : {e}", False


def _git_status(dossier: str | None) -> tuple[str, bool]:
    chemin = _trouver_projet(dossier) if dossier else None
    chemin = chemin or Path(os.getcwd())
    if not (chemin / ".git").exists():
        return f"{chemin.name} n'est pas un depot git.", False
    try:
        r = subprocess.run(
            ["git", "-C", str(chemin), "status", "--short"],
            capture_output=True, text=True, timeout=8, shell=False,
        )
        out = r.stdout.strip()
        if not out:
            return f"Le depot {chemin.name} est propre, rien a committer.", True
        nb = len(out.splitlines())
        return f"{nb} fichiers modifies dans {chemin.name}.", True
    except Exception as e:
        return f"Erreur git : {e}", False


def _git_log_du_jour(dossier: str | None = None) -> tuple[str, bool]:
    chemin = _trouver_projet(dossier) if dossier else Path(os.getcwd())
    if not (chemin / ".git").exists():
        return f"{chemin.name} n'est pas un depot git.", False
    try:
        depuis = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
        r = subprocess.run(
            ["git", "-C", str(chemin), "log", f"--since={depuis}", "--oneline", "-n", "10"],
            capture_output=True, text=True, timeout=8, shell=False,
        )
        out = r.stdout.strip()
        if not out:
            return f"Aucun commit depuis 24h sur {chemin.name}.", True
        nb = len(out.splitlines())
        first_msgs = " | ".join(line.split(" ", 1)[1] if " " in line else line for line in out.splitlines()[:3])
        return f"{nb} commits sur {chemin.name} : {first_msgs[:200]}", True
    except Exception as e:
        return f"Erreur git log : {e}", False


_TIMERS: dict[str, threading.Timer] = {}


def _timer(minutes: int, message: str, callback) -> tuple[str, bool]:
    if minutes <= 0 or minutes > 240:
        return "Duree invalide (1 a 240 minutes).", False
    nom = f"timer_{int(time.time())}"

    def fire():
        try:
            callback(message)
        except Exception:
            pass
        _TIMERS.pop(nom, None)

    t = threading.Timer(minutes * 60, fire)
    t.daemon = True
    t.start()
    _TIMERS[nom] = t
    return f"Minuteur de {minutes} minutes lance.", True


def _lire_presse_papier() -> tuple[str, bool]:
    try:
        import pyperclip
        contenu = pyperclip.paste()
    except Exception:
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                capture_output=True, text=True, timeout=4, shell=False,
            )
            contenu = r.stdout.strip()
        except Exception as e:
            return f"Impossible de lire le presse-papier : {e}", False
    if not contenu:
        return "Le presse-papier est vide.", True
    apercu = contenu[:300].replace("\n", " ")
    return f"Presse-papier ({len(contenu)} caracteres) : {apercu}", True


def _note_rapide(obsidian_bridge, texte: str) -> tuple[str, bool]:
    if not obsidian_bridge:
        return "Obsidian n'est pas connecte, je ne peux pas noter.", False
    if not texte.strip():
        return f"Que veux-tu que je note, {USER_NAME} ?", False
    try:
        day = datetime.now().strftime("%Y-%m-%d")
        path = obsidian_bridge.dir_notes / f"{day}-rapides.md"
        time_str = datetime.now().strftime("%H:%M")
        if not path.exists():
            path.write_text(f"---\ndate: {day}\n---\n\n# Notes rapides du {day}\n\n", encoding="utf-8")
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"- **{time_str}** : {texte.strip()}\n")
        return "Note ajoutee dans Obsidian.", True
    except Exception as e:
        return f"Echec note : {e}", False


def _lister_projets() -> tuple[str, bool]:
    projets: list[str] = []
    for root in _PROJECT_ROOTS:
        if not root.exists():
            continue
        for p in _walk_limited(root, 3):
            if any((p / m).exists() for m in _PROJECT_MARKERS):
                projets.append(p.name)
    projets = sorted(set(projets))
    if not projets:
        return "Aucun projet detecte.", True
    apercu = ", ".join(projets[:12])
    return f"{len(projets)} projets : {apercu}", True


_TIMER_RE = re.compile(r"\s*(\d+)\s*(minute|min|m|seconde|sec|s)\b", re.I)


def executer(cmd: str, obsidian_bridge=None, callback_parler=None) -> tuple[str | None, bool]:
    if not cmd:
        return None, False
    c = cmd.lower().strip()

    m = re.search(r"(?:ouvre|lance|edite)\s+(?:le\s+)?projet\s+(.+?)(?:\s+dans|\s+avec|$)", c)
    if m:
        return _ouvrir_projet_vscode(m.group(1).strip())

    if any(p in c for p in ("ouvre un terminal", "ouvre le terminal", "lance un terminal")):
        cible = None
        m = re.search(r"(?:dans|sur)\s+(?:le\s+)?(?:projet\s+|dossier\s+)?(.+)", c)
        if m:
            cible = m.group(1).strip()
        return _ouvrir_terminal(cible)

    if any(p in c for p in ("git status", "etat du depot", "etat du projet", "etat git")):
        cible = None
        m = re.search(r"(?:de|dans|du projet)\s+(.+)", c)
        if m:
            cible = m.group(1).strip()
        return _git_status(cible)

    if any(p in c for p in ("qu'est-ce que j'ai fait", "qu ai-je fait", "mes commits", "git log", "commits du jour")):
        cible = None
        m = re.search(r"(?:dans|sur|du projet)\s+(.+)", c)
        if m:
            cible = m.group(1).strip()
        return _git_log_du_jour(cible)

    if "presse" in c and ("papier" in c or "papiers" in c) or "clipboard" in c:
        return _lire_presse_papier()

    m = re.search(r"(?:lance|mets|cree)?\s*(?:un\s+)?(?:minuteur|timer|pomodoro)\s+(?:de\s+)?(\d+)\s*(?:min|minute|m)?", c)
    if m:
        minutes = int(m.group(1))
        message = f"Temps ecoule, {USER_NAME}."
        if "pomodoro" in c:
            message = "Pomodoro termine, fais une pause de 5 minutes."
        cb = callback_parler or (lambda _: None)
        return _timer(minutes, message, cb)

    m = re.match(r"\s*(?:note|prends note|retiens vite|memo)\s*(?:que|:)?\s*(.+)", cmd, re.I)
    if m:
        return _note_rapide(obsidian_bridge, m.group(1))

    if any(p in c for p in ("liste mes projets", "mes projets", "quels sont mes projets")):
        return _lister_projets()

    return None, False
