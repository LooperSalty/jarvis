"""Tests du ROUTEUR PUR `pc_control.router.Router`.

Aucun mock, aucune dependance OS : on verifie uniquement le mapping
texte -> Intention(domaine, action[, args]) | None. C'est le filet
anti-regression de tout le controle PC (porte le corpus de
test_system_actions.py + ajouts v2 : window/list, files, launcher...).

Style aligne sur la suite : parametrize, imports a plat (jarvis_actions est
un package ; pytest.ini ajoute la racine au pythonpath).
"""

from __future__ import annotations

import pytest

from jarvis_actions.pc_control.router import Router
from jarvis_actions.pc_control.core import (
    DOM_CLIPBOARD,
    DOM_FILES,
    DOM_LAUNCHER,
    DOM_MEDIA,
    DOM_POWER,
    DOM_PROCESS,
    DOM_SCREEN,
    DOM_SETTINGS,
    DOM_SYSINFO,
    DOM_VOLUME,
    DOM_WINDOW,
)


@pytest.fixture
def r() -> Router:
    return Router()


# ============================================================
# POWER — energie (migration fidele de test_system_actions)
# ============================================================

@pytest.mark.parametrize("phrase, action", [
    ("eteins le pc", "shutdown"),
    ("arrete l'ordinateur", "shutdown"),
    ("eteins l'ordi maintenant", "shutdown"),
    ("coupe la machine", "shutdown"),
    ("redemarre le pc", "restart"),
    ("reboot la machine", "restart"),
    ("annule l'extinction", "cancel"),
    ("annule le redemarrage", "cancel"),
    ("mets en veille", "sleep"),
    ("mets le pc en veille", "sleep"),
    ("veille prolongee", "hibernate"),
    ("hibernation", "hibernate"),
    ("deconnecte ma session", "logoff"),
    ("verrouille le pc", "lock"),
    ("ferme la session", "lock"),
])
def test_power(r, phrase, action):
    intent = r.route(phrase)
    assert intent is not None
    assert intent.domaine == DOM_POWER
    assert intent.action == action


# ============================================================
# GARDES — non-collisions critiques (domotique / fenetre)
# ============================================================

@pytest.mark.parametrize("phrase", [
    "eteins la lumiere",   # domotique, PAS power
    "eteins tout",         # ambigu domotique : ne doit PAS eteindre le PC
])
def test_garde_lumiere_pas_power(r, phrase):
    assert r.route(phrase) is None


@pytest.mark.parametrize("phrase", [
    "ferme la fenetre",
    "ferme cette fenetre",
])
def test_garde_fermeture_fenetre_pas_power_ni_process(r, phrase):
    intent = r.route(phrase)
    assert intent is not None
    assert intent.domaine == DOM_WINDOW
    assert intent.action == "close_active"


# ============================================================
# WINDOW — gestion fenetres + bureaux virtuels + liste
# ============================================================

@pytest.mark.parametrize("phrase, action", [
    ("reduis tout", "show_desktop"),
    ("affiche le bureau", "show_desktop"),
    ("minimise tout", "show_desktop"),
    ("agrandis la fenetre", "maximize"),
    ("maximise la fenetre", "maximize"),
    ("reduis la fenetre", "minimize"),
    ("change de fenetre", "switch"),
    ("mets la fenetre a gauche", "snap_left"),
    ("colle la fenetre a droite", "snap_right"),
    ("liste les fenetres", "list"),
    ("vue des taches", "vd_taskview"),
    ("bureau suivant", "vd_next"),
    ("bureau precedent", "vd_prev"),
    ("nouveau bureau", "vd_new"),
])
def test_window(r, phrase, action):
    intent = r.route(phrase)
    assert intent is not None
    assert intent.domaine == DOM_WINDOW
    assert intent.action == action


# ============================================================
# SYSINFO — infos lecture seule
# ============================================================

@pytest.mark.parametrize("phrase, action", [
    ("niveau de batterie", "battery"),
    ("combien de batterie il reste", "battery"),
    ("charge du processeur", "cpu"),
    ("utilisation cpu", "cpu"),
    ("combien de memoire vive", "memory"),
    ("la ram est a combien", "memory"),
    ("espace disque restant", "disk"),
    ("etat du pc", "overview"),
    ("donne moi l'adresse ip", "ip"),
    ("c'est quoi le nom du pc", "hostname"),
    ("uptime", "uptime"),
    ("depuis quand le pc est allume", "uptime"),
])
def test_sysinfo(r, phrase, action):
    intent = r.route(phrase)
    assert intent is not None
    assert intent.domaine == DOM_SYSINFO
    assert intent.action == action


# ============================================================
# SCREEN — raccourcis navigateur/edition (ordre critique)
# ============================================================

