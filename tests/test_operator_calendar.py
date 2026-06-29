"""Tests de l'agenda Operator (jarvis_actions/operator/calendar_ops.py).

Parties pures (parser_rdv_json, construire_event, creneaux_libres) + appels
Calendar isoles via un service factice (aucun acces reseau / Google).
"""

from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture
def cal():
    return importlib.import_module("jarvis_actions.operator.calendar_ops")


# ============================================================
# construire_event
# ============================================================

def test_construire_event_fin_par_defaut_plus_1h(cal):
    body = cal.construire_event({"titre": "Dentiste", "debut_iso": "2026-07-01T14:00:00"})
    assert body["summary"] == "Dentiste"
    assert body["start"] == {"dateTime": "2026-07-01T14:00:00", "timeZone": "Europe/Paris"}
    assert body["end"] == {"dateTime": "2026-07-01T15:00:00", "timeZone": "Europe/Paris"}
    assert "location" not in body and "attendees" not in body


def test_construire_event_fin_explicite(cal):
    body = cal.construire_event({
        "titre": "Reunion",
        "debut_iso": "2026-07-01T09:00:00",
        "fin_iso": "2026-07-01T11:30:00",
    })
    assert body["end"]["dateTime"] == "2026-07-01T11:30:00"
    assert body["end"]["timeZone"] == "Europe/Paris"


def test_construire_event_lieu_et_invites(cal):
    body = cal.construire_event({
        "titre": "Chantier",
        "debut_iso": "2026-07-01T10:00:00",
        "lieu": "12 rue des Lilas",
        "invites": ["a@x.fr", "b@x.fr"],
    })
    assert body["location"] == "12 rue des Lilas"
    assert body["attendees"] == [{"email": "a@x.fr"}, {"email": "b@x.fr"}]


# ============================================================
# creneaux_libres
# ============================================================

def test_creneaux_journee_vide_un_seul_creneau(cal):
    plage = {"date": "2026-07-01", "debut": "09:00", "fin": "12:00"}
    res = cal.creneaux_libres([], plage, duree_min=30)
    assert len(res) == 1
    assert res[0]["debut"].endswith("09:00:00")
    assert res[0]["fin"].endswith("12:00:00")


def test_creneaux_event_au_milieu_deux_creneaux(cal):
    plage = {"date": "2026-07-01", "debut": "09:00", "fin": "12:00"}
    events = [{"debut": "2026-07-01T10:00:00", "fin": "2026-07-01T11:00:00"}]
    res = cal.creneaux_libres(events, plage, duree_min=30)
    assert len(res) == 2
    assert res[0]["debut"].endswith("09:00:00") and res[0]["fin"].endswith("10:00:00")
    assert res[1]["debut"].endswith("11:00:00") and res[1]["fin"].endswith("12:00:00")


def test_creneaux_forme_start_end_normalisee(cal):
    plage = {"date": "2026-07-01", "debut": "09:00", "fin": "12:00"}
    events = [{
        "start": {"dateTime": "2026-07-01T10:00:00"},
        "end": {"dateTime": "2026-07-01T11:00:00"},
    }]
    res = cal.creneaux_libres(events, plage, duree_min=30)
    assert len(res) == 2


def test_creneaux_plage_invalide_renvoie_vide(cal):
    assert cal.creneaux_libres([], {"date": "", "debut": "", "fin": ""}, 30) == []


def test_creneaux_filtre_trous_trop_courts(cal):
    # Trou de 09:00->09:15 (15 min) ecarte par duree_min=30, garde 09:15->12:00.
    plage = {"date": "2026-07-01", "debut": "09:00", "fin": "12:00"}
    events = [{"debut": "2026-07-01T09:15:00", "fin": "2026-07-01T09:30:00"}]
    res = cal.creneaux_libres(events, plage, duree_min=30)
    assert len(res) == 1
    assert res[0]["debut"].endswith("09:30:00")


# ============================================================
# parser_rdv_json
# ============================================================

def test_parser_rdv_json_propre(cal):
    texte = 'Voici le RDV : ' + json.dumps({
        "titre": "Dentiste",
        "debut_iso": "2026-07-01T14:00:00",
        "fin_iso": "2026-07-01T15:00:00",
        "lieu": "Cabinet",
        "invites": ["doc@x.fr"],
    }) + " (fin)"
    res = cal.parser_rdv_json(texte)
    assert res is not None
    assert res["titre"] == "Dentiste"
    assert res["debut_iso"] == "2026-07-01T14:00:00"
    assert res["lieu"] == "Cabinet"
    assert res["invites"] == ["doc@x.fr"]


def test_parser_rdv_json_cles_completes_defaut(cal):
    res = cal.parser_rdv_json('{"titre": "X", "debut_iso": "2026-07-01T09:00:00"}')
    assert res is not None
    assert set(res) == {"titre", "debut_iso", "fin_iso", "lieu", "invites"}
    assert res["fin_iso"] == "" and res["invites"] == []


def test_parser_rdv_json_invalide_renvoie_none(cal):
    assert cal.parser_rdv_json("aucune accolade ici") is None
    assert cal.parser_rdv_json("{ceci n'est pas du json}") is None
    assert cal.parser_rdv_json("[1, 2, 3]") is None
    assert cal.parser_rdv_json("") is None


# ============================================================
# Fonctions a effet (service factice, aucun reseau)
# ============================================================

class _FakeExec:
    def __init__(self, resultat):
        self._resultat = resultat

    def execute(self):
        return self._resultat


class _FakeEvents:
    def __init__(self, parent):
        self._p = parent

    def list(self, **kwargs):
        self._p.calls.append(("list", kwargs))
        return _FakeExec({"items": [{"id": "e1"}]})

    def insert(self, **kwargs):
        self._p.calls.append(("insert", kwargs))
        return _FakeExec({"id": "new", **kwargs.get("body", {})})

    def delete(self, **kwargs):
        self._p.calls.append(("delete", kwargs))
        return _FakeExec(None)


class _FakeService:
    def __init__(self):
        self.calls = []

    def events(self):
        return _FakeEvents(self)


def test_lister_retourne_items(cal):
    svc = _FakeService()
    items = cal.lister(svc, "2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z")
    assert items == [{"id": "e1"}]
    nom, kwargs = svc.calls[0]
    assert nom == "list" and kwargs["calendarId"] == "primary"
    assert kwargs["singleEvents"] is True and kwargs["orderBy"] == "startTime"


def test_lister_erreur_renvoie_liste_vide(cal):
    class _Boom:
        def events(self):
            raise RuntimeError("boom")

    assert cal.lister(_Boom(), "a", "b") == []


def test_creer_renvoie_event(cal):
    svc = _FakeService()
    res = cal.creer(svc, {"summary": "X"})
    assert res["id"] == "new" and res["summary"] == "X"
    assert svc.calls[0][0] == "insert"


def test_creer_erreur_renvoie_dict_vide(cal):
    class _Boom:
        def events(self):
            raise RuntimeError("boom")

    assert cal.creer(_Boom(), {}) == {}


def test_supprimer_ok(cal):
    svc = _FakeService()
    assert cal.supprimer(svc, "e1") is True
    nom, kwargs = svc.calls[0]
    assert nom == "delete" and kwargs["eventId"] == "e1"


def test_supprimer_erreur_renvoie_false(cal):
    class _Boom:
        def events(self):
            raise RuntimeError("boom")

    assert cal.supprimer(_Boom(), "x") is False
