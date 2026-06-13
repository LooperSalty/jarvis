"""Stockage securise des secrets de Jarvis via le trousseau systeme (keyring).

Sur Windows, keyring utilise le Credential Manager natif ; sur macOS, le
Keychain ; sur Linux, le Secret Service (GNOME/KWallet). Quand aucun backend
fonctionnel n'est disponible, on retombe proprement sur les variables
d'environnement (lecture seule).

Objectif : sortir les cles API (GEMINI_API_KEY, GROQ_API_KEY...) du fichier
.env en clair. Au demarrage, charger_dans_environ() injecte dans os.environ les
secrets trouves dans le trousseau pour que le reste de main2.py continue de les
lire via os.environ sans modification.

Aucune fonction de ce module ne propage d'exception : un trousseau casse ou
indisponible ne doit jamais tuer main2.py. Tout echec keyring degrade vers le
fallback variables d'environnement.
"""

from __future__ import annotations

import os

# Nom de service unique sous lequel tous les secrets Jarvis sont regroupes
# dans le trousseau systeme.
SERVICE = "jarvis"

# Placeholders consideres comme "pas de vraie valeur" (memes conventions que
# _cle_valide cote main2.py). Une cle valant l'un d'eux est traitee comme vide.
_PLACEHOLDERS = frozenset(
    {
        "",
        "VOTRE_API",
        "VOTRE_CLE_ICI",
        "VOTRE_CLE",
        "VOTRE_TOKEN",
        "CHANGEME",
    }
)

# Cache du resultat de keyring_disponible (la sonde backend est couteuse).
_dispo_cache: bool | None = None


def _import_keyring():
    """Importe keyring de facon paresseuse. Retourne le module ou None.

    Jamais d'exception : si keyring n'est pas installe -> None.
    """
    try:
        import keyring  # import paresseux : evite le cout au demarrage si inutilise

        return keyring
    except Exception:
        return None


def _est_placeholder(valeur: str | None) -> bool:
    """True si la valeur est vide ou egale a un placeholder connu."""
    if valeur is None:
        return True
    return valeur.strip() in _PLACEHOLDERS


def keyring_disponible() -> bool:
    """True si keyring est importable ET adosse a un backend reellement fonctionnel.

    Ecarte explicitement le backend fail/null (keyring.backends.fail.Keyring)
    et verifie qu'un get_password de sonde ne leve pas. Resultat memoise.
    Jamais d'exception.
    """
    global _dispo_cache
    if _dispo_cache is not None:
        return _dispo_cache

    _dispo_cache = False
    keyring = _import_keyring()
    if keyring is None:
        return False

    try:
        backend = keyring.get_keyring()
        if backend is None:
            return False

        # Rejette le backend fail (leve toujours) si la classe est importable.
        try:
            from keyring.backends import fail as _fail

            if isinstance(backend, _fail.Keyring):
                return False
        except Exception:
            # Module fail absent : on ne peut pas tester par isinstance, on
            # se rabat sur le test fonctionnel ci-dessous.
            pass

        # Rejette aussi les backends null/chainer vides via une sonde reelle :
        # un get_password sur une cle improbable ne doit pas lever.
        keyring.get_password(SERVICE, "__sonde_disponibilite__")
        _dispo_cache = True
    except Exception:
        _dispo_cache = False
    return _dispo_cache


def obtenir(nom: str) -> str | None:
    """Retourne la valeur du secret `nom`.

    Lit le trousseau si disponible, sinon retombe sur os.environ.get(nom).
    Retourne None si introuvable. Jamais d'exception.
    """
    try:
        if not nom:
            return None
        if keyring_disponible():
            keyring = _import_keyring()
            if keyring is not None:
                valeur = keyring.get_password(SERVICE, nom)
                if valeur is not None:
                    return valeur
        # Fallback environnement (couvre aussi le cas valeur keyring absente).
        return os.environ.get(nom)
    except Exception as e:
        print(f"[SECRETS] Lecture '{nom}' impossible ({e})")
        return os.environ.get(nom)


def definir(nom: str, valeur: str) -> bool:
    """Stocke `valeur` sous `nom` dans le trousseau.

    Retourne True si ecrit, False si keyring indisponible ou en cas d'echec.
    Ne touche jamais a os.environ. Jamais d'exception.
    """
    try:
        if not nom:
            return False
        if not keyring_disponible():
            return False
        keyring = _import_keyring()
        if keyring is None:
            return False
        keyring.set_password(SERVICE, nom, valeur)
        return True
    except Exception as e:
        print(f"[SECRETS] Ecriture '{nom}' impossible ({e})")
        return False


def supprimer(nom: str) -> bool:
    """Supprime le secret `nom` du trousseau.

    Retourne True si supprime, False si keyring indisponible, secret absent
    ou echec. Jamais d'exception.
    """
    try:
        if not nom:
            return False
        if not keyring_disponible():
            return False
        keyring = _import_keyring()
        if keyring is None:
            return False
        keyring.delete_password(SERVICE, nom)
        return True
    except Exception as e:
        # delete_password leve PasswordDeleteError si le secret n'existe pas :
        # ce n'est pas une vraie erreur, on retourne juste False.
        print(f"[SECRETS] Suppression '{nom}' impossible ({e})")
        return False


def charger_dans_environ(noms: list[str]) -> int:
    """Injecte dans os.environ les secrets du trousseau manquants/placeholder.

    Pour chaque nom : si os.environ ne contient pas de vraie valeur (absent ou
    placeholder) mais que le trousseau en a une, fait os.environ[nom]=valeur.
    A appeler AU DEMARRAGE de main2 AVANT la lecture des cles. Retourne le
    nombre de secrets effectivement charges. Jamais d'exception.
    """
    charges = 0
    try:
        if not noms or not keyring_disponible():
            return 0
        keyring = _import_keyring()
        if keyring is None:
            return 0
        for nom in noms:
            try:
                if not nom:
                    continue
                # Deja une vraie valeur dans l'environnement -> on ne touche pas.
                if not _est_placeholder(os.environ.get(nom)):
                    continue
                valeur = keyring.get_password(SERVICE, nom)
                if _est_placeholder(valeur):
                    continue
                os.environ[nom] = valeur
                charges += 1
            except Exception as e:
                print(f"[SECRETS] Chargement '{nom}' ignore ({e})")
        return charges
    except Exception as e:
        print(f"[SECRETS] Chargement environnement impossible ({e})")
        return charges


def migrer_env_vers_keyring(noms: list[str]) -> dict:
    """Copie vers le trousseau les secrets actuellement dans os.environ.

    Pour chaque nom present dans os.environ avec une vraie valeur (non vide,
    non placeholder), tente un definir(nom, valeur). Retourne un dict
    {nom: bool} indiquant le succes de chaque migration. Les noms absents ou
    en placeholder sont ignores (pas de cle dans le resultat). Jamais
    d'exception.
    """
    resultats: dict[str, bool] = {}
    try:
        if not noms:
            return resultats
        for nom in noms:
            try:
                if not nom:
                    continue
                valeur = os.environ.get(nom)
                if _est_placeholder(valeur):
                    continue
                resultats[nom] = definir(nom, valeur)
            except Exception as e:
                print(f"[SECRETS] Migration '{nom}' impossible ({e})")
                resultats[nom] = False
        return resultats
    except Exception as e:
        print(f"[SECRETS] Migration impossible ({e})")
        return resultats
