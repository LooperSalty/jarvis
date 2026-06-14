"""Tests du pont free-claude-code (jarvis_actions/free_code.py).

en_marche/installe/demarrer pilotent urllib + shutil + subprocess -> mockes.
"""

from __future__ import annotations

from jarvis_actions import free_code as fc


class _FakeResp:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def getcode(self):
        return self.status


def test_en_marche_vrai(monkeypatch):
    monkeypatch.setattr(fc.urllib.request, "urlopen", lambda *a, **k: _FakeResp(200))
    assert fc.en_marche() is True


def test_en_marche_faux_si_refus(monkeypatch):
    def _boom(*a, **k):
        raise OSError("connection refused")
    monkeypatch.setattr(fc.urllib.request, "urlopen", _boom)
    assert fc.en_marche() is False


def test_installe(monkeypatch):
    monkeypatch.setattr(fc.shutil, "which", lambda _n: "fcc-server")
    assert fc.installe() is True
    monkeypatch.setattr(fc.shutil, "which", lambda _n: None)
    assert fc.installe() is False


def test_demarrer_deja_en_marche(monkeypatch):
    monkeypatch.setattr(fc, "en_marche", lambda *a, **k: True)
    ok, msg = fc.demarrer()
    assert ok is True
    assert "deja" in msg.lower()


def test_demarrer_pas_installe(monkeypatch):
    monkeypatch.setattr(fc, "en_marche", lambda *a, **k: False)
    monkeypatch.setattr(fc.shutil, "which", lambda _n: None)
    ok, msg = fc.demarrer()
    assert ok is False
    assert "installe" in msg.lower()


def test_demarrer_lance_le_process(monkeypatch):
    monkeypatch.setattr(fc, "en_marche", lambda *a, **k: False)
    monkeypatch.setattr(fc.shutil, "which", lambda _n: "C:/fcc-server.exe")
    monkeypatch.setattr(fc.os, "name", "nt")
    appels = []
    monkeypatch.setattr(fc.subprocess, "Popen", lambda args, **kw: appels.append((args, kw)))
    ok, msg = fc.demarrer()
    assert ok is True
    args, kw = appels[0]
    assert args == ["C:/fcc-server.exe"]
    assert "creationflags" in kw  # detache sous Windows


def test_statut_forme(monkeypatch):
    monkeypatch.setattr(fc, "installe", lambda: True)
    monkeypatch.setattr(fc, "en_marche", lambda *a, **k: False)
    st = fc.statut()
    assert st["installe"] is True
    assert st["en_marche"] is False
    assert st["url_admin"].endswith("/admin")
    assert st["port"] == 8082


def test_assurer_demarre_deja_en_marche(monkeypatch):
    monkeypatch.setattr(fc, "en_marche", lambda *a, **k: True)
    appels = []
    monkeypatch.setattr(fc, "demarrer", lambda: appels.append(1) or (True, ""))
    assert fc.assurer_demarre() is True
    assert appels == []  # deja en marche -> ne relance pas


def test_assurer_demarre_lance_si_absent(monkeypatch):
    etats = iter([False, True])  # down puis up apres demarrage
    monkeypatch.setattr(fc, "en_marche", lambda *a, **k: next(etats))
    monkeypatch.setattr(fc, "demarrer", lambda: (True, "lance"))
    assert fc.assurer_demarre(timeout=3) is True
