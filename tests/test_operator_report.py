"""Tests du journal d'activite Operator (jarvis_actions/operator/report.py)."""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def rep(monkeypatch, tmp_path):
    mod = importlib.import_module("jarvis_actions.operator.report")
    monkeypatch.setattr(mod, "REPORT_PATH", tmp_path / "jarvis_operator_report.json")
    mod.set_broadcast(None)
    return mod


def test_journaliser_persiste_et_horodate(rep):
    ev = rep.journaliser({"type": "email_trie", "detail": "Facture EDF -> Factures"})
    assert ev["type"] == "email_trie"
    assert "ts" in ev and ev["ts"]
    assert len(rep.derniers()) == 1


def test_resume_compte_par_type(rep):
    rep.journaliser({"type": "email_trie", "detail": "a"})
    rep.journaliser({"type": "email_trie", "detail": "b"})
    rep.journaliser({"type": "email_archive", "detail": "c"})
    txt = rep.resume_textuel()
    assert "2" in txt and "email" in txt.lower()


def test_resume_vide(rep):
    assert "Rien" in rep.resume_textuel()


def test_broadcast_appele(rep):
    recu = []
    rep.set_broadcast(lambda payload: recu.append(payload))
    rep.journaliser({"type": "rdv_cree", "detail": "x"})
    assert recu and recu[0]["action"] == "operator_activity"
    assert recu[0]["evenement"]["type"] == "rdv_cree"


def test_derniers_limite(rep):
    for i in range(10):
        rep.journaliser({"type": "t", "detail": str(i)})
    assert len(rep.derniers(3)) == 3
    assert rep.derniers(3)[-1]["detail"] == "9"
