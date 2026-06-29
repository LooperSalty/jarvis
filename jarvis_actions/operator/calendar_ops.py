"""Agenda / RDV de l'Operator : parties PURES (parsing JSON LLM, construction du
corps d'evenement Google Calendar, calcul de creneaux libres) + appels Calendar
ISOLES (service injecte, jamais d'import reseau ici).

Les fonctions publiques de parsing/calcul sont DEFENSIVES : elles ne levent jamais
et retombent sur un defaut documente (None ou liste/dict vide). Les fonctions a
effet enveloppent l'appel Google dans un try/except et degradent proprement.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

_TZ = "Europe/Paris"


# ============================================================
# Helpers internes (purs)
# ============================================================

def _extraire_bloc(texte: Any) -> str | None:
    """Retourne le premier bloc accolades equilibre {...} du texte, sinon None."""
    if not isinstance(texte, str):
        return None
    debut = texte.find("{")
    if debut < 0:
        return None
    profondeur = 0
    for i in range(debut, len(texte)):
        c = texte[i]
        if c == "{":
            profondeur += 1
        elif c == "}":
            profondeur -= 1
            if profondeur == 0:
                return texte[debut:i + 1]
    return None


def _parse_iso(valeur: Any) -> datetime | None:
    """datetime.fromisoformat tolerant : None si non parsable."""
    if not isinstance(valeur, str) or not valeur:
        return None
    try:
        return datetime.fromisoformat(valeur)
    except ValueError:
        return None


def _naive(dt: datetime) -> datetime:
    """Retire l'info de fuseau pour comparer des heures murales homogenes."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _fin_par_defaut(debut_iso: str) -> str:
    """debut_iso + 1h (isoformat). Retombe sur debut_iso si non parsable."""
    dt = _parse_iso(debut_iso)
    if dt is None:
        return debut_iso
    return (dt + timedelta(hours=1)).isoformat()


def _intervalle(ev: Any) -> tuple[datetime, datetime] | None:
    """Normalise un event occupe en (debut, fin) naifs.

    Accepte deux formes : {debut, fin} iso, ou {start: {dateTime}, end: {dateTime}}.
    Renvoie None si la forme est invalide ou non parsable.
    """
    if not isinstance(ev, dict):
        return None
    if ev.get("debut") and ev.get("fin"):
        d, f = _parse_iso(ev.get("debut")), _parse_iso(ev.get("fin"))
    else:
        s, e = ev.get("start"), ev.get("end")
        if not (isinstance(s, dict) and isinstance(e, dict)):
            return None
        d, f = _parse_iso(s.get("dateTime")), _parse_iso(e.get("dateTime"))
    if d is None or f is None:
        return None
    return (_naive(d), _naive(f))


# ============================================================
# Fonctions PURES
# ============================================================

def parser_rdv_json(texte_llm: str) -> dict | None:
    """Extrait le premier bloc {...} du texte LLM vers un dict normalise.

    Cles renvoyees : titre, debut_iso, fin_iso, lieu, invites (liste de str).
    DEFENSIF : renvoie None si aucun bloc, JSON invalide ou non-objet.
    """
    bloc = _extraire_bloc(texte_llm)
    if bloc is None:
        return None
    try:
        data = json.loads(bloc)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    brut_invites = data.get("invites")
    invites = [str(x) for x in brut_invites] if isinstance(brut_invites, list) else []
    return {
        "titre": str(data.get("titre", "") or ""),
        "debut_iso": str(data.get("debut_iso", "") or ""),
        "fin_iso": str(data.get("fin_iso", "") or ""),
        "lieu": str(data.get("lieu", "") or ""),
        "invites": invites,
    }


