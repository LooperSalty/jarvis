"""Tests des primitives PURES de `pc_control.core`.

On verifie le contrat de `ActionResult` (constructeurs + `to_legacy` + immuabilite)
et de `Intention` (immuabilite + args par defaut non partages). Aucune dependance
OS, aucun mock : ces objets sont le coeur stable de tout le controle PC.
"""

from __future__ import annotations

import dataclasses

import pytest

from jarvis_actions.pc_control.core import ActionResult, Intention, Status


# ============================================================
# ActionResult — constructeurs + to_legacy
# ============================================================

def test_unhandled_to_legacy():
    assert ActionResult.unhandled().to_legacy() == (None, False)


def test_ok_to_legacy():
    assert ActionResult.ok("x").to_legacy() == ("x", True)


def test_fail_to_legacy():
    assert ActionResult.fail("y").to_legacy() == ("y", False)


def test_refused_to_legacy():
    assert ActionResult.refused("z").to_legacy() == ("z", False)


# ============================================================
# Status associes
# ============================================================

@pytest.mark.parametrize("res, statut", [
    (ActionResult.unhandled(), Status.UNHANDLED),
    (ActionResult.ok("a"), Status.OK),
    (ActionResult.fail("b"), Status.FAILED),
    (ActionResult.refused("c"), Status.REFUSED),
])
def test_status(res, statut):
    assert res.status is statut


# ============================================================
# is_handled
# ============================================================

def test_is_handled():
    assert ActionResult.unhandled().is_handled is False
    assert ActionResult.ok("a").is_handled is True
    assert ActionResult.fail("b").is_handled is True
    assert ActionResult.refused("c").is_handled is True


# ============================================================
# Immuabilite (frozen=True)
# ============================================================

def test_action_result_frozen():
    res = ActionResult.ok("x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        res.message = "autre"  # type: ignore[misc]


def test_intention_frozen():
    intent = Intention("power", "shutdown")
    with pytest.raises(dataclasses.FrozenInstanceError):
        intent.action = "restart"  # type: ignore[misc]


# ============================================================
# data / args par defaut : NON partages entre instances
# ============================================================

def test_action_result_data_defaut_vide_et_isolee():
    a = ActionResult.unhandled()
    b = ActionResult.unhandled()
    assert a.data == {}
    assert b.data == {}
    # Defaut isole : deux instances ne partagent pas le meme dict.
    assert a.data is not b.data


def test_intention_args_defaut_vide_et_isolee():
    a = Intention("window", "list")
    b = Intention("window", "list")
    assert a.args == {}
    assert b.args == {}
    assert a.args is not b.args


# ============================================================
# data transmise via les constructeurs
# ============================================================

def test_ok_transmet_data():
    res = ActionResult.ok("ok", niveau=30)
    assert res.data == {"niveau": 30}


def test_intention_args_explicites():
    intent = Intention("volume", "set", {"level": "30"})
    assert intent.args == {"level": "30"}
