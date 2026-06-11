"""Pont OpenClaw : lier Jarvis a un agent OpenClaw local.

OpenClaw (https://docs.openclaw.ai, ex-Clawdbot/Moltbot) est un assistant IA
personnel open-source qui tourne sur ta machine : un Gateway Node.js (port
18789 par defaut, loopback) connecte un agent a WhatsApp, Telegram, Discord,
Signal, iMessage, etc. Ce module relie Jarvis a ce gateway :

- "demande a openclaw <tache>" / "delegue <tache> a openclaw"
  -> appel SYNCHRONE via l'endpoint compatible OpenAI du gateway
     (POST /v1/chat/completions, model="openclaw"), reponse vocalisee.
     Le champ `user` fixe ("conv:jarvis") donne une session stable cote
     OpenClaw : le contexte est conserve entre les demandes de Jarvis.
- "envoie a openclaw <message>" / "dis a openclaw <message>"
  -> fire-and-forget via le webhook POST /hooks/agent : OpenClaw lance un
     tour d'agent isole et livre sa reponse sur ses propres canaux
     (deliver=true, channel="last"). Jarvis confirme juste la transmission.
- "previens openclaw que <texte>" / "signale a openclaw <texte>"
  -> POST /hooks/wake : simple evenement systeme enfile dans la session
     principale de l'agent (pas de tour d'agent dedie).
- "statut openclaw" -> GET /health (liveness, non authentifie).

Pre-requis (.env, tout optionnel — sans config le module est inactif) :
- OPENCLAW_URL         : URL de base du gateway (defaut http://127.0.0.1:18789).
- OPENCLAW_TOKEN       : token du gateway (gateway.auth.token) pour l'endpoint
                         OpenAI. Cote OpenClaw, activer l'endpoint via
                         gateway.http.endpoints.chatCompletions.enabled=true.
- OPENCLAW_HOOKS_TOKEN : token des webhooks (hooks.token, DISTINCT du token
                         gateway) pour /hooks/agent et /hooks/wake. Cote
                         OpenClaw : hooks.enabled=true + hooks.token defini.
- OPENCLAW_AGENT_ID    : (optionnel) id d'agent cible ("openclaw/<id>").

Securite : le token gateway = acces operateur complet sur OpenClaw. On ne le
loggue jamais, et le gateway doit rester en loopback (defaut OpenClaw).

Contrat identique aux autres modules d'action (meross, browser, spotify) :
- disponible() -> bool
- async_executer(cmd) -> (reponse, succes) ou (None, False) si non reconnu /
  non configure. Aucune exception n'est jamais propagee : la chaine de
  fallback de main2.py doit toujours pouvoir continuer.

Les appels reseau bloquants passent par asyncio.to_thread pour ne pas geler
l'event loop (meme approche que messaging_bridge).
"""

from __future__ import annotations

import asyncio
import os
import re

# Import paresseux de requests : le module ne doit jamais casser l'import de
# main2 si la lib manque. On degrade proprement a l'usage.
try:  # pragma: no cover - depend de l'environnement
    import requests  # type: ignore
except Exception:  # noqa: BLE001
    requests = None  # type: ignore


# URL de base par defaut du gateway OpenClaw (instance locale, loopback).
_DEFAULT_URL = "http://127.0.0.1:18789"

# Timeout (s) de l'appel chat synchrone : un run d'agent OpenClaw peut durer
# (outils, reflexion). On laisse du temps sans bloquer Jarvis indefiniment.
_CHAT_TIMEOUT_S = 120

# Timeout (s) des appels courts (webhooks fire-and-forget, statut).
_COURT_TIMEOUT_S = 10

# Longueur max de la reponse vocalisee par Jarvis (le surplus est tronque :
# une reponse d'agent peut etre tres longue, la voix doit rester ecoutable).
_MAX_VOCAL_LEN = 600

# Cle de session stable cote gateway : les demandes successives de Jarvis
# partagent la meme session agent OpenClaw (contexte conserve la-bas).
_SESSION_USER = "conv:jarvis"

# True une fois l'avertissement "tokens identiques" emis (une seule fois).
_TOKENS_VERIFIES = False


# ============================================================
# Configuration / disponibilite
# ============================================================

def _base_url() -> str:
    """URL de base du gateway, sans slash final (defaut instance locale)."""
    url = (os.getenv("OPENCLAW_URL") or "").strip() or _DEFAULT_URL
    return url.rstrip("/")