def construire_event(payload: dict) -> dict:
    """Construit le corps d'evenement Google Calendar depuis un payload.

    payload : titre, debut_iso (requis logiquement), et optionnellement fin_iso,
    lieu, invites. Renvoie summary + start/end (dateTime + timeZone Europe/Paris),
    ajoute location si lieu non vide et attendees si invites non vide. Si fin_iso
    est vide/absent : debut_iso + 1h. PUR et defensif (ne leve jamais).
    """
    p = payload if isinstance(payload, dict) else {}
    titre = str(p.get("titre", "") or "")
    debut_iso = str(p.get("debut_iso", "") or "")
    fin_iso = str(p.get("fin_iso", "") or "").strip()
    lieu = str(p.get("lieu", "") or "").strip()
    brut_invites = p.get("invites")
    invites = [str(x) for x in brut_invites if x] if isinstance(brut_invites, list) else []

    if not fin_iso:
        fin_iso = _fin_par_defaut(debut_iso)

    event: dict[str, Any] = {
        "summary": titre,
        "start": {"dateTime": debut_iso, "timeZone": _TZ},
        "end": {"dateTime": fin_iso, "timeZone": _TZ},
    }
    if lieu:
        event["location"] = lieu
    if invites:
        event["attendees"] = [{"email": e} for e in invites]
    return event


def creneaux_libres(events: list[dict], plage: dict, duree_min: int) -> list[dict]:
    """Calcule les trous libres (>= duree_min minutes) dans une plage horaire.

    plage : {date: YYYY-MM-DD, debut: HH:MM, fin: HH:MM}. events : intervalles
    occupes ({debut, fin} iso ou {start/end: {dateTime}}). Renvoie une liste de
    {debut, fin} (isoformat sur la date donnee). PUR et defensif (liste vide si
    plage invalide).
    """
    pl = plage if isinstance(plage, dict) else {}
    date = str(pl.get("date", "") or "")
    h_debut = str(pl.get("debut", "") or "")
    h_fin = str(pl.get("fin", "") or "")
    plage_debut = _parse_iso(f"{date}T{h_debut}")
    plage_fin = _parse_iso(f"{date}T{h_fin}")
    if plage_debut is None or plage_fin is None or plage_fin <= plage_debut:
        return []
    try:
        seuil = timedelta(minutes=max(0, int(duree_min)))
    except (TypeError, ValueError):
        seuil = timedelta(minutes=0)

    # Intervalles occupes, clippes a la plage.
    occupes: list[tuple[datetime, datetime]] = []
    for ev in events or []:
        iv = _intervalle(ev)
        if iv is None:
            continue
        s = max(iv[0], plage_debut)
        e = min(iv[1], plage_fin)
        if e > s:
            occupes.append((s, e))
    occupes.sort()

    # Balayage : trous entre la fin du dernier occupe et le debut du suivant.
    creneaux: list[dict] = []
    curseur = plage_debut
    for s, e in occupes:
        if s > curseur and (s - curseur) >= seuil:
            creneaux.append({"debut": curseur.isoformat(), "fin": s.isoformat()})
        curseur = max(curseur, e)
    if plage_fin > curseur and (plage_fin - curseur) >= seuil:
        creneaux.append({"debut": curseur.isoformat(), "fin": plage_fin.isoformat()})
    return creneaux


# ============================================================
# Fonctions a EFFET (service Google Calendar injecte)
# ============================================================

def lister(service: Any, debut_iso: str, fin_iso: str) -> list[dict]:
    """Liste les evenements du calendrier primary dans [debut_iso, fin_iso].

    Renvoie les items (liste de dicts) ; liste vide en cas d'erreur.
    """
    try:
        res = service.events().list(
            calendarId="primary",
            timeMin=debut_iso,
            timeMax=fin_iso,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        items = res.get("items", []) if isinstance(res, dict) else []
        return items if isinstance(items, list) else []
    except Exception as e:
        print(f"[OPERATOR-CALENDAR] Listing echoue : {e}")
        return []


def creer(service: Any, body: dict) -> dict:
    """Cree un evenement (events().insert) ; renvoie l'event cree, {} si erreur."""
    try:
        res = service.events().insert(calendarId="primary", body=body).execute()
        return res if isinstance(res, dict) else {}
    except Exception as e:
        print(f"[OPERATOR-CALENDAR] Creation echouee : {e}")
        return {}


def supprimer(service: Any, event_id: str) -> bool:
    """Supprime l'evenement event_id (events().delete) ; True si reussi, False sinon."""
    try:
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        return True
    except Exception as e:
        print(f"[OPERATOR-CALENDAR] Suppression echouee : {e}")
        return False
