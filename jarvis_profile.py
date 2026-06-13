"""Profil utilisateur enrichi de Jarvis (identite, famille, adresse, habitudes...).

Equivalent local de la personnalisation Claude : un fichier JSON editable
(jarvis_profile.json, gitignore conseille — donnees personnelles) dont le
contenu est injecte dans le system prompt via contexte_profil().

Schema complet (toutes les cles optionnelles, defauts vides) :
voir examples/jarvis_profile_example.json.

Usage cote main2.py :
    from jarvis_profile import contexte_profil, enregistrer_info_profil
    bloc = contexte_profil()          # "" si profil vide, sinon bloc pret a coller
    enregistrer_info_profil("habitude", "se leve a 7h")  # -> (reponse, succes)

Aucune fonction de ce module ne leve d'exception : tout est attrape et
journalise pour ne jamais faire tomber main2.py.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _dossier_donnees() -> Path:
    """Dossier ou lire/ecrire les donnees perso. A cote de l'exe en mode
    PyInstaller (sys._MEIPASS est temporaire et efface a la sortie), sinon
    racine du repo. Garantit la persistance du profil entre deux lancements."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


PROFILE_PATH: Path = _dossier_donnees() / "jarvis_profile.json"

MAX_STR = 500    # longueur max d'une chaine apres trim
MAX_LISTE = 50   # nombre max d'entrees par liste

# Sous-cles attendues pour chaque section structuree du schema
_CHAMPS_IDENTITE = ("prenom", "surnom_prefere", "date_naissance", "metier")
_CHAMPS_ADRESSE = ("rue", "ville", "code_postal", "pays")
_CHAMPS_FAMILLE = ("nom", "relation", "notes")
_CHAMPS_ROUTINE = ("quand", "quoi")

# Categories vocales acceptees par enregistrer_info_profil -> cle du schema
_CATEGORIES_LISTE = {
    "habitude": "habitudes",
    "habitudes": "habitudes",
    "preference": "preferences",
    "preferences": "preferences",
}


def _profil_vide() -> dict:
    """Retourne un nouveau profil au schema complet, valeurs vides."""
    return {
        "identite": {champ: "" for champ in _CHAMPS_IDENTITE},
        "famille": [],
        "adresse": {champ: "" for champ in _CHAMPS_ADRESSE},
        "habitudes": [],
        "preferences": [],
        "routines": [],
        "notes_libres": "",
    }


def _nettoyer_str(valeur: Any) -> str:
    """Force en chaine propre : trim + coupe a MAX_STR caracteres.

    Les nombres sont convertis en texte, tout le reste devient "".
    """
    if isinstance(valeur, bool) or valeur is None:
        return ""
    if isinstance(valeur, (int, float)):
        valeur = str(valeur)
    if not isinstance(valeur, str):
        return ""
    return valeur.strip()[:MAX_STR]


def _nettoyer_section(brut: Any, champs: tuple[str, ...]) -> dict:
    """Ne garde que les champs attendus d'une section dict (copie neuve)."""
    if not isinstance(brut, dict):
        brut = {}
    return {champ: _nettoyer_str(brut.get(champ)) for champ in champs}


def _nettoyer_liste_str(brut: Any) -> list[str]:
    """Liste de chaines propres, entrees vides retirees, MAX_LISTE max."""
    if not isinstance(brut, list):
        return []
    propres = [_nettoyer_str(entree) for entree in brut]
    return [entree for entree in propres if entree][:MAX_LISTE]


def _nettoyer_liste_dicts(brut: Any, champs: tuple[str, ...]) -> list[dict]:
    """Liste de dicts restreints aux champs attendus, entrees vides retirees."""
    if not isinstance(brut, list):
        return []
    propres: list[dict] = []
    for entree in brut:
        nettoye = _nettoyer_section(entree, champs)
        if any(nettoye.values()):
            propres.append(nettoye)
        if len(propres) >= MAX_LISTE:
            break
    return propres


def valider_profil(profil: dict) -> dict:
    """Retourne une copie du profil limitee au schema attendu.

    Cles inconnues supprimees, types forces, chaines trimees et coupees a
    MAX_STR caracteres, listes plafonnees a MAX_LISTE entrees.
    Ne modifie jamais le dict passe en argument (copie neuve).
    """
    if not isinstance(profil, dict):
        profil = {}
    return {
        "identite": _nettoyer_section(profil.get("identite"), _CHAMPS_IDENTITE),
        "famille": _nettoyer_liste_dicts(profil.get("famille"), _CHAMPS_FAMILLE),
        "adresse": _nettoyer_section(profil.get("adresse"), _CHAMPS_ADRESSE),
        "habitudes": _nettoyer_liste_str(profil.get("habitudes")),
        "preferences": _nettoyer_liste_str(profil.get("preferences")),
        "routines": _nettoyer_liste_dicts(profil.get("routines"), _CHAMPS_ROUTINE),
        "notes_libres": _nettoyer_str(profil.get("notes_libres")),
    }


def charger_profil() -> dict:
    """Lit jarvis_profile.json et retourne un profil complet et valide.

    Fichier absent, illisible ou corrompu -> profil vide. Jamais d'exception.
    """
    try:
        if not PROFILE_PATH.exists():
            return _profil_vide()
        with open(PROFILE_PATH, "r", encoding="utf-8") as f:
            brut = json.load(f)
        return valider_profil(brut)
    except Exception as e:
        print(f"[PROFIL] Lecture impossible ({e}), profil vide utilise")
        return _profil_vide()


