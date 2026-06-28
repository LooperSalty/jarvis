"""Sous-systeme Operator de Jarvis : tri mail, RDV/agenda, reunion, devis, recherche.

Facade publique :
- init(ctx)                : injecte les dependances de main2 (services Google, LLM,
                             parler, broadcast WS, show_content, user_name).
- async_executer(cmd)      : point d'entree voix (contrat (str|None, bool)).
- tools() / dispatch(...)   : outils de l'agent Gemini (operator_*).
- demarrer_planificateur() : boucle de tri mail de fond.

Le routeur _router est PUR (texte -> (intention, params) | None) et entierement teste.
Toute la logique d'effet (Google, LLM, PDF) passe par les callables injectes dans _CTX
et reste defensive : aucune intention ne fait crasher la boucle vocale.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any, Callable

from . import (
    approvals,
    calendar_ops,
    config,
    devis,
    devis_pdf,
    gmail_ops,
    meeting,
    report,
    research,
)

_CTX: dict[str, Any] = {}


def init(ctx: dict[str, Any]) -> None:
    """Injecte les dependances de main2 et cable report/approvals sur le broadcast WS."""
    global _CTX
    _CTX = dict(ctx or {})
    bc = _CTX.get("broadcast_ws")
    if bc:
        report.set_broadcast(bc)
        approvals.set_broadcast(bc)


# ============================================================
# Routeur vocal PUR : texte -> (intention, params) | None
# ============================================================

_REGLES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(trie|tri)\b.*\bmails?\b"), "email_triage"),
    (re.compile(r"\boccupe[- ]toi\b.*\bmails?\b"), "email_triage"),
    (re.compile(r"\b(arr[eê]te d'?[eé]couter|stop r[eé]union|fini la r[eé]union)\b"), "meeting_stop"),
    (re.compile(r"\b[eé]coute(r)?\b.*\b(r[eé]union|conversation)\b"), "meeting_start"),
    (re.compile(r"\b(fais|pr[eé]pare|cr[eé]e|g[eé]n[eé]re)\b.*\bdevis\b"), "devis_new"),
    (re.compile(r"\b(prends?|ajoute|cr[eé]e|planifie)\b.*\b(rdv|rendez[- ]vous|agenda)\b"), "rdv_new"),
    (re.compile(r"\brecherche approfondie\b"), "research"),
    (re.compile(r"\b(fais|lance)\b.*\brecherche(s)?\b"), "research"),
    (re.compile(r"\brecherche(r)?\b.*\b(sur internet|en ligne)\b"), "research"),
]
_CONFIRM = re.compile(r"^\s*(oui|ok|d'?accord|valide|envoie|envoyer|confirme)\b", re.I)
_REJECT = re.compile(r"^\s*(non|annule|annuler|refuse|rejette|laisse tomber)\b", re.I)


def _router(texte: str, a_des_approbations: bool) -> tuple[str, dict] | None:
    """Texte -> (intention, params) | None. PUR, sans effet de bord.

    Les confirmations 'oui'/'non' ne sont capturees QUE si une approbation est en
    attente (sinon on ne hijacke pas la conversation normale).
    """
    t = (texte or "").strip().lower()
    if not t:
        return None
    if a_des_approbations:
        if _CONFIRM.search(t):
            return ("approve_confirm", {})
        if _REJECT.search(t):
            return ("approve_reject", {})
    for pat, intent in _REGLES:
        if pat.search(t):
            return (intent, {"texte": texte})
    return None


# ============================================================
# Point d'entree voix
# ============================================================

async def async_executer(cmd: str) -> tuple[str | None, bool]:
    """Point d'entree voix. Renvoie (None, False) si non gere (la chaine continue)."""
    a_pending = bool(approvals.lister())
    routed = _router(cmd, a_pending)
    if routed is None:
        return None, False
    intent, params = routed
    try:
        return await _executer_intent(intent, params)
    except Exception as e:
        print(f"[OPERATOR] intent {intent} : {e}")
        return f"Une erreur est survenue cote Operator : {e}", False


