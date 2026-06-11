"""Triggers contextuels Jarvis : reagit au lancement/fermeture de processus.

Un TRIGGER associe un evenement systeme a une commande Jarvis :
- "processus" : sous-chaine du nom de process a surveiller (insensible casse,
  ex "Code.exe", "chrome", "spotify")
- "evenement" : "lancement" (le process apparait) ou "fermeture" (il disparait)
- "commande" : texte execute comme si l'utilisateur l'avait dit

La surveillance compare l'ensemble des processus actifs entre deux iterations
(diff de sets) via psutil. psutil est importe paresseusement : si la lib est
absente, disponible() renvoie False et la surveillance ne demarre simplement
pas (aucune exception qui remonterait jusqu'a main2.py).

API publique :
- TRIGGERS_PATH : Path du fichier de persistance (gitignore)
- disponible()  : True si psutil est importable
- charger() / sauvegarder(triggers)         : lecture / ecriture atomique JSON
- valider(trigger)                           : force les types, genere un id
- ajouter(trigger) / supprimer(id) / maj(trigger) : CRUD, renvoient la liste
- async demarrer_surveillance(executer_commande, intervalle_s=5.0)
    boucle de fond : diff des process actifs, declenche les triggers actifs.

Robustesse : chaque trigger est evalue dans son propre try/except, une erreur
n'interrompt jamais la boucle ni les autres triggers.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

# Type de la callable injectee par main2 (wrapper autour de traiter_reponse_ia).
ExecuterCommande = Callable[[str], Awaitable[None]]

_FICHIER = "jarvis_triggers.json"
_EVENEMENTS_VALIDES = ("lancement", "fermeture")


# ============================================================
# Localisation du fichier de persistance
# ============================================================

def _resoudre_chemin() -> Path:
    """Chemin de jarvis_triggers.json (a cote de l'exe si frozen, sinon racine repo)."""
    try:
        if getattr(sys, "frozen", False):
            # .exe PyInstaller : fichier modifiable a cote de l'executable
            return Path(sys.executable).resolve().parent / _FICHIER
        # En dev : triggers.py est dans jarvis_actions/, la racine est au-dessus
        return Path(__file__).resolve().parent.parent / _FICHIER
    except Exception:
        # Dernier recours : repertoire courant
        return Path(os.getcwd()) / _FICHIER


TRIGGERS_PATH: Path = _resoudre_chemin()


# ============================================================
# Disponibilite psutil (import paresseux)
# ============================================================

def _importer_psutil() -> Any | None:
    """Importe psutil a la demande, ou None si la lib est absente/cassee."""
    try:
        import psutil  # noqa: PLC0415 (import paresseux volontaire)

        return psutil
    except Exception as e:
        print(f"[TRIGGERS] psutil indisponible : {e}")
        return None


def disponible() -> bool:
    """True si psutil est importable (donc si la surveillance peut tourner)."""
    return _importer_psutil() is not None


# ============================================================
# Validation
# ============================================================

def valider(trigger: Any) -> dict:
    """Normalise un trigger : force les types, genere un id si absent.

    Args:
        trigger: dict (ou objet quelconque) decrivant un trigger.

    Returns:
        dict valide : {"id", "nom", "processus", "evenement", "commande", "actif"}.
        "evenement" retombe sur "lancement" si invalide.
    """
    src = trigger if isinstance(trigger, dict) else {}

    tid = src.get("id")
    if not isinstance(tid, str) or not tid.strip():
        tid = uuid.uuid4().hex[:12]

    nom = src.get("nom")
    nom = nom.strip() if isinstance(nom, str) and nom.strip() else "Trigger"

    processus = src.get("processus")
    processus = processus.strip() if isinstance(processus, str) else ""

    evenement = src.get("evenement")
    if not isinstance(evenement, str) or evenement not in _EVENEMENTS_VALIDES:
        evenement = "lancement"

    commande = src.get("commande")
    commande = commande.strip() if isinstance(commande, str) else ""

    actif = src.get("actif")
    actif = bool(actif) if isinstance(actif, bool) else True

    return {
        "id": tid,
        "nom": nom,
        "processus": processus,
        "evenement": evenement,
        "commande": commande,
        "actif": actif,
    }


# ============================================================
# Persistance (JSON, lecture / ecriture atomique)
# ============================================================

def charger() -> list[dict]:
    """Charge les triggers depuis le disque. [] si absent / corrompu."""
    try:
        if not TRIGGERS_PATH.exists():
            return []
        with open(TRIGGERS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            print(f"[TRIGGERS] Format invalide dans {TRIGGERS_PATH.name} (liste attendue)")
            return []
        return [valider(item) for item in data]
    except Exception as e:
        print(f"[TRIGGERS] Erreur lecture {TRIGGERS_PATH.name} : {e}")
        return []


def sauvegarder(triggers: Any) -> bool:
    """Ecriture atomique (.tmp puis os.replace). Valide chaque trigger avant ecriture."""
    if not isinstance(triggers, list):
        print("[TRIGGERS] sauvegarde annulee (liste attendue)")
        return False
    valides = [valider(t) for t in triggers]
    tmp = Path(str(TRIGGERS_PATH) + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(valides, f, ensure_ascii=False, indent=2)
        os.replace(tmp, TRIGGERS_PATH)
        return True
    except Exception as e:
        print(f"[TRIGGERS] Erreur sauvegarde : {e}")
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return False


# ============================================================
# CRUD (renvoient toujours la liste resultante)
# ============================================================

def ajouter(trigger: Any) -> list[dict]:
    """Ajoute un trigger (id genere si absent) et persiste. Renvoie la liste."""
    triggers = charger()
    nouveau = valider(trigger)
    triggers.append(nouveau)
    sauvegarder(triggers)
    return triggers


def supprimer(trigger_id: Any) -> list[dict]:
    """Supprime le trigger d'id donne et persiste. Renvoie la liste restante."""
    triggers = charger()
    if isinstance(trigger_id, str):
        triggers = [t for t in triggers if t.get("id") != trigger_id]
    sauvegarder(triggers)
    return triggers


def maj(trigger: Any) -> list[dict]:
    """Met a jour le trigger de meme id (ou l'ajoute si absent). Renvoie la liste."""
    nouveau = valider(trigger)
    triggers = charger()
    remplace = False
    resultat: list[dict] = []
    for t in triggers:
        if t.get("id") == nouveau["id"]:
            resultat.append(nouveau)
            remplace = True
        else:
            resultat.append(t)
    if not remplace:
        resultat.append(nouveau)
    sauvegarder(resultat)
    return resultat


# ============================================================
# Surveillance des processus
# ============================================================

def _processus_actifs(psutil: Any) -> set[str]:
    """Ensemble des noms de process actifs, en minuscules. {} si erreur."""
    actifs: set[str] = set()
    try:
        for proc in psutil.process_iter(["name"]):
            try:
                nom = proc.info.get("name")
                if isinstance(nom, str) and nom:
                    actifs.add(nom.lower())
            except Exception:
                # Process disparu pendant l'iteration, droits insuffisants, etc.
                continue
    except Exception as e:
        print(f"[TRIGGERS] process_iter erreur : {e}")
    return actifs


def _trigger_declenche(trigger: dict, apparus: set[str], disparus: set[str]) -> bool:
    """True si le trigger doit se declencher vu les process apparus / disparus.

    Le champ "processus" est une sous-chaine (insensible casse) cherchee dans
    chaque nom de process apparu (evenement "lancement") ou disparu ("fermeture").
    """
    if not trigger.get("actif", False):
        return False
    cible = trigger.get("processus") or ""
    if not isinstance(cible, str) or not cible.strip():
        return False
    cible = cible.strip().lower()
    cibles = apparus if trigger.get("evenement") == "lancement" else disparus
    return any(cible in nom for nom in cibles)


async def demarrer_surveillance(
    executer_commande: ExecuterCommande,
    intervalle_s: float = 5.0,
) -> None:
    """Boucle de fond : diff des process actifs, declenche les triggers.

    Toutes les `intervalle_s` secondes, calcule l'ensemble des process actifs et
    le compare a l'iteration precedente (diff de sets). Pour chaque trigger actif :
    - "lancement"  -> declenche si son processus apparait,
    - "fermeture"  -> declenche si son processus disparait.

    La PREMIERE iteration sert de baseline (rien n'est declenche). Chaque trigger
    est evalue dans son propre try/except : une erreur n'interrompt pas la boucle.

    Args:
        executer_commande: callable async fournie par main2 (await sur le texte).
        intervalle_s: periode d'echantillonnage en secondes (min 1.0).
    """
    psutil = _importer_psutil()
    if psutil is None:
        print("[TRIGGERS] Surveillance non demarree (psutil absent).")
        return
    if not callable(executer_commande):
        print("[TRIGGERS] Surveillance non demarree (executer_commande invalide).")
        return

    # Borne le pas pour eviter une boucle trop serree (CPU) ou une valeur absurde.
    try:
        pas = max(1.0, float(intervalle_s))
    except Exception:
        pas = 5.0

    precedents: set[str] | None = None  # None tant que la baseline n'est pas prise
    print(f"[TRIGGERS] Surveillance demarree (intervalle {pas:g}s).")

    while True:
        try:
            actuels = _processus_actifs(psutil)

            if precedents is None:
                # Premiere iteration : baseline, aucun declenchement.
                precedents = actuels
            else:
                apparus = actuels - precedents
                disparus = precedents - actuels
                precedents = actuels

                if apparus or disparus:
                    for trigger in charger():
                        try:
                            if _trigger_declenche(trigger, apparus, disparus):
                                commande = (trigger.get("commande") or "").strip()
                                if commande:
                                    print(
                                        f"[TRIGGERS] '{trigger.get('nom')}' "
                                        f"({trigger.get('evenement')}) -> {commande}"
                                    )
                                    await executer_commande(commande)
                        except Exception as e:
                            print(f"[TRIGGERS] Erreur trigger {trigger.get('id')} : {e}")
        except asyncio.CancelledError:
            # Arret propre demande par main2 (annulation de la tache).
            print("[TRIGGERS] Surveillance arretee.")
            raise
        except Exception as e:
            print(f"[TRIGGERS] Erreur boucle surveillance : {e}")

        try:
            await asyncio.sleep(pas)
        except asyncio.CancelledError:
            print("[TRIGGERS] Surveillance arretee.")
            raise
