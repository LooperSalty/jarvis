"""Routeur des messages WebSocket du dashboard Jarvis.

Tout message client dont le champ "type" commence par "dash_" est traite ici
(voir traiter_message_dashboard, appele depuis ws_handler dans main2.py).
Les reponses sont envoyees sur le meme websocket avec un champ "action".

Cablage cote main2.py :
    import jarvis_dashboard_api
    jarvis_dashboard_api.init_api({
        "charger_memoire": charger_memoire,
        "ajouter_memoire": ajouter_memoire,
        "supprimer_memoire": supprimer_memoire,
        "user_name": lambda: USER_NAME,
        # optionnel : "obsidian_actif": lambda: OBSIDIAN is not None,
    })
    # puis dans ws_handler, avant les autres elif :
    #   if await jarvis_dashboard_api.traiter_message_dashboard(data, websocket):
    #       continue

SECURITE : les valeurs des cles API ne sont JAMAIS renvoyees au client,
uniquement des booleens "presente / absente".
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

try:
    import requests
except Exception as e:  # pragma: no cover - requests est une dep du repo
    requests = None
    print(f"[DASHBOARD] Module requests indisponible : {e}")

# --- Imports degrades : les modules peuvent manquer selon l'installation ---
try:
    from jarvis_profile import charger_profil, sauvegarder_profil
except Exception as e:
    charger_profil = None
    sauvegarder_profil = None
    print(f"[DASHBOARD] Module jarvis_profile indisponible : {e}")

try:
    from jarvis_actions import mcp_client
except Exception as e:
    mcp_client = None
    print(f"[DASHBOARD] Module mcp_client indisponible : {e}")

try:
    from jarvis_actions import skills_loader
except Exception as e:
    skills_loader = None
    print(f"[DASHBOARD] Module skills_loader indisponible : {e}")

try:
    from jarvis_actions import model_advisor_service
except Exception as e:
    model_advisor_service = None
    print(f"[DASHBOARD] Module model_advisor_service indisponible : {e}")

try:
    from jarvis_actions import memory_rag
except Exception as e:
    memory_rag = None
    print(f"[DASHBOARD] Module memory_rag indisponible : {e}")

try:
    import jarvis_security
except Exception as e:
    jarvis_security = None
    print(f"[DASHBOARD] Module jarvis_security indisponible : {e}")

try:
    from jarvis_actions import routines
except Exception as e:
    routines = None
    print(f"[DASHBOARD] Module routines indisponible : {e}")

try:
    from jarvis_actions import triggers
except Exception as e:
    triggers = None
    print(f"[DASHBOARD] Module triggers indisponible : {e}")

try:
    from jarvis_actions import operator as operator_mod
    from jarvis_actions.operator import (
        report as op_report,
        approvals as op_approvals,
        config as op_config,
    )
except Exception as e:
    operator_mod = None
    op_report = None
    op_approvals = None
    op_config = None
    print(f"[DASHBOARD] Module operator indisponible : {e}")

try:
    import jarvis_secrets
except Exception as e:
    jarvis_secrets = None
    print(f"[DASHBOARD] Module jarvis_secrets indisponible : {e}")

try:
    import jarvis_version
except Exception as e:
    jarvis_version = None
    print(f"[DASHBOARD] Module jarvis_version indisponible : {e}")

try:
    import jarvis_ui_config
except Exception as e:
    jarvis_ui_config = None
    print(f"[DASHBOARD] Module jarvis_ui_config indisponible : {e}")

try:
    from jarvis_actions import claude_bridge
except Exception as e:
    claude_bridge = None
    print(f"[DASHBOARD] Module claude_bridge indisponible : {e}")

try:
    from jarvis_actions import cc_skills
except Exception as e:
    cc_skills = None
    print(f"[DASHBOARD] Module cc_skills indisponible : {e}")

try:
    from jarvis_actions import skills_sh
except Exception as e:
    skills_sh = None
    print(f"[DASHBOARD] Module skills_sh indisponible : {e}")

try:
    from jarvis_actions import free_code
except Exception as e:
    free_code = None
    print(f"[DASHBOARD] Module free_code indisponible : {e}")

try:
    from jarvis_actions import code_chat
except Exception as e:
    code_chat = None
    print(f"[DASHBOARD] Module code_chat indisponible : {e}")

try:
    from jarvis_actions import memory_sync
except Exception as e:
    memory_sync = None
    print(f"[DASHBOARD] Module memory_sync indisponible : {e}")


# ==========================================
# CONSTANTES
# ==========================================
def _dossier_donnees() -> Path:
    """Dossier ou lire/ecrire le .env. A cote de l'exe en mode PyInstaller
    (sys._MEIPASS est temporaire et efface a la sortie : ecrire dedans perdrait
    les reglages a chaque redemarrage), sinon racine du repo. Meme pattern que
    jarvis_profile._dossier_donnees."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent  # jarvis_core/ -> racine du repo (dev)


REPO_DIR = _dossier_donnees()
ENV_PATH = REPO_DIR / ".env"

# Liste blanche des cles .env gerees par le dashboard (rien d'autre n'est accepte)
CLES_GEREES: tuple[str, ...] = (
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "XAI_API_KEY",
    "SERPAPI_API_KEY",
    "YOUTUBE_API_KEY",
    "HA_URL",
    "HA_TOKEN",
    "MEROSS_EMAIL",
    "MEROSS_PASSWORD",
    "OBSIDIAN_VAULT",
    "JARVIS_USER_NAME",
    "FORCE_OLLAMA",
    # Modele Ollama local prefere (defini via "Choisir ce modele" du dashboard).
    # main2.py le met en tete de la priorite OLLAMA_MODELS au demarrage.
    "JARVIS_OLLAMA_MODEL",
    # Flags voix avancee (opt-in, non secrets) — voir requirements-voice.txt
    "JARVIS_STT_LOCAL",
    "JARVIS_WAKE_LOCAL",
    "JARVIS_BARGE_IN",
    # Spotify (controle lecture via l'API officielle spotipy)
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_CLIENT_SECRET",
    # Messagerie : pont Telegram entrant + notifications Discord sortantes
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "DISCORD_WEBHOOK_URL",
    # OpenClaw : pont vers l'agent IA personnel local (gateway :18789).
    # Deux tokens DISTINCTS cote OpenClaw : gateway.auth.token et hooks.token.
    "OPENCLAW_URL",
    "OPENCLAW_TOKEN",
    "OPENCLAW_HOOKS_TOKEN",
    # Notion : synchronisation de la memoire vers une page Notion (section Memoire).
    # NOTION_TOKEN = secret d'integration interne ; NOTION_PAGE_ID = page partagee.
    "NOTION_TOKEN",
    "NOTION_PAGE_ID",
)

# Cles SECRETES parmi CLES_GEREES : stockees dans keyring si dispo (jamais en
# clair dans le .env). Les autres cles (URL, nom utilisateur, flags) restent
# dans le .env car non sensibles et utiles a lire en clair pour le debug.
CLES_SECRETES: frozenset[str] = frozenset({
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "XAI_API_KEY",
    "SERPAPI_API_KEY",
    "YOUTUBE_API_KEY",
    "HA_TOKEN",
    "MEROSS_PASSWORD",
    # SPOTIFY_CLIENT_ID et TELEGRAM_CHAT_ID ne sont pas des secrets (id public /
    # identifiant de chat) : ils restent en clair dans le .env.
    "SPOTIFY_CLIENT_SECRET",
    "TELEGRAM_BOT_TOKEN",
    "DISCORD_WEBHOOK_URL",
    # OPENCLAW_URL n'est pas un secret (adresse locale) ; les deux tokens oui.
    "OPENCLAW_TOKEN",
    "OPENCLAW_HOOKS_TOKEN",
    # NOTION_PAGE_ID est un identifiant (non secret) ; le token d'integration oui.
    "NOTION_TOKEN",
})

_PLACEHOLDERS = ("VOTRE_API", "VOTRE_CLE_ICI")

# Catalogue de serveurs MCP preconfigures pour ajout en 1 clic depuis le
# dashboard. Constante en dur : ces serveurs npx sont les references officielles
# du Model Context Protocol. Le champ "besoin" (optionnel) signale a l'utilisateur
# qu'un argument est a editer (chemin, cle...) avant l'ajout. Le frontend
# reutilise le handler dash_mcp_add existant (name, command, args).
CATALOGUE_MCP: tuple[dict[str, Any], ...] = (
    {
        "nom": "filesystem",
        "description": "Acces lecture/ecriture aux fichiers d'un dossier autorise.",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:/Users"],
        "besoin": "Remplace le dernier argument par le dossier a exposer.",
    },
    {
        "nom": "github",
        "description": "Lecture/ecriture de depots, issues et PR GitHub.",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "besoin": "Definis GITHUB_PERSONAL_ACCESS_TOKEN dans l'environnement.",
    },
    {
        "nom": "brave-search",
        "description": "Recherche web via l'API Brave Search.",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-brave-search"],
        "besoin": "Definis BRAVE_API_KEY dans l'environnement.",
    },
    {
        "nom": "memory",
        "description": "Memoire persistante a base de graphe de connaissances.",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
    },
    {
        "nom": "sequential-thinking",
        "description": "Raisonnement etape par etape structure pour les taches complexes.",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
    },
    {
        "nom": "fetch",
        "description": "Recupere et convertit des pages web en texte exploitable.",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-fetch"],
    },
    {
        "nom": "time",
        "description": "Heure courante et conversions de fuseaux horaires.",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-time"],
    },
)

# Meme defaut/surcharge que main2.py et model_advisor_service.py.
# "127.0.0.1" et PAS "localhost" : sous Windows, "localhost" resout d'abord en
# IPv6 (::1) ou Ollama N'ECOUTE PAS (il bind l'IPv4 seul). Le repli IPv6->IPv4
# de la stack reseau prend ~2 s, ce qui DEPASSE le timeout court -> le dashboard
# croyait alors "Ollama ne fonctionne pas" alors que le serveur tournait et que
# le reste de Jarvis (qui tape 127.0.0.1) l'atteignait sans probleme.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_TAGS_URL = f"{OLLAMA_URL}/api/tags"
OLLAMA_TIMEOUT_S = 3.0

# Graphe memoire
MAX_LIENS_TRANSVERSAUX = 60
LONGUEUR_MOT_SIGNIFICATIF = 5
LONGUEUR_LABEL_MAX = 40