def sauvegarder_profil(profil: dict) -> bool:
    """Valide puis ecrit le profil sur disque (ecriture atomique .tmp + replace).

    Retourne True si l'ecriture a reussi, False sinon. Jamais d'exception.
    """
    tmp_path = PROFILE_PATH.with_name(PROFILE_PATH.name + ".tmp")
    try:
        propre = valider_profil(profil)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(propre, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, PROFILE_PATH)
        return True
    except Exception as e:
        print(f"[PROFIL] Echec sauvegarde : {e}")
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        return False


def _lignes_identite(identite: dict) -> list[str]:
    """Lignes "- Libelle : valeur" pour les champs identite renseignes."""
    libelles = {
        "prenom": "Prenom",
        "surnom_prefere": "Surnom prefere",
        "date_naissance": "Date de naissance",
        "metier": "Metier",
    }
    return [
        f"- {libelles[champ]} : {identite[champ]}"
        for champ in _CHAMPS_IDENTITE
        if identite[champ]
    ]


def _ligne_famille(famille: list[dict]) -> str:
    """Rend la famille en une ligne : "Marie (sa femme), aime le the ; ..."."""
    if not famille:
        return ""
    membres: list[str] = []
    for membre in famille:
        texte = membre["nom"] or "?"
        if membre["relation"]:
            texte += f" ({membre['relation']})"
        if membre["notes"]:
            texte += f", {membre['notes']}"
        membres.append(texte)
    return "- Famille : " + " ; ".join(membres)


def _ligne_adresse(adresse: dict) -> str:
    """Rend l'adresse en une ligne, champs vides ignores."""
    morceaux = [adresse[champ] for champ in _CHAMPS_ADRESSE if adresse[champ]]
    return "- Adresse : " + ", ".join(morceaux) if morceaux else ""


def _ligne_routines(routines: list[dict]) -> str:
    """Rend les routines en une ligne : "le matin : resume meteo ; ..."."""
    if not routines:
        return ""
    rendus: list[str] = []
    for routine in routines:
        if routine["quand"] and routine["quoi"]:
            rendus.append(f"{routine['quand']} : {routine['quoi']}")
        else:
            rendus.append(routine["quand"] or routine["quoi"])
    return "- Routines : " + " ; ".join(rendus)


def contexte_profil() -> str:
    """Rend le profil en bloc de prose francaise pour le system prompt.

    Retourne "" si le profil est entierement vide (rien a injecter).
    Jamais d'exception.
    """
    try:
        profil = charger_profil()
        if profil == _profil_vide():
            return ""

        lignes: list[str] = ["PROFIL DE L'UTILISATEUR :"]
        lignes.extend(_lignes_identite(profil["identite"]))
        for ligne in (
            _ligne_famille(profil["famille"]),
            _ligne_adresse(profil["adresse"]),
        ):
            if ligne:
                lignes.append(ligne)
        if profil["habitudes"]:
            lignes.append("- Habitudes : " + " ; ".join(profil["habitudes"]))
        if profil["preferences"]:
            lignes.append("- Preferences : " + " ; ".join(profil["preferences"]))
        ligne_routines = _ligne_routines(profil["routines"])
        if ligne_routines:
            lignes.append(ligne_routines)
        if profil["notes_libres"]:
            lignes.append("- Notes : " + profil["notes_libres"])

        lignes.append(
            "Utilise ces informations naturellement quand c'est pertinent, "
            "sans les reciter ni les rappeler explicitement a l'utilisateur."
        )
        return "\n".join(lignes)
    except Exception as e:
        print(f"[PROFIL] Echec rendu contexte : {e}")
        return ""


def enregistrer_info_profil(categorie: str, info: str) -> tuple[str, bool]:
    """Ajoute une info dictee vocalement dans le profil.

    categorie : "habitude(s)" ou "preference(s)" -> liste correspondante ;
    toute autre valeur -> notes_libres. Retourne (reponse_vocale, succes)
    comme les modules jarvis_actions. Jamais d'exception.
    """
    try:
        info_propre = _nettoyer_str(info)
        if not info_propre:
            return ("Je n'ai rien compris a retenir, desole.", False)

        profil = charger_profil()
        cle = _CATEGORIES_LISTE.get(_nettoyer_str(categorie).lower())
        if cle:
            if info_propre in profil[cle]:
                return ("Je le sais deja, c'est dans votre profil.", True)
            if len(profil[cle]) >= MAX_LISTE:
                return (f"La liste des {cle} est pleine ({MAX_LISTE} maximum).", False)
            nouveau = {**profil, cle: [*profil[cle], info_propre]}
            libelle = f"vos {cle}"
        else:
            notes = profil["notes_libres"]
            ajout = f"{notes}\n{info_propre}" if notes else info_propre
            nouveau = {**profil, "notes_libres": ajout[:MAX_STR]}
            libelle = "mes notes"

        if sauvegarder_profil(nouveau):
            return (f"C'est note dans {libelle}.", True)
        return ("Je n'ai pas reussi a enregistrer cette information.", False)
    except Exception as e:
        print(f"[PROFIL] Echec enregistrement info : {e}")
        return ("Je n'ai pas reussi a enregistrer cette information.", False)
