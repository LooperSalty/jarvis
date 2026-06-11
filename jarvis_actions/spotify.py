"""Controle de Spotify via l'API officielle (spotipy).

Approche : detection locale par mots-cles FR, puis appels a l'API Web Spotify
(play/pause/next/previous/recherche+lecture/volume). Aucun clic pixel.

Pre-requis :
- pip install spotipy
- .env : SPOTIFY_CLIENT_ID=... SPOTIFY_CLIENT_SECRET=...
- Optionnel : SPOTIFY_REDIRECT_URI (defaut http://127.0.0.1:8888/callback)

Le client spotipy est importe paresseusement (try/except) et memoise au premier
appel reussi. Le token OAuth est mis en cache dans un fichier local gitignore
(.spotify_cache, a cote de l'exe si frozen, sinon a cote de ce module).

Contrat identique aux autres modules d'action :
- disponible() -> bool
- executer(cmd) -> (reponse, succes) ou (None, False) si non reconnu / non configure.

Aucune exception n'est jamais propagee : la chaine de fallback de main2.py doit
toujours pouvoir continuer.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from jarvis_config import USER_NAME

# Scope minimal pour piloter la lecture
_SCOPE = "user-modify-playback-state user-read-playback-state"
_DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"

# Client spotipy memoise (None tant que pas initialise / si echec).
_CLIENT = None
# Sentinelle : True si une tentative d'init a deja echoue (evite de re-tenter
# l'OAuth en boucle a chaque commande).
_INIT_FAILED = False


def _cache_path() -> Path:
    """Chemin du cache token OAuth. A cote de l'exe si frozen, sinon du module."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent.parent
    return base / ".spotify_cache"


def disponible() -> bool:
    """True si les identifiants Spotify sont definis ET spotipy est importable."""
    if not os.getenv("SPOTIFY_CLIENT_ID") or not os.getenv("SPOTIFY_CLIENT_SECRET"):
        return False
    try:
        import spotipy  # noqa: F401
    except Exception:
        return False
    return True


def _get_client():
    """Retourne le client spotipy memoise, ou None si indisponible / echec.

    L'import de spotipy est paresseux. L'OAuth utilise un cache fichier local
    pour eviter de redemander l'autorisation a chaque session.
    """
    global _CLIENT, _INIT_FAILED
    if _CLIENT is not None:
        return _CLIENT
    if _INIT_FAILED:
        return None

    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        _INIT_FAILED = True
        return None

    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth

        redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", _DEFAULT_REDIRECT_URI)
        auth = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=_SCOPE,
            cache_path=str(_cache_path()),
            open_browser=False,
        )
        _CLIENT = spotipy.Spotify(auth_manager=auth)
        return _CLIENT
    except Exception as e:
        print(f"[SPOTIFY] Init impossible : {e}")
        _INIT_FAILED = True
        return None


def _device_actif(client) -> str | None:
    """Retourne l'id du device actif, ou None s'il n'y en a aucun."""
    try:
        info = client.current_playback()
        if info and info.get("device"):
            return info["device"].get("id")
    except Exception:
        pass
    # Repli : on prend le premier device disponible si aucun n'est "actif"
    try:
        devices = client.devices().get("devices", [])
        for d in devices:
            if d.get("is_active"):
                return d.get("id")
        if devices:
            return devices[0].get("id")
    except Exception:
        pass
    return None


_MSG_PAS_DE_DEVICE = (
    "Aucun appareil Spotify actif, {user}. Ouvre Spotify sur un appareil "
    "et relance la lecture."
)


