"""Detection du mot-cle d'activation ("jarvis") — local optionnel via openWakeWord.

Deux niveaux de detection :

1. **Detection texte** (`mot_present`) : repli universel, toujours disponible.
   Cherche "jarvis" (et variantes phonetiques) dans un texte deja transcrit,
   insensible a la casse ET aux accents (normalisation Unicode NFD).

2. **Detection audio locale** (`creer_detecteur`) : pre-gate openWakeWord sur
   le flux micro brut, active uniquement si `JARVIS_WAKE_LOCAL=1` et que la lib
   openwakeword + un modele sont chargeables. Permet de declencher l'ecoute sans
   passer par une transcription cloud.

Opt-in strict : sans `JARVIS_WAKE_LOCAL=1`, `disponible()` renvoie False et
`creer_detecteur()` renvoie None — le comportement reste identique a aujourd'hui.

Import openWakeWord paresseux dans try/except : ce module s'importe meme si la
lib lourde est absente.
"""

from __future__ import annotations

import os
import unicodedata

# Variantes textuelles tolerees du mot-cle (apres normalisation sans accents).
_VARIANTES_WAKE: tuple[str, ...] = (
    "jarvis",
    "jarviss",
    "jarvys",
    "jervis",
    "jarvi",
    "djarvis",
)

# Cache du modele openWakeWord : None = pas encore tente, False = indisponible,
# sinon True (lib + modele chargeables). Evite de re-tenter l'import a chaque appel.
_OWW_DISPONIBLE: bool | None = None


def _flag_actif() -> bool:
    """True si l'utilisateur a explicitement active le wake word local."""
    return os.getenv("JARVIS_WAKE_LOCAL", "") == "1"


def _normaliser(texte: str) -> str:
    """Minuscule + suppression des accents (NFD) pour une comparaison robuste.

    Args:
        texte: Chaine quelconque (peut contenir accents/majuscules).

    Returns:
        Texte en minuscules sans diacritiques. Renvoie "" sur entree invalide.
    """
    try:
        if not isinstance(texte, str):
            return ""
        decompose = unicodedata.normalize("NFD", texte)
        sans_accents = "".join(
            c for c in decompose if unicodedata.category(c) != "Mn"
        )
        return sans_accents.lower()
    except Exception:
        # Jamais d'exception qui remonte : on degrade silencieusement.
        return ""


def mot_present(texte: str) -> bool:
    """Detecte le mot-cle d'activation dans un texte transcrit.

    Repli universel, toujours disponible (independant des flags et libs).
    Insensible a la casse et aux accents ; tolere quelques variantes phonetiques.

    Args:
        texte: Texte transcrit a inspecter.

    Returns:
        True si une variante du mot-cle "jarvis" est presente.

    Examples:
        >>> mot_present("eh jarvis allume")
        True
        >>> mot_present("bonjour")
        False
    """
    normalise = _normaliser(texte)
    if not normalise:
        return False
    return any(variante in normalise for variante in _VARIANTES_WAKE)


def _charger_openwakeword():
    """Tente d'importer openWakeWord et de charger un modele (import paresseux).

    Returns:
        Une instance `openwakeword.Model` prete a l'emploi, ou None si la lib
        est absente ou si aucun modele n'est chargeable.
    """
    try:
        # Import paresseux : la lib est lourde et optionnelle.
        from openwakeword.model import Model  # type: ignore

        # Tentative de telechargement/verification des modeles pre-entraines.
        # Best-effort : si la fonction n'existe pas ou echoue, on continue,
        # Model() peut deja disposer des poids en cache local.
        try:
            from openwakeword import utils as _oww_utils  # type: ignore

            _oww_utils.download_models()
        except Exception:
            pass

        # Choix du modele : variable d'env optionnelle, sinon modeles par defaut.
        nom_modele = os.getenv("JARVIS_WAKE_MODEL", "").strip()
        if nom_modele:
            modele = Model(wakeword_models=[nom_modele])
        else:
            modele = Model()
        return modele
    except Exception as exc:
        print(f"[WAKE] openWakeWord indisponible : {exc}")
        return None


def disponible() -> bool:
    """Indique si la detection audio locale openWakeWord est utilisable.

    Returns:
        True uniquement si `JARVIS_WAKE_LOCAL=1` ET openwakeword importable ET
        un modele chargeable. Sinon False (le repli texte `mot_present` reste
        toujours disponible).
    """
    global _OWW_DISPONIBLE
    if not _flag_actif():
        return False
    if _OWW_DISPONIBLE is None:
        modele = _charger_openwakeword()
        _OWW_DISPONIBLE = modele is not None
    return bool(_OWW_DISPONIBLE)


class _DetecteurWake:
    """Detecteur audio openWakeWord enveloppe (frames 16 kHz mono int16).

    Encapsule un `openwakeword.Model` et expose une API minimale et robuste :
    aucune exception ne remonte, on degrade vers False en cas de probleme.
    """

    def __init__(self, modele, seuil: float) -> None:
        """Initialise le detecteur.

        Args:
            modele: Instance `openwakeword.Model` deja chargee.
            seuil: Score minimal (0..1) pour considerer le wake word detecte.
        """
        self._modele = modele
        self._seuil = float(seuil)

    def verifier_frame(self, frame_bytes: bytes) -> bool:
        """Analyse un frame audio et renvoie True si le wake word est detecte.

        Args:
            frame_bytes: Frame audio brut 16 kHz mono int16 (~80 ms recommande).

        Returns:
            True si un score de prediction depasse le seuil, sinon False.
            Jamais d'exception : renvoie False sur entree invalide ou erreur.
        """
        try:
            if not frame_bytes:
                return False

            # Conversion bytes int16 -> numpy int16 attendu par openWakeWord.
            import numpy as np  # type: ignore

            echantillons = np.frombuffer(frame_bytes, dtype=np.int16)
            if echantillons.size == 0:
                return False

            scores = self._modele.predict(echantillons)
            if not scores:
                return False

            # `predict` renvoie un dict {nom_modele: score}. On garde le max.
            meilleur = max(float(v) for v in scores.values())
            return meilleur >= self._seuil
        except Exception as exc:
            print(f"[WAKE] Erreur verifier_frame : {exc}")
            return False

    def reset(self) -> None:
        """Reinitialise l'etat interne du modele (buffers de prediction)."""
        try:
            reset_fn = getattr(self._modele, "reset", None)
            if callable(reset_fn):
                reset_fn()
        except Exception as exc:
            print(f"[WAKE] Erreur reset : {exc}")


def creer_detecteur(seuil: float = 0.5):
    """Cree un detecteur audio local openWakeWord, ou None si indisponible.

    Args:
        seuil: Score minimal (0..1) pour declencher la detection (defaut 0.5).

    Returns:
        Un objet exposant `.verifier_frame(frame_bytes) -> bool` et `.reset()`,
        ou None si `JARVIS_WAKE_LOCAL` n'est pas active / openWakeWord absent.
    """
    if not disponible():
        return None
    modele = _charger_openwakeword()
    if modele is None:
        return None
    try:
        return _DetecteurWake(modele, seuil)
    except Exception as exc:
        print(f"[WAKE] Impossible de creer le detecteur : {exc}")
        return None
