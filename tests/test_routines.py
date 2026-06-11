"""Tests du planificateur de routines (jarvis_actions.routines).

Couvre : validation/normalisation (heure HH:MM, jours 0..6), declenchement aux
bons creneaux avec un datetime fixe, et anti-double via la boucle (sans attendre
de vraies secondes : on remplace asyncio.sleep par une coupure controlee).

La fixture `routines` (conftest) redirige ROUTINES_PATH vers tmp_path.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest


# ============================================================
# Validation
# ============================================================

def test_valider_force_types_et_id(routines):
    """valider force les types, garde l'id fourni et plafonne les chaines."""
    r = routines.valider({
        "id": "abc",
        "nom": 123,
        "heure": "07:05",
        "jours": [1, 2],
        "commande": "  quelle meteo  ",
        "actif": "oui",  # non-bool -> bool() applique
    })
    assert r["id"] == "abc"
    assert r["nom"] == "123"
    assert r["heure"] == "07:05"
    assert r["jours"] == [1, 2]
    assert r["commande"] == "quelle meteo"
    assert r["actif"] is True


def test_valider_genere_id_si_absent(routines):
    """Un id absent est genere (chaine hex non vide)."""
    r = routines.valider({"commande": "x"})
    assert isinstance(r["id"], str) and r["id"]


def test_heure_invalide_retombe_sur_defaut(routines):
    """Une heure invalide retombe sur HEURE_DEFAUT (08:00)."""
    assert routines.valider({"heure": "99:99"})["heure"] == routines.HEURE_DEFAUT
    assert routines.valider({"heure": "pasunheure"})["heure"] == routines.HEURE_DEFAUT
    assert routines.valider({"heure": "7:5"})["heure"] == "07:05"  # normalisation


def test_jours_filtres_tries_dedoublonnes(routines):
    """Les jours hors 0..6, doublons et non-entiers sont ecartes/tries."""
    r = routines.valider({"jours": [6, 0, 0, 9, -1, "x", True, 3]})
    # True est un bool -> ignore ; 9 et -1 hors plage ; "x" non int.
    assert r["jours"] == [0, 3, 6]


# ============================================================
# _doit_declencher (datetime fixe)
# ============================================================

def _routine(routines, **kw):
    """Construit une routine validee avec des champs surchargeables."""
    base = {"nom": "t", "heure": "08:00", "jours": [], "commande": "go", "actif": True}
    base.update(kw)
    return routines.valider(base)


def test_doit_declencher_au_bon_creneau(routines):
    """Declenche si heure == HH:MM courant et jour autorise (lundi = 0)."""
    # 2024-01-01 est un lundi.
    maintenant = datetime(2024, 1, 1, 8, 0)
    r = _routine(routines, heure="08:00", jours=[0])
    assert routines._doit_declencher(r, maintenant) is True


def test_ne_declenche_pas_mauvaise_heure(routines):
    """Pas de declenchement si l'heure ne correspond pas a la minute courante."""
    maintenant = datetime(2024, 1, 1, 8, 1)
    r = _routine(routines, heure="08:00", jours=[])
    assert routines._doit_declencher(r, maintenant) is False


def test_ne_declenche_pas_mauvais_jour(routines):
    """Pas de declenchement si le jour courant n'est pas dans la liste."""
    # Lundi (0), mais routine seulement le mardi (1).
    maintenant = datetime(2024, 1, 1, 8, 0)
    r = _routine(routines, heure="08:00", jours=[1])
    assert routines._doit_declencher(r, maintenant) is False


def test_jours_vide_signifie_tous_les_jours(routines):
    """Une liste de jours vide declenche n'importe quel jour a la bonne heure."""
    maintenant = datetime(2024, 1, 3, 8, 0)  # mercredi
    r = _routine(routines, heure="08:00", jours=[])
    assert routines._doit_declencher(r, maintenant) is True


