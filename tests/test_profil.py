"""Tests du module jarvis_profile (profil utilisateur enrichi).

Couvre : validation/normalisation du schema, contexte vide si profil vide,
round-trip sauvegarder/charger, et enregistrement d'infos vocales.

La fixture `profil` (conftest) redirige PROFILE_PATH vers tmp_path : aucune
ecriture dans le depot.
"""

from __future__ import annotations


def test_valider_force_types_et_caps(profil):
    """valider_profil ignore les cles inconnues, force les types et plafonne."""
    brut = {
        "identite": {"prenom": "  Tony  ", "metier": 42, "inconnu": "x"},
        "famille": "pas une liste",
        "habitudes": ["  cafe  ", "", "cafe", 123, None],
        "preferences": list(range(80)),  # > MAX_LISTE
        "notes_libres": "n" * (profil.MAX_STR + 50),
        "cle_inconnue": "doit disparaitre",
    }
    valide = profil.valider_profil(brut)
    # Cle inconnue supprimee, schema complet present.
    assert set(valide.keys()) == {
        "identite", "famille", "adresse", "habitudes",
        "preferences", "routines", "notes_libres",
    }
    # Trim applique, champ inconnu de la section identite supprime.
    assert valide["identite"]["prenom"] == "Tony"
    assert "inconnu" not in valide["identite"]
    # Entier converti en texte par _nettoyer_str.
    assert valide["identite"]["metier"] == "42"
    # famille invalide -> liste vide.
    assert valide["famille"] == []
    # Liste nettoyee : vides retires, types forces (123 -> "123").
    assert "" not in valide["habitudes"]
    assert "cafe" in valide["habitudes"]
    # Plafond MAX_LISTE applique.
    assert len(valide["preferences"]) <= profil.MAX_LISTE
    # Chaine coupee a MAX_STR.
    assert len(valide["notes_libres"]) <= profil.MAX_STR


def test_valider_ne_mute_pas_l_original(profil):
    """valider_profil retourne une copie neuve sans muter l'argument."""
    brut = {"identite": {"prenom": "Tony"}}
    copie_avant = {"identite": {"prenom": "Tony"}}
    profil.valider_profil(brut)
    assert brut == copie_avant


def test_contexte_vide_si_profil_vide(profil):
    """contexte_profil retourne "" quand aucun fichier (profil entierement vide)."""
    assert profil.contexte_profil() == ""


def test_round_trip_sauvegarder_charger(profil):
    """sauvegarder_profil puis charger_profil restituent les memes donnees."""
    source = {
        "identite": {"prenom": "Tony", "metier": "ingenieur"},
        "famille": [{"nom": "Marie", "relation": "epouse", "notes": "aime le the"}],
        "habitudes": ["se leve a 7h"],
        "notes_libres": "aime la mecanique",
    }
    assert profil.sauvegarder_profil(source) is True
    assert profil.PROFILE_PATH.exists()
    recharge = profil.charger_profil()
    assert recharge["identite"]["prenom"] == "Tony"
    assert recharge["identite"]["metier"] == "ingenieur"
    assert recharge["famille"][0]["nom"] == "Marie"
    assert recharge["habitudes"] == ["se leve a 7h"]
    assert recharge["notes_libres"] == "aime la mecanique"


def test_charger_fichier_absent_renvoie_vide(profil):
    """charger_profil renvoie un profil vide si le fichier n'existe pas."""
    assert not profil.PROFILE_PATH.exists()
    charge = profil.charger_profil()
    assert charge == profil._profil_vide()


def test_charger_json_corrompu_renvoie_vide(profil):
    """Un JSON corrompu sur disque ne fait pas crasher : profil vide retourne."""
    profil.PROFILE_PATH.write_text("{ pas du json valide", encoding="utf-8")
    assert profil.charger_profil() == profil._profil_vide()


def test_contexte_non_vide_apres_sauvegarde(profil):
    """contexte_profil produit un bloc prose non vide si le profil est renseigne."""
    profil.sauvegarder_profil({"identite": {"prenom": "Tony"}})
    bloc = profil.contexte_profil()
    assert bloc != ""
    assert "PROFIL DE L'UTILISATEUR" in bloc
    assert "Tony" in bloc


def test_enregistrer_info_habitude(profil):
    """enregistrer_info_profil ajoute une habitude et persiste."""
    reponse, succes = profil.enregistrer_info_profil("habitude", "court le matin")
    assert succes is True
    assert isinstance(reponse, str) and reponse
    assert "court le matin" in profil.charger_profil()["habitudes"]


def test_enregistrer_info_doublon(profil):
    """Une habitude deja connue n'est pas dupliquee (succes mais signale)."""
    profil.enregistrer_info_profil("habitude", "court le matin")
    _, succes = profil.enregistrer_info_profil("habitude", "court le matin")
    assert succes is True
    assert profil.charger_profil()["habitudes"].count("court le matin") == 1


def test_enregistrer_info_categorie_libre_va_dans_notes(profil):
    """Une categorie inconnue range l'info dans notes_libres."""
    reponse, succes = profil.enregistrer_info_profil("divers", "il aime le rouge")
    assert succes is True
    assert "il aime le rouge" in profil.charger_profil()["notes_libres"]


def test_enregistrer_info_vide_echoue(profil):
    """Une info vide n'est pas enregistree (succes False)."""
    _, succes = profil.enregistrer_info_profil("habitude", "   ")
    assert succes is False
