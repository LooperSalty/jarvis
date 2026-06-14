"""Tests de la detection Tailscale (jarvis_actions/tailscale_net.py).

Coeur teste sans reseau :
- `_ip_dans_plage_tailscale` : fonction PURE (appartenance a 100.64.0.0/10).
- `statut` / `_ip_via_cli` : I/O (subprocess, shutil.which) mockees via monkeypatch.
"""

from __future__ import annotations

import pytest

from jarvis_actions import tailscale_net as ts


# ============================================================
# _ip_dans_plage_tailscale — fonction pure
# ============================================================

@pytest.mark.parametrize("ip", [
    "100.64.0.0",        # borne basse de la plage
    "100.64.0.1",
    "100.100.100.100",
    "100.127.255.255",   # borne haute de la plage
])
def test_ip_dans_plage_tailscale_vrai(ip):
    assert ts._ip_dans_plage_tailscale(ip) is True


@pytest.mark.parametrize("ip", [
    "192.168.1.10",
    "10.0.0.5",
    "8.8.8.8",
    "100.63.255.255",    # juste SOUS la plage
    "100.128.0.0",       # juste AU-DESSUS de la plage
    "172.16.0.1",
    "",
    "pas-une-ip",
    "999.999.999.999",
])
def test_ip_dans_plage_tailscale_faux(ip):
    assert ts._ip_dans_plage_tailscale(ip) is False


# ============================================================
# statut — agrege la detection
# ============================================================

def test_statut_sans_tailscale(monkeypatch):
    monkeypatch.setattr(ts, "detecter_ip", lambda: "")
    s = ts.statut()
    assert s == {"actif": False, "ip": "", "url_mobile": ""}


def test_statut_avec_ip_et_token(monkeypatch):
    monkeypatch.setattr(ts, "detecter_ip", lambda: "100.101.102.103")
    s = ts.statut(token="abc123")
    assert s["actif"] is True
    assert s["ip"] == "100.101.102.103"
    assert s["url_mobile"] == "http://100.101.102.103:8080/?token=abc123"


def test_statut_avec_ip_sans_token(monkeypatch):
    monkeypatch.setattr(ts, "detecter_ip", lambda: "100.101.102.103")
    s = ts.statut()
    assert s["url_mobile"] == "http://100.101.102.103:8080"


# ============================================================
# _ip_via_cli — wrapper de la CLI tailscale
# ============================================================

def test_ip_via_cli_absente(monkeypatch):
    """CLI tailscale absente -> chaine vide."""
    monkeypatch.setattr(ts.shutil, "which", lambda _n: None)
    assert ts._ip_via_cli() == ""


class _FakeProc:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def test_ip_via_cli_retourne_ip(monkeypatch):
    """CLI presente + sortie valide -> l'IP Tailscale est extraite."""
    monkeypatch.setattr(ts.shutil, "which", lambda _n: "tailscale")
    monkeypatch.setattr(ts.subprocess, "run",
                        lambda *a, **k: _FakeProc(stdout="100.88.0.42\n"))
    assert ts._ip_via_cli() == "100.88.0.42"


def test_ip_via_cli_ignore_ip_hors_plage(monkeypatch):
    """Une sortie qui n'est pas dans la plage Tailscale est ignoree."""
    monkeypatch.setattr(ts.shutil, "which", lambda _n: "tailscale")
    monkeypatch.setattr(ts.subprocess, "run",
                        lambda *a, **k: _FakeProc(stdout="192.168.1.5\n"))
    assert ts._ip_via_cli() == ""


def test_ip_via_cli_erreur_subprocess(monkeypatch):
    """Si subprocess leve, on degrade en chaine vide (pas d'exception)."""
    monkeypatch.setattr(ts.shutil, "which", lambda _n: "tailscale")

    def _boom(*a, **k):
        raise OSError("boom")

    monkeypatch.setattr(ts.subprocess, "run", _boom)
    assert ts._ip_via_cli() == ""


def test_detecter_ip_repli_interfaces(monkeypatch):
    """CLI vide -> repli sur le scan des interfaces."""
    monkeypatch.setattr(ts, "_ip_via_cli", lambda: "")
    monkeypatch.setattr(ts, "_ip_via_interfaces", lambda: "100.77.0.9")
    assert ts.detecter_ip() == "100.77.0.9"
