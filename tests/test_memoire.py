"""Tests memoire proactive + resume d'historique.

- memory_proactive.extraire_faits : parsing JSON defensif (bloc enrobe de texte),
  filtrage des faits ephemeres (meteo/heure...), via un faux demander_json.
- history_summary.resumer_si_besoin : None si l'historique est court, et None si
  google.genai est absent (cas de l'environnement de test sans la lib lourde).

Aucun appel LLM reel : la callable est une coroutine factice.
"""

from __future__ import annotations

import asyncio
import importlib


# ============================================================
# memory_proactive.extraire_faits
# ============================================================

def _faux_demander_json(reponse: str):
    """Fabrique une coroutine demander_json(prompt) -> reponse figee."""
    async def _demander(_prompt: str) -> str:
        return reponse
    return _demander


def test_extraire_faits_json_enrobe():
    """Un JSON enrobe de texte est extrait et parse en faits valides."""
    mod = importlib.import_module("jarvis_actions.memory_proactive")
    reponse = (
        "Bien sur, voici les faits :\n"
        '[{"cle": "prenom", "valeur": "Tony"}, '
        '{"cle": "voiture", "valeur": "une Audi"}]\n'
        "Voila, j'espere que c'est utile."
    )
    faits = asyncio.run(
        mod.extraire_faits("je m'appelle Tony", "Enchante", _faux_demander_json(reponse))
    )
    cles = {f["cle"] for f in faits}
    assert cles == {"prenom", "voiture"}


def test_extraire_faits_filtre_ephemere():
    """Les faits ephemeres (meteo, heure...) sont filtres."""
    mod = importlib.import_module("jarvis_actions.memory_proactive")
    reponse = (
        '[{"cle": "meteo", "valeur": "il fait beau"}, '
        '{"cle": "prenom", "valeur": "Tony"}, '
        '{"cle": "temperature", "valeur": "20 degres"}]'
    )
    faits = asyncio.run(mod.extraire_faits("u", "j", _faux_demander_json(reponse)))
    cles = {f["cle"] for f in faits}
    # Seul le fait durable subsiste.
    assert cles == {"prenom"}


def test_extraire_faits_liste_vide():
    """Une reponse '[]' renvoie une liste vide."""
    mod = importlib.import_module("jarvis_actions.memory_proactive")
    faits = asyncio.run(mod.extraire_faits("u", "j", _faux_demander_json("[]")))
    assert faits == []


def test_extraire_faits_json_invalide():
    """Une reponse sans bloc JSON exploitable renvoie []."""
    mod = importlib.import_module("jarvis_actions.memory_proactive")
    faits = asyncio.run(mod.extraire_faits("u", "j", _faux_demander_json("aucun json ici")))
    assert faits == []


def test_extraire_faits_entrees_incompletes_ignorees():
    """Les objets sans 'cle'/'valeur' chaine non vide sont ignores."""
    mod = importlib.import_module("jarvis_actions.memory_proactive")
    reponse = (
        '[{"cle": "", "valeur": "x"}, '
        '{"cle": "ok", "valeur": "  "}, '
        '{"cle": "ville", "valeur": "Paris"}, '
        '{"autre": "champ"}]'
    )
    faits = asyncio.run(mod.extraire_faits("u", "j", _faux_demander_json(reponse)))
    assert faits == [{"cle": "ville", "valeur": "Paris"}]


def test_extraire_faits_entrees_vides_renvoie_vide():
    """Si user_text et jarvis_text sont vides, retourne [] sans appeler le LLM."""
    mod = importlib.import_module("jarvis_actions.memory_proactive")

    async def _ne_doit_pas_etre_appele(_p: str) -> str:  # pragma: no cover
        raise AssertionError("le LLM ne doit pas etre appele")

    faits = asyncio.run(mod.extraire_faits("", "  ", _ne_doit_pas_etre_appele))
    assert faits == []


def test_extraire_faits_llm_leve_renvoie_vide():
    """Si la callable LLM leve, extraire_faits renvoie [] (jamais d'exception)."""
    mod = importlib.import_module("jarvis_actions.memory_proactive")

    async def _qui_leve(_p: str) -> str:
        raise RuntimeError("boom")

    faits = asyncio.run(mod.extraire_faits("u", "j", _qui_leve))
    assert faits == []


def test_extraire_bloc_json_imbrique():
    """_extraire_bloc_json gere l'imbrication des crochets sans couper trop tot."""
    mod = importlib.import_module("jarvis_actions.memory_proactive")
    texte = 'prefixe [{"a": [1, 2]}, {"b": 3}] suffixe'
    bloc = mod._extraire_bloc_json(texte)
    assert bloc == '[{"a": [1, 2]}, {"b": 3}]'


# ============================================================
# history_summary.resumer_si_besoin
# ============================================================

def test_resumer_none_si_court():
    """Historique plus court que le seuil -> None (rien a resumer)."""
    mod = importlib.import_module("jarvis_actions.history_summary")

    async def _demander(_p: str) -> str:  # pragma: no cover - ne doit pas etre appele
        raise AssertionError("ne doit pas appeler le LLM sur un historique court")

    res = asyncio.run(mod.resumer_si_besoin(["m1", "m2", "m3"], _demander, seuil=60))
    assert res is None


def test_resumer_none_si_pas_une_liste():
    """Un historique qui n'est pas une liste renvoie None."""
    mod = importlib.import_module("jarvis_actions.history_summary")

    async def _demander(_p: str) -> str:  # pragma: no cover
        raise AssertionError("ne doit pas etre appele")

    assert asyncio.run(mod.resumer_si_besoin("pas une liste", _demander)) is None


def test_resumer_none_si_garder_couvre_tout():
    """Si garder >= taille de l'historique, rien a compacter -> None."""
    mod = importlib.import_module("jarvis_actions.history_summary")

    async def _demander(_p: str) -> str:  # pragma: no cover
        raise AssertionError("ne doit pas etre appele")

    historique = list(range(70))  # > seuil 60
    res = asyncio.run(mod.resumer_si_besoin(historique, _demander, seuil=60, garder=70))
    assert res is None


def test_resumer_none_si_genai_absent():
    """Quand google.genai est absent, resumer_si_besoin degrade en None.

    L'environnement de test n'a pas google.genai installe : _charger_types()
    renvoie None et la fonction retourne None meme sur un historique long.
    """
    mod = importlib.import_module("jarvis_actions.history_summary")

    appele = {"oui": False}

    async def _demander(_p: str) -> str:
        appele["oui"] = True
        return "resume factice"

    historique = list(range(100))  # > seuil
    res = asyncio.run(mod.resumer_si_besoin(historique, _demander, seuil=60, garder=30))
    assert res is None
    # Sans types, on n'appelle meme pas le LLM (court-circuit avant transcript).
    assert appele["oui"] is False
