"""Planificateur de routines de Jarvis (taches recurrentes a heure fixe).

Une ROUTINE est une commande vocale rejouee automatiquement a une heure et
des jours donnes, exactement comme si l'utilisateur l'avait dictee. Exemple :
chaque matin a 08:00, declencher "quelle est la meteo".

Schema d'une routine (contrat partage PR D) :
    {
        "id": str,            # genere si absent
        "nom": str,
        "heure": "HH:MM",     # 24h ; "08:00" par defaut si invalide
        "jours": [int, ...],  # 0=lundi .. 6=dimanche ; vide = tous les jours
        "commande": str,      # texte rejoue via executer_commande
        "actif": bool,
    }

Persistance : jarvis_routines.json a cote de l'exe si frozen, sinon racine du
repo (gitignore). Ecriture atomique (.tmp + os.replace).

Aucune fonction de ce module ne laisse remonter d'exception : tout est attrape
et journalise pour ne jamais faire tomber main2.py. La boucle du planificateur
isole chaque execution dans son propre try/except.

Usage cote main2.py :
    from jarvis_actions import routines
    asyncio.create_task(routines.demarrer_planificateur(executer_commande))
ou executer_commande est une coroutine `async fn(texte: str) -> None`.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

# Callable injectee par main2 : rejoue une commande comme une dictee vocale.
ExecuterCommande = Callable[[str], Awaitable[None]]


def _dossier_donnees() -> Path:
    """Dossier de persistance : a cote de l'exe si PyInstaller, sinon racine repo.

    sys._MEIPASS etant temporaire (efface a la sortie), on ecrit a cote de
    l'executable pour garder les routines entre deux lancements. En mode source,
    le module est dans jarvis_actions/ donc on remonte d'un cran vers la racine.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


ROUTINES_PATH: Path = _dossier_donnees() / "jarvis_routines.json"

MAX_STR = 200       # longueur max d'une chaine (nom, commande) apres trim
MAX_ROUTINES = 100  # nombre max de routines stockees
HEURE_DEFAUT = "08:00"


def _nettoyer_str(valeur: Any) -> str:
    """Force une valeur en chaine propre : trim + coupe a MAX_STR caracteres."""
    if isinstance(valeur, bool) or valeur is None:
        return ""
    if isinstance(valeur, (int, float)):
        valeur = str(valeur)
    if not isinstance(valeur, str):
        return ""
    return valeur.strip()[:MAX_STR]


def _heure_valide(valeur: Any) -> str:
    """Retourne une heure "HH:MM" valide (24h), ou HEURE_DEFAUT si invalide."""
    texte = _nettoyer_str(valeur)
    parties = texte.split(":")
    if len(parties) != 2:
        return HEURE_DEFAUT
    try:
        heures = int(parties[0])
        minutes = int(parties[1])
    except (ValueError, TypeError):
        return HEURE_DEFAUT
    if 0 <= heures <= 23 and 0 <= minutes <= 59:
        return f"{heures:02d}:{minutes:02d}"
    return HEURE_DEFAUT


def _jours_valides(valeur: Any) -> list[int]:
    """Retourne une liste triee et dedoublonnee de jours valides (0..6).

    Tout ce qui n'est pas un entier dans 0..6 est ignore. Liste vide = tous les
    jours (interpretation au runtime dans la boucle).
    """
    if not isinstance(valeur, (list, tuple)):
        return []
    jours: set[int] = set()
    for entree in valeur:
        if isinstance(entree, bool):
            continue
        if isinstance(entree, int) and 0 <= entree <= 6:
            jours.add(entree)
    return sorted(jours)


def valider(routine: Any) -> dict:
    """Retourne une copie propre et typee d'une routine selon le contrat.

    Force les types, valide l'heure (HH:MM sinon "08:00"), restreint les jours
    a 0..6, genere un id si absent. Ne modifie jamais le dict d'origine.
    """
    if not isinstance(routine, dict):
        routine = {}
    rid = _nettoyer_str(routine.get("id"))
    return {
        "id": rid or uuid.uuid4().hex,
        "nom": _nettoyer_str(routine.get("nom")),
        "heure": _heure_valide(routine.get("heure")),
        "jours": _jours_valides(routine.get("jours")),
        "commande": _nettoyer_str(routine.get("commande")),
        "actif": bool(routine.get("actif", True)),
    }


def _valider_liste(brut: Any) -> list[dict]:
    """Valide une liste de routines, ignore les entrees illisibles, plafonne."""
    if not isinstance(brut, list):
        return []
    valides: list[dict] = []
    for entree in brut:
        try:
            valides.append(valider(entree))
        except Exception as e:  # robustesse : une entree pourrie ne casse pas tout
            print(f"[ROUTINES] Entree ignoree ({e})")
        if len(valides) >= MAX_ROUTINES:
            break
    return valides