# Mots francais trop courants pour creer des liens pertinents (sans accents)
_STOPWORDS = {
    "alors", "aussi", "autre", "autres", "avant", "avoir", "celle", "celles",
    "celui", "cette", "chaque", "comme", "depuis", "encore", "entre", "etais",
    "etait", "faire", "leurs", "moins", "notre", "petit", "petite", "quand",
    "quelle", "quelles", "selon", "toujours", "toute", "toutes", "votre",
}

# ==========================================
# ETAT MODULE
# ==========================================
# Callables injectes par main2.py via init_api()
_CTX: dict[str, Any] = {}
# Passe a True apres toute modification du .env (les clients IA sont
# initialises au demarrage de main2, un redemarrage est donc necessaire)
_RESTART_REQUIRED = False


def init_api(contexte: dict) -> None:
    """Initialise le routeur avec les callables injectes par main2.

    Cles attendues : charger_memoire, ajouter_memoire, supprimer_memoire,
    user_name. Optionnel : obsidian_actif, lan_ip (callable ou str, sert
    a construire l'URL d'appairage mobile ; defaut "127.0.0.1").
    """
    if not isinstance(contexte, dict):
        print("[DASHBOARD] init_api : contexte invalide (dict attendu)")
        return
    _CTX.clear()
    _CTX.update(contexte)
    print(f"[DASHBOARD] API dashboard initialisee ({len(_CTX)} entrees de contexte).")


# ==========================================
# HELPERS CONTEXTE
# ==========================================
def _appel_ctx(nom: str, *args: Any, defaut: Any = None) -> Any:
    """Appelle un callable du contexte. Retourne defaut si absent ou en echec."""
    fn = _CTX.get(nom)
    if not callable(fn):
        return defaut
    try:
        return fn(*args)
    except Exception as e:
        print(f"[DASHBOARD] Callable contexte '{nom}' en echec : {e}")
        return defaut


def _nom_utilisateur() -> str:
    """Nom de l'utilisateur via le contexte, sinon l'env, sinon 'Monsieur'."""
    nom = _appel_ctx("user_name")
    if isinstance(nom, str) and nom.strip():
        return nom.strip()
    return (os.environ.get("JARVIS_USER_NAME") or "").strip() or "Monsieur"


def _lan_ip() -> str:
    """IP LAN du PC pour l'URL d'appairage. Lit _CTX['lan_ip'] (callable ou valeur).

    Defaut "127.0.0.1" si le contexte ne fournit rien (main2 l'injecte).
    """
    valeur = _CTX.get("lan_ip")
    if callable(valeur):
        try:
            valeur = valeur()
        except Exception as e:
            print(f"[DASHBOARD] Lecture lan_ip echouee : {e}")
            valeur = None
    if isinstance(valeur, str) and valeur.strip():
        return valeur.strip()
    return "127.0.0.1"


def _charger_profil_sur() -> dict:
    """Charge le profil utilisateur sans jamais lever d'exception."""
    if charger_profil is None:
        return {}
    try:
        profil = charger_profil()
        return profil if isinstance(profil, dict) else {}
    except Exception as e:
        print(f"[DASHBOARD] Lecture profil echouee : {e}")
        return {}


async def _en_executor(fn: Any, *args: Any) -> Any:
    """Execute un appel bloquant dans un thread pour ne pas figer l'event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: fn(*args))


async def _attendre_si_besoin(resultat: Any) -> Any:
    """Await le resultat s'il est awaitable (API sync ou async indifferente)."""
    if inspect.isawaitable(resultat):
        return await resultat
    return resultat


# ==========================================
# GESTION .ENV
# ==========================================
def _valeur_presente(valeur: str) -> bool:
    """Une valeur est presente si non vide et differente des placeholders."""
    v = (valeur or "").strip().strip('"').strip("'")
    return bool(v) and v not in _PLACEHOLDERS and not v.startswith("VOTRE_")


def _parser_env() -> dict[str, str]:
    """Parse le .env en dict {CLE: valeur brute}. Ignore commentaires et lignes vides."""
    valeurs: dict[str, str] = {}
    if not ENV_PATH.exists():
        return valeurs
    try:
        for ligne in ENV_PATH.read_text(encoding="utf-8").splitlines():
            propre = ligne.strip()
            if not propre or propre.startswith("#") or "=" not in propre:
                continue
            cle, _, valeur = propre.partition("=")
            valeurs[cle.strip()] = valeur.strip()
    except Exception as e:
        print(f"[DASHBOARD] Lecture .env echouee : {e}")
    return valeurs


def _valeur_brute_cle(cle: str, env_fichier: dict[str, str]) -> str:
    """Valeur brute d'une cle : os.environ -> keyring -> .env. Jamais renvoyee au client.

    L'ordre suit la priorite reelle de chargement (la session prime, puis le
    coffre keyring, puis le fichier .env en dernier recours).
    """
    val = os.environ.get(cle, "")
    if _valeur_presente(val):
        return val
    if jarvis_secrets is not None:
        try:
            depuis_keyring = jarvis_secrets.obtenir(cle)
        except Exception as e:
            print(f"[DASHBOARD] Lecture keyring '{cle}' echouee : {e}")
            depuis_keyring = None
        if isinstance(depuis_keyring, str) and _valeur_presente(depuis_keyring):
            return depuis_keyring
    return env_fichier.get(cle, "")


def lire_cles_env() -> dict[str, bool]:
    """Etat presente/absente de chaque cle geree. Ne renvoie JAMAIS les valeurs.

    Une cle est consideree presente si os.environ, keyring ou le .env la
    contient avec une valeur non placeholder.
    """
    valeurs = _parser_env()
    presentes: dict[str, bool] = {}
    for cle in CLES_GEREES:
        presentes[cle] = _valeur_presente(_valeur_brute_cle(cle, valeurs))
    return presentes


def _valider_updates_env(updates: Any) -> tuple[dict[str, str] | None, str | None]:
    """Valide les updates : liste blanche + pas de saut de ligne. (dict, None) ou (None, erreur)."""
    if not isinstance(updates, dict) or not updates:
        return None, "Aucune mise a jour fournie"
    propres: dict[str, str] = {}
    for cle, valeur in updates.items():
        cle = str(cle).strip()
        if cle not in CLES_GEREES:
            return None, f"Cle non geree : {cle}"
        valeur = str(valeur if valeur is not None else "")
        if "\n" in valeur or "\r" in valeur:
            return None, f"Valeur invalide pour {cle} (saut de ligne interdit)"
        propres[cle] = valeur.strip()
    return propres, None


def _fusionner_lignes_env(lignes: list[str], updates: dict[str, str]) -> list[str]:
    """Remplace les lignes CLE=... concernees, preserve le reste, ajoute les nouvelles."""
    restantes = dict(updates)
    resultat: list[str] = []
    for ligne in lignes:
        propre = ligne.strip()
        if propre and not propre.startswith("#") and "=" in propre:
            cle = propre.partition("=")[0].strip()
            if cle in restantes:
                resultat.append(f"{cle}={restantes.pop(cle)}")
                continue
        resultat.append(ligne)
    for cle, valeur in restantes.items():
        resultat.append(f"{cle}={valeur}")
    return resultat


def _purger_cles_env(cles) -> None:
    """Retire definitivement des cles du fichier .env (ecriture atomique).

    Appele apres avoir place un secret dans keyring : sinon la valeur en clair
    resterait dans .env et serait rechargee (et prioritaire) par load_dotenv au
    prochain demarrage, annulant le benefice du coffre securise.
    """
    cles = {str(c).strip() for c in cles if str(c).strip()}
    if not cles or not ENV_PATH.exists():
        return
    try:
        lignes = ENV_PATH.read_text(encoding="utf-8").splitlines()
        gardees = []
        retiree = False
        for ligne in lignes:
            propre = ligne.strip()
            if propre and not propre.startswith("#") and "=" in propre:
                if propre.partition("=")[0].strip() in cles:
                    retiree = True
                    continue
            gardees.append(ligne)
        if not retiree:
            return
        tmp = ENV_PATH.with_name(ENV_PATH.name + ".tmp")
        tmp.write_text("\n".join(gardees) + "\n", encoding="utf-8")
        os.replace(tmp, ENV_PATH)
        _restreindre_env()
    except Exception as e:
        print(f"[DASHBOARD] Purge .env echouee : {e}")


def _restreindre_env() -> None:
    """ACL restreinte sur le .env apres ecriture (peut contenir des secrets
    en clair quand keyring est indisponible). Best-effort, jamais d'exception."""
    if jarvis_security is not None:
        try:
            jarvis_security.restreindre_acces_fichier(ENV_PATH)
        except Exception as e:
            print(f"[DASHBOARD] Restriction ACL du .env echouee : {e}")


def _keyring_disponible() -> bool:
    """True si jarvis_secrets est importe ET expose un backend keyring fonctionnel."""
    if jarvis_secrets is None:
        return False
    try:
        return bool(jarvis_secrets.keyring_disponible())
    except Exception as e:
        print(f"[DASHBOARD] Test keyring echoue : {e}")
        return False


def _ecrire_secrets_keyring(secrets: dict[str, str]) -> str | None:
    """Stocke les cles secretes dans keyring + os.environ. Retourne une erreur ou None.

    Une valeur vide supprime l'entree keyring (l'utilisateur efface la cle).
    """
    for cle, valeur in secrets.items():
        try:
            if valeur:
                ok = bool(jarvis_secrets.definir(cle, valeur))
            else:
                # Effacement : on tolere l'absence d'entree existante
                jarvis_secrets.supprimer(cle)
                ok = True
        except Exception as e:
            print(f"[DASHBOARD] Ecriture keyring '{cle}' echouee : {e}")
            ok = False
        if not ok:
            return f"Ecriture dans le coffre securise impossible pour {cle}"
    return None


