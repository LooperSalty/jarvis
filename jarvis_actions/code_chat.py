"""Chat specialise code, branche sur un modele LOCAL via Ollama (gratuit, prive).

Alimente l'onglet "Code" du dashboard : un chat ou l'utilisateur pose des
questions de programmation, repondues par un modele de code local (DeepSeek
Coder / Qwen) — pas le Claude payant. Aucun appel cloud.

`_choisir_modele` est PUR (choisit le meilleur modele de code parmi ceux
installes). `repondre` fait un POST Ollama /api/chat (mockable dans les tests).
"""

from __future__ import annotations

import os

import requests

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
# Modele force par l'utilisateur (sinon choix auto parmi les modeles installes).
_MODELE_FORCE = os.getenv("JARVIS_CODE_MODEL", "").strip()
# Ordre de preference pour un chat de CODE (le plus specialise d'abord).
_PREFERENCES = ("deepseek-coder", "qwen2.5-coder", "codellama", "qwen2.5", "qwen", "llama")

_SYSTEM = (
    "Tu es un assistant de programmation expert et concis. Tu reponds en "
    "francais. Donne du code clair, correct et idiomatique, dans des blocs de "
    "code, avec une explication breve. Si la demande est ambigue, propose une "
    "hypothese raisonnable plutot que de poser trop de questions."
)


def _choisir_modele(modeles_installes: list[str]) -> str:
    """Choisit le meilleur modele de code parmi ceux installes (fonction PURE).

    Respecte JARVIS_CODE_MODEL s'il est defini ET installe. Sinon prend le 1er
    qui matche l'ordre de preference. Repli : le 1er modele installe, ou "".
    """
    noms = [m for m in modeles_installes if m]
    if _MODELE_FORCE and _MODELE_FORCE in noms:
        return _MODELE_FORCE
    for pref in _PREFERENCES:
        for nom in noms:
            if nom.lower().startswith(pref):
                return nom
    return noms[0] if noms else ""


def modeles_installes(timeout: float = 4.0) -> list[str]:
    """Liste les modeles Ollama installes (/api/tags). [] si Ollama injoignable."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=timeout)
        if r.status_code != 200:
            return []
        return [m.get("name", "") for m in r.json().get("models", []) if m.get("name")]
    except Exception:  # noqa: BLE001 - Ollama down
        return []


def modele_actif() -> str:
    """Le modele de code qui sera utilise (selon ce qui est installe), ou ""."""
    return _choisir_modele(modeles_installes())


def repondre(prompt: str, historique: list[dict] | None = None,
             modele: str | None = None) -> tuple[str, bool]:
    """Repond a une question de code via Ollama. (texte, succes).

    historique : liste de {role: "user"|"assistant", content: str} (tours precedents).
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return "Message vide.", False
    mod = modele or _MODELE_FORCE or _choisir_modele(modeles_installes())
    if not mod:
        return ("Aucun modele local detecte. Lance Ollama et installe un modele "
                "de code (ex: ollama pull deepseek-coder-v2:lite)."), False

    messages = [{"role": "system", "content": _SYSTEM}]
    for tour in (historique or [])[-8:]:
        role = tour.get("role")
        contenu = tour.get("content")
        if role in ("user", "assistant") and contenu:
            messages.append({"role": role, "content": contenu})
    messages.append({"role": "user", "content": prompt})

    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={"model": mod, "messages": messages, "stream": False},
            timeout=180,
        )
    except Exception as e:  # noqa: BLE001
        return f"Modele local injoignable ({e}). Verifie qu'Ollama tourne.", False
    if r.status_code != 200:
        return f"Erreur Ollama {r.status_code}.", False
    try:
        contenu = (r.json().get("message", {}).get("content", "") or "").strip()
    except Exception:  # noqa: BLE001
        return "Reponse Ollama illisible.", False
    return (contenu or "(reponse vide)"), True
