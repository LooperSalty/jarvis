"""Tests voix : backend STT et detection texte du mot-cle.

- voice_stt.backend() vaut "google" tant que JARVIS_STT_LOCAL n'est pas active
  (et faster-whisper absent en environnement de test).
- wake_word.mot_present : detection robuste (accents, casse, variantes) et
  gestion des entrees None/invalides.

Les fixtures `voice_stt` / `wake_word` (conftest) remettent a zero les caches
module-level et desactivent les flags d'env.
"""

from __future__ import annotations


# ============================================================
# voice_stt.backend()
# ============================================================

def test_backend_google_par_defaut(voice_stt):
    """Sans flag JARVIS_STT_LOCAL, le backend est 'google'."""
    assert voice_stt.backend() == "google"


def test_disponible_local_false_sans_flag(voice_stt):
    """disponible_local() est False tant que le flag local n'est pas pose."""
    assert voice_stt.disponible_local() is False


def test_backend_google_meme_avec_flag_sans_lib(voice_stt, monkeypatch):
    """Flag actif mais faster-whisper absent -> repli 'google' (pas de crash)."""
    monkeypatch.setenv("JARVIS_STT_LOCAL", "1")
    # On force l'indisponibilite du modele (simule lib absente) pour rendre le
    # test DETERMINISTE, que faster-whisper soit installe ou non dans l'env.
    monkeypatch.setattr(voice_stt, "_charger_modele", lambda: None)
    assert voice_stt.backend() == "google"


def test_transcrire_google_delegue(voice_stt):
    """transcrire en backend google delegue a recognizer.recognize_google."""
    class _FauxRecognizer:
        def recognize_google(self, audio, language="fr-FR"):
            return "  bonjour jarvis  "

    texte = voice_stt.transcrire(_FauxRecognizer(), object(), language="fr-FR")
    assert texte == "bonjour jarvis"


def test_transcrire_google_erreur_renvoie_vide(voice_stt):
    """Une erreur de reconnaissance renvoie "" (jamais d'exception)."""
    class _RecognizerKO:
        def recognize_google(self, audio, language="fr-FR"):
            raise RuntimeError("UnknownValueError")

    assert voice_stt.transcrire(_RecognizerKO(), object()) == ""


# ============================================================
# wake_word.mot_present
# ============================================================

def test_mot_present_basique(wake_word):
    """Detecte 'jarvis' dans une phrase simple, insensible a la casse."""
    assert wake_word.mot_present("eh jarvis allume la lumiere") is True
    assert wake_word.mot_present("EH JARVIS") is True


def test_mot_present_accents(wake_word):
    """La detection ignore les accents (normalisation NFD)."""
    # "jârvis" / "Jàrvis" doivent matcher la variante "jarvis".
    assert wake_word.mot_present("eh jârvis") is True
    assert wake_word.mot_present("Jàrvis tu m'entends") is True


def test_mot_present_variantes(wake_word):
    """Quelques variantes phonetiques sont tolerees."""
    assert wake_word.mot_present("jarviss tu es la") is True
    assert wake_word.mot_present("djarvis") is True
    assert wake_word.mot_present("jervis") is True


def test_mot_absent(wake_word):
    """Un texte sans le mot-cle renvoie False."""
    assert wake_word.mot_present("bonjour comment vas-tu") is False
    assert wake_word.mot_present("") is False


def test_mot_present_entree_none(wake_word):
    """Une entree None (ou non-chaine) ne leve pas et renvoie False."""
    assert wake_word.mot_present(None) is False
    assert wake_word.mot_present(12345) is False


def test_disponible_false_sans_flag(wake_word):
    """disponible() est False tant que JARVIS_WAKE_LOCAL n'est pas active."""
    assert wake_word.disponible() is False


def test_creer_detecteur_none_sans_flag(wake_word):
    """creer_detecteur() renvoie None sans flag local actif."""
    assert wake_word.creer_detecteur() is None
