"""Barge-in : interruption du TTS quand l'utilisateur se met a parler.

Pendant que Jarvis parle (TTS), on surveille le micro en parallele. Si l'energie
sonore (RMS) depasse un seuil pendant plusieurs frames consecutifs, on considere
que l'utilisateur prend la parole et on declenche le rappel `on_parole` UNE fois
(cote main2 : `STOP_PARLER = True`), puis le moniteur s'arrete.

Reutilise le pattern pyaudio + audioop.rms deja present dans `monitor_claps`
(main2.py) : flux d'entree int16, lecture par buffers, calcul RMS.

Opt-in strict : ce module ne fait RIEN tant que main2 ne l'active pas derriere
`JARVIS_BARGE_IN=1`. `disponible()` permet de verifier que pyaudio est present.
Tout est encapsule dans try/except : si pyaudio echoue, le moniteur est un no-op
et ne tue jamais le process appelant.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional


def disponible() -> bool:
    """Indique si pyaudio est importable (pre-requis du barge-in audio).

    Returns:
        True si `pyaudio` peut etre importe, sinon False. Ne leve jamais.
    """
    try:
        import pyaudio  # noqa: F401  (import paresseux : juste un test)

        return True
    except Exception:
        return False


# Parametres du flux audio (alignes sur monitor_claps / format int16 mono).
_FORMAT_LARGEUR = 2          # octets par echantillon (int16)
_CANAUX = 1                  # mono
_TAUX = 16000                # 16 kHz (suffisant pour de la detection d'energie)
_TAILLE_BUFFER = 1024        # ~64 ms a 16 kHz


class MoniteurBargeIn:
    """Surveille le micro et appelle `on_parole` quand l'utilisateur parle.

    Concu pour tourner pendant le TTS : un thread daemon ouvre un flux pyaudio
    en entree, calcule le RMS de chaque buffer, et apres `frames_min` frames
    consecutives au-dessus de `seuil_rms`, declenche `on_parole()` UNE seule fois
    puis s'arrete proprement.

    Robustesse :
    - Si pyaudio est absent ou que l'ouverture du flux echoue, c'est un no-op
      (aucune exception ne remonte).
    - Le rappel `on_parole` est lui-meme protege par try/except.
    """

    def __init__(
        self,
        on_parole: Callable[[], None],
        seuil_rms: int = 1200,
        frames_min: int = 3,
    ) -> None:
        """Initialise le moniteur (sans demarrer le flux).

        Args:
            on_parole: Callable synchrone appele une fois quand l'utilisateur
                parle (typiquement : mettre `STOP_PARLER = True` cote main2).
            seuil_rms: Seuil d'energie RMS au-dela duquel un frame compte comme
                "parole" (defaut 1200).
            frames_min: Nombre de frames consecutifs au-dessus du seuil requis
                pour declencher (defaut 3 ; filtre les bruits ponctuels).
        """
        self._on_parole = on_parole
        self._seuil_rms = int(seuil_rms)
        self._frames_min = max(1, int(frames_min))

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._declenche = threading.Event()  # garantit l'appel unique

    def demarrer(self) -> None:
        """Lance la surveillance dans un thread daemon (no-op si deja lance)."""
        try:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._declenche.clear()
            self._thread = threading.Thread(
                target=self._boucle, name="barge-in", daemon=True
            )
            self._thread.start()
        except Exception as exc:
            # Aucune exception ne doit remonter cote appelant.
            print(f"[BARGE-IN] Impossible de demarrer : {exc}")

    def arreter(self) -> None:
        """Demande l'arret et attend la fin du thread (ferme le flux proprement)."""
        try:
            self._stop.set()
            thread = self._thread
            if thread is not None and thread.is_alive():
                # Le flux se ferme dans _boucle ; on attend brievement.
                thread.join(timeout=2.0)
        except Exception as exc:
            print(f"[BARGE-IN] Erreur a l'arret : {exc}")
        finally:
            self._thread = None

    def _declencher(self) -> None:
        """Appelle `on_parole` une seule fois (idempotent, protege)."""
        if self._declenche.is_set():
            return
        self._declenche.set()
        try:
            if callable(self._on_parole):
                self._on_parole()
        except Exception as exc:
            print(f"[BARGE-IN] Erreur dans on_parole : {exc}")

    def _boucle(self) -> None:
        """Boucle de lecture micro + detection RMS (thread daemon).

        Reproduit le pattern de `monitor_claps` : flux pyaudio int16, lecture
        par buffers, `audioop.rms`. Ferme toujours le flux a la sortie.
        """
        pa = None
        stream = None
        try:
            import audioop
            import pyaudio

            pa = pyaudio.PyAudio()
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=_CANAUX,
                rate=_TAUX,
                input=True,
                frames_per_buffer=_TAILLE_BUFFER,
            )

            frames_au_dessus = 0
            while not self._stop.is_set():
                try:
                    data = stream.read(_TAILLE_BUFFER, exception_on_overflow=False)
                    rms = audioop.rms(data, _FORMAT_LARGEUR)

                    if rms > self._seuil_rms:
                        frames_au_dessus += 1
                        if frames_au_dessus >= self._frames_min:
                            self._declencher()
                            break  # mission accomplie : on s'arrete
                    else:
                        frames_au_dessus = 0
                except Exception:
                    # Lecture ratee (micro occupe/debranche) : on temporise sans
                    # bloquer indefiniment, et on respecte la demande d'arret.
                    if self._stop.wait(0.1):
                        break
                    continue
        except Exception as exc:
            # pyaudio absent ou ouverture du flux impossible : no-op.
            print(f"[BARGE-IN] Surveillance indisponible : {exc}")
        finally:
            # Fermeture propre du flux et de pyaudio, quoi qu'il arrive.
            try:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
            except Exception:
                pass
            try:
                if pa is not None:
                    pa.terminate()
            except Exception:
                pass