async def _executer_intent(intent: str, params: dict) -> tuple[str | None, bool]:
    """Aiguillage intention -> action."""
    if intent == "approve_confirm":
        return await _confirmer_derniere()
    if intent == "approve_reject":
        rec = approvals.plus_recente()
        if rec and approvals.rejeter(rec["id"]):
            return "Tres bien, j'annule.", True
        return "Il n'y a rien a annuler.", True
    if intent == "email_triage":
        return await _trier_mails()
    if intent == "rdv_new":
        return await _creer_rdv(params)
    if intent == "meeting_start":
        return await _meeting_start()
    if intent == "meeting_stop":
        return await _meeting_stop()
    if intent == "devis_new":
        return await _creer_devis(params)
    if intent == "research":
        return await _rechercher(params)
    return f"La fonction '{intent}' n'est pas encore disponible.", True


# ============================================================
# Approbations
# ============================================================

async def _confirmer_derniere() -> tuple[str | None, bool]:
    rec = approvals.plus_recente()
    if not rec:
        return "Il n'y a rien a valider.", True
    return await approvals.confirmer(rec["id"], _executeurs_approbation())


async def confirmer_depuis_dashboard(aid: str) -> tuple[str, bool]:
    """Confirme une approbation par id (appelee par le handler dashboard)."""
    return await approvals.confirmer(aid, _executeurs_approbation())


def _executeurs_approbation() -> dict[str, Callable]:
    return {
        "send_email_reply": _executer_envoi_reponse,
        "send_devis": _executer_envoi_devis,
    }


async def _executer_envoi_reponse(payload: dict) -> tuple[str, bool]:
    get_svc = _CTX.get("get_gmail_service")
    draft_id = payload.get("draft_id")
    if not get_svc or not draft_id:
        return "Impossible d'envoyer la reponse (brouillon ou Gmail manquant).", False
    service = await asyncio.to_thread(get_svc)
    ok = await asyncio.to_thread(gmail_ops.envoyer_brouillon, service, draft_id)
    if ok:
        report.journaliser({"type": "email_repondu", "detail": payload.get("sujet", "")})
        return "Reponse envoyee.", True
    return "Echec de l'envoi de la reponse.", False


async def _executer_envoi_devis(payload: dict) -> tuple[str, bool]:
    get_svc = _CTX.get("get_gmail_service")
    to = (payload.get("client_email") or "").strip()
    pdf_path = payload.get("pdf_path")
    numero = payload.get("numero", "")
    if not get_svc:
        return "Gmail n'est pas configure, devis non envoye.", False
    if not to:
        return "L'email du client est manquant : complete-le dans le dashboard avant l'envoi.", False
    service = await asyncio.to_thread(get_svc)
    corps = (f"Bonjour,\n\nVeuillez trouver ci-joint notre devis {numero}.\n\n"
             "Restant a votre disposition,\nCordialement.")
    if pdf_path:
        ok = await asyncio.to_thread(
            gmail_ops.envoyer_avec_pj, service, to, f"Devis {numero}", corps, pdf_path
        )
    else:
        draft = await asyncio.to_thread(
            gmail_ops.creer_brouillon, service, "", to, f"Devis {numero}", corps
        )
        ok = bool(draft) and await asyncio.to_thread(gmail_ops.envoyer_brouillon, service, draft)
    if ok:
        report.journaliser({"type": "devis_envoye", "detail": f"{numero} -> {to}"})
        return f"Devis {numero} envoye a {to}.", True
    return "Echec de l'envoi du devis.", False


# ============================================================
# Email : tri de fond
# ============================================================

_AUTO_LABEL = ("tri_auto_reponses_validees", "tri_auto_seul", "autonomie_totale")
_AUTO_REPLY = ("tri_auto_reponses_validees", "tout_en_validation", "autonomie_totale")


