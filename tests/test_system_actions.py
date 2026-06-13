"""Tests du module d'actions systeme (jarvis_actions/system_actions.py).

Coeur teste sans toucher a l'OS :
- `detecter_intention` : routeur PUR texte -> intention (le gros de la valeur).
- formatters purs (batterie/cpu/memoire/disque).
- dispatch `executer` : effets de bord (subprocess) mockes via monkeypatch, et
  IS_WINDOWS force pour un comportement deterministe quel que soit l'OS de CI.

Style aligne sur la suite : pas de marker async (le module est synchrone).
"""

from __future__ import annotations

import pytest

from jarvis_actions import system_actions as sa


# ============================================================
# detecter_intention — energie
# ============================================================

@pytest.mark.parametrize("phrase, attendu", [
    ("eteins le pc", "power_shutdown"),
    ("arrete l'ordinateur", "power_shutdown"),
    ("eteins l'ordi maintenant", "power_shutdown"),
    ("redemarre le pc", "power_restart"),
    ("reboot la machine", "power_restart"),
    ("annule l'extinction", "power_cancel"),
    ("annule le redemarrage", "power_cancel"),
    ("mets en veille", "power_sleep"),
    ("mets le pc en veille", "power_sleep"),
    ("veille prolongee", "power_hibernate"),
    ("deconnecte ma session", "power_logoff"),
])
def test_router_energie(phrase, attendu):
    intent = sa.detecter_intention(phrase)
    assert intent is not None and intent[0] == attendu


# ============================================================
# detecter_intention — fenetres
# ============================================================

@pytest.mark.parametrize("phrase, attendu", [
    ("reduis tout", "win_show_desktop"),
    ("affiche le bureau", "win_show_desktop"),
    ("minimise tout", "win_show_desktop"),
    ("agrandis la fenetre", "win_maximize"),
    ("maximise la fenetre", "win_maximize"),
    ("reduis la fenetre", "win_minimize"),
    ("change de fenetre", "win_switch"),
    ("mets la fenetre a gauche", "win_snap_left"),
    ("colle la fenetre a droite", "win_snap_right"),
])
def test_router_fenetres(phrase, attendu):
    intent = sa.detecter_intention(phrase)
    assert intent is not None and intent[0] == attendu


# ============================================================
# detecter_intention — infos systeme / presse-papier / corbeille
# ============================================================

@pytest.mark.parametrize("phrase, attendu", [
    ("niveau de batterie", "sys_battery"),
    ("combien de batterie il reste", "sys_battery"),
    ("charge du processeur", "sys_cpu"),
    ("utilisation cpu", "sys_cpu"),
    ("combien de memoire vive", "sys_memory"),
    ("la ram est a combien", "sys_memory"),
    ("espace disque restant", "sys_disk"),
    ("etat du pc", "sys_overview"),
    ("lis le presse-papier", "clipboard_read"),
    ("qu'y a-t-il dans le presse-papier", "clipboard_read"),
    ("vide la corbeille", "recycle_empty"),
])
def test_router_infos_et_outils(phrase, attendu):
    intent = sa.detecter_intention(phrase)
    assert intent is not None and intent[0] == attendu


# ============================================================
# detecter_intention — fermeture de programme
# ============================================================

@pytest.mark.parametrize("phrase, cible", [
    ("ferme chrome", "chrome"),
    ("quitte discord", "discord"),
    ("tue spotify", "spotify"),
    ("ferme l'appli steam", "steam"),
])
def test_router_process_kill(phrase, cible):
    intent = sa.detecter_intention(phrase)
    assert intent is not None
    assert intent[0] == "process_kill"
    assert intent[1] == cible


# ============================================================
# detecter_intention — non-collisions (laisse pc_actions/meross gerer)
# ============================================================

@pytest.mark.parametrize("phrase", [
    "ferme cette fenetre",
    "ferme la fenetre",
    "ferme la session",
    "ouvre chrome",
    "eteins la lumiere",
    "eteins tout",          # ambigu domotique : ne doit PAS declencher l'arret PC
    "monte le volume",
    "",
])
def test_router_non_reconnu(phrase):
    assert sa.detecter_intention(phrase) is None


# ============================================================
# Formatters purs
# ============================================================

def test_format_batterie_absente():
    msg = sa._format_batterie(None, None)
    assert "poste fixe" in msg


def test_format_batterie_en_charge():
    msg = sa._format_batterie(85, True)
    assert "85" in msg and "charge" in msg


