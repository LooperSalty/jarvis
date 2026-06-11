"""Gestion du token d'appairage WebSocket de Jarvis.

Le serveur WebSocket (ws://0.0.0.0:8765) auto-authentifie les clients
loopback (le PC lui-meme : orbe + dashboard). Les clients distants
(mobile / LAN) doivent presenter un token avant toute commande.

Ce module fournit ce token, persiste localement, jamais versionne.
Source de verite par ordre de priorite :
    1. variable d'environnement JARVIS_WS_TOKEN (si non vide)
    2. fichier TOKEN_PATH (jarvis_ws_token.txt, a cote de l'exe ou racine repo)
    3. generation auto (secrets.token_urlsafe), persistee atomiquement

Aucune fonction de ce module ne propage d'exception destinee a tuer
main2.py : tout est attrape et journalise. Le pire cas degrade reste un
token genere en memoire (utilisable le temps de la session).
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path


def _dossier_donnees() -> Path:
    """Dossier ou lire/ecrire le token. A cote de l'exe en mode PyInstaller
    (sys._MEIPASS est temporaire), sinon racine du repo. Meme pattern que
    jarvis_profile._dossier_donnees pour la persistance entre lancements."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


TOKEN_PATH: Path = _dossier_donnees() / "jarvis_ws_token.txt"

# Nombre d'octets d'entropie passes a secrets.token_urlsafe.
_TOKEN_OCTETS = 24

# Cache memoire du token courant (mempise). None tant qu'il n'est pas resolu.
_token_cache: str | None = None


def _lire_fichier() -> str:
    """Lit TOKEN_PATH et retourne son contenu trime, ou "" si absent/illisible.

    Jamais d'exception : fichier manquant, droits, encodage -> "".
    """
    try:
        if not TOKEN_PATH.exists():
            return ""
        with open(TOKEN_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        print(f"[SECURITY] Lecture token impossible ({e})")
        return ""


def _ecrire_fichier(token: str) -> bool:
    """Ecrit le token sur disque (ecriture atomique .tmp + os.replace).

    Retourne True si l'ecriture a reussi, False sinon. Jamais d'exception.
    """
    tmp_path = TOKEN_PATH.with_name(TOKEN_PATH.name + ".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(token)
        os.replace(tmp_path, TOKEN_PATH)
        return True
    except Exception as e:
        print(f"[SECURITY] Echec ecriture token : {e}")
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        return False


def _generer() -> str:
    """Genere un nouveau token aleatoire url-safe."""
    return secrets.token_urlsafe(_TOKEN_OCTETS)


def get_ws_token() -> str:
    """Retourne le token d'appairage WebSocket courant (memoise).

    Ordre de resolution :
        1. os.environ["JARVIS_WS_TOKEN"] si non vide ;
        2. contenu de TOKEN_PATH si non vide ;
        3. token genere aleatoirement, persiste atomiquement.

    Le resultat est mis en cache pour les appels suivants. Jamais d'exception.
    """
    global _token_cache
    if _token_cache:
        return _token_cache

    # 1. Variable d'environnement prioritaire (override explicite).
    env_token = (os.environ.get("JARVIS_WS_TOKEN") or "").strip()
    if env_token:
        _token_cache = env_token
        return _token_cache

    # 2. Fichier persiste.
    fichier_token = _lire_fichier()
    if fichier_token:
        _token_cache = fichier_token
        return _token_cache

    # 3. Generation + persistance (best effort : on garde le token en memoire
    #    meme si l'ecriture disque echoue, pour rester operationnel).
    nouveau = _generer()
    _ecrire_fichier(nouveau)
    _token_cache = nouveau
    return _token_cache


def verifier_token(t: str) -> bool:
    """Compare t au token courant en temps constant (secrets.compare_digest).

    Retourne False si t est vide ou ne correspond pas. Jamais d'exception.
    """
    try:
        if not t:
            return False
        return secrets.compare_digest(str(t), get_ws_token())
    except Exception as e:
        print(f"[SECURITY] Echec verification token ({e})")
        return False


def regenerer_token() -> str:
    """Genere un nouveau token, le persiste, reinitialise le cache, le retourne.

    Invalide tous les appairages distants existants. Jamais d'exception.
    """
    global _token_cache
    nouveau = _generer()
    _ecrire_fichier(nouveau)
    _token_cache = nouveau
    return _token_cache


def token_masque() -> str:
    """Version affichable masquee du token courant pour les logs.

    Exemple : "abcd...wxyz". Ne revele jamais le token complet. Pour un token
    tres court, retourne une suite d'asterisques. Jamais d'exception.
    """
    try:
        token = get_ws_token()
        if not token:
            return ""
        if len(token) <= 8:
            return "*" * len(token)
        return f"{token[:4]}...{token[-4:]}"
    except Exception as e:
        print(f"[SECURITY] Echec masquage token ({e})")
        return ""
