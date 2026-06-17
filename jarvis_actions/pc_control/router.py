"""Routeur d'intention PUR : texte -> Intention | None.

AUCUN import OS, AUCUN effet de bord -> 100% testable en CI Linux. C'est le filet
anti-regression de tout le controle PC.

Deux etages, evalues DANS L'ORDRE (l'ordre = la priorite) :
1. `_REGLES` : predicats sans capture -> Intention(domaine, action).
2. `_EXTRACTEURS` : fonctions a capture (volume %, cible a tuer, texte a taper,
   chemin de fichier, nom de fenetre, nom d'app...) -> Intention avec args.
"""

from __future__ import annotations

import re
from typing import Callable

from .core import (
    DOM_CLIPBOARD,
    DOM_FILES,
    DOM_MEDIA,
    DOM_POWER,
    DOM_PROCESS,
    DOM_SCREEN,
    DOM_SETTINGS,
    DOM_SYSINFO,
    DOM_VOLUME,
    DOM_WINDOW,
    DOM_LAUNCHER,
    Intention,
)
from .text import (
    est_annulation_arret,
    est_arret_pc,
    est_fermeture_fenetre,
    est_fermeture_generique,
    est_lecture_presse_papier,
    est_redemarrage,
    est_verrouillage,
    rx,
)

Regle = tuple[Callable[[str], bool], str, str]  # (predicat, domaine, action)

