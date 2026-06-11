"""Skill exemple : citation du jour.

Mots-cles : "citation du jour", "donne-moi une citation".
La citation est choisie par hash de la date du jour : stable toute la journee,
change le lendemain (hashlib et non hash() qui est sale par process).
"""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import date

SKILL = {
    "nom": "citation_du_jour",
    "description": "Donne une citation de dev ou de scientifique, stable sur la journee.",
    "version": "1.0.0",
}

# Mots-cles SANS accents : la commande est normalisee avant comparaison
_MOTS_CLES = (
    "citation du jour",
    "donne-moi une citation",
    "donne moi une citation",
    "une citation",
    "cite-moi quelque chose",
    "cite moi quelque chose",
)

# (texte, auteur) — les textes sont vocalises par le TTS, accents conserves
_CITATIONS: tuple[tuple[str, str], ...] = (
    ("Parler est facile. Montre-moi le code.", "Linus Torvalds"),
    ("Le code est lu bien plus souvent qu'il n'est écrit.", "Guido van Rossum"),
    ("L'optimisation prématurée est la racine de tous les maux.", "Donald Knuth"),
    ("Les programmes doivent être écrits pour être lus par des humains, et accessoirement exécutés par des machines.", "Harold Abelson"),
    ("Le meilleur moyen de prédire l'avenir, c'est de l'inventer.", "Alan Kay"),
    ("L'informatique ne concerne pas plus les ordinateurs que l'astronomie ne concerne les télescopes.", "Edsger Dijkstra"),
    ("Il y a deux façons de concevoir un logiciel : le faire si simple qu'il n'a manifestement aucun défaut, ou si compliqué qu'il n'a aucun défaut manifeste.", "Tony Hoare"),
    ("D'abord, résous le problème. Ensuite, écris le code.", "John Johnson"),
    ("Neuf personnes ne font pas un bébé en un mois.", "Fred Brooks"),
    ("La simplicité est la sophistication suprême.", "Léonard de Vinci"),
    ("L'imagination est plus importante que le savoir.", "Albert Einstein"),
    ("Dans la vie, rien n'est à craindre, tout est à comprendre.", "Marie Curie"),
    ("Si j'ai vu plus loin, c'est en montant sur les épaules de géants.", "Isaac Newton"),
    ("Nous ne pouvons voir qu'à courte distance devant nous, mais nous y voyons déjà beaucoup à faire.", "Alan Turing"),
    ("Je n'ai pas échoué, j'ai trouvé dix mille moyens qui ne fonctionnent pas.", "Thomas Edison"),
)


def _normaliser(texte: str) -> str:
    """Minuscules + suppression des accents pour le matching des mots-cles."""
    decompose = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


def _citation_du_jour() -> str:
    """Choisit la citation par hash sha256 de la date ISO du jour (stable)."""
    empreinte = hashlib.sha256(date.today().isoformat().encode("utf-8"))
    index = int(empreinte.hexdigest(), 16) % len(_CITATIONS)
    texte, auteur = _CITATIONS[index]
    return f"La citation du jour : {texte} Signé {auteur}."


def executer(cmd: str) -> tuple[str | None, bool]:
    """Detecte une demande de citation. (None, False) si non reconnue."""
    try:
        c = _normaliser(cmd or "")
        if not any(mot in c for mot in _MOTS_CLES):
            return None, False
        return _citation_du_jour(), True
    except Exception as e:
        print(f"[SKILL citation_du_jour] Erreur : {e}")
        return None, False
