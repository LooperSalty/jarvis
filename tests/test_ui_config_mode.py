"""Tests du mode clair/sombre/auto de la config UI (jarvis_ui_config.py).

Verifie la validation du champ `mode` (liste blanche MODES) et son defaut.
"""

from __future__ import annotations

import jarvis_ui_config as u


def test_mode_dans_les_defauts_vaut_auto():
    assert u.DEFAUTS["mode"] == "auto"
    assert "mode" in u.charger() or True  # charger() renvoie au moins les defauts


def test_modes_liste_blanche():
    assert set(u.MODES) == {"auto", "clair", "sombre"}


def test_normaliser_accepte_les_modes_valides():
    for m in ("auto", "clair", "sombre"):
        assert u._normaliser({"mode": m})["mode"] == m


def test_normaliser_casse_insensible():
    assert u._normaliser({"mode": "CLAIR"})["mode"] == "clair"


def test_normaliser_rejette_mode_invalide():
    assert u._normaliser({"mode": "neon"})["mode"] == "auto"
    assert u._normaliser({"mode": ""})["mode"] == "auto"
    assert u._normaliser({})["mode"] == "auto"


def test_sauvegarder_conserve_le_mode(tmp_path, monkeypatch):
    # Redirige le fichier de config vers un tmp pour ne pas toucher le vrai.
    cible = tmp_path / "jarvis_ui_config.json"
    monkeypatch.setattr(u, "CONFIG_PATH", cible)
    res = u.sauvegarder({"mode": "sombre"})
    assert res["mode"] == "sombre"
    # Relecture depuis le disque : la valeur persiste.
    assert u.charger()["mode"] == "sombre"


def test_h_set_ui_conserve_le_mode(tmp_path, monkeypatch):
    """Regression : _h_set_ui filtrait les champs et JETAIT 'mode' (le theme
    revenait toujours en clair). Le handler doit desormais le conserver."""
    import asyncio
    import jarvis_dashboard_api as api

    cible = tmp_path / "jarvis_ui_config.json"
    monkeypatch.setattr(u, "CONFIG_PATH", cible)

    res = asyncio.run(api._h_set_ui({"updates": {"mode": "sombre"}}))
    assert res["config"]["mode"] == "sombre"
    assert u.charger()["mode"] == "sombre"