def test_format_batterie_pleine():
    assert "pleine" in sa._format_batterie(100, True)


def test_format_batterie_sur_batterie():
    msg = sa._format_batterie(50, False)
    assert "50" in msg and "batterie" in msg


def test_format_cpu_arrondi():
    assert "43" in sa._format_cpu(42.6)


def test_format_memoire():
    msg = sa._format_memoire(60.0, 9.6, 16.0)
    assert "60" in msg and "16.0" in msg


def test_format_disque():
    msg = sa._format_disque(75.0, 120.0, 480.0)
    assert "120" in msg and "480" in msg and "75" in msg


# ============================================================
# Dispatch executer — effets de bord mockes
# ============================================================

class _FakeProc:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


@pytest.fixture
def capture_subprocess(monkeypatch):
    """Remplace subprocess.run par un mock qui enregistre les appels."""
    appels = []

    def _fake_run(args, **kwargs):
        appels.append(args)
        return _FakeProc(returncode=0)

    monkeypatch.setattr(sa.subprocess, "run", _fake_run)
    monkeypatch.setattr(sa, "IS_WINDOWS", True)
    monkeypatch.setattr(sa, "IS_MAC", False)
    return appels


def test_executer_non_reconnu_retourne_none():
    assert sa.executer("ouvre chrome") == (None, False)


def test_executer_annule_extinction(capture_subprocess):
    rep, ok = sa.executer("annule l'extinction")
    assert ok is True
    assert any("shutdown" in a and "/a" in a for a in capture_subprocess)


def test_executer_shutdown_programme_avec_delai(capture_subprocess):
    rep, ok = sa.executer("eteins le pc")
    assert ok is True
    assert "annule" in rep.lower()  # message invite a annuler
    cmd = capture_subprocess[0]
    assert "shutdown" in cmd and "/s" in cmd and str(sa.DELAI_ARRET_S) in cmd


def test_executer_kill_process_connu(capture_subprocess):
    rep, ok = sa.executer("ferme chrome")
    assert ok is True
    cmd = capture_subprocess[0]
    assert "taskkill" in cmd and "chrome.exe" in cmd


def test_executer_kill_process_introuvable(monkeypatch):
    monkeypatch.setattr(sa, "IS_WINDOWS", True)
    monkeypatch.setattr(sa, "IS_MAC", False)
    monkeypatch.setattr(sa.subprocess, "run", lambda args, **kw: _FakeProc(returncode=128))
    rep, ok = sa.executer("ferme spotify")
    assert ok is False
    assert "trouve" in rep.lower()


def test_executer_fenetre_sans_pyautogui(monkeypatch):
    """Sans pyautogui (CI/headless), une action fenetre degrade proprement."""
    monkeypatch.setattr(sa, "pyautogui", None)
    rep, ok = sa.executer("affiche le bureau")
    assert ok is False
    assert rep is not None


def test_executer_fenetre_avec_pyautogui(monkeypatch):
    """Avec un pyautogui mock, l'action fenetre envoie le bon raccourci."""
    appels = []

    class _FakePyAutoGui:
        @staticmethod
        def hotkey(*touches):
            appels.append(touches)

    monkeypatch.setattr(sa, "pyautogui", _FakePyAutoGui)
    rep, ok = sa.executer("change de fenetre")
    assert ok is True
    assert appels == [("alt", "tab")]


# ============================================================
# v2 : routeur — volume, parametres, bureaux virtuels, raccourcis, infos+
# ============================================================

@pytest.mark.parametrize("phrase, attendu", [
    ("mets le volume au maximum", "vol_max"),
    ("volume a fond", "vol_max"),
    ("volume au minimum", "vol_min"),
])
def test_router_volume_extremes(phrase, attendu):
    intent = sa.detecter_intention(phrase)
    assert intent is not None and intent[0] == attendu


@pytest.mark.parametrize("phrase, niveau", [
    ("mets le volume a 30", "30"),
    ("volume a 50%", "50"),
    ("baisse le volume a 20 pour cent", "20"),
    ("regle le volume sur 75", "75"),
])
def test_router_volume_precis(phrase, niveau):
    intent = sa.detecter_intention(phrase)
    assert intent is not None
    assert intent[0] == "vol_set"
    assert intent[1] == niveau


@pytest.mark.parametrize("phrase, attendu", [
    ("ouvre les parametres", "set_main"),
    ("parametres bluetooth", "set_bluetooth"),
    ("ouvre le wifi", "set_wifi"),
    ("parametres son", "set_sound"),
    ("parametres d'affichage", "set_display"),
])
def test_router_parametres(phrase, attendu):
    intent = sa.detecter_intention(phrase)
    assert intent is not None and intent[0] == attendu


