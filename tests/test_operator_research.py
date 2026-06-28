"""Tests de la recherche internet + synthese Operator (operator/research.py).

Le shaping (shaper_resultats) est PUR ; rechercher() injecte le reseau (http_get)
et le LLM (demander_ia) — AUCUN acces reseau reel ici.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def research():
    return importlib.import_module("jarvis_actions.operator.research")


def _faux_serp() -> dict:
    """Fausse reponse SerpAPI avec 10 resultats organiques (snippets longs)."""
    return {
        "organic_results": [
            {"title": f"Titre {i}", "link": f"https://ex/{i}", "snippet": "x" * 500}
            for i in range(10)
        ]
    }


# ----- shaper_resultats (PUR) ------------------------------------------------

def test_shaper_mappe_et_limite_a_6(research):
    src = research.shaper_resultats(_faux_serp())
    assert len(src) == 6
    assert set(src[0]) == {"titre", "lien", "extrait"}
    assert src[0]["titre"] == "Titre 0"
    assert src[0]["lien"] == "https://ex/0"


def test_shaper_tronque_extrait_a_300(research):
    src = research.shaper_resultats({"organic_results": [{"snippet": "a" * 1000}]})
    assert len(src) == 1
    assert len(src[0]["extrait"]) == 300


def test_shaper_robuste_si_non_dict(research):
    assert research.shaper_resultats(None) == []
    assert research.shaper_resultats("pas un dict") == []
    assert research.shaper_resultats(42) == []
    assert research.shaper_resultats({}) == []


def test_shaper_champs_manquants_defaut_vide(research):
    src = research.shaper_resultats({"organic_results": [{}]})
    assert src == [{"titre": "", "lien": "", "extrait": ""}]


# ----- rechercher (ASYNC, reseau injecte) -----------------------------------

@pytest.mark.asyncio
async def test_rechercher_branche_serpapi(research, monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")
    appels: dict = {}

    def faux_http(url, params):
        appels["url"] = url
        appels["params"] = params
        return _faux_serp()

    async def faux_ia(prompt):
        appels["prompt"] = prompt
        return "Synthese des resultats."

    res = await research.rechercher("prix carrelage", faux_ia, http_get=faux_http)
    assert res["resume"] == "Synthese des resultats."  # resume non vide
    assert len(res["sources"]) == 6  # sources non vides
    assert appels["url"] == research._SERPAPI_URL
    assert "fake-key" in appels["params"].values()  # cle injectee dans la requete
    assert "prix carrelage" in appels["prompt"]  # query reinjectee dans le prompt


@pytest.mark.asyncio
async def test_rechercher_repli_sans_cle(research, monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    recu: dict = {}

    async def faux_ia(prompt):
        recu["prompt"] = prompt
        return "Reponse directe."

    def http_interdit(url, params):  # ne doit jamais etre appele sans cle
        raise AssertionError("reseau appele sans cle SERPAPI")

    res = await research.rechercher("question", faux_ia, http_get=http_interdit)
    assert res["resume"] == "Reponse directe."
    assert res["sources"] == []
    assert recu["prompt"] == "question"


@pytest.mark.asyncio
async def test_rechercher_repli_si_aucun_resultat(research, monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")

    def http_vide(url, params):
        return {"organic_results": []}

    async def faux_ia(prompt):
        return "Repli sans source."

    res = await research.rechercher("q", faux_ia, http_get=http_vide)
    assert res["sources"] == []
    assert res["resume"] == "Repli sans source."


@pytest.mark.asyncio
async def test_rechercher_defensif_http_qui_leve(research, monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")

    def http_casse(url, params):
        raise RuntimeError("boom reseau")

    async def faux_ia(prompt):
        return "Repli apres erreur."

    res = await research.rechercher("q", faux_ia, http_get=http_casse)
    assert res["sources"] == []
    assert res["resume"] == "Repli apres erreur."
