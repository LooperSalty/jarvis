"""File d'approbation de l'Operator : aucune action sortante (devis/email) n'est
executee sans un 'oui' explicite. Persistee, diffusee a tous les clients
(operator_pending). confirmer() delegue a un executeur fourni par main2.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from . import config

APPROVALS_PATH: Path = config._dossier_donnees() / "jarvis_operator_approvals.json"
TYPES = ("send_devis", "send_email_reply")
_broadcast: Callable[[dict], None] | None = None


def set_broadcast(cb: Callable[[dict], None] | None) -> None:
    """Injecte le callable de diffusion WS (operator_pending). None = silencieux."""
    global _broadcast
    _broadcast = cb


def _charger() -> list[dict]:
    if not APPROVALS_PATH.exists():
        return []
    try:
        data = json.loads(APPROVALS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _ecrire(items: list[dict]) -> None:
    try:
        tmp = APPROVALS_PATH.with_name(APPROVALS_PATH.name + ".tmp")
        tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, APPROVALS_PATH)
    except Exception as e:
        print(f"[OPERATOR-APPROVALS] Ecriture echouee : {e}")


def _diffuser() -> None:
    if _broadcast:
        try:
            _broadcast({"action": "operator_pending", "pending": lister()})
        except Exception:
            pass


def ajouter(action: dict) -> str:
    """Ajoute une action en attente ({type, resume, payload}) ; renvoie son id."""
    aid = uuid.uuid4().hex[:12]
    item = {
        "id": aid,
        "type": str(action.get("type", "")),
        "resume": str(action.get("resume", "")),
        "payload": action.get("payload", {}) if isinstance(action.get("payload"), dict) else {},
        "ts": datetime.now().isoformat(timespec="seconds"),
    }
    items = _charger()
    items.append(item)
    _ecrire(items)
    _diffuser()
    return aid


def lister() -> list[dict]:
    return _charger()


def get(aid: str) -> dict | None:
    return next((i for i in _charger() if i["id"] == aid), None)


def plus_recente() -> dict | None:
    items = _charger()
    return items[-1] if items else None


def rejeter(aid: str) -> bool:
    """Retire l'action `aid` ; renvoie True si retiree, False si introuvable."""
    items = _charger()
    restant = [i for i in items if i["id"] != aid]
    if len(restant) == len(items):
        return False
    _ecrire(restant)
    _diffuser()
    return True


async def confirmer(
    aid: str,
    executeurs: dict[str, Callable[[dict], Awaitable[tuple[str, bool]]]],
) -> tuple[str, bool]:
    """Execute l'action `aid` via l'executeur correspondant a son type.

    Retire l'action seulement si l'execution reussit (ok=True). Renvoie
    (message, succes). Ne leve jamais.
    """
    item = get(aid)
    if not item:
        return "Aucune action en attente avec cet identifiant.", False
    ex = executeurs.get(item["type"])
    if ex is None:
        return f"Type d'action non gere : {item['type']}.", False
    try:
        msg, ok = await ex(item["payload"])
    except Exception as e:
        return f"Echec de l'envoi : {e}", False
    if ok:
        rejeter(aid)  # retire + diffuse
    return msg, ok
