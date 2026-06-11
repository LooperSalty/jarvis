"""Memoire proactive : extraction de faits durables sur l'utilisateur.

A partir d'un echange (ce que l'utilisateur a dit + la reponse de Jarvis), on
demande au LLM d'extraire les faits PERSISTANTS qui meritent d'etre memorises
(prenom, preferences, materiel, habitudes, lieux importants...).

Le module ne fait AUCUN appel LLM lui-meme : l'appelant fournit une fonction
async `demander_json(prompt) -> str`. Cela evite tout import circulaire avec
main2.py et permet de router vers Gemini ou Ollama selon la config.

Le declenchement (opt-in) est gere par main2 via un flag, pas ici.

Parsing JSON defensif : meme si le LLM enrobe sa reponse de texte, on extrait
le premier bloc `[...]` valide. Aucune exception n'est jamais propagee.
"""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable

# Type de la callable LLM fournie par l'appelant.
DemanderJson = Callable[[str], Awaitable[str]]

# Mots-cles indiquant un fait ephemere a ignorer (meteo, heure, etat ponctuel).
_EPHEMERE_RE = re.compile(
    r"\b(m[ée]t[ée]o|temp[ée]rature|il\s+fait|degr[ée]s|"
    r"heure|aujourd['\s]hui|maintenant|ce\s+(?:matin|soir)|"
    r"actuellement|en\s+ce\s+moment|tout\s+de\s+suite)\b",
    re.IGNORECASE,
)

# Prompt FR demandant l'extraction des faits durables au format JSON strict.
_PROMPT_TEMPLATE = (
    "Tu es un extracteur de faits pour un assistant personnel.\n"
    "A partir de l'echange ci-dessous, extrais UNIQUEMENT les faits DURABLES "
    "sur l'utilisateur qui meritent d'etre memorises a long terme : prenom, "
    "preferences, gouts, materiel possede, habitudes, lieux importants, "
    "personnes proches, projets en cours.\n\n"
    "IGNORE tout ce qui est ephemere ou contextuel : la meteo, l'heure, "
    "l'etat actuel d'un appareil, une question ponctuelle, une action que "
    "Jarvis vient de faire.\n\n"
    "Reponds STRICTEMENT au format JSON : une liste d'objets "
    '{{"cle": "...", "valeur": "..."}}. '
    "La cle est un identifiant court en minuscules (ex: prenom, ville, "
    "voiture, langage_prefere). La valeur est le fait en clair.\n"
    "Si aucun fait durable, reponds exactement : []\n"
    "N'ajoute aucun texte avant ou apres le JSON.\n\n"
    "--- Echange ---\n"
    "Utilisateur : {user_text}\n"
    "Jarvis : {jarvis_text}\n"
    "--- Fin ---\n\n"
    "JSON :"
)


def _extraire_bloc_json(texte: str) -> str | None:
    """Extrait le premier bloc liste JSON `[...]` d'une chaine.

    Tolere que le LLM ajoute du texte autour. Gere l'imbrication des crochets
    pour ne pas couper trop tot. Retourne la sous-chaine ou None si introuvable.
    """
    if not texte:
        return None
    debut = texte.find("[")
    if debut == -1:
        return None
    profondeur = 0
    for i in range(debut, len(texte)):
        c = texte[i]
        if c == "[":
            profondeur += 1
        elif c == "]":
            profondeur -= 1
            if profondeur == 0:
                return texte[debut : i + 1]
    return None


def _parser_faits(rep_text: str) -> list[dict]:
    """Parse defensif de la reponse LLM en liste de faits valides.

    Chaque fait doit etre un dict avec 'cle' et 'valeur' non vides. Les faits
    ephemeres (meteo, heure...) sont filtres. Ne leve jamais d'exception.
    """
    bloc = _extraire_bloc_json(rep_text or "")
    if not bloc:
        return []

    try:
        data: Any = json.loads(bloc)
    except (ValueError, TypeError):
        return []

    if not isinstance(data, list):
        return []

    faits: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        cle = item.get("cle")
        valeur = item.get("valeur")
        if not isinstance(cle, str) or not isinstance(valeur, str):
            continue
        cle = cle.strip()
        valeur = valeur.strip()
        if not cle or not valeur:
            continue
        # Filtre les faits ephemeres (meteo, heure, etat ponctuel).
        if _EPHEMERE_RE.search(cle) or _EPHEMERE_RE.search(valeur):
            continue
        faits.append({"cle": cle, "valeur": valeur})
    return faits


async def extraire_faits(
    user_text: str,
    jarvis_text: str,
    demander_json: DemanderJson,
) -> list[dict]:
    """Extrait les faits durables sur l'utilisateur a partir d'un echange.

    Args:
        user_text: ce que l'utilisateur a dit.
        jarvis_text: la reponse de Jarvis.
        demander_json: callable async(prompt) -> str fournie par l'appelant
            (appel LLM). Le module construit le prompt FR demandant l'extraction.

    Returns:
        Liste de faits [{"cle", "valeur"}], potentiellement vide. Jamais None.
        Aucune exception n'est propagee : en cas d'erreur, retourne [].
    """
    user_text = (user_text or "").strip()
    jarvis_text = (jarvis_text or "").strip()
    if not user_text and not jarvis_text:
        return []

    prompt = _PROMPT_TEMPLATE.format(
        user_text=user_text or "(rien)",
        jarvis_text=jarvis_text or "(rien)",
    )

    try:
        rep_text = await demander_json(prompt)
    except Exception as e:  # noqa: BLE001 - on ne doit jamais tuer l'appelant
        print(f"[MEMOIRE_PROACTIVE] Echec appel LLM : {e}")
        return []

    if not isinstance(rep_text, str):
        return []

    return _parser_faits(rep_text)