@pytest.mark.parametrize("phrase, attendu", [
    ("vue des taches", "vd_taskview"),
    ("bureau suivant", "vd_next"),
    ("bureau precedent", "vd_prev"),
    ("nouveau bureau", "vd_new"),
])
def test_router_bureaux_virtuels(phrase, attendu):
    intent = sa.detecter_intention(phrase)
    assert intent is not None and intent[0] == attendu


@pytest.mark.parametrize("phrase, attendu", [
    ("nouvel onglet", "kbd_new_tab"),
    ("ferme l'onglet", "kbd_close_tab"),
    ("rouvre l'onglet", "kbd_reopen_tab"),
    ("actualise la page", "kbd_refresh"),
    ("plein ecran", "kbd_fullscreen"),
    ("recherche dans la page", "kbd_find"),
    ("zoom avant", "kbd_zoom_in"),
    ("zoom arriere", "kbd_zoom_out"),
    ("zoom normal", "kbd_zoom_reset"),
])
def test_router_raccourcis_clavier(phrase, attendu):
    intent = sa.detecter_intention(phrase)
    assert intent is not None and intent[0] == attendu


@pytest.mark.parametrize("phrase, attendu", [
    ("donne moi l'adresse ip", "sys_ip"),
    ("c'est quoi le nom du pc", "sys_hostname"),
    ("uptime", "sys_uptime"),
    ("depuis quand le pc est allume", "sys_uptime"),
])
def test_router_infos_plus(phrase, attendu):
    intent = sa.detecter_intention(phrase)
    assert intent is not None and intent[0] == attendu


def test_router_plein_ecran_vs_maximize():
    """Separation claire : 'plein ecran' -> F11 (kbd_fullscreen) ; 'agrandis/
    maximise la fenetre' -> win+up (win_maximize). Pas d'ambiguite."""
    assert sa.detecter_intention("mets la fenetre en plein ecran")[0] == "kbd_fullscreen"
    assert sa.detecter_intention("agrandis la fenetre")[0] == "win_maximize"
    assert sa.detecter_intention("maximise la fenetre")[0] == "win_maximize"


def test_router_ferme_onglet_ne_kill_pas():
    """'ferme l'onglet' -> raccourci ctrl+w, pas un kill de process 'onglet'."""
    assert sa.detecter_intention("ferme l'onglet")[0] == "kbd_close_tab"


# ============================================================
# v2 : formatter uptime + dispatch
# ============================================================

def test_format_uptime():
    # 1 jour + 2h + 3min = 1440 + 120 + 3 = 1563 minutes
    msg = sa._format_uptime(1563 * 60)
    assert "1 jour" in msg and "2 heures" in msg and "3 minutes" in msg


def test_executer_parametres_ouvre_uri(monkeypatch):
    """'ouvre le wifi' lance os.startfile avec l'URI ms-settings adequat."""
    appels = []
    monkeypatch.setattr(sa, "IS_WINDOWS", True)
    monkeypatch.setattr(sa.os, "startfile", lambda uri: appels.append(uri), raising=False)
    rep, ok = sa.executer("ouvre le wifi")
    assert ok is True
    assert appels == ["ms-settings:network-wifi"]


def test_executer_volume_precis_appuie_sur_les_touches(monkeypatch):
    """'mets le volume a 30' force a 0 (50 down) puis remonte (~15 up)."""
    presses = []

    class _FakePyAutoGui:
        @staticmethod
        def press(touche):
            presses.append(touche)

    monkeypatch.setattr(sa, "pyautogui", _FakePyAutoGui)
    rep, ok = sa.executer("mets le volume a 30")
    assert ok is True
    assert presses.count("volumedown") == 50
    assert presses.count("volumeup") == 15  # round(30/2)


def test_executer_nouvel_onglet_envoie_ctrl_t(monkeypatch):
    appels = []

    class _FakePyAutoGui:
        @staticmethod
        def hotkey(*touches):
            appels.append(touches)

    monkeypatch.setattr(sa, "pyautogui", _FakePyAutoGui)
    rep, ok = sa.executer("nouvel onglet")
    assert ok is True
    assert appels == [("ctrl", "t")]


def test_sys_hostname_repond():
    rep, ok = sa._sys_hostname()
    assert ok is True and rep
