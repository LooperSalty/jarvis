"""Actions systeme avancees sur le PC depuis une commande en langage naturel.

Complete `pc_actions.py` (apps, media, saisie) avec le controle systeme :
energie (eteindre/redemarrer/veille), gestion des fenetres, infos materielles
(batterie, CPU, RAM, disque), fermeture d'un programme, presse-papier, corbeille.

Conception :
- `detecter_intention(cmd)` est une fonction PURE (texte -> intention) : aucun
  effet de bord, entierement testable sans mocker l'OS.
- Les formatters (`_format_batterie`, ...) sont purs eux aussi.
- Les dependances (pyautogui, psutil, pyperclip) sont importees de facon
  OPTIONNELLE : le module se charge meme en CI/headless ou sur un OS sans elles
  (degradation propre : on renvoie un message clair au lieu de crasher).

Contrat identique aux autres modules d'actions :
`executer(cmd) -> (reponse_vocale, succes)` ou `(None, False)` si non reconnu.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
from typing import Callable

from jarvis_config import USER_NAME

# --- Dependances optionnelles (degradation propre si absentes) ---
try:
    import pyautogui  # type: ignore
except Exception:  # noqa: BLE001 - environnement headless/CI sans display
    pyautogui = None  # type: ignore

try:
    import psutil  # type: ignore
except Exception:  # noqa: BLE001
    psutil = None  # type: ignore

try:
    import pyperclip  # type: ignore
except Exception:  # noqa: BLE001
    pyperclip = None  # type: ignore

IS_WINDOWS = os.name == "nt"
IS_MAC = platform.system() == "Darwin"

# Delai (s) avant extinction/redemarrage : laisse le temps d'annuler a la voix.
DELAI_ARRET_S = 30

# Message commun quand psutil n'est pas installe (CI/headless ou env minimal).
_PSUTIL_ABSENT = "Les infos systeme ne sont pas disponibles (psutil absent)."
_VSCODE_PROC = "Code.exe"

# Programmes courants -> nom de processus a tuer (taskkill /IM ...).
_PROCESS_ALIASES = {
    "chrome": "chrome.exe",
    "firefox": "firefox.exe",
    "edge": "msedge.exe",
    "vscode": _VSCODE_PROC,
    "vs code": _VSCODE_PROC,
    "code": _VSCODE_PROC,
    "discord": "Discord.exe",
    "spotify": "Spotify.exe",
    "steam": "steam.exe",
    "obsidian": "Obsidian.exe",
    "notepad": "notepad.exe",
    "bloc-notes": "notepad.exe",
    "explorateur": "explorer.exe",
    "explorer": "explorer.exe",
    "calculatrice": "Calculator.exe",
    "paint": "mspaint.exe",
    "word": "WINWORD.EXE",
    "excel": "EXCEL.EXE",
}

# Mots generiques a NE PAS traiter comme un nom de programme a tuer : ils sont
# deja geres par pc_actions (fermer la fenetre active, verrouiller la session).
_FERMETURE_GENERIQUE = ("fenetre", "fenêtre", "session", "application", "appli", "onglet")


# ============================================================
# ROUTEUR PUR : texte -> (intention, argument)  — testable sans OS
# ============================================================

# Regles de routage (predicat sur le texte normalise -> intention), evaluees
# DANS L'ORDRE : il encode les priorites (annulation avant arret, veille
# prolongee avant veille simple, arret PC garde par un nom d'ordinateur...).
# Chaque predicat est PUR. La fermeture de programme (qui capture une cible) est
# traitee a part dans detecter_intention.
_REGLES: list[tuple[Callable[[str], bool], str]] = [
    # Annulation d'un arret/redemarrage programme (prioritaire).
    (lambda c: bool(re.search(r"\b(annule|stoppe|arr[eê]te)\b.*\b(extinction|arr[eê]t|red[eé]marrage|red[eé]marre|veille)\b", c))
               or "annule l'arret" in c or "annule l'extinction" in c, "power_cancel"),
    # Energie.
    (lambda c: bool(re.search(r"\b(red[eé]marre|red[eé]marrer|reboot|relance le pc|relance l'ordinateur)\b", c)), "power_restart"),
    (lambda c: bool(re.search(r"\b(veille prolong[eé]e|hibernation|hiberne)\b", c)), "power_hibernate"),
    (lambda c: bool(re.search(r"\b(mets? en veille|mise en veille|veille|endors le pc|dors)\b", c)) and "prolong" not in c, "power_sleep"),
    (lambda c: bool(re.search(r"\b(d[eé]connecte|d[eé]connexion|log ?off|ferme ma session|d[eé]logue)\b", c)), "power_logoff"),
    (lambda c: bool(re.search(r"\b([eé]teins|[eé]teindre|arr[eê]te|arr[eê]ter|coupe|shutdown)\b", c))
               and bool(re.search(r"\b(pc|ordinateur|ordi|machine|syst[eè]me)\b", c))
               and "fenetre" not in c and "fenêtre" not in c, "power_shutdown"),
    # Gestion des fenetres.
    (lambda c: bool(re.search(r"\b(affiche|montre|voir|r[eé]duis tout|minimise tout)\b.*\bbureau\b", c))
               or "reduis tout" in c or "réduis tout" in c or "minimise tout" in c, "win_show_desktop"),
    (lambda c: bool(re.search(r"\b(agrandis|maximise|plein [eé]cran)\b.*\bfen[eê]tre\b", c))
               or "maximise la fenetre" in c or "maximise la fenêtre" in c, "win_maximize"),
    (lambda c: bool(re.search(r"\b(r[eé]duis|minimise)\b.*\bfen[eê]tre\b", c)), "win_minimize"),
    (lambda c: bool(re.search(r"\b(change de fen[eê]tre|fen[eê]tre suivante|bascule de fen[eê]tre|alt ?tab)\b", c)), "win_switch"),
    (lambda c: bool(re.search(r"\bfen[eê]tre\b.*\b[aà] gauche\b", c)) or "colle a gauche" in c or "snap gauche" in c, "win_snap_left"),
    (lambda c: bool(re.search(r"\bfen[eê]tre\b.*\b[aà] droite\b", c)) or "colle a droite" in c or "snap droite" in c, "win_snap_right"),
    # Infos systeme (lecture seule).
    (lambda c: bool(re.search(r"\b(batterie|charge de la batterie|niveau de batterie)\b", c)), "sys_battery"),
    (lambda c: bool(re.search(r"\b(processeur|cpu|charge cpu|charge processeur)\b", c)), "sys_cpu"),
    (lambda c: bool(re.search(r"\b(m[eé]moire vive|m[eé]moire|ram)\b", c)), "sys_memory"),
    (lambda c: bool(re.search(r"\b(espace disque|disque dur|stockage|espace de stockage)\b", c)), "sys_disk"),
    (lambda c: bool(re.search(r"\b(infos? syst[eè]me|[eé]tat du pc|sant[eé] du pc|[eé]tat de la machine)\b", c)), "sys_overview"),
    # Presse-papier (lecture).
    (lambda c: bool(re.search(r"\b(presse[- ]papier|presse[- ]papiers)\b", c))
               and bool(re.search(r"\b(lis|lit|contenu|qu[' ]?y a[- ]?t[- ]?il|qu[' ]?est[- ]?ce|montre|dis)\b", c)), "clipboard_read"),
    # Corbeille.
    (lambda c: bool(re.search(r"\bvide(r)?\b.*\bcorbeille\b", c)) or "vide la corbeille" in c, "recycle_empty"),
]


def detecter_intention(cmd: str) -> tuple[str, str | None] | None:
    """Mappe une commande en langage naturel vers une intention systeme.

    Retourne (intention, argument) ou None si non reconnue. Fonction PURE :
    aucun effet de bord, aucune dependance OS. C'est le coeur testable du module.
    """
    if not cmd:
        return None
    c = cmd.lower().strip()

    for predicat, intention in _REGLES:
        if predicat(c):
            return (intention, None)

    # Fermer un programme (taskkill) : capture la cible et filtre les generiques
    # (fenetre/session deja geres par pc_actions).
    m = re.search(r"\b(ferme|quitte|tue|kill|termine|arr[eê]te)\s+(?:l[' ]?(?:appli|application)\s+)?(.+)", c)
    if m:
        cible = m.group(2).strip()
        if cible and not any(g in cible for g in _FERMETURE_GENERIQUE):
            return ("process_kill", cible)

    return None


# ============================================================
# FORMATTERS PURS
# ============================================================

def _format_batterie(percent: float | int | None, branche: bool | None) -> str:
    if percent is None:
        return f"Je ne detecte pas de batterie sur ce PC, {USER_NAME} (poste fixe ?)."
    pct = int(round(percent))
    if branche:
        etat = "en charge" if pct < 100 else "pleine, sur secteur"
    else:
        etat = "sur batterie"
    return f"Batterie a {pct} pour cent, {etat}, {USER_NAME}."


def _format_cpu(percent: float) -> str:
    return f"Le processeur est utilise a {int(round(percent))} pour cent, {USER_NAME}."


def _format_memoire(percent: float, used_go: float, total_go: float) -> str:
    return (
        f"Memoire vive : {int(round(percent))} pour cent utilisee, "
        f"soit {used_go:.1f} sur {total_go:.1f} gigaoctets."
    )


def _format_disque(percent: float, libre_go: float, total_go: float) -> str:
    return (
        f"Disque principal : {libre_go:.0f} gigaoctets libres sur {total_go:.0f}, "
        f"rempli a {int(round(percent))} pour cent."
    )


# ============================================================
# HANDLERS (effets de bord, dependances optionnelles)
# ============================================================

def _hotkey(*touches: str) -> tuple[str, bool]:
    if pyautogui is None:
        return ("Le controle clavier n'est pas disponible sur cet environnement.", False)
    try:
        pyautogui.hotkey(*touches)
        return ("", True)
    except Exception as e:  # noqa: BLE001
        return (f"Echec de l'action fenetre : {e}", False)


def _power_shutdown() -> tuple[str, bool]:
    if IS_WINDOWS:
        subprocess.run(["shutdown", "/s", "/t", str(DELAI_ARRET_S),
                        "/c", "Extinction demandee par Jarvis"], check=False, shell=False)
        return (f"J'eteins le PC dans {DELAI_ARRET_S} secondes, {USER_NAME}. "
                f"Dis 'annule l'extinction' pour stopper.", True)
    if IS_MAC:
        subprocess.run(["osascript", "-e", 'tell app "System Events" to shut down'],
                       check=False, shell=False)
        return (f"J'eteins le Mac, {USER_NAME}.", True)
    subprocess.run(["shutdown", "-h", f"+{DELAI_ARRET_S // 60 or 1}"], check=False, shell=False)
    return (f"Extinction programmee, {USER_NAME}.", True)


def _power_restart() -> tuple[str, bool]:
    if IS_WINDOWS:
        subprocess.run(["shutdown", "/r", "/t", str(DELAI_ARRET_S),
                        "/c", "Redemarrage demande par Jarvis"], check=False, shell=False)
        return (f"Je redemarre le PC dans {DELAI_ARRET_S} secondes, {USER_NAME}. "
                f"Dis 'annule le redemarrage' pour stopper.", True)
    if IS_MAC:
        subprocess.run(["osascript", "-e", 'tell app "System Events" to restart'],
                       check=False, shell=False)
        return (f"Je redemarre le Mac, {USER_NAME}.", True)
    subprocess.run(["shutdown", "-r", "+1"], check=False, shell=False)
    return (f"Redemarrage programme, {USER_NAME}.", True)


def _power_cancel() -> tuple[str, bool]:
    if IS_WINDOWS:
        subprocess.run(["shutdown", "/a"], check=False, shell=False)
        return (f"C'est annule, {USER_NAME}. Le PC reste allume.", True)
    subprocess.run(["shutdown", "-c"], check=False, shell=False)
    return (f"Arret annule, {USER_NAME}.", True)


def _power_sleep() -> tuple[str, bool]:
    if IS_WINDOWS:
        subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                       check=False, shell=False)
        return (f"Mise en veille, {USER_NAME}.", True)
    if IS_MAC:
        subprocess.run(["pmset", "sleepnow"], check=False, shell=False)
        return (f"Mise en veille, {USER_NAME}.", True)
    subprocess.run(["systemctl", "suspend"], check=False, shell=False)
    return (f"Mise en veille, {USER_NAME}.", True)


def _power_hibernate() -> tuple[str, bool]:
    if IS_WINDOWS:
        subprocess.run(["shutdown", "/h"], check=False, shell=False)
        return (f"Mise en veille prolongee, {USER_NAME}.", True)
    return ("La veille prolongee n'est supportee que sous Windows.", False)


def _power_logoff() -> tuple[str, bool]:
    if IS_WINDOWS:
        subprocess.run(["shutdown", "/l"], check=False, shell=False)
        return (f"Je ferme ta session, {USER_NAME}.", True)
    if IS_MAC:
        subprocess.run(["osascript", "-e", 'tell app "System Events" to log out'],
                       check=False, shell=False)
        return (f"Je ferme ta session, {USER_NAME}.", True)
    return ("La deconnexion n'est pas supportee sur cet OS.", False)


def _sys_battery() -> tuple[str, bool]:
    if psutil is None:
        return (_PSUTIL_ABSENT, False)
    try:
        batt = psutil.sensors_battery()
    except Exception:  # noqa: BLE001 - certaines plateformes ne l'implementent pas
        batt = None
    if batt is None:
        return (_format_batterie(None, None), True)
    return (_format_batterie(batt.percent, batt.power_plugged), True)


def _sys_cpu() -> tuple[str, bool]:
    if psutil is None:
        return (_PSUTIL_ABSENT, False)
    return (_format_cpu(psutil.cpu_percent(interval=0.4)), True)


def _sys_memory() -> tuple[str, bool]:
    if psutil is None:
        return (_PSUTIL_ABSENT, False)
    m = psutil.virtual_memory()
    go = 1024 ** 3
    return (_format_memoire(m.percent, m.used / go, m.total / go), True)


def _sys_disk() -> tuple[str, bool]:
    if psutil is None:
        return (_PSUTIL_ABSENT, False)
    racine = "C:\\" if IS_WINDOWS else "/"
    d = psutil.disk_usage(racine)
    go = 1024 ** 3
    return (_format_disque(d.percent, d.free / go, d.total / go), True)


def _sys_overview() -> tuple[str, bool]:
    parties = []
    for fn in (_sys_cpu, _sys_memory, _sys_disk, _sys_battery):
        rep, ok = fn()
        if ok and rep:
            parties.append(rep)
    if not parties:
        return (_PSUTIL_ABSENT, False)
    return (" ".join(parties), True)


def _clipboard_read() -> tuple[str, bool]:
    if pyperclip is None:
        return ("Je ne peux pas lire le presse-papier sur cet environnement.", False)
    try:
        contenu = (pyperclip.paste() or "").strip()
    except Exception as e:  # noqa: BLE001
        return (f"Echec de lecture du presse-papier : {e}", False)
    if not contenu:
        return (f"Le presse-papier est vide, {USER_NAME}.", True)
    apercu = contenu if len(contenu) <= 300 else contenu[:300] + "..."
    return (f"Presse-papier : {apercu}", True)


def _recycle_empty() -> tuple[str, bool]:
    if IS_WINDOWS:
        subprocess.run(["powershell", "-NoProfile", "-Command", "Clear-RecycleBin -Force"],
                       check=False, shell=False)
        return (f"Corbeille videe, {USER_NAME}.", True)
    return ("Vider la corbeille n'est supporte que sous Windows pour l'instant.", False)


def _process_kill(cible: str) -> tuple[str, bool]:
    nom = cible.strip().lower()
    proc = _PROCESS_ALIASES.get(nom)
    if proc is None:
        # Nom libre : on tente <nom>.exe sous Windows (sans .exe ailleurs).
        if nom.endswith(".exe") or not IS_WINDOWS:
            proc = nom
        else:
            proc = f"{nom}.exe"
    try:
        if IS_WINDOWS:
            r = subprocess.run(["taskkill", "/IM", proc, "/F"],
                               check=False, shell=False, capture_output=True, text=True)
            if r.returncode == 0:
                return (f"J'ai ferme {cible}, {USER_NAME}.", True)
            return (f"Je n'ai pas trouve {cible} en cours d'execution, {USER_NAME}.", False)
        subprocess.run(["pkill", "-f", proc], check=False, shell=False)
        return (f"J'ai ferme {cible}, {USER_NAME}.", True)
    except Exception as e:  # noqa: BLE001
        return (f"Echec de fermeture de {cible} : {e}", False)


# ============================================================
# DISPATCH
# ============================================================

_HANDLERS_SANS_ARG = {
    "power_shutdown": _power_shutdown,
    "power_restart": _power_restart,
    "power_cancel": _power_cancel,
    "power_sleep": _power_sleep,
    "power_hibernate": _power_hibernate,
    "power_logoff": _power_logoff,
    "sys_battery": _sys_battery,
    "sys_cpu": _sys_cpu,
    "sys_memory": _sys_memory,
    "sys_disk": _sys_disk,
    "sys_overview": _sys_overview,
    "clipboard_read": _clipboard_read,
    "recycle_empty": _recycle_empty,
}

# Intentions de fenetre -> raccourci clavier (touche Windows = 'win').
_WIN_HOTKEYS = {
    "win_show_desktop": ("win", "d"),
    "win_maximize": ("win", "up"),
    "win_minimize": ("win", "down"),
    "win_switch": ("alt", "tab"),
    "win_snap_left": ("win", "left"),
    "win_snap_right": ("win", "right"),
}

_WIN_MESSAGES = {
    "win_show_desktop": "Bureau affiche.",
    "win_maximize": "Fenetre agrandie.",
    "win_minimize": "Fenetre reduite.",
    "win_switch": "Je change de fenetre.",
    "win_snap_left": "Fenetre callee a gauche.",
    "win_snap_right": "Fenetre callee a droite.",
}


def executer(cmd: str) -> tuple[str | None, bool]:
    """Execute une action systeme. (reponse, succes) ou (None, False) si non reconnu."""
    intention = detecter_intention(cmd)
    if intention is None:
        return None, False
    nom, arg = intention

    if nom in _HANDLERS_SANS_ARG:
        return _HANDLERS_SANS_ARG[nom]()

    if nom in _WIN_HOTKEYS:
        _, ok = _hotkey(*_WIN_HOTKEYS[nom])
        if ok:
            return _WIN_MESSAGES[nom], True
        return "Le controle des fenetres n'est pas disponible ici.", False

    if nom == "process_kill" and arg:
        return _process_kill(arg)

    return None, False
