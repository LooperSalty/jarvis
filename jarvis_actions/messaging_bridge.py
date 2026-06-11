"""Pont de messagerie : parler a Jarvis depuis Telegram + notifications Discord.

Deux directions :
- Telegram (entrant) : un bot Telegram fait du long-polling `getUpdates` et relaie
  chaque message texte recu a Jarvis via un callable async injecte par main2.
  La reponse textuelle de Jarvis est renvoyee dans le chat via `sendMessage`.
- Discord (sortant) : un simple POST sur un webhook permet a Jarvis d'envoyer
  une notification (ex : "tache Claude Code terminee").

Pre-requis (tout optionnel, lus via os.getenv) :
- TELEGRAM_BOT_TOKEN : token du bot (BotFather). Active le bridge Telegram.
- TELEGRAM_CHAT_ID  : (optionnel) restreint les reponses a ce chat. Si absent,
  Jarvis repond a TOUT chat (un avertissement est logge).
- DISCORD_WEBHOOK_URL : URL de webhook Discord. Active les notifications sortantes.

Aucune dependance lourde : on utilise `requests` (deja present pour le reste du
projet) plutot qu'une lib bot dediee. Les appels reseau bloquants sont deportes
dans `asyncio.to_thread` pour ne pas geler l'event loop principal.
"""

from __future__ import annotations

import asyncio
import os
from typing import Awaitable, Callable

# Import paresseux de requests : la lib est optionnelle au sens ou le module ne
# doit jamais casser l'import de main2 si elle manque. On la resout au moment de
# l'usage et on degrade proprement.
try:  # pragma: no cover - depend de l'environnement
    import requests  # type: ignore
except Exception:  # noqa: BLE001
    requests = None  # type: ignore


# Base de l'API Telegram (le token est interpole a l'usage, jamais en dur).
_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

# Timeout du long-polling getUpdates cote serveur Telegram (secondes).
_LONGPOLL_TIMEOUT_S = 30

# Timeout de la requete HTTP cote client : un peu plus que le long-poll pour
# laisser Telegram repondre meme quand il garde la connexion ouverte.
_HTTP_TIMEOUT_S = _LONGPOLL_TIMEOUT_S + 10

# Backoff (secondes) applique apres une erreur reseau, borne pour ne pas
# attendre indefiniment.
_BACKOFF_MIN_S = 2.0
_BACKOFF_MAX_S = 60.0

# Telegram limite un message a ~4096 caracteres ; on tronque sous cette borne.
_TELEGRAM_MAX_LEN = 4000


# ============================================================
# Disponibilite
# ============================================================

def telegram_disponible() -> bool:
    """True si un token de bot Telegram est configure (et requests importable)."""
    return bool(_token()) and requests is not None


def discord_disponible() -> bool:
    """True si une URL de webhook Discord est configuree (et requests importable)."""
    return bool(_webhook_url()) and requests is not None


