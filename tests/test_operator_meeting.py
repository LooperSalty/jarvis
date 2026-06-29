"""Tests du mode reunion de l'Operator (jarvis_actions/operator/meeting.py).

Aucun acces reseau / disque hors tmp_path : la transcription fichier porte sur
un fichier inexistant (court-circuit avant whisper) et le LLM est mocke.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def meeting():
    return importlib.import_module("jarvis_actions.operator.meeting")


def test_transcrire_fichier_inexistant_renvoie_vide(meeting, tmp_path):
    absent = tmp_path / "n_existe_pas.wav"
    assert meeting.transcrire_fichier(str(absent)) == ""


def test_transcrire_fichier_chemin_vide_renvoie_vide(meeting):
    assert meeting.transcrire_fichier("") == ""


def test_disponible_renvoie_bool(meeting):
    assert isinstance(meeting.disponible(), bool)


def test_etat_dict_avec_cles(meeting):
    et = meeting.etat()
    assert isinstance(et, dict)
    assert "actif" in et and "transcript" in et
    assert isinstance(et["actif"], bool)
    assert isinstance(et["transcript"], str)


@pytest.mark.asyncio
async def test_resumer_delegue_au_llm(meeting):
    async def faux_llm(prompt: str) -> str:
        assert "Transcription" in prompt
        return "Compte-rendu : un devis a ete evoque pour le carrelage."

    res = await meeting.resumer("On a parle du chantier salle de bain.", faux_llm)
    assert "devis" in res.lower()


@pytest.mark.asyncio
async def test_resumer_transcript_vide_renvoie_vide(meeting):
    async def faux_llm(prompt: str) -> str:  # ne doit jamais etre appele
        raise AssertionError("le LLM ne doit pas etre appele pour un transcript vide")

    assert await meeting.resumer("", faux_llm) == ""
    assert await meeting.resumer("   ", faux_llm) == ""


@pytest.mark.asyncio
async def test_resumer_defensif_si_llm_leve(meeting):
    async def llm_qui_plante(prompt: str) -> str:
        raise RuntimeError("boom")

    assert await meeting.resumer("du contenu", llm_qui_plante) == ""


def test_arreter_repositionne_etat(meeting):
    meeting._ETAT["actif"] = True
    meeting._ETAT["transcript"] = "bonjour"
    accumule = meeting.arreter()
    assert accumule == "bonjour"
    assert meeting.etat()["actif"] is False
