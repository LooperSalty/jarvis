"""Tests du handler de redemarrage du dashboard (jarvis_dashboard_api._h_restart).

Le handler delegue au callable 'redemarrer' injecte par main2 (via _CTX). On
verifie le branchement sans declencher de vrai redemarrage (callable mocke).
"""

from __future__ import annotations

import asyncio

import jarvis_dashboard_api as jda


def test_h_restart_appelle_redemarrer(monkeypatch):
    appels = []
    monkeypatch.setitem(jda._CTX, "redemarrer", lambda: appels.append(1) or True)
    res = asyncio.run(jda._h_restart({}))
    assert res["action"] == "dash_restart"
    assert res["ok"] is True
    assert appels == [1]


def test_h_restart_indisponible_si_callable_absent(monkeypatch):
    monkeypatch.delitem(jda._CTX, "redemarrer", raising=False)
    res = asyncio.run(jda._h_restart({}))
    assert res["ok"] is False
    assert "indisponible" in res["message"].lower()


def test_h_restart_defensif_si_callable_leve(monkeypatch):
    def boom():
        raise RuntimeError("echec")

    monkeypatch.setitem(jda._CTX, "redemarrer", boom)
    res = asyncio.run(jda._h_restart({}))
    # _appel_ctx avale l'exception -> defaut False (jamais de crash du handler).
    assert res["ok"] is False


def test_dash_restart_enregistre_dans_handlers():
    assert jda._HANDLERS.get("dash_restart") is jda._h_restart
