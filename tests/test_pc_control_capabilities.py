"""Tests des capacites pc_control : garde-fous (safety), compat, never-throw.

On mocke la facade `deps` (point unique) et on injecte un faux Runner (capture
l'argv) dans les capacites power/process. Les comportements testes ici sont
INDEPENDANTS de l'OS (refus de securite, validation, compat introuvable).
"""

from __future__ import annotations

import types

from jarvis_actions.pc_control.core import (
    ActionResult,
    Intention,
    SafetyPolicy,
    Status,
    DOM_LAUNCHER,
    DOM_POWER,
    DOM_PROCESS,
    DOM_VOLUME,
)
from jarvis_actions.pc_control.capabilities.base import Capability, never_throw
from jarvis_actions.pc_control.capabilities.system import PowerManager, ProcessManager
from jarvis_actions.pc_control.capabilities.io import VolumeController
from jarvis_actions.pc_control.capabilities.apps import AppLauncher


class _FakeRunner:
    """Runner factice : capture l'argv, ne touche pas l'OS."""

    def __init__(self, returncode: int = 0):
        self.calls: list[list[str]] = []
        self._rc = returncode

    def run(self, args, **kwargs):
        self.calls.append(list(args))
        return types.SimpleNamespace(returncode=self._rc, stdout="", stderr="")


# ============================================================
# never_throw : aucune exception ne remonte
# ============================================================

def test_never_throw_attrape_les_exceptions():
    class _Boom(Capability):
        domain = "x"

        @never_throw
        def handle(self, intent):
            raise RuntimeError("boom")

    res = _Boom().handle(Intention("x", "y"))
    assert isinstance(res, ActionResult)
    assert res.status is Status.FAILED  # transforme en echec propre, pas de crash


# ============================================================
# SafetyPolicy : garde-fous power / process
# ============================================================

def test_power_refuse_si_extinction_desactivee():
    runner = _FakeRunner()
    pm = PowerManager(runner, SafetyPolicy(allow_power=False))
    res = pm.handle(Intention(DOM_POWER, "shutdown"))
    assert res.status is Status.REFUSED
    assert runner.calls == []  # rien execute


def test_power_verrouillage_toujours_autorise():
    # lock n'est pas destructif : autorise meme si allow_power=False.
    runner = _FakeRunner()
    pm = PowerManager(runner, SafetyPolicy(allow_power=False))
    res = pm.handle(Intention(DOM_POWER, "lock"))
    assert res.status in (Status.OK, Status.FAILED)  # tente l'action (pas refused)


def test_process_refuse_si_kill_desactive():
    runner = _FakeRunner()
    proc = ProcessManager(runner, SafetyPolicy(allow_kill=False))
    res = proc.handle(Intention(DOM_PROCESS, "kill", {"target": "chrome"}))
    assert res.status is Status.REFUSED
    assert runner.calls == []


def test_process_kill_succes_et_echec():
    ok_runner = _FakeRunner(returncode=0)
    proc = ProcessManager(ok_runner, SafetyPolicy())
    res = proc.handle(Intention(DOM_PROCESS, "kill", {"target": "chrome"}))
    assert res.status is Status.OK
    assert ok_runner.calls  # une commande a bien ete lancee

    ko_runner = _FakeRunner(returncode=1)
    proc2 = ProcessManager(ko_runner, SafetyPolicy())
    res2 = proc2.handle(Intention(DOM_PROCESS, "kill", {"target": "chrome"}))
    assert res2.status is Status.FAILED


# ============================================================
# VolumeController : validation + clamp (mock de la facade deps)
# ============================================================

def test_volume_set_validation(monkeypatch):
    import jarvis_actions.pc_control.deps as deps
    monkeypatch.setattr(deps, "press", lambda *a, **k: True)

    vol = VolumeController()
    assert vol.handle(Intention(DOM_VOLUME, "set", {"level": "30"})).status is Status.OK
    # Non numerique -> echec explicite (pas de crash).
    assert vol.handle(Intention(DOM_VOLUME, "set", {"level": "abc"})).status is Status.FAILED
    # Hors borne -> clampe a 100 (succes, message a 100).
    res = vol.handle(Intention(DOM_VOLUME, "set", {"level": "120"}))
    assert res.status is Status.OK
    assert "100" in (res.message or "")


# ============================================================
# AppLauncher : compat introuvable + anti-injection
# ============================================================

def test_launcher_introuvable_est_unhandled():
    # 'zzzqqwww' ne matche aucun alias -> UNHANDLED (la commande file vers l'IA).
    res = AppLauncher().handle(Intention(DOM_LAUNCHER, "open_app", {"name": "zzzqqwww"}))
    assert res.status is Status.UNHANDLED


def test_launcher_anti_injection():
    res = AppLauncher().handle(Intention(DOM_LAUNCHER, "open_app", {"name": "-evil"}))
    assert res.status is Status.REFUSED


# ============================================================
# Non-regression des correctifs de revue (C1/C3/C4/H1/H3)
# ============================================================

def test_revue_c3_coupe_systeme_de_son_n_eteint_pas_le_pc():
    from jarvis_actions.pc_control.router import Router
    r = Router()
    # Ne doit PAS router vers power/shutdown (faux positif destructeur).
    it = r.route("coupe le systeme de son")
    assert it is None or it.domaine != DOM_POWER


def test_revue_h1_decolle_n_est_pas_un_coller():
    from jarvis_actions.pc_control.router import Router
    r = Router()
    assert r.route("on a decolle de l'aeroport") is None  # pas clipboard/paste


def test_revue_c1_process_kill_refuse_tiret():
    runner = _FakeRunner()
    proc = ProcessManager(runner, SafetyPolicy())
    res = proc.handle(Intention(DOM_PROCESS, "kill", {"target": "-rf"}))
    assert res.status is Status.REFUSED
    assert runner.calls == []


def test_revue_h3_resolution_alias_sous_chaine():
    proc = ProcessManager(_FakeRunner(), SafetyPolicy())
    # 'le navigateur chrome' doit resoudre vers l'alias chrome.
    assert proc._resoudre_processus("le navigateur chrome") == "chrome.exe"


def test_revue_c4_create_folder_refuse_separateurs():
    from jarvis_actions.pc_control.capabilities.system import FileManager
    from jarvis_actions.pc_control.core import DOM_FILES
    res = FileManager().handle(Intention(DOM_FILES, "create_folder", {"name": "a/b/c"}))
    assert res.status is Status.FAILED  # arborescence refusee
