"""Capacites de controle systeme du PC (6 domaines).

Migration fidele de `system_actions.py` (+ verrouillage/fermeture de fenetre de
`pc_actions.py`) vers le modele Capability du package `pc_control` :

- `PowerManager`   (DOM_POWER)   : extinction/redemarrage/veille/verrouillage...
- `WindowManager`  (DOM_WINDOW)  : fenetres + bureaux virtuels + list/focus.
- `ProcessManager` (DOM_PROCESS) : kill par alias + list (top RAM).
- `SystemInfo`     (DOM_SYSINFO) : infos lecture seule (batterie/cpu/ram/disque...).
- `SettingsPanel`  (DOM_SETTINGS): panneaux ms-settings: + vidage corbeille.
- `FileManager`    (DOM_FILES)   : explorateur + ouverture/creation/recherche (SUR).

Chaque handler est decore `@never_throw` et renvoie TOUJOURS un `ActionResult`.
subprocess passe par le `Runner` injecte (shell=False) ; les actions clavier par
les wrappers `deps.*`. Garde-fous : `SafetyPolicy.allow_power` / `allow_kill`.
"""

from __future__ import annotations

import os
import platform
import socket
import subprocess
import time
from pathlib import Path

from jarvis_config import USER_NAME

from .. import deps
from ..core import (
    DOM_FILES,
    DOM_POWER,
    DOM_PROCESS,
    DOM_SETTINGS,
    DOM_SYSINFO,
    DOM_WINDOW,
    ActionResult,
    Intention,
    Runner,
    SafetyPolicy,
    Status,
    get_logger,
)
from ..text import (
    format_batterie,
    format_cpu,
    format_disque,
    format_memoire,
    format_uptime,
)
from .base import Capability, never_throw

_GO = 1024 ** 3  # octets -> gigaoctets
_LOG = get_logger()


