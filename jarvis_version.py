"""Version de Jarvis + verification de mise a jour (best-effort, sans dependance).

La version suit le tag git de release (vX.Y.Z). Le workflow .github/workflows/
release.yml publie une release GitHub a chaque tag. check_update() interroge
l'API GitHub pour savoir si une version plus recente existe.
"""

from __future__ import annotations

import json
import urllib.request

# Version courante. A bumper en meme temps que le tag git de release.
VERSION = "0.1.0"

# Depot GitHub (owner/repo) pour la verification de mise a jour.
GITHUB_REPO = "LooperSalty/jarvis"
_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def _normaliser(tag: str) -> tuple[int, ...]:
    """Transforme 'v1.2.3' (ou '1.2.3') en tuple comparable (1, 2, 3).

    Les composantes non numeriques sont ignorees. Retourne (0,) si illisible.
    """
    tag = (tag or "").strip().lstrip("vV")
    parties: list[int] = []
    for morceau in tag.split("."):
        chiffres = "".join(c for c in morceau if c.isdigit())
        if chiffres:
            parties.append(int(chiffres))
    return tuple(parties) if parties else (0,)


def check_update(timeout_s: float = 4.0) -> dict:
    """Verifie si une release plus recente que VERSION existe sur GitHub.

    Returns:
        Un dict {"disponible": bool, "version_locale": str, "version_distante":
        str | None, "url": str | None, "erreur": str | None}. Ne leve jamais :
        en cas d'erreur reseau, "disponible" est False et "erreur" est renseigne.
    """
    resultat = {
        "disponible": False,
        "version_locale": VERSION,
        "version_distante": None,
        "url": None,
        "erreur": None,
    }
    try:
        req = urllib.request.Request(
            _RELEASES_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "jarvis"},
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as reponse:
            data = json.loads(reponse.read().decode("utf-8"))
        tag = str(data.get("tag_name") or "")
        resultat["version_distante"] = tag or None
        resultat["url"] = data.get("html_url")
        resultat["disponible"] = _normaliser(tag) > _normaliser(VERSION)
    except Exception as e:  # noqa: BLE001 - jamais d'exception propagee
        resultat["erreur"] = str(e)
    return resultat


if __name__ == "__main__":
    print(f"Jarvis {VERSION}")
    print(check_update())