def _token_gateway() -> str | None:
    """Token du gateway (gateway.auth.token) — endpoint OpenAI /v1/*."""
    return (os.getenv("OPENCLAW_TOKEN") or "").strip() or None


def _token_hooks() -> str | None:
    """Token des webhooks (hooks.token) — endpoints /hooks/*."""
    return (os.getenv("OPENCLAW_HOOKS_TOKEN") or "").strip() or None


def _model_cible() -> str:
    """Cible d'agent OpenClaw : "openclaw" ou "openclaw/<OPENCLAW_AGENT_ID>"."""
    agent_id = (os.getenv("OPENCLAW_AGENT_ID") or "").strip()
    return f"openclaw/{agent_id}" if agent_id else "openclaw"


def disponible() -> bool:
    """True si au moins un des deux tokens est configure et requests importable."""
    if requests is None:
        return False
    return _token_gateway() is not None or _token_hooks() is not None


def _avertir_si_tokens_identiques() -> None:
    """Avertit (une fois) si le meme secret sert au gateway ET aux hooks.

    OpenClaw recommande deux tokens distincts : reutiliser le token gateway
    (acces operateur complet) comme token de webhook elargit inutilement la
    surface d'attaque.
    """
    global _TOKENS_VERIFIES
    if _TOKENS_VERIFIES:
        return
    _TOKENS_VERIFIES = True
    tg, th = _token_gateway(), _token_hooks()
    if tg and th and tg == th:
        print("[OPENCLAW] AVERTISSEMENT : OPENCLAW_TOKEN et OPENCLAW_HOOKS_TOKEN "
              "sont identiques. OpenClaw recommande des secrets distincts "
              "(gateway.auth.token != hooks.token).")


# ============================================================
# Appels HTTP gateway (sync, deportes dans to_thread)
# ============================================================

def _chat_sync(message: str) -> tuple[str | None, str | None]:
    """Envoie un message a l'agent et attend sa reponse (BLOQUANT — to_thread).

    Utilise l'endpoint compatible OpenAI du gateway OpenClaw
    (POST /v1/chat/completions). Le champ `model` est une cible d'agent
    OpenClaw, pas un modele LLM. Le champ `user` stable conserve le contexte
    de conversation cote gateway entre les appels.

    Returns:
        (texte_reponse, None) en cas de succes, (None, erreur_lisible) sinon.
        Jamais d'exception propagee.
    """
    token = _token_gateway()
    if requests is None:
        return None, "la librairie requests est indisponible"
    if not token:
        return None, "OPENCLAW_TOKEN absent (token du gateway requis)"
    try:
        resp = requests.post(
            f"{_base_url()}/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "model": _model_cible(),
                "user": _SESSION_USER,
                "messages": [{"role": "user", "content": message}],
            },
            timeout=_CHAT_TIMEOUT_S,
        )
        if resp.status_code == 401:
            return None, "token refuse (verifie OPENCLAW_TOKEN = gateway.auth.token)"
        if resp.status_code == 404:
            return None, (
                "endpoint OpenAI desactive cote OpenClaw (mets "
                "gateway.http.endpoints.chatCompletions.enabled a true "
                "dans ~/.openclaw/openclaw.json)"
            )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            return None, "reponse inattendue du gateway"
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return None, "reponse vide du gateway"
        message_obj = choices[0].get("message") if isinstance(choices[0], dict) else None
        contenu = message_obj.get("content") if isinstance(message_obj, dict) else None
        if not isinstance(contenu, str) or not contenu.strip():
            return None, "reponse vide de l'agent"
        return contenu.strip(), None
    except Exception as e:  # noqa: BLE001
        return None, f"gateway injoignable ({e})"


