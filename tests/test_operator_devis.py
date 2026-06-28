"""Tests du modele de devis polyvalent (jarvis_actions/operator/devis.py).

Calculs PURS (ligne, calculer_totaux, numero_suivant, construire) + extraction
async depuis un transcript (from_transcript) avec LLM mocke. Aucun acces reseau.
"""

from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture
def devis():
    return importlib.import_module("jarvis_actions.operator.devis")


def _config(prefixe="DEV", compteur=0):
    return {
        "societe": {"nom": "ACME"},
        "devis": {
            "prefixe": prefixe,
            "compteur": compteur,
            "tva_taux_defaut": 20.0,
            "validite_jours": 30,
            "mentions": "Paiement a 30 jours.",
        },
    }


def test_ligne_total_ht(devis):
    l = devis.ligne("Pose carrelage", "prestation", 10, "h", 50, 20)
    assert l["total_ht"] == 500.0
    assert l["type"] == "prestation"
    assert l["quantite"] == 10.0 and l["pu_ht"] == 50.0 and l["tva_pct"] == 20.0


def test_calculer_totaux_mono_taux(devis):
    lignes = [devis.ligne("Service", "prestation", 1, "u", 200, 20)]
    t = devis.calculer_totaux(lignes)
    assert t["total_ht"] == 200.0
    assert t["tva_par_taux"][20.0] == 40.0
    assert t["total_tva"] == 40.0
    assert t["total_ttc"] == 240.0


def test_calculer_totaux_multi_taux(devis):
    lignes = [
        devis.ligne("Main d'oeuvre", "prestation", 10, "h", 50, 10),  # 500 HT a 10%
        devis.ligne("Forfait", "produit", 1, "u", 200, 20),           # 200 HT a 20%
    ]
    t = devis.calculer_totaux(lignes)
    assert t["total_ht"] == 700.0
    assert t["tva_par_taux"][10.0] == 50.0
    assert t["tva_par_taux"][20.0] == 40.0
    assert t["total_tva"] == 90.0
    assert t["total_ttc"] == 790.0


def test_calculer_totaux_arrondi(devis):
    lignes = [devis.ligne("Materiau", "materiau", 3, "u", 9.99, 20)]
    t = devis.calculer_totaux(lignes)
    assert t["total_ht"] == 29.97
    assert t["total_ttc"] == 35.96


def test_calculer_totaux_vide_defensif(devis):
    t = devis.calculer_totaux(None)
    assert t["total_ht"] == 0.0 and t["total_ttc"] == 0.0
    assert t["tva_par_taux"] == {}


def test_numero_suivant_compteur_41(devis):
    num = devis.numero_suivant({"prefixe": "DEV", "compteur": 41})
    assert num.endswith("0042")
    assert num.startswith("DEV-")


def test_numero_suivant_defauts(devis):
    num = devis.numero_suivant({})
    assert num.startswith("DEV-")
    assert num.endswith("0001")


def test_construire_devis_complet(devis):
    cfg = _config(compteur=0)
    lignes = [devis.ligne("Service", "prestation", 1, "u", 200, 20)]
    d = devis.construire({"nom": "Client", "email": "c@x.fr"}, lignes, cfg)
    assert d["numero"].endswith("0001")
    assert d["validite_jours"] == 30
    assert d["mentions"] == "Paiement a 30 jours."
    assert d["societe"]["nom"] == "ACME"
    assert d["totaux"]["total_ttc"] == 240.0
    assert d["client"]["nom"] == "Client"
    assert len(d["date"]) == 10  # YYYY-MM-DD


@pytest.mark.asyncio
async def test_from_transcript_json_valide(devis):
    reponse = json.dumps({
        "client": {"nom": "Dupont", "email": "d@x.fr"},
        "lignes": [
            {"libelle": "Pose", "type": "prestation", "quantite": 10,
             "unite": "h", "pu_ht": 50, "tva_pct": 20},
        ],
    })

    async def demander_json(prompt):
        assert "JSON" in prompt
        return reponse

    d = await devis.from_transcript("pose 10h a 50e", demander_json, _config())
    assert d["client"]["nom"] == "Dupont"
    assert len(d["lignes"]) == 1
    assert d["totaux"]["total_ht"] == 500.0
    assert d["totaux"]["total_ttc"] == 600.0


@pytest.mark.asyncio
async def test_from_transcript_tva_par_defaut(devis):
    # tva_pct absente -> doit prendre tva_taux_defaut (20.0)
    reponse = json.dumps({
        "client": {"nom": "X"},
        "lignes": [{"libelle": "Truc", "type": "produit",
                    "quantite": 2, "unite": "u", "pu_ht": 100}],
    })

    async def demander_json(prompt):
        return reponse

    d = await devis.from_transcript("deux trucs a 100", demander_json, _config())
    assert d["lignes"][0]["tva_pct"] == 20.0
    assert d["totaux"]["total_tva"] == 40.0


@pytest.mark.asyncio
async def test_from_transcript_sortie_invalide(devis):
    async def demander_json(prompt):
        return "desole je n'ai pas compris la demande"

    d = await devis.from_transcript("blabla", demander_json, _config())
    assert d["lignes"] == []
    assert d["totaux"]["total_ttc"] == 0.0
    assert d["numero"].endswith("0001")


@pytest.mark.asyncio
async def test_from_transcript_coroutine_qui_leve(devis):
    async def demander_json(prompt):
        raise RuntimeError("LLM indisponible")

    d = await devis.from_transcript("blabla", demander_json, _config())
    assert d["lignes"] == []
    assert d["totaux"]["total_ttc"] == 0.0
