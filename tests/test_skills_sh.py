"""Tests du catalogue skills.sh (jarvis_actions/skills_sh.py).

`installer_skill` / `npx_disponible` pilotent la CLI `npx` -> mockees via
monkeypatch. On verifie surtout la LISTE BLANCHE (securite : pas de repo
arbitraire) et le mapping (succes, message).
"""

from __future__ import annotations

from jarvis_actions import skills_sh


class _FakeProc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


# ============================================================
# CATALOGUE
# ============================================================

def test_catalogue_non_vide_et_repos_valides():
    assert skills_sh.CATALOGUE
    for e in skills_sh.CATALOGUE:
        assert e["repo"].count("/") == 1  # owner/repo
        assert e["nom"] and e["description"]


# ============================================================
# npx_disponible
# ============================================================

def test_npx_disponible(monkeypatch):
    monkeypatch.setattr(skills_sh.shutil, "which", lambda _n: "npx")
    assert skills_sh.npx_disponible() is True
    monkeypatch.setattr(skills_sh.shutil, "which", lambda _n: None)
    assert skills_sh.npx_disponible() is False


# ============================================================
# installer_skill — liste blanche
# ============================================================

def test_installer_skill_refuse_hors_catalogue(monkeypatch):
    # Meme si npx existe, un repo hors catalogue est refuse AVANT tout appel.
    monkeypatch.setattr(skills_sh.shutil, "which", lambda _n: "npx")
    appels = []
    monkeypatch.setattr(skills_sh.subprocess, "run",
                        lambda *a, **k: appels.append(a) or _FakeProc())
    ok, msg = skills_sh.installer_skill("attacker/evil-repo")
    assert ok is False
    assert "catalogue" in msg.lower()
    assert appels == []  # aucun subprocess lance


def test_installer_skill_sans_npx(monkeypatch):
    monkeypatch.setattr(skills_sh.shutil, "which", lambda _n: None)
    ok, msg = skills_sh.installer_skill(skills_sh.CATALOGUE[0]["repo"])
    assert ok is False
    assert "npx" in msg.lower()


def test_installer_skill_succes(monkeypatch):
    repo = skills_sh.CATALOGUE[0]["repo"]
    monkeypatch.setattr(skills_sh.shutil, "which", lambda _n: "npx")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeProc(returncode=0, stdout="ok")

    monkeypatch.setattr(skills_sh.subprocess, "run", fake_run)
    ok, msg = skills_sh.installer_skill(repo)
    assert ok is True
    # La commande cible bien Claude Code en global.
    assert "skills" in captured["cmd"] and "add" in captured["cmd"]
    assert repo in captured["cmd"]
    assert "-a" in captured["cmd"] and "claude-code" in captured["cmd"]
    assert "-g" in captured["cmd"]


def test_installer_skill_echec_cli(monkeypatch):
    repo = skills_sh.CATALOGUE[0]["repo"]
    monkeypatch.setattr(skills_sh.shutil, "which", lambda _n: "npx")
    monkeypatch.setattr(skills_sh.subprocess, "run",
                        lambda *a, **k: _FakeProc(returncode=1, stderr="boom"))
    ok, msg = skills_sh.installer_skill(repo)
    assert ok is False
    assert "boom" in msg