# ============================================================
# 1) POWER — energie + verrouillage (cross-platform)
# ============================================================
class PowerManager(Capability):
    """Energie : shutdown/restart/cancel/sleep/hibernate/logoff/lock.

    Garde-fou : sans `policy.allow_power`, les actions destructrices (arret,
    redemarrage, hibernation, deconnexion) sont REFUSEES ; lock et cancel restent
    toujours possibles. subprocess via le Runner injecte.
    """

    domain = DOM_POWER
    #: actions soumises au garde-fou allow_power.
    _PROTEGEES = ("shutdown", "restart", "hibernate", "logoff")

    def __init__(self, runner: Runner, policy: SafetyPolicy) -> None:
        self._runner = runner
        self._policy = policy

    @never_throw
    def handle(self, intent: Intention) -> ActionResult:
        action = intent.action
        if action in self._PROTEGEES and not self._policy.allow_power:
            return ActionResult.refused(
                f"L'extinction et le redemarrage sont desactives, {USER_NAME}."
            )
        handlers = {
            "shutdown": self._shutdown,
            "restart": self._restart,
            "cancel": self._cancel,
            "sleep": self._sleep,
            "hibernate": self._hibernate,
            "logoff": self._logoff,
            "lock": self._lock,
        }
        fn = handlers.get(action)
        return fn() if fn else ActionResult.unhandled()

    def _shutdown(self) -> ActionResult:
        delai = self._policy.shutdown_delay_s
        _LOG.warning("[PCCTL] extinction du PC demandee (delai %ss)", delai)
        if deps.IS_WINDOWS:
            self._runner.run(["shutdown", "/s", "/t", str(delai),
                              "/c", "Extinction demandee par Jarvis"])
            return ActionResult.ok(
                f"J'eteins le PC dans {delai} secondes, {USER_NAME}. "
                f"Dis 'annule l'extinction' pour stopper."
            )
        if deps.IS_MAC:
            self._runner.run(["osascript", "-e",
                              'tell app "System Events" to shut down'])
            return ActionResult.ok(f"J'eteins le Mac, {USER_NAME}.")
        self._runner.run(["shutdown", "-h", f"+{delai // 60 or 1}"])
        return ActionResult.ok(f"Extinction programmee, {USER_NAME}.")

    def _restart(self) -> ActionResult:
        delai = self._policy.shutdown_delay_s
        _LOG.warning("[PCCTL] redemarrage du PC demande (delai %ss)", delai)
        if deps.IS_WINDOWS:
            self._runner.run(["shutdown", "/r", "/t", str(delai),
                              "/c", "Redemarrage demande par Jarvis"])
            return ActionResult.ok(
                f"Je redemarre le PC dans {delai} secondes, {USER_NAME}. "
                f"Dis 'annule le redemarrage' pour stopper."
            )
        if deps.IS_MAC:
            self._runner.run(["osascript", "-e",
                              'tell app "System Events" to restart'])
            return ActionResult.ok(f"Je redemarre le Mac, {USER_NAME}.")
        self._runner.run(["shutdown", "-r", "+1"])
        return ActionResult.ok(f"Redemarrage programme, {USER_NAME}.")

    def _cancel(self) -> ActionResult:
        if deps.IS_WINDOWS:
            self._runner.run(["shutdown", "/a"])
            return ActionResult.ok(f"C'est annule, {USER_NAME}. Le PC reste allume.")
        self._runner.run(["shutdown", "-c"])
        return ActionResult.ok(f"Arret annule, {USER_NAME}.")

    def _sleep(self) -> ActionResult:
        if deps.IS_WINDOWS:
            self._runner.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        elif deps.IS_MAC:
            self._runner.run(["pmset", "sleepnow"])
        else:
            self._runner.run(["systemctl", "suspend"])
        return ActionResult.ok(f"Mise en veille, {USER_NAME}.")

    def _hibernate(self) -> ActionResult:
        if deps.IS_WINDOWS:
            self._runner.run(["shutdown", "/h"])
            return ActionResult.ok(f"Mise en veille prolongee, {USER_NAME}.")
        return ActionResult.fail("La veille prolongee n'est supportee que sous Windows.")

    def _logoff(self) -> ActionResult:
        if deps.IS_WINDOWS:
            self._runner.run(["shutdown", "/l"])
            return ActionResult.ok(f"Je ferme ta session, {USER_NAME}.")
        if deps.IS_MAC:
            self._runner.run(["osascript", "-e",
                              'tell app "System Events" to log out'])
            return ActionResult.ok(f"Je ferme ta session, {USER_NAME}.")
        return ActionResult.fail("La deconnexion n'est pas supportee sur cet OS.")

    def _lock(self) -> ActionResult:
        if deps.IS_WINDOWS:
            self._runner.run(["rundll32.exe", "user32.dll,LockWorkStation"])
            return ActionResult.ok(f"PC verrouille, {USER_NAME}.")
        if deps.IS_MAC:
            # Ctrl+Cmd+Q = verrouillage natif macOS (permission Accessibilite requise).
            if deps.hotkey("ctrl", "command", "q"):
                return ActionResult.ok(f"Session verrouillee, {USER_NAME}.")
            return ActionResult.fail("Le verrouillage n'est pas disponible ici.")
        return ActionResult.fail("Verrouillage non supporte sur cet OS.")


# ============================================================
# 2) WINDOW — fenetres + bureaux virtuels + list/focus
# ============================================================
# action -> (touches du raccourci, message vocal de succes).
_WINDOW_HOTKEYS = {
    "show_desktop": (("win", "d"), "Bureau affiche."),
    "maximize": (("win", "up"), "Fenetre agrandie."),
    "minimize": (("win", "down"), "Fenetre reduite."),
    "switch": (("alt", "tab"), "Je change de fenetre."),
    "snap_left": (("win", "left"), "Fenetre callee a gauche."),
    "snap_right": (("win", "right"), "Fenetre callee a droite."),
    "vd_taskview": (("win", "tab"), "Vue des taches."),
    "vd_next": (("ctrl", "win", "right"), "Bureau suivant."),
    "vd_prev": (("ctrl", "win", "left"), "Bureau precedent."),
    "vd_new": (("ctrl", "win", "d"), "Nouveau bureau virtuel."),
}


def _import_pygetwindow():
    """Import optionnel de pygetwindow (gestion fenetres Windows). None si absent."""
    try:
        import pygetwindow  # type: ignore
        return pygetwindow
    except Exception:  # noqa: BLE001 - lib absente / OS non supporte
        return None


