"""Tests des triggers contextuels (jarvis_actions.triggers).

Couvre : validation/normalisation (evenement valide, types), declenchement
(_trigger_declenche) au lancement/fermeture avec recherche de sous-chaine
insensible a la casse, et disponible() qui ne leve jamais.

La fixture `triggers` (conftest) redirige TRIGGERS_PATH vers tmp_path.
"""

from __future__ import annotations


# ============================================================
# Validation
# ============================================================

def test_valider_force_types_et_id(triggers):
    """valider force les types et genere un id si absent."""
    t = triggers.valider({
        "nom": "  VSCode  ",
        "processus": "  Code.exe  ",
        "evenement": "fermeture",
        "commande": "  dis au revoir  ",
        "actif": True,
    })
    assert isinstance(t["id"], str) and t["id"]
    assert t["nom"] == "VSCode"
    assert t["processus"] == "Code.exe"
    assert t["evenement"] == "fermeture"
    assert t["commande"] == "dis au revoir"
    assert t["actif"] is True


def test_valider_evenement_invalide_retombe_sur_lancement(triggers):
    """Un evenement inconnu retombe sur 'lancement'."""
    assert triggers.valider({"evenement": "explosion"})["evenement"] == "lancement"
    assert triggers.valider({"evenement": 42})["evenement"] == "lancement"


def test_valider_defauts_sur_dict_vide(triggers):
    """Un trigger vide recoit des defauts surs (nom 'Trigger', actif True)."""
    t = triggers.valider({})
    assert t["nom"] == "Trigger"
    assert t["processus"] == ""
    assert t["evenement"] == "lancement"
    assert t["commande"] == ""
    assert t["actif"] is True


def test_valider_objet_non_dict(triggers):
    """valider tolere un argument non-dict et renvoie un trigger par defaut."""
    t = triggers.valider("pas un dict")
    assert t["evenement"] == "lancement"
    assert isinstance(t["id"], str) and t["id"]


# ============================================================
# _trigger_declenche : lancement / fermeture, sous-chaine, casse
# ============================================================

def _trig(triggers, **kw):
    base = {"processus": "code", "evenement": "lancement", "commande": "go", "actif": True}
    base.update(kw)
    return triggers.valider(base)


def test_declenche_au_lancement(triggers):
    """Evenement 'lancement' : declenche si le process apparait (sous-chaine)."""
    t = _trig(triggers, processus="code", evenement="lancement")
    apparus = {"code.exe", "chrome.exe"}
    disparus: set[str] = set()
    assert triggers._trigger_declenche(t, apparus, disparus) is True


def test_declenche_a_la_fermeture(triggers):
    """Evenement 'fermeture' : declenche si le process disparait."""
    t = _trig(triggers, processus="spotify", evenement="fermeture")
    apparus: set[str] = set()
    disparus = {"spotify.exe"}
    assert triggers._trigger_declenche(t, apparus, disparus) is True


def test_sous_chaine_insensible_casse(triggers):
    """La recherche est une sous-chaine insensible a la casse."""
    # _processus_actifs met les noms en minuscules ; cible "Code.exe" est
    # normalisee par _trigger_declenche -> matche "code.exe".
    t = _trig(triggers, processus="Code", evenement="lancement")
    assert triggers._trigger_declenche(t, {"code.exe"}, set()) is True


def test_ne_declenche_pas_mauvais_evenement(triggers):
    """Un 'lancement' ne declenche pas sur un process disparu."""
    t = _trig(triggers, processus="code", evenement="lancement")
    assert triggers._trigger_declenche(t, set(), {"code.exe"}) is False


def test_ne_declenche_pas_si_inactif(triggers):
    """Un trigger inactif ne se declenche jamais."""
    t = _trig(triggers, processus="code", actif=False)
    assert triggers._trigger_declenche(t, {"code.exe"}, set()) is False


def test_ne_declenche_pas_si_processus_vide(triggers):
    """Un trigger sans processus cible ne se declenche pas."""
    t = _trig(triggers, processus="")
    assert triggers._trigger_declenche(t, {"code.exe"}, set()) is False


def test_ne_declenche_pas_si_aucun_match(triggers):
    """Aucun process ne contient la sous-chaine -> pas de declenchement."""
    t = _trig(triggers, processus="discord", evenement="lancement")
    assert triggers._trigger_declenche(t, {"code.exe", "chrome.exe"}, set()) is False


# ============================================================
# disponible() ne leve jamais
# ============================================================

def test_disponible_ne_leve_pas(triggers):
    """disponible() renvoie un bool sans jamais lever (psutil present ou non)."""
    res = triggers.disponible()
    assert isinstance(res, bool)


# ============================================================
# Persistance CRUD
# ============================================================

def test_ajouter_supprimer(triggers):
    """ajouter persiste un trigger, supprimer le retire par id."""
    liste = triggers.ajouter({"id": "t1", "processus": "code", "commande": "go"})
    assert any(t["id"] == "t1" for t in liste)
    restant = triggers.supprimer("t1")
    assert all(t["id"] != "t1" for t in restant)


def test_maj_remplace_par_id(triggers):
    """maj remplace le trigger de meme id sans dupliquer."""
    triggers.ajouter({"id": "t1", "processus": "code", "commande": "a"})
    liste = triggers.maj({"id": "t1", "processus": "code", "commande": "b"})
    cibles = [t for t in liste if t["id"] == "t1"]
    assert len(cibles) == 1
    assert cibles[0]["commande"] == "b"


def test_charger_fichier_absent(triggers):
    """charger renvoie [] quand le fichier n'existe pas."""
    assert triggers.charger() == []


def test_charger_format_invalide(triggers):
    """Un JSON qui n'est pas une liste renvoie [] sans crasher."""
    triggers.TRIGGERS_PATH.write_text('{"pas": "une liste"}', encoding="utf-8")
    assert triggers.charger() == []