def _set_env_detail(updates: Any) -> tuple[bool, str | None]:
    """Met a jour les cles gerees. (ok, erreur).

    Les cles SECRETES vont dans keyring si dispo (jamais en clair), sinon elles
    retombent dans le .env. Les cles non sensibles restent toujours dans le
    .env. Dans tous les cas os.environ est mis a jour pour la session courante.
    Ecriture .env atomique (.tmp + os.replace).
    """
    global _RESTART_REQUIRED
    propres, erreur = _valider_updates_env(updates)
    if propres is None:
        return False, erreur

    keyring_ok = _keyring_disponible()
    # Repartition : secrets vers keyring si dispo, le reste (et fallback) vers .env
    vers_keyring: dict[str, str] = {}
    vers_env: dict[str, str] = {}
    for cle, valeur in propres.items():
        if keyring_ok and cle in CLES_SECRETES:
            vers_keyring[cle] = valeur
        else:
            vers_env[cle] = valeur

    if vers_keyring:
        erreur = _ecrire_secrets_keyring(vers_keyring)
        if erreur is not None:
            return False, erreur
        # Le secret est dans keyring : on s'assure qu'aucune copie en clair ne
        # subsiste dans .env (sinon load_dotenv la repriorise au redemarrage).
        _purger_cles_env(vers_keyring.keys())

    if vers_env:
        try:
            lignes = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
            nouvelles = _fusionner_lignes_env(lignes, vers_env)
            tmp = ENV_PATH.with_name(ENV_PATH.name + ".tmp")
            tmp.write_text("\n".join(nouvelles) + "\n", encoding="utf-8")
            os.replace(tmp, ENV_PATH)
            _restreindre_env()
        except Exception as e:
            print(f"[DASHBOARD] Ecriture .env echouee : {e}")
            return False, "Ecriture du fichier .env impossible"

    # Mise a jour de la session courante (les clients IA restent inchanges -> restart)
    for cle, valeur in propres.items():
        if valeur:
            os.environ[cle] = valeur
        else:
            os.environ.pop(cle, None)
    _RESTART_REQUIRED = True
    print(
        f"[DASHBOARD] Cles mises a jour ({len(vers_keyring)} keyring, "
        f"{len(vers_env)} .env). Redemarrage requis."
    )
    return True, None


def set_env_values(updates: dict) -> bool:
    """Met a jour/ajoute des cles du .env (liste blanche uniquement). True si OK."""
    ok, _ = _set_env_detail(updates)
    return ok


# ==========================================
# INTEGRATIONS
# ==========================================
def _ollama_disponible() -> bool:
    """Ping local du serveur Ollama (GET /api/tags, timeout court)."""
    if requests is None:
        return False
    try:
        r = requests.get(OLLAMA_TAGS_URL, timeout=OLLAMA_TIMEOUT_S)
        return r.status_code == 200
    except Exception:
        return False


def _obsidian_actif(env_keys: dict[str, bool]) -> bool:
    """Statut Obsidian via le contexte si dispo (vault auto-detecte), sinon cle env."""
    fn = _CTX.get("obsidian_actif")
    if callable(fn):
        try:
            return bool(fn())
        except Exception as e:
            print(f"[DASHBOARD] Statut Obsidian via contexte echoue : {e}")
    return bool(env_keys.get("OBSIDIAN_VAULT", False))


def _construire_integrations(env_keys: dict[str, bool], ollama_ok: bool) -> dict[str, bool]:
    """Etat booleen de chaque integration a partir des cles presentes."""
    return {
        "gemini": env_keys.get("GEMINI_API_KEY", False),
        "groq": env_keys.get("GROQ_API_KEY", False),
        "grok": env_keys.get("XAI_API_KEY", False),
        "serpapi": env_keys.get("SERPAPI_API_KEY", False),
        "youtube": env_keys.get("YOUTUBE_API_KEY", False),
        "home_assistant": env_keys.get("HA_URL", False) and env_keys.get("HA_TOKEN", False),
        "meross": env_keys.get("MEROSS_EMAIL", False) and env_keys.get("MEROSS_PASSWORD", False),
        "obsidian": _obsidian_actif(env_keys),
        "ollama": bool(ollama_ok),
        # OpenClaw : configure des qu'un des deux tokens (gateway ou hooks)
        # est present — chaque token active une partie du pont.
        "openclaw": env_keys.get("OPENCLAW_TOKEN", False)
        or env_keys.get("OPENCLAW_HOOKS_TOKEN", False),
    }


# ==========================================
# GRAPHE MEMOIRE
# ==========================================
def _normaliser_texte(texte: str) -> str:
    """Minuscules + suppression des accents (NFD puis filtre des diacritiques)."""
    nfd = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _mots_significatifs(texte: str) -> set[str]:
    """Mots >= 5 lettres, minuscules, sans accents, hors mots trop courants."""
    norm = _normaliser_texte(str(texte))
    mots = re.findall(rf"[a-z]{{{LONGUEUR_MOT_SIGNIFICATIF},}}", norm)
    return {m for m in mots if m not in _STOPWORDS}


def _tronquer(texte: str, longueur: int = LONGUEUR_LABEL_MAX) -> str:
    """Tronque un label trop long avec une ellipse."""
    texte = str(texte).strip()
    return texte if len(texte) <= longueur else texte[: longueur - 1] + "…"


def _texte_de(valeur: Any) -> str:
    """Aplatit dict/list/scalaire en texte brut pour l'analyse de mots.

    Pour les dicts, seules les valeurs sont gardees : les noms de champs
    (rue, ville, relation...) creeraient des liens transversaux parasites.
    """
    if isinstance(valeur, dict):
        return " ".join(_texte_de(v) for v in valeur.values() if v)
    if isinstance(valeur, (list, tuple)):
        return " ".join(_texte_de(v) for v in valeur)
    return str(valeur) if valeur is not None else ""


def _section_non_vide(valeur: Any) -> bool:
    """True si la section contient au moins une vraie donnee.

    Un dict au schema complet mais aux champs vides (cas jarvis_profile)
    est considere comme vide.
    """
    if isinstance(valeur, dict):
        return any(_section_non_vide(v) for v in valeur.values())
    if isinstance(valeur, (list, tuple)):
        return any(_section_non_vide(v) for v in valeur)
    return bool(str(valeur).strip()) if valeur is not None else False


def _en_liste(valeur: Any) -> list:
    """Normalise une section de profil en liste (vide si None/vide)."""
    if not valeur:
        return []
    if isinstance(valeur, list):
        return valeur
    return [valeur]


def _noeuds_profil(profil: dict) -> list[tuple[str, str, str]]:
    """Construit (id, label, texte) pour chaque section non vide du profil."""
    noeuds: list[tuple[str, str, str]] = []
    identite = profil.get("identite")
    if _section_non_vide(identite):
        texte = _texte_de(identite)
        label = "Identite"
        if isinstance(identite, dict):
            label = str(identite.get("prenom") or identite.get("nom") or label)
        noeuds.append(("profil_identite", _tronquer(label), texte))
    for i, membre in enumerate(_en_liste(profil.get("famille"))):
        if not _section_non_vide(membre):
            continue
        if isinstance(membre, dict):
            nom = str(membre.get("nom") or membre.get("prenom") or f"Membre {i + 1}")
            relation = str(membre.get("relation") or "famille")
            label = _tronquer(f"{nom} ({relation})")
        else:
            label = _tronquer(str(membre))
        noeuds.append((f"profil_famille_{i}", label, _texte_de(membre)))
    adresse = profil.get("adresse")
    if _section_non_vide(adresse):
        texte = _texte_de(adresse)
        noeuds.append(("profil_adresse", _tronquer(texte), texte))
    sections = (
        ("habitudes", "profil_habitude"),
        ("preferences", "profil_pref"),
        ("routines", "profil_routine"),
    )
    for section, prefixe in sections:
        for i, item in enumerate(_en_liste(profil.get(section))):
            if not _section_non_vide(item):
                continue
            texte = _texte_de(item)
            noeuds.append((f"{prefixe}_{i}", _tronquer(texte), texte))
    return noeuds


def _liens_transversaux(
    mots_memoire: dict[str, set[str]],
    mots_profil: dict[str, set[str]],
) -> list[dict]:
    """Liens entre une memoire et une autre memoire ou un noeud profil partageant un mot."""
    liens: list[dict] = []
    vus: set[tuple[str, str]] = set()
    cibles = list(mots_memoire.items()) + list(mots_profil.items())
    for id_mem, mots in mots_memoire.items():
        if not mots:
            continue
        for id_cible, mots_cible in cibles:
            if id_cible == id_mem:
                continue
            paire = tuple(sorted((id_mem, id_cible)))
            if paire in vus:
                continue
            if mots & mots_cible:
                vus.add(paire)
                liens.append({"source": id_mem, "target": id_cible})
                if len(liens) >= MAX_LIENS_TRANSVERSAUX:
                    return liens
    return liens


def construire_graphe_memoire(memoire: dict, profil: dict) -> dict:
    """Graphe {nodes, links} : hub central -> categories -> feuilles + liens transversaux."""
    nodes: list[dict] = [
        {"id": "jarvis", "label": "JARVIS", "type": "hub", "taille": 3},
        {"id": "cat_memoire", "label": "Mémoire", "type": "categorie", "taille": 2},
        {"id": "cat_profil", "label": "Profil", "type": "categorie", "taille": 2},
    ]
    links: list[dict] = [
        {"source": "jarvis", "target": "cat_memoire"},
        {"source": "jarvis", "target": "cat_profil"},
    ]
    mots_memoire: dict[str, set[str]] = {}
    for cle, data in (memoire or {}).items():
        node_id = f"mem_{cle}"
        nodes.append({"id": node_id, "label": str(cle), "type": "memoire", "taille": 1})
        links.append({"source": "cat_memoire", "target": node_id})
        valeur = data.get("valeur", "") if isinstance(data, dict) else data
        mots_memoire[node_id] = _mots_significatifs(f"{cle} {valeur}")
    mots_profil: dict[str, set[str]] = {}
    for node_id, label, texte in _noeuds_profil(profil if isinstance(profil, dict) else {}):
        nodes.append({"id": node_id, "label": label, "type": "profil", "taille": 1})
        links.append({"source": "cat_profil", "target": node_id})
        mots_profil[node_id] = _mots_significatifs(texte)
    links.extend(_liens_transversaux(mots_memoire, mots_profil))
    return {"nodes": nodes, "links": links}


# ==========================================
# HANDLERS — VUE D'ENSEMBLE / .ENV
# ==========================================
def _flag_voix_actif(cle: str) -> bool:
    """True si le flag voix est explicitement active (os.environ == '1')."""
    return (os.environ.get(cle, "") or "").strip() == "1"


def _etat_voix() -> dict[str, bool]:
    """Etat des 3 flags voix avancee (opt-in, defaut OFF si non definis)."""
    return {
        "stt_local": _flag_voix_actif("JARVIS_STT_LOCAL"),
        "wake_local": _flag_voix_actif("JARVIS_WAKE_LOCAL"),
        "barge_in": _flag_voix_actif("JARVIS_BARGE_IN"),
    }


# Cache du check de mise a jour : un appel reseau max par heure (l'overview
# est rafraichi a chaque visite de la section, on ne re-interroge pas GitHub
# a chaque fois). {"resultat": dict | None, "expire": float monotonic}
_UPDATE_TTL_S = 3600.0
_UPDATE_CACHE: dict[str, Any] = {"resultat": None, "expire": 0.0}


