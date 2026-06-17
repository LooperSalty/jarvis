"""Helpers texte PURS : normalisation, gardes metier, formatters.

Aucune dependance OS : ce fichier (avec router.py) est le coeur 100% testable.
Les gardes encodent les pieges critiques (distinguer 'eteins le pc' de
'eteins la lumiere', exclure 'fenetre' de l'arret, etc.).
"""

from __future__ import annotations

import re

from jarvis_config import USER_NAME

# Mots generiques qu'on ne traite PAS comme une cible de process a tuer
# (deja geres par la fermeture de fenetre / le verrouillage de session).
FERMETURE_GENERIQUE = ("fenetre", "fenêtre", "session", "application", "appli", "onglet")


def normaliser(texte: str) -> str:
    """Minuscule + espaces resserres. Base de toute detection."""
    return (texte or "").lower().strip()


def rx(c: str, motif: str) -> bool:
    """`bool(re.search(motif, c))` — sucre pour les regles du routeur."""
    return bool(re.search(motif, c))


# ── Gardes metier (chacune < 15 lignes, testees finement) ──
def est_annulation_arret(c: str) -> bool:
    """'annule l'extinction / le redemarrage' — prioritaire sur tout l'energie."""
    return (
        rx(c, r"\b(annule|stoppe|arr[eê]te)\b.*\b(extinction|arr[eê]t|red[eé]marrage|red[eé]marre|veille)\b")
        or "annule l'arret" in c
        or "annule l'extinction" in c
    )


def est_redemarrage(c: str) -> bool:
    return rx(c, r"\b(red[eé]marre|red[eé]marrer|reboot|relance le pc|relance l'ordinateur)\b")


def est_arret_pc(c: str) -> bool:
    """'eteins le pc' OUI ; 'eteins la lumiere' / 'eteins tout' / 'ferme la
    fenetre' / 'coupe le systeme de son' NON. 'systeme' EXCLU des cibles : trop
    dangereux (faux positif 'coupe le systeme de son' -> arret reel)."""
    return (
        rx(c, r"\b([eé]teins|[eé]teindre|arr[eê]te|arr[eê]ter|coupe|shutdown)\b")
        and rx(c, r"\b(pc|ordinateur|ordi|machine)\b")
        and "fenetre" not in c
        and "fenêtre" not in c
    )


def est_verrouillage(c: str) -> bool:
    return rx(c, r"\b(verrouille|verrouiller|lock le pc|ferme la session)\b")


def est_fermeture_fenetre(c: str) -> bool:
    return (
        "ferme cette fenetre" in c
        or "ferme la fenetre" in c
        or "ferme cette fenêtre" in c
        or "ferme la fenêtre" in c
        or "ferme l'application" in c
        or "ferme l application" in c
    )


def est_fermeture_generique(cible: str) -> bool:
    """True si la cible d'un 'ferme X' est un mot generique (pas un programme)."""
    return any(g in cible for g in FERMETURE_GENERIQUE)


def est_lecture_presse_papier(c: str) -> bool:
    return rx(c, r"\b(presse[- ]papier|presse[- ]papiers)\b") and rx(
        c, r"\b(lis|lit|contenu|qu[' ]?y a[- ]?t[- ]?il|qu[' ]?est[- ]?ce|montre|dis)\b"
    )


# ── Formatters PURS (messages vocaux) ──
def format_batterie(percent: float | int | None, branche: bool | None) -> str:
    if percent is None:
        return f"Je ne detecte pas de batterie sur ce PC, {USER_NAME} (poste fixe ?)."
    pct = int(round(percent))
    if branche:
        etat = "en charge" if pct < 100 else "pleine, sur secteur"
    else:
        etat = "sur batterie"
    return f"Batterie a {pct} pour cent, {etat}, {USER_NAME}."


def format_cpu(percent: float) -> str:
    return f"Le processeur est utilise a {int(round(percent))} pour cent, {USER_NAME}."


def format_memoire(percent: float, used_go: float, total_go: float) -> str:
    return (
        f"Memoire vive : {int(round(percent))} pour cent utilisee, "
        f"soit {used_go:.1f} sur {total_go:.1f} gigaoctets."
    )


def format_disque(percent: float, libre_go: float, total_go: float) -> str:
    return (
        f"Disque principal : {libre_go:.0f} gigaoctets libres sur {total_go:.0f}, "
        f"rempli a {int(round(percent))} pour cent."
    )


def format_uptime(secondes: float) -> str:
    total_min = int(secondes // 60)
    jours, reste = divmod(total_min, 1440)
    heures, minutes = divmod(reste, 60)
    morceaux = []
    if jours:
        morceaux.append(f"{jours} jour{'s' if jours > 1 else ''}")
    if heures:
        morceaux.append(f"{heures} heure{'s' if heures > 1 else ''}")
    morceaux.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
    return "Le PC est allume depuis " + ", ".join(morceaux) + "."
