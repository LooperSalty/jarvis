"""Transcription vocale (STT) avec backend local optionnel.

Ce module fournit une couche d'abstraction au-dessus de la reconnaissance
vocale utilisee par `main2.py`. Par defaut il delegue a Google
(`recognizer.recognize_google`) — comportement strictement identique a
l'historique. Quand le flag `JARVIS_STT_LOCAL=1` est actif ET que
`faster-whisper` est importable et qu'un modele est chargeable, la
transcription se fait localement (hors-ligne), avec repli automatique sur
Google a la moindre erreur.

Contrat PR C :
- `backend()` -> "whisper" si STT local dispo, sinon "google".
- `transcrire(recognizer, audio, language="fr-FR")` -> texte transcrit ("" si
  rien compris). Ne leve jamais d'exception.
- `disponible_local()` -> bool.

Flags d'environnement :
- `JARVIS_STT_LOCAL=1`   -> active le backend whisper local (OPT-IN).
- `JARVIS_WHISPER_MODEL` -> taille du modele whisper (defaut "base").

Le modele whisper est charge paresseusement et memoise (un seul chargement).
Les imports lourds (`faster-whisper`, `numpy`) sont paresseux et proteges par
try/except pour que ce module reste importable meme sans ces dependances.
"""

from __future__ import annotations

import os
import tempfile
import threading
from typing import Any, Optional

# --- Etat memoise (charge une seule fois) -------------------------------------

# Modele whisper memoise apres le premier chargement reussi.
_WHISPER_MODEL: Any = None
# True une fois que la tentative de chargement a eu lieu (succes ou echec).
_WHISPER_TRIED: bool = False
# Verrou pour eviter un double chargement concurrent du modele.
_WHISPER_LOCK = threading.Lock()


def _flag_local_actif() -> bool:
    """Retourne True si le flag d'activation `JARVIS_STT_LOCAL` vaut "1"."""
    return os.getenv("JARVIS_STT_LOCAL", "").strip() == "1"


def _taille_modele() -> str:
    """Retourne la taille du modele whisper a charger (defaut "base")."""
    taille = os.getenv("JARVIS_WHISPER_MODEL", "").strip()
    return taille or "base"


def _charger_modele() -> Any:
    """Charge (une seule fois) le modele faster-whisper.

    Import paresseux : `faster_whisper` n'est importe qu'ici, pour que le
    module reste importable meme si la dependance optionnelle est absente.

    Returns:
        L'instance `WhisperModel` chargee, ou `None` si l'import ou le
        chargement echoue (dependance absente, modele introuvable, etc.).
    """
    global _WHISPER_MODEL, _WHISPER_TRIED

    # Lecture rapide hors verrou : si on a deja tente, on renvoie le resultat.
    if _WHISPER_TRIED:
        return _WHISPER_MODEL

    with _WHISPER_LOCK:
        # Re-verification a l'interieur du verrou (double-checked locking).
        if _WHISPER_TRIED:
            return _WHISPER_MODEL
        _WHISPER_TRIED = True
        try:
            # Import paresseux de la lib lourde et optionnelle.
            from faster_whisper import WhisperModel  # type: ignore

            taille = _taille_modele()
            # CPU + int8 : leger et sans dependance GPU. Suffisant pour du STT
            # vocal court. compute_type="int8" reduit l'empreinte memoire.
            _WHISPER_MODEL = WhisperModel(
                taille, device="cpu", compute_type="int8"
            )
            print(f"[STT] Modele whisper local charge : {taille}")
        except Exception as e:  # noqa: BLE001 — on veut un repli total
            # Toute erreur (import, telechargement, modele invalide) => repli
            # silencieux sur Google. On ne tue jamais main2.py.
            print(f"[STT] Whisper local indisponible ({e}). Repli sur Google.")
            _WHISPER_MODEL = None

    return _WHISPER_MODEL


def disponible_local() -> bool:
    """Indique si la transcription locale (whisper) est disponible.

    True uniquement si le flag `JARVIS_STT_LOCAL=1` est actif ET qu'un modele
    faster-whisper est chargeable. Le premier appel peut declencher le
    chargement du modele (memoise ensuite).

    Returns:
        bool: True si le backend whisper local est operationnel.
    """
    if not _flag_local_actif():
        return False
    return _charger_modele() is not None