def _play(client, query: str | None) -> tuple[str, bool]:
    """Lance la lecture. Si query est fourni, recherche puis joue le 1er resultat,
    sinon reprend la lecture courante."""
    device_id = _device_actif(client)
    if device_id is None:
        return _MSG_PAS_DE_DEVICE.format(user=USER_NAME), False

    # Pas de titre -> simple reprise de lecture
    if not query:
        try:
            client.start_playback(device_id=device_id)
            return f"Lecture reprise, {USER_NAME}.", True
        except Exception as e:
            return f"Impossible de reprendre la lecture : {e}", False

    # Recherche du titre puis lecture du 1er resultat
    try:
        res = client.search(q=query, type="track", limit=1)
        items = (res or {}).get("tracks", {}).get("items", [])
        if not items:
            return f"Je n'ai rien trouve pour '{query}' sur Spotify.", False
        track = items[0]
        uri = track.get("uri")
        nom = track.get("name", query)
        artistes = ", ".join(a.get("name", "") for a in track.get("artists", []))
        client.start_playback(device_id=device_id, uris=[uri])
        if artistes:
            return f"Je lance {nom} de {artistes}, {USER_NAME}.", True
        return f"Je lance {nom}, {USER_NAME}.", True
    except Exception as e:
        return f"Erreur de lecture Spotify : {e}", False


def _pause(client) -> tuple[str, bool]:
    try:
        client.pause_playback()
        return f"Musique en pause, {USER_NAME}.", True
    except Exception as e:
        return f"Impossible de mettre en pause : {e}", False


def _resume(client) -> tuple[str, bool]:
    device_id = _device_actif(client)
    if device_id is None:
        return _MSG_PAS_DE_DEVICE.format(user=USER_NAME), False
    try:
        client.start_playback(device_id=device_id)
        return f"Je reprends la musique, {USER_NAME}.", True
    except Exception as e:
        return f"Impossible de reprendre : {e}", False


def _next(client) -> tuple[str, bool]:
    try:
        client.next_track()
        return f"Morceau suivant, {USER_NAME}.", True
    except Exception as e:
        return f"Impossible de passer au suivant : {e}", False


def _previous(client) -> tuple[str, bool]:
    try:
        client.previous_track()
        return f"Morceau precedent, {USER_NAME}.", True
    except Exception as e:
        return f"Impossible de revenir en arriere : {e}", False


def _volume(client, monter: bool) -> tuple[str, bool]:
    """Ajuste le volume Spotify de +/- 20 points (borne 0..100)."""
    try:
        info = client.current_playback()
        actuel = 50
        if info and info.get("device"):
            v = info["device"].get("volume_percent")
            if isinstance(v, int):
                actuel = v
        delta = 20 if monter else -20
        cible = max(0, min(100, actuel + delta))
        client.volume(cible)
        sens = "monte" if monter else "baisse"
        return f"Volume Spotify {sens} a {cible}%, {USER_NAME}.", True
    except Exception as e:
        return f"Impossible de regler le volume Spotify : {e}", False


# ============================================================
# Detection mots-cles FR
# ============================================================

# "joue/lance/mets <titre> sur spotify" ou "joue la musique sur spotify".
# Capture optionnelle du titre dans le groupe "titre".
_RE_PLAY = re.compile(
    r"\b(?:joue|lance|mets|met|met[ts]|jouer|lancer|mettre)\b\s+"
    r"(?P<titre>.+?)?"
    r"(?:\s+sur\s+spotify)?\s*$",
    re.IGNORECASE,
)

# Volume Spotify (teste AVANT le play generique car "monte/baisse" + "spotify")
_RE_VOL_UP = re.compile(
    r"\b(?:monte|augmente|plus fort)\b.*\b(?:son|volume)\b.*\bspotify\b",
    re.IGNORECASE,
)
_RE_VOL_DOWN = re.compile(
    r"\b(?:baisse|diminue|moins fort)\b.*\b(?:son|volume)\b.*\bspotify\b",
    re.IGNORECASE,
)

_RE_NEXT = re.compile(
    r"\b(?:musique|chanson|morceau|piste|titre)\s+suivante?\b|\bmorceau suivant\b|\bsuivant\b.*\bspotify\b",
    re.IGNORECASE,
)
_RE_PREV = re.compile(
    r"\b(?:musique|chanson|morceau|piste|titre)\s+pr[ée]c[ée]dente?\b"
    r"|\bmorceau pr[ée]c[ée]dent\b|\bpr[ée]c[ée]dent\b.*\bspotify\b",
    re.IGNORECASE,
)

