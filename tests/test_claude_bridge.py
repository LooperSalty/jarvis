"""Tests de claude_bridge.ouvrir_session_terminal (session de code interactive).

Le lancement reel ouvre une console : on mocke shutil.which / subprocess.Popen /
os.name pour valider la commande construite sans rien ouvrir.
"""

from __future__ import annotations

import os

from jarvis_actions import claude_bridge as cb


class _FakeRun:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


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


def test_ouvrir_session_macos_chemin_en_argv_pas_interpole(monkeypatch, tmp_path):
    """Securite : le chemin est passe en ARGV a osascript (pas interpole dans
    le script) -> pas d'injection AppleScript/shell via un nom de dossier."""
    monkeypatch.setattr(cb.os, "name", "posix")

    def _which(n):
        if n == "claude":
            return "/usr/local/bin/claude"
        if n == "osascript":
            return "/usr/bin/osascript"
        return None  # x-terminal-emulator absent -> on tombe sur osascript

    monkeypatch.setattr(cb.shutil, "which", _which)
    appels = []
    monkeypatch.setattr(cb.subprocess, "Popen", lambda args, **kw: appels.append((args, kw)))

    cible = str(tmp_path)
    msg, ok = cb.ouvrir_session_terminal(cible)
    assert ok is True
    args, _ = appels[0]
    assert args[0] == "osascript"
    # Le chemin est le DERNIER argv (transmis a osascript), PAS interpole :
    assert args[-1] == cible
    script = args[2]
    assert cible not in script
    assert "quoted form of" in script


# ============================================================
# Modes de permission (--permission-mode)
# ============================================================

def test_args_mode_liste_blanche():
    assert cb._args_mode("default") == []          # mode normal -> pas de flag
    assert cb._args_mode("plan") == ["--permission-mode", "plan"]
    assert cb._args_mode("bypassPermissions") == ["--permission-mode", "bypassPermissions"]
    assert cb._args_mode("acceptEdits") == ["--permission-mode", "acceptEdits"]
    assert cb._args_mode("rm -rf /") == []          # hors liste blanche -> ignore


def test_ouvrir_session_passe_le_permission_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(cb.shutil, "which", lambda n: "C:/claude.exe" if n == "claude" else None)
    monkeypatch.setattr(cb.os, "name", "nt")
    appels = []
    monkeypatch.setattr(cb.subprocess, "Popen", lambda args, **kw: appels.append((args, kw)))
    cb.ouvrir_session_terminal(str(tmp_path), "plan")
    args, _ = appels[0]
    assert "--permission-mode" in args and "plan" in args


def test_ouvrir_session_mode_invalide_ignore(monkeypatch, tmp_path):
    monkeypatch.setattr(cb.shutil, "which", lambda n: "C:/claude.exe" if n == "claude" else None)
    monkeypatch.setattr(cb.os, "name", "nt")
    appels = []
    monkeypatch.setattr(cb.subprocess, "Popen", lambda args, **kw: appels.append((args, kw)))
    cb.ouvrir_session_terminal(str(tmp_path), "evil; rm -rf")
    args, _ = appels[0]
    assert "--permission-mode" not in args  # mode hors liste blanche -> pas injecte


# ============================================================
# chat_claude_code (Cowork agentique) + dossier par defaut
# ============================================================

def test_chat_claude_code_sans_claude(monkeypatch):
    monkeypatch.setattr(cb.shutil, "which", lambda _n: None)
    txt, ok = cb.chat_claude_code("fais un truc")
    assert ok is False
    assert "claude" in txt.lower()


def test_chat_claude_code_construit_les_args(monkeypatch, tmp_path):
    captures = {}

    def _run(args, **kw):
        captures["args"] = args
        captures["env"] = kw.get("env")
        captures["cwd"] = kw.get("cwd")
        return _FakeRun(returncode=0, stdout="Fait.")

    monkeypatch.setattr(cb.shutil, "which", lambda n: "C:/claude.exe" if n == "claude" else None)
    monkeypatch.setattr(cb.subprocess, "run", _run)

    txt, ok = cb.chat_claude_code(
        "ajoute un test", cwd=str(tmp_path), model="qwen2.5:7b",
        permission_mode="acceptEdits", continuer=True, via_proxy=True,
    )
    assert ok is True and txt == "Fait."
    args = captures["args"]
    assert "--print" in args and "--continue" in args
    assert "--model" in args and "qwen2.5:7b" in args
    assert "--permission-mode" in args and "acceptEdits" in args
    assert args[-1] == "ajoute un test"            # prompt en dernier (positionnel)
    assert captures["cwd"] == str(tmp_path)
    # via_proxy -> l'env pointe le proxy local
    assert captures["env"]["ANTHROPIC_BASE_URL"] == cb._PROXY_URL


def test_chat_claude_code_sans_proxy_pas_d_env_proxy(monkeypatch):
    captures = {}
    monkeypatch.setattr(cb.shutil, "which", lambda n: "C:/claude.exe" if n == "claude" else None)
    monkeypatch.setattr(cb.subprocess, "run",
                        lambda args, **kw: captures.update(env=kw.get("env")) or _FakeRun(0, "ok"))
    cb.chat_claude_code("x", via_proxy=False)
    assert "ANTHROPIC_BASE_URL" not in captures["env"]


def test_dossier_cowork_defaut(monkeypatch, tmp_path):
    monkeypatch.setattr(cb.Path, "home", classmethod(lambda cls: tmp_path))
    d = cb.dossier_cowork_defaut()
    assert d.endswith("JarvisCowork")
    assert os.path.isdir(d)
