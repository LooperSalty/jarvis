"""Synchronisation de la memoire de Jarvis vers des services externes.

Trois cibles, toutes OPTIONNELLES et degradees proprement si non configurees :
- Obsidian      : un fichier markdown par souvenir dans le vault (ObsidianBridge).
- Google Drive  : sauvegarde du fichier memoire (JSON) sur le Drive de l'utilisateur.
- Notion        : un bloc par souvenir ajoute sous une page Notion (API officielle).

Chaque fonction retourne (resume: str, ok: bool) et ne leve JAMAIS d'exception :
le dashboard affiche le resume tel quel (succes vert / echec rouge).
"""

from __future__ import annotations

import io
import json
from typing import Any

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

try:
    from jarvis_actions.obsidian_memory import ObsidianBridge
except Exception:  # pragma: no cover
    ObsidianBridge = None


def _items(memoire: dict) -> list[tuple[str, str, str]]:
    """Normalise la memoire en liste (cle, valeur, timestamp)."""
    out: list[tuple[str, str, str]] = []
    for cle, entree in (memoire or {}).items():
        if isinstance(entree, dict):
            out.append((str(cle), str(entree.get("valeur", "")), str(entree.get("timestamp", ""))))
        else:
            out.append((str(cle), str(entree), ""))
    return out


# ==========================================
# OBSIDIAN
# ==========================================
def sync_obsidian(memoire: dict, vault_path: str) -> tuple[str, bool]:
    """Ecrit un fichier markdown par souvenir dans {vault}/Jarvis/Memoire/."""
    if ObsidianBridge is None:
        return "Module Obsidian indisponible.", False
    if not vault_path:
        return "Aucun vault Obsidian configure (cle OBSIDIAN_VAULT).", False
    try:
        bridge = ObsidianBridge(vault_path)
    except FileNotFoundError:
        return f"Vault Obsidian introuvable : {vault_path}", False
    except Exception as e:
        return f"Obsidian : {str(e)[:160]}", False
    n = 0
    for cle, valeur, ts in _items(memoire):
        if not valeur:
            continue
        try:
            bridge.save_memory(cle, valeur, ts or None)
            n += 1
        except Exception:
            continue
    return f"{n} souvenir(s) synchronise(s) vers Obsidian.", True


# ==========================================
# GOOGLE DRIVE
# ==========================================
DRIVE_FILENAME = "jarvis_memoire.json"


def backup_drive(memoire: dict, drive_service: Any) -> tuple[str, bool]:
    """Sauvegarde la memoire (JSON) sur le Drive : cree ou met a jour le fichier."""
    if drive_service is None:
        return "Google Drive non connecte (credentials.json + autorisation requis).", False
    try:
        from googleapiclient.http import MediaIoBaseUpload
    except Exception:
        return "Bibliotheque Google API indisponible.", False
    try:
        contenu = json.dumps(memoire or {}, ensure_ascii=False, indent=2).encode("utf-8")
        media = MediaIoBaseUpload(io.BytesIO(contenu), mimetype="application/json", resumable=False)
        # Met a jour le fichier existant du meme nom s'il y en a un (sinon cree).
        recherche = drive_service.files().list(
            q=f"name = '{DRIVE_FILENAME}' and trashed = false",
            spaces="drive", fields="files(id, name)", pageSize=1,
        ).execute()
        fichiers = recherche.get("files", [])
        if fichiers:
            drive_service.files().update(fileId=fichiers[0]["id"], media_body=media).execute()
            return f"Memoire mise a jour sur Google Drive ({DRIVE_FILENAME}).", True
        drive_service.files().create(
            body={"name": DRIVE_FILENAME}, media_body=media, fields="id",
        ).execute()
        return f"Memoire sauvegardee sur Google Drive ({DRIVE_FILENAME}).", True
    except Exception as e:
        return f"Echec Google Drive : {str(e)[:200]}", False


# ==========================================
# NOTION
# ==========================================
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def sync_notion(memoire: dict, token: str, page_id: str) -> tuple[str, bool]:
    """Ajoute un bloc (puce) par souvenir sous une page Notion partagee avec
    l'integration. NOTION_PAGE_ID = l'id de la page (32 hex, avec ou sans tirets)."""
    if requests is None:
        return "Module requests indisponible.", False
    if not token or not page_id:
        return "Notion non configure (cles NOTION_TOKEN + NOTION_PAGE_ID requises).", False
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    children: list[dict] = []
    for cle, valeur, ts in _items(memoire):
        if not valeur:
            continue
        texte = f"{cle} : {valeur}" + (f"  ({ts})" if ts else "")
        children.append({
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": texte[:1900]}}]
            },
        })
    if not children:
        return "Aucun souvenir a synchroniser.", True
    ajoutes = 0
    try:
        # Notion limite a 100 blocs enfants par requete : on pagine.
        for i in range(0, len(children), 100):
            lot = children[i : i + 100]
            r = requests.patch(
                f"{NOTION_API}/blocks/{page_id}/children",
                headers=headers, json={"children": lot}, timeout=15,
            )
            if r.status_code >= 400:
                return f"Notion a refuse la requete ({r.status_code}) : {r.text[:160]}", False
            ajoutes += len(lot)
        return f"{ajoutes} souvenir(s) ajoute(s) a la page Notion.", True
    except Exception as e:
        return f"Echec Notion : {str(e)[:200]}", False
