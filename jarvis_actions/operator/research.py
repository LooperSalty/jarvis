"""Recherche internet (SerpAPI) + synthese LLM pour l'Operator.

Le shaping des resultats (`shaper_resultats`) est PUR et entierement teste ; l'acces
reseau est INJECTE (`http_get`) ou realise via urllib en lazy import. Defensif :
aucune fonction publique ne leve — en cas d'echec, repli sur une synthese directe
de la requete par le LLM (sans sources).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Awaitable, Callable

_SERPAPI_URL = "https://serpapi.com/search"
_MAX_SOURCES = 6
_EXTRAIT_MAX = 300


def shaper_resultats(brut_serp: Any) -> list[dict]:
    """Reponse SerpAPI brute -> liste de sources {titre, lien, extrait}.

    Prend les `organic_results`, tronque chaque extrait a 300 caracteres et limite
    a 6 elements. Renvoie [] si l'entree n'est pas un dict exploitable. PUR, ne
    leve jamais.
    """
    if not isinstance(brut_serp, dict):
        return []
    organic = brut_serp.get("organic_results", [])
    if not isinstance(organic, list):
        return []
    sources: list[dict] = []
    for r in organic:
        if not isinstance(r, dict):
            continue
        sources.append({
            "titre": r.get("title", ""),
            "lien": r.get("link", ""),
            "extrait": str(r.get("snippet", ""))[:_EXTRAIT_MAX],
        })
        if len(sources) >= _MAX_SOURCES:
            break
    return sources


def _prompt_synthese(query: str, sources: list[dict]) -> str:
    """Construit le prompt de synthese a partir des titres + extraits des sources."""
    lignes = [f"- {s.get('titre', '')} : {s.get('extrait', '')}" for s in sources]
    corps = "\n".join(lignes)
    return (
        f"Synthetise en francais, de maniere concise et factuelle, les resultats de "
        f"recherche suivants pour la requete \"{query}\" :\n{corps}"
    )


def _http_get_reel(url: str, params: dict) -> dict:
    """GET reel SerpAPI via urllib (lazy import) -> JSON deserialise. Ne leve pas."""
    try:
        import json
        import urllib.parse
        import urllib.request

        qs = urllib.parse.urlencode(params)
        with urllib.request.urlopen(f"{url}?{qs}", timeout=15) as resp:  # nosec B310
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {}


async def _appeler_ia(demander_ia: Callable[[str], Awaitable[str]], prompt: str) -> str:
    """Await defensif du LLM : renvoie '' (defaut documente) si l'appel echoue."""
    try:
        res = await demander_ia(prompt)
        return str(res or "")
    except Exception:
        return ""


async def rechercher(
    query: str,
    demander_ia: Callable[[str], Awaitable[str]],
    http_get: Callable[[str, dict], dict] | None = None,
) -> dict:
    """Recherche internet + synthese -> {"resume": str, "sources": list[dict]}.

    Si une cle `SERPAPI_API_KEY` et un moyen HTTP sont disponibles, recupere les
    resultats, les met en forme (`shaper_resultats`) puis demande une synthese au
    LLM (`demander_ia`). Sinon — pas de cle, aucun resultat ou erreur reseau — repli
    sur une synthese directe de la requete avec `sources` vide. Defensif : ne leve
    jamais.
    """
    q = (query or "").strip()
    cle = os.environ.get("SERPAPI_API_KEY", "").strip()
    sources: list[dict] = []
    if cle:
        try:
            getter = http_get or _http_get_reel
            params = {"q": q, "api_key": cle, "engine": "google"}
            # GET reseau synchrone -> hors event loop (ne pas geler le serveur WS).
            brut = await asyncio.to_thread(getter, _SERPAPI_URL, params)
            sources = shaper_resultats(brut)
        except Exception:
            sources = []
    if sources:
        resume = await _appeler_ia(demander_ia, _prompt_synthese(q, sources))
        return {"resume": resume, "sources": sources}
    # Repli : synthese directe de la requete, sans sources.
    return {"resume": await _appeler_ia(demander_ia, q), "sources": []}
