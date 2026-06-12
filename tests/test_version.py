"""Tests de jarvis_version (version + check_update) et de son exposition dashboard.

Couvre : normalisation des tags, check_update avec reponse GitHub simulee
(disponible / a jour / erreur reseau), et le cache _info_maj du dashboard
(un seul appel reseau par TTL, champs version/update presents dans l'overview).

Aucun test ne fait de vrai appel reseau : urllib est monkeypatche.
"""

from __future__ import annotations

import io
import json

import pytest

import jarvis_version


# ============================================================
# _normaliser : tags -> tuples comparables
# ============================================================

@pytest.mark.parametrize(
    ("tag", "attendu"),
    [
        ("v1.2.3", (1, 2, 3)),
        ("1.2.3", (1, 2, 3)),
        ("V2.0", (2, 0)),
        # Les chiffres d'une composante sont concatenes ("3-rc1" -> 31) :
        # suffisant pour les tags vX.Y.Z simples publies par release.yml.
        ("v1.2.3-rc1", (1, 2, 31)),
        ("", (0,)),
        ("abc", (0,)),
        (None, (0,)),
    ],
)
def test_normaliser(tag, attendu):
    assert jarvis_version._normaliser(tag) == attendu


def test_normaliser_comparaison_versions():
    """La comparaison de tuples ordonne correctement les versions."""
    n = jarvis_version._normaliser
    assert n("v0.2.0") > n("v0.1.0")
    assert n("v1.0.0") > n("v0.9.9")
    assert not n("v0.1.0") > n("0.1.0")


# ============================================================
# check_update : reponses GitHub simulees
# ============================================================

class _FausseReponse(io.BytesIO):
    """Reponse urllib minimale (context manager + read)."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _patch_release(monkeypatch, tag: str, url: str = "https://exemple/rel"):
    corps = json.dumps({"tag_name": tag, "html_url": url}).encode("utf-8")
    monkeypatch.setattr(
        jarvis_version.urllib.request,
        "urlopen",
        lambda req, timeout=0: _FausseReponse(corps),
    )


def test_check_update_disponible(monkeypatch):
    """Release distante plus recente -> disponible=True + url renseignee."""
    monkeypatch.setattr(jarvis_version, "VERSION", "0.1.0")
    _patch_release(monkeypatch, "v9.9.9")
    info = jarvis_version.check_update()
    assert info["disponible"] is True
    assert info["version_distante"] == "v9.9.9"
    assert info["url"] == "https://exemple/rel"
    assert info["erreur"] is None


def test_check_update_a_jour(monkeypatch):
    """Release distante identique -> disponible=False, pas d'erreur."""
    monkeypatch.setattr(jarvis_version, "VERSION", "0.1.0")
    _patch_release(monkeypatch, "v0.1.0")
    info = jarvis_version.check_update()
    assert info["disponible"] is False
    assert info["erreur"] is None


def test_check_update_erreur_reseau(monkeypatch):
    """Erreur reseau -> jamais d'exception, disponible=False + erreur renseignee."""
    def _boom(req, timeout=0):
        raise OSError("pas de reseau")

    monkeypatch.setattr(jarvis_version.urllib.request, "urlopen", _boom)
    info = jarvis_version.check_update()
    assert info["disponible"] is False
    assert "pas de reseau" in info["erreur"]
    assert info["version_locale"] == jarvis_version.VERSION


# ============================================================
# Dashboard : _info_maj (cache) + overview
# ============================================================

@pytest.fixture
def dash(monkeypatch):
    """Module jarvis_dashboard_api avec cache de mise a jour remis a zero."""
    import jarvis_dashboard_api as mod

    monkeypatch.setattr(mod, "_UPDATE_CACHE", {"resultat": None, "expire": 0.0})
    return mod


def test_info_maj_expose_version_et_update(dash, monkeypatch):
    """_info_maj renvoie la version locale et l'etat de mise a jour."""
    monkeypatch.setattr(
        jarvis_version,
        "check_update",
        lambda timeout_s=4.0: {
            "disponible": True,
            "version_locale": "0.1.0",
            "version_distante": "v0.2.0",
            "url": "https://exemple/rel",
            "erreur": None,
        },
    )
    info = dash._info_maj()
    assert info["version"] == jarvis_version.VERSION
    assert info["update"]["disponible"] is True
    assert info["update"]["version_distante"] == "v0.2.0"
    assert info["update"]["url"] == "https://exemple/rel"


def test_info_maj_cache_un_seul_appel(dash, monkeypatch):
    """Deux appels dans le TTL ne declenchent qu'une verification reseau."""
    compteur = {"n": 0}

    def _fake_check(timeout_s=4.0):
        compteur["n"] += 1
        return {
            "disponible": False,
            "version_locale": "0.1.0",
            "version_distante": "v0.1.0",
            "url": None,
            "erreur": None,
        }

    monkeypatch.setattr(jarvis_version, "check_update", _fake_check)
    dash._info_maj()
    dash._info_maj()
    assert compteur["n"] == 1


def test_info_maj_sans_module(dash, monkeypatch):
    """jarvis_version indisponible -> champs None, jamais d'exception."""
    monkeypatch.setattr(dash, "jarvis_version", None)
    info = dash._info_maj()
    assert info == {"version": None, "update": None}