def _prompt_reponse(ent: dict) -> str:
    return (
        "Redige une reponse FR courte, polie et professionnelle a cet email. "
        "Reponds uniquement par le corps du message (pas d'objet, pas de signature).\n\n"
        f"De : {ent.get('from', '')}\nSujet : {ent.get('sujet', '')}\n"
        f"Extrait : {ent.get('extrait', '')}\n"
    )


async def _trier_mails() -> tuple[str, bool]:
    get_svc = _CTX.get("get_gmail_service")
    demander_json = _CTX.get("demander_json")
    demander_ia = _CTX.get("demander_ia")
    if not get_svc or not demander_json:
        return "Le tri des mails n'est pas disponible (Gmail ou IA non configures).", False
    cfg = config.charger()
    autonomie = cfg["autonomie_email"]
    regles = cfg["regles_tri"]
    depuis = datetime.now().isoformat(timespec="seconds")
    try:
        service = await asyncio.to_thread(get_svc)
    except Exception as e:
        return f"Impossible de me connecter a Gmail : {e}", False
    messages = await asyncio.to_thread(gmail_ops.lister_threads_non_lus, service, 10)
    if not messages:
        return "Aucun mail non lu a trier.", True
    n = 0
    for msg in messages:
        ent = gmail_ops.extraire_entetes(msg)
        try:
            rep = await demander_json(gmail_ops.classif_email(ent["from"], ent["sujet"], ent["extrait"]))
        except Exception:
            continue
        classif = {**gmail_ops.parser_classif(rep), "sujet": ent["sujet"]}
        action = gmail_ops.decider_action(classif, regles)
        msg_id = msg.get("id", "")
        if autonomie in _AUTO_LABEL:
            if action["label"]:
                if await asyncio.to_thread(gmail_ops.appliquer_label, service, msg_id, action["label"]):
                    report.journaliser({"type": "email_etiquete", "detail": f"{ent['sujet']} -> {action['label']}"})
            if action["archiver"]:
                if await asyncio.to_thread(gmail_ops.archiver, service, msg_id):
                    report.journaliser({"type": "email_archive", "detail": ent["sujet"]})
        if action["brouillon"] and autonomie in _AUTO_REPLY and demander_ia:
            try:
                corps = await demander_ia(_prompt_reponse(ent))
            except Exception:
                corps = ""
            if corps:
                draft_id = await asyncio.to_thread(
                    gmail_ops.creer_brouillon, service, msg.get("threadId", ""),
                    ent["from"], f"Re: {ent['sujet']}", corps,
                )
                if autonomie == "autonomie_totale" and draft_id:
                    if await asyncio.to_thread(gmail_ops.envoyer_brouillon, service, draft_id):
                        report.journaliser({"type": "email_repondu", "detail": ent["sujet"]})
                elif draft_id:
                    approvals.ajouter({
                        "type": "send_email_reply",
                        "resume": f"Reponse a {ent['from']} : {ent['sujet']}",
                        "payload": {"draft_id": draft_id, "sujet": ent["sujet"]},
                    })
        n += 1
    return report.resume_textuel(depuis=depuis), True


async def demarrer_planificateur() -> None:
    """Boucle de tri mail de fond (intervalle configurable, defaut 15 min)."""
    while True:
        try:
            intervalle = max(1, int(config.charger().get("triage_intervalle_min", 15)))
        except Exception:
            intervalle = 15
        await asyncio.sleep(intervalle * 60)
        if _CTX.get("get_gmail_service") and _CTX.get("demander_json"):
            try:
                await _trier_mails()
            except Exception as e:
                print(f"[OPERATOR] tri auto echoue : {e}")


# ============================================================
# RDV / agenda
# ============================================================

def _prompt_rdv(texte: str) -> str:
    aujourdhui = datetime.now().strftime("%Y-%m-%d (%A)")
    return (
        f"Nous sommes le {aujourdhui}. Extrais le rendez-vous de la phrase suivante "
        "et reponds UNIQUEMENT par un objet JSON avec les cles : titre, debut_iso "
        "(ISO 8601 local, ex 2026-07-01T14:00:00), fin_iso (vide si inconnu), lieu, "
        "invites (liste d'emails, vide si aucun).\n\n"
        f"Phrase : {texte}"
    )


