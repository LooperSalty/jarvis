"""Tests de la file d'approbation Operator (jarvis_actions/operator/approvals.py)."""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def ap(monkeypatch, tmp_path):
    mod = importlib.import_module("jarvis_actions.operator.approvals")
    monkeypatch.setattr(mod, "APPROVALS_PATH", tmp_path / "jarvis_operator_approvals.json")
    mod.set_broadcast(None)
    return mod


def test_ajouter_genere_id_et_persiste(ap):
    aid = ap.ajouter({"type": "send_devis", "resume": "Devis ACME 1200 EUR", "payload": {"x": 1}})
    assert aid
    items = ap.lister()
    assert len(items) == 1 and items[0]["id"] == aid and items[0]["type"] == "send_devis"
    assert items[0]["payload"] == {"x": 1}


def test_plus_recente(ap):
    ap.ajouter({"type": "send_email_reply", "resume": "r1", "payload": {}})
    a2 = ap.ajouter({"type": "send_devis", "resume": "r2", "payload": {}})
    assert ap.plus_recente()["id"] == a2


def test_lister_public_sans_payload(ap):
    # Le payload contient des PII (email client, IBAN/SIRET du devis) : il ne doit
    # JAMAIS etre diffuse aux clients. lister_public() le retire.
    ap.ajouter({"type": "send_devis", "resume": "Devis ACME",
                "payload": {"client_email": "x@y.z", "iban": "FR76..."}})
    pub = ap.lister_public()
    assert pub and "payload" not in pub[0]
    assert pub[0]["resume"] == "Devis ACME" and pub[0]["type"] == "send_devis"
    # La version interne conserve bien le payload (pour l'execution).
    assert "payload" in ap.lister()[0]


def test_rejeter_retire(ap):
    aid = ap.ajouter({"type": "send_devis", "resume": "x", "payload": {}})
    assert ap.rejeter(aid) is True
    assert ap.lister() == []
    assert ap.rejeter("inexistant") is False


@pytest.mark.asyncio
async def test_confirmer_appelle_executeur_et_retire(ap):
    aid = ap.ajouter({"type": "send_devis", "resume": "x", "payload": {"client": "ACME"}})
    appels = []

    async def faux_envoi(payload):
        appels.append(payload)
        return "Devis envoye a ACME.", True

    msg, ok = await ap.confirmer(aid, {"send_devis": faux_envoi})
    assert ok is True and "ACME" in msg
    assert appels and appels[0]["client"] == "ACME"
    assert ap.lister() == []  # retiree apres execution reussie


@pytest.mark.asyncio
async def test_confirmer_type_inconnu_conserve(ap):
    aid = ap.ajouter({"type": "mystere", "resume": "x", "payload": {}})
    msg, ok = await ap.confirmer(aid, {})
    assert ok is False
    assert ap.get(aid) is not None  # conservee si echec


@pytest.mark.asyncio
async def test_confirmer_echec_conserve(ap):
    aid = ap.ajouter({"type": "send_devis", "resume": "x", "payload": {}})

    async def echoue(payload):
        return "Erreur reseau", False

    msg, ok = await ap.confirmer(aid, {"send_devis": echoue})
    assert ok is False
    assert ap.get(aid) is not None  # non retiree si echec