# ── Regles sans capture. ORDRE = PRIORITE (migration fidele system puis pc). ──
_REGLES: list[Regle] = [
    # POWER (annulation prioritaire ; hibernation avant veille ; arret garde).
    (est_annulation_arret, DOM_POWER, "cancel"),
    (est_redemarrage, DOM_POWER, "restart"),
    (lambda c: rx(c, r"\b(veille prolong[eé]e|hibernation|hiberne)\b"), DOM_POWER, "hibernate"),
    (lambda c: rx(c, r"\b(mets? en veille|mise en veille|veille|endors le pc|dors)\b") and "prolong" not in c, DOM_POWER, "sleep"),
    (lambda c: rx(c, r"\b(d[eé]connecte|d[eé]connexion|log ?off|ferme ma session|d[eé]logue)\b"), DOM_POWER, "logoff"),
    (est_arret_pc, DOM_POWER, "shutdown"),
    (est_verrouillage, DOM_POWER, "lock"),
    # WINDOW (fermeture fenetre AVANT process_kill ; gestion + bureaux virtuels).
    (est_fermeture_fenetre, DOM_WINDOW, "close_active"),
    (lambda c: rx(c, r"\b(affiche|montre|voir|r[eé]duis tout|minimise tout)\b.*\bbureau\b") or "reduis tout" in c or "réduis tout" in c or "minimise tout" in c, DOM_WINDOW, "show_desktop"),
    (lambda c: rx(c, r"\b(agrandis|maximise)\b.*\bfen[eê]tre\b"), DOM_WINDOW, "maximize"),
    (lambda c: rx(c, r"\b(r[eé]duis|minimise)\b.*\bfen[eê]tre\b"), DOM_WINDOW, "minimize"),
    (lambda c: rx(c, r"\b(change de fen[eê]tre|fen[eê]tre suivante|bascule de fen[eê]tre|alt ?tab)\b"), DOM_WINDOW, "switch"),
    (lambda c: rx(c, r"\bfen[eê]tre\b.*\b[aà] gauche\b") or "snap gauche" in c, DOM_WINDOW, "snap_left"),
    (lambda c: rx(c, r"\bfen[eê]tre\b.*\b[aà] droite\b") or "snap droite" in c, DOM_WINDOW, "snap_right"),
    (lambda c: rx(c, r"\b(liste|quelles?)\b.*\bfen[eê]tres?\b") or "fenetres ouvertes" in c or "fenêtres ouvertes" in c, DOM_WINDOW, "list"),
    (lambda c: rx(c, r"\b(vue des t[aâ]ches|task view)\b"), DOM_WINDOW, "vd_taskview"),
    (lambda c: rx(c, r"\bbureau\b.*\bsuivant\b"), DOM_WINDOW, "vd_next"),
    (lambda c: rx(c, r"\bbureau\b.*\bpr[eé]c[eé]dent\b"), DOM_WINDOW, "vd_prev"),
    (lambda c: rx(c, r"\bnouveau bureau\b"), DOM_WINDOW, "vd_new"),
    # SYSINFO (lecture seule).
    (lambda c: rx(c, r"\b(batterie|charge de la batterie|niveau de batterie)\b"), DOM_SYSINFO, "battery"),
    (lambda c: rx(c, r"\b(processeur|cpu|charge cpu|charge processeur)\b"), DOM_SYSINFO, "cpu"),
    (lambda c: rx(c, r"\b(m[eé]moire vive|m[eé]moire|ram)\b"), DOM_SYSINFO, "memory"),
    (lambda c: rx(c, r"\b(espace disque|disque dur|stockage|espace de stockage)\b"), DOM_SYSINFO, "disk"),
    (lambda c: rx(c, r"\b(infos? syst[eè]me|[eé]tat du pc|sant[eé] du pc|[eé]tat de la machine)\b"), DOM_SYSINFO, "overview"),
    (lambda c: rx(c, r"\b(adresse ip|mon ip|ip locale)\b"), DOM_SYSINFO, "ip"),
    (lambda c: rx(c, r"\b(nom du pc|nom de la machine|nom de l'ordinateur)\b"), DOM_SYSINFO, "hostname"),
    (lambda c: rx(c, r"\b(uptime|temps de fonctionnement)\b") or rx(c, r"depuis quand.*allum"), DOM_SYSINFO, "uptime"),
    # PROCESS (lister les plus gourmands — lecture seule).
    (lambda c: rx(c, r"\b(processus gourmands?|qui consomme|liste des processus|programmes? qui tourne|quels programmes)\b"), DOM_PROCESS, "list"),
    # CLIPBOARD (lecture).
    (est_lecture_presse_papier, DOM_CLIPBOARD, "read"),
    # SCREEN (capture).
    (lambda c: any(p in c for p in ("screenshot", "capture d'ecran", "capture ecran", "capture l'ecran", "prends une capture")), DOM_SCREEN, "screenshot"),
    # FILES (ouvrir l'explorateur — la creation/recherche/ouverture de dossier sont des extracteurs).
    (lambda c: rx(c, r"\b(explorateur( de fichiers)?|gestionnaire de fichiers)\b") and rx(c, r"\b(ouvre|lance|affiche|montre)\b"), DOM_FILES, "open_explorer"),
    # SETTINGS (corbeille + panneaux ms-settings ; specifiques avant le principal).
    (lambda c: rx(c, r"\bvide(r)?\b.*\bcorbeille\b"), DOM_SETTINGS, "recycle_empty"),
    (lambda c: "bluetooth" in c and rx(c, r"\b(param[eè]tre|r[eé]glage|ouvre|active|d[eé]sactive)"), DOM_SETTINGS, "bluetooth"),
    (lambda c: rx(c, r"\b(wifi|wi-fi)\b") and rx(c, r"\b(param[eè]tre|r[eé]glage|ouvre|active|d[eé]sactive)"), DOM_SETTINGS, "wifi"),
    (lambda c: rx(c, r"\b(param[eè]tre|r[eé]glage)") and rx(c, r"\b(son|audio)\b"), DOM_SETTINGS, "sound"),
    (lambda c: rx(c, r"\b(param[eè]tre|r[eé]glage)") and rx(c, r"\b(affichage|[eé]cran)\b"), DOM_SETTINGS, "display"),
    (lambda c: rx(c, r"\b(ouvre|affiche)\b.*\b(param[eè]tres?|r[eé]glages?)\b") or "parametres windows" in c or "paramètres windows" in c, DOM_SETTINGS, "main"),
    # VOLUME extremes (le reglage precis '... a X%' est capture par un extracteur).
    (lambda c: rx(c, r"\bvolume\b.*\b(au maximum|au max|[aà] fond|maximal)\b"), DOM_VOLUME, "max"),
    (lambda c: rx(c, r"\bvolume\b.*\b(au minimum|au plus bas|minimal)\b"), DOM_VOLUME, "min"),
    (lambda c: ("volume" in c or "son" in c) and any(p in c for p in ("coupe", "mute", "silence")), DOM_VOLUME, "mute"),
    (lambda c: ("volume" in c or "son" in c) and any(p in c for p in ("monte", "augmente", "plus fort")), DOM_VOLUME, "up"),
    (lambda c: ("volume" in c or "son" in c) and any(p in c for p in ("baisse", "diminue", "moins fort")), DOM_VOLUME, "down"),
    # SCREEN — raccourcis navigateur/edition (reopen AVANT close ; close_tab AVANT process_kill).
    (lambda c: rx(c, r"\bnouvel? onglet\b"), DOM_SCREEN, "new_tab"),
    (lambda c: rx(c, r"\b(rouvre|r[eé]ouvre|restaure)\b.*\bonglet\b"), DOM_SCREEN, "reopen_tab"),
    (lambda c: rx(c, r"\bferme.{0,5}onglet\b"), DOM_SCREEN, "close_tab"),
    (lambda c: rx(c, r"\b(actualise|rafra[iî]chis|recharge la page)\b"), DOM_SCREEN, "refresh"),
    (lambda c: rx(c, r"\bplein [eé]cran\b"), DOM_SCREEN, "fullscreen"),
    (lambda c: rx(c, r"\b(zoom avant|zoome|agrandis le texte|zoom plus)\b"), DOM_SCREEN, "zoom_in"),
    (lambda c: rx(c, r"\b(zoom arri[eè]re|d[eé]zoom|r[eé]duis le texte|zoom moins)\b"), DOM_SCREEN, "zoom_out"),
    (lambda c: rx(c, r"\b(zoom normal|r[eé]initialise le zoom|zoom par d[eé]faut)\b"), DOM_SCREEN, "zoom_reset"),
    (lambda c: rx(c, r"\b(recherche|cherche|trouve)\b.*\bdans la page\b"), DOM_SCREEN, "find"),
    # MEDIA (touches multimedia).
    (lambda c: any(p in c for p in ("mets pause", "pause la musique", "pause la video", "appuie sur pause")), DOM_MEDIA, "pause"),
    (lambda c: any(p in c for p in ("reprends la musique", "reprends la video", "joue la musique", "remets la musique")), DOM_MEDIA, "play"),
    (lambda c: any(p in c for p in ("piste suivante", "musique suivante", "chanson suivante", "next morceau")), DOM_MEDIA, "next"),
    (lambda c: any(p in c for p in ("piste precedente", "morceau precedent", "musique precedente")), DOM_MEDIA, "prev"),
    # CLIPBOARD copy/paste (bordures de mots : evite 'decolle'/'collecte'/'collegue').
    (lambda c: rx(c, r"\bcopie\b") and rx(c, r"\b(ce|cet|cette|ceci|s[eé]lection)\b"), DOM_CLIPBOARD, "copy"),
    (lambda c: rx(c, r"\bcolle\b"), DOM_CLIPBOARD, "paste"),
]