def _token() -> str | None:
    """Token du bot Telegram (None si absent ou vide)."""
    return (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip() or None


def _chat_id_autorise() -> str | None:
    """Chat ID autorise pour filtrer les messages entrants (None = tous)."""
    return (os.getenv("TELEGRAM_CHAT_ID") or "").strip() or None


def _webhook_url() -> str | None:
    """URL du webhook Discord (None si absente ou vide)."""
    return (os.getenv("DISCORD_WEBHOOK_URL") or "").strip() or None


# ============================================================
# Parsing du payload getUpdates
# ============================================================

def _extraire_messages(payload: dict) -> list[tuple[int, str, str]]:
    """Extrait les messages texte d'une reponse `getUpdates`.

    Args:
        payload: dict JSON renvoye par l'API Telegram. Forme attendue :
            ``{"ok": true, "result": [{"update_id": N, "message": {...}}, ...]}``.

    Returns:
        Liste de tuples ``(update_id, chat_id, texte)``. Les updates sans champ
        texte (stickers, photos, edits non geres...) sont ignores. ``chat_id``
        est renvoye en str pour comparer facilement avec TELEGRAM_CHAT_ID.
        Renvoie une liste vide si le payload est malforme — jamais d'exception.
    """
    messages: list[tuple[int, str, str]] = []
    if not isinstance(payload, dict):
        return messages
    if not payload.get("ok"):
        return messages
    results = payload.get("result")
    if not isinstance(results, list):
        return messages

    for update in results:
        if not isinstance(update, dict):
            continue
        update_id = update.get("update_id")
        if not isinstance(update_id, int):
            continue
        # Telegram envoie soit "message", soit "edited_message" ; on prend les deux.
        message = update.get("message")
        if not isinstance(message, dict):
            message = update.get("edited_message")
        if not isinstance(message, dict):
            continue
        texte = message.get("text")
        if not isinstance(texte, str) or not texte.strip():
            continue
        chat = message.get("chat")
        if not isinstance(chat, dict):
            continue
        chat_id = chat.get("id")
        if chat_id is None:
            continue
        messages.append((update_id, str(chat_id), texte.strip()))

    return messages


# ============================================================
# Appels HTTP Telegram (sync, deportes dans to_thread)
# ============================================================

def _get_updates_sync(token: str, offset: int | None) -> dict:
    """Long-polling `getUpdates` (BLOQUANT — a appeler via asyncio.to_thread).

    Renvoie le payload JSON, ou un dict d'erreur ``{"ok": False, ...}`` en cas
    d'echec reseau (jamais d'exception propagee).
    """
    if requests is None:
        return {"ok": False, "error": "requests indisponible"}
    url = _TELEGRAM_API.format(token=token, method="getUpdates")
    params: dict[str, object] = {"timeout": _LONGPOLL_TIMEOUT_S}
    if offset is not None:
        params["offset"] = offset
    try:
        resp = requests.get(url, params=params, timeout=_HTTP_TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            return data
        return {"ok": False, "error": "reponse non-dict"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _send_message_sync(token: str, chat_id: str, texte: str) -> bool:
    """Envoie un message via `sendMessage` (BLOQUANT — via asyncio.to_thread).

    Renvoie True si l'envoi reussit, False sinon. Jamais d'exception propagee.
    """
    if requests is None:
        return False
    url = _TELEGRAM_API.format(token=token, method="sendMessage")
    contenu = (texte or "").strip() or "(reponse vide)"
    if len(contenu) > _TELEGRAM_MAX_LEN:
        contenu = contenu[:_TELEGRAM_MAX_LEN] + " [...]"
    payload = {"chat_id": chat_id, "text": contenu}
    try:
        resp = requests.post(url, json=payload, timeout=_HTTP_TIMEOUT_S)
        resp.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[TELEGRAM] Echec sendMessage : {e}")
        return False


# ============================================================
# Boucle Telegram (entrant)
# ============================================================

async def demarrer_telegram(
    executer_commande_texte: Callable[[str], Awaitable[str]],
) -> None:
    """Boucle long-polling Telegram : relaie chaque message texte a Jarvis.

    Args:
        executer_commande_texte: callable async ``fn(texte) -> str`` fourni par
            main2. Execute le texte comme une commande utilisateur et renvoie la
            reponse textuelle de Jarvis (vocalisee aussi cote PC le cas echeant).

    Comportement :
    - Filtre par TELEGRAM_CHAT_ID si defini ; sinon repond a tout chat (warning).
    - Backoff progressif sur erreur reseau ; la boucle ne meurt jamais.
    - Confirme la reception des updates via le mecanisme `offset` (acquittement).

    Ne fait rien (retour immediat) si Telegram n'est pas configure.
    """
    token = _token()
    if not token:
        print("[TELEGRAM] TELEGRAM_BOT_TOKEN absent : bridge desactive.")
        return
    if requests is None:
        print("[TELEGRAM] 'requests' indisponible : bridge desactive "
              "(pip install requests).")
        return

    chat_autorise = _chat_id_autorise()
    if chat_autorise is None:
        print("[TELEGRAM] AVERTISSEMENT : TELEGRAM_CHAT_ID non defini — Jarvis "
              "repondra a N'IMPORTE QUEL chat. Definis TELEGRAM_CHAT_ID pour "
              "restreindre l'acces.")
    else:
        print(f"[TELEGRAM] Bridge actif (chat autorise : {chat_autorise}).")

    offset: int | None = None
    backoff = _BACKOFF_MIN_S

    while True:
        try:
            payload = await asyncio.to_thread(_get_updates_sync, token, offset)
            if not payload.get("ok"):
                # Erreur reseau ou API : backoff puis on reessaie.
                erreur = payload.get("error", "erreur inconnue")
                print(f"[TELEGRAM] getUpdates en echec ({erreur}), "
                      f"nouvelle tentative dans {backoff:.0f}s.")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX_S)
                continue

            # Succes : on reinitialise le backoff.
            backoff = _BACKOFF_MIN_S
            messages = _extraire_messages(payload)

            for update_id, chat_id, texte in messages:
                # Acquittement : avancer l'offset au-dela de cet update, meme si
                # on l'ignore ensuite (evite de le retraiter en boucle).
                offset = update_id + 1

                if chat_autorise is not None and chat_id != chat_autorise:
                    print(f"[TELEGRAM] Message ignore (chat {chat_id} non "
                          f"autorise).")
                    continue

                try:
                    reponse = await executer_commande_texte(texte)
                except Exception as e:  # noqa: BLE001
                    print(f"[TELEGRAM] Erreur execution commande : {e}")
                    reponse = "Desole, une erreur interne m'a empeche de traiter ta demande."

                await asyncio.to_thread(
                    _send_message_sync, token, chat_id, reponse or "(reponse vide)"
                )

        except asyncio.CancelledError:
            # Arret propre demande (shutdown) : on relaie l'annulation.
            print("[TELEGRAM] Bridge arrete.")
            raise
        except Exception as e:  # noqa: BLE001
            # Filet de securite : aucune exception ne doit tuer la boucle.
            print(f"[TELEGRAM] Erreur inattendue dans la boucle : {e}, "
                  f"reprise dans {backoff:.0f}s.")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX_S)


# ============================================================
# Notification Discord (sortant)
# ============================================================

def notifier_discord(texte: str) -> bool:
    """Envoie une notification sur le webhook Discord (sync, jamais d'exception).

    Args:
        texte: contenu du message a poster.

    Returns:
        True si le POST a reussi, False sinon (webhook absent, requests manquant,
        erreur reseau, etc.).
    """
    url = _webhook_url()
    if not url:
        return False
    if requests is None:
        print("[DISCORD] 'requests' indisponible : notification ignoree.")
        return False

    contenu = (texte or "").strip()
    if not contenu:
        return False
    # Discord limite le champ "content" a 2000 caracteres.
    if len(contenu) > 2000:
        contenu = contenu[:1990] + " [...]"

    try:
        resp = requests.post(url, json={"content": contenu}, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[DISCORD] Echec notification : {e}")
        return False