class WindowManager(Capability):
    """Fenetres et bureaux virtuels via raccourcis clavier + list/focus.

    Les raccourcis passent par `deps.hotkey` (jamais d'exception). `list` et
    `focus` tentent pygetwindow et se degradent proprement s'il manque.
    """

    domain = DOM_WINDOW

    def available(self) -> bool:
        return deps.has_pyautogui()

    @never_throw
    def handle(self, intent: Intention) -> ActionResult:
        action = intent.action
        if action == "close_active":
            return self._close_active()
        if action == "list":
            return self._list()
        if action == "focus":
            return self._focus(intent.args.get("name", ""))
        regle = _WINDOW_HOTKEYS.get(action)
        if regle is None:
            return ActionResult.unhandled()
        touches, message = regle
        if deps.hotkey(*touches):
            return ActionResult.ok(message)
        return ActionResult.fail("Ce raccourci n'est pas disponible sur cet environnement.")

    def _close_active(self) -> ActionResult:
        touches = ("command", "w") if deps.IS_MAC else ("alt", "f4")
        if deps.hotkey(*touches):
            return ActionResult.ok("Fenetre fermee.")
        return ActionResult.fail("Je n'ai pas pu fermer la fenetre active.")

    def _list(self) -> ActionResult:
        gw = _import_pygetwindow()
        if gw is None:
            return ActionResult.fail(
                f"Je ne peux pas lister les fenetres ici, {USER_NAME}."
            )
        titres = [t.strip() for t in gw.getAllTitles() if t and t.strip()]
        if not titres:
            return ActionResult.ok(f"Aucune fenetre visible, {USER_NAME}.")
        apercu = ", ".join(titres[:8])
        return ActionResult.ok(f"Fenetres ouvertes : {apercu}.", titres=titres)

    def _focus(self, name: str) -> ActionResult:
        cible = (name or "").strip().lower()
        if not cible:
            return ActionResult.unhandled()
        gw = _import_pygetwindow()
        if gw is None:
            return ActionResult.fail(
                f"Je ne peux pas changer de fenetre ici, {USER_NAME}."
            )
        for fenetre in gw.getAllWindows():
            titre = (getattr(fenetre, "title", "") or "")
            if cible in titre.lower():
                fenetre.activate()
                return ActionResult.ok(f"Voila {titre}, {USER_NAME}.")
        return ActionResult.fail(f"Je n'ai pas trouve de fenetre '{name}', {USER_NAME}.")


# ============================================================
# 3) PROCESS — fermeture de programme + list (top RAM)
# ============================================================
# Programmes courants -> nom de processus a tuer (taskkill /IM ...).
_VSCODE_PROC = "Code.exe"
_PROCESS_ALIASES = {
    "chrome": "chrome.exe", "firefox": "firefox.exe", "edge": "msedge.exe",
    "vscode": _VSCODE_PROC, "vs code": _VSCODE_PROC, "code": _VSCODE_PROC,
    "discord": "Discord.exe", "spotify": "Spotify.exe", "steam": "steam.exe",
    "obsidian": "Obsidian.exe", "notepad": "notepad.exe", "bloc-notes": "notepad.exe",
    "explorateur": "explorer.exe", "explorer": "explorer.exe",
    "calculatrice": "Calculator.exe", "paint": "mspaint.exe",
    "word": "WINWORD.EXE", "excel": "EXCEL.EXE",
}
# Mots generiques refuses comme cible (geres par WindowManager/PowerManager).
_CIBLES_GENERIQUES = ("fenetre", "fenêtre", "session", "application", "appli", "onglet")