# ── Extracteurs a capture (apres _REGLES). ──
def _extr_type_text(c: str, brut: str) -> Intention | None:
    """'tape|saisis|ecris X' -> screen/type_text. Preserve la CASSE via `brut`."""
    if re.match(r"\s*(tape|saisis|ecris)\s+(.+)", c, re.I):
        texte = re.split(r"\s*(tape|saisis|ecris)\s+", brut, maxsplit=1, flags=re.I)[-1]
        return Intention(DOM_SCREEN, "type_text", {"text": texte})
    return None


def _extr_vol_set(c: str, brut: str) -> Intention | None:
    if "volume" in c:
        m = re.search(r"(\d{1,3})\s*(?:%|pour ?cent)?", c)
        if m:
            return Intention(DOM_VOLUME, "set", {"level": m.group(1)})
    return None


def _extr_process_kill(c: str, brut: str) -> Intention | None:
    m = re.search(r"\b(ferme|quitte|tue|kill|termine|arr[eê]te)\s+(?:l[' ]?(?:appli|application)\s+)?(.+)", c)
    if m:
        cible = m.group(2).strip()
        if cible and not est_fermeture_generique(cible):
            return Intention(DOM_PROCESS, "kill", {"target": cible})
    return None


def _extr_files(c: str, brut: str) -> Intention | None:
    """Creation/recherche/ouverture de dossier — AVANT open_app (sinon capte)."""
    m = re.search(r"\b(cr[eé]e|cr[eé]er|nouveau)\b.*\bdossier\b\s+(.+)", c)
    if m:
        return Intention(DOM_FILES, "create_folder", {"name": _capture(brut, m.group(2))})
    m = re.search(r"\b(cherche|trouve|recherche)\b.*\bfichier\b\s+(.+)", c)
    if m:
        return Intention(DOM_FILES, "search", {"query": _capture(brut, m.group(2))})
    m = re.search(r"\b(ouvre|montre|affiche)\b.*\bdossier\b\s+(.+)", c)
    if m:
        return Intention(DOM_FILES, "open_folder", {"name": _capture(brut, m.group(2))})
    return None


