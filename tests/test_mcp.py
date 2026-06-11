"""Tests du client MCP (jarvis_actions.mcp_client) — logique pure uniquement.

On ne lance AUCUN process MCP : on teste le parsing/validation de config et le
dispatch JSON-RPC (correlation reponse <-> future), sans reseau ni subprocess.

Le chemin de config est redirige vers tmp_path en monkeypatchant _config_path.
"""

from __future__ import annotations

import asyncio
import importlib

import pytest


@pytest.fixture
def mcp(monkeypatch, tmp_path):
    """Module mcp_client avec _config_path redirige vers tmp_path."""
    mod = importlib.import_module("jarvis_actions.mcp_client")
    cfg = tmp_path / "jarvis_mcp.json"
    monkeypatch.setattr(mod, "_config_path", lambda: cfg)
    return mod


def test_charger_config_absente(mcp):
    """charger_config renvoie {'servers': {}} quand le fichier n'existe pas."""
    assert mcp.charger_config() == {"servers": {}}


def test_charger_config_corrompue(mcp, tmp_path):
    """Un JSON corrompu renvoie {'servers': {}} sans crasher."""
    (tmp_path / "jarvis_mcp.json").write_text("{ pas json", encoding="utf-8")
    assert mcp.charger_config() == {"servers": {}}


def test_charger_config_sans_cle_servers(mcp, tmp_path):
    """Une config sans cle 'servers' valide retombe sur {'servers': {}}."""
    (tmp_path / "jarvis_mcp.json").write_text('{"autre": 1}', encoding="utf-8")
    assert mcp.charger_config() == {"servers": {}}


def test_round_trip_sauvegarder_charger(mcp):
    """sauvegarder_config puis charger_config restitue la meme structure."""
    cfg = {"servers": {"demo": {"command": "echo", "args": ["hi"], "enabled": True}}}
    assert mcp.sauvegarder_config(cfg) is True
    assert mcp.charger_config() == cfg


def test_ajouter_serveur(mcp):
    """ajouter_serveur cree une entree valide avec env/enabled par defaut."""
    msg, ok = mcp.ajouter_serveur("demo", "npx", ["-y", "pkg"])
    assert ok is True
    assert "demo" in msg
    srv = mcp.charger_config()["servers"]["demo"]
    assert srv["command"] == "npx"
    assert srv["args"] == ["-y", "pkg"]
    assert srv["enabled"] is True
    assert srv["env"] == {}


def test_ajouter_serveur_nom_invalide(mcp):
    """Un nom vide ou prefixe '_' est rejete."""
    assert mcp.ajouter_serveur("", "npx", [])[1] is False
    assert mcp.ajouter_serveur("_reserve", "npx", [])[1] is False


def test_ajouter_serveur_commande_invalide(mcp):
    """Une commande vide est rejetee."""
    assert mcp.ajouter_serveur("demo", "", [])[1] is False


def test_activer_desactiver_serveur(mcp):
    """activer_serveur bascule le flag enabled de l'entree existante."""
    mcp.ajouter_serveur("demo", "npx", [])
    msg, ok = mcp.activer_serveur("demo", False)
    assert ok is True
    assert mcp.charger_config()["servers"]["demo"]["enabled"] is False
    mcp.activer_serveur("demo", True)
    assert mcp.charger_config()["servers"]["demo"]["enabled"] is True


def test_activer_serveur_inconnu(mcp):
    """activer_serveur sur un serveur absent renvoie (msg, False)."""
    assert mcp.activer_serveur("fantome", True)[1] is False


def test_supprimer_serveur(mcp):
    """supprimer_serveur retire l'entree de la config."""
    mcp.ajouter_serveur("demo", "npx", [])
    msg, ok = mcp.supprimer_serveur("demo")
    assert ok is True
    assert "demo" not in mcp.charger_config()["servers"]


def test_supprimer_serveur_inconnu(mcp):
    """supprimer_serveur sur un serveur absent renvoie (msg, False)."""
    assert mcp.supprimer_serveur("fantome")[1] is False


def test_etat_serveurs_vide(mcp):
    """etat_serveurs renvoie {} quand la config est vide."""
    assert mcp.etat_serveurs() == {}


def test_etat_serveurs_non_connecte(mcp):
    """Un serveur en config mais sans session est 'non connecte', 0 tools."""
    mcp.ajouter_serveur("demo", "npx", [])
    etat = mcp.etat_serveurs()
    assert etat["demo"] == {"connected": False, "nb_tools": 0}


# ============================================================
# Dispatch JSON-RPC (logique pure de correlation reponse <-> future)
# ============================================================

class _FakeProc:
    """Faux process : juste assez pour _McpSession (alive + stdin None)."""

    def __init__(self):
        self.returncode = None
        self.stdin = None


def _session(mcp):
    """Construit une _McpSession sur un faux process (sans subprocess reel)."""
    return mcp._McpSession("test", _FakeProc())


def test_dispatch_correle_reponse_par_id(mcp):
    """_dispatch_message resout la future en attente correspondant a l'id."""
    async def scenario():
        session = _session(mcp)
        fut = asyncio.get_running_loop().create_future()
        session.pending[7] = fut
        await mcp._dispatch_message(session, {"jsonrpc": "2.0", "id": 7, "result": {"ok": 1}})
        return fut.result()

    res = asyncio.run(scenario())
    assert res == {"jsonrpc": "2.0", "id": 7, "result": {"ok": 1}}


def test_dispatch_id_chaine_numerique(mcp):
    """Un id renvoye en chaine numerique est correle a la future entiere."""
    async def scenario():
        session = _session(mcp)
        fut = asyncio.get_running_loop().create_future()
        session.pending[3] = fut
        await mcp._dispatch_message(session, {"id": "3", "result": {}})
        return fut.done()

    assert asyncio.run(scenario()) is True


def test_dispatch_notification_sans_id_ignoree(mcp):
    """Une notification serveur (sans id) ne resout aucune future, sans erreur."""
    async def scenario():
        session = _session(mcp)
        fut = asyncio.get_running_loop().create_future()
        session.pending[1] = fut
        # message 'method' sans id -> notification serveur, ignoree.
        await mcp._dispatch_message(session, {"method": "notifications/x"})
        return fut.done()

    assert asyncio.run(scenario()) is False


def test_fail_pending_echoue_les_futures(mcp):
    """_fail_pending leve une exception sur toutes les futures en attente."""
    async def scenario():
        session = _session(mcp)
        fut = asyncio.get_running_loop().create_future()
        session.pending[5] = fut
        mcp._fail_pending(session, "serveur mort")
        assert session.pending == {}
        return fut

    fut = asyncio.run(scenario())
    assert fut.done()
    with pytest.raises(RuntimeError, match="serveur mort"):
        fut.result()


def test_session_alive(mcp):
    """alive() reflete returncode du process (None = vivant)."""
    session = _session(mcp)
    assert session.alive() is True
    session.proc.returncode = 0
    assert session.alive() is False