class ProcessManager(Capability):
    """Fermeture de programme (kill) et top des processus par memoire.

    Garde-fou : sans `policy.allow_kill`, `kill` est REFUSE. Une cible vide ou
    generique laisse la main a l'IA (unhandled). subprocess via le Runner.
    """

    domain = DOM_PROCESS

    def __init__(self, runner: Runner, policy: SafetyPolicy) -> None:
        self._runner = runner
        self._policy = policy

    @never_throw
    def handle(self, intent: Intention) -> ActionResult:
        if intent.action == "list":
            return self._list()
        if intent.action == "kill":
            return self._kill(intent.args.get("target", ""))
        return ActionResult.unhandled()

    def _kill(self, target: str) -> ActionResult:
        nom = (target or "").strip().lower()
        if not nom or any(g in nom for g in _CIBLES_GENERIQUES):
            return ActionResult.unhandled()
        # ANTI-INJECTION : un nom commencant par '-' serait pris pour une option
        # par taskkill/pkill (coherence avec la garde du launcher).
        if nom.startswith("-"):
            return ActionResult.refused(
                f"Je ne peux pas fermer '{target}' : nom invalide, {USER_NAME}."
            )
        if not self._policy.allow_kill:
            return ActionResult.refused(
                f"La fermeture de programmes est desactivee, {USER_NAME}."
            )
        proc = self._resoudre_processus(nom)
        _LOG.warning("[PCCTL] fermeture du processus '%s' (%s)", target, proc)
        introuvable = f"Je n'ai pas trouve {target} en cours d'execution, {USER_NAME}."
        if deps.IS_WINDOWS:
            r = self._runner.run(["taskkill", "/IM", proc, "/F"],
                                 capture_output=True, text=True)
            if r.returncode == 0:
                return ActionResult.ok(f"J'ai ferme {target}, {USER_NAME}.")
            return ActionResult.fail(introuvable)
        # Non-Windows : pkill par NOM exact (pas -f, qui matche toute la cmdline
        # en regex non echappee). On verifie le code retour (0 = au moins un tue).
        cible = proc[:-4] if proc.endswith(".exe") else proc
        r = self._runner.run(["pkill", cible], capture_output=True, text=True)
        if getattr(r, "returncode", 1) == 0:
            return ActionResult.ok(f"J'ai ferme {target}, {USER_NAME}.")
        return ActionResult.fail(introuvable)

    @staticmethod
    def _resoudre_processus(nom: str) -> str:
        """Alias connu (exact OU en sous-chaine, pour 'le navigateur chrome'),
        sinon <nom>.exe sous Windows (nom brut ailleurs)."""
        proc = _PROCESS_ALIASES.get(nom)
        if proc is not None:
            return proc
        for alias, cible in _PROCESS_ALIASES.items():
            if alias in nom:
                return cible
        if nom.endswith(".exe") or not deps.IS_WINDOWS:
            return nom
        return f"{nom}.exe"

    def _list(self) -> ActionResult:
        procs = deps.process_iter(["name", "memory_info"])
        if procs is None:
            return ActionResult.fail(
                f"Je ne peux pas lister les processus ici, {USER_NAME} (psutil absent)."
            )
        classes = sorted(
            procs, key=lambda p: getattr(p.get("memory_info"), "rss", 0), reverse=True
        )
        morceaux = []
        for p in classes[:5]:
            mo = getattr(p.get("memory_info"), "rss", 0) / (1024 ** 2)
            morceaux.append(f"{p.get('name') or '?'} ({mo:.0f} Mo)")
        if not morceaux:
            return ActionResult.ok(f"Aucun processus a lister, {USER_NAME}.")
        return ActionResult.ok("Processus les plus gourmands : " + ", ".join(morceaux) + ".")