def _hook_agent_sync(message: str) -> tuple[bool, str | None]:
    """Declenche un tour d'agent en tache de fond (BLOQUANT — to_thread).

    POST /hooks/agent : OpenClaw lance une session agent isolee et LIVRE sa
    reponse sur le dernier canal utilise (deliver=true, channel="last") —
    WhatsApp, Telegram, etc. On n'attend pas la reponse de l'agent ici,
    seulement l'acquittement du webhook.

    Returns:
        (True, None) si le webhook a accepte, (False, erreur_lisible) sinon.
    """
    token = _token_hooks()
    if requests is None:
        return False, "la librairie requests est indisponible"
    if not token:
        return False, "OPENCLAW_HOOKS_TOKEN absent (hooks.token requis)"
    try:
        resp = requests.post(
            f"{_base_url()}/hooks/agent",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "message": message,
                "name": "Jarvis",
                "deliver": True,
                "channel": "last",
            },
            timeout=_COURT_TIMEOUT_S,
        )
        if resp.status_code == 401:
            return False, "token refuse (verifie OPENCLAW_HOOKS_TOKEN = hooks.token)"
        if resp.status_code == 404:
            return False, (
                "webhooks desactives cote OpenClaw (mets hooks.enabled a true "
                "et definis hooks.token dans ~/.openclaw/openclaw.json)"
            )
        resp.raise_for_status()
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, f"gateway injoignable ({e})"


def _hook_wake_sync(texte: str) -> tuple[bool, str | None]:
    """Enfile un evenement systeme dans la session principale (BLOQUANT).

    POST /hooks/wake : simple signal ({"text": ..., "mode": "now"}), sans
    tour d'agent dedie. L'agent OpenClaw le verra a son prochain reveil.
    """
    token = _token_hooks()
    if requests is None:
        return False, "la librairie requests est indisponible"
    if not token:
        return False, "OPENCLAW_HOOKS_TOKEN absent (hooks.token requis)"
    try:
        resp = requests.post(
            f"{_base_url()}/hooks/wake",
            headers={"Authorization": f"Bearer {token}"},
            json={"text": texte, "mode": "now"},
            timeout=_COURT_TIMEOUT_S,
        )
        if resp.status_code == 401:
            return False, "token refuse (verifie OPENCLAW_HOOKS_TOKEN = hooks.token)"
        if resp.status_code == 404:
            return False, (
                "webhooks desactives cote OpenClaw (mets hooks.enabled a true "
                "et definis hooks.token dans ~/.openclaw/openclaw.json)"
            )
        resp.raise_for_status()
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, f"gateway injoignable ({e})"


def _statut_sync() -> bool:
    """True si le gateway OpenClaw repond (GET /health, liveness sans auth)."""
    if requests is None:
        return False
    try:
        resp = requests.get(f"{_base_url()}/health", timeout=_COURT_TIMEOUT_S)
        # Liveness : toute reponse HTTP < 500 suffit (certaines versions
        # servent le Control UI au lieu d'un JSON — le process ecoute).
        return resp.status_code < 500
    except Exception:  # noqa: BLE001
        return False


# ============================================================
# Detection des commandes vocales
# ============================================================

# "openclaw" se prononce/transcrit de plusieurs facons : on tolere l'espace
# ("open claw") et les variantes phonetiques courantes de la reconnaissance FR.
_NOM = r"(?:open\s?claw|open\s?clo|openclo)"

# Demande synchrone : "demande a openclaw de ranger mes mails",
# "demande a open claw : resume mes messages whatsapp".
_RE_DEMANDE = re.compile(
    rf"\bdemande\s+(?:a|à)\s+{_NOM}\s*(?:de\s+|d'|:\s*)?(?P<tache>.+)$",
    re.IGNORECASE,
)

# Delegation synchrone alternative : "delegue X a openclaw", "confie X a openclaw".
_RE_DELEGUE = re.compile(
    rf"\b(?:d[eé]l[eè]gue|confie)\s+(?P<tache>.+?)\s+(?:a|à)\s+{_NOM}\s*$",
    re.IGNORECASE,
)

# Fire-and-forget (tour d'agent isole, reponse sur les canaux OpenClaw) :
# "envoie a openclaw <message>", "dis a openclaw <message>".
_RE_ENVOIE = re.compile(
    rf"\b(?:envoie|dis|transmets?)\s+(?:a|à)\s+{_NOM}\s*(?:que\s+|de\s+|d'|:\s*)?(?P<message>.+)$",
    re.IGNORECASE,
)

# Signal simple (/hooks/wake) : "previens openclaw que X", "signale a openclaw X".
_RE_PREVIENS = re.compile(
    rf"\b(?:pr(?:e|é)viens|signale)\s+(?:(?:a|à)\s+)?{_NOM}\s*(?:que\s+|:\s*)?(?P<texte>.+)$",
    re.IGNORECASE,
)