def backend() -> str:
    """Retourne le nom du backend STT actif.

    Returns:
        str: "whisper" si la transcription locale est disponible, sinon
        "google" (comportement par defaut, identique a l'historique).
    """
    return "whisper" if disponible_local() else "google"


def _transcrire_whisper(audio: Any, language: str) -> Optional[str]:
    """Transcrit un `sr.AudioData` via faster-whisper local.

    Convertit l'audio en WAV (bytes) via `audio.get_wav_data()`, ecrit dans un
    fichier temporaire, puis lance la transcription whisper sur ce fichier.

    Args:
        audio: Objet `speech_recognition.AudioData`.
        language: Code langue (ex. "fr-FR"). Seuls les 2 premiers caracteres
            sont transmis a whisper qui attend un code ISO court ("fr").

    Returns:
        Le texte transcrit (eventuellement vide), ou `None` si une erreur
        survient (le repli Google sera alors tente par l'appelant).
    """
    modele = _charger_modele()
    if modele is None:
        return None

    # Code langue court attendu par whisper : "fr-FR" -> "fr".
    lang_court = (language or "fr").split("-")[0].lower() or None

    chemin_tmp: Optional[str] = None
    try:
        # sr.AudioData expose get_wav_data() -> bytes d'un WAV complet.
        wav_bytes = audio.get_wav_data()

        # Fichier temporaire ferme avant lecture par whisper (Windows ne permet
        # pas a deux handles d'ouvrir le meme fichier simultanement).
        with tempfile.NamedTemporaryFile(
            suffix=".wav", delete=False
        ) as f:
            f.write(wav_bytes)
            chemin_tmp = f.name

        segments, _info = modele.transcribe(
            chemin_tmp,
            language=lang_court,
            beam_size=1,
            vad_filter=True,
        )
        # `segments` est un generateur : on concatene les morceaux de texte.
        texte = "".join(seg.text for seg in segments)
        return texte.strip()
    except Exception as e:  # noqa: BLE001 — repli Google a la moindre erreur
        print(f"[STT] Erreur transcription whisper ({e}). Repli sur Google.")
        return None
    finally:
        # Nettoyage du fichier temporaire (best-effort).
        if chemin_tmp:
            try:
                os.unlink(chemin_tmp)
            except OSError:
                pass


def _transcrire_google(recognizer: Any, audio: Any, language: str) -> str:
    """Transcrit via Google (comportement historique).

    Args:
        recognizer: Instance `speech_recognition.Recognizer`.
        audio: Objet `speech_recognition.AudioData`.
        language: Code langue (ex. "fr-FR").

    Returns:
        Le texte transcrit, ou "" si rien n'a ete compris ou en cas d'erreur.
    """
    try:
        texte = recognizer.recognize_google(audio, language=language)
        return (texte or "").strip()
    except Exception as e:  # noqa: BLE001
        # UnknownValueError (rien compris) ou RequestError (reseau) -> "".
        # On evite d'importer sr juste pour typer l'exception : on ne veut
        # jamais qu'une erreur STT remonte jusqu'a main2.py.
        nom = type(e).__name__
        if nom not in ("UnknownValueError",):
            print(f"[STT] Erreur recognize_google ({nom}: {e}).")
        return ""


def transcrire(recognizer: Any, audio: Any, language: str = "fr-FR") -> str:
    """Transcrit un segment audio en texte.

    Point d'entree unique utilise par `main2.py` a la place de
    `recognizer.recognize_google(audio, ...)`.

    - Si `backend()` vaut "whisper" : transcription locale, avec repli
      automatique sur Google si whisper echoue.
    - Sinon : `recognizer.recognize_google` (comportement historique).

    Ne leve JAMAIS d'exception : retourne "" si rien n'est compris.

    Args:
        recognizer: Instance `speech_recognition.Recognizer`.
        audio: Objet `speech_recognition.AudioData` (issu de `r.listen`).
        language: Code langue (defaut "fr-FR").

    Returns:
        str: Le texte transcrit (vide si rien compris ou erreur).
    """
    if backend() == "whisper":
        texte = _transcrire_whisper(audio, language)
        if texte is not None:
            return texte
        # Repli sur Google si whisper a echoue (texte is None).

    return _transcrire_google(recognizer, audio, language)