async def _creer_rdv(params: dict) -> tuple[str, bool]:
    get_svc = _CTX.get("get_calendar_service")
    demander_json = _CTX.get("demander_json")
    if not get_svc or not demander_json:
        return "La gestion de l'agenda n'est pas disponible (Calendar ou IA non configures).", False
    try:
        rep = await demander_json(_prompt_rdv(params.get("texte", "")))
    except Exception as e:
        return f"Je n'ai pas pu analyser le rendez-vous : {e}", False
    payload = calendar_ops.parser_rdv_json(rep)
    if not payload or not payload.get("debut_iso"):
        return "Je n'ai pas compris la date du rendez-vous. Peux-tu reformuler ?", False
    body = calendar_ops.construire_event(payload)
    service = await asyncio.to_thread(get_svc)
    ev = await asyncio.to_thread(calendar_ops.creer, service, body)
    if ev:
        titre = payload.get("titre", "rendez-vous")
        debut = payload.get("debut_iso", "")
        report.journaliser({"type": "rdv_cree", "detail": f"{titre} {debut}"})
        return f"C'est note : {titre} le {debut}.", True
    return "Je n'ai pas pu creer le rendez-vous dans l'agenda.", False


# ============================================================
# Reunion
# ============================================================

async def _meeting_start() -> tuple[str, bool]:
    if meeting.etat().get("actif"):
        return "J'ecoute deja la reunion.", True
    ok = meeting.demarrer(_CTX.get("broadcast_ws"))
    if ok:
        report.journaliser({"type": "reunion_demarree", "detail": ""})
        return "J'ecoute la reunion. Dis 'arrete d'ecouter' quand c'est fini.", True
    return "Je ne peux pas ecouter : micro ou reconnaissance vocale indisponible.", False


async def _meeting_stop() -> tuple[str, bool]:
    transcript = meeting.arreter()
    if not transcript.strip():
        return "Reunion terminee, mais je n'ai rien capte.", True
    demander_ia = _CTX.get("demander_ia")
    resume = await meeting.resumer(transcript, demander_ia) if demander_ia else ""
    report.journaliser({"type": "reunion_terminee", "detail": (resume[:200] if resume else "transcript capte")})
    base = "Reunion terminee. "
    if resume:
        base += resume + " "
    base += "Dis 'fais un devis' pour generer un devis a partir de cette reunion."
    return base, True


# ============================================================
# Devis
# ============================================================

async def _creer_devis(params: dict) -> tuple[str, bool]:
    demander_json = _CTX.get("demander_json")
    if not demander_json:
        return "La generation de devis n'est pas disponible (IA non configuree).", False
    cfg = config.charger()
    transcript = meeting.etat().get("transcript", "").strip()
    source = transcript or params.get("texte", "")
    if not source:
        return ("Je n'ai pas d'elements pour le devis. Dicte-moi les prestations "
                "ou lance d'abord une reunion."), False
    d = await devis.from_transcript(source, demander_json, cfg)
    config.incrementer_compteur_devis()  # reserve le numero
    pdf_path = devis_pdf.rendre(d)
    client = d.get("client") or {}
    client_email = (client.get("email") or "").strip()
    numero = d.get("numero", "")
    ttc = (d.get("totaux") or {}).get("total_ttc", 0)
    resume = f"Devis {numero} pour {client.get('nom') or 'client'} - {ttc} EUR TTC"
    approvals.ajouter({
        "type": "send_devis",
        "resume": resume,
        "payload": {"client_email": client_email, "pdf_path": pdf_path,
                    "numero": numero, "devis": d},
    })
    report.journaliser({"type": "devis_prepare", "detail": resume})
    avert = "" if client_email else " (email du client manquant : complete-le dans le dashboard)"
    avert_pdf = "" if pdf_path else " Le PDF n'a pas pu etre genere (fpdf2 absent)."
    return f"J'ai prepare le {resume}. Dis 'oui' pour l'envoyer.{avert}{avert_pdf}", True