def _info_maj() -> dict:
    """Version locale + disponibilite d'une mise a jour (cache 1 h).

    Ne leve jamais : check_update() encapsule deja ses erreurs reseau.
    """
    if jarvis_version is None:
        return {"version": None, "update": None}
    maintenant = time.monotonic()
    if _UPDATE_CACHE["resultat"] is None or maintenant >= _UPDATE_CACHE["expire"]:
        _UPDATE_CACHE["resultat"] = jarvis_version.check_update()
        _UPDATE_CACHE["expire"] = maintenant + _UPDATE_TTL_S
    info = _UPDATE_CACHE["resultat"]
    return {
        "version": jarvis_version.VERSION,
        "update": {
            "disponible": bool(info.get("disponible")),
            "version_distante": info.get("version_distante"),
            "url": info.get("url"),
        },
    }


async def _h_overview(data: dict) -> dict:
    env_keys = lire_cles_env()
    ollama_ok = await _en_executor(_ollama_disponible)
    maj = await _en_executor(_info_maj)
    return {
        "action": "dash_overview",
        "user_name": _nom_utilisateur(),
        "integrations": _construire_integrations(env_keys, ollama_ok),
        "env_keys": env_keys,
        "keyring": _keyring_disponible(),
        "voix": _etat_voix(),
        "restart_required": _RESTART_REQUIRED,
        **maj,
    }


async def _h_set_env(data: dict) -> dict:
    ok, erreur = _set_env_detail(data.get("updates"))
    reponse = {"action": "dash_env_saved", "ok": ok, "restart_required": _RESTART_REQUIRED}
    if erreur:
        reponse["error"] = erreur
    return reponse


async def _h_set_user_name(data: dict) -> dict:
    nom = str(data.get("name", "")).strip()
    if not nom:
        return {
            "action": "dash_env_saved",
            "ok": False,
            "restart_required": _RESTART_REQUIRED,
            "error": "Nom vide",
        }
    ok, erreur = _set_env_detail({"JARVIS_USER_NAME": nom})
    reponse = {"action": "dash_env_saved", "ok": ok, "restart_required": _RESTART_REQUIRED}
    if erreur:
        reponse["error"] = erreur
    return reponse


# ==========================================
# HANDLERS — APPAIRAGE / SECRETS
# ==========================================
# Ces handlers ne sont appeles que depuis un client loopback (gate cote main2),
# le token complet peut donc etre renvoye en clair : il sert a appairer le mobile.
def _payload_appairage(token: str) -> dict:
    """Construit le payload dash_pairing (token complet + URL d'appairage LAN,
    + URL Tailscale pour le controle a distance si un tailnet est detecte)."""
    ip = _lan_ip()
    payload = {
        "action": "dash_pairing",
        "token": token,
        "lan_ip": ip,
        "lan_url": f"http://{ip}:8080/?token={token}",
    }
    # Acces distant via Tailscale (depuis n'importe ou, pas seulement le LAN).
    # Degrade en silence si le module/tailnet est absent.
    try:
        from jarvis_actions import tailscale_net
        ts = tailscale_net.statut(token)
        if ts.get("actif"):
            payload["tailscale_ip"] = ts["ip"]
            payload["tailscale_url"] = ts["url_mobile"]
    except Exception as e:  # noqa: BLE001
        print(f"[DASHBOARD] Detection Tailscale ignoree : {e}")
    return payload


async def _h_get_pairing(data: dict) -> dict:
    if jarvis_security is None:
        return {"action": "dash_pairing", "error": "Module jarvis_security indisponible"}
    try:
        token = jarvis_security.get_ws_token()
    except Exception as e:
        print(f"[DASHBOARD] get_ws_token echoue : {e}")
        return {"action": "dash_pairing", "error": "Generation du token impossible"}
    return _payload_appairage(token)


async def _h_regen_pairing(data: dict) -> dict:
    if jarvis_security is None:
        return {"action": "dash_pairing", "error": "Module jarvis_security indisponible"}
    try:
        token = jarvis_security.regenerer_token()
    except Exception as e:
        print(f"[DASHBOARD] regenerer_token echoue : {e}")
        return {"action": "dash_pairing", "error": "Regeneration du token impossible"}
    return _payload_appairage(token)


async def _h_migrate_secrets(data: dict) -> dict:
    """Deplace les cles secretes connues du .env vers keyring si dispo."""
    if jarvis_secrets is None or not _keyring_disponible():
        return {
            "action": "dash_secrets_migrated",
            "ok": False,
            "keyring": False,
            "resultats": {},
            "error": "keyring indisponible",
        }
    try:
        resultats = jarvis_secrets.migrer_env_vers_keyring(list(CLES_SECRETES))
    except Exception as e:
        print(f"[DASHBOARD] Migration secrets echouee : {e}")
        return {
            "action": "dash_secrets_migrated",
            "ok": False,
            "keyring": True,
            "resultats": {},
            "error": "Migration des secrets impossible",
        }
    resultats = resultats if isinstance(resultats, dict) else {}
    # Booleens propres pour le frontend : {NOM: bool}
    resultats = {str(nom): bool(ok) for nom, ok in resultats.items()}
    # Purge du .env les cles effectivement migrees vers keyring (plus de clair).
    _purger_cles_env([nom for nom, ok in resultats.items() if ok])
    return {
        "action": "dash_secrets_migrated",
        "ok": True,
        "keyring": True,
        "resultats": resultats,
    }


# ==========================================
# HANDLERS — PROFIL
# ==========================================
async def _h_get_profile(data: dict) -> dict:
    if charger_profil is None:
        return {"action": "dash_profile", "profile": {}, "error": "Module jarvis_profile indisponible"}
    return {"action": "dash_profile", "profile": _charger_profil_sur()}


async def _h_set_profile(data: dict) -> dict:
    if sauvegarder_profil is None:
        return {"action": "dash_profile_saved", "ok": False, "error": "Module jarvis_profile indisponible"}
    profil = data.get("profile")
    if not isinstance(profil, dict):
        return {"action": "dash_profile_saved", "ok": False, "error": "Champ 'profile' manquant ou invalide"}
    ok = bool(sauvegarder_profil(profil))
    reponse = {"action": "dash_profile_saved", "ok": ok}
    if not ok:
        reponse["error"] = "Sauvegarde du profil refusee"
    return reponse


# ==========================================
# HANDLERS — MEMOIRE
# ==========================================
async def _h_get_memory(data: dict) -> dict:
    memoire = _appel_ctx("charger_memoire", defaut={}) or {}
    items: list[dict] = []
    for cle, entree in memoire.items():
        if isinstance(entree, dict):
            items.append({
                "cle": str(cle),
                "valeur": str(entree.get("valeur", "")),
                "timestamp": str(entree.get("timestamp", "")),
            })
        else:
            items.append({"cle": str(cle), "valeur": str(entree), "timestamp": ""})
    graph = construire_graphe_memoire(memoire, _charger_profil_sur())
    return {"action": "dash_memory", "items": items, "graph": graph}


async def _h_memory_add(data: dict) -> dict:
    cle = str(data.get("cle", "")).strip()
    valeur = str(data.get("valeur", "")).strip()
    if not cle or not valeur:
        return {"action": "dash_memory_saved", "ok": False, "error": "Cle et valeur requises"}
    fn = _CTX.get("ajouter_memoire")
    if not callable(fn):
        return {"action": "dash_memory_saved", "ok": False, "error": "Memoire indisponible (init_api non appele)"}
    fn(cle, valeur)
    return {"action": "dash_memory_saved", "ok": True}


async def _h_memory_delete(data: dict) -> dict:
    cle = str(data.get("cle", "")).strip()
    fn = _CTX.get("supprimer_memoire")
    if not cle or not callable(fn):
        return {"action": "dash_memory_saved", "ok": False, "error": "Cle manquante ou memoire indisponible"}
    return {"action": "dash_memory_saved", "ok": bool(fn(cle))}


def _recherche_sous_chaine(query: str) -> list[dict]:
    """Repli de recherche memoire sans RAG : filtre par sous-chaine (casse ignoree).

    Retourne [{cle, valeur, score}] (score binaire 1.0). Jamais d'exception."""
    try:
        memoire = _appel_ctx("charger_memoire", defaut={}) or {}
        q = query.lower()
        results = []
        for cle, entree in memoire.items():
            valeur = entree.get("valeur", "") if isinstance(entree, dict) else str(entree)
            if q in str(cle).lower() or q in str(valeur).lower():
                results.append({"cle": str(cle), "valeur": str(valeur), "score": 1.0})
        return results
    except Exception as e:
        print(f"[DASHBOARD] Repli recherche memoire echoue : {e}")
        return []


async def _h_memory_search(data: dict) -> dict:
    """Recherche semantique (RAG) dans la memoire via embeddings Ollama.

    L'appel a memory_rag.rechercher fait du reseau (Ollama) : il est deporte
    dans un thread (_en_executor) pour ne pas figer l'event loop. Si le module
    RAG est absent ou Ollama indisponible, rag=False et results=[] (le frontend
    affiche une note expliquant la degradation).
    """
    query = str(data.get("query", "")).strip()
    if not query:
        return {"action": "dash_memory_results", "query": query, "results": [], "rag": False}
    rag_actif = False
    if memory_rag is not None:
        try:
            rag_actif = bool(await _en_executor(memory_rag.disponible))
        except Exception as e:
            print(f"[DASHBOARD] memory_rag.disponible en echec : {e}")
            rag_actif = False
    if not rag_actif:
        # Repli sans RAG : recherche par sous-chaine sur la memoire complete.
        return {
            "action": "dash_memory_results",
            "query": query,
            "results": _recherche_sous_chaine(query),
            "rag": False,
        }
    try:
        bruts = await _en_executor(memory_rag.rechercher, query, 8)
    except Exception as e:
        print(f"[DASHBOARD] memory_rag.rechercher en echec : {e}")
        return {"action": "dash_memory_results", "query": query, "results": [], "rag": True}
    results: list[dict] = []
    for item in bruts or []:
        if not isinstance(item, dict):
            continue
        results.append({
            "cle": str(item.get("cle", "")),
            "valeur": str(item.get("valeur", "")),
            "score": float(item.get("score", 0.0) or 0.0),
        })
    return {"action": "dash_memory_results", "query": query, "results": results, "rag": True}


