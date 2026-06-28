"""Tests du routeur vocal pur de l'Operator (jarvis_actions/operator/__init__.py).

Le routeur _router est PUR : texte -> (intention, params) | None, aucun effet de bord.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def op():
    return importlib.import_module("jarvis_actions.operator")


@pytest.mark.parametrize("phrase, intent", [
    ("trie mes mails", "email_triage"),
    ("occupe-toi de mes mails", "email_triage"),
    ("ecoute la reunion", "meeting_start"),
    ("ecoute la conversation", "meeting_start"),
    ("arrete d'ecouter", "meeting_stop"),
    ("stop reunion", "meeting_stop"),
    ("fais un devis", "devis_new"),
    ("prepare le devis", "devis_new"),
    ("genere un devis", "devis_new"),
    ("prends un rdv mardi 14h", "rdv_new"),
    ("ajoute a mon agenda demain 9h dentiste", "rdv_new"),
    ("planifie un rendez-vous", "rdv_new"),
    ("fais une recherche sur les prix du carrelage", "research"),
    ("recherche approfondie sur la TVA chantier", "research"),
    ("recherche sur internet le cours de l'or", "research"),
])
def test_router_intentions(op, phrase, intent):
    res = op._router(phrase, a_des_approbations=False)
    assert res is not None and res[0] == intent


def test_oui_non_ignores_sans_approbation(op):
    assert op._router("oui", a_des_approbations=False) is None
    assert op._router("non", a_des_approbations=False) is None


def test_oui_non_captures_avec_approbation(op):
    assert op._router("oui", a_des_approbations=True)[0] == "approve_confirm"
    assert op._router("envoie", a_des_approbations=True)[0] == "approve_confirm"
    assert op._router("d'accord", a_des_approbations=True)[0] == "approve_confirm"
    assert op._router("annule", a_des_approbations=True)[0] == "approve_reject"
    assert op._router("non", a_des_approbations=True)[0] == "approve_reject"


def test_non_pertinent_renvoie_none(op):
    assert op._router("quelle heure est-il", a_des_approbations=True) is None
    assert op._router("", a_des_approbations=True) is None


@pytest.mark.asyncio
async def test_async_executer_non_gere_renvoie_none(op, monkeypatch):
    # Aucune approbation en attente -> lister() renvoie [] -> 'oui' non capture.
    monkeypatch.setattr(op.approvals, "lister", lambda: [])
    rep, ok = await op.async_executer("quelle heure est-il")
    assert rep is None and ok is False


@pytest.mark.asyncio
async def test_async_executer_degrade_sans_ctx(op, monkeypatch):
    # Sans dependances injectees (ctx vide), une intention metier degrade
    # proprement (message d'indisponibilite) plutot que de crasher.
    monkeypatch.setattr(op.approvals, "lister", lambda: [])
    op.init({})
    rep, ok = await op.async_executer("trie mes mails")
    assert rep is not None
    assert "disponible" in rep.lower()
