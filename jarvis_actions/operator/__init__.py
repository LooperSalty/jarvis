"""Sous-systeme Operator de Jarvis : tri mail, RDV/agenda, reunion, devis, recherche.

Facade publique :
- init(ctx)                : injecte les dependances de main2 (services Google, LLM,
                             parler, broadcast WS, user_name) et cable les broadcasts.
- async_executer(cmd)      : point d'entree voix (contrat (str|None, bool)).
- tools() / dispatch(...)   : outils de l'agent Gemini (remplis en Phase 6).
- demarrer_planificateur() : boucle de tri mail de fond (remplie en Phase 2).

Le routeur _router est PUR (texte -> (intention, params) | None) et entierement teste.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from . import approvals, config, report

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
        return f"Erreur Operator : {e}", False


async def _executer_intent(intent: str, params: dict) -> tuple[str | None, bool]:
    """Aiguillage intention -> action. Les capacites sont branchees au fil des phases."""
    if intent == "approve_confirm":
        return await _confirmer_derniere()
    if intent == "approve_reject":
        rec = approvals.plus_recente()
        if rec and approvals.rejeter(rec["id"]):
            return "Tres bien, j'annule.", True
        return "Il n'y a rien a annuler.", True
    # Intentions metier branchees en Phase 2-6.
    return f"La fonction '{intent}' n'est pas encore disponible.", True


async def _confirmer_derniere() -> tuple[str | None, bool]:
    rec = approvals.plus_recente()
    if not rec:
        return "Il n'y a rien a valider.", True
    return await approvals.confirmer(rec["id"], _executeurs_approbation())


async def confirmer_depuis_dashboard(aid: str) -> tuple[str, bool]:
    """Confirme une approbation par id (appelee par le handler dashboard)."""
    return await approvals.confirmer(aid, _executeurs_approbation())


def _executeurs_approbation() -> dict[str, Callable]:
    """Map type d'approbation -> coroutine d'execution. Rempli en Phase 2/5."""
    return {}


# ============================================================
# Outils agent Gemini (Phase 6) + scheduler (Phase 2)
# ============================================================

def tools() -> list:
    """FunctionDeclarations Gemini de l'Operator (rempli en Phase 6)."""
    return []


async def dispatch(name: str, args: dict) -> str:
    """Dispatch des outils Gemini de l'Operator (rempli en Phase 6)."""
    return ""


async def demarrer_planificateur() -> None:
    """Boucle de tri mail de fond (implementee en Phase 2)."""
    return None
