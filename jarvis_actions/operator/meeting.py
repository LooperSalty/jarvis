"""Mode reunion de l'Operator : transcription d'un fichier audio + resume, et
squelette de transcription LIVE (micro sans wake-word).

- Transcription fichier : faster-whisper local (CPU/int8), import paresseux et
  memoise, degradation propre si la dependance est absente.
- Resume : delegue a un LLM (coroutine `demander_ia`) via un prompt de
  compte-rendu (synthese + points d'action + elements de devis evoques).
- Live : thread daemon qui ecoute le micro en continu (speech_recognition) et
  alimente un transcript module-level, diffuse chunk par chunk.

Toutes les fonctions publiques sont DEFENSIVES : aucune ne leve d'exception non
geree (valeur de repli documentee). Les imports lourds/optionnels
(`faster_whisper`, `speech_recognition`) sont paresseux pour que ce module
reste toujours importable et que `disponible()` reflete la presence reelle.

Flag d'environnement :
- `JARVIS_WHISPER_MODEL` : taille du modele whisper (defaut "base").
"""

from __future__ import annotations

import importlib.util
import os
import threading
from typing import Any, Awaitable, Callable

# --- Etat module-level --------------------------------------------------------

# Etat de la session live (lu par etat(), mute par demarrer()/arreter()).
_ETAT: dict[str, Any] = {"actif": False, "transcript": ""}

# Modele whisper memoise apres le premier chargement (succes ou echec).
_WHISPER_MODEL: Any = None
_WHISPER_TRIED: bool = False
_WHISPER_LOCK = threading.Lock()


# --- Transcription fichier ----------------------------------------------------

def _charger_whisper() -> Any:
    """Charge (une seule fois) le modele faster-whisper, ou None si indisponible.

    Import paresseux : `faster_whisper` n'est importe qu'ici pour que le module
    reste importable sans la dependance. Taille via `JARVIS_WHISPER_MODEL`
    (defaut "base"), CPU + int8 (leger, sans GPU). Memoise via `_WHISPER_TRIED`.
    """
    global _WHISPER_MODEL, _WHISPER_TRIED
    if _WHISPER_TRIED:
        return _WHISPER_MODEL
    with _WHISPER_LOCK:
        if _WHISPER_TRIED:
            return _WHISPER_MODEL
        _WHISPER_TRIED = True
        try:
            from faster_whisper import WhisperModel  # type: ignore

            taille = os.environ.get("JARVIS_WHISPER_MODEL", "base") or "base"
            _WHISPER_MODEL = WhisperModel(taille, device="cpu", compute_type="int8")
        except Exception as e:  # noqa: BLE001 — degradation propre voulue
            print(f"[OPERATOR-MEETING] Whisper indisponible ({e}).")
            _WHISPER_MODEL = None
    return _WHISPER_MODEL


def disponible() -> bool:
    """True si `faster_whisper` est importable (transcription fichier possible)."""
    try:
        return importlib.util.find_spec("faster_whisper") is not None
    except Exception:
        return False


def transcrire_fichier(path: str) -> str:
    """Transcrit un fichier audio en texte. DEFENSIF : ne leve jamais.

    Renvoie "" si le fichier n'existe pas (`os.path.isfile` faux), si whisper
    est indisponible, ou a la moindre erreur. Sinon concatene le texte de tous
    les segments retournes par `model.transcribe(path)`.
    """
    try:
        if not path or not os.path.isfile(path):
            return ""
        model = _charger_whisper()
        if model is None:
            return ""
        res = model.transcribe(path)
        # faster-whisper renvoie (segments, info) ; on tolere aussi un iterable seul.
        segments = res[0] if isinstance(res, tuple) else res
        morceaux = [(getattr(s, "text", "") or "").strip() for s in segments]
        return " ".join(m for m in morceaux if m).strip()
    except Exception as e:  # noqa: BLE001
        print(f"[OPERATOR-MEETING] Transcription echouee ({e}).")
        return ""


