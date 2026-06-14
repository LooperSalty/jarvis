"""Catalogue de skills du registre skills.sh, installables en un clic.

skills.sh (https://www.skills.sh/) est l'annuaire ouvert de skills d'agents IA.
Les skills s'installent via l'outil `vercel-labs/skills` :

    npx skills add <owner>/<repo> -a claude-code -g

(`-a claude-code` = cible Claude Code, `-g` = global -> ~/.claude/skills/, dispo
dans tous les projets et donc dans le Cowork / jcode / jarvis).

C'est un mecanisme DIFFERENT de cc_skills.py (qui ajoute des marketplaces via
`claude plugin marketplace add`). Ici on installe des skills individuels via npx.

Le module ne fait que piloter la CLI `npx`. La liste blanche `CATALOGUE` empeche
d'installer un repo arbitraire venu du client.
"""

from __future__ import annotations

import os
import shutil
import subprocess

# Windows : empeche le flash d'une fenetre console quand l'app sans console lance npx.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# Skills skills.sh reputees (repos GitHub verifies). "repo" = ce qu'on passe a
# `npx skills add`. Liste blanche : seuls ces repos sont installables.
CATALOGUE: list[dict] = [
    {
        "nom": "find-skills (vercel-labs/skills)",
        "repo": "vercel-labs/skills",
        "description": "Le skill le plus installe : permet a l'agent de DECOUVRIR et charger les autres skills disponibles.",
    },
    {
        "nom": "Superpowers (obra/superpowers)",
        "repo": "obra/superpowers",
        "description": "Framework de skills + methodologie de dev agentique : planification, debug, sous-agents, boucles autonomes.",
    },
    {
        "nom": "Agent skills Vercel (vercel-labs/agent-skills)",
        "repo": "vercel-labs/agent-skills",
        "description": "Collection officielle Vercel : best practices React/Next.js, patterns de composants, web design.",
    },
    {
        "nom": "Agent Browser (vercel-labs/agent-browser)",
        "repo": "vercel-labs/agent-browser",
        "description": "Automatisation de navigateur pour l'agent : naviguer, cliquer, extraire des pages web.",
    },
    {
        "nom": "Skills Anthropic (anthropics/skills)",
        "repo": "anthropics/skills",
        "description": "Skills officielles Anthropic via npx : documents (PDF/DOCX/XLSX/PPTX), frontend-design, skill-creator.",
    },
    {
        "nom": "Azure (microsoft/azure-skills)",
        "repo": "microsoft/azure-skills",
        "description": "Plugin officiel Microsoft : skills + config MCP pour les scenarios Azure.",
    },
]


def npx_disponible() -> bool:
    """True si `npx` (Node.js) est dans le PATH — requis pour installer un skill."""
    return shutil.which("npx") is not None


def installer_skill(repo: str) -> tuple[bool, str]:
    """Installe un skill skills.sh via `npx skills add <repo> -a claude-code -g`.

    Retourne (succes, message). N'installe que des repos du CATALOGUE (liste
    blanche) pour ne jamais executer un repo arbitraire venu du client.
    """
    repo = (repo or "").strip()
    repos_connus = {e["repo"].lower() for e in CATALOGUE}
    if repo.lower() not in repos_connus:
        return False, "Skill non reconnu (hors catalogue)."
    npx = shutil.which("npx")
    if not npx:
        return False, "npx (Node.js) n'est pas installe ou pas dans le PATH."
    try:
        r = subprocess.run(
            [npx, "--yes", "skills", "add", repo, "-a", "claude-code", "-g"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180, shell=False, creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return False, "Delai depasse pendant l'installation (npx)."
    except Exception as e:  # noqa: BLE001
        return False, f"Echec : {e}"
    if r.returncode == 0:
        return True, f"Skill {repo} installe globalement (~/.claude/skills). Dispo dans le Cowork / jcode."
    detail = (r.stderr or r.stdout or "").strip()[:200]
    return False, f"npx a echoue : {detail}"
