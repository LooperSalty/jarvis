"""Tests de la memoire proactive (jarvis_actions/memory_proactive.py).

Le module extrait les faits durables sur l'utilisateur a partir d'un echange.
Il NE fait aucun appel reseau lui-meme : l'appelant fournit une callable async
`demander_json(prompt) -> str`. On la stub donc avec des reponses canned, ce qui
rend tout le module testable sans Ollama/Gemini.

Style aligne sur la suite : pas de marker pytest-asyncio, on pilote les
coroutines via asyncio.run (cf. tests/test_mcp.py).
"""

from __future__ import annotations

import asyncio

from jarvis_actions import memory_proactive


def _stub_llm(reponse: str):
    """Construit une callable async qui renvoie toujours `reponse`."""
    async def _demander_json(prompt: str) -> str:
        _stub_llm.dernier_prompt = prompt
        return reponse
    return _demander_json


# ============================================================
# extraire_faits — chemin nominal
# ============================================================

def test_extraire_faits_parse_liste_valide():
    """Une reponse JSON propre produit la liste de faits attendue."""
    llm = _stub_llm('[{"cle": "prenom", "valeur": "Paul"}, '
                    '{"cle": "ville", "valeur": "Metz"}]')
    faits = asyncio.run(memory_proactive.extraire_faits("Je suis Paul de Metz", "Enchante.", llm))
    assert faits == [
        {"cle": "prenom", "valeur": "Paul"},
        {"cle": "ville", "valeur": "Metz"},
    ]


def test_extraire_faits_liste_vide():
    """Le LLM signale l'absence de fait durable via [] -> liste vide."""
    faits = asyncio.run(memory_proactive.extraire_faits("Quelle heure est-il ?", "Il est midi.", _stub_llm("[]")))
    assert faits == []


def test_extraire_faits_json_enrobe_de_texte():
    """Parsing defensif : on extrait le bloc [...] meme noye dans du texte."""
    llm = _stub_llm('Bien sur, voici les faits :\n'
                    '[{"cle": "langage_prefere", "valeur": "Python"}]\n'
                    'Voila qui devrait aider.')
    faits = asyncio.run(memory_proactive.extraire_faits("Je code en Python", "Note.", llm))
    assert faits == [{"cle": "langage_prefere", "valeur": "Python"}]


def test_extraire_faits_filtre_ephemere():
    """Les faits ephemeres (meteo/heure) sont rejetes, les durables gardes."""
    llm = _stub_llm('[{"cle": "meteo", "valeur": "il fait 20 degres"}, '
                    '{"cle": "voiture", "valeur": "Tesla Model 3"}]')
    faits = asyncio.run(memory_proactive.extraire_faits("...", "...", llm))
    assert faits == [{"cle": "voiture", "valeur": "Tesla Model 3"}]


# ============================================================
# extraire_faits — robustesse (jamais d'exception, jamais None)
# ============================================================

def test_extraire_faits_json_invalide_renvoie_vide():
    """Un JSON casse ne fait pas planter : liste vide."""
    faits = asyncio.run(memory_proactive.extraire_faits("x", "y", _stub_llm("[{cassé}")))
    assert faits == []


def test_extraire_faits_llm_leve_exception():
    """Si la callable LLM leve, on ne propage pas : liste vide."""
    async def _llm_ko(prompt: str) -> str:
        raise RuntimeError("Ollama down")
    faits = asyncio.run(memory_proactive.extraire_faits("x", "y", _llm_ko))
    assert faits == []


def test_extraire_faits_reponse_non_str():
    """Une callable qui renvoie autre chose qu'une str -> liste vide."""
    async def _llm_none(prompt: str):
        return None
    faits = asyncio.run(memory_proactive.extraire_faits("x", "y", _llm_none))
    assert faits == []


def test_extraire_faits_echange_vide_n_appelle_pas_le_llm():
    """user_text et jarvis_text vides : court-circuit sans appel LLM."""
    appels = {"n": 0}

    async def _llm_compteur(prompt: str) -> str:
        appels["n"] += 1
        return "[]"

    faits = asyncio.run(memory_proactive.extraire_faits("  ", "", _llm_compteur))
    assert faits == []
    assert appels["n"] == 0


# ============================================================
# _parser_faits — unites de parsing
# ============================================================

def test_parser_faits_ignore_entrees_incompletes():
    """Cle ou valeur manquante/vide/non-str -> entree ignoree."""
    rep = ('[{"cle": "prenom", "valeur": "Paul"}, '
           '{"cle": "", "valeur": "vide"}, '
           '{"cle": "sansvaleur"}, '
           '{"cle": 42, "valeur": "num"}, '
           '"pas un objet"]')
    assert memory_proactive._parser_faits(rep) == [{"cle": "prenom", "valeur": "Paul"}]


def test_parser_faits_strip_des_valeurs():
    """Les cles/valeurs sont strippees des espaces superflus."""
    assert memory_proactive._parser_faits('[{"cle": "  ville ", "valeur": " Metz  "}]') == [
        {"cle": "ville", "valeur": "Metz"}
    ]


def test_parser_faits_objet_racine_non_liste():
    """Un objet JSON non-liste a la racine -> liste vide."""
    assert memory_proactive._parser_faits('{"cle": "x", "valeur": "y"}') == []


# ============================================================
# _extraire_bloc_json — extraction du premier bloc liste
# ============================================================

def test_extraire_bloc_json_imbrique():
    """Gere l'imbrication des crochets sans couper trop tot."""
    texte = 'avant [{"a": [1, 2]}, {"b": 3}] apres'
    assert memory_proactive._extraire_bloc_json(texte) == '[{"a": [1, 2]}, {"b": 3}]'


def test_extraire_bloc_json_absent():
    """Aucun crochet -> None."""
    assert memory_proactive._extraire_bloc_json("aucun bloc ici") is None
