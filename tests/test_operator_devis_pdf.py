"""Tests du rendu PDF de devis (jarvis_actions/operator/devis_pdf.py).

La degradation (fpdf absent) est testee sans dependance ; le rendu reel n'est
execute que si fpdf2 est installe (pytest.importorskip). Aucun acces reseau.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def mod():
    return importlib.import_module("jarvis_actions.operator.devis_pdf")


def _devis_minimal() -> dict:
    return {
        "numero": "DEV-1",
        "societe": {},
        "client": {},
        "lignes": [],
        "totaux": {"total_ht": 0, "tva_par_taux": {}, "total_tva": 0, "total_ttc": 0},
        "mentions": "",
    }


def _devis_complet() -> dict:
    return {
        "numero": "DEV-2026-007",
        "date": "2026-06-28",
        "societe": {
            "nom": "ACME SARL",
            "adresse": "1 rue des Tests, 75000 Paris",
            "siret": "12345678900011",
            "email": "contact@acme.fr",
            "tel": "01 02 03 04 05",
            "iban": "FR76 0000 0000 0000",
        },
        "client": {
            "nom": "Client Demo",
            "adresse": "2 avenue du Code, 69000 Lyon",
            "email": "client@demo.fr",
        },
        "lignes": [
            {
                "libelle": "Developpement module",
                "quantite": 2,
                "unite": "jour",
                "pu_ht": 500.0,
                "tva_pct": 20.0,
                "total_ht": 1000.0,
            },
            {
                "libelle": "Maintenance",
                "quantite": 1,
                "unite": "forfait",
                "pu_ht": 150.0,
                "tva_pct": 10.0,
                "total_ht": 150.0,
            },
        ],
        "totaux": {
            "total_ht": 1150.0,
            "tva_par_taux": {"20.0": 200.0, "10.0": 15.0},
            "total_tva": 215.0,
            "total_ttc": 1365.0,
        },
        "mentions": "Devis valable 30 jours.\nReglement a 30 jours.",
    }


def test_degradation_sans_fpdf(mod, monkeypatch):
    """Si _charger_fpdf renvoie None, rendre retourne None sans lever."""
    monkeypatch.setattr(mod, "_charger_fpdf", lambda: None)
    assert mod.disponible() is False
    assert mod.rendre(_devis_minimal()) is None


def test_nettoyer_nom_defensif(mod):
    """Le nettoyage du numero ne leve jamais et n'est jamais vide."""
    assert mod._nettoyer_nom("DEV/2026 #1") == "DEV_2026_1"
    assert mod._nettoyer_nom("") == "devis"
    assert mod._nettoyer_nom(None) == "devis"


def test_rendu_reel_conditionnel(mod, tmp_path):
    """Avec fpdf2 installe : un PDF non vide est ecrit dans tmp_path."""
    pytest.importorskip("fpdf")
    chemin = mod.rendre(_devis_complet(), dossier=tmp_path)
    assert chemin is not None
    fichier = tmp_path / "DEV-2026-007.pdf"
    assert fichier.exists()
    assert fichier.stat().st_size > 0
