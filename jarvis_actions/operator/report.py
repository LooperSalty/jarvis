"""Journal d'activite de l'Operator : chaque action autonome (mail trie, RDV cree,
devis envoye...) est journalisee (persistee), diffusee aux clients (operator_activity),
et resumable en langage naturel ('voici ce que j'ai fait avec ta boite mail').
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import config

REPORT_PATH: Path = config._dossier_donnees() / "jarvis_operator_report.json"
_MAX = 500
_broadcast: Callable[[dict], None] | None = None


def set_broadcast(cb: Callable[[dict], None] | None) -> None:
    """Injecte le callable de diffusion WS (operator_activity). None = silencieux."""
    global _broadcast
    _broadcast = cb


def _charger() -> list[dict]:
    if not REPORT_PATH.exists():
        return []
    try:
        data = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _ecrire(items: list[dict]) -> None:
    try:
        tmp = REPORT_PATH.with_name(REPORT_PATH.name + ".tmp")
        tmp.write_text(json.dumps(items[-_MAX:], indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, REPORT_PATH)
    except Exception as e:
        print(f"[OPERATOR-REPORT] Ecriture echouee : {e}")


def journaliser(evenement: dict) -> dict:
    """Ajoute un evenement horodate au journal, le persiste et le diffuse."""
    ev = {
        "type": str(evenement.get("type", "info")),
        "detail": str(evenement.get("detail", "")),
        "ts": datetime.now().isoformat(timespec="seconds"),
    }
    items = _charger()
    items.append(ev)
    _ecrire(items)
    if _broadcast:
        try:
            _broadcast({"action": "operator_activity", "evenement": ev})
        except Exception:
            pass
    return ev


def etape(donnees: dict) -> dict:
    """Evenement RICHE d'activite en direct (operator_step) : c'est ce qui alimente
    le flux visuel 'comme une video' (categorie + titre + detail + RAISON/pourquoi
    + statut). Appende aussi une entree compacte au journal (pour le resume a la
    demande / dash_operator_init). Diffuse uniquement aux clients loopback.

    `categorie` : mail / rdv / devis / recherche / reunion / info.
    `statut`    : ok / info / attente / erreur (pilote la couleur de la carte).
    """
    ev = {
        "categorie": str(donnees.get("categorie", "info")),
        "titre": str(donnees.get("titre", "")),
        "detail": str(donnees.get("detail", "")),
        "raison": str(donnees.get("raison", "")),
        "statut": str(donnees.get("statut", "ok")),
        "ts": datetime.now().isoformat(timespec="seconds"),
    }
    items = _charger()
    items.append({"type": ev["categorie"], "detail": ev["titre"] or ev["detail"], "ts": ev["ts"]})
    _ecrire(items)
    if _broadcast:
        try:
            _broadcast({"action": "operator_step", "etape": ev})
        except Exception:
            pass
    return ev


def derniers(n: int = 50) -> list[dict]:
    """Les n evenements les plus recents (ordre chronologique)."""
    return _charger()[-n:]


def resume_textuel(depuis: str | None = None) -> str:
    """Resume en langage naturel : compte par type ('Voici ce que j'ai fait : ...').

    `depuis` : timestamp ISO ; ne compte que les evenements >= a cette valeur.
    """
    items = _charger()
    if depuis:
        items = [e for e in items if e.get("ts", "") >= depuis]
    if not items:
        return "Rien a signaler pour le moment."
    cnt = Counter(e["type"] for e in items)
    morceaux = [f"{n} {t.replace('_', ' ')}" for t, n in cnt.most_common()]
    return "Voici ce que j'ai fait : " + ", ".join(morceaux) + "."
