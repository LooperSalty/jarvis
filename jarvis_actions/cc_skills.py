"""Catalogue de skills Claude Code installables en un clic (pour le Cowork).

Jarvis delegue des taches de code a Claude Code (via `claude`, cf. claude_bridge
et la commande jcode). Plus Claude Code a de skills installes, plus le Cowork est
puissant. Ce module expose un CATALOGUE de marketplaces de skills reputees et
permet de les AJOUTER via la CLI `claude plugin marketplace add <repo>`.

Le module ne fait que piloter la CLI `claude` (deja sur le PATH). `_parser_marketplaces`
est PUR (parse la sortie de `claude plugin marketplace list`) et testable sans CLI.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

# Windows : empeche l'ouverture d'une fenetre console quand Jarvis.exe (app sans
# console) lance `claude` -> sinon un terminal "flashe" a chaque appel (ex: en
# ouvrant l'onglet Skills). 0 ailleurs.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# Marketplaces de skills Claude Code recommandees (nom affiche, repo GitHub, desc).
# "repo" est ce qu'on passe a `claude plugin marketplace add`.
CATALOGUE: list[dict] = [
    {
        "nom": "Skills officiels Anthropic",
        "repo": "anthropics/skills",
        "description": "Skills officielles : documents (PDF, DOCX, XLSX, PPTX), creation MCP, design… La base.",
    },
    {
        "nom": "Skills de Matt Pocock",
        "repo": "mattpocock/skills",
        "description": "Skills d'ingenierie pour vrais devs : TDD, diagnostic de bugs, amelioration d'architecture, handoff.",
    },
    {
        "nom": "Plugins officiels Claude Code",
        "repo": "anthropics/claude-plugins-official",
        "description": "Marketplace officielle de plugins Claude Code (commandes, agents, hooks).",
    },
]


def claude_disponible() -> bool:
    """True si la CLI `claude` (Claude Code) est dans le PATH."""
    return shutil.which("claude") is not None


def _parser_marketplaces(stdout: str) -> set[str]:
    """Extrait les repos GitHub des marketplaces deja configurees. PUR.

    Parse les lignes "Source: GitHub (owner/repo)" de `claude plugin marketplace
    list`. Retourne un set de "owner/repo" en minuscules. Jamais d'exception.
    """
    repos: set[str] = set()
    for m in re.finditer(r"GitHub\s*\(([^)]+)\)", stdout or ""):
        repo = m.group(1).strip().lower()
        if "/" in repo:
            repos.add(repo)
    return repos


def marketplaces_installes() -> set[str]:
    """Set des repos de marketplaces deja ajoutes (via la CLI). "" si erreur."""
    cli = shutil.which("claude")
    if not cli:
        return set()
    try:
        r = subprocess.run(
            [cli, "plugin", "marketplace", "list"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15, shell=False, creationflags=_NO_WINDOW,
        )
    except Exception:  # noqa: BLE001
        return set()
    if r.returncode != 0:
        return set()
    return _parser_marketplaces(r.stdout)


def ajouter_marketplace(repo: str) -> tuple[bool, str]:
    """Ajoute une marketplace via `claude plugin marketplace add <repo>`.

    Retourne (succes, message). N'ajoute que des repos du CATALOGUE (liste
    blanche) pour ne jamais executer un repo arbitraire venu du client.
    """
    repo = (repo or "").strip()
    repos_connus = {e["repo"].lower() for e in CATALOGUE}
    if repo.lower() not in repos_connus:
        return False, "Repository non reconnu (hors catalogue)."
    cli = shutil.which("claude")
    if not cli:
        return False, "Claude Code (claude) n'est pas installe ou pas dans le PATH."
    try:
        r = subprocess.run(
            [cli, "plugin", "marketplace", "add", repo],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, shell=False, creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return False, "Delai depasse en ajoutant la marketplace."
    except Exception as e:  # noqa: BLE001
        return False, f"Echec : {e}"
    if r.returncode == 0:
        return True, f"Marketplace {repo} ajoutee. Ses skills sont disponibles dans Claude Code."
    detail = (r.stderr or r.stdout or "").strip()[:200]
    return False, f"Claude a refuse : {detail}"
