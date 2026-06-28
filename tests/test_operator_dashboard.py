"""Tests des helpers facade dashboard de l'Operator (agenda, previsualisation PDF).

On isole les chemins de persistance (approvals) vers tmp_path et on n'effectue
aucun appel reseau / Google.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def op(monkeypatch, tmp_path):
    mod = importlib.import_module("jarvis_actions.operator")
    monkeypatch.setattr(mod.approvals, "APPROVALS_PATH", tmp_path / "ap.json")
    mod.approvals.set_broadcast(None)
    mod.init({})  # ctx vide : degradation propre
    return mod


def test_shaper_event_datetime(op):
    ev = {"summary": "Dentiste", "start": {"dateTime": "2026-07-01T09:00:00"}, "location": "Cabinet"}
    out = op._shaper_event(ev)
    assert out["titre"] == "Dentiste"
    assert out["debut"] == "2026-07-01T09:00:00"
    assert out["lieu"] == "Cabinet"


def test_shaper_event_all_day_et_sans_titre(op):
    out = op._shaper_event({"start": {"date": "2026-07-02"}})
    assert out["titre"] == "(sans titre)" and out["debut"] == "2026-07-02" and out["lieu"] == ""


@pytest.mark.asyncio
async def test_dashboard_agenda_sans_service(op):
    # ctx vide -> pas de get_calendar_service -> liste vide, jamais d'exception.
    assert await op.dashboard_agenda() == []


def test_pdf_base64_pour_send_devis(op, tmp_path):
    pdf = tmp_path / "DEV-1.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    aid = op.approvals.ajouter({"type": "send_devis", "resume": "x",
                                "payload": {"pdf_path": str(pdf)}})
    b64 = op.pdf_base64_pour(aid)
    assert b64
    import base64
    assert base64.b64decode(b64) == b"%PDF-1.4 fake"


def test_pdf_base64_pour_mauvais_type(op):
    aid = op.approvals.ajouter({"type": "send_email_reply", "resume": "x", "payload": {}})
    assert op.pdf_base64_pour(aid) is None


def test_pdf_base64_pour_fichier_absent(op, tmp_path):
    aid = op.approvals.ajouter({"type": "send_devis", "resume": "x",
                                "payload": {"pdf_path": str(tmp_path / "absent.pdf")}})
    assert op.pdf_base64_pour(aid) is None


def test_pdf_base64_pour_non_pdf_refuse(op, tmp_path):
    # Defense en profondeur : seul un .pdf existant est lu.
    autre = tmp_path / "secret.txt"
    autre.write_text("donnees sensibles")
    aid = op.approvals.ajouter({"type": "send_devis", "resume": "x",
                                "payload": {"pdf_path": str(autre)}})
    assert op.pdf_base64_pour(aid) is None
