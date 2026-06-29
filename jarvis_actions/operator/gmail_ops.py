"""Helpers de tri email de l'Operator.

Parties PURES (testees, sans reseau) : construction du prompt de classification,
parsing defensif de la reponse LLM, decision de tri a partir des regles, extraction
des entetes d'un message Gmail brut.

Parties a EFFET (service Gmail injecte) : lister/etiqueter/archiver/brouillon/envoi.
Toutes enveloppees try/except (jamais d'exception qui sort, defaut sur erreur).
"""

from __future__ import annotations

import base64
import json
from typing import Any

_PRIORITES = ("haute", "normale", "basse")
_CLASSIF_DEFAUT = {"categorie": "Autre", "priorite": "normale", "besoin_reponse": False, "raison": ""}


# ============================================================
# PUR : prompt de classification
# ============================================================

def classif_email(expediteur: str, sujet: str, extrait: str) -> str:
    """Prompt FR demandant au LLM de classer un email et de repondre par un JSON."""
    return (
        "Tu es un assistant qui trie des emails. Classe l'email suivant et reponds "
        "UNIQUEMENT par un objet JSON (aucun texte autour) avec exactement ces cles :\n"
        '{"categorie": "...", "priorite": "haute|normale|basse", "besoin_reponse": true|false, "raison": "..."}\n'
        "categorie parmi : Facture, Client, Newsletter, Spam, Personnel, Administratif, Autre.\n"
        "besoin_reponse = true si l'email attend une reponse de ma part.\n"
        "raison = une phrase COURTE expliquant POURQUOI cette categorie (ex: "
        "'expediteur EDF + mot facture dans le sujet').\n\n"
        f"Expediteur : {expediteur}\n"
        f"Sujet : {sujet}\n"
        f"Extrait : {extrait}\n"
    )


# ============================================================
# PUR : parsing defensif de la classification
# ============================================================

def _extraire_bloc_json(texte: str) -> dict | None:
    """Extrait le premier objet JSON {...} equilibre d'un texte. None si echec."""
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
                try:
                    obj = json.loads(texte[debut : i + 1])
                    return obj if isinstance(obj, dict) else None
                except Exception:
                    return None
    return None


def parser_classif(texte_llm: str) -> dict:
    """Parse defensivement la reponse LLM -> {categorie, priorite, besoin_reponse}.

    Retourne le defaut ({"Autre","normale",False}) sur toute anomalie.
    """
    obj = _extraire_bloc_json(texte_llm)
    if not obj:
        return dict(_CLASSIF_DEFAUT)
    cat = str(obj.get("categorie") or "Autre").strip() or "Autre"
    prio = str(obj.get("priorite") or "normale").strip().lower()
    if prio not in _PRIORITES:
        prio = "normale"
    besoin = bool(obj.get("besoin_reponse"))
    raison = str(obj.get("raison") or "").strip()
    return {"categorie": cat, "priorite": prio, "besoin_reponse": besoin, "raison": raison}


# ============================================================
# PUR : decision de tri
# ============================================================

def decider_action(classif: dict, regles: list[dict]) -> dict:
    """Decide l'action de tri a partir de la classification et des regles.

    regles : liste de {"si_contient": str, "label": str, "archiver": bool}.
    Match si si_contient (minuscules) est sous-chaine de la categorie OU du sujet.
    label/archiver viennent de la PREMIERE regle qui matche (sinon "" / False).
    brouillon = bool(classif["besoin_reponse"]).
    """
    classif = classif if isinstance(classif, dict) else {}
    categorie = str(classif.get("categorie", "")).lower()
    sujet = str(classif.get("sujet", "")).lower()
    label, archiver = "", False
    for regle in regles or []:
        if not isinstance(regle, dict):
            continue
        motif = str(regle.get("si_contient", "")).strip().lower()
        if motif and (motif in categorie or motif in sujet):
            label = str(regle.get("label", ""))
            archiver = bool(regle.get("archiver"))
            break
    return {"label": label, "archiver": archiver, "brouillon": bool(classif.get("besoin_reponse"))}


# ============================================================
# PUR : extraction des entetes
# ============================================================