def _extr_window_focus(c: str, brut: str) -> Intention | None:
    """'passe sur X' / 'mets X au premier plan' / 'bascule sur la fenetre X'."""
    m = re.search(r"\b(passe sur|bascule sur|va sur)\b\s+(?:la fen[eê]tre\s+)?(.+)", c)
    if m:
        return Intention(DOM_WINDOW, "focus", {"name": _capture(brut, m.group(2))})
    m = re.search(r"\bmets?\b\s+(.+?)\s+au premier plan", c)
    if m:
        return Intention(DOM_WINDOW, "focus", {"name": _capture(brut, m.group(1))})
    return None


def _extr_open_app(c: str, brut: str) -> Intention | None:
    """Fourre-tout 'ouvre|lance|demarre X' -> launcher (EN DERNIER)."""
    m = re.search(r"\b(ouvre|lance|demarre|demarrer|ouvrir|lancer)\s+(.+)", c, re.I)
    if m:
        return Intention(DOM_LAUNCHER, "open_app", {"name": m.group(2).strip()})
    return None


def _capture(brut: str, fragment_minuscule: str) -> str:
    """Recupere le fragment dans le texte ORIGINAL (casse preservee) si possible."""
    idx = brut.lower().rfind(fragment_minuscule.strip())
    return brut[idx:].strip() if idx >= 0 else fragment_minuscule.strip()


# ORDRE : dossier & focus AVANT open_app (fourre-tout) ; type_text/vol_set/kill avant.
_EXTRACTEURS = [_extr_type_text, _extr_vol_set, _extr_process_kill, _extr_files, _extr_window_focus, _extr_open_app]


class Router:
    """Detecteur d'intention. PUR (aucun effet de bord, aucune dependance OS)."""

    def __init__(self, regles: list[Regle] | None = None, extracteurs: list | None = None) -> None:
        self._regles = regles if regles is not None else _REGLES
        self._extracteurs = extracteurs if extracteurs is not None else _EXTRACTEURS

    def route(self, texte: str) -> Intention | None:
        if not texte or not texte.strip():
            return None
        c = texte.lower().strip()
        for predicat, dom, act in self._regles:
            if predicat(c):
                return Intention(dom, act)
        for extr in self._extracteurs:
            intention = extr(c, texte)
            if intention is not None:
                return intention
        return None