def test_ne_declenche_pas_si_inactif(routines):
    """Une routine inactive ne se declenche jamais."""
    maintenant = datetime(2024, 1, 1, 8, 0)
    r = _routine(routines, heure="08:00", jours=[], actif=False)
    assert routines._doit_declencher(r, maintenant) is False


def test_ne_declenche_pas_si_commande_vide(routines):
    """Une routine sans commande ne se declenche pas."""
    maintenant = datetime(2024, 1, 1, 8, 0)
    r = _routine(routines, heure="08:00", jours=[], commande="")
    assert routines._doit_declencher(r, maintenant) is False


# ============================================================
# Persistance CRUD
# ============================================================

def test_ajouter_et_charger(routines):
    """ajouter persiste la routine et charger la relit."""
    routines.ajouter({"id": "r1", "heure": "09:00", "commande": "salut"})
    charge = routines.charger()
    assert any(r["id"] == "r1" for r in charge)


def test_ajouter_upsert_par_id(routines):
    """Re-ajouter le meme id remplace la routine (comportement upsert)."""
    routines.ajouter({"id": "r1", "commande": "a"})
    routines.ajouter({"id": "r1", "commande": "b"})
    charge = [r for r in routines.charger() if r["id"] == "r1"]
    assert len(charge) == 1
    assert charge[0]["commande"] == "b"


def test_supprimer(routines):
    """supprimer retire la routine d'id donne."""
    routines.ajouter({"id": "r1", "commande": "a"})
    routines.supprimer("r1")
    assert all(r["id"] != "r1" for r in routines.charger())


# ============================================================
# Boucle planificateur : anti-double sur la meme minute
# ============================================================

def test_planificateur_anti_double(routines, monkeypatch):
    """Sur deux tours dans la meme minute, la routine ne se lance qu'une fois."""
    # Fige datetime.now() a une minute precise pour les deux iterations.
    fixe = datetime(2024, 1, 1, 8, 0, 0)

    class _FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixe

    monkeypatch.setattr(routines, "datetime", _FakeDatetime)
    routines.ajouter({"id": "r1", "heure": "08:00", "jours": [], "commande": "go"})

    appels: list[str] = []

    async def faux_executer(texte: str) -> None:
        appels.append(texte)

    # On capture le vrai asyncio.sleep AVANT de patcher pour ne pas recurser.
    vrai_sleep = asyncio.sleep
    tours = {"n": 0}

    async def faux_sleep(_s):
        # Simule la fin d'iteration : laisse tourner les taches detachees puis,
        # apres deux tours dans la meme minute, annule la boucle.
        tours["n"] += 1
        await vrai_sleep(0)
        if tours["n"] >= 2:
            raise asyncio.CancelledError()

    # Patch cible sur l'attribut utilise par la boucle (restaure par monkeypatch).
    monkeypatch.setattr(routines.asyncio, "sleep", faux_sleep)

    async def scenario():
        try:
            await routines.demarrer_planificateur(faux_executer, intervalle_s=0.0)
        except asyncio.CancelledError:
            pass
        # Laisse les taches create_task() finir leur execution.
        await vrai_sleep(0)

    asyncio.run(scenario())
    # Malgre 2 tours dans la meme minute, une seule execution.
    assert appels == ["go"]


def test_executer_maintenant(routines):
    """executer_maintenant lance la routine ciblee et renvoie True."""
    routines.ajouter({"id": "r1", "commande": "go", "actif": False})
    appels: list[str] = []

    async def faux_executer(texte: str) -> None:
        appels.append(texte)

    ok = asyncio.run(routines.executer_maintenant("r1", faux_executer))
    assert ok is True
    assert appels == ["go"]


def test_executer_maintenant_id_inconnu(routines):
    """executer_maintenant renvoie False si l'id n'existe pas."""
    async def faux_executer(texte: str) -> None:  # pragma: no cover - jamais appele
        raise AssertionError("ne doit pas etre appele")

    assert asyncio.run(routines.executer_maintenant("absent", faux_executer)) is False
