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
    import jarvis_security
except Exception as e:
    jarvis_security = None
    print(f"[DASHBOARD] Module jarvis_security indisponible : {e}")

try:
    import jarvis_secrets
except Exception as e:
    jarvis_secrets = None
    print(f"[DASHBOARD] Module jarvis_secrets indisponible : {e}")


# ==========================================
# CONSTANTES
# ==========================================
REPO_DIR = Path(__file__).resolve().parent
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
})

_PLACEHOLDERS = ("VOTRE_API", "VOTRE_CLE_ICI")

OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
OLLAMA_TIMEOUT_S = 1.5

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
    except Exception as e:
        print(f"[DASHBOARD] Purge .env echouee : {e}")


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
async def _h_overview(data: dict) -> dict:
    env_keys = lire_cles_env()
    ollama_ok = await _en_executor(_ollama_disponible)
    return {
        "action": "dash_overview",
        "user_name": _nom_utilisateur(),
        "integrations": _construire_integrations(env_keys, ollama_ok),
        "env_keys": env_keys,
        "keyring": _keyring_disponible(),
        "restart_required": _RESTART_REQUIRED,
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
    """Construit le payload dash_pairing (token complet + URL d'appairage LAN)."""
    ip = _lan_ip()
    return {
        "action": "dash_pairing",
        "token": token,
        "lan_ip": ip,
        "lan_url": f"http://{ip}:8080/?token={token}",
    }


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
    "dash_get_specs": _h_get_specs,
    "dash_model_reco": _h_model_reco,
    "dash_mcp_list": _h_mcp_list,
    "dash_mcp_add": _h_mcp_add,
    "dash_mcp_remove": _h_mcp_remove,
    "dash_mcp_toggle": _h_mcp_toggle,
    "dash_mcp_tools": _h_mcp_tools,
    "dash_skills_list": _h_skills_list,
    "dash_skill_toggle": _h_skill_toggle,
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