def charger() -> list[dict]:
    """Lit jarvis_routines.json et retourne la liste validee des routines.

    Fichier absent, illisible ou corrompu -> liste vide. Jamais d'exception.
    """
    try:
        if not ROUTINES_PATH.exists():
            return []
        with open(ROUTINES_PATH, "r", encoding="utf-8") as f:
            brut = json.load(f)
        return _valider_liste(brut)
    except Exception as e:
        print(f"[ROUTINES] Lecture impossible ({e}), liste vide utilisee")
        return []


def sauvegarder(routines: Any) -> bool:
    """Valide puis ecrit les routines sur disque (ecriture atomique .tmp + replace).

    Retourne True si l'ecriture a reussi, False sinon. Jamais d'exception.
    """
    tmp_path = ROUTINES_PATH.with_name(ROUTINES_PATH.name + ".tmp")
    try:
        propres = _valider_liste(routines)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(propres, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, ROUTINES_PATH)
        return True
    except Exception as e:
        print(f"[ROUTINES] Echec sauvegarde : {e}")
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        return False


def ajouter(routine: Any) -> list[dict]:
    """Ajoute une routine (id genere si absent) et retourne la liste a jour.

    Si l'id existe deja, la routine est remplacee (comportement upsert).
    """
    nouvelle = valider(routine)
    routines = [r for r in charger() if r["id"] != nouvelle["id"]]
    routines.append(nouvelle)
    sauvegarder(routines)
    return charger()


def supprimer(routine_id: Any) -> list[dict]:
    """Supprime la routine d'id donne et retourne la liste a jour."""
    cible = _nettoyer_str(routine_id)
    routines = [r for r in charger() if r["id"] != cible]
    sauvegarder(routines)
    return charger()


def maj(routine: Any) -> list[dict]:
    """Met a jour une routine existante (par id) et retourne la liste a jour.

    Si l'id n'existe pas, la routine est simplement ajoutee (upsert).
    """
    return ajouter(routine)


def _doit_declencher(routine: dict, maintenant: datetime) -> bool:
    """Vrai si la routine active doit se declencher a l'instant `maintenant`.

    Compare l'heure HH:MM courante et verifie que le jour de la semaine est
    dans `jours` (ou que `jours` est vide = tous les jours).
    """
    if not routine.get("actif"):
        return False
    if not routine.get("commande"):
        return False
    if routine.get("heure") != maintenant.strftime("%H:%M"):
        return False
    jours = routine.get("jours") or []
    if jours and maintenant.weekday() not in jours:
        return False
    return True


async def demarrer_planificateur(
    executer_commande: ExecuterCommande,
    intervalle_s: float = 30.0,
) -> None:
    """Boucle de fond : declenche les routines actives a leur heure et jour.

    Toutes les ~intervalle_s secondes, recharge les routines depuis le disque
    (pour prendre en compte les ajouts/suppressions a chaud) et execute celles
    dont l'heure == HH:MM courant et le jour courant est dans `jours`.

    Garde anti-double-declenchement : une routine ne peut s'executer qu'une
    seule fois par minute donnee, identifiee par (id, "YYYY-MM-DD HH:MM").
    Sans cette garde, la fenetre d'une minute serait re-matchee a chaque tour
    de boucle (toutes les 30s -> 2 declenchements).

    datetime.now() est evalue AU RUNTIME a chaque iteration. Chaque execution
    est isolee dans un try/except : une commande qui plante ne tue jamais la
    boucle. Tourne indefiniment (a annuler via la tache asyncio).
    """
    deja_declenchees: set[str] = set()
    while True:
        try:
            maintenant = datetime.now()
            cle_minute = maintenant.strftime("%Y-%m-%d %H:%M")
            for routine in charger():
                try:
                    if not _doit_declencher(routine, maintenant):
                        continue
                    cle = f"{routine['id']}|{cle_minute}"
                    if cle in deja_declenchees:
                        continue
                    deja_declenchees.add(cle)
                    await executer_commande(routine["commande"])
                except Exception as e:
                    print(f"[ROUTINES] Echec execution routine : {e}")
            # Purge la garde des minutes passees pour eviter une croissance infinie.
            deja_declenchees = {
                c for c in deja_declenchees if c.endswith(cle_minute)
            }
        except Exception as e:
            print(f"[ROUTINES] Erreur boucle planificateur : {e}")
        await asyncio.sleep(intervalle_s)


async def executer_maintenant(
    routine_id: Any,
    executer_commande: ExecuterCommande,
) -> bool:
    """Lance immediatement la routine d'id donne, sans attendre son heure.

    Retourne True si la routine existe et a ete declenchee (commande non vide),
    False sinon. Jamais d'exception : une commande qui plante renvoie False.
    """
    cible = _nettoyer_str(routine_id)
    try:
        for routine in charger():
            if routine["id"] == cible:
                if not routine["commande"]:
                    return False
                await executer_commande(routine["commande"])
                return True
        return False
    except Exception as e:
        print(f"[ROUTINES] Echec executer_maintenant : {e}")
        return False
