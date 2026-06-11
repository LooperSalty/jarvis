"""Skill exemple : pile ou face.

Mots-cles : "pile ou face", "lance une piece" (accents geres via normalisation).
"""

from __future__ import annotations

import random
import unicodedata

SKILL = {
    "nom": "pile_ou_face",
    "description": "Lance une piece virtuelle et annonce pile ou face.",
    "version": "1.0.0",
}

# Mots-cles SANS accents : la commande est normalisee avant comparaison
_MOTS_CLES = (
    "pile ou face",
    "lance une piece",
    "lancer une piece",
    "lance la piece",
    "tire a pile ou face",
    "jouons a pile ou face",
)

_PHRASES = (
    "Roulement de tambour... c'est {resultat} !",
    "La piece tournoie dans les airs et retombe sur... {resultat} !",
    "Verdict de la gravite : {resultat}.",
    "J'ai lance la piece avec une precision toute robotique : {resultat} !",
    "Le hasard a parle : {resultat}.",
)


def _normaliser(texte: str) -> str:
    """Minuscules + suppression des accents (le STT renvoie 'pièce' accentue)."""
    decompose = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


def executer(cmd: str) -> tuple[str | None, bool]:
    """Detecte une demande de pile ou face. (None, False) si non reconnue."""
    try:
        c = _normaliser(cmd or "")
        if not any(mot in c for mot in _MOTS_CLES):
            return None, False
        resultat = random.choice(("pile", "face"))
        return random.choice(_PHRASES).format(resultat=resultat), True
    except Exception as e:
        print(f"[SKILL pile_ou_face] Erreur : {e}")
        return None, False
