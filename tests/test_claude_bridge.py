"""Tests de claude_bridge.ouvrir_session_terminal (session de code interactive).

Le lancement reel ouvre une console : on mocke shutil.which / subprocess.Popen /
os.name pour valider la commande construite sans rien ouvrir.
"""

from __future__ import annotations

from jarvis_actions import claude_bridge as cb


def test_ouvrir_session_sans_claude(monkeypatch):
    """Claude Code absent du PATH -> (message, False), aucun Popen."""
    monkeypatch.setattr(cb.shutil, "which", lambda _n: None)
    appels = []
    monkeypatch.setattr(cb.subprocess, "Popen", lambda *a, **k: appels.append((a, k)))
    msg, ok = cb.ouvrir_session_terminal()
    assert ok is False
    assert "claude" in msg.lower()
    assert appels == []


def test_ouvrir_session_windows_lance_cmd_k(monkeypatch, tmp_path):
    """Sous Windows + dossier valide : `cmd /k claude` dans une nouvelle console."""
    monkeypatch.setattr(cb.shutil, "which", lambda n: "C:/claude.exe" if n == "claude" else None)
    monkeypatch.setattr(cb.os, "name", "nt")
    appels = []
    monkeypatch.setattr(cb.subprocess, "Popen", lambda args, **kw: appels.append((args, kw)))

    msg, ok = cb.ouvrir_session_terminal(str(tmp_path))
    assert ok is True
    args, kw = appels[0]
    assert args[0] == "cmd" and args[1] == "/k"
    assert kw.get("cwd") == str(tmp_path)
    assert kw.get("creationflags") == cb._CREATE_NEW_CONSOLE


def test_ouvrir_session_dossier_invalide_lance_sans_cwd(monkeypatch):
    """Un cwd inexistant est ignore (cwd=None) plutot que de planter."""
    monkeypatch.setattr(cb.shutil, "which", lambda n: "C:/claude.exe" if n == "claude" else None)
    monkeypatch.setattr(cb.os, "name", "nt")
    appels = []
    monkeypatch.setattr(cb.subprocess, "Popen", lambda args, **kw: appels.append((args, kw)))

    msg, ok = cb.ouvrir_session_terminal("C:/dossier/inexistant/xyz")
    assert ok is True
    _, kw = appels[0]
    assert kw.get("cwd") is None