# ============================================================
# Recherche internet
# ============================================================

_NETTOYER_RE = re.compile(
    r"^\s*(fais|lance|fais-moi|peux-tu faire)?\s*(une\s+)?recherche(s)?"
    r"(\s+approfondie)?(\s+(sur|de|a propos de|concernant|pour|en ligne|sur internet))?\s*",
    re.I,
)


def _nettoyer_requete(texte: str) -> str:
    q = _NETTOYER_RE.sub("", texte or "").strip()
    return q or (texte or "").strip()


async def _rechercher(params: dict) -> tuple[str, bool]:
    demander_ia = _CTX.get("demander_ia")
    if not demander_ia:
        return "La recherche n'est pas disponible (IA non configuree).", False
    query = _nettoyer_requete(params.get("texte", ""))
    if not query:
        return "Quelle recherche veux-tu que je fasse ?", True
    res = await research.rechercher(query, demander_ia)
    resume = (res.get("resume") or "").strip() or "Je n'ai rien trouve de concluant."
    sources = res.get("sources", [])
    report.journaliser({"type": "recherche", "detail": query[:120]})
    show = _CTX.get("show_content")
    if show and sources:
        contenu = resume + "\n\nSources :\n" + "\n".join(
            f"- {s.get('titre', '')} : {s.get('lien', '')}" for s in sources
        )
        try:
            show("Recherche", contenu, "info")
        except Exception:
            pass
    return resume, True


# ============================================================
# Outils agent Gemini (operator_*)
# ============================================================

def tools() -> list:
    """FunctionDeclarations Gemini de l'Operator (lazy import genai ; [] si absent)."""
    try:
        from google.genai import types
    except Exception:
        return []
    S, T = types.Schema, types.Type
    return [
        types.FunctionDeclaration(
            name="operator_triage_mail",
            description="Trie la boite mail (classe, etiquette, archive) et renvoie un compte-rendu. Ne fait AUCUN envoi sortant.",
            parameters=S(type=T.OBJECT, properties={}),
        ),
        types.FunctionDeclaration(
            name="operator_creer_rdv",
            description="Cree un rendez-vous dans l'agenda Google a partir d'une description en langage naturel (ex: 'dentiste mardi 14h').",
            parameters=S(type=T.OBJECT, properties={
                "description": S(type=T.STRING, description="Description du RDV avec date/heure/lieu"),
            }, required=["description"]),
        ),
        types.FunctionDeclaration(
            name="operator_recherche",
            description="Fait une recherche internet et renvoie une synthese factuelle.",
            parameters=S(type=T.OBJECT, properties={
                "requete": S(type=T.STRING, description="La requete de recherche"),
            }, required=["requete"]),
        ),
        types.FunctionDeclaration(
            name="operator_faire_devis",
            description="Prepare un devis (PDF) a partir d'une description ou de la derniere reunion ; il sera soumis a validation avant envoi.",
            parameters=S(type=T.OBJECT, properties={
                "description": S(type=T.STRING, description="Elements du devis : prestations, quantites, prix, client"),
            }, required=[]),
        ),
    ]


async def dispatch(name: str, args: dict) -> str:
    """Dispatch des outils Gemini operator_* -> intentions. Renvoie un texte pour l'IA."""
    args = args or {}
    try:
        if name == "operator_triage_mail":
            msg, _ = await _trier_mails()
            return msg
        if name == "operator_creer_rdv":
            msg, _ = await _creer_rdv({"texte": args.get("description", "")})
            return msg
        if name == "operator_recherche":
            msg, _ = await _rechercher({"texte": args.get("requete", "")})
            return msg
        if name == "operator_faire_devis":
            msg, _ = await _creer_devis({"texte": args.get("description", "")})
            return msg
    except Exception as e:
        return f"Erreur outil {name} : {e}"
    return f"Outil operator inconnu : {name}"