# ==========================================
# HANDLERS — SPECS / RECO MODELES
# ==========================================
async def _h_get_specs(data: dict) -> dict:
    if model_advisor_service is None:
        return {"action": "dash_specs", "specs": {}, "error": "Module model_advisor_service indisponible"}
    specs = await _en_executor(model_advisor_service.detecter_specs)
    return {"action": "dash_specs", "specs": specs if isinstance(specs, dict) else {}}


async def _h_model_reco(data: dict) -> dict:
    if model_advisor_service is None:
        return {
            "action": "dash_model_reco",
            "use_cases_disponibles": [],
            "modeles": [],
            "error": "Module model_advisor_service indisponible",
        }
    use_cases_bruts = data.get("use_cases")
    use_cases = [str(u) for u in use_cases_bruts] if isinstance(use_cases_bruts, list) else []
    disponibles = await _en_executor(model_advisor_service.use_cases_disponibles)
    # recommander() renvoie {"specs": dict, "modeles": [...]}
    resultat = await _en_executor(model_advisor_service.recommander, use_cases)
    if isinstance(resultat, dict):
        modeles = resultat.get("modeles", [])
    else:
        modeles = resultat or []
    return {
        "action": "dash_model_reco",
        "use_cases_disponibles": disponibles or [],
        "modeles": modeles,
    }


# Nom de modele Ollama valide : alphanum + . _ - / et tag optionnel ":<tag>".
# Empeche l'argv flag smuggling (ex. "--config") et toute injection d'argument.
_MODELE_OLLAMA_RE = re.compile(r"^[A-Za-z0-9._/-]+(?::[A-Za-z0-9._-]+)?$")


def _nom_modele_valide(model: str) -> bool:
    return bool(model) and not model.startswith("-") and bool(_MODELE_OLLAMA_RE.match(model))


