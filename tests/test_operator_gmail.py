"""Tests des helpers de tri email Operator (jarvis_actions/operator/gmail_ops.py).

Seules les fonctions PURES sont testees (parsing, decision, entetes) : aucun reseau.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def g():
    return importlib.import_module("jarvis_actions.operator.gmail_ops")


def test_parser_classif_json_propre(g):
    out = g.parser_classif('{"categorie": "Facture", "priorite": "haute", "besoin_reponse": true}')
    assert out["categorie"] == "Facture"
    assert out["priorite"] == "haute"
    assert out["besoin_reponse"] is True


def test_parser_classif_bruite(g):
    txt = 'Voici l\'analyse: {"categorie":"Spam","priorite":"basse","besoin_reponse":false} merci'
    out = g.parser_classif(txt)
    assert out["categorie"] == "Spam" and out["besoin_reponse"] is False


def test_parser_classif_invalide_renvoie_defaut(g):
    out = g.parser_classif("pas de json ici")
    assert out["categorie"] == "Autre" and out["priorite"] == "normale"
    assert out["besoin_reponse"] is False


def test_parser_classif_priorite_invalide_normalisee(g):
    out = g.parser_classif('{"categorie":"Client","priorite":"URGENT","besoin_reponse":false}')
    assert out["priorite"] == "normale"


def test_parser_classif_inclut_raison(g):
    out = g.parser_classif('{"categorie":"Facture","priorite":"haute","besoin_reponse":false,"raison":"EDF dans le sujet"}')
    assert out["raison"] == "EDF dans le sujet"


def test_parser_classif_raison_absente_defaut(g):
    out = g.parser_classif('{"categorie":"Autre"}')
    assert out["raison"] == ""


def test_decider_action_regle_match(g):
    classif = {"categorie": "Facture", "besoin_reponse": False}
    regles = [{"si_contient": "facture", "label": "Factures", "archiver": True}]
    act = g.decider_action(classif, regles)
    assert act["label"] == "Factures" and act["archiver"] is True
    assert act["brouillon"] is False


def test_decider_action_aucune_regle(g):
    act = g.decider_action({"categorie": "Client", "besoin_reponse": False}, [])
    assert act["label"] == "" and act["archiver"] is False


def test_decider_action_brouillon_si_besoin_reponse(g):
    act = g.decider_action({"categorie": "Client", "besoin_reponse": True}, [])
    assert act["brouillon"] is True


def test_decider_action_premiere_regle_gagne(g):
    classif = {"categorie": "Newsletter", "besoin_reponse": False}
    regles = [
        {"si_contient": "newsletter", "label": "News", "archiver": True},
        {"si_contient": "newsletter", "label": "Autre", "archiver": False},
    ]
    act = g.decider_action(classif, regles)
    assert act["label"] == "News" and act["archiver"] is True


def test_extraire_entetes(g):
    msg = {
        "payload": {"headers": [
            {"name": "From", "value": "a@b.com"},
            {"name": "Subject", "value": "Bonjour"},
        ]},
        "snippet": "Ceci est un extrait",
    }
    e = g.extraire_entetes(msg)
    assert e["from"] == "a@b.com" and e["sujet"] == "Bonjour"
    assert "extrait" in e["extrait"]


def test_extraire_entetes_casse_et_manquant(g):
    msg = {"payload": {"headers": [{"name": "FROM", "value": "x@y.z"}]}}
    e = g.extraire_entetes(msg)
    assert e["from"] == "x@y.z" and e["sujet"] == "" and e["extrait"] == ""