@pytest.mark.parametrize("phrase, action", [
    ("nouvel onglet", "new_tab"),
    ("rouvre l'onglet", "reopen_tab"),   # reopen AVANT close
    ("ferme l'onglet", "close_tab"),     # close_tab AVANT process_kill
    ("actualise la page", "refresh"),
    ("mets la fenetre en plein ecran", "fullscreen"),
    ("zoom avant", "zoom_in"),
    ("zoom arriere", "zoom_out"),
    ("zoom normal", "zoom_reset"),
    ("recherche dans la page", "find"),
    ("prends une capture", "screenshot"),
])
def test_screen(r, phrase, action):
    intent = r.route(phrase)
    assert intent is not None
    assert intent.domaine == DOM_SCREEN
    assert intent.action == action


def test_screen_ferme_onglet_ne_kill_pas(r):
    """'ferme l'onglet' -> screen/close_tab, PAS process/kill d'un 'onglet'."""
    intent = r.route("ferme l'onglet")
    assert intent is not None
    assert intent.domaine == DOM_SCREEN
    assert intent.action == "close_tab"


# ============================================================
# CAPTURES — extracteurs a arguments
# ============================================================

def test_capture_volume_set(r):
    intent = r.route("mets le volume a 30")
    assert intent is not None
    assert intent.domaine == DOM_VOLUME
    assert intent.action == "set"
    assert intent.args == {"level": "30"}


def test_capture_process_kill(r):
    intent = r.route("ferme chrome")
    assert intent is not None
    assert intent.domaine == DOM_PROCESS
    assert intent.action == "kill"
    assert intent.args == {"target": "chrome"}


def test_capture_type_text_preserve_casse(r):
    """La casse du texte a taper est PRESERVEE via le texte brut."""
    intent = r.route("tape Bonjour Le Monde")
    assert intent is not None
    assert intent.domaine == DOM_SCREEN
    assert intent.action == "type_text"
    assert intent.args == {"text": "Bonjour Le Monde"}


# ============================================================
# LAUNCHER — ouverture d'apps/sites (fourre-tout, EN DERNIER)
# ============================================================

@pytest.mark.parametrize("phrase, nom", [
    ("ouvre youtube", "youtube"),
    ("ouvre chrome", "chrome"),
    ("lance spotify", "spotify"),
])
def test_launcher_open_app(r, phrase, nom):
    intent = r.route(phrase)
    assert intent is not None
    assert intent.domaine == DOM_LAUNCHER
    assert intent.action == "open_app"
    assert intent.args == {"name": nom}


# ============================================================
# MEDIA / CLIPBOARD / VOLUME relatif
# ============================================================

@pytest.mark.parametrize("phrase, domaine, action", [
    ("mets pause", DOM_MEDIA, "pause"),
    ("joue la musique", DOM_MEDIA, "play"),
    ("piste suivante", DOM_MEDIA, "next"),
    ("morceau precedent", DOM_MEDIA, "prev"),
    ("colle", DOM_CLIPBOARD, "paste"),
    ("lis le presse-papier", DOM_CLIPBOARD, "read"),
    ("monte le volume", DOM_VOLUME, "up"),
    ("baisse le volume", DOM_VOLUME, "down"),
    ("coupe le son", DOM_VOLUME, "mute"),
    ("mets le volume au maximum", DOM_VOLUME, "max"),
    ("volume au minimum", DOM_VOLUME, "min"),
])
def test_media_clipboard_volume(r, phrase, domaine, action):
    intent = r.route(phrase)
    assert intent is not None
    assert intent.domaine == domaine
    assert intent.action == action


# ============================================================
# SETTINGS — panneaux Windows + corbeille
# ============================================================

@pytest.mark.parametrize("phrase, action", [
    ("ouvre les parametres", "main"),
    ("parametres bluetooth", "bluetooth"),
    ("ouvre le wifi", "wifi"),
    ("parametres son", "sound"),
    ("parametres d'affichage", "display"),
    ("vide la corbeille", "recycle_empty"),
])
def test_settings(r, phrase, action):
    intent = r.route(phrase)
    assert intent is not None
    assert intent.domaine == DOM_SETTINGS
    assert intent.action == action


# ============================================================
# FILES — dossiers + explorateur
# ============================================================

def test_files_create_folder(r):
    intent = r.route("cree un dossier Photos")
    assert intent is not None
    assert intent.domaine == DOM_FILES
    assert intent.action == "create_folder"
    assert "Photos" in intent.args.get("name", "")


def test_files_open_folder(r):
    intent = r.route("ouvre le dossier telechargements")
    assert intent is not None
    assert intent.domaine == DOM_FILES
    assert intent.action == "open_folder"
    assert "telechargements" in intent.args.get("name", "")


def test_files_open_explorer(r):
    intent = r.route("ouvre l'explorateur")
    assert intent is not None
    assert intent.domaine == DOM_FILES
    assert intent.action == "open_explorer"


# ============================================================
# VIDE / espaces -> None
# ============================================================

@pytest.mark.parametrize("phrase", ["", "   ", "\t\n"])
def test_vide_ou_espaces(r, phrase):
    assert r.route(phrase) is None