def _ollama_exe() -> str | None:
    """Localise l'executable ollama : PATH d'abord, puis emplacements d'install
    connus.

    Pourquoi le repli : sous Windows, l'installeur d'Ollama ajoute son dossier au
    PATH UTILISATEUR, mais un process deja lance (Jarvis demarre juste apres
    l'install, ou par l'installeur lui-meme) herite d'un PATH FIGE sans Ollama ->
    shutil.which("ollama") renvoie None alors qu'Ollama est bel et bien installe,
    et le dashboard repondait a tort "Ollama n'est pas installe". On replie donc
    sur le chemin d'installation standard."""
    import shutil

    exe = shutil.which("ollama")
    if exe:
        return exe
    candidats: list[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidats.append(Path(local) / "Programs" / "Ollama" / "ollama.exe")
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        candidats.append(Path(program_files) / "Ollama" / "ollama.exe")
    # Replis Linux / macOS classiques.
    candidats += [
        Path("/usr/local/bin/ollama"),
        Path("/usr/bin/ollama"),
        Path.home() / ".ollama" / "bin" / "ollama",
    ]
    for c in candidats:
        try:
            if c.is_file():
                return str(c)
        except OSError:
            continue
    return None


def _lancer_ollama_pull(model: str) -> tuple[bool, str]:
    """Lance 'ollama pull <model>' en arriere-plan (non bloquant).

    Localise Ollama de facon robuste (PATH + chemin d'install), et demarre le
    serveur s'il n'est pas joignable (sinon 'ollama pull' echoue avec
    "could not connect to ollama app"). Returns (demarre, message).
    False seulement si Ollama est reellement introuvable sur le PC.
    """
    import subprocess
    import sys as _sys

    exe = _ollama_exe()
    if not exe:
        return False, "Ollama n'est pas installe sur ce PC (voir ollama.com)."
    creationflags = 0
    if _sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # Serveur eteint -> le demarrer PUIS attendre qu'il ecoute avant le pull :
    # 'ollama pull' echoue ("could not connect to ollama app") si le port 11434
    # n'est pas encore ouvert (Popen rend la main avant le bind du serveur).
    if not _ollama_disponible():
        try:
            subprocess.Popen(
                [exe, "serve"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except Exception as e:  # pragma: no cover - best effort
            print(f"[DASHBOARD] Demarrage d'Ollama impossible : {e}")
        else:
            # Poll borne (~8 s). On tape 127.0.0.1 : un refus est instantane, donc
            # la boucle sort vite des que le serveur ecoute. Tourne dans un thread
            # executor (cf. _h_model_select) -> ne bloque pas l'event loop WS.
            for _ in range(16):
                if _ollama_disponible():
                    break
                time.sleep(0.5)
    try:
        # "--" termine le parsing d'options : model ne peut pas devenir un flag.
        subprocess.Popen(
            [exe, "pull", "--", model],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        return True, f"Telechargement de {model} lance en arriere-plan."
    except Exception as e:
        return False, f"Echec du lancement de l'installation : {e}"


def _modele_deja_installe(model: str, installes: list[str]) -> bool:
    """Vrai si le modele (ou sa base avant ':') figure dans les tags installes."""
    base = model.split(":")[0]
    return any(t == model or t.split(":")[0] == base for t in (installes or []))


async def _h_model_select(data: dict) -> dict:
    """Definit un modele Ollama comme modele local prefere de Jarvis.

    Persiste JARVIS_OLLAMA_MODEL dans le .env (main2 le met en priorite n°1 au
    demarrage) et lance l'installation 'ollama pull' s'il n'est pas deja present.
    """
    model = str(data.get("model", "")).strip()
    if not model:
        return {"action": "dash_model_select", "ok": False,
                "error": "Modele manquant.", "message": "Aucun modele specifie."}
    if not _nom_modele_valide(model):
        return {"action": "dash_model_select", "ok": False,
                "error": "Nom de modele invalide.",
                "message": f"Nom de modele invalide : {model[:40]}"}

    # 1) Persiste le modele prefere (liste blanche CLES_GEREES -> restart_required).
    persiste = set_env_values({"JARVIS_OLLAMA_MODEL": model})

    # 2) Installe-le s'il manque.
    installes = []
    if model_advisor_service is not None:
        installes = await _en_executor(model_advisor_service.modeles_installes)
    deja = _modele_deja_installe(model, installes)

    install_lance, install_msg = False, ""
    if not deja:
        install_lance, install_msg = await _en_executor(_lancer_ollama_pull, model)

    if deja:
        message = f"{model} defini comme modele local. Redemarre Jarvis pour l'activer."
    elif install_lance:
        message = f"{install_msg} Il sera utilise apres installation + redemarrage."
    else:
        message = f"{model} enregistre, mais {install_msg}"

    return {
        "action": "dash_model_select",
        "ok": bool(persiste),
        "model": model,
        "installe": deja,
        "install_lance": install_lance,
        "message": message,
        "restart_required": _RESTART_REQUIRED,
    }


# ==========================================
# HANDLERS — MCP
# ==========================================
def _resultat_ok(resultat: Any) -> tuple[bool, str | None]:
    """Normalise un retour (message, ok) | bool | None en (ok, erreur_eventuelle)."""
    if isinstance(resultat, tuple) and len(resultat) == 2:
        message, ok = resultat
        return bool(ok), None if ok else str(message)
    if isinstance(resultat, bool):
        return resultat, None if resultat else "Operation refusee"
    return True, None


def _normaliser_config_mcp(config: Any) -> list[dict]:
    """Accepte dict {name: conf}, {"servers": ...} ou liste de confs avec 'name'."""
    if isinstance(config, dict) and isinstance(config.get("servers"), (dict, list)):
        config = config["servers"]
    bruts: list[tuple[str, Any]] = []
    if isinstance(config, dict):
        bruts = [(str(nom), conf) for nom, conf in config.items()]
    elif isinstance(config, list):
        bruts = [(str(conf.get("name", "")), conf) for conf in config if isinstance(conf, dict)]
    serveurs: list[dict] = []
    for nom, conf in bruts:
        if not nom:
            continue
        conf = conf if isinstance(conf, dict) else {}
        args = conf.get("args")
        serveurs.append({
            "name": nom,
            "command": str(conf.get("command", "")),
            "args": [str(a) for a in args] if isinstance(args, list) else [],
            "enabled": bool(conf.get("enabled", True)),
        })
    return serveurs


async def _h_mcp_list(data: dict) -> dict:
    if mcp_client is None:
        return {"action": "dash_mcp_list", "servers": [], "error": "Module mcp_client indisponible"}
    config = _normaliser_config_mcp(mcp_client.charger_config())
    try:
        etats = mcp_client.etat_serveurs() or {}
    except Exception as e:
        print(f"[DASHBOARD] etat_serveurs en echec : {e}")
        etats = {}
    servers: list[dict] = []
    for srv in config:
        etat = etats.get(srv["name"], {}) if isinstance(etats, dict) else {}
        etat = etat if isinstance(etat, dict) else {}
        servers.append({
            **srv,
            "connected": bool(etat.get("connected", False)),
            "nb_tools": int(etat.get("nb_tools", 0) or 0),
        })
    return {"action": "dash_mcp_list", "servers": servers}


async def _h_mcp_add(data: dict) -> dict:
    if mcp_client is None:
        return {"action": "dash_mcp_saved", "ok": False, "error": "Module mcp_client indisponible"}
    name = str(data.get("name", "")).strip()
    command = str(data.get("command", "")).strip()
    args_bruts = data.get("args")
    args = [str(a) for a in args_bruts] if isinstance(args_bruts, list) else []
    if not name or not command:
        return {"action": "dash_mcp_saved", "ok": False, "error": "Nom et commande requis"}
    ok, erreur = _resultat_ok(mcp_client.ajouter_serveur(name, command, args))
    reponse = {"action": "dash_mcp_saved", "ok": ok}
    if erreur:
        reponse["error"] = erreur
    return reponse


async def _h_mcp_remove(data: dict) -> dict:
    if mcp_client is None:
        return {"action": "dash_mcp_saved", "ok": False, "error": "Module mcp_client indisponible"}
    name = str(data.get("name", "")).strip()
    if not name:
        return {"action": "dash_mcp_saved", "ok": False, "error": "Nom requis"}
    ok, erreur = _resultat_ok(mcp_client.supprimer_serveur(name))
    reponse = {"action": "dash_mcp_saved", "ok": ok}
    if erreur:
        reponse["error"] = erreur
    return reponse


async def _h_mcp_toggle(data: dict) -> dict:
    if mcp_client is None:
        return {"action": "dash_mcp_saved", "ok": False, "error": "Module mcp_client indisponible"}
    name = str(data.get("name", "")).strip()
    if not name:
        return {"action": "dash_mcp_saved", "ok": False, "error": "Nom requis"}
    ok, erreur = _resultat_ok(mcp_client.activer_serveur(name, bool(data.get("enabled", True))))
    reponse = {"action": "dash_mcp_saved", "ok": ok}
    if erreur:
        reponse["error"] = erreur
    return reponse


async def _h_mcp_tools(data: dict) -> dict:
    name = str(data.get("name", "")).strip()
    if mcp_client is None:
        return {"action": "dash_mcp_tools", "name": name, "tools": [], "error": "Module mcp_client indisponible"}
    if not name:
        return {"action": "dash_mcp_tools", "name": name, "tools": [], "error": "Nom de serveur requis"}
    try:
        bruts = await _attendre_si_besoin(mcp_client.lister_tools(name)) or []
    except Exception as e:
        return {"action": "dash_mcp_tools", "name": name, "tools": [], "error": str(e)}
    tools: list[dict] = []
    for outil in bruts:
        if not isinstance(outil, dict):
            continue
        if outil.get("server") and str(outil["server"]) != name:
            continue
        tools.append({
            "name": str(outil.get("name", "")),
            "description": str(outil.get("description", "")),
        })
    return {"action": "dash_mcp_tools", "name": name, "tools": tools}


async def _h_mcp_catalog(data: dict) -> dict:
    """Renvoie le catalogue de serveurs MCP preconfigures (constante en dur).

    Le frontend affiche chaque entree et reutilise dash_mcp_add pour l'ajout.
    Les dicts sont recopies (jamais l'objet interne) pour eviter toute mutation
    accidentelle du catalogue partage.
    """
    catalogue: list[dict] = []
    for entree in CATALOGUE_MCP:
        item = {
            "nom": str(entree.get("nom", "")),
            "description": str(entree.get("description", "")),
            "command": str(entree.get("command", "")),
            "args": [str(a) for a in entree.get("args", [])],
        }
        besoin = entree.get("besoin")
        if besoin:
            item["besoin"] = str(besoin)
        catalogue.append(item)
    return {"action": "dash_mcp_catalog", "catalogue": catalogue}


# ==========================================
# HANDLERS — SKILLS
# ==========================================
def _skills_normalises() -> list[dict]:
    """Liste des skills au format attendu par le frontend."""
    bruts = skills_loader.lister_skills() or []
    skills: list[dict] = []
    for skill in bruts:
        if not isinstance(skill, dict):
            continue
        skills.append({
            "nom": str(skill.get("nom", "")),
            "description": str(skill.get("description", "")),
            "fichier": str(skill.get("fichier", "")),
            "active": bool(skill.get("active", False)),
        })
    return skills


async def _h_skills_list(data: dict) -> dict:
    if skills_loader is None:
        return {"action": "dash_skills_list", "skills": [], "error": "Module skills_loader indisponible"}
    return {"action": "dash_skills_list", "skills": _skills_normalises()}


async def _h_skill_toggle(data: dict) -> dict:
    if skills_loader is None:
        return {"action": "dash_skills_list", "skills": [], "error": "Module skills_loader indisponible"}
    nom = str(data.get("nom", "")).strip()
    if nom:
        skills_loader.activer_skill(nom, bool(data.get("enabled", True)))
        try:
            # Recharge pour que main2 voie le changement immediatement
            skills_loader.charger_skills(force_reload=True)
        except Exception as e:
            print(f"[DASHBOARD] Rechargement skills echoue : {e}")
    return {"action": "dash_skills_list", "skills": _skills_normalises()}


# ==========================================
# HANDLERS — AUTOMATISATION (ROUTINES)
# ==========================================
# Les modules routines/triggers sont synchrones pour le CRUD (I/O fichier court),
# on les appelle dans un executor pour ne pas bloquer l'event loop. L'execution
# d'une routine (executer_maintenant) est deja async et est awaitee directement.

async def _h_routines_list(data: dict) -> dict:
    if routines is None:
        return {"action": "dash_routines", "routines": [], "error": "Module routines indisponible"}
    liste = await _en_executor(routines.charger)
    return {"action": "dash_routines", "routines": liste if isinstance(liste, list) else []}


async def _h_routine_save(data: dict) -> dict:
    if routines is None:
        return {"action": "dash_routines", "routines": [], "error": "Module routines indisponible"}
    routine = data.get("routine")
    if not isinstance(routine, dict):
        return {
            "action": "dash_routines",
            "routines": await _en_executor(routines.charger),
            "error": "Champ 'routine' manquant ou invalide",
        }
    # maj() fait un upsert (par id) ; un id est genere par valider() si absent.
    liste = await _en_executor(routines.maj, routine)
    return {"action": "dash_routines", "routines": liste if isinstance(liste, list) else []}


async def _h_routine_delete(data: dict) -> dict:
    if routines is None:
        return {"action": "dash_routines", "routines": [], "error": "Module routines indisponible"}
    routine_id = str(data.get("id", "")).strip()
    if not routine_id:
        return {
            "action": "dash_routines",
            "routines": await _en_executor(routines.charger),
            "error": "Identifiant requis",
        }
    liste = await _en_executor(routines.supprimer, routine_id)
    return {"action": "dash_routines", "routines": liste if isinstance(liste, list) else []}


async def _h_routine_run(data: dict) -> dict:
    routine_id = str(data.get("id", "")).strip()
    if routines is None:
        return {"action": "dash_routine_run", "id": routine_id, "ok": False}
    executer = _CTX.get("executer_commande")
    if not callable(executer):
        # Pas de wrapper d'execution injecte par main2 : on ne peut rien lancer.
        return {"action": "dash_routine_run", "id": routine_id, "ok": False}
    try:
        ok = bool(await routines.executer_maintenant(routine_id, executer))
    except Exception as e:
        print(f"[DASHBOARD] executer_maintenant en echec : {e}")
        ok = False
    return {"action": "dash_routine_run", "id": routine_id, "ok": ok}


# ==========================================
# HANDLERS — AUTOMATISATION (TRIGGERS)
# ==========================================
def _psutil_disponible() -> bool:
    """True si le module triggers est present ET psutil importable."""
    if triggers is None:
        return False
    try:
        return bool(triggers.disponible())
    except Exception as e:
        print(f"[DASHBOARD] triggers.disponible en echec : {e}")
        return False


async def _h_triggers_list(data: dict) -> dict:
    if triggers is None:
        return {"action": "dash_triggers", "triggers": [], "psutil": False, "error": "Module triggers indisponible"}
    liste = await _en_executor(triggers.charger)
    return {
        "action": "dash_triggers",
        "triggers": liste if isinstance(liste, list) else [],
        "psutil": _psutil_disponible(),
    }


async def _h_trigger_save(data: dict) -> dict:
    if triggers is None:
        return {"action": "dash_triggers", "triggers": [], "psutil": False, "error": "Module triggers indisponible"}
    trigger = data.get("trigger")
    if not isinstance(trigger, dict):
        return {
            "action": "dash_triggers",
            "triggers": await _en_executor(triggers.charger),
            "psutil": _psutil_disponible(),
            "error": "Champ 'trigger' manquant ou invalide",
        }
    liste = await _en_executor(triggers.maj, trigger)
    return {
        "action": "dash_triggers",
        "triggers": liste if isinstance(liste, list) else [],
        "psutil": _psutil_disponible(),
    }


async def _h_trigger_delete(data: dict) -> dict:
    if triggers is None:
        return {"action": "dash_triggers", "triggers": [], "psutil": False, "error": "Module triggers indisponible"}
    trigger_id = str(data.get("id", "")).strip()
    if not trigger_id:
        return {
            "action": "dash_triggers",
            "triggers": await _en_executor(triggers.charger),
            "psutil": _psutil_disponible(),
            "error": "Identifiant requis",
        }
    liste = await _en_executor(triggers.supprimer, trigger_id)
    return {
        "action": "dash_triggers",
        "triggers": liste if isinstance(liste, list) else [],
        "psutil": _psutil_disponible(),
    }


# ==========================================
# HANDLERS — CONNECTEURS MEMOIRE (Obsidian / Drive / Notion)
# ==========================================
def _vault_obsidian() -> str:
    """Chemin du vault Obsidian : cle OBSIDIAN_VAULT, sinon auto-detection."""
    vault = (os.environ.get("OBSIDIAN_VAULT") or "").strip()
    if vault:
        return vault
    try:
        from jarvis_actions import obsidian_memory
        return obsidian_memory.auto_detect_vault() or ""
    except Exception:
        return ""


def _google_credentials_presentes() -> bool:
    """True si credentials.json OU le token Google existe (Drive configurable)."""
    return (REPO_DIR / "credentials.json").exists() or (REPO_DIR / "token.pickle").exists()


def _connecteurs_memoire_statut() -> dict:
    """Etat booleen de chaque connecteur de memoire (configure ou non)."""
    env = _parser_env()
    notion_token = _valeur_presente(_valeur_brute_cle("NOTION_TOKEN", env))
    notion_page = _valeur_presente(_valeur_brute_cle("NOTION_PAGE_ID", env))
    return {
        "obsidian": bool(_vault_obsidian()),
        "drive": _google_credentials_presentes(),
        "notion": bool(notion_token and notion_page),
    }


async def _h_memory_connectors(data: dict) -> dict:
    statut = await _en_executor(_connecteurs_memoire_statut)
    return {"action": "dash_memory_connectors", "connectors": statut}


async def _h_memory_sync(data: dict) -> dict:
    """Synchronise la memoire vers la cible demandee (obsidian / drive / notion)."""
    cible = str(data.get("target", "")).strip().lower()
    if memory_sync is None:
        return {"action": "dash_memory_sync", "target": cible, "ok": False,
                "message": "Module de synchronisation indisponible."}
    memoire = _appel_ctx("charger_memoire", defaut={}) or {}
    if cible == "obsidian":
        resume, ok = await _en_executor(memory_sync.sync_obsidian, memoire, _vault_obsidian())
    elif cible == "drive":
        # get_drive_service peut declencher l'autorisation OAuth (navigateur) au
        # premier appel : on l'execute en thread pour ne pas figer l'event loop.
        service = await _en_executor(lambda: _appel_ctx("get_drive_service"))
        resume, ok = await _en_executor(memory_sync.backup_drive, memoire, service)
    elif cible == "notion":
        env = _parser_env()
        token = _valeur_brute_cle("NOTION_TOKEN", env)
        page = _valeur_brute_cle("NOTION_PAGE_ID", env)
        resume, ok = await _en_executor(memory_sync.sync_notion, memoire, token, page)
    else:
        return {"action": "dash_memory_sync", "target": cible, "ok": False,
                "message": f"Cible inconnue : {cible}"}
    return {
        "action": "dash_memory_sync",
        "target": cible,
        "ok": bool(ok),
        "message": str(resume),
        "connectors": await _en_executor(_connecteurs_memoire_statut),
    }


# ==========================================
# HANDLERS — PERSONNALISATION (UI)
# ==========================================
async def _diffuser_config_ui(config: dict) -> None:
    """Pousse la config UI a TOUS les clients (orbe incluse) pour appliquer la
    couleur/le theme en live, sans rechargement. No-op si main2 n'a pas injecte
    de diffuseur (le client recharge alors la couleur a sa prochaine connexion)."""
    diffuseur = _CTX.get("diffuser_ui")
    if not callable(diffuseur):
        return
    try:
        await _attendre_si_besoin(diffuseur({"action": "dash_ui", "config": config}))
    except Exception as e:
        print(f"[DASHBOARD] Diffusion config UI echouee : {e}")


async def _h_get_ui(data: dict) -> dict:
    if jarvis_ui_config is None:
        return {"action": "dash_ui", "config": {}, "error": "Module jarvis_ui_config indisponible"}
    return {"action": "dash_ui", "config": jarvis_ui_config.charger()}


async def _h_set_ui(data: dict) -> dict:
    """Enregistre les reglages d'apparence (theme/accent/orbe). Le dossier Cowork
    a son propre handler (dash_set_cowork) — ici on ignore tout autre champ."""
    if jarvis_ui_config is None:
        return {"action": "dash_ui", "config": {}, "error": "Module jarvis_ui_config indisponible"}
    updates = data.get("updates")
    if not isinstance(updates, dict):
        return {
            "action": "dash_ui",
            "config": jarvis_ui_config.charger(),
            "error": "Champ 'updates' manquant ou invalide",
        }
    apparence = {
        k: updates[k]
        for k in ("mode", "theme", "accent", "orb_style", "orb_color", "orb_shape")
        if k in updates
    }
    config = jarvis_ui_config.sauvegarder(apparence)
    await _diffuser_config_ui(config)
    return {"action": "dash_ui", "config": config}


# ==========================================
# HANDLERS — COWORK
# ==========================================
def _claude_dispo() -> bool:
    """True si le CLI 'claude' (Claude Code) est dans le PATH."""
    import shutil
    return bool(shutil.which("claude"))


def _git_statut(folder: str) -> dict:
    """Statut git du dossier : {is_repo, branch, dirty}. {} si git absent.

    Lecture seule (rev-parse / status), jamais de mutation. Le dossier vient du
    dashboard loopback (machine de l'utilisateur), git -C l'isole proprement.
    """
    import shutil
    import subprocess

    git = shutil.which("git")
    if not git or not folder or not os.path.isdir(folder):
        return {}

    def _run(args: list[str]) -> str | None:
        try:
            r = subprocess.run(
                [git, "-C", folder, *args],
                capture_output=True, text=True, timeout=5,
            )
            return r.stdout.strip() if r.returncode == 0 else None
        except Exception:
            return None

    if _run(["rev-parse", "--is-inside-work-tree"]) != "true":
        return {"is_repo": False}
    branche = _run(["rev-parse", "--abbrev-ref", "HEAD"]) or "?"
    porcelain = _run(["status", "--porcelain"])
    modifies = len([l for l in porcelain.splitlines() if l.strip()]) if porcelain else 0
    return {"is_repo": True, "branch": branche, "dirty": modifies}


def _apercu_dossier(folder: str, limite: int = 14) -> dict:
    """Apercu NON recursif : nombre d'entrees + premieres entrees (nom + type).

    Ne lit aucun contenu de fichier (noms seulement) : aucun risque de fuite.
    """
    try:
        entrees = sorted(os.listdir(folder))
    except Exception as e:
        return {"file_count": 0, "entries": [], "error": str(e)}
    apercu: list[dict] = []
    for nom in entrees:
        if nom.startswith("."):
            continue
        apercu.append({"name": nom, "dir": os.path.isdir(os.path.join(folder, nom))})
        if len(apercu) >= limite:
            break
    return {"file_count": len(entrees), "entries": apercu}


def _statut_cowork(folder: str) -> dict:
    """Payload dash_cowork complet pour un dossier (existence, git, apercu)."""
    existe = bool(folder) and os.path.isdir(folder)
    payload: dict[str, Any] = {
        "action": "dash_cowork",
        "folder": folder or "",
        "exists": existe,
        "claude_dispo": _claude_dispo(),
    }
    if existe:
        payload["git"] = _git_statut(folder)
        payload.update(_apercu_dossier(folder))
    return payload


async def _h_cowork_status(data: dict) -> dict:
    config = jarvis_ui_config.charger() if jarvis_ui_config is not None else {}
    folder = str(config.get("cowork_folder", "") or "")
    # _statut_cowork fait du subprocess (git) bloquant -> executor.
    return await _en_executor(_statut_cowork, folder)


async def _h_set_cowork(data: dict) -> dict:
    if jarvis_ui_config is None:
        return {"action": "dash_cowork", "folder": "", "exists": False,
                "error": "Module jarvis_ui_config indisponible"}
    folder_brut = str(data.get("folder", "") or "").strip().strip('"').strip("'")
    if folder_brut and not os.path.isdir(os.path.expanduser(folder_brut)):
        return {"action": "dash_cowork", "folder": "", "exists": False,
                "error": f"Dossier introuvable : {folder_brut[:120]}"}
    config = jarvis_ui_config.sauvegarder({"cowork_folder": folder_brut})
    folder = str(config.get("cowork_folder", "") or "")
    return await _en_executor(_statut_cowork, folder)


async def _h_cowork_delegate(data: dict) -> dict:
    """Confie une tache a Claude Code DANS le dossier Cowork (subprocess borne)."""
    if claude_bridge is None:
        return {"action": "dash_cowork_result", "ok": False,
                "error": "Module claude_bridge indisponible"}
    prompt = str(data.get("prompt", "") or "").strip()
    if not prompt:
        return {"action": "dash_cowork_result", "ok": False, "error": "Tache vide"}
    config = jarvis_ui_config.charger() if jarvis_ui_config is not None else {}
    folder = str(config.get("cowork_folder", "") or "")
    if not folder or not os.path.isdir(folder):
        return {"action": "dash_cowork_result", "ok": False,
                "error": "Aucun dossier Cowork valide defini"}
    sortie, ok = await _en_executor(
        lambda: claude_bridge.lancer_claude_code(prompt, 180.0, folder)
    )
    return {
        "action": "dash_cowork_result",
        "ok": bool(ok),
        "output": str(sortie),
        "folder": folder,
    }


async def _h_cowork_session(data: dict) -> dict:
    """Ouvre une session de code Claude Code INTERACTIVE (terminal) dans le Cowork."""
    if claude_bridge is None:
        return {"action": "dash_cowork_session_result", "ok": False,
                "error": "Module claude_bridge indisponible"}
    config = jarvis_ui_config.charger() if jarvis_ui_config is not None else {}
    folder = str(config.get("cowork_folder", "") or "")
    if not folder or not os.path.isdir(folder):
        return {"action": "dash_cowork_session_result", "ok": False,
                "error": "Aucun dossier Cowork valide defini"}
    mode = str(data.get("mode", "default") or "default")
    msg, ok = await _en_executor(
        lambda: claude_bridge.ouvrir_session_terminal(folder, mode)
    )
    return {"action": "dash_cowork_session_result", "ok": bool(ok),
            "message": msg, "error": "" if ok else msg}


async def _h_cowork_chat(data: dict) -> dict:
    """Un tour de chat AGENTIQUE Claude Code dans le dossier Cowork (modele local).

    Resout le dossier (config Cowork, sinon dossier par defaut auto-cree), demarre
    le proxy local si besoin, puis lance `claude --print` (--continue pour les
    tours suivants) avec le modele/mode choisis."""
    if claude_bridge is None:
        return {"action": "dash_cowork_reply", "ok": False,
                "text": "Module claude_bridge indisponible."}
    prompt = str(data.get("prompt", "") or "")
    if not prompt.strip():
        return {"action": "dash_cowork_reply", "ok": False, "text": "Message vide."}
    config = jarvis_ui_config.charger() if jarvis_ui_config is not None else {}
    folder = str(config.get("cowork_folder", "") or "")
    if not folder or not os.path.isdir(folder):
        folder = await _en_executor(claude_bridge.dossier_cowork_defaut)
    model = str(data.get("model", "") or "")
    mode = str(data.get("mode", "default") or "default")
    continuer = bool(data.get("continue", False))
    via_proxy = bool(await _en_executor(free_code.assurer_demarre)) if free_code is not None else False
    text, ok = await _en_executor(
        lambda: claude_bridge.chat_claude_code(prompt, folder, model, mode, continuer, via_proxy)
    )
    return {"action": "dash_cowork_reply", "ok": bool(ok), "text": text, "folder": folder}


# ==========================================
# HANDLERS — CODE (free-claude-code / proxy fcc-server)
# ==========================================
async def _h_fcc_status(data: dict) -> dict:
    """Statut du proxy free-claude-code (installe, en marche, URL admin)."""
    if free_code is None:
        return {"action": "dash_fcc_status", "installe": False,
                "en_marche": False, "url_admin": "", "port": 0}
    st = await _en_executor(free_code.statut)
    return {"action": "dash_fcc_status", **st}


async def _h_fcc_start(data: dict) -> dict:
    """Demarre le proxy free-claude-code s'il ne tourne pas."""
    if free_code is None:
        return {"action": "dash_fcc_started", "ok": False,
                "message": "Module free_code indisponible"}
    ok, message = await _en_executor(free_code.demarrer)
    return {"action": "dash_fcc_started", "ok": bool(ok), "message": message}


async def _h_code_model(data: dict) -> dict:
    """Modele de code actif + liste des modeles locaux (pour le selecteur)."""
    if code_chat is None:
        return {"action": "dash_code_model", "model": "", "models": []}

    def _infos():
        return code_chat.modele_actif(), code_chat.modeles_installes()

    model, models = await _en_executor(_infos)
    return {"action": "dash_code_model", "model": model, "models": models}


async def _h_code_chat(data: dict) -> dict:
    """Une question de code -> reponse d'un modele LOCAL (Ollama)."""
    if code_chat is None:
        return {"action": "dash_code_reply", "ok": False,
                "text": "Module code_chat indisponible."}
    prompt = str(data.get("prompt", "") or "")
    historique = data.get("history") if isinstance(data.get("history"), list) else []
    modele = str(data.get("model", "") or "") or None
    text, ok = await _en_executor(lambda: code_chat.repondre(prompt, historique, modele))
    return {"action": "dash_code_reply", "ok": bool(ok), "text": text}


# ==========================================
# HANDLERS — SKILLS CLAUDE CODE (Cowork)
# ==========================================
async def _h_cc_skills(data: dict) -> dict:
    """Catalogue de skills Claude Code + marketplaces deja ajoutees."""
    if cc_skills is None:
        return {"action": "dash_cc_skills", "claude_present": False,
                "catalogue": [], "installes": []}
    present = cc_skills.claude_disponible()
    installes = await _en_executor(cc_skills.marketplaces_installes) if present else set()
    return {
        "action": "dash_cc_skills",
        "claude_present": present,
        "catalogue": cc_skills.CATALOGUE,
        "installes": sorted(installes),
    }


async def _h_cc_skill_add(data: dict) -> dict:
    """Ajoute une marketplace de skills Claude Code (liste blanche = CATALOGUE)."""
    if cc_skills is None:
        return {"action": "dash_cc_skill_added", "ok": False,
                "message": "Module indisponible", "repo": ""}
    repo = str(data.get("repo", "") or "")
    ok, message = await _en_executor(lambda: cc_skills.ajouter_marketplace(repo))
    return {"action": "dash_cc_skill_added", "ok": bool(ok),
            "message": message, "repo": repo}


# ==========================================
# HANDLERS — SKILLS skills.sh (npx skills add)
# ==========================================
async def _h_skills_sh(data: dict) -> dict:
    """Catalogue de skills skills.sh (installables via npx skills add)."""
    if skills_sh is None:
        return {"action": "dash_skills_sh", "npx_present": False, "catalogue": []}
    return {
        "action": "dash_skills_sh",
        "npx_present": skills_sh.npx_disponible(),
        "catalogue": skills_sh.CATALOGUE,
    }


async def _h_skills_sh_add(data: dict) -> dict:
    """Installe un skill skills.sh (liste blanche = CATALOGUE)."""
    if skills_sh is None:
        return {"action": "dash_skills_sh_added", "ok": False,
                "message": "Module indisponible", "repo": ""}
    repo = str(data.get("repo", "") or "")
    ok, message = await _en_executor(lambda: skills_sh.installer_skill(repo))
    return {"action": "dash_skills_sh_added", "ok": bool(ok),
            "message": message, "repo": repo}


# ==========================================
# OPERATOR (tri mail, RDV, reunion, devis, recherche)
# ==========================================
async def _h_operator_init(data: dict) -> dict:
    """Etat initial de l'onglet Operator : file d'approbation + activite recente."""
    if op_approvals is None or op_report is None:
        return {"action": "dash_operator_state", "pending": [], "activity": [],
                "error": "Module operator indisponible"}
    try:
        return {"action": "dash_operator_state",
                "pending": op_approvals.lister(),
                "activity": op_report.derniers(50)}
    except Exception as e:
        return {"action": "dash_operator_state", "pending": [], "activity": [], "error": str(e)}


async def _h_operator_confirm(data: dict) -> dict:
    """Valide une action en attente (devis/email) -> execution via la facade operator."""
    if operator_mod is None or op_approvals is None:
        return {"action": "dash_operator_pending", "pending": [], "ok": False,
                "message": "Module operator indisponible"}
    aid = str(data.get("id", "") or "")
    try:
        msg, ok = await operator_mod.confirmer_depuis_dashboard(aid)
    except Exception as e:
        msg, ok = f"Erreur : {e}", False
    return {"action": "dash_operator_pending", "pending": op_approvals.lister(),
            "ok": bool(ok), "message": msg}


async def _h_operator_reject(data: dict) -> dict:
    """Rejette une action en attente."""
    if op_approvals is None:
        return {"action": "dash_operator_pending", "pending": [], "ok": False}
    aid = str(data.get("id", "") or "")
    ok = op_approvals.rejeter(aid)
    return {"action": "dash_operator_pending", "pending": op_approvals.lister(), "ok": bool(ok)}


async def _h_operator_settings_get(data: dict) -> dict:
    """Reglages Operator (societe, TVA, compteur devis, regles, autonomie). Sans secret."""
    if op_config is None:
        return {"action": "dash_operator_settings", "config": {}, "error": "indisponible"}
    return {"action": "dash_operator_settings", "config": op_config.charger()}


async def _h_operator_settings_set(data: dict) -> dict:
    """Enregistre des reglages Operator (fusion partielle validee)."""
    if op_config is None:
        return {"action": "dash_operator_settings", "config": {}, "ok": False}
    config = await _en_executor(lambda: op_config.sauvegarder(data.get("updates")))
    return {"action": "dash_operator_settings", "config": config, "ok": True}


async def _h_operator_meeting(data: dict) -> dict:
    """Controle de la session reunion : start / stop / import / state."""
    if operator_mod is None:
        return {"action": "dash_operator_meeting", "ok": False, "message": "indisponible"}
    op = str(data.get("op", "state") or "state")
    if op == "start":
        res = await operator_mod.dashboard_meeting_start()
    elif op == "stop":
        res = await operator_mod.dashboard_meeting_stop()
    elif op == "import":
        res = await operator_mod.dashboard_meeting_import(str(data.get("path", "") or ""))
    else:
        res = operator_mod.meeting_etat()
    res = dict(res)
    res["action"] = "dash_operator_meeting"
    return res


async def _h_operator_research(data: dict) -> dict:
    """Recherche internet depuis le dashboard -> synthese + sources."""
    if operator_mod is None:
        return {"action": "dash_operator_research", "resume": "", "sources": []}
    res = await operator_mod.dashboard_research(str(data.get("query", "") or ""))
    return {"action": "dash_operator_research", "resume": res.get("resume", ""),
            "sources": res.get("sources", [])}


async def _h_operator_devis(data: dict) -> dict:
    """Prepare un devis (depuis la reunion courante ou une description) -> approbation."""
    if operator_mod is None:
        return {"action": "dash_operator_pending", "pending": [], "ok": False, "message": "indisponible"}
    res = await operator_mod.dashboard_creer_devis(str(data.get("description", "") or ""))
    return {"action": "dash_operator_pending", "pending": res.get("pending", []),
            "ok": res.get("ok", False), "message": res.get("message", "")}


# ==========================================
# DISPATCH
# ==========================================
_HANDLERS = {
    "dash_get_overview": _h_overview,
    "dash_set_env": _h_set_env,
    "dash_set_user_name": _h_set_user_name,
    "dash_get_pairing": _h_get_pairing,
    "dash_regen_pairing": _h_regen_pairing,
    "dash_migrate_secrets": _h_migrate_secrets,
    "dash_get_profile": _h_get_profile,
    "dash_set_profile": _h_set_profile,
    "dash_get_memory": _h_get_memory,
    "dash_memory_add": _h_memory_add,
    "dash_memory_delete": _h_memory_delete,
    "dash_memory_search": _h_memory_search,
    "dash_memory_connectors": _h_memory_connectors,
    "dash_memory_sync": _h_memory_sync,
    "dash_get_specs": _h_get_specs,
    "dash_model_reco": _h_model_reco,
    "dash_model_select": _h_model_select,
    "dash_mcp_list": _h_mcp_list,
    "dash_mcp_add": _h_mcp_add,
    "dash_mcp_remove": _h_mcp_remove,
    "dash_mcp_toggle": _h_mcp_toggle,
    "dash_mcp_tools": _h_mcp_tools,
    "dash_mcp_catalog": _h_mcp_catalog,
    "dash_skills_list": _h_skills_list,
    "dash_skill_toggle": _h_skill_toggle,
    "dash_cc_skills": _h_cc_skills,
    "dash_cc_skill_add": _h_cc_skill_add,
    "dash_skills_sh": _h_skills_sh,
    "dash_skills_sh_add": _h_skills_sh_add,
    "dash_fcc_status": _h_fcc_status,
    "dash_fcc_start": _h_fcc_start,
    "dash_code_model": _h_code_model,
    "dash_code_chat": _h_code_chat,
    "dash_routines_list": _h_routines_list,
    "dash_routine_save": _h_routine_save,
    "dash_routine_delete": _h_routine_delete,
    "dash_routine_run": _h_routine_run,
    "dash_triggers_list": _h_triggers_list,
    "dash_trigger_save": _h_trigger_save,
    "dash_trigger_delete": _h_trigger_delete,
    "dash_get_ui": _h_get_ui,
    "dash_set_ui": _h_set_ui,
    "dash_cowork_status": _h_cowork_status,
    "dash_set_cowork": _h_set_cowork,
    "dash_cowork_delegate": _h_cowork_delegate,
    "dash_cowork_session": _h_cowork_session,
    "dash_cowork_chat": _h_cowork_chat,
    "dash_operator_init": _h_operator_init,
    "dash_operator_confirm": _h_operator_confirm,
    "dash_operator_reject": _h_operator_reject,
    "dash_operator_settings_get": _h_operator_settings_get,
    "dash_operator_settings_set": _h_operator_settings_set,
    "dash_operator_meeting": _h_operator_meeting,
    "dash_operator_research": _h_operator_research,
    "dash_operator_devis": _h_operator_devis,
}


async def _envoyer(websocket: Any, payload: dict) -> None:
    """Serialise et envoie une reponse sur le websocket."""
    await websocket.send(json.dumps(payload))


async def traiter_message_dashboard(data: dict, websocket: Any) -> bool:
    """Route un message dashboard. False si le type n'est pas 'dash_*' (main2 continue).

    Tout pepin dans un handler renvoie {action: "dash_error", error} au client,
    jamais d'exception remontee a ws_handler.
    """
    if not isinstance(data, dict):
        return False
    msg_type = str(data.get("type") or "")
    if not msg_type.startswith("dash_"):
        return False
    handler = _HANDLERS.get(msg_type)
    try:
        if handler is None:
            await _envoyer(websocket, {"action": "dash_error", "error": f"Type dashboard inconnu : {msg_type}"})
            return True
        reponse = await handler(data)
        if reponse is not None:
            await _envoyer(websocket, reponse)
    except Exception as e:
        print(f"[DASHBOARD] Erreur handler {msg_type} : {e}")
        try:
            await _envoyer(websocket, {"action": "dash_error", "error": str(e)})
        except Exception:
            pass  # client deconnecte entre temps : rien a faire
    return True