def extraire_entetes(message: dict) -> dict:
    """Extrait {from, sujet, extrait} d'un message Gmail brut (insensible a la casse)."""
    message = message if isinstance(message, dict) else {}
    headers = (message.get("payload") or {}).get("headers") or []
    valeurs = {}
    for h in headers:
        if isinstance(h, dict):
            nom = str(h.get("name", "")).lower()
            valeurs[nom] = str(h.get("value", ""))
    return {
        "from": valeurs.get("from", ""),
        "sujet": valeurs.get("subject", ""),
        "extrait": str(message.get("snippet", "")),
    }


# ============================================================
# EFFET : appels Gmail (service injecte, defensifs)
# ============================================================

def lister_threads_non_lus(service: Any, n: int = 10) -> list[dict]:
    """Liste les messages non lus de la boite de reception (avec From/Subject/snippet)."""
    try:
        res = service.users().messages().list(
            userId="me", q="is:unread in:inbox", maxResults=n
        ).execute()
        messages = []
        for ref in res.get("messages", []):
            try:
                msg = service.users().messages().get(
                    userId="me", id=ref["id"], format="metadata",
                    metadataHeaders=["From", "Subject"],
                ).execute()
                messages.append(msg)
            except Exception:
                continue
        return messages
    except Exception as e:
        print(f"[OPERATOR-GMAIL] lister_threads_non_lus : {e}")
        return []


def assurer_label(service: Any, nom: str) -> str:
    """Renvoie l'id du label `nom`, le creant si absent. "" sur erreur."""
    try:
        labels = service.users().labels().list(userId="me").execute().get("labels", [])
        for lab in labels:
            if str(lab.get("name", "")).lower() == nom.lower():
                return lab.get("id", "")
        cree = service.users().labels().create(
            userId="me",
            body={"name": nom, "labelListVisibility": "labelShow",
                  "messageListVisibility": "show"},
        ).execute()
        return cree.get("id", "")
    except Exception as e:
        print(f"[OPERATOR-GMAIL] assurer_label : {e}")
        return ""


def appliquer_label(service: Any, msg_id: str, label_nom: str) -> bool:
    """Applique le label `label_nom` au message msg_id."""
    try:
        label_id = assurer_label(service, label_nom)
        if not label_id:
            return False
        service.users().messages().modify(
            userId="me", id=msg_id, body={"addLabelIds": [label_id]}
        ).execute()
        return True
    except Exception as e:
        print(f"[OPERATOR-GMAIL] appliquer_label : {e}")
        return False


def archiver(service: Any, msg_id: str) -> bool:
    """Archive le message (retire le label INBOX)."""
    try:
        service.users().messages().modify(
            userId="me", id=msg_id, body={"removeLabelIds": ["INBOX"]}
        ).execute()
        return True
    except Exception as e:
        print(f"[OPERATOR-GMAIL] archiver : {e}")
        return False


def _mime_simple(to: str, sujet: str, corps: str):
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = sujet
    msg.set_content(corps)
    return msg


def creer_brouillon(service: Any, thread_id: str, to: str, sujet: str, corps: str) -> str:
    """Cree un brouillon de reponse dans le thread. Renvoie l'id du brouillon ("" si echec)."""
    try:
        msg = _mime_simple(to, sujet, corps)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        body: dict[str, Any] = {"message": {"raw": raw}}
        if thread_id:
            body["message"]["threadId"] = thread_id
        draft = service.users().drafts().create(userId="me", body=body).execute()
        return draft.get("id", "")
    except Exception as e:
        print(f"[OPERATOR-GMAIL] creer_brouillon : {e}")
        return ""


def envoyer_brouillon(service: Any, draft_id: str) -> bool:
    """Envoie un brouillon existant."""
    try:
        service.users().drafts().send(userId="me", body={"id": draft_id}).execute()
        return True
    except Exception as e:
        print(f"[OPERATOR-GMAIL] envoyer_brouillon : {e}")
        return False


def envoyer_avec_pj(service: Any, to: str, sujet: str, corps: str, pdf_path: str) -> bool:
    """Envoie un email avec un PDF en piece jointe."""
    try:
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["To"] = to
        msg["Subject"] = sujet
        msg.set_content(corps)
        with open(pdf_path, "rb") as f:
            data = f.read()
        nom = pdf_path.replace("\\", "/").split("/")[-1] or "devis.pdf"
        msg.add_attachment(data, maintype="application", subtype="pdf", filename=nom)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return True
    except Exception as e:
        print(f"[OPERATOR-GMAIL] envoyer_avec_pj : {e}")
        return False