# Mots de "reprise" explicite (distincts de pause)
_RE_RESUME = re.compile(r"\b(?:reprends|reprend|reprendre|relance la musique)\b", re.IGNORECASE)
_RE_PAUSE = re.compile(r"\b(?:pause|met[ts]? en pause|stoppe|arr[êe]te) ?(?:la musique|spotify)?\b", re.IGNORECASE)

# "la musique" generique a retirer du titre quand on dit "joue la musique"
_TITRE_GENERIQUE = re.compile(r"^(?:la\s+)?musique$", re.IGNORECASE)


def _nettoyer_titre(titre: str | None) -> str | None:
    """Normalise le titre capture. Retourne None si vide ou generique."""
    if not titre:
        return None
    t = titre.strip().strip("'\"").strip()
    # Retire un "sur spotify" residuel si la regex l'a laisse passer
    t = re.sub(r"\s+sur\s+spotify\s*$", "", t, flags=re.IGNORECASE).strip()
    if not t or _TITRE_GENERIQUE.match(t):
        return None
    return t


def executer(cmd: str) -> tuple[str | None, bool]:
    """Detecte une commande Spotify dans cmd. Renvoie (reponse, succes) ou
    (None, False) si non reconnu OU si Spotify n'est pas configure (la chaine
    de fallback prend alors le relais).

    Aucune exception n'est jamais propagee.
    """
    if not cmd:
        return None, False

    c = cmd.lower().strip()

    # Une commande n'est "Spotify" que si elle mentionne spotify, OU si c'est
    # un controle media generique (pause/suivant/precedent/reprends) qu'on veut
    # router vers Spotify quand il est configure. On reste prudent : on ne
    # capture le play que s'il y a "spotify" ou un mot musical explicite.
    mentionne_spotify = "spotify" in c

    # Determine l'intention SANS encore toucher au reseau, pour pouvoir rendre
    # (None, False) tot si rien ne matche.
    intention = None  # ("play", titre) | "pause" | "resume" | "next" | "prev" | ("vol", up)

    if _RE_VOL_UP.search(c):
        intention = ("vol", True)
    elif _RE_VOL_DOWN.search(c):
        intention = ("vol", False)
    elif _RE_NEXT.search(c) and (mentionne_spotify or "suivant" in c):
        intention = "next"
    elif _RE_PREV.search(c) and (mentionne_spotify or "précédent" in c or "precedent" in c):
        intention = "prev"
    elif _RE_RESUME.search(c):
        intention = "resume"
    elif _RE_PAUSE.search(c):
        intention = "pause"
    else:
        m = _RE_PLAY.search(c)
        # On ne route un "joue/mets X" vers Spotify que si "spotify" est
        # mentionne (sinon ca matcherait trop large et volerait des commandes
        # destinees a d'autres modules / a l'IA).
        if m and mentionne_spotify:
            # Recapture le titre depuis la chaine d'origine (casse preservee)
            titre = _nettoyer_titre(m.group("titre"))
            intention = ("play", titre)

    if intention is None:
        return None, False

    # A partir d'ici, on a une intention Spotify -> il faut un client.
    if not disponible():
        # Pas configure : on laisse la chaine de fallback gerer (None, False).
        return None, False

    client = _get_client()
    if client is None:
        return (
            f"Spotify n'est pas accessible pour le moment, {USER_NAME}.",
            False,
        )

    try:
        if isinstance(intention, tuple):
            kind = intention[0]
            if kind == "play":
                return _play(client, intention[1])
            if kind == "vol":
                return _volume(client, intention[1])
        if intention == "pause":
            return _pause(client)
        if intention == "resume":
            return _resume(client)
        if intention == "next":
            return _next(client)
        if intention == "prev":
            return _previous(client)
    except Exception as e:
        # Garde-fou ultime : jamais d'exception qui remonte vers main2.py.
        return f"Erreur Spotify : {e}", False

    return None, False