# ============================================================
# 4) SYSINFO — infos materielles (lecture seule)
# ============================================================
class SystemInfo(Capability):
    """Infos systeme en lecture seule (batterie/cpu/ram/disque/ip/hostname/uptime).

    S'appuie sur les accesseurs `deps.*` (psutil) + les formatters purs de text.py.
    """

    domain = DOM_SYSINFO

    @never_throw
    def handle(self, intent: Intention) -> ActionResult:
        handlers = {
            "battery": self._battery, "cpu": self._cpu, "memory": self._memory,
            "disk": self._disk, "overview": self._overview, "ip": self._ip,
            "hostname": self._hostname, "uptime": self._uptime,
        }
        fn = handlers.get(intent.action)
        return fn() if fn else ActionResult.unhandled()

    @staticmethod
    def _absent() -> ActionResult:
        return ActionResult.fail("Les infos systeme ne sont pas disponibles (psutil absent).")

    def _battery(self) -> ActionResult:
        if not deps.has_psutil():
            return self._absent()
        batt = deps.battery()
        if batt is None:
            return ActionResult.ok(format_batterie(None, None))
        return ActionResult.ok(format_batterie(batt.percent, batt.power_plugged))

    def _cpu(self) -> ActionResult:
        pct = deps.cpu_percent()
        if pct is None:
            return self._absent()
        return ActionResult.ok(format_cpu(pct))

    def _memory(self) -> ActionResult:
        m = deps.virtual_memory()
        if m is None:
            return self._absent()
        return ActionResult.ok(format_memoire(m.percent, m.used / _GO, m.total / _GO))

    def _disk(self) -> ActionResult:
        racine = "C:\\" if deps.IS_WINDOWS else "/"
        d = deps.disk_usage(racine)
        if d is None:
            return self._absent()
        return ActionResult.ok(format_disque(d.percent, d.free / _GO, d.total / _GO))

    def _overview(self) -> ActionResult:
        parties = []
        for fn in (self._cpu, self._memory, self._disk, self._battery):
            res = fn()
            if res.status is Status.OK and res.message:
                parties.append(res.message)
        if not parties:
            return self._absent()
        return ActionResult.ok(" ".join(parties))

    def _ip(self) -> ActionResult:
        ip = self._detecter_ip()
        if not ip:
            return ActionResult.fail("Je n'ai pas reussi a determiner l'adresse IP locale.")
        return ActionResult.ok(f"L'adresse IP locale est {ip}, {USER_NAME}.")

    @staticmethod
    def _detecter_ip() -> str:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:  # noqa: BLE001
            ip = ""
        if ip and not ip.startswith("127."):
            return ip
        # Repli : socket UDP (ne transmet rien) pour l'IP de l'interface active.
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except Exception:  # noqa: BLE001
            return ""
        finally:
            if s is not None:
                s.close()  # ferme le FD meme si connect/getsockname leve

    def _hostname(self) -> ActionResult:
        nom = platform.node() or socket.gethostname()
        return ActionResult.ok(f"Ce PC s'appelle {nom}, {USER_NAME}.")

    def _uptime(self) -> ActionResult:
        boot = deps.boot_time()
        if boot is None:
            return self._absent()
        return ActionResult.ok(format_uptime(time.time() - boot))


# ============================================================
# 5) SETTINGS — panneaux ms-settings: + corbeille (Windows)
# ============================================================
# action -> (URI ms-settings:, message vocal).
_SETTINGS_URIS = {
    "main": ("ms-settings:", "J'ouvre les parametres Windows."),
    "bluetooth": ("ms-settings:bluetooth",
                  "J'ouvre les parametres Bluetooth. Tu peux l'activer ou le couper la."),
    "wifi": ("ms-settings:network-wifi",
             "J'ouvre les parametres Wi-Fi. Tu peux l'activer ou le couper la."),
    "sound": ("ms-settings:sound", "J'ouvre les parametres son."),
    "display": ("ms-settings:display", "J'ouvre les parametres d'affichage."),
}


class SettingsPanel(Capability):
    """Panneaux de parametres Windows (ms-settings:) et vidage de la corbeille.

    Hors Windows : echec propre (ces panneaux n'existent pas ailleurs).
    """

    domain = DOM_SETTINGS

    def __init__(self, runner: Runner) -> None:
        self._runner = runner

    @never_throw
    def handle(self, intent: Intention) -> ActionResult:
        if not deps.IS_WINDOWS:
            return ActionResult.fail(
                "Les panneaux de parametres ne sont disponibles que sous Windows."
            )
        if intent.action == "recycle_empty":
            self._runner.run(["powershell", "-NoProfile", "-Command",
                              "Clear-RecycleBin -Force"])
            return ActionResult.ok(f"Corbeille videe, {USER_NAME}.")
        regle = _SETTINGS_URIS.get(intent.action)
        if regle is None:
            return ActionResult.unhandled()
        uri, message = regle
        os.startfile(uri)  # type: ignore[attr-defined]
        return ActionResult.ok(message)


# ============================================================
# 6) FILES — explorateur + ouverture/creation/recherche (SUR)
# ============================================================
# Nom usuel -> nom de dossier standard sous le home.
_DOSSIERS_STANDARD = {
    "telechargements": "Downloads", "téléchargements": "Downloads",
    "downloads": "Downloads", "documents": "Documents",
    "bureau": "Desktop", "desktop": "Desktop",
    "images": "Pictures", "photos": "Pictures", "pictures": "Pictures",
    "musique": "Music", "music": "Music",
    "videos": "Videos", "vidéos": "Videos",
}


