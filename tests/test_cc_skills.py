"""Tests du catalogue de skills Claude Code (jarvis_actions/cc_skills.py).

`_parser_marketplaces` est pur (parse la sortie CLI). `ajouter_marketplace` /
`marketplaces_installes` pilotent la CLI `claude` -> mockees via monkeypatch.
"""

from __future__ import annotations

from jarvis_actions import cc_skills


_SORTIE_LIST = """Configured marketplaces:

  > claude-plugins-official
    Source: GitHub (anthropics/claude-plugins-official)

  > ruflo
    Source: GitHub (ruvnet/ruflo)
"""


class _FakeProc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


# ============================================================
# _parser_marketplaces — pur
# ============================================================

def test_parser_marketplaces_extrait_les_repos():
    repos = cc_skills._parser_marketplaces(_SORTIE_LIST)
    assert repos == {"anthropics/claude-plugins-official", "ruvnet/ruflo"}


def test_parser_marketplaces_vide():
    assert cc_skills._parser_marketplaces("") == set()
    assert cc_skills._parser_marketplaces("aucune marketplace ici") == set()


# ============================================================
# claude_disponible
# ============================================================

def test_claude_disponible(monkeypatch):
    monkeypatch.setattr(cc_skills.shutil, "which", lambda _n: "claude")
    assert cc_skills.claude_disponible() is True
    monkeypatch.setattr(cc_skills.shutil, "which", lambda _n: None)
    assert cc_skills.claude_disponible() is False


# ============================================================
# marketplaces_installes
# ============================================================

def test_marketplaces_installes_parse_la_cli(monkeypatch):
    monkeypatch.setattr(cc_skills.shutil, "which", lambda _n: "claude")
    monkeypatch.setattr(cc_skills.subprocess, "run",
                        lambda *a, **k: _FakeProc(stdout=_SORTIE_LIST))
    assert "ruvnet/ruflo" in cc_skills.marketplaces_installes()


def test_marketplaces_installes_sans_claude(monkeypatch):
    monkeypatch.setattr(cc_skills.shutil, "which", lambda _n: None)
    assert cc_skills.marketplaces_installes() == set()


# ============================================================
# ajouter_marketplace — liste blanche + CLI
# ============================================================

def test_ajouter_marketplace_hors_catalogue():
    """Un repo arbitraire (hors CATALOGUE) est refuse : pas d'execution."""
    ok, msg = cc_skills.ajouter_marketplace("attacker/evil")
    assert ok is False
    assert "catalogue" in msg.lower()


def test_ajouter_marketplace_sans_claude(monkeypatch):
    monkeypatch.setattr(cc_skills.shutil, "which", lambda _n: None)
    ok, msg = cc_skills.ajouter_marketplace("anthropics/skills")
    assert ok is False
    assert "claude" in msg.lower()


def test_ajouter_marketplace_succes(monkeypatch):
    appels = []

    def _fake_run(args, **kw):
        appels.append(args)
        return _FakeProc(returncode=0)

    monkeypatch.setattr(cc_skills.shutil, "which", lambda _n: "claude")
    monkeypatch.setattr(cc_skills.subprocess, "run", _fake_run)
    ok, msg = cc_skills.ajouter_marketplace("anthropics/skills")
    assert ok is True
    cmd = appels[0]
    assert cmd[1:4] == ["plugin", "marketplace", "add"]
    assert "anthropics/skills" in cmd


def test_ajouter_marketplace_echec_cli(monkeypatch):
    monkeypatch.setattr(cc_skills.shutil, "which", lambda _n: "claude")
    monkeypatch.setattr(cc_skills.subprocess, "run",
                        lambda *a, **k: _FakeProc(stderr="boom", returncode=1))
    ok, msg = cc_skills.ajouter_marketplace("mattpocock/skills")
    assert ok is False
    assert "boom" in msg


def test_catalogue_non_vide_et_bien_forme():
    assert len(cc_skills.CATALOGUE) >= 2
    for e in cc_skills.CATALOGUE:
        assert e["repo"] and "/" in e["repo"]
        assert e["nom"] and e["description"]
