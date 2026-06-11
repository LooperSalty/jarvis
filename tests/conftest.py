"""Fixtures pytest communes a toute la suite Jarvis.

Objectifs :
- Isoler tout chemin de persistance vers tmp_path (aucune ecriture dans le depot).
- Reinitialiser les caches module-level (token, keyring, whisper, oww, spotify)
  pour garantir l'independance des tests.

Les modules calculent certains chemins (TOKEN_PATH, PROFILE_PATH, ...) au moment
de l'import : on les redirige donc via monkeypatch.setattr sur la constante du
module concerne, plus fiable qu'une variable d'environnement.
"""

from __future__ import annotations

import importlib

import pytest


# ============================================================
# jarvis_security : token WebSocket
# ============================================================

@pytest.fixture
def securite(monkeypatch, tmp_path):
    """Module jarvis_security avec TOKEN_PATH isole et cache vide.

    Redirige TOKEN_PATH vers tmp_path, vide le cache memoire et nettoie la
    variable d'environnement JARVIS_WS_TOKEN pour partir d'un etat neutre.
    """
    mod = importlib.import_module("jarvis_security")
    monkeypatch.delenv("JARVIS_WS_TOKEN", raising=False)
    monkeypatch.setattr(mod, "TOKEN_PATH", tmp_path / "jarvis_ws_token.txt")
    monkeypatch.setattr(mod, "_token_cache", None)
    return mod


# ============================================================
# jarvis_profile : profil utilisateur
# ============================================================

@pytest.fixture
def profil(monkeypatch, tmp_path):
    """Module jarvis_profile avec PROFILE_PATH isole vers tmp_path."""
    mod = importlib.import_module("jarvis_profile")
    monkeypatch.setattr(mod, "PROFILE_PATH", tmp_path / "jarvis_profile.json")
    return mod


# ============================================================
# jarvis_actions.routines : routines programmees
# ============================================================

@pytest.fixture
def routines(monkeypatch, tmp_path):
    """Module routines avec ROUTINES_PATH isole vers tmp_path."""
    mod = importlib.import_module("jarvis_actions.routines")
    monkeypatch.setattr(mod, "ROUTINES_PATH", tmp_path / "jarvis_routines.json")
    return mod


# ============================================================
# jarvis_actions.triggers : triggers contextuels
# ============================================================

@pytest.fixture
def triggers(monkeypatch, tmp_path):
    """Module triggers avec TRIGGERS_PATH isole vers tmp_path."""
    mod = importlib.import_module("jarvis_actions.triggers")
    monkeypatch.setattr(mod, "TRIGGERS_PATH", tmp_path / "jarvis_triggers.json")
    return mod


# ============================================================
# jarvis_actions.voice_stt : caches whisper
# ============================================================

@pytest.fixture
def voice_stt(monkeypatch):
    """Module voice_stt avec caches whisper remis a zero et flag local off."""
    mod = importlib.import_module("jarvis_actions.voice_stt")
    monkeypatch.delenv("JARVIS_STT_LOCAL", raising=False)
    monkeypatch.setattr(mod, "_WHISPER_MODEL", None)
    monkeypatch.setattr(mod, "_WHISPER_TRIED", False)
    return mod


# ============================================================
# jarvis_actions.wake_word : caches openWakeWord
# ============================================================

@pytest.fixture
def wake_word(monkeypatch):
    """Module wake_word avec caches openWakeWord remis a zero et flag off."""
    mod = importlib.import_module("jarvis_actions.wake_word")
    monkeypatch.delenv("JARVIS_WAKE_LOCAL", raising=False)
    monkeypatch.setattr(mod, "_OWW_DISPONIBLE", None)
    monkeypatch.setattr(mod, "_OWW_MODELE", None)
    return mod


# ============================================================
# jarvis_actions.spotify : client memoise
# ============================================================

@pytest.fixture
def spotify(monkeypatch, tmp_path):
    """Module spotify avec client/init reinitialises et identifiants absents.

    Supprime les identifiants Spotify de l'environnement pour que disponible()
    renvoie False par defaut, et remet a zero le client memoise.
    """
    mod = importlib.import_module("jarvis_actions.spotify")
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(mod, "_CLIENT", None)
    monkeypatch.setattr(mod, "_INIT_FAILED", False)
    return mod