# --- Resume LLM ---------------------------------------------------------------

def _prompt_compte_rendu(transcript: str) -> str:
    """Construit le prompt de compte-rendu de reunion a partir du transcript."""
    return (
        "Tu es l'assistant d'un artisan. Voici la transcription brute d'une "
        "reunion ou d'un appel client. Redige un compte-rendu clair et concis "
        "en francais structure en trois parties :\n"
        "1. Resume des points abordes.\n"
        "2. Points d'action (qui fait quoi, echeances).\n"
        "3. Elements de devis evoques (prestations, quantites, prix, materiaux).\n\n"
        f"Transcription :\n{transcript}"
    )


async def resumer(
    transcript: str,
    demander_ia: Callable[[str], Awaitable[str]],
) -> str:
    """Resume un transcript via le LLM. ASYNC. DEFENSIF : ne leve jamais.

    `demander_ia` est une coroutine `fn(prompt) -> str`. Renvoie "" si le
    transcript est vide ou en cas d'erreur ; sinon le compte-rendu produit par
    le LLM.
    """
    try:
        t = (transcript or "").strip()
        if not t:
            return ""
        res = await demander_ia(_prompt_compte_rendu(t))
        return res if isinstance(res, str) else str(res or "")
    except Exception as e:  # noqa: BLE001
        print(f"[OPERATOR-MEETING] Resume echoue ({e}).")
        return ""


# --- Transcription live (squelette) ------------------------------------------

def etat() -> dict[str, Any]:
    """Etat courant de la session live : {actif: bool, transcript: str}."""
    return {"actif": bool(_ETAT["actif"]), "transcript": str(_ETAT["transcript"])}


def definir_transcript(texte: str) -> None:
    """Remplace le transcript courant (ex: apres import d'un fichier audio) afin
    qu'il serve de source a une generation de devis ('fais un devis')."""
    _ETAT["transcript"] = str(texte or "")


def _boucle_capture(sr: Any, broadcast: Callable[[dict], None] | None) -> None:
    """Boucle micro (thread daemon) : ecoute en continu et alimente le transcript.

    Sans wake-word : chaque phrase reconnue est ajoutee au transcript et, si
    `broadcast` est fourni, diffusee via {action: operator_transcript, chunk}.
    Tout est protege : une erreur ponctuelle n'interrompt pas la boucle.
    """
    try:
        recognizer = sr.Recognizer()
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            while _ETAT["actif"]:
                try:
                    audio = recognizer.listen(source, timeout=5, phrase_time_limit=15)
                    chunk = recognizer.recognize_google(audio, language="fr-FR")
                except Exception:
                    continue
                if not chunk:
                    continue
                _ETAT["transcript"] = (str(_ETAT["transcript"]) + " " + chunk).strip()
                if broadcast:
                    try:
                        broadcast({"action": "operator_transcript", "chunk": chunk})
                    except Exception:
                        pass
    except Exception as e:  # noqa: BLE001
        print(f"[OPERATOR-MEETING] Capture live interrompue ({e}).")


def demarrer(broadcast: Callable[[dict], None] | None = None) -> bool:
    """Demarre la transcription live du micro (sans wake-word). DEFENSIF.

    Lazy import de `speech_recognition` ; si indisponible, ne fait rien et
    renvoie False. Sinon arme l'etat (actif=True, transcript vide), lance un
    thread daemon de capture et renvoie True.
    """
    try:
        try:
            import speech_recognition as sr  # type: ignore
        except Exception:
            return False
        _ETAT["actif"] = True
        _ETAT["transcript"] = ""
        threading.Thread(
            target=_boucle_capture, args=(sr, broadcast), daemon=True
        ).start()
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[OPERATOR-MEETING] Demarrage live echoue ({e}).")
        _ETAT["actif"] = False
        return False


def arreter() -> str:
    """Stoppe la session live (actif=False) et renvoie le transcript accumule."""
    _ETAT["actif"] = False
    return str(_ETAT["transcript"])