class FileManager(Capability):
    """Acces fichiers SUR : ouvrir l'explorateur / un dossier, en creer un,
    chercher des fichiers. AUCUNE suppression (par conception). Validation des
    entrees pour interdire les chemins hors du home a la creation.
    """

    domain = DOM_FILES

    @never_throw
    def handle(self, intent: Intention) -> ActionResult:
        handlers = {
            "open_explorer": lambda: self._ouvrir(Path.home()),
            "open_folder": lambda: self._open_folder(intent.args.get("name", "")),
            "create_folder": lambda: self._create_folder(intent.args.get("name", "")),
            "search": lambda: self._search(intent.args.get("query", "")),
        }
        fn = handlers.get(intent.action)
        return fn() if fn else ActionResult.unhandled()

    @staticmethod
    def _lanceur(chemin: Path) -> None:
        """Ouvre un dossier dans l'explorateur natif (cross-platform).

        macOS/Linux : subprocess.run avec liste d'args (shell=False) — JAMAIS
        os.system (sink d'injection). Le chemin est passe comme argv, pas
        interpole dans une ligne de commande shell.
        """
        if deps.IS_WINDOWS:
            os.startfile(str(chemin))  # type: ignore[attr-defined]
        elif deps.IS_MAC:
            subprocess.run(["open", str(chemin)], check=False, shell=False)
        else:
            subprocess.run(["xdg-open", str(chemin)], check=False, shell=False)

    def _ouvrir(self, chemin: Path) -> ActionResult:
        if not chemin.exists():
            return ActionResult.fail(f"Dossier introuvable, {USER_NAME}.")
        self._lanceur(chemin)
        return ActionResult.ok(f"J'ouvre {chemin.name or 'le dossier'}, {USER_NAME}.")

    def _open_folder(self, name: str) -> ActionResult:
        brut = (name or "").strip()
        if not brut:
            return self._ouvrir(Path.home())
        standard = _DOSSIERS_STANDARD.get(brut.lower())
        if standard:
            cible = Path.home() / standard
            if cible.exists():
                return self._ouvrir(cible)
        # Sinon : un chemin existant fourni tel quel.
        candidat = Path(brut).expanduser()
        if candidat.is_dir():
            return self._ouvrir(candidat)
        return ActionResult.fail(f"Dossier '{name}' introuvable, {USER_NAME}.")

    def _create_folder(self, name: str) -> ActionResult:
        brut = (name or "").strip()
        # Validation : NOM SIMPLE uniquement -> pas de remontee, pas de chemin
        # absolu, pas de '~', et AUCUN separateur (interdit de creer une
        # arborescence type a/b/c ou de sortir du dossier de base).
        if (not brut or ".." in brut or os.path.isabs(brut)
                or brut.startswith("~") or "/" in brut or "\\" in brut):
            return ActionResult.fail(f"Nom de dossier invalide, {USER_NAME}.")
        base = Path.home() / "Desktop"
        if not base.exists():
            base = Path.home()
        cible = (base / brut).resolve()
        # Defense en profondeur : la cible doit rester directement sous la base.
        if cible.parent != base.resolve():
            return ActionResult.fail(f"Emplacement non autorise, {USER_NAME}.")
        cible.mkdir(parents=False, exist_ok=True)  # un seul niveau, base existe deja
        return ActionResult.ok(f"Dossier '{brut}' cree dans {base.name}, {USER_NAME}.")

    def _search(self, query: str) -> ActionResult:
        terme = (query or "").strip().lower()
        if not terme:
            return ActionResult.unhandled()
        racines = [Path.home() / d for d in ("Desktop", "Documents", "Downloads")]
        trouves = self._chercher(racines, terme, max_resultats=8)
        if not trouves:
            return ActionResult.fail(f"Aucun fichier ne contient '{query}', {USER_NAME}.")
        liste = ", ".join(p.name for p in trouves)
        return ActionResult.ok(
            f"J'ai trouve : {liste}.", chemins=[str(p) for p in trouves]
        )

    @staticmethod
    def _chercher(racines: list[Path], terme: str, max_resultats: int) -> list[Path]:
        """Cherche les fichiers contenant `terme` (profondeur <= 3)."""
        resultats: list[Path] = []
        for racine in racines:
            if not racine.is_dir():
                continue
            base_prof = len(racine.parts)
            for chemin in racine.rglob("*"):
                if len(chemin.parts) - base_prof > 3:
                    continue
                if chemin.is_file() and terme in chemin.name.lower():
                    resultats.append(chemin)
                    if len(resultats) >= max_resultats:
                        return resultats
        return resultats