# Statut : "statut openclaw", "openclaw status", "est-ce qu'openclaw tourne".
_RE_STATUT = re.compile(
    rf"\b(?:statut|status)\b.*{_NOM}"
    rf"|{_NOM}.*\b(?:statut|status|tourne|marche|fonctionne|en\s+ligne|est\s+(?:la|là|actif))\b",
    re.IGNORECASE,
)


# ============================================================
# Point d'entree module d'action
# ============================================================

async def async_executer(cmd: str) -> tuple[str | None, bool]:
    """Execute une commande OpenClaw si elle est reconnue.

    Args:
        cmd: La commande utilisateur brute (texte issu de la voix ou du chat).

    Returns:
        (reponse, succes) si la commande concerne OpenClaw, (None, False)
        sinon — la chaine d'actions de main2 continue alors normalement.
    """
    texte = (cmd or "").strip()
    if not texte:
        return None, False

    # Tri rapide : si le nom n'apparait nulle part, ce n'est pas pour nous.
    if not re.search(_NOM, texte, re.IGNORECASE):
        return None, False

    if not disponible():
        return (
            "OpenClaw n'est pas configure. Renseigne OPENCLAW_TOKEN ou "
            "OPENCLAW_HOOKS_TOKEN dans la section Vue d'ensemble du dashboard.",
            False,
        )
    _avertir_si_tokens_identiques()

    # Statut d'abord (les autres regex pourraient matcher "statut..." comme tache).
    if _RE_STATUT.search(texte):
        ok = await asyncio.to_thread(_statut_sync)
        if ok:
            return "Le gateway OpenClaw est en ligne et repond.", True
        return (
            "Le gateway OpenClaw ne repond pas. Verifie qu'il tourne "
            "(openclaw gateway status).",
            False,
        )

    # Signal simple AVANT le fire-and-forget ("previens/signale").
    m = _RE_PREVIENS.search(texte)
    if m:
        contenu = m.group("texte").strip()
        if not contenu:
            return "Que dois-je signaler a OpenClaw ?", False
        ok, erreur = await asyncio.to_thread(_hook_wake_sync, contenu)
        if ok:
            return "OpenClaw est prevenu.", True
        return f"Echec du signal a OpenClaw : {erreur}.", False

    # Fire-and-forget AVANT la demande synchrone ("envoie/dis/transmets").
    m = _RE_ENVOIE.search(texte)
    if m:
        message = m.group("message").strip()
        if not message:
            return "Que dois-je envoyer a OpenClaw ?", False
        ok, erreur = await asyncio.to_thread(_hook_agent_sync, message)
        if ok:
            return ("C'est transmis a OpenClaw, il s'en occupe et repondra "
                    "sur tes canaux habituels."), True
        return f"Echec de l'envoi a OpenClaw : {erreur}.", False

    # Demande synchrone : on attend la reponse et on la vocalise.
    m = _RE_DEMANDE.search(texte) or _RE_DELEGUE.search(texte)
    if m:
        tache = m.group("tache").strip()
        if not tache:
            return "Que dois-je demander a OpenClaw ?", False
        reponse, erreur = await asyncio.to_thread(_chat_sync, tache)
        if reponse is None:
            return f"OpenClaw n'a pas pu repondre : {erreur}.", False
        if len(reponse) > _MAX_VOCAL_LEN:
            reponse = reponse[:_MAX_VOCAL_LEN] + "... La suite est sur tes canaux OpenClaw."
        return reponse, True

    # Le nom apparait mais aucune forme reconnue : on laisse la chaine continuer
    # (l'IA generale repondra, p.ex. "c'est quoi openclaw ?").
    return None, False


# ============================================================
# API directe (utilisee par le tool Gemini ask_openclaw)
# ============================================================

async def demander(message: str) -> tuple[str, bool]:
    """Envoie un message a l'agent OpenClaw et renvoie sa reponse.

    Args:
        message: La tache/question a transmettre a l'agent.

    Returns:
        (reponse_ou_erreur_lisible, succes). Jamais d'exception propagee.
    """
    message = (message or "").strip()
    if not message:
        return "Message vide.", False
    if _token_gateway() is None or requests is None:
        return "OpenClaw n'est pas configure (OPENCLAW_TOKEN absent).", False
    reponse, erreur = await asyncio.to_thread(_chat_sync, message)
    if reponse is None:
        return f"Echec OpenClaw : {erreur}.", False
    return reponse, True
