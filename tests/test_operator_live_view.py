"""Tests de la vue live Operator (jarvis_actions/operator/live_view.py).

On verifie que la page HTML autonome est ecrite et contient le client WebSocket
(connexion loopback + rendu operator_step). Aucune ouverture de navigateur reelle.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def lv(monkeypatch, tmp_path):
    mod = importlib.import_module("jarvis_actions.operator.live_view")
    monkeypatch.setattr(mod.tempfile, "gettempdir", lambda: str(tmp_path))
    return mod


def test_ecrire_produit_html_autonome(lv):
    path = lv.ecrire()
    assert path.endswith(".html")
    contenu = open(path, encoding="utf-8").read()
    # Client WS loopback + rendu des etapes live + des broadcasts d'activite.
    assert "127.0.0.1:8765" in contenu
    assert "operator_step" in contenu
    assert "operator_activity" in contenu
    assert "dash_operator_init" in contenu


def test_ouvrir_best_effort(lv, monkeypatch):
    # os.startfile peut ne pas exister hors Windows -> repli webbrowser ; on mocke
    # les deux pour ne RIEN ouvrir et verifier que ouvrir() renvoie True.
    monkeypatch.setattr(lv.webbrowser, "open", lambda *a, **k: True)
    if hasattr(lv.os, "startfile"):
        monkeypatch.setattr(lv.os, "startfile", lambda *a, **k: None, raising=False)
    assert lv.ouvrir() is True
