"""Tests de la config Operator (jarvis_actions/operator/config.py).

Coeur teste sans aucune ecriture dans le depot : OPERATOR_PATH est redirige vers
tmp_path. Validation par liste blanche / typage + persistance atomique + compteur
de devis.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def cfg(monkeypatch, tmp_path):
    mod = importlib.import_module("jarvis_actions.operator.config")
    monkeypatch.setattr(mod, "OPERATOR_PATH", tmp_path / "jarvis_operator.json")
    return mod


def test_defauts_quand_absent(cfg):
    c = cfg.charger()
    assert c["societe"]["nom"] == ""
    assert c["autonomie_email"] == "tri_auto_reponses_validees"
    assert c["devis"]["compteur"] == 0
    assert c["devis"]["prefixe"] == "DEV"


def test_sauvegarde_partielle_et_validation(cfg):
    out = cfg.sauvegarder({"societe": {"nom": "ACME", "siret": "123"}})
    assert out["societe"]["nom"] == "ACME"
    assert out["societe"]["siret"] == "123"
    # rechargement persistant
    assert cfg.charger()["societe"]["nom"] == "ACME"


def test_autonomie_invalide_retombe_defaut(cfg):
    out = cfg.sauvegarder({"autonomie_email": "n_importe_quoi"})
    assert out["autonomie_email"] == "tri_auto_reponses_validees"


def test_autonomie_valide_acceptee(cfg):
    out = cfg.sauvegarder({"autonomie_email": "autonomie_totale"})
    assert out["autonomie_email"] == "autonomie_totale"


def test_tva_taux_filtre_valeurs_non_numeriques(cfg):
    out = cfg.sauvegarder({"devis": {"tva_taux_defaut": "abc"}})
    assert out["devis"]["tva_taux_defaut"] == 20.0  # defaut


def test_increment_compteur_devis(cfg):
    assert cfg.incrementer_compteur_devis() == 1
    assert cfg.incrementer_compteur_devis() == 2
    assert cfg.charger()["devis"]["compteur"] == 2


def test_regles_tri_filtre_entrees_non_dict(cfg):
    out = cfg.sauvegarder({"regles_tri": [{"si_contient": "x", "label": "X"}, "pourri", 42]})
    assert out["regles_tri"] == [{"si_contient": "x", "label": "X"}]
