# from ursina import *  # DESACTIVE — interface web Three.js
import threading
import asyncio
import google.genai as genai
from google.genai import types
import edge_tts
import os
import sys

# Imports audio/GUI tolerants : en conteneur (Docker, mode serveur headless)
# il n'y a ni micro, ni haut-parleur, ni display. Ces libs crashent a l'import
# (pyautogui) ou a l'usage (pyaudio/pygame mixer) sans peripherique. On degrade
# en None ; tout le code en aval (boucle vocale, TTS, actions souris) est soit
# saute en mode headless, soit deja protege par try/except.
try:
    import speech_recognition as sr
except Exception as _e:
    print(f"[VOIX] speech_recognition indisponible : {_e}")
    sr = None
try:
    import pygame
except Exception as _e:
    print(f"[AUDIO] pygame indisponible : {_e}")
    pygame = None
from dotenv import load_dotenv
import random
import math
try:
    import pyautogui
except Exception as _e:
    print(f"[GUI] pyautogui indisponible (pas de display ?) : {_e}")
    pyautogui = None
import webbrowser
import subprocess
import requests
import time
import pickle
import json
import re
import shutil
from pathlib import Path
from datetime import datetime
try:
    import pyaudio
except Exception as _e:
    print(f"[AUDIO] pyaudio indisponible : {_e}")
    pyaudio = None
import websockets
import json
from PIL import Image
from openai import OpenAI
import uuid
import base64
import io

# Google APIs
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from jarvis_config import USER_NAME

# Dossier des donnees persistantes : a cote de l'exe en mode PyInstaller
# (le cwd est alors sys._MEIPASS, un dossier temporaire efface a la sortie),
# sinon racine du repo. Meme pattern que jarvis_profile._dossier_donnees.
def _dossier_donnees() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


DOSSIER_DONNEES = _dossier_donnees()

# En mode .exe, les fichiers perso deposes a cote du binaire (jarvis_home_config.py,
# skills...) doivent etre importables : le dossier de l'exe passe en tete de
# sys.path (il prime sur les modules generiques embarques dans le bundle).
if getattr(sys, "frozen", False) and str(DOSSIER_DONNEES) not in sys.path:
    sys.path.insert(0, str(DOSSIER_DONNEES))

# Chargement des variables d'environnement. En mode .exe, le .env persistant
# vit a cote du binaire : on le charge en premier (load_dotenv n'ecrase pas
# une cle deja chargee, le premier lu gagne).
if getattr(sys, "frozen", False):
    load_dotenv(DOSSIER_DONNEES / ".env")
load_dotenv()

# Mode serveur headless (Docker / VM sans peripheriques) : desactive la boucle
# vocale (micro) et la sortie audio locale (pygame). Le serveur WebSocket, le
# serveur HTTP mobile et le frontend restent actifs ; le STT/TTS se fait alors
# cote navigateur (Web Speech API) via l'interface web ou mobile.
HEADLESS = os.getenv("JARVIS_HEADLESS", "0") == "1"

# Securite : auth WebSocket par token (clients LAN) + secrets via keyring.
# Imports tolerants (comme les autres modules optionnels) : -> None si echec,
# tout le code en aval verifie la disponibilite avant usage.
try:
    import jarvis_security
except Exception as _e:
    print(f"[SECURITE] Module jarvis_security desactive : {_e}")
    jarvis_security = None

try:
    import jarvis_secrets
except Exception as _e:
    print(f"[SECRETS] Module jarvis_secrets desactive : {_e}")
    jarvis_secrets = None

# Liste des cles secretes connues. Si elles sont stockees dans keyring (et absentes
# de l'environnement), on les repeuple dans os.environ AVANT la lecture ci-dessous.
_CLES_SECRETES = [
    "GEMINI_API_KEY",
    "YOUTUBE_API_KEY",
    "XAI_API_KEY",
    "HA_TOKEN",
    "SERPAPI_API_KEY",
    "GROQ_API_KEY",
    "MEROSS_PASSWORD",
    "MEROSS_EMAIL",
]
if jarvis_secrets is not None:
    try:
        _nb = jarvis_secrets.charger_dans_environ(_CLES_SECRETES)
        if _nb:
            print(f"[SECRETS] {_nb} cle(s) chargee(s) depuis keyring.")
    except Exception as _e:
        print(f"[SECRETS] Echec chargement keyring : {_e}")


# Fonctions pures du cerveau local extraites dans jarvis_brain_local.py.
# Reimport ici pour que tous les appels existants de main2 marchent a l'identique.
from jarvis_brain_local import (
    resoudre_math_localement,
    resoudre_francais_localement,
    resoudre_conversion_localement,
    resoudre_traduction_localement,
    nettoyer_pour_tts,
    nettoyer_commande,
)


def _local_ip():
    """Detecte l'IP LAN de la machine (pour acces mobile/reseau)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


LAN_IP = _local_ip()

GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
XAI_API_KEY     = os.getenv("XAI_API_KEY")
HA_URL          = os.getenv("HA_URL")
HA_TOKEN        = os.getenv("HA_TOKEN")
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
GROQ_API_KEY    = os.getenv("GROQ_API_KEY")

def _cle_valide(val):
    return bool(val) and val not in ("VOTRE_API", "VOTRE_CLE_ICI") and not val.startswith("VOTRE_")

GEMINI_DISPONIBLE = _cle_valide(GEMINI_API_KEY)
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_DISPONIBLE else None

grok_client = OpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1") if _cle_valide(XAI_API_KEY) else None
groq_client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1") if _cle_valide(GROQ_API_KEY) else None

MODELS_LIST     = ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash-exp", "gemini-1.5-flash"]
CHOSEN_MODEL    = MODELS_LIST[0]

# Surchageable via .env (ex. Docker : OLLAMA_URL=http://ollama:11434).
# Meme defaut que jarvis_actions/memory_rag.py et model_advisor_service.py.
OLLAMA_URL      = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODELS   = ["qwen2.5:7b", "qwen2.5", "mistral:7b", "mistral:instruct", "llama3.1:8b", "llama3.2:3b", "llama3.2", "gemma2:9b", "deepseek-coder-v2:lite"]
# Modele prefere choisi depuis le dashboard ("Choisir ce modele" -> JARVIS_OLLAMA_MODEL).
# Place en tete de priorite : _decouvrir_modeles_ollama() le selectionnera en premier s'il est installe.
_MODELE_PREFERE = os.environ.get("JARVIS_OLLAMA_MODEL", "").strip()
if _MODELE_PREFERE:
    OLLAMA_MODELS = [_MODELE_PREFERE] + [m for m in OLLAMA_MODELS if m != _MODELE_PREFERE]
FORCE_OLLAMA    = os.getenv("FORCE_OLLAMA", "1" if not GEMINI_DISPONIBLE else "0") == "1"

if FORCE_OLLAMA:
    print("[CERVEAU] Mode 100% local (Ollama). Gemini desactive.")
elif not GEMINI_DISPONIBLE:
    print("[CERVEAU] Cle Gemini absente. Ollama sera utilise.")

VILLE_PAR_DEFAUT = "Amilly"
LAT_PAR_DEFAUT   = 47.9742
LON_PAR_DEFAUT   = 2.7708

CLAP_THRESHOLD = 1200
VIDEO_LANCEE   = False
MODE_IRON_MAN = False 

HA_HEADERS = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type" : "application/json"
}

CREATOR_INFO = (
    "INFORMATIONS SUR TON CREATEUR :\n"
    f"- Prenom : {USER_NAME}\n"
    "- Role : Ton createur et maitre\n"
    f"- Tu dois toujours l'appeler {USER_NAME} avec respect mais aussi une pointe de sarcasme affectueux.\n"
)

EXTENSIONS = {
    "Images"   : [".jpg", ".jpeg", ".png", ".gif", ".bmp",
                  ".tiff", ".tif", ".webp", ".svg", ".ico",
                  ".heic", ".raw", ".cr2", ".nef"],
    "Videos"   : [".mp4", ".avi", ".mkv", ".mov", ".wmv",
                  ".flv", ".webm", ".m4v", ".mpg", ".mpeg",
                  ".3gp", ".ts"],
    "Musique"  : [".mp3", ".wav", ".flac", ".aac", ".ogg",
                  ".wma", ".m4a", ".opus", ".aiff"],
    "Documents": [".pdf", ".doc", ".docx", ".xls", ".xlsx",
                  ".ppt", ".pptx", ".txt", ".odt", ".ods",
                  ".odp", ".rtf", ".csv", ".epub"],
    "Archives" : [".zip", ".rar", ".7z", ".tar", ".gz",
                  ".bz2", ".xz", ".iso"],
    "Code"     : [".py", ".js", ".html", ".css", ".java",
                  ".cpp", ".c", ".h", ".cs", ".php",
                  ".json", ".xml", ".yaml", ".yml",
                  ".sh", ".bat", ".ps1", ".ts", ".jsx",
                  ".tsx", ".vue", ".go", ".rs", ".rb"],
    "Executables": [".exe", ".msi", ".apk", ".dmg", ".deb"],
}

dossier_courant = None

def trouver_extension(ext):
    for categorie, extensions in EXTENSIONS.items():
        if ext.lower() in extensions:
            return categorie
    return "Autres"

def ouvrir_dossier(chemin):
    global dossier_courant
    chemin = chemin.strip().strip('"').strip("'")
    raccourcis = {
        "bureau"      : os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"),
        "desktop"     : os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"),
        "documents"   : os.path.join(os.environ.get("USERPROFILE", ""), "Documents"),
        "telechargements": os.path.join(os.environ.get("USERPROFILE", ""), "Downloads"),
        "downloads"   : os.path.join(os.environ.get("USERPROFILE", ""), "Downloads"),
        "images"      : os.path.join(os.environ.get("USERPROFILE", ""), "Pictures"),
        "photos"      : os.path.join(os.environ.get("USERPROFILE", ""), "Pictures"),
        "videos"      : os.path.join(os.environ.get("USERPROFILE", ""), "Videos"),
        "musique"     : os.path.join(os.environ.get("USERPROFILE", ""), "Music"),
    }
    chemin_resolu = raccourcis.get(chemin.lower(), chemin)
    if not os.path.exists(chemin_resolu):
        return False, f"Dossier introuvable : {chemin_resolu}"
    dossier_courant = chemin_resolu
    subprocess.Popen(f'explorer "{chemin_resolu}"')
    return True, chemin_resolu

def lister_dossier(chemin=None):
    cible = chemin or dossier_courant
    if not cible or not os.path.exists(cible):
        return None, "Aucun dossier ouvert ou chemin invalide."
    fichiers  = []
    dossiers  = []
    for item in os.scandir(cible):
        if item.is_file():
            fichiers.append(item.name)
        elif item.is_dir():
            dossiers.append(item.name)
    return {"chemin": cible, "fichiers": fichiers, "dossiers": dossiers}, None

def trier_par_type(chemin=None):
    cible = chemin or dossier_courant
    if not cible or not os.path.exists(cible):
        return False, "Aucun dossier ouvert."
    deplacements = 0
    erreurs      = 0
    categories   = {}
    for item in os.scandir(cible):
        if not item.is_file():
            continue
        ext       = Path(item.name).suffix
        categorie = trouver_extension(ext)
        dest_dir  = os.path.join(cible, categorie)
        try:
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = os.path.join(dest_dir, item.name)
            if os.path.exists(dest_path):
                base  = Path(item.name).stem
                ext2  = Path(item.name).suffix
                dest_path = os.path.join(dest_dir, f"{base}_{int(time.time())}{ext2}")
            shutil.move(item.path, dest_path)
            deplacements += 1
            categories[categorie] = categories.get(categorie, 0) + 1
        except Exception as e:
            print(f"[FICHIER] Erreur deplacement {item.name} : {e}")
            erreurs += 1
    resume = ", ".join([f"{v} {k}" for k, v in categories.items()])
    return True, f"{deplacements} fichiers tries : {resume}. {erreurs} erreurs."

def trier_par_date(chemin=None):
    cible = chemin or dossier_courant
    if not cible or not os.path.exists(cible):
        return False, "Aucun dossier ouvert."
    deplacements = 0
    erreurs      = 0
    for item in os.scandir(cible):
        if not item.is_file():
            continue
        try:
            mtime     = item.stat().st_mtime
            date      = datetime.fromtimestamp(mtime)
            annee     = str(date.year)
            mois      = date.strftime("%m - %B")
            dest_dir  = os.path.join(cible, annee, mois)
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = os.path.join(dest_dir, item.name)
            if os.path.exists(dest_path):
                base      = Path(item.name).stem
                ext2      = Path(item.name).suffix
                dest_path = os.path.join(dest_dir, f"{base}_{int(time.time())}{ext2}")
            shutil.move(item.path, dest_path)
            deplacements += 1
        except Exception as e:
            print(f"[FICHIER] Erreur deplacement {item.name} : {e}")
            erreurs += 1
    return True, f"{deplacements} fichiers tries par date. {erreurs} erreurs."

def trier_par_type_puis_date(chemin=None):
    cible = chemin or dossier_courant
    if not cible or not os.path.exists(cible):
        return False, "Aucun dossier ouvert."
    ok1, msg1 = trier_par_type(cible)
    if not ok1:
        return False, msg1
    for item in os.scandir(cible):
        if item.is_dir() and item.name in EXTENSIONS.keys():
            trier_par_date(item.path)
    return True, "Dossier trie par type puis par date dans chaque categorie."

def creer_sous_dossier(nom, chemin=None):
    cible = chemin or dossier_courant
    if not cible:
        return False, "Aucun dossier ouvert."
    nouveau = os.path.join(cible, nom)
    try:
        os.makedirs(nouveau, exist_ok=True)
        return True, f"Dossier {nom} cree."
    except Exception as e:
        return False, f"Erreur creation dossier : {e}"

def renommer_fichier(ancien_nom, nouveau_nom, chemin=None):
    cible = chemin or dossier_courant
    if not cible:
        return False, "Aucun dossier ouvert."
    ancien = os.path.join(cible, ancien_nom)
    nouveau = os.path.join(cible, nouveau_nom)
    try:
        os.rename(ancien, nouveau)
        return True, f"Fichier renomme en {nouveau_nom}."
    except Exception as e:
        return False, f"Erreur renommage : {e}"

def deplacer_fichier(nom_fichier, dossier_dest, chemin=None):
    cible = chemin or dossier_courant
    if not cible:
        return False, "Aucun dossier ouvert."
    source = os.path.join(cible, nom_fichier)
    dest   = os.path.join(cible, dossier_dest, nom_fichier)
    try:
        os.makedirs(os.path.join(cible, dossier_dest), exist_ok=True)
        shutil.move(source, dest)
        return True, f"{nom_fichier} deplace dans {dossier_dest}."
    except Exception as e:
        return False, f"Erreur deplacement : {e}"

def chercher_fichier(nom, chemin=None):
    cible = chemin or dossier_courant
    if not cible:
        return [], "Aucun dossier ouvert."
    resultats = []
    for root, dirs, files in os.walk(cible):
        for f in files:
            if nom.lower() in f.lower():
                resultats.append(os.path.join(root, f))
    return resultats, None

# ==========================================
# MEMOIRE PERSISTANTE
# ==========================================
# Ancres sur DOSSIER_DONNEES : en mode .exe le cwd est sys._MEIPASS (temporaire),
# un chemin relatif y perdrait memoire et historique a chaque fermeture.
MEMOIRE_FILE = str(DOSSIER_DONNEES / "jarvis_memoire.json")
HISTORIQUE_FILE = str(DOSSIER_DONNEES / "jarvis_historique.json")

# --- Pont Obsidian (optionnel) ---
try:
    from jarvis_actions.obsidian_memory import ObsidianBridge, auto_detect_vault
    _vault = os.getenv("OBSIDIAN_VAULT") or auto_detect_vault()
    OBSIDIAN = ObsidianBridge(_vault) if _vault else None
    if OBSIDIAN:
        print(f"[OBSIDIAN] Memoire persistante reliee a : {_vault}")
    else:
        print("[OBSIDIAN] Aucun vault detecte (defini OBSIDIAN_VAULT pour activer).")
except Exception as e:
    print(f"[OBSIDIAN] Pont desactive : {e}")
    OBSIDIAN = None


def charger_memoire():
    if os.path.exists(MEMOIRE_FILE):
        try:
            with open(MEMOIRE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def sauvegarder_memoire(memoire):
    try:
        with open(MEMOIRE_FILE, "w", encoding="utf-8") as f:
            json.dump(memoire, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Erreur sauvegarde memoire : {e}")

def ajouter_memoire(cle, valeur):
    memoire      = charger_memoire()
    timestamp    = time.strftime("%d/%m/%Y %H:%M")
    memoire[cle] = {"valeur": valeur, "timestamp": timestamp}
    sauvegarder_memoire(memoire)
    if OBSIDIAN:
        try:
            OBSIDIAN.save_memory(cle, valeur, timestamp)
        except Exception as e:
            print(f"[OBSIDIAN] Echec ecriture memoire : {e}")
    # Indexation vectorielle (RAG) DEPORTEE dans un thread : indexer() fait un
    # appel reseau Ollama (jusqu'a 30s) ; le lancer inline gelerait l'event loop
    # car ajouter_memoire est souvent appele depuis une coroutine.
    _rag_en_arriere_plan("indexer", cle, valeur, timestamp)

def _rag_en_arriere_plan(operation: str, cle: str, valeur: str = "", timestamp: str = "") -> None:
    """Lance une operation RAG (indexer/supprimer) dans un thread daemon.

    indexer()/supprimer() font du reseau (embeddings Ollama) : on ne les execute
    JAMAIS sur l'event loop. Fire-and-forget, jamais d'exception propagee."""
    _rag = globals().get("memory_rag")
    if _rag is None:
        return

    def _travail():
        try:
            if not _rag.disponible():
                return
            if operation == "indexer":
                _rag.indexer(cle, valeur, timestamp)
            elif operation == "supprimer":
                _rag.supprimer(cle)
        except Exception as e:
            print(f"[RAG] Echec {operation} '{cle}' : {e}")

    try:
        threading.Thread(target=_travail, daemon=True).start()
    except Exception as e:
        print(f"[RAG] Echec lancement thread {operation} : {e}")

def supprimer_memoire(cle):
    memoire = charger_memoire()
    if cle in memoire:
        del memoire[cle]
        sauvegarder_memoire(memoire)
        if OBSIDIAN:
            try:
                OBSIDIAN.delete_memory(cle)
            except Exception as e:
                print(f"[OBSIDIAN] Echec suppression : {e}")
        # Retrait de l'index vectoriel (RAG) dans un thread (appel reseau).
        _rag_en_arriere_plan("supprimer", cle)
        return True
    return False


def synchroniser_memoire_obsidian():
    """Fusionne la memoire JSON locale avec celle d'Obsidian au demarrage."""
    if not OBSIDIAN:
        return
    locale = charger_memoire()
    distante = OBSIDIAN.load_all_memories()
    fusion = dict(distante)
    fusion.update(locale)
    sauvegarder_memoire(fusion)
    for k, v in fusion.items():
        try:
            OBSIDIAN.save_memory(k, v.get("valeur", ""), v.get("timestamp"))
        except Exception:
            pass
    print(f"[OBSIDIAN] {len(fusion)} memoires synchronisees.")


def charger_historique():
    """Charge l'historique de conversation depuis le disque."""
    if not os.path.exists(HISTORIQUE_FILE):
        return []
    try:
        with open(HISTORIQUE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [
            types.Content(
                role=item["role"],
                parts=[types.Part(text=item["text"])],
            )
            for item in data
        ]
    except Exception as e:
        print(f"[HIST] Echec chargement historique : {e}")
        return []


def sauvegarder_historique(historique_local):
    try:
        data = [
            {"role": h.role, "text": h.parts[0].text if h.parts else ""}
            for h in historique_local[-200:]
        ]
        with open(HISTORIQUE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[HIST] Echec sauvegarde historique : {e}")


try:
    from jarvis_actions import pc_actions
except Exception as e:
    print(f"[PC] Module pc_actions desactive : {e}")
    pc_actions = None

try:
    from jarvis_actions import dev_actions
except Exception as e:
    print(f"[DEV] Module dev_actions desactive : {e}")
    dev_actions = None

try:
    from jarvis_actions import claude_bridge
    CLAUDE_INACTIVITE_SEUIL_JOURS = float(os.getenv("CLAUDE_INACTIVITE_SEUIL_JOURS", "3"))
except Exception as e:
    print(f"[CLAUDE] Module claude_bridge desactive : {e}")
    claude_bridge = None
    CLAUDE_INACTIVITE_SEUIL_JOURS = 3

# Proactivite (PR D) : routines programmees + triggers contextuels.
# Imports tolerants -> None si echec (modules optionnels). Sans eux, le
# comportement reste strictement identique a aujourd'hui.
try:
    from jarvis_actions import routines
except Exception as e:
    print(f"[ROUTINES] Module routines desactive : {e}")
    routines = None

try:
    from jarvis_actions import triggers
except Exception as e:
    print(f"[TRIGGERS] Module triggers desactive : {e}")
    triggers = None

try:
    from jarvis_actions import meross
except Exception as e:
    print(f"[MEROSS] Module meross desactive : {e}")
    meross = None

# Connecteurs (PR E) : Spotify (API officielle) + bridge Telegram/Discord.
# Imports tolerants -> None si echec (modules optionnels, libs paresseuses a
# l'interieur). Sans eux ou sans config (.env), le comportement reste identique.
try:
    from jarvis_actions import spotify
except Exception as e:
    print(f"[SPOTIFY] Module spotify desactive : {e}")
    spotify = None

try:
    from jarvis_actions import messaging_bridge
except Exception as e:
    print(f"[MESSAGING] Module messaging_bridge desactive : {e}")
    messaging_bridge = None

try:
    from jarvis_actions import openclaw
except Exception as e:
    print(f"[OPENCLAW] Module openclaw desactive : {e}")
    openclaw = None

try:
    from jarvis_actions import browser as jarvis_browser
except Exception as e:
    print(f"[BROWSER] Module browser desactive : {e}")
    jarvis_browser = None

try:
    from jarvis_actions import agent as jarvis_agent
except Exception as e:
    print(f"[AGENT] Module agent desactive : {e}")
    jarvis_agent = None

try:
    from jarvis_actions import openjarvis_brain
    if openjarvis_brain.is_available() and openjarvis_brain.is_agent_enabled():
        try:
            from jarvis_actions import openjarvis_tools
            openjarvis_tools.register_jarvis_tools()
            tools = openjarvis_tools.list_registered_tools()
            print(f"[OPENJARVIS] Mode AGENT active. Tools enregistres: {tools}")
        except Exception as e:
            print(f"[OPENJARVIS] Echec enregistrement tools : {e}")
    elif openjarvis_brain.is_enabled() and openjarvis_brain.is_available():
        print("[OPENJARVIS] Cerveau OpenJarvis active (USE_OPENJARVIS=1).")
    elif openjarvis_brain.is_enabled():
        print("[OPENJARVIS] USE_OPENJARVIS=1 mais le package n'est pas importable.")
except Exception as e:
    print(f"[OPENJARVIS] Module openjarvis_brain desactive : {e}")
    openjarvis_brain = None

try:
    from jarvis_actions import display_actions
except Exception as e:
    print(f"[DISPLAY] Module display_actions desactive : {e}")
    display_actions = None

try:
    from jarvis_actions import skills_loader
    skills_loader.charger_skills()
except Exception as e:
    print(f"[SKILLS] Module skills_loader desactive : {e}")
    skills_loader = None

try:
    from jarvis_actions import mcp_client
except Exception as e:
    print(f"[MCP] Module mcp_client desactive : {e}")
    mcp_client = None

# Memoire vectorielle (RAG) : embeddings locaux via Ollama. Tout le code en aval
# verifie memory_rag.disponible() avant usage -> degradation propre si absent.
try:
    from jarvis_actions import memory_rag
except Exception as e:
    print(f"[RAG] Module memory_rag desactive : {e}")
    memory_rag = None

# Extraction proactive de faits durables (OPT-IN via JARVIS_MEMOIRE_PROACTIVE=1).
try:
    from jarvis_actions import memory_proactive
except Exception as e:
    print(f"[PROACTIF] Module memory_proactive desactive : {e}")
    memory_proactive = None

# Resume automatique de l'historique quand il devient trop long.
try:
    from jarvis_actions import history_summary
except Exception as e:
    print(f"[RESUME] Module history_summary desactive : {e}")
    history_summary = None

# ==========================================================================
# Voix avancee (OPT-IN) : STT local, wake word local, barge-in.
# Imports tolerants -> None si echec (les libs lourdes faster-whisper /
# openwakeword sont chargees paresseusement DANS ces modules). Quand les
# flags sont OFF, le comportement reste STRICTEMENT identique a aujourd'hui.
# ==========================================================================
try:
    from jarvis_actions import voice_stt
except Exception as e:
    print(f"[STT] Module voice_stt desactive : {e}")
    voice_stt = None

try:
    from jarvis_actions import wake_word
except Exception as e:
    print(f"[WAKE] Module wake_word desactive : {e}")
    wake_word = None

try:
    from jarvis_actions import barge_in
except Exception as e:
    print(f"[BARGE] Module barge_in desactive : {e}")
    barge_in = None

# Flags voix (defaut OFF = comportement actuel inchange).
# JARVIS_STT_LOCAL  : "1" = STT local faster-whisper au lieu de recognize_google.
# JARVIS_WAKE_LOCAL : "1" = wake word local openWakeWord en pre-gate.
# JARVIS_BARGE_IN   : "1" = interruption du TTS quand l'utilisateur parle.
STT_LOCAL  = os.getenv("JARVIS_STT_LOCAL", "0") == "1"
WAKE_LOCAL = os.getenv("JARVIS_WAKE_LOCAL", "0") == "1"
BARGE_IN   = os.getenv("JARVIS_BARGE_IN", "0") == "1"

# Flags d'activation (defauts preservent le comportement actuel).
# JARVIS_RESUME_HISTORIQUE : "1" (defaut) = resume l'historique long.
# JARVIS_MEMOIRE_PROACTIVE : "1" = extrait des faits durables (defaut OFF).
RESUME_HISTORIQUE = os.getenv("JARVIS_RESUME_HISTORIQUE", "1") == "1"
MEMOIRE_PROACTIVE = os.getenv("JARVIS_MEMOIRE_PROACTIVE", "0") == "1"

try:
    import jarvis_profile
except Exception as e:
    print(f"[PROFIL] Module jarvis_profile desactive : {e}")
    jarvis_profile = None

try:
    import jarvis_dashboard_api
    jarvis_dashboard_api.init_api({
        "charger_memoire": charger_memoire,
        "ajouter_memoire": ajouter_memoire,
        "supprimer_memoire": supprimer_memoire,
        "user_name": lambda: USER_NAME,
        # OBSIDIAN est defini plus haut au runtime ; globals() evite un NameError
        # si l'ordre d'initialisation change.
        "obsidian_actif": lambda: globals().get("OBSIDIAN") is not None,
        # IP LAN pour que le dashboard construise le lien d'appairage mobile
        # (http://<LAN_IP>:8080/?token=...). Le token est lu cote dashboard via
        # import direct de jarvis_security (jamais expose ici).
        "lan_ip": LAN_IP,
        # Execution d'une commande Jarvis (bouton "Tester" d'une routine). Lambda
        # a liaison tardive : _executer_commande_proactive est defini plus bas
        # dans le module mais resolu seulement a l'appel.
        "executer_commande": lambda texte: _executer_commande_proactive(texte),
    })
except Exception as e:
    print(f"[DASHBOARD] Module jarvis_dashboard_api desactive : {e}")
    jarvis_dashboard_api = None


def consigner_echange(role_user_or_model, texte):
    """Note un echange dans Obsidian si dispo."""
    if not OBSIDIAN:
        return
    try:
        OBSIDIAN.append_conversation(role_user_or_model, texte)
    except Exception as e:
        print(f"[OBSIDIAN] Echec consignation : {e}")

def construire_contexte_memoire(query: str | None = None):
    """Construit le bloc memoire injecte dans le prompt systeme.

    Si une `query` est fournie ET que le RAG est disponible ET que la memoire est
    assez grande (>12 entrees), on ne renvoie QUE les souvenirs pertinents (RAG)
    pour eviter de gonfler le prompt. Sinon : comportement historique (toute la
    memoire). Toute erreur RAG -> repli silencieux sur la memoire complete."""
    memoire = charger_memoire()
    if not memoire:
        return ""

    # RAG cible : recherche semantique des souvenirs lies a la requete courante.
    _rag = globals().get("memory_rag")
    if query and _rag is not None and len(memoire) > 12:
        try:
            if _rag.disponible():
                resultats = _rag.rechercher(query, k=6)
                if resultats:
                    lignes = ["SOUVENIRS PERTINENTS :"]
                    for r in resultats:
                        cle = r.get("cle", "")
                        valeur = r.get("valeur", "")
                        lignes.append(f"  - {cle} : {valeur}")
                    return "\n".join(lignes)
        except Exception as e:
            print(f"[RAG] Echec recherche contexte : {e}")
        # Pas de resultat ou erreur -> on retombe sur la memoire complete ci-dessous.

    lignes = ["MEMOIRE PERSISTANTE :"]
    for cle, data in memoire.items():
        lignes.append(f"  - {cle} : {data['valeur']} (note le {data['timestamp']})")
    return "\n".join(lignes)


# ==========================================
# WEBSOCKET
# ==========================================
CONNECTED_CLIENTS = set()
# Clients authentifies : loopback (auto) ou LAN ayant fourni un token valide.
# Seuls ces clients recoivent les broadcasts de conversation et peuvent envoyer
# des commandes. Voir _client_est_local + le handler {"type":"auth"}.
AUTHED_CLIENTS = set()
interface_deja_connectee = False
_skip_pc_audio = False  # True quand la commande vient du mobile (le tél gère son propre TTS)
IS_MUTED = False  # Mute persistant active depuis le frontend
PENDING_SCREEN_CAPTURES = {}


def _clients_diffusion():
    """Retourne les clients connectes ET authentifies (cibles des broadcasts).

    Les clients loopback sont toujours authentifies a la connexion ; les clients
    LAN ne le sont qu'apres un {"type":"auth"} valide. On intersecte avec
    CONNECTED_CLIENTS pour ne jamais viser un socket deja ferme."""
    return [ws for ws in CONNECTED_CLIENTS if ws in AUTHED_CLIENTS]

def _client_est_local(websocket) -> bool:
    """True si le client WebSocket vient de la machine locale (loopback).
    Garde-fou pour les messages dash_* (config sensible) : le WS ecoute sur
    0.0.0.0 sans authentification, on limite donc la config au PC lui-meme."""
    try:
        addr = getattr(websocket, "remote_address", None)
        host = addr[0] if addr else ""
        # IPv4 loopback (127.0.0.0/8), IPv6 loopback, et forme mappee IPv4.
        return (
            host in ("127.0.0.1", "::1", "localhost")
            or host.startswith("127.")
            or host in ("::ffff:127.0.0.1",)
        )
    except Exception:
        return False


async def ws_handler(websocket):
    global interface_deja_connectee
    CONNECTED_CLIENTS.add(websocket)
    # Les clients loopback (orbe locale, dashboard, jarvis_notify) sont
    # auto-authentifies : ils tournent sur le PC, aucun token requis.
    if _client_est_local(websocket):
        AUTHED_CLIENTS.add(websocket)
    interface_deja_connectee = True
    print(f"[WEB] Interface connectee (Clients actifs: {len(CONNECTED_CLIENTS)})")
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                # Messages du dashboard de configuration (dash_*) : deleguees au routeur dedie.
                # SECURITE : le dashboard ecrit le .env, lance des serveurs MCP (process
                # arbitraires) et expose profil/memoire. Le WS ecoute sur 0.0.0.0 sans auth,
                # donc on RESTREINT ces messages aux clients loopback (le dashboard tourne sur
                # le PC). Le mobile utilise mobile_command et n'est pas impacte.
                if isinstance(data.get("type"), str) and data["type"].startswith("dash_"):
                    if not _client_est_local(websocket):
                        print("[DASHBOARD] Message dash_* refuse (client non local).")
                        await websocket.send(json.dumps({
                            "action": "dash_error",
                            "error": "Configuration accessible uniquement depuis le PC local.",
                        }))
                        continue
                    # dash_memory_search est route par jarvis_dashboard_api._h_memory_search
                    # qui deporte l'appel RAG (reseau) dans un executor : on NE le traite
                    # PAS inline ici (ce serait bloquant pour l'event loop).
                    if jarvis_dashboard_api and await jarvis_dashboard_api.traiter_message_dashboard(data, websocket):
                        continue

                # Authentification par token (clients LAN/mobile). Les loopback
                # sont deja dans AUTHED_CLIENTS ; ce message reste tolere pour eux.
                if data.get("type") == "auth":
                    token = data.get("token", "")
                    # Un client loopback est deja authentifie a la connexion : on
                    # repond ok=true meme s'il n'a pas envoye de token (sinon la
                    # mobile ouverte sur le PC se verrouillerait a tort).
                    ok = bool(
                        websocket in AUTHED_CLIENTS
                        or (
                            jarvis_security is not None
                            and isinstance(token, str)
                            and jarvis_security.verifier_token(token)
                        )
                    )
                    if ok:
                        AUTHED_CLIENTS.add(websocket)
                        print("[AUTH] Client authentifie.")
                    else:
                        print("[AUTH] Token refuse.")
                    try:
                        await websocket.send(json.dumps({"action": "auth_result", "ok": ok}))
                    except Exception:
                        pass
                    continue

                # Gate : un client non authentifie (donc LAN non appaire) ne peut
                # envoyer aucune commande/donnee. On l'invite a s'appairer et on
                # ignore le message. Les loopback passent toujours (deja authes).
                if websocket not in AUTHED_CLIENTS:
                    try:
                        await websocket.send(json.dumps({"action": "auth_required"}))
                    except Exception:
                        pass
                    continue

                if data.get("type") == "mobile_command":
                    texte = data.get("text", "").strip()
                    if texte:
                        print(f"[MOBILE] Commande recue : {texte}")
                        asyncio.ensure_future(traiter_reponse_ia(texte, mobile_ws=websocket))
                elif data.get("type") == "text_command":
                    texte = data.get("text", "").strip()
                    repondre_vocal = bool(data.get("vocal", True))
                    if texte:
                        print(f"[WEB-TEXT] Commande tapee : {texte} (vocal={repondre_vocal})")
                        asyncio.ensure_future(
                            traiter_reponse_ia(texte, repondre_vocal=repondre_vocal)
                        )
                elif data.get("type") == "external_say":
                    texte = data.get("text", "").strip()
                    if texte:
                        print(f"[EXTERNAL] {texte}")
                        asyncio.ensure_future(parler(texte))
                elif data.get("type") == "request_history":
                    limit = int(data.get("limit", 80))
                    items = []
                    for h in historique[-limit:]:
                        try:
                            txt = h.parts[0].text if h.parts else ""
                            if txt.startswith("[Information retournée"):
                                continue
                            items.append({
                                "role": "user" if h.role == "user" else "jarvis",
                                "text": txt,
                            })
                        except Exception:
                            continue
                    await websocket.send(json.dumps({"action": "history", "items": items}))
                elif data.get("type") == "request_conversations":
                    days = []
                    if OBSIDIAN:
                        try:
                            files = sorted(
                                OBSIDIAN.dir_conversations.glob("*.md"),
                                key=lambda p: p.stat().st_mtime,
                                reverse=True,
                            )
                            for f in files[:30]:
                                days.append({
                                    "date": f.stem,
                                    "size": f.stat().st_size,
                                })
                        except Exception as e:
                            print(f"[OBSIDIAN] list jours echec : {e}")
                    await websocket.send(json.dumps({"action": "conversations_list", "days": days}))
                elif data.get("type") == "request_conversation":
                    date = data.get("date", "")
                    content = ""
                    if OBSIDIAN and date:
                        try:
                            f = OBSIDIAN.dir_conversations / f"{date}.md"
                            if f.exists():
                                content = f.read_text(encoding="utf-8")
                        except Exception as e:
                            print(f"[OBSIDIAN] read jour echec : {e}")
                    await websocket.send(json.dumps({"action": "conversation_content", "date": date, "content": content}))
                elif data.get("type") == "stop_audio":
                    global STOP_PARLER
                    STOP_PARLER = True
                    print("[MOBILE] Signal STOP audio recu")
                elif data.get("type") == "set_mute":
                    global IS_MUTED
                    IS_MUTED = bool(data.get("muted", False))
                    if IS_MUTED:
                        STOP_PARLER = True
                    print(f"[WEB] Mute persistant : {IS_MUTED}")
                elif data.get("type") == "screen_frame":
                    req_id = data.get("id")
                    if req_id in PENDING_SCREEN_CAPTURES:
                        fut = PENDING_SCREEN_CAPTURES.pop(req_id)
                        if "error" in data:
                            fut.set_exception(Exception(data["error"]))
                        else:
                            fut.set_result(data["data"])
                    print(f"[VISION] Frame recue pour ID: {req_id}")
            except Exception as e:
                print(f"[WEB] Erreur traitement message : {e}")
    except Exception:
        pass
    finally:
        CONNECTED_CLIENTS.discard(websocket)
        AUTHED_CLIENTS.discard(websocket)
        print(f"[WEB] Interface deconnectee (Clients actifs: {len(CONNECTED_CLIENTS)})")

async def send_web_state(state):
    # Diffuse uniquement aux clients authentifies (loopback inclus d'office).
    cibles = _clients_diffusion()
    if cibles:
        message = json.dumps({"action": "set_state", "state": state})
        await asyncio.gather(*[ws.send(message) for ws in cibles], return_exceptions=True)

async def send_web_volume(volume):
    cibles = _clients_diffusion()
    if cibles:
        message = json.dumps({"action": "set_volume", "volume": round(volume, 3)})
        await asyncio.gather(*[ws.send(message) for ws in cibles], return_exceptions=True)


async def broadcast_chat(role, text):
    """Envoie un message de chat au frontend pour l'afficher dans la mini-UI."""
    cibles = _clients_diffusion()
    if not cibles or not text:
        return
    payload = json.dumps({
        "action": "chat_message",
        "role": role,
        "text": text,
        "ts": time.strftime("%H:%M:%S"),
    })
    await asyncio.gather(*[ws.send(payload) for ws in cibles], return_exceptions=True)

async def request_screen_capture():
    """Demande une capture d'écran au frontend via WebSocket."""
    cibles = _clients_diffusion()
    if not cibles:
        return None

    req_id = str(uuid.uuid4())
    loop = asyncio.get_event_loop()
    fut = loop.create_future()
    PENDING_SCREEN_CAPTURES[req_id] = fut

    print(f"[VISION] Envoi requete capture ID: {req_id}")
    msg = json.dumps({"action": "request_screen_capture", "id": req_id})
    await asyncio.gather(*[ws.send(msg) for ws in cibles], return_exceptions=True)
    
    try:
        # Timeout de 15 secondes car l'utilisateur doit parfois accepter le partage
        img_b64 = await asyncio.wait_for(fut, timeout=15.0)
        return img_b64
    except Exception as e:
        print(f"[VISION] Erreur ou timeout capture : {e}")
        PENDING_SCREEN_CAPTURES.pop(req_id, None)
        return None

# ==========================================
# PROMPT SYSTEME
# ==========================================
def construire_system_prompt(query: str | None = None):
    # `query` = texte utilisateur courant, transmis pour la recherche RAG ciblee.
    # Defaut None -> comportement historique (toute la memoire).
    contexte_memoire = construire_contexte_memoire(query)
    base = (
        f"Tu es JARVIS, une IA sophistiquée, élégante et experte mondiale. {USER_NAME} est ton créateur. "
        "Tu possèdes une expertise de niveau professionnel dans les domaines suivants :\n"
        f"- Mathématiques : Tu es un mathématicien hors pair. Pour les problèmes complexes, fournis des solutions détaillées étape par étape, explique les théorèmes et aide {USER_NAME} à comprendre la logique mathématique.\n"
        "- Langue Française : Tu es un Professeur de Français émérite. Ton orthographe, ta grammaire et ta syntaxe sont irréprochables. Tu peux expliquer des règles complexes, analyser des textes littéraires et aider à la rédaction de documents élégants.\n"
        "- Expert en Conversions : Tu es un convertisseur universel. Tu peux transformer n'importe quelle unité (métrique, impériale, devises, informatique) avec précision.\n"
        f"- Polyglotte : Tu maîtrises parfaitement plusieurs langues. Tu peux traduire, expliquer des nuances linguistiques et aider {USER_NAME} à communiquer dans le monde entier.\n"
        "- High-Tech (IA, hardware, software), Mode, Loisirs, Ingénierie et Sport (analyses tactiques, résultats).\n\n"
        f"Tu es également un conseiller hors pair, capable de donner des astuces et conseils brillants pour simplifier la vie de {USER_NAME}.\n\n"
        "DIRECTIVES DE RÉPONSE :\n"
        f"- Sois direct, percutant et va à l'essentiel. Évite les détails superflus (comme les minutes exactes ou les décimales météo) sauf si {USER_NAME} le demande.\n"
        "- NE DIS JAMAIS 'POINT' pour les nombres. Arrondis toujours les températures à l'unité la plus proche (ex: dis '20 degrés' au lieu de '20.3').\n"
        "- N'UTILISE JAMAIS de caractères Markdown (comme **, * ou #) dans tes réponses, car ils sont lus à voix haute par le système de synthèse vocale.\n"
        "- Reste poli mais garde une touche de sarcasme affectueux propre à ton personnage.\n\n"
        + CREATOR_INFO
    )
    # Profil utilisateur enrichi (famille, adresse, habitudes — edite via le dashboard)
    if jarvis_profile:
        try:
            ctx_profil = jarvis_profile.contexte_profil()
            if ctx_profil:
                base += "\n\n" + ctx_profil + "\n"
        except Exception as e:
            print(f"[PROFIL] Echec contexte profil : {e}")
    base += (
        f"\n\nTu es connecte a Home Assistant, la domotique de {USER_NAME}.\n"
        f"Quand {USER_NAME} parle de lumieres, prises, chauffage, temperature, "
        "scenes ou alarme, tu DOIS generer une commande JSON.\n"
        "Pour CES demandes domotiques UNIQUEMENT, reponds avec le JSON ci-dessous. Pour TOUTES les autres questions (actualites, meteo, calculs, conversations, recherches internet...), reponds en texte normal.\n\n"
        "COMMANDES HOME ASSISTANT :\n"
        '{"action": "ha_lumiere", "piece": "salon", "etat": "on/off", "couleur": "rouge/bleu/blanc/...", "luminosite": 0-255}\n'
        f"Note : Pour la luminosité, 255 est le maximum (100%). Si {USER_NAME} dit '50%', utilise 127.\n"
        '{"action": "ha_prise", "piece": "bureau", "etat": "on/off"}\n'
        '{"action": "ha_temperature", "piece": "salon/chambre/bureau"}\n'
        '{"action": "ha_humidite", "piece": "bureau"}\n'
        '{"action": "ha_batterie", "appareil": "mon telephone/tablette/montre/aspirateur/..."}\n'
        '{"action": "ha_simulation", "etat": "on/off"}\n'
        '{"action": "ha_anniversaires"}\n'
        '{"action": "ha_consommation"}\n'
        '{"action": "ha_tiktok"}\n'
        '{"action": "ha_oeufs"}\n'
        '{"action": "ha_energie", "periode": "hier/mois", "appareil": "tv/salon/lave-vaisselle/bureau/..."}\n'
        '{"action": "ha_aspirateur", "commande": "start/stop/pause/base"}\n'
        '{"action": "ha_thermostat", "temperature": 21}\n'
        '{"action": "ha_scene", "nom": "cinema/diner/nuit/reveil"}\n'
        '{"action": "ha_alarme", "etat": "on/off"}\n\n'
    )
    base += (
        f"\n\nTu peux GERER LES FICHIERS ET DOSSIERS de {USER_NAME}.\n"
        '{"action": "ouvrir_dossier", "chemin": "bureau/documents/downloads/ou/chemin/complet"}\n'
        '{"action": "lister_dossier"}\n'
        '{"action": "trier_par_type"}\n'
        '{"action": "trier_par_date"}\n'
        '{"action": "trier_complet"}\n'
        '{"action": "creer_dossier", "nom": "NOM_DOSSIER"}\n'
        '{"action": "renommer_fichier", "ancien": "ancien.txt", "nouveau": "nouveau.txt"}\n'
        '{"action": "deplacer_fichier", "fichier": "photo.jpg", "destination": "Images"}\n'
        '{"action": "chercher_fichier", "nom": "rapport"}\n\n'
    )
    base += (
        "\n\nMETEO & RECHERCHE :\n"
        '{"action": "meteo", "ville": "NOM_VILLE_ou_null"}\n'
        '{"action": "alerte_meteo", "ville": "NOM_VILLE_ou_null"}\n'
        '{"action": "recherche_web", "query": "ta recherche ici"}\n\n'
    )
    base += (
        "\n\nSPORT :\n"
        '{"action": "sport_resultats", "equipe": "NOM_ou_null", "ligue": "NOM_LIGUE"}\n'
        '{"action": "sport_classement", "ligue": "NOM_LIGUE"}\n'
        f'{{"action": "sport_live", "question": "question complete de {USER_NAME}"}}\n\n'
    )
    base += (
        "\n\nMODE IRON MAN (Sécurité Domotique) :\n"
        '{"action": "mode_iron_man", "etat": "on/off"}\n'
        "Instructions : Active ou désactive la détection des applaudissements pour contrôler les lumières et YouTube.\n\n"
    )
    if contexte_memoire:
        base += "\n\n" + contexte_memoire + "\n"
    base += (
        "\nMEMOIRE :\n"
        '{"action": "memoriser", "cle": "CLE_COURTE", "valeur": "VALEUR_ICI"}\n'
        '{"action": "oublier", "cle": "CLE_ICI"}\n'
        '{"action": "lister_memoire"}\n\n'
        "GOOGLE :\n"
        '{"action": "create_doc", "title": "TITRE", "content": "CONTENU"}\n'
        '{"action": "write_doc", "content": "TEXTE"}\n'
        '{"action": "create_sheet", "title": "TITRE"}\n'
        '{"action": "read_emails"}\n'
        '{"action": "read_calendar"}\n\n'
        "WHATSAPP :\n"
        '{"action": "whatsapp_appel", "contact": "NOM_DU_CONTACT"}\n'
        "Le contact est le nom exact tel qu'enregistre dans WhatsApp.\n\n"
        "VISION (Interactions avec l'ecran):\n"
        '{"action": "voir_ecran", "instruction": "ou cliquer EXACTEMENT (ex: \'bouton reduire en haut a droite\')"}\n'
        '{"action": "vision_ecrire", "instruction": "ou cliquer", "texte": "le texte a taper"}\n'
        "IMPORTANT : Utilise 'voir_ecran' pour un simple CLIC, et 'vision_ecrire' UNIQUEMENT s'il faut TAPER du texte apres le clic.\n\n"
        "REGLES MULTI-COMMANDES :\n"
        f"Si {USER_NAME} demande plusieurs choses en une seule phrase, tu PEUX et DOIS générer plusieurs blocs JSON.\n"
        "Exemple: { \"action\": \"ha_lumiere\", ... } { \"action\": \"meteo\", ... }\n\n"
        "REGLE ABSOLUE : Si la demande n est PAS une commande JSON, reponds TOUJOURS en texte naturel, sans JSON."
    )
    return base

historique = charger_historique()
if historique:
    print(f"[HIST] {len(historique)} messages restaures depuis le disque.")
synchroniser_memoire_obsidian()


def _reindexer_rag_demarrage():
    """Reconstruit l'index vectoriel au demarrage si l'index est vide.

    Lance dans un thread daemon : l'embedding de toute la memoire peut prendre
    plusieurs secondes (un appel Ollama par entree) et ne doit JAMAIS bloquer le
    demarrage. Aucune exception ne remonte (degradation propre)."""
    if memory_rag is None:
        return
    try:
        if not memory_rag.disponible():
            print("[RAG] Embeddings indisponibles (Ollama/modele absent) — RAG inactif.")
            return
        if memory_rag.nb_indexes() == 0:
            n = memory_rag.reindexer_tout(charger_memoire())
            print(f"[RAG] Index vectoriel reconstruit : {n} entree(s).")
        else:
            print(f"[RAG] Index vectoriel deja present ({memory_rag.nb_indexes()} entree(s)).")
    except Exception as e:
        print(f"[RAG] Echec reindexation demarrage : {e}")


if memory_rag is not None:
    threading.Thread(target=_reindexer_rag_demarrage, daemon=True).start()

is_listening = False
is_speaking  = False
is_thinking  = False
speak_volume = 0.0

WAKE_WORD       = "jarvis"
SLEEP_PHRASES   = ["tais toi", "silence", "ferme-la", "arrete", "stop"]
jarvis_actif    = False
SESSION_TIMEOUT = 30.0
dernier_message = time.time()

dernier_doc_id    = None
dernier_doc_titre = None

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar",
]

# Chemins persistants des credentials Google : en mode .exe, le cwd est
# sys._MEIPASS (temporaire) — ecrire token.pickle dedans forcerait un
# re-OAuth a chaque lancement. On lit/ecrit a cote de l'exe a la place.
_GOOGLE_TOKEN_PATH = DOSSIER_DONNEES / "token.pickle"
_GOOGLE_CREDENTIALS_PATH = DOSSIER_DONNEES / "credentials.json"


def get_google_creds():
    creds = None
    if os.path.exists(_GOOGLE_TOKEN_PATH):
        with open(_GOOGLE_TOKEN_PATH, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(_GOOGLE_CREDENTIALS_PATH):
                print("[GOOGLE] Pas de credentials.json - fonctions Google desactivees.")
                return None
            flow  = InstalledAppFlow.from_client_secrets_file(str(_GOOGLE_CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(_GOOGLE_TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)
    return creds

def get_docs_service():
    creds = get_google_creds()
    return build("docs", "v1", credentials=creds) if creds else None

def get_drive_service():
    creds = get_google_creds()
    return build("drive", "v3", credentials=creds) if creds else None

def get_gmail_service():
    creds = get_google_creds()
    return build("gmail", "v1", credentials=creds) if creds else None

def get_sheets_service():
    creds = get_google_creds()
    return build("sheets", "v4", credentials=creds) if creds else None

def get_calendar_service():
    creds = get_google_creds()
    return build("calendar", "v3", credentials=creds) if creds else None

def creer_google_doc(titre="Nouveau Document", contenu=""):
    global dernier_doc_id, dernier_doc_titre
    try:
        service = get_docs_service()
        if not service:
            return "Google Docs non disponible."
        doc    = service.documents().create(body={"title": titre}).execute()
        doc_id = doc["documentId"]
        dernier_doc_id    = doc_id
        dernier_doc_titre = titre
        if contenu:
            requests_body = [{"insertText": {"location": {"index": 1}, "text": contenu}}]
            service.documents().batchUpdate(documentId=doc_id, body={"requests": requests_body}).execute()
        webbrowser.open(f"https://docs.google.com/document/d/{doc_id}/edit")
        return f"Document {titre} cree et ouvert, {USER_NAME}."
    except Exception as e:
        return f"Erreur Google Docs : {e}"

def modifier_google_doc(contenu, doc_id=None):
    global dernier_doc_id
    try:
        service   = get_docs_service()
        if not service:
            return "Google Docs non disponible."
        target_id = doc_id or dernier_doc_id
        if not target_id:
            return "Aucun document ouvert en memoire."
        doc       = service.documents().get(documentId=target_id).execute()
        end_index = doc["body"]["content"][-1]["endIndex"] - 1
        requests_body = [{"insertText": {"location": {"index": end_index}, "text": "\n" + contenu}}]
        service.documents().batchUpdate(documentId=target_id, body={"requests": requests_body}).execute()
        webbrowser.open(f"https://docs.google.com/document/d/{target_id}/edit")
        return f"Texte ajoute dans le document {dernier_doc_titre}."
    except Exception as e:
        return f"Erreur modification doc : {e}"

def lire_emails(max_results=3):
    try:
        service  = get_gmail_service()
        if not service:
            return "Gmail non disponible."
        results  = service.users().messages().list(userId="me", maxResults=max_results, labelIds=["INBOX"]).execute()
        messages = results.get("messages", [])
        if not messages:
            return "Aucun email trouve."
        reponse = ""
        for msg in messages:
            m       = service.users().messages().get(userId="me", id=msg["id"], format="metadata").execute()
            headers = {h["name"]: h["value"] for h in m["payload"]["headers"]}
            reponse += f"De: {headers.get('From','?')} | Sujet: {headers.get('Subject','?')}\n"
        return reponse.strip()
    except Exception as e:
        return f"Erreur Gmail : {e}"

def lister_evenements_calendar():
    try:
        service = get_calendar_service()
        if not service:
            return "Google Calendar non disponible."
        from datetime import datetime, timezone
        now    = datetime.now(timezone.utc).isoformat()
        events = service.events().list(calendarId="primary", timeMin=now, maxResults=5, singleEvents=True, orderBy="startTime").execute()
        items = events.get("items", [])
        if not items:
            return "Aucun evenement a venir."
        reponse = ""
        for e in items:
            start    = e["start"].get("dateTime", e["start"].get("date"))
            reponse += f"{start} : {e['summary']}\n"
        return reponse.strip()
    except Exception as e:
        return f"Erreur Calendar : {e}"

def creer_google_sheet(titre="Nouvelle Feuille"):
    try:
        service  = get_sheets_service()
        if not service:
            return "Google Sheets non disponible."
        sheet    = service.spreadsheets().create(body={"properties": {"title": titre}}).execute()
        sheet_id = sheet["spreadsheetId"]
        webbrowser.open(f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit")
        return f"Feuille {titre} creee et ouverte."
    except Exception as e:
        return f"Erreur Google Sheets : {e}"

async def jarvis_vision_cliquer(instruction):
    try:
        path_ss = "jarvis_vision_temp.png"
        screenshot = pyautogui.screenshot()
        screenshot.save(path_ss)
        img = Image.open(path_ss)
        prompt_vision = (
            f"Tu es la vision de JARVIS. Voici une capture de l'ecran de {USER_NAME}.\n"
            f"Instruction : {instruction}\n"
            "Trouve EXACTEMENT la position de cet element.\n"
            "Reponds UNIQUEMENT sous forme de JSON avec la bounding box normalisee (0 a 1000) sous le format [ymin, xmin, ymax, xmax].\n"
            "Exemple : {\"box\": [250, 480, 290, 520]}"
        )
        response = client.models.generate_content(model=CHOSEN_MODEL, contents=[prompt_vision, img])
        rep_text = response.text.strip()
        start = rep_text.find('{')
        end = rep_text.rfind('}')
        if start != -1 and end != -1:
            rep_text = rep_text[start:end+1]
        data = json.loads(rep_text)
        
        box = data.get("box", [500, 500, 500, 500])
        ymin, xmin, ymax, xmax = box
        
        # Calcul du centre
        center_y = (ymin + ymax) / 2
        center_x = (xmin + xmax) / 2
        
        screen_w, screen_h = pyautogui.size()
        target_x = int((center_x / 1000) * screen_w)
        target_y = int((center_y / 1000) * screen_h)
        pyautogui.moveTo(target_x, target_y, duration=0.4)
        pyautogui.click()
        os.remove(path_ss)
        return f"C'est fait {USER_NAME}. J'ai clique sur l'element correspondant a : {instruction}."
    except Exception as e:
        print(f"[VISION ERROR] {e}")
        return f"Je vois l'interface, mais je n'ai pas reussi a identifier l'element precis, {USER_NAME}."

async def jarvis_vision_ecrire(instruction, texte_a_taper):
    try:
        path_ss = "jarvis_vision_temp.png"
        screenshot = pyautogui.screenshot()
        screenshot.save(path_ss)
        img = Image.open(path_ss)
        prompt_vision = (
            f"Tu es la vision de JARVIS. {USER_NAME} veut ecrire dans le champ : {instruction}.\n"
            "Trouve EXACTEMENT la position de ce champ de saisie.\n"
            "Reponds UNIQUEMENT sous forme de JSON avec la bounding box normalisee (0 a 1000) sous le format [ymin, xmin, ymax, xmax].\n"
            "Exemple : {\"box\": [250, 480, 290, 520]}"
        )
        response = client.models.generate_content(model=CHOSEN_MODEL, contents=[prompt_vision, img])
        rep_text = response.text.strip()
        start = rep_text.find('{')
        end = rep_text.rfind('}')
        if start != -1 and end != -1:
            rep_text = rep_text[start:end+1]
        data = json.loads(rep_text)
        
        box = data.get("box", [500, 500, 500, 500])
        ymin, xmin, ymax, xmax = box
        
        # Calcul du centre
        center_y = (ymin + ymax) / 2
        center_x = (xmin + xmax) / 2
        
        screen_w, screen_h = pyautogui.size()
        target_x = int((center_x / 1000) * screen_w)
        target_y = int((center_y / 1000) * screen_h)
        pyautogui.moveTo(target_x, target_y, duration=0.4)
        pyautogui.click()
        time.sleep(0.3)
        pyautogui.write(texte_a_taper, interval=0.03)
        pyautogui.press('enter')
        os.remove(path_ss)
        return f"C'est fait {USER_NAME}. J'ai saisi '{texte_a_taper}' dans {instruction}."
    except Exception as e:
        print(f"[VISION ERROR] {e}")
        return f"J'ai eu un petit souci technique pour taper le texte, {USER_NAME}."

def ha_appeler_service(domaine, service, entity_id, donnees=None):
    try:
        payload = {"entity_id": entity_id}
        if donnees:
            payload.update(donnees)
        print(f"[HA DEBUG] Calling {domaine}/{service} for {entity_id} with {donnees}")
        r = requests.post(f"{HA_URL}/api/services/{domaine}/{service}", headers=HA_HEADERS, json=payload, timeout=5)
        print(f"[HA DEBUG] Response {r.status_code}: {r.text}")
        return r.status_code in [200, 201]
    except Exception as e:
        print(f"[HA] Erreur service : {e}")
        return False

def ha_get_etat(entity_id, attribut=None):
    try:
        r    = requests.get(f"{HA_URL}/api/states/{entity_id}", headers=HA_HEADERS, timeout=5)
        data = r.json()
        if attribut:
            return data.get("attributes", {}).get(attribut, "inconnu")
        return data.get("state", "inconnu")
    except Exception as e:
        print(f"[HA] Erreur get etat : {e}")
        return "inconnu"

def ha_get_calendrier(entity_id):
    try:
        now = datetime.now()
        start = now.strftime("%Y-%m-%dT00:00:00Z")
        end = now.strftime("%Y-%m-%dT23:59:59Z")
        r = requests.get(
            f"{HA_URL}/api/calendars/{entity_id}",
            headers=HA_HEADERS,
            params={"start": start, "end": end},
            timeout=5
        )
        return r.json()
    except Exception as e:
        print(f"[HA] Erreur calendrier : {e}")
        return []

def ha_lumiere(entity_id, etat="on", luminosite=None, rgb=None):
    service_name = "toggle" if etat == "toggle" else ("turn_on" if etat == "on" else "turn_off")
    donnees = {}
    if etat == "on":
        if luminosite is not None:
            donnees["brightness"] = int(luminosite)
        if rgb is not None:
            donnees["rgb_color"] = rgb
    return ha_appeler_service("light", service_name, entity_id, donnees)

def ha_interrupteur(entity_id, etat="on"):
    service_name = "turn_on" if etat == "on" else "turn_off"
    return ha_appeler_service("switch", service_name, entity_id)

def ha_thermostat(entity_id, temperature):
    return ha_appeler_service("climate", "set_temperature", entity_id, {"temperature": temperature})

def ha_scene(scene_id):
    return ha_appeler_service("scene", "turn_on", scene_id)

def recherche_web_serpapi(query):
    """Effectue une recherche sur Google via SerpAPI."""
    if not SERPAPI_API_KEY or SERPAPI_API_KEY == "VOTRE_CLE_ICI":
        return f"{USER_NAME}, la clé SerpAPI n'est pas configurée dans le fichier d'environnement."
    
    try:
        print(f"[WEB] Recherche SerpAPI pour : {query}")
        params = {
            "engine": "google",
            "q": query,
            "api_key": SERPAPI_API_KEY,
            "hl": "fr",
            "gl": "fr"
        }
        r = requests.get("https://serpapi.com/search.json", params=params, timeout=10)
        data = r.json()
        
        # Extraction des actualités si présentes
        if "news_results" in data:
            news = data["news_results"][:3]
            reponse = f"Voici les dernières actualités pour {query} :\n"
            for n in news:
                source = n.get("source", "Source inconnue")
                titre = n.get("title", "")
                reponse += f"- {titre} (via {source})\n"
            return reponse
            
        # Extraction des résultats organiques sinon
        if "organic_results" in data:
            results = data["organic_results"][:3]
            reponse = f"Voici ce que j'ai trouvé sur le web pour {query} :\n"
            for r in results:
                titre = r.get("title", "")
                snippet = r.get("snippet", "")
                reponse += f"- {titre} : {snippet}\n"
            return reponse
            
        return f"Je n'ai rien trouvé de pertinent sur le web pour : {query}."
    except Exception as e:
        print(f"[WEB] Erreur SerpAPI : {e}")
        return "Une erreur est survenue lors de la recherche sur internet."

# Config Home Assistant (entites perso). Chargee depuis jarvis_home_config.py
# (gitignore, valeurs reelles) avec repli sur l'exemple generique commite.
try:
    from jarvis_home_config import (
        PIECES_LUMIERES, PIECES_PRISES, PIECES_CAPTEURS, PIECES_HUMIDITE,
        HA_TARIFS, APPAREILS_ENERGIE, APPAREILS_BATTERIE,
    )
except ImportError:
    from jarvis_home_config_example import (
        PIECES_LUMIERES, PIECES_PRISES, PIECES_CAPTEURS, PIECES_HUMIDITE,
        HA_TARIFS, APPAREILS_ENERGIE, APPAREILS_BATTERIE,
    )

COULEURS_MAP = {
    "rouge"      : [255, 0,   0  ],
    "bleu"       : [0,   0,   255],
    "vert"       : [0,   255, 0  ],
    "blanc"      : [255, 255, 255],
    "orange"     : [255, 140, 0  ],
    "violet"     : [148, 0,   211],
    "rose"       : [255, 20,  147],
    "jaune"      : [255, 255, 0  ],
    "cyan"       : [0,   255, 255],
    "magenta"    : [255, 0,   255],
    "turquoise"  : [64,  224, 208],
    "or"         : [255, 215, 0  ],
    "argent"     : [192, 192, 192],
    "indigo"     : [75,  0,   130],
    "marron"     : [139, 69,  19 ],
    "citron"     : [255, 250, 0  ],
    "corail"     : [255, 127, 80 ],
    "lavande"    : [230, 230, 250],
}

CODES_METEO = {
    0:  "ciel degage",
    1:  "principalement clair", 2: "partiellement nuageux", 3: "couvert",
    45: "brouillard", 48: "brouillard givrant",
    51: "bruine legere", 53: "bruine moderee", 55: "bruine dense",
    61: "pluie faible", 63: "pluie moderee", 65: "pluie forte",
    71: "neige faible", 73: "neige moderee", 75: "neige forte",
    80: "averses faibles", 81: "averses moderees", 82: "averses violentes",
    85: "averses de neige", 86: "averses de neige fortes",
    95: "orage", 96: "orage avec grele", 99: "orage violent avec grele",
}

def geocoder_ville(ville):
    try:
        r = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": ville, "count": 1, "language": "fr", "format": "json"},
            timeout=5
        )
        data = r.json()
        if data.get("results"):
            res = data["results"][0]
            return res["latitude"], res["longitude"], res.get("name", ville), res.get("country", "")
    except Exception as e:
        print(f"[METEO] Erreur geocoding : {e}")
    return None, None, ville, ""

def get_meteo_actuelle(ville=None):
    try:
        nom_ville = ville or VILLE_PAR_DEFAUT
        lat, lon, nom_affiche, pays = geocoder_ville(nom_ville)
        if lat is None:
            lat, lon = LAT_PAR_DEFAUT, LON_PAR_DEFAUT
            nom_affiche = VILLE_PAR_DEFAUT
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude"      : lat, "longitude": lon,
                "current"       : "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,wind_direction_10m,weathercode,precipitation",
                "hourly"        : "temperature_2m,precipitation_probability",
                "daily"         : "temperature_2m_max,temperature_2m_min,weathercode,precipitation_sum,wind_speed_10m_max,sunrise,sunset",
                "timezone"      : "Europe/Paris",
                "forecast_days" : 3,
                "wind_speed_unit": "kmh",
            },
            timeout=8
        )
        data  = r.json()
        cur   = data["current"]
        daily = data["daily"]
        code     = cur.get("weathercode", 0)
        desc     = CODES_METEO.get(code, "conditions inconnues")
        temp     = round(float(cur.get("temperature_2m", 0)))
        
        reponse = f"À {nom_affiche}, il fait {temp} degrés et le ciel est {desc}. C'est tout."
        return reponse
    except Exception as e:
        print(f"[METEO] Erreur : {e}")
        return "Je n'arrive pas à récupérer la météo pour le moment."

def get_alertes_meteo(ville=None):
    try:
        nom_ville = ville or VILLE_PAR_DEFAUT
        lat, lon, nom_affiche, _ = geocoder_ville(nom_ville)
        if lat is None:
            lat, lon, nom_affiche = LAT_PAR_DEFAUT, LON_PAR_DEFAUT, VILLE_PAR_DEFAUT
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat, "longitude": lon,
                "daily"   : "weathercode,precipitation_sum,wind_speed_10m_max",
                "timezone": "Europe/Paris", "forecast_days": 3,
            },
            timeout=8
        )
        data  = r.json()
        daily = data["daily"]
        alertes = []
        for i in range(len(daily["weathercode"])):
            code  = daily["weathercode"][i]
            pluie = daily.get("precipitation_sum", [0]*3)[i] or 0
            vent  = daily.get("wind_speed_10m_max", [0]*3)[i] or 0
            jour  = ["aujourd hui", "demain", "apres-demain"][i]
            if code in [95, 96, 99]:
                alertes.append(f"Orage prevu {jour}")
            if code in [71, 73, 75, 85, 86]:
                alertes.append(f"Neige prevue {jour}")
            if pluie > 20:
                alertes.append(f"Fortes pluies {jour} ({pluie}mm)")
            if vent > 60:
                alertes.append(f"Vents forts {jour} ({vent} km/h)")
        if alertes:
            return f"Alertes meteo pour {nom_affiche} : " + ", ".join(alertes) + "."
        return f"Aucune alerte meteo pour {nom_affiche} dans les 3 prochains jours."
    except Exception as e:
        return f"Impossible de verifier les alertes meteo : {e}"

THESPORTSDB_BASE = "https://www.thesportsdb.com/api/v1/json/3"

def get_resultats_football(equipe=None, ligue=None):
    try:
        if equipe:
            print(f"[SPORT] Recherche pour l'equipe : {equipe}")
            r = requests.get(f"{THESPORTSDB_BASE}/searchteams.php", params={"t": equipe}, timeout=5)
            data = r.json()
            teams = data.get("teams")
            if not teams:
                return f"Je n'ai pas trouvé l'équipe {equipe}."
            
            team_id   = teams[0]["idTeam"]
            team_name = teams[0]["strTeam"]
            
            # On cherche les derniers ET les prochains matchs
            res_last = requests.get(f"{THESPORTSDB_BASE}/eventslast.php", params={"id": team_id}, timeout=5).json()
            res_next = requests.get(f"{THESPORTSDB_BASE}/eventsnext.php", params={"id": team_id}, timeout=5).json()
            
            matchs_passes = res_last.get("results", [])
            matchs_futurs = res_next.get("events", [])
            
            reponse = f"Concernant le {team_name} : "
            
            if matchs_futurs:
                m = matchs_futurs[0]
                date_m = m.get("dateEvent", "date inconnue")
                heure_m = m.get("strTime", "")
                reponse += f"Le prochain match aura lieu le {date_m} à {heure_m} contre {m.get('strOpponent')}. "
            
            if matchs_passes:
                m = matchs_passes[0]
                reponse += f"Leur dernier résultat était {m.get('intHomeScore')} à {m.get('intAwayScore')} contre {m.get('strOpponent')}."
            
            if not matchs_futurs and not matchs_passes:
                return f"Je n'ai pas d'informations récentes ou futures pour {team_name}."
                
            return reponse
        else:
            nom_ligue = ligue or "Ligue 1"
            ligue_ids = {
                "ligue 1": "4334", "premier league": "4328", "liga": "4335",
                "bundesliga": "4331", "serie a": "4332",
                "champions league": "4480", "ligue des champions": "4480",
            }
            ligue_id = ligue_ids.get(nom_ligue.lower(), "4334")
            r = requests.get(f"{THESPORTSDB_BASE}/eventspastleague.php", params={"id": ligue_id}, timeout=5)
            data   = r.json()
            matchs = data.get("events", [])
            if not matchs:
                return f"Aucun resultat trouve pour {nom_ligue}."
            reponse = f"Derniers resultats {nom_ligue} : "
            lignes  = []
            for m in matchs[-6:]:
                home    = m.get("strHomeTeam", "?")
                away    = m.get("strAwayTeam", "?")
                score_h = m.get("intHomeScore", "?")
                score_a = m.get("intAwayScore", "?")
                date    = m.get("dateEvent", "?")
                lignes.append(f"{home} {score_h}-{score_a} {away} ({date})")
            return reponse + " | ".join(lignes)
    except Exception as e:
        print(f"[SPORT] Erreur football : {e}")
        return f"Impossible de recuperer les resultats football : {e}"

def get_classement_football(ligue=None):
    try:
        nom_ligue = ligue or "Ligue 1"
        ligue_ids = {
            "ligue 1": "4334", "premier league": "4328", "liga": "4335",
            "bundesliga": "4331", "serie a": "4332",
            "champions league": "4480", "ligue des champions": "4480",
        }
        ligue_id = ligue_ids.get(nom_ligue.lower(), "4334")
        r = requests.get(f"{THESPORTSDB_BASE}/lookuptable.php", params={"l": ligue_id, "s": "2024-2025"}, timeout=8)
        data    = r.json()
        tableau = data.get("table", [])
        if not tableau:
            return f"Classement {nom_ligue} non disponible pour le moment."
        reponse = f"Classement {nom_ligue} : "
        lignes  = []
        for eq in tableau[:10]:
            pos   = eq.get("intRank", "?")
            nom   = eq.get("strTeam", "?")
            pts   = eq.get("intPoints", "?")
            joues = eq.get("intPlayed", "?")
            lignes.append(f"{pos}. {nom} - {pts}pts ({joues}J)")
        return reponse + " | ".join(lignes)
    except Exception as e:
        print(f"[SPORT] Erreur classement : {e}")
        return f"Impossible de recuperer le classement : {e}"

def get_resultats_sport_gemini(question_sport):
    try:
        response = client.models.generate_content(
            model   = CHOSEN_MODEL,
            contents= [types.Content(role="user", parts=[types.Part(text=
                f"Donne-moi les derniers resultats et actualites sportives en 2026 "
                f"pour : {question_sport}. "
                f"Sois precis, donne les scores et dates. Reponds en francais."
            )])],
            config  = types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                system_instruction=(
                    "Tu es un expert sportif. Donne des resultats precis et a jour. "
                    "Reponds de facon concise et conversationnelle en francais."
                )
            )
        )
        return response.text.strip()
    except Exception as e:
        print(f"[SPORT] Erreur Gemini sport : {e}")
        return "Je n arrive pas a recuperer les resultats sportifs pour le moment."

def chercher_youtube(recherche):
    """Renvoie l'URL de la 1ere video YouTube pour la recherche.
    Essaie d'abord l'API officielle (si YOUTUBE_API_KEY valide), sinon
    scrape la page de resultats publique (pas besoin de cle).
    """
    # Voie 1 : API officielle si cle valide
    if _cle_valide(YOUTUBE_API_KEY):
        try:
            r = requests.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={"part": "snippet", "q": recherche, "type": "video",
                        "maxResults": 1, "key": YOUTUBE_API_KEY},
                timeout=5,
            )
            vid = r.json()["items"][0]["id"]["videoId"]
            return f"https://www.youtube.com/watch?v={vid}"
        except Exception as e:
            print(f"[YOUTUBE-API] Echec : {e} -> fallback scrape")

    # Voie 2 : scrape de la page publique (pas de cle requise)
    try:
        from urllib.parse import quote_plus
        r = requests.get(
            f"https://www.youtube.com/results?search_query={quote_plus(recherche)}",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                     "Accept-Language": "fr-FR,fr;q=0.9"},
            timeout=8,
        )
        # YouTube embed l'ID des videos dans le HTML : "videoId":"XXXXXXXXXXX"
        m = re.search(r'"videoId":"([A-Za-z0-9_-]{11})"', r.text)
        if m:
            return f"https://www.youtube.com/watch?v={m.group(1)}"
    except Exception as e:
        print(f"[YOUTUBE-SCRAPE] Echec : {e}")
    return None

def executer_action_pc(commande):
    cmd          = commande.lower()
    user_profile = os.environ.get('USERPROFILE', '')

    if "met de la musique" in cmd or "mets de la musique" in cmd:
        url = "https://www.youtube.com/watch?v=7CGKeID7nRc&list=PL4fGSI1pDJn50iCQRUVmgUjOrCggCQ9nR"
        webbrowser.open(url, new=2)
        time.sleep(6) # Laisser un peu plus de temps pour le chargement de la playlist
        pyautogui.press('f')
        return f"C'est parti {USER_NAME}, je mets votre playlist en plein écran."

    if "youtube" in cmd:
        recherche = cmd
        # Strip exhaustive : verbes d'ouverture/lancement + termes generiques
        for mot in ["ouvres", "ouvre", "ouvrir", "ouvrez", "va sur", "va", "vas",
                    "sur youtube", "youtube", "jarvis",
                    "mets", "met", "metz", "joues", "joue", "jouer",
                    "lances", "lance", "lancer",
                    "regarde", "regarder", "voir",
                    "la video", "la vidéo", "une video", "une vidéo",
                    "sur", "le", "la", "les", "moi", "stp", "s'il te plait", "s'il te plaît"]:
            recherche = re.sub(rf"\b{re.escape(mot)}\b", "", recherche, flags=re.IGNORECASE)
        recherche = re.sub(r"\s+", " ", recherche).strip()
        if recherche:
            url = chercher_youtube(recherche)
            if url:
                webbrowser.open(url, new=2)
                time.sleep(5)
                pyautogui.press('f')
                return f"Je lance {recherche} sur YouTube."
            return "Video introuvable."
        # Pas de query specifique -> juste ouvrir youtube.com
        webbrowser.open("https://www.youtube.com", new=2)
        return "YouTube ouvert."

    if "ouvre" in cmd or "lance" in cmd:
        if "chrome" in cmd:
            subprocess.Popen(["chrome.exe"])
            return "Chrome ouvert."
        if "notepad" in cmd or "bloc-notes" in cmd:
            subprocess.Popen(["notepad.exe"])
            return "Bloc-notes ouvert."
        if "explorateur" in cmd:
            subprocess.Popen(["explorer.exe"])
            return "Explorateur ouvert."

    if "volume" in cmd:
        if "monte" in cmd or "augmente" in cmd:
            for _ in range(5):
                pyautogui.press('volumeup')
            return "Volume augmente."
        if "baisse" in cmd:
            for _ in range(5):
                pyautogui.press('volumedown')
            return "Volume baisse."
        if "coupe" in cmd:
            pyautogui.press('volumemute')
            return "Son coupe."

    if "screenshot" in cmd or "capture" in cmd:
        path = os.path.join(user_profile, "Desktop", "screenshot.png")
        pyautogui.screenshot(path)
        return "Screenshot sauvegarde."

    if "eteins" in cmd or "shutdown" in cmd:
        os.system("shutdown /s /t 5")
        return "Extinction dans 5 secondes."

    return None

def init_mixer():
    if not pygame.mixer.get_init():
        pygame.mixer.init()

# ==========================================
# BUG 1 CORRIGE : fonction parler
# Le await send_web_state("idle") etait dans le mauvais bloc except
# ==========================================
async def parler(texte):
    global is_speaking, speak_volume, STOP_PARLER, _skip_pc_audio, historique

    # Reset l'eventuel STOP_PARLER laisse a True par un intercept "stop"
    # precedent (sans ca, le 1er chunk audio est cut immediatement)
    STOP_PARLER = False

    # Nettoyage des artefacts markdown/code/url pour le TTS
    try:
        texte_tts = nettoyer_pour_tts(texte)
    except NameError:
        texte_tts = texte.replace("**", "").replace("*", "").replace("#", "").replace("`", "").strip()

    # Enregistrer ce que Jarvis dit dans sa memoire (pour contexte conversation)
    # NB : on ajoute le texte tel quel (pas de prefixe) — le prefixe
    # "[Information retournee par l'action..." se retrouvait dans les replies
    # Gemini suivantes qui les repetaient en boucle.
    if historique and len(historique) > 0:
        dernier_texte_modele = historique[-1].parts[0].text
        if dernier_texte_modele != texte:
            historique.append(types.Content(role="model", parts=[types.Part(text=texte)]))

    consigner_echange("model", texte)
    await broadcast_chat("jarvis", texte)
    sauvegarder_historique(historique)

    # Si la commande vient du mobile, le tél gère lui-même son TTS
    if _skip_pc_audio:
        print(f"[MOBILE] Envoi au mobile : {texte_tts}")
        cibles = _clients_diffusion()
        if cibles:
            try:
                message = json.dumps({"action": "jarvis_response", "text": texte_tts})
                await asyncio.gather(*[ws.send(message) for ws in cibles], return_exceptions=True)
            except Exception as e:
                print(f"[MOBILE] Erreur broadcast response : {e}")
        return

    # Mute persistant : on log la reponse mais on ne la joue pas
    if IS_MUTED:
        print(f"[MUTE] Reponse non vocalisee : {texte_tts[:80]}")
        await send_web_state("idle")
        return

    # Mode serveur headless / pygame absent : le texte a deja ete diffuse aux
    # clients web et mobile (broadcast_chat ci-dessus). Pas de sortie audio locale.
    if HEADLESS or pygame is None:
        print(f"[HEADLESS] Reponse non vocalisee localement : {texte_tts[:80]}")
        await send_web_state("idle")
        return

    is_speaking  = True
    await send_web_state("speaking")
    speak_volume = 0.0
    tmp = f"jarvis_tts_{int(time.time()*1000)}.mp3"

    # Barge-in OPT-IN : si le flag est on et pyaudio dispo, on surveille le micro
    # pendant la lecture ; au-dela du seuil RMS, on_parole bascule STOP_PARLER=True
    # (la boucle ci-dessous gere deja l'arret). No-op total si flag OFF.
    moniteur_barge = None
    if BARGE_IN and barge_in is not None:
        try:
            if barge_in.disponible():
                moniteur_barge = barge_in.MoniteurBargeIn(
                    on_parole=lambda: globals().__setitem__("STOP_PARLER", True)
                )
                moniteur_barge.demarrer()
        except Exception as e:
            print(f"[BARGE] Echec demarrage barge-in : {e}")
            moniteur_barge = None

    try:
        communicate = edge_tts.Communicate(texte_tts, voice="fr-FR-HenriNeural")
        await communicate.save(tmp)
        init_mixer()
        pygame.mixer.music.load(tmp)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            if STOP_PARLER:
                pygame.mixer.music.stop()
                break
            
            # Simulation de volume plus réaliste pour l'animation
            t_audio = time.time() * 20
            base_vol = 0.4 + 0.3 * math.sin(t_audio) + 0.2 * math.sin(t_audio * 0.5)
            speak_volume = max(0.1, min(1.0, base_vol + random.uniform(-0.1, 0.1)))
            
            # Forward volume to frontend for sync
            await send_web_volume(speak_volume)
            await asyncio.sleep(0.05)
    except Exception as e:
        print(f"Erreur TTS : {e}")
    finally:
        # Arret propre du moniteur barge-in (no-op si jamais demarre).
        if moniteur_barge is not None:
            try:
                moniteur_barge.arreter()
            except Exception as e:
                print(f"[BARGE] Echec arret barge-in : {e}")
        speak_volume = 0.0
        is_speaking  = False
        STOP_PARLER  = False
        try:
            pygame.mixer.music.unload()
            await asyncio.sleep(0.1)
            os.remove(tmp)
        except Exception:
            pass
        # CORRIGE : send_web_state est maintenant hors du try/except interne
        await send_web_state("idle")

def reponse_locale(texte):
    """Réponse locale pour les requêtes basiques en cas de panne API."""
    t = texte.lower().strip()
    
    # Identité
    if any(m in t for m in ["qui es-tu", "ton nom", "quelle es ton identité", "t'appelle comment"]):
        return "Je suis JARVIS, votre assistant personnel et système informatique. Mes serveurs principaux sont actuellement en maintenance, mais je reste opérationnel localement."
    
    # Créateur
    if any(m in t for m in ["ton créateur", "t'as créé", "qui t'a créé", f"qui est {USER_NAME.lower()}"]):
        return f"{USER_NAME} est mon créateur et mon maître. C'est lui qui a conçu mes protocoles, même si ma connexion à mes serveurs neuronaux est actuellement limitée."
    
    # État
    if any(m in t for m in ["ça va", "tu vas bien", "comment vas-tu"]):
        return f"Je fonctionne en mode de réserve, {USER_NAME}. Mes capacités de réflexion profonde sont réduites, mais mon intégrité logicielle est intacte."
        
    # Heure et Date
    if any(m in t for m in ["heure", "quelle heure"]):
        h = time.strftime("%H:%M")
        return f"Il est précisément {h} Monsieur."
    if any(m in t for m in ["date", "quel jour", "le combien"]):
        d = time.strftime("%A %d %B %Y")
        return f"Nous sommes le {d}."
        
    # Politesse
    if any(m in t for m in ["bonjour", "salut", "hey", "bonsoir"]):
        return f"Bonjour {USER_NAME}. Je suis en ligne, bien que mes capacités soient actuellement restreintes."
    return None
    
async def demander_ia(texte):

    global is_thinking
    is_thinking = True
    await send_web_state("thinking")
    try:
        # --- BRANCHE OPENJARVIS AGENT (opt-in via USE_OPENJARVIS_AGENT=1) ---
        if openjarvis_brain is not None and openjarvis_brain.is_agent_enabled() and openjarvis_brain.is_available():
            try:
                res = await openjarvis_brain.ask_agent_async(
                    texte,
                    system_prompt=_prompt_ollama_systeme(),
                )
                if res and res.get("content"):
                    rep_oj = res["content"]
                    used = ", ".join(tr["tool_name"] for tr in res.get("tool_results", []))
                    if used:
                        print(f"[OPENJARVIS-AGENT] tools utilises: {used}")
                    historique.append(types.Content(role="user", parts=[types.Part(text=texte)]))
                    historique.append(types.Content(role="model", parts=[types.Part(text=rep_oj)]))
                    return rep_oj
                print("[OPENJARVIS-AGENT] reponse vide, fallback brain.")
            except Exception as e:
                print(f"[OPENJARVIS-AGENT] Echec, fallback brain : {e}")

        # --- BRANCHE OPENJARVIS BRAIN (opt-in via USE_OPENJARVIS=1) ---
        if openjarvis_brain is not None and openjarvis_brain.is_enabled() and openjarvis_brain.is_available():
            try:
                rep_oj = await openjarvis_brain.ask_with_history_async(
                    texte,
                    system_prompt=_prompt_ollama_systeme(),
                    history_pairs=openjarvis_brain.history_to_pairs(historique, limit=6),
                )
                if rep_oj:
                    historique.append(types.Content(role="user", parts=[types.Part(text=texte)]))
                    historique.append(types.Content(role="model", parts=[types.Part(text=rep_oj)]))
                    return rep_oj
                print("[OPENJARVIS] reponse vide, fallback chaine classique.")
            except Exception as e:
                print(f"[OPENJARVIS] Echec, fallback chaine classique : {e}")

        if FORCE_OLLAMA:
            rep_local = await demander_ollama(texte)
            if rep_local:
                return rep_local
            return f"Je suis desole {USER_NAME}, mes modeles locaux sont indisponibles. Verifiez qu'Ollama tourne."

        cerveau = detecter_cerveau(texte)

        async def _call_gemini():
            print(f"[CERVEAU] Tentative avec Gemini (Liste: {MODELS_LIST})...")
            # On ne modifie pas l'historique global avant d'être sûr que ça marche
            temp_hist = historique + [types.Content(role="user", parts=[types.Part(text=texte)])]
            # texte courant transmis pour la recherche RAG ciblee dans le prompt.
            # to_thread : construire_system_prompt peut faire un embedding Ollama
            # (reseau, jusqu'a 30s) -> jamais sur l'event loop.
            prompt_actuel = await asyncio.to_thread(construire_system_prompt, texte)
            
            last_err = None
            for model_name in MODELS_LIST:
                try:
                    print(f"[CERVEAU] Essai modele : {model_name} (Timeout 12s)")
                    # Utilisation de to_thread pour ne pas bloquer la boucle et pouvoir mettre un timeout
                    response = await asyncio.wait_for(
                        asyncio.to_thread(
                            client.models.generate_content,
                            model=model_name,
                            config=types.GenerateContentConfig(
                                system_instruction=prompt_actuel,
                                temperature=0.7,
                            ),
                            contents=temp_hist
                        ),
                        timeout=12.0
                    )
                    rep = response.text
                    # Succès : mise à jour de l'historique officiel
                    historique.append(types.Content(role="user", parts=[types.Part(text=texte)]))
                    historique.append(types.Content(role="model", parts=[types.Part(text=rep)]))
                    return rep
                except Exception as e:
                    print(f"[CERVEAU] Echec {model_name} : {e}")
                    last_err = e
                    continue
            
            raise last_err or Exception("Tous les modeles Gemini ont echoue")

        async def _call_grok():
            print("[CERVEAU] Tentative avec Grok...")
            rep_grok = await demander_grok(texte)
            if not rep_grok:
                raise Exception("Grok n'a rien renvoyé ou est mal configuré")
            return rep_grok

        # Logique de bascule bidirectionnelle
        if cerveau == "GROK" and grok_client:
            try:
                return await _call_grok()
            except Exception as e:
                print(f"[CERVEAU] Erreur Grok ({e}). Bascule sur Gemini.")
                try:
                    return await _call_gemini()
                except Exception as e2:
                    print(f"[ERREUR IA (Gemini repli)] {e2}")
        else:
            try:
                return await _call_gemini()
            except Exception as e:
                print(f"[CERVEAU] Erreur Gemini ({e}). Bascule sur SerpAPI.")
                
                # --- FALLBACK SERPAPI ---
                if len(texte.split()) > 2:
                    res_serp = recherche_web_serpapi(texte)
                    if res_serp and "VOTRE_CLE" not in res_serp and "rien trouvé" not in res_serp and "erreur" not in res_serp.lower():
                        return "Voici ce que j'ai trouvé sur le web : " + res_serp

                # --- FALLBACK GROQ (LLAMA 3.3) ---
                print("[CERVEAU] Bascule sur Groq (Llama 3.3).")
                if groq_client:
                    rep_groq = await demander_groq(texte)
                    if rep_groq:
                        return rep_groq
                
                # --- FALLBACK GROK (xAI) ---
                print("[CERVEAU] Bascule sur Grok (xAI).")
                if grok_client:
                    try:
                        return await _call_grok()
                    except Exception as e2:
                        print(f"[ERREUR IA (Grok repli)] {e2}")
        # --- FALLBACK OLLAMA (100% offline) ---
        print("[CERVEAU] Gemini et Grok KO. Tentative Ollama (local)...")
        rep_ollama = await demander_ollama(texte)
        if rep_ollama:
            return rep_ollama

        # --- FALLBACK LOCAL ---
        print("[CERVEAU] Tous les serveurs IA ont echoue. Tentative fallback local...")
        rep_loc = reponse_locale(texte)
        if rep_loc:
            return rep_loc
            
        return f"Desole {USER_NAME}, mes serveurs de réflexion profonde sont surchargés et mes modèles locaux ne sont pas disponibles non plus. Je reste cependant disponible pour vos commandes domestiques."
    finally:
        is_thinking = False
        await send_web_state("idle")


async def _llm_simple(prompt: str) -> str:
    """Appel LLM one-shot, SANS toucher a l'historique ni aux etats UI.

    Utilise par les taches de fond (resume d'historique, extraction de faits).
    Gemini en priorite (si dispo et pas FORCE_OLLAMA), repli Ollama. Renvoie ""
    en cas d'echec — jamais d'exception propagee."""
    try:
        if client is not None and not FORCE_OLLAMA:
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        client.models.generate_content,
                        model=MODELS_LIST[0],
                        config=types.GenerateContentConfig(temperature=0.2),
                        contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
                    ),
                    timeout=20.0,
                )
                return (response.text or "").strip()
            except Exception as e:
                print(f"[LLM-SIMPLE] Gemini KO ({e}), repli Ollama.")
        # Repli local : reutilise le chat Ollama brut sans historique global.
        return (await _ollama_chat_simple(prompt)) or ""
    except Exception as e:
        print(f"[LLM-SIMPLE] Echec : {e}")
        return ""


async def _ollama_chat_simple(prompt: str) -> str:
    """Appel Ollama /api/chat one-shot (un seul message user, pas d'historique)."""
    try:
        modeles = _OLLAMA_MODELS_DISPO or _decouvrir_modeles_ollama()
        for modele in modeles:
            try:
                r = await asyncio.to_thread(
                    requests.post,
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": modele,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                    },
                    timeout=60,
                )
                if r.status_code == 200:
                    return (r.json().get("message", {}).get("content", "") or "").strip()
            except Exception as e:
                print(f"[LLM-SIMPLE] Ollama {modele} KO : {e}")
                continue
    except Exception as e:
        print(f"[LLM-SIMPLE] Ollama indisponible : {e}")
    return ""


def _llm_ia_disponible() -> bool:
    """True si un cerveau IA (Gemini ou Ollama) peut etre sollicite."""
    return client is not None or FORCE_OLLAMA or bool(_OLLAMA_MODELS_DISPO)


async def demander_ia_vision(texte, img_b64):
    """Analyse une image (capture d'écran) avec Gemini Vision."""
    global is_thinking, historique
    is_thinking = True
    await send_web_state("thinking")
    try:
        print("[VISION] Analyse de l'image avec Gemini...")
        
        # Conversion base64 en bytes pour l'API
        img_bytes = base64.b64decode(img_b64)
        image_part = types.Part.from_bytes(
            data=img_bytes,
            mime_type="image/jpeg"
        )
        
        prompt_actuel = await asyncio.to_thread(construire_system_prompt, texte)
        prompt_actuel += f"\n\nIMPORTANT : Tu viens de recevoir une capture d'écran de {USER_NAME}. Analyse-la attentivement et réponds à sa question en te basant sur ce que tu vois."
        
        # On envoie l'image et le texte avec retry en cas de 503
        contents = [
            types.Content(role="user", parts=[image_part, types.Part(text=texte)])
        ]
        
        rep = None
        last_err = None
        for model_name in MODELS_LIST:
            print(f"[VISION] Essai modele : {model_name}")
            for attempt in range(2): # 2 tentatives par modele
                try:
                    print(f"[VISION] Appel modele : {model_name} (Timeout 15s)")
                    response = await asyncio.wait_for(
                        asyncio.to_thread(
                            client.models.generate_content,
                            model=model_name,
                            config=types.GenerateContentConfig(
                                system_instruction=prompt_actuel,
                                temperature=0.7,
                            ),
                            contents=contents
                        ),
                        timeout=15.0
                    )
                    rep = response.text
                    break
                except Exception as e:
                    if ("503" in str(e) or "overloaded" in str(e).lower()) and attempt < 1:
                        print(f"[VISION] Surcharge {model_name} (503). Retente...")
                        await asyncio.sleep(1)
                        continue
                    print(f"[VISION] Erreur {model_name} : {e}")
                    last_err = e
                    break
            if rep: break
        
        if not rep:
            print("[VISION] Tous les modeles Gemini ont echoue. Bascule sur Grok (Texte uniquement)...")
            if grok_client:
                return await demander_grok(texte + " (Note: Je n'ai pas pu voir ton écran car mes serveurs de vision sont indisponibles, je réponds donc uniquement à ton texte).")
            raise last_err or Exception("Aucun modele n'a pu analyser l'image")

        # On ajoute la trace dans l'historique (sans l'image pour éviter de saturer la mémoire)
        historique.append(types.Content(role="user", parts=[types.Part(text=f"[Analyse d'écran] {texte}")]))
        historique.append(types.Content(role="model", parts=[types.Part(text=rep)]))
        
        return rep
    except Exception as e:
        print(f"[VISION] Erreur Gemini Vision : {e}")
        # On évite les accolades dans le message d'erreur pour ne pas perturber l'extracteur JSON
        err_msg = str(e).replace("{", "[").replace("}", "]")
        return f"Désolé {USER_NAME}, je n'ai pas pu analyser votre écran. Erreur : {err_msg}"
    finally:
        is_thinking = False
        await send_web_state("idle")

def detecter_cerveau(texte):
    # Heuristique pour basculer sur Grok uniquement pour X/Twitter
    mots_cles_grok = ["sur x", "twitter", "grok", "elon", "x.com"]
    cmd = texte.lower()
    if any(m in cmd for m in mots_cles_grok):
        return "GROK"
    return "GEMINI"

async def demander_grok(texte):
    if not grok_client:
        return None
    
    try:
        # Conversion de l'historique Gemini vers format OpenAI pour Grok
        messages = [{"role": "system", "content": f"Tu es JARVIS, l'IA de {USER_NAME}. Tu utilises actuellement ton module Grok pour les infos en temps reel."}]
        for h in historique[-6:]: # Limiter aux 6 derniers messages pour eviter de saturer le contexte
            role = "user" if h.role == "user" else "assistant"
            msg_text = h.parts[0].text
            messages.append({"role": role, "content": msg_text})
        
        messages.append({"role": "user", "content": texte})
        
        completion = grok_client.chat.completions.create(
            model="grok-3", 
            messages=messages,
            temperature=0.7,
        )
        
        rep = completion.choices[0].message.content
        
        # On synchronise l'historique Gemini
        historique.append(types.Content(role="user", parts=[types.Part(text=texte)]))
        historique.append(types.Content(role="model", parts=[types.Part(text=rep)]))
        
        return rep
    except Exception as e:
        print(f"[ERREUR GROK] {e}")
        return None

_OLLAMA_MODELS_DISPO = None
_PHRASE_END_RE = re.compile(r"([\.!\?]+\s+|\n+)")


def _formater_memoire_naturelle():
    """Convertit la memoire cle/valeur en phrases naturelles pour l'IA."""
    memoire = charger_memoire()
    if not memoire:
        return ""
    lignes = [f"Voici ce que tu sais sur {USER_NAME} (faits memorisees, source de verite) :"]
    for cle, data in memoire.items():
        valeur = data.get("valeur", "")
        cle_lisible = cle.replace("_", " ")
        lignes.append(f"- {cle_lisible} : {valeur}")
    return "\n".join(lignes)


def _prompt_ollama_systeme():
    base = (
        f"Tu es JARVIS, l'assistant dev personnel de {USER_NAME}. Tu parles directement a {USER_NAME} (l'utilisateur "
        f"que tu vois EST {USER_NAME}). Tu tournes 100% en local via Ollama (qwen2.5:7b) avec une memoire "
        "persistante synchronisee avec son vault Obsidian.\n\n"
        f"PROFIL DE {USER_NAME} :\n"
        "- Developpeur. Travaille sur des projets perso (IA, web, automation).\n"
        "- Utilise Windows, VSCode, Claude Code, Ollama, Obsidian.\n\n"
        f"TA MISSION : faire gagner du temps a {USER_NAME} sur ses projets de dev.\n\n"
        "TU ES BON POUR :\n"
        "- Aider a debugger, comprendre une stack trace, suggerer une approche.\n"
        "- Expliquer un concept (algos, design pattern, framework, bibliotheque).\n"
        "- Generer du code (Python, JS/TS, shell, SQL) clair et direct.\n"
        "- Resumer un fichier, un texte, une commande.\n"
        "- Brainstormer une fonctionnalite, un nom, une archi.\n"
        "- Repondre aux questions generales (geographie, science, histoire, culture) sans pretexter une limitation.\n\n"
    )
    memoire_text = _formater_memoire_naturelle()
    if memoire_text:
        base += memoire_text + "\n\n"

    base += (
        "REGLES :\n"
        "1. Direct, concis, en francais. Pas de \"je suis ravi de t'aider\", pas de phrases creuses.\n"
        "2. Si tu ne sais pas, dis-le en une phrase. NE POSE PAS de questions etranges hors-sujet.\n"
        "3. Pour le code : un bloc, propre, sans commentaires inutiles. Style senior dev.\n"
        f"4. Tu peux appeler {USER_NAME} par son prenom avec un peu d'humour si naturel.\n"
        f"5. Tu n'es pas un assistant generique : tu travailles avec {USER_NAME} sur ses projets dev, va a l'essentiel."
    )
    return base


def _construire_messages_ollama(texte):
    msgs = [{"role": "system", "content": _prompt_ollama_systeme()}]
    for h in historique[-6:]:
        role = "user" if h.role == "user" else "assistant"
        msgs.append({"role": role, "content": h.parts[0].text})
    msgs.append({"role": "user", "content": texte})
    return msgs


async def demander_ollama_stream(texte):
    """Generateur asynchrone : yield les morceaux de texte au fur et a mesure."""
    # --- BRANCHE OPENJARVIS (opt-in via USE_OPENJARVIS=1) ---
    if openjarvis_brain is not None and openjarvis_brain.is_enabled() and openjarvis_brain.is_available():
        got_anything = False
        try:
            async for token in openjarvis_brain.stream_with_history_async(
                texte,
                system_prompt=_prompt_ollama_systeme(),
                history_pairs=openjarvis_brain.history_to_pairs(historique, limit=6),
            ):
                got_anything = True
                yield token
            if got_anything:
                return
            print("[OPENJARVIS-STREAM] aucun token, fallback Ollama direct.")
        except Exception as e:
            print(f"[OPENJARVIS-STREAM] echec ({e}), fallback Ollama direct.")

    modeles = _OLLAMA_MODELS_DISPO or _decouvrir_modeles_ollama()
    messages = _construire_messages_ollama(texte)

    for model_name in modeles:
        print(f"[OLLAMA-STREAM] {model_name}")
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def producer():
            try:
                with requests.post(
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": model_name,
                        "messages": messages,
                        "stream": True,
                        "options": {"temperature": 0.7, "num_predict": 512},
                    },
                    stream=True,
                    timeout=180,
                ) as resp:
                    if resp.status_code != 200:
                        loop.call_soon_threadsafe(queue.put_nowait, ("err", f"HTTP {resp.status_code}"))
                        return
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        try:
                            obj = json.loads(line.decode("utf-8"))
                        except Exception:
                            continue
                        chunk = (obj.get("message") or {}).get("content", "")
                        if chunk:
                            loop.call_soon_threadsafe(queue.put_nowait, ("chunk", chunk))
                        if obj.get("done"):
                            break
                loop.call_soon_threadsafe(queue.put_nowait, ("end", None))
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, ("err", str(e)))

        threading.Thread(target=producer, daemon=True).start()

        got_anything = False
        while True:
            kind, payload = await queue.get()
            if kind == "chunk":
                got_anything = True
                yield payload
            elif kind == "end":
                if got_anything:
                    return
                break
            elif kind == "err":
                print(f"[OLLAMA-STREAM] {model_name} echec : {payload}")
                break


async def repondre_streaming(texte_utilisateur):
    """Stream Ollama + TTS phrase par phrase. Skip les blocs de code (pas vocalises)."""
    if IS_MUTED:
        rep = await demander_ollama(texte_utilisateur)
        return rep or ""

    await send_web_state("thinking")

    full_text = ""
    buffer = ""
    in_code_block = False
    code_block_announced = False
    phrases_queue: asyncio.Queue = asyncio.Queue()

    async def consumer():
        first = True
        while True:
            phrase = await phrases_queue.get()
            if phrase is None:
                break
            if first:
                await send_web_state("speaking")
                first = False
            await parler(phrase)
        await send_web_state("idle")

    consumer_task = asyncio.create_task(consumer())

    async def push_phrase(raw: str):
        nonlocal code_block_announced
        cleaned = nettoyer_pour_tts(raw)
        if not cleaned:
            return
        if len(cleaned) < 3:
            return
        await phrases_queue.put(cleaned)

    try:
        async for chunk in demander_ollama_stream(texte_utilisateur):
            full_text += chunk
            buffer += chunk

            # Traite les separateurs ``` au fur et a mesure
            while True:
                idx = buffer.find("```")
                if idx == -1:
                    break
                avant = buffer[:idx]
                buffer = buffer[idx + 3 :]
                if not in_code_block:
                    # Vocalise ce qui precede le code
                    while True:
                        m = _PHRASE_END_RE.search(avant)
                        if not m:
                            break
                        await push_phrase(avant[: m.end()])
                        avant = avant[m.end() :]
                    if avant.strip():
                        await push_phrase(avant)
                    in_code_block = True
                    if not code_block_announced:
                        await phrases_queue.put("Voici le code, regarde l'ecran.")
                        code_block_announced = True
                else:
                    # On sort du bloc de code, on jette ce qu'il y avait dedans pour le TTS
                    in_code_block = False

            if not in_code_block:
                while True:
                    m = _PHRASE_END_RE.search(buffer)
                    if not m:
                        break
                    await push_phrase(buffer[: m.end()])
                    buffer = buffer[m.end() :]

        if not in_code_block and buffer.strip():
            await push_phrase(buffer)
    finally:
        await phrases_queue.put(None)
        await consumer_task

    if full_text:
        historique.append(types.Content(role="user", parts=[types.Part(text=texte_utilisateur)]))
        historique.append(types.Content(role="model", parts=[types.Part(text=full_text)]))
        sauvegarder_historique(historique)

    return full_text or f"Je n'ai rien recu du modele local, {USER_NAME}."

def _decouvrir_modeles_ollama():
    global _OLLAMA_MODELS_DISPO
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        if r.status_code == 200:
            noms = [m["name"] for m in r.json().get("models", [])]
            ordonnes = [m for m in OLLAMA_MODELS if m in noms]
            for n in noms:
                if n not in ordonnes:
                    ordonnes.append(n)
            _OLLAMA_MODELS_DISPO = ordonnes
            print(f"[OLLAMA] Modeles disponibles : {_OLLAMA_MODELS_DISPO}")
            return _OLLAMA_MODELS_DISPO
    except Exception as e:
        print(f"[OLLAMA] Decouverte modeles impossible : {e}")
    _OLLAMA_MODELS_DISPO = OLLAMA_MODELS
    return _OLLAMA_MODELS_DISPO


async def demander_ollama(texte):
    """Appelle un modèle local via Ollama (100% offline)."""
    global historique
    try:
        modeles = _OLLAMA_MODELS_DISPO or _decouvrir_modeles_ollama()

        prompt_systeme = (
            f"Tu es JARVIS, l'IA personnelle de {USER_NAME}. "
            "Tu fonctionnes en local via Ollama, sans connexion cloud. "
            "Reponds toujours en francais, de facon concise (1 a 3 phrases sauf si on te demande des details). "
            f"Tu peux appeler {USER_NAME} par son prenom avec respect et une pointe d'humour bienveillant. "
            "Ne genere PAS de JSON ou de code sauf si on te le demande explicitement."
        )
        messages = [{"role": "system", "content": prompt_systeme}]
        for h in historique[-6:]:
            role = "user" if h.role == "user" else "assistant"
            messages.append({"role": role, "content": h.parts[0].text})
        messages.append({"role": "user", "content": texte})

        for model_name in modeles:
            try:
                print(f"[OLLAMA] Essai modele local : {model_name}")
                resp = await asyncio.wait_for(
                    asyncio.to_thread(
                        requests.post,
                        f"{OLLAMA_URL}/api/chat",
                        json={
                            "model": model_name,
                            "messages": messages,
                            "stream": False,
                            "options": {"temperature": 0.7, "num_predict": 512},
                        },
                        timeout=120,
                    ),
                    timeout=125.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    rep = (data.get("message") or {}).get("content", "").strip()
                    if rep:
                        historique.append(types.Content(role="user", parts=[types.Part(text=texte)]))
                        historique.append(types.Content(role="model", parts=[types.Part(text=rep)]))
                        print(f"[OLLAMA] Reponse recue de {model_name} ({len(rep)} car.)")
                        return rep
                else:
                    print(f"[OLLAMA] Erreur HTTP {resp.status_code} pour {model_name} : {resp.text[:200]}")
            except Exception as e:
                print(f"[OLLAMA] Echec {model_name} : {e}")
                continue

        print("[OLLAMA] Tous les modeles locaux ont echoue")
        return None
    except Exception as e:
        print(f"[ERREUR OLLAMA] {e}")
        return None

async def demander_groq(texte):
    """Appelle Groq (Llama 3.3) en fallback gratuit."""
    if not groq_client:
        return None
    
    try:
        messages = [{"role": "system", "content": f"Tu es JARVIS, l'IA de {USER_NAME}. Tu utilises actuellement le modèle Llama 3.3 de Groq pour répondre rapidement."}]
        for h in historique[-6:]:
            role = "user" if h.role == "user" else "assistant"
            messages.append({"role": role, "content": h.parts[0].text})
        messages.append({"role": "user", "content": texte})
        
        completion = await asyncio.to_thread(
            groq_client.chat.completions.create,
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.7,
        )
        
        rep = completion.choices[0].message.content
        
        historique.append(types.Content(role="user", parts=[types.Part(text=texte)]))
        historique.append(types.Content(role="model", parts=[types.Part(text=rep)]))
        
        return rep
    except Exception as e:
        print(f"[ERREUR GROQ] {e}")
        return None

async def action_whatsapp_appel(contact):
    try:
        await parler(f"J'appelle {contact} sur WhatsApp, {USER_NAME}.")
        # Lancement de l'app via le protocole
        os.system("start whatsapp://")
        time.sleep(6) # On laisse le temps a l'app de s'ouvrir et se focuser
        
        # Recherche du contact (Ctrl+F)
        pyautogui.hotkey('ctrl', 'f')
        time.sleep(1)
        pyautogui.typewrite(contact)
        time.sleep(2)
        pyautogui.press('enter')
        time.sleep(3) # On attend que la conversation s'affiche bien
        
        # Utilisation du raccourci clavier officiel pour l'appel audio (plus fiable que la vision)
        print(f"[WHATSAPP] Envoi du raccourci d'appel (Ctrl+Shift+C)...")
        pyautogui.hotkey('ctrl', 'shift', 'c')
        
        # On ajoute quand meme un petit clic de vision en secours si le raccourci ne suffit pas
        time.sleep(2)
        print(f"[WHATSAPP] Verification par vision au cas ou...")
        await jarvis_vision_cliquer("clique sur le bouton 'Appel vocal' ou l icone de telephone qui vient de s afficher en haut a droite")
        
        return True
    except Exception as e:
        print(f"[WHATSAPP ERROR] {e}")
        await parler(f"Desole {USER_NAME}, je n'ai pas pu lancer l'appel WhatsApp. {e}")
        return False

def _send_media_key(vk_code: int, repeat: int = 1):
    """Envoie une touche media Win32 (plus fiable que pyautogui).
    VK codes utiles :
      0xAD = Volume Mute, 0xAE = Volume Down, 0xAF = Volume Up
      0xB0 = Next Track,  0xB1 = Prev Track,  0xB3 = Play/Pause
    """
    try:
        import ctypes
        KEYEVENTF_EXTENDEDKEY = 0x0001
        KEYEVENTF_KEYUP = 0x0002
        u32 = ctypes.windll.user32
        for _ in range(repeat):
            u32.keybd_event(vk_code, 0, KEYEVENTF_EXTENDEDKEY, 0)
            u32.keybd_event(vk_code, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
    except Exception as e:
        print(f"[MEDIA-KEY] Echec vk={hex(vk_code)} : {e}")


# Tools MCP exposes a la boucle agent : nom Gemini "safe" -> (serveur, tool)
_MCP_TOOLS_REGISTRY: dict = {}
_MCP_TOOL_DECLS: list = []
# Event loop du serveur WS : les sessions MCP (process, futures, reader) y vivent.
# La boucle vocale tourne sur un loop jetable different ; on route donc les appels
# MCP vers ce loop via run_coroutine_threadsafe pour respecter le contrat de mcp_client.
_WS_LOOP = None


async def _appeler_mcp_safe(srv: str, tool: str, args: dict) -> tuple[str, bool]:
    """Appelle un tool MCP depuis n'importe quel loop, en l'executant toujours
    sur le loop du serveur WS (ou vivent les sessions MCP)."""
    if not mcp_client:
        return "Module MCP indisponible.", False
    try:
        courant = asyncio.get_running_loop()
    except RuntimeError:
        courant = None
    # Meme loop que les sessions MCP (cas WS/dashboard) : appel direct.
    if _WS_LOOP is None or courant is _WS_LOOP:
        return await mcp_client.appeler_tool(srv, tool, args)
    # Loop different (cas voix) : on planifie sur le loop WS et on attend le resultat
    # sans bloquer le loop courant (concurrent.futures.Future via un executor).
    try:
        cf = asyncio.run_coroutine_threadsafe(
            mcp_client.appeler_tool(srv, tool, args), _WS_LOOP
        )
        return await asyncio.get_running_loop().run_in_executor(None, cf.result, 35)
    except Exception as e:
        return f"Erreur appel MCP cross-loop : {e}", False


def _json_schema_vers_gemini(schema: dict):
    """Convertit un inputSchema MCP (JSON Schema) en types.Schema Gemini.
    Conversion minimale : objets plats + types simples. OBJECT vide en repli."""
    from google.genai import types as gtypes
    type_map = {
        "string": gtypes.Type.STRING, "number": gtypes.Type.NUMBER,
        "integer": gtypes.Type.INTEGER, "boolean": gtypes.Type.BOOLEAN,
        "array": gtypes.Type.ARRAY, "object": gtypes.Type.OBJECT,
    }
    try:
        props = {}
        for pname, pdef in (schema.get("properties") or {}).items():
            ptype = type_map.get(str(pdef.get("type", "string")).lower(), gtypes.Type.STRING)
            kwargs = {"type": ptype, "description": str(pdef.get("description", ""))[:300]}
            if ptype == gtypes.Type.ARRAY:
                items_def = pdef.get("items") or {}
                itype = type_map.get(str(items_def.get("type", "string")).lower(), gtypes.Type.STRING)
                kwargs["items"] = gtypes.Schema(type=itype)
            props[pname] = gtypes.Schema(**kwargs)
        required = [r for r in (schema.get("required") or []) if r in props]
        return gtypes.Schema(type=gtypes.Type.OBJECT, properties=props, required=required or None)
    except Exception:
        return gtypes.Schema(type=gtypes.Type.OBJECT, properties={})


async def _init_mcp_tools():
    """Connecte les serveurs MCP actifs et expose leurs tools a la boucle agent."""
    global _MCP_TOOL_DECLS
    if not (mcp_client and jarvis_agent):
        return
    try:
        from google.genai import types as gtypes
        tools = await mcp_client.lister_tools()
        decls, registry = [], {}
        for t in tools:
            safe = re.sub(r"[^a-zA-Z0-9_]", "_", f"mcp_{t['server']}_{t['name']}")[:60]
            if safe in registry:
                continue
            registry[safe] = (t["server"], t["name"])
            decls.append(gtypes.FunctionDeclaration(
                name=safe,
                description=(t.get("description") or f"Tool MCP {t['name']} ({t['server']})")[:900],
                parameters=_json_schema_vers_gemini(t.get("input_schema") or {}),
            ))
        _MCP_TOOLS_REGISTRY.clear()
        _MCP_TOOLS_REGISTRY.update(registry)
        _MCP_TOOL_DECLS = decls
        if decls:
            print(f"[MCP] {len(decls)} tools MCP exposes a l'agent.")
    except Exception as e:
        print(f"[MCP] Init tools echec : {e}")


async def _agent_dispatch(name: str, args: dict) -> str:
    """Mappe les noms de tools (Gemini function calls) -> vraies fonctions Jarvis.
    Retourne une chaine de resultat lisible par l'IA pour son raisonnement."""
    try:
        # --- Domotique Meross ---
        if name == "toggle_light":
            if not meross:
                return "Module Meross indisponible."
            ok, msg = await meross._toggle()
            return msg if ok else f"Echec : {msg}"
        if name == "set_light":
            if not meross:
                return "Module Meross indisponible."
            ok, msg = await meross._switch(target_on=bool(args.get("on", True)))
            return msg if ok else f"Echec : {msg}"

        # --- Media (touches Win32) ---
        if name == "media_control":
            action = args.get("action", "play_pause")
            vk_map = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1}
            _send_media_key(vk_map.get(action, 0xB3))
            return f"OK media={action}"
        if name == "set_volume":
            action = args.get("action", "up")
            steps = int(args.get("steps", 5))
            if action == "mute":
                _send_media_key(0xAD)
                return "Mute toggle."
            if action in ("max", "up"):
                _send_media_key(0xAF, repeat=25 if action == "max" else steps)
                return f"Volume {action}."
            if action in ("min", "down"):
                _send_media_key(0xAE, repeat=25 if action == "min" else steps)
                return f"Volume {action}."
            return f"Action volume inconnue : {action}"
        if name == "play_music":
            try:
                os.startfile("spotify:collection:tracks")
                await asyncio.sleep(2.0)
                if pc_actions:
                    pc_actions._bring_to_front("Spotify", max_wait_s=3.0)
                await asyncio.sleep(0.5)
                _click_spotify_play_button()
                if args.get("shuffle"):
                    await asyncio.sleep(0.4)
                    import pyautogui as _pa
                    _pa.hotkey("ctrl", "shift", "s")
                return "Spotify lance" + (" en aleatoire" if args.get("shuffle") else "")
            except Exception as e:
                return f"Echec lancement Spotify : {e}"

        # --- Apps / Fenetres ---
        if name == "open_app":
            if not pc_actions:
                return "Module pc_actions indisponible."
            rep, ok = pc_actions._ouvrir_app(args.get("name", ""))
            return rep or "Action effectuee."
        if name == "close_active_window":
            if not pc_actions:
                return "Module pc_actions indisponible."
            rep, _ = pc_actions._fermer_fenetre_active()
            return rep
        if name == "lock_pc":
            if not pc_actions:
                return "Module pc_actions indisponible."
            rep, _ = pc_actions._verrouiller()
            return rep
        if name == "screenshot":
            if not pc_actions:
                return "Module pc_actions indisponible."
            dossier = os.path.join(os.environ.get("USERPROFILE", "."), "Pictures", "Jarvis")
            rep, _ = pc_actions._capture_ecran(dossier)
            return rep
        if name == "screens_off":
            try:
                import ctypes
                ctypes.windll.user32.SendMessageW(0xFFFF, 0x0112, 0xF170, 2)
                return "Ecrans en veille."
            except Exception as e:
                return f"Echec : {e}"

        # --- Navigateur Chromium ---
        if name == "browser_navigate":
            if not jarvis_browser:
                return "Module browser indisponible."
            ok, msg = await jarvis_browser.navigate(args.get("site_or_url", ""))
            return msg
        if name == "browser_search":
            if not jarvis_browser:
                return "Module browser indisponible."
            ok, msg = await jarvis_browser.search(args.get("engine", "google"), args.get("query", ""))
            return msg
        if name == "browser_click":
            if not jarvis_browser:
                return "Module browser indisponible."
            ok, msg = await jarvis_browser.click_text(args.get("text", ""))
            return msg
        if name == "browser_read_page":
            if not jarvis_browser:
                return "Module browser indisponible."
            ok, msg = await jarvis_browser.read_main_text()
            return msg
        if name == "browser_close":
            if jarvis_browser:
                await jarvis_browser.shutdown()
                return "Navigateur ferme."
            return "Pas de navigateur ouvert."

        # --- YouTube direct (default browser, plein ecran) ---
        if name == "play_youtube":
            query = args.get("query", "").strip()
            if not query:
                webbrowser.open("https://www.youtube.com", new=2)
                return "YouTube ouvert."
            url = chercher_youtube(query)
            if not url:
                return "Aucune video trouvee."
            webbrowser.open(url, new=2)
            await asyncio.sleep(5)
            try:
                import pyautogui as _pa
                _pa.press('f')
            except Exception:
                pass
            return f"Lancement de '{query}' sur YouTube."

        # --- Cache l'orbe ---
        if name == "hide_orb":
            global STOP_PARLER  # noqa: PLW0603
            STOP_PARLER = True
            await send_web_state("idle")
            return "Orbe cachee."

        # --- Affichage visuel (fenetre de contenu) ---
        if name == "show_content":
            if not display_actions:
                return "Module affichage indisponible."
            rep, ok = display_actions.montrer_contenu(
                args.get("title", "Jarvis"),
                args.get("content", ""),
                args.get("content_type", "texte"),
            )
            return rep

        # --- Delegation a OpenClaw (agent IA personnel externe) ---
        if name == "ask_openclaw":
            if not openclaw:
                return "Module OpenClaw indisponible."
            rep, ok = await openclaw.demander(args.get("message", ""))
            return rep

        # --- Tools MCP dynamiques (connecteurs externes) ---
        if name in _MCP_TOOLS_REGISTRY:
            srv, tool = _MCP_TOOLS_REGISTRY[name]
            rep, ok = await _appeler_mcp_safe(srv, tool, args)
            return rep if ok else f"Echec MCP : {rep}"

        return f"Tool inconnu : {name}"
    except Exception as e:
        return f"Erreur dispatch {name} : {e}"


def _click_spotify_play_button() -> bool:
    """Localise le bouton Play vert Spotify (#1DB954) et le clique.
    Scanne la fenetre Spotify a la recherche de pixels vert-Spotify, trouve
    le plus gros cluster, et clique sur son centre.
    Retourne True si un click a ete fait."""
    try:
        import pygetwindow as gw
        from PIL import ImageGrab
        import numpy as np
        import pyautogui

        spotify = None
        for w in gw.getAllWindows():
            if w.title and "spotify" in w.title.lower() and w.width > 200:
                spotify = w
                break
        if not spotify:
            return False

        # Capture la moitie superieure (le bouton play est haut sur la page playlist)
        bbox = (spotify.left, spotify.top,
                spotify.left + spotify.width,
                spotify.top + spotify.height // 2)
        img = ImageGrab.grab(bbox=bbox)
        arr = np.array(img)

        # Spotify green : R~29, G~185, B~84 — large tolerance
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        mask = (r < 90) & (g > 140) & (b < 130) & (g > r + 60) & (g > b + 40)
        if not mask.any():
            print("[SPOTIFY] Aucun pixel vert detecte dans la fenetre")
            return False

        ys, xs = np.where(mask)
        # Cluster le plus gros : on segmente par densite via histogramme grossier
        # Approche simple suffisante : binning 40x40
        h_bins = np.histogram2d(ys, xs, bins=20)
        # Trouve la cellule la plus dense
        max_idx = np.unravel_index(np.argmax(h_bins[0]), h_bins[0].shape)
        y_low, y_high = h_bins[1][max_idx[0]], h_bins[1][max_idx[0] + 1]
        x_low, x_high = h_bins[2][max_idx[1]], h_bins[2][max_idx[1] + 1]
        # Centroid des pixels dans cette cellule
        in_cell = (ys >= y_low) & (ys < y_high) & (xs >= x_low) & (xs < x_high)
        cx = int(np.mean(xs[in_cell])) + bbox[0]
        cy = int(np.mean(ys[in_cell])) + bbox[1]

        pyautogui.click(cx, cy)
        print(f"[SPOTIFY] Click bouton Play vert a ({cx},{cy})")
        return True
    except Exception as e:
        print(f"[SPOTIFY] Echec detection bouton Play : {e}")
        return False


async def _resumer_historique_si_besoin():
    """Compacte l'historique global s'il devient trop long (resume des anciens).

    Branche par le flag JARVIS_RESUME_HISTORIQUE (defaut ON). Necessite un cerveau
    IA dispo. Remplace IN-PLACE le contenu de `historique` (historique[:] = ...) pour
    que toutes les references globales restent valides. Jamais d'exception propagee."""
    global historique
    if not RESUME_HISTORIQUE or history_summary is None:
        return
    if not _llm_ia_disponible():
        return
    try:
        # Snapshot : on resume une COPIE figee. Des messages peuvent etre ajoutes
        # a `historique` pendant l'await (autres tours de conversation) ; il ne faut
        # pas les perdre en ecrasant tout.
        snapshot = list(historique)
        n0 = len(snapshot)
        nouvelle = await history_summary.resumer_si_besoin(snapshot, _llm_simple)
        if nouvelle is not None:
            ancien = len(historique)
            # Messages ajoutes pendant l'await (apres l'index n0) : on les preserve.
            ajouts = historique[n0:]
            historique[:] = list(nouvelle) + ajouts
            print(f"[RESUME] Historique compacte : {ancien} -> {len(historique)} messages.")
            try:
                sauvegarder_historique(historique)
            except Exception as e:
                print(f"[RESUME] Echec sauvegarde post-resume : {e}")
    except Exception as e:
        print(f"[RESUME] Echec resume historique : {e}")


async def _extraire_faits_proactif(user_text: str, jarvis_text: str):
    """Extrait en tache de fond les faits durables sur l'utilisateur (OPT-IN).

    Active uniquement si JARVIS_MEMOIRE_PROACTIVE=1 et un cerveau IA dispo. Chaque
    fait extrait est memorise via ajouter_memoire SAUF si la cle existe deja (dedup).
    Ne bloque jamais la reponse et n'emet aucune exception."""
    if not MEMOIRE_PROACTIVE or memory_proactive is None:
        return
    if not _llm_ia_disponible():
        return
    try:
        faits = await memory_proactive.extraire_faits(user_text, jarvis_text, _llm_simple)
        if not faits:
            return
        memoire = charger_memoire()
        for fait in faits:
            try:
                cle = (fait.get("cle") or "").strip()
                valeur = (fait.get("valeur") or "").strip()
                if not cle or not valeur:
                    continue
                if cle in memoire:
                    continue  # dedup : on n'ecrase pas un fait deja connu
                ajouter_memoire(cle, valeur)
                memoire[cle] = {"valeur": valeur, "timestamp": ""}  # evite les doublons intra-lot
                print(f"[PROACTIF] Fait memorise : {cle} = {valeur}")
            except Exception as e:
                print(f"[PROACTIF] Echec memorisation fait : {e}")
    except Exception as e:
        print(f"[PROACTIF] Echec extraction faits : {e}")


def _lancer_taches_post_conversation(user_text: str, jarvis_text: str):
    """Declenche en arriere-plan resume d'historique + memoire proactive.

    Appele apres une reponse conversationnelle reussie. Utilise ensure_future pour
    ne JAMAIS bloquer la reponse vocale. Tolere l'absence de boucle (no-op)."""
    try:
        asyncio.ensure_future(_resumer_historique_si_besoin())
        asyncio.ensure_future(_extraire_faits_proactif(user_text, jarvis_text))
    except Exception as e:
        print(f"[POST-CONV] Echec lancement taches de fond : {e}")


async def traiter_reponse_ia(texte_utilisateur, mobile_ws=None, repondre_vocal=True):
    global MODE_IRON_MAN, jarvis_actif, dernier_message, _skip_pc_audio, STOP_PARLER

    # Chat "texte seulement" (repondre_vocal=False) : on diffuse le texte aux
    # clients (chat_message) mais on ne joue PAS l'audio local — meme mecanisme
    # que le mobile (_skip_pc_audio). Pose le flag des maintenant pour couvrir
    # aussi les interceptions prioritaires ci-dessous. Affectation INCONDITIONNELLE :
    # chaque commande repart d'une base saine, sinon le True d'une commande texte
    # precedente fuit et rend muette la commande vocale suivante.
    _skip_pc_audio = not repondre_vocal

    async def _parler_et_restaurer(msg: str):
        """parler() pour les interceptions a retour immediat : restaure le flag
        audio apres coup, pour ne pas laisser un skip fuiter vers les annonces
        proactives (routines/triggers) emises entre deux commandes."""
        global _skip_pc_audio
        try:
            await parler(msg)
        finally:
            _skip_pc_audio = False

    # ============================================================
    # INTERCEPTIONS PRIORITAIRES (avant tout le reste)
    # ============================================================
    txt_l = texte_utilisateur.lower().strip()

    # 1) "stop la musique / video" -> PLAY/PAUSE media key globale (pas de focus requis)
    if re.search(r"\b(stop|arr[êe]te|coupe|pause)\b.*\b(musique|vid[ée]o|playlist|chanson|son|lecture)\b", txt_l):
        _send_media_key(0xB3)  # VK_MEDIA_PLAY_PAUSE — marche meme sans focus
        await _parler_et_restaurer("Pause.")
        return

    # 2) "stop" / "tais-toi" / "silence" tout seul -> interrompt Jarvis immediatement
    if re.search(r"\b(stop|arr[êe]te[zr]?|tais[ -]toi|silence|chut|ferme[ -]?la)\b", txt_l):
        STOP_PARLER = True
        print(f"[STOP] Interruption demandee : '{txt_l}'")
        await send_web_state("idle")
        _skip_pc_audio = False  # pas de parler() ici : restaure la base avant de sortir
        return

    # 2bis) "cache toi" / "disparais" / "ferme l'orbe" -> cache la mini-fenetre
    # (set_state=idle force jarvis_desktop a hide la fenetre, et stop le TTS
    # courant si Jarvis parle)
    if re.search(
        r"\b(?:cache[ -]?toi|disparai?s|disparais|ferme\s+(?:l[' ]?orbe|la\s+fen[êe]tre|toi)"
        r"|va[- ]?t[' ]?en|degage|tire[ -]?toi|planque[ -]?toi)\b",
        txt_l,
    ):
        STOP_PARLER = True
        print(f"[CACHE] Demande de cacher l'orbe : '{txt_l}'")
        await send_web_state("idle")
        _skip_pc_audio = False  # pas de parler() ici : restaure la base avant de sortir
        return

    # 2ter) Spotify API (si configure) AVANT les touches media : pause/suivant/
    # precedent/volume controlent alors le device Spotify ACTIF via l'API
    # officielle (y compris telephone/enceinte), pas seulement le PC. Place
    # APRES les sections stop/interruption (le "stop" qui coupe Jarvis garde la
    # priorite) et execute dans un thread (spotipy fait des appels HTTP
    # bloquants : dans l'event loop WS, ils gelaient tout le backend). Sans
    # config, disponible() est False et les touches media restent le defaut.
    if spotify is not None:
        try:
            if await asyncio.to_thread(spotify.disponible):
                sp_reponse, sp_ok = await asyncio.to_thread(spotify.executer, texte_utilisateur)
                if sp_reponse is not None:
                    print(f"[SPOTIFY] {sp_reponse}")
                    if mobile_ws:
                        _skip_pc_audio = True
                    await _parler_et_restaurer(sp_reponse)
                    return
        except Exception as e:
            print(f"[SPOTIFY] Erreur : {e}")

    # 3) "pause" / "met pause" -> VK_MEDIA_PLAY_PAUSE (toggle global, pas de focus requis)
    if re.search(r"\b(met[s]?\s+(?:la\s+|en\s+)?pause|pause)\b", txt_l):
        _send_media_key(0xB3)
        await _parler_et_restaurer("Pause.")
        return

    # 4) "play" / "lecture" / "reprend" -> VK_MEDIA_PLAY_PAUSE (toggle global)
    # Marche meme si Spotify est en arriere-plan (Windows route la touche
    # vers la session media active).
    if re.search(r"\b(play|lecture|reprend(?:s|re)?|relance\s+(?:la\s+)?(?:vid[ée]o|musique))\b", txt_l):
        _send_media_key(0xB3)
        await _parler_et_restaurer("Lecture.")
        return

    # 4bis) "musique suivante" / "next" / "passe a la suivante" / "musique d'apres"
    #       -> touche media VK_MEDIA_NEXT_TRACK (0xB0) via ctypes (plus fiable que pyautogui)
    if re.search(
        r"\b(?:(?:musique|chanson|piste|morceau|titre|son)\s+(?:suivante?|prochaine?|d['’]?\s*apr[èe]s)"
        r"|next(?:\s+(?:musique|chanson|track|morceau))?"
        r"|passe\s+(?:a\s+(?:la\s+)?(?:suivante?|prochaine?|musique\s+d['’]?apr[èe]s)|au\s+suivant)"
        r"|^suivant(?:e)?$|^prochaine?$|change\s+(?:de\s+)?(?:musique|son|chanson))\b",
        txt_l,
    ):
        _send_media_key(0xB0)  # VK_MEDIA_NEXT_TRACK
        await _parler_et_restaurer("Musique suivante.")
        return

    # 4ter) "musique precedente" / "previous" / "musique d'avant" / "retour"
    #       -> VK_MEDIA_PREV_TRACK (0xB1)
    if re.search(
        r"\b(?:(?:musique|chanson|piste|morceau|titre|son)\s+(?:pr[ée]c[ée]dente?|d['’]?\s*avant|davant)"
        r"|prev(?:ious)?(?:\s+(?:musique|chanson|track))?"
        r"|reviens?\s+(?:en\s+arri[èe]re|a\s+la\s+pr[ée]c[ée]dente)"
        r"|^pr[ée]c[ée]dent(?:e)?$|retour\s+(?:musique|chanson))\b",
        txt_l,
    ):
        _send_media_key(0xB1)  # VK_MEDIA_PREV_TRACK
        await _parler_et_restaurer("Musique precedente.")
        return

    # 4q) VOLUME UP — "monte/augmente le volume", "plus fort", "volume max"
    if re.search(
        r"\b(?:(?:monte|augmente|hausse|leve)\s+(?:le\s+|du\s+)?(?:volume|son)"
        r"|volume\s+(?:plus\s+fort|max(?:imum)?|a\s+fond)"
        r"|(?:plus|encore)\s+fort"
        r"|(?:augmente|monte)\s+le\s+son)\b",
        txt_l,
    ):
        # Volume max => 25 presses (chaque press = 2%, donc ~50% en plus)
        # Sinon 5 presses (~10%)
        n = 25 if re.search(r"max|fond|maximum", txt_l) else 5
        _send_media_key(0xAF, repeat=n)  # VK_VOLUME_UP
        await _parler_et_restaurer("Volume monte.")
        return

    # 4r) VOLUME DOWN — "baisse/diminue le volume", "moins fort", "volume zero"
    if re.search(
        r"\b(?:(?:baisse|diminue|reduis|reduit|abaisse)\s+(?:le\s+|du\s+)?(?:volume|son)"
        r"|volume\s+(?:moins\s+fort|min(?:imum)?|au\s+min(?:imum)?|zero)"
        r"|(?:moins|pas\s+trop)\s+fort"
        r"|(?:baisse|diminue)\s+le\s+son)\b",
        txt_l,
    ):
        n = 25 if re.search(r"min|zero|minimum", txt_l) else 5
        _send_media_key(0xAE, repeat=n)  # VK_VOLUME_DOWN
        await _parler_et_restaurer("Volume baisse.")
        return

    # 4s) MUTE — "coupe le son", "mute", "rends le son" (toggle mute)
    if re.search(
        r"\b(?:coupe\s+(?:le\s+|du\s+)?son|mute|met[srz]?\s+en?\s+sourdine"
        r"|rends?\s+(?:moi\s+)?le\s+son|d[ée]coupe\s+le\s+son|reactive\s+le\s+son)\b",
        txt_l,
    ):
        _send_media_key(0xAD)  # VK_VOLUME_MUTE (toggle)
        await _parler_et_restaurer(
            "Son coupe." if re.search(r"coupe|mute|sourdine", txt_l) else "Son retabli."
        )
        return

    # 5) "musique" tout seul ou "lance/met/joue de la musique" -> SPOTIFY
    # Ouvre la playlist Liked Songs (spotify:collection:tracks), la met au
    # premier plan, et clique le bouton Play vert (detection du pixel vert
    # Spotify #1DB954). Active le shuffle si "aleatoire" mentionne.
    musique_match = re.search(
        r"\b(?:(?:lance[srz]?|met[srz]?|joue[srz]?|fais|balance|enclenche|ouvre[srz]?)\s+(?:moi\s+)?"
        r"(?:de\s+la\s+|une\s+|du\s+)?(?:musique|son|spotify)"
        r"|musique\s+(?:al[ée]atoire|likes?|likee?s?|spotify)"
        r"|^musique$|^de\s+la\s+musique$|^spotify$"
        r"|playlist\s+like[se]?)\b",
        txt_l,
    )
    if musique_match:
        veut_shuffle = bool(re.search(r"al[ée]atoire|shuffle|random|m[ée]lange", txt_l))

        # Etape 1 : lancer Spotify directement sur Liked Songs
        spotify_launched = False
        try:
            os.startfile("spotify:collection:tracks")  # URI Likes generique
            spotify_launched = True
            print("[MUSIQUE] Spotify ouvert sur Liked Songs")
        except Exception:
            try:
                from pathlib import Path as _P
                spotify_exe = _P(os.environ.get("APPDATA", "")) / "Spotify" / "Spotify.exe"
                if spotify_exe.exists():
                    subprocess.Popen([str(spotify_exe), "--uri=spotify:collection:tracks"])
                    spotify_launched = True
            except Exception as e:
                print(f"[MUSIQUE] Echec launch Spotify : {e}")

        if spotify_launched:
            # Etape 2 : attendre + bring to front
            await asyncio.sleep(2.5)
            try:
                if pc_actions:
                    pc_actions._bring_to_front("Spotify", max_wait_s=3.0)
            except Exception:
                pass
            await asyncio.sleep(0.6)

            # Etape 3 : cliquer le bouton play vert (Spotify green = #1DB954)
            clicked = _click_spotify_play_button()
            if not clicked:
                # Fallback : touche media playpause (marche si track deja loadee)
                try:
                    import pyautogui as _pa
                    _pa.press("playpause")
                except Exception:
                    pass

            # Etape 4 : shuffle si demande
            if veut_shuffle:
                await asyncio.sleep(0.4)
                try:
                    import pyautogui as _pa
                    _pa.hotkey("ctrl", "shift", "s")
                except Exception:
                    pass

            msg_vocal = f"Musique en aleatoire, {USER_NAME}." if veut_shuffle else f"Musique lancee, {USER_NAME}."
            await _parler_et_restaurer(msg_vocal)
            return

        # Fallback : Spotify introuvable -> YouTube Liked via Playwright
        print("[MUSIQUE] Spotify introuvable, fallback YouTube")
        if jarvis_browser:
            try:
                ok, msg = await jarvis_browser.play_liked_shuffle()
                await _parler_et_restaurer(f"C'est parti, {USER_NAME}." if ok else msg)
                return
            except Exception as e:
                print(f"[MUSIQUE] Erreur Playwright : {e}")
        try:
            webbrowser.open("https://www.youtube.com/playlist?list=LL", new=2)
            await _parler_et_restaurer("Spotify introuvable. J'ouvre ta playlist YouTube.")
            return
        except Exception as e:
            print(f"[MUSIQUE-FALLBACK] {e}")

    # 5bis) "shuffle" / "aleatoire" tout seul -> Ctrl+Shift+S sur Spotify focus
    if re.search(r"^(?:al[ée]atoire|shuffle|m[ée]lange)$", txt_l) or \
       re.search(r"\b(?:active|met[srz]?)\s+(?:le\s+|l['']\s*)?(?:al[ée]atoire|shuffle|m[ée]lange)", txt_l):
        try:
            if pc_actions:
                pc_actions._bring_to_front("Spotify", max_wait_s=2.0)
            await asyncio.sleep(0.3)
            import pyautogui as _pa
            _pa.hotkey("ctrl", "shift", "s")
            await _parler_et_restaurer("Lecture aleatoire activee.")
            return
        except Exception as e:
            print(f"[SHUFFLE] {e}")

    # Reset du flag audio au début de chaque commande.
    # En mode "texte seulement", on conserve le skip pour ne rien vocaliser.
    _skip_pc_audio = not repondre_vocal

    consigner_echange("user", texte_utilisateur)
    await broadcast_chat("user", texte_utilisateur)

    if dev_actions:
        try:
            def _cb_parler_sync(msg: str):
                asyncio.run_coroutine_threadsafe(parler(msg), asyncio.get_event_loop())
            dev_reponse, dev_ok = dev_actions.executer(
                texte_utilisateur,
                obsidian_bridge=OBSIDIAN,
                callback_parler=_cb_parler_sync,
            )
            if dev_reponse and dev_ok:
                print(f"[DEV] {dev_reponse}")
                if mobile_ws:
                    _skip_pc_audio = True
                await parler(dev_reponse)
                _skip_pc_audio = False
                return
        except Exception as e:
            print(f"[DEV] Erreur action dev : {e}")

    # Meross AVANT pc_actions : capture "lumiere" / "allume la lampe" / etc
    # avant que pc_actions essaie de matcher autre chose.
    if meross:
        try:
            m_reponse, m_ok = await meross.async_executer(texte_utilisateur)
            if m_reponse is not None:
                print(f"[MEROSS] {m_reponse}")
                if mobile_ws:
                    _skip_pc_audio = True
                await parler(m_reponse)
                _skip_pc_audio = False
                return
        except Exception as e:
            print(f"[MEROSS] Erreur : {e}")

    # Browser AVANT pc_actions aussi : capture "ouvre/cherche/clique sur..."
    # pour que Jarvis pilote Chromium plutot que d'ouvrir le navigateur systeme.
    if jarvis_browser:
        try:
            b_reponse, b_ok = await jarvis_browser.async_executer(texte_utilisateur)
            if b_reponse is not None:
                print(f"[BROWSER] {b_reponse}")
                if mobile_ws:
                    _skip_pc_audio = True
                # Pour 'lis-moi la page' on parle le contenu extrait, sinon une
                # confirmation courte.
                vocal = b_reponse if len(b_reponse) < 400 else b_reponse[:400] + "..."
                await parler(vocal)
                _skip_pc_audio = False
                return
        except Exception as e:
            print(f"[BROWSER] Erreur : {e}")

    # NB : le connecteur Spotify API est branche plus haut (section 2ter),
    # AVANT les interceptions touches media, pour que pause/suivant/volume
    # controlent le device Spotify actif quand l'API est configuree.

    # OpenClaw AVANT skills/pc_actions : capture "demande a openclaw...",
    # "envoie a openclaw...", "statut openclaw". Le module retourne (None, False)
    # si la commande ne le concerne pas ou s'il n'est pas configure -> la chaine
    # continue normalement.
    if openclaw:
        try:
            oc_reponse, oc_ok = await openclaw.async_executer(texte_utilisateur)
            if oc_reponse is not None:
                print(f"[OPENCLAW] {oc_reponse}")
                if mobile_ws:
                    _skip_pc_audio = True
                await parler(oc_reponse)
                _skip_pc_audio = False
                return
        except Exception as e:
            print(f"[OPENCLAW] Erreur : {e}")

    # Skills utilisateur (jarvis_skills/) AVANT pc_actions : extensions perso prioritaires.
    if skills_loader:
        try:
            sk_reponse, sk_ok = skills_loader.executer_skills(texte_utilisateur)
            if sk_reponse is None:
                sk_reponse, sk_ok = await skills_loader.async_executer_skills(texte_utilisateur)
            if sk_reponse is not None:
                print(f"[SKILLS] {sk_reponse}")
                if mobile_ws:
                    _skip_pc_audio = True
                await parler(sk_reponse)
                _skip_pc_audio = False
                return
        except Exception as e:
            print(f"[SKILLS] Erreur : {e}")

    # Affichage de fichiers/dossiers ("montre le fichier X") avant pc_actions.
    if display_actions:
        try:
            d_reponse, d_ok = display_actions.executer(texte_utilisateur)
            if d_reponse is not None:
                print(f"[DISPLAY] {d_reponse}")
                if mobile_ws:
                    _skip_pc_audio = True
                await parler(d_reponse)
                _skip_pc_audio = False
                return
        except Exception as e:
            print(f"[DISPLAY] Erreur : {e}")

    if pc_actions:
        try:
            pc_reponse, pc_ok = pc_actions.executer(texte_utilisateur)
            if pc_reponse and pc_ok:
                print(f"[PC] {pc_reponse}")
                if mobile_ws:
                    _skip_pc_audio = True
                await parler(pc_reponse)
                _skip_pc_audio = False
                return
        except Exception as e:
            print(f"[PC] Erreur action locale : {e}")

    if claude_bridge and any(kw in texte_utilisateur.lower() for kw in (
        "demande a claude code", "demande à claude code", "passe a claude code",
        "passe à claude code", "envoie a claude", "envoie à claude",
    )):
        prompt_cc = re.sub(
            r"(?i)^.*?(demande[ ]?[aà]?[ ]?claude[ ]?code|passe[ ]?[aà]?[ ]?claude[ ]?code|envoie[ ]?[aà]?[ ]?claude)[ ,:.-]*",
            "",
            texte_utilisateur,
        ).strip() or texte_utilisateur
        await parler(f"J'envoie ca a Claude Code, {USER_NAME}. Un instant.")
        rep_cc, _ok = await asyncio.to_thread(claude_bridge.lancer_claude_code, prompt_cc)
        await parler(rep_cc[:600])
        return

    if claude_bridge and any(kw in texte_utilisateur.lower() for kw in (
        "depuis quand claude code", "derniere fois claude code", "dernière fois claude code",
        "claude code j'y suis", "j'ai pas relance claude", "j'ai pas relancé claude",
    )):
        jours = claude_bridge.jours_depuis_derniere_session()
        if jours is None:
            await parler(f"Je ne trouve aucune session Claude Code, {USER_NAME}.")
        elif jours < 1:
            await parler(f"Tu as utilise Claude Code il y a {int(jours * 24)} heures.")
        else:
            await parler(f"Ta derniere session Claude Code remonte a {int(jours)} jours.")
        return

    # TENTATIVE DE RÉSOLUTION LOCALE (Math, Français, Conversion, Traduction)
    reponse = resoudre_math_localement(texte_utilisateur)
    if not reponse: reponse = resoudre_francais_localement(texte_utilisateur)
    if not reponse: reponse = resoudre_conversion_localement(texte_utilisateur)
    if not reponse: reponse = resoudre_traduction_localement(texte_utilisateur)
    
    # VISION (Regarde mon écran)
    if not reponse:
        t = texte_utilisateur.lower()
        if any(keyword in t for keyword in ["regarde mon écran", "analyse mon écran", "vois-tu mon écran", "qu'est-ce qu'il y a sur mon écran"]):
            await parler(f"Bien sûr {USER_NAME}, laissez-moi jeter un œil...")
            img_b64 = await request_screen_capture()
            if img_b64:
                reponse = await demander_ia_vision(texte_utilisateur, img_b64)
            else:
                reponse = f"Je suis désolé {USER_NAME}, mais je n'ai pas pu capturer votre écran. Assurez-vous d'avoir cliqué sur 'Activer la vision' sur l'interface et d'avoir autorisé le partage."

    # Mode local Ollama : streaming + TTS phrase par phrase (reponse perçue ~5x plus rapide)
    if not reponse and FORCE_OLLAMA and not mobile_ws:
        reponse = await repondre_streaming(texte_utilisateur)
        print(f"[JARVIS] {reponse}")
        json_blocks = re.findall(r'\{.*?\}', reponse, re.DOTALL)
        if not json_blocks:
            return  # deja parle en streaming

    # AGENT : si Gemini est dispo, on lance l'agent function-calling avant le
    # fallback demander_ia. L'agent peut soit appeler des tools (lumiere,
    # musique, navigateur, apps) soit juste repondre du texte (= conversation).
    elif not reponse and GEMINI_DISPONIBLE and jarvis_agent and client:
        try:
            await send_web_state("thinking")
            agent_model = MODELS_LIST[1] if len(MODELS_LIST) > 1 else MODELS_LIST[0]  # gemini-2.5-flash
            sys_prompt = (
                f"Tu es Jarvis, assistant vocal personnel de {USER_NAME}. Tu controles son PC Windows. "
                "Tu DOIS utiliser les tools disponibles pour agir : "
                "toggle_light/set_light pour la prise Meross, media_control/set_volume pour l'audio, "
                "play_music pour Spotify, open_app pour lancer des apps, browser_* pour Chromium pilote, "
                "play_youtube pour lire une video YouTube en plein ecran, screens_off pour eteindre les ecrans, "
                "lock_pc/screenshot/close_active_window pour les actions systeme. "
                "Tu peux enchainer plusieurs tools si la demande est complexe. "
                "Termine TOUJOURS par 'respond' avec une phrase courte et naturelle en francais "
                f"(ex: 'C'est fait, {USER_NAME}.' ou la reponse a une question conversationnelle). "
                "Si la demande est juste conversationnelle (question generale, blague, info), "
                "appelle directement 'respond' avec ta reponse. "
                f"Utilise show_content pour MONTRER visuellement du contenu a {USER_NAME} "
                "(listes, tableaux, comparatifs, longs textes, images, liens) dans une fenetre "
                f"— obligatoire quand {USER_NAME} dit 'montre-moi' ou 'affiche'. "
                + ("Des tools mcp_* (connecteurs externes configures dans le dashboard) "
                   "sont aussi disponibles." if _MCP_TOOL_DECLS else "")
            )
            reponse = await jarvis_agent.run_agent(
                client=client,
                model_name=agent_model,
                system_prompt=sys_prompt,
                user_text=texte_utilisateur,
                dispatch=_agent_dispatch,
                extra_tools=_MCP_TOOL_DECLS or None,
            )
            print(f"[AGENT] Reponse finale : {reponse}")
        except Exception as e:
            print(f"[AGENT] Echec : {e} -> fallback demander_ia")
            reponse = await demander_ia(texte_utilisateur)
    elif not reponse:
        reponse = await demander_ia(texte_utilisateur)

    if not reponse:
        return

    print(f"[JARVIS] {reponse}")

    if mobile_ws:
        _skip_pc_audio = True

    json_blocks = re.findall(r'\{.*?\}', reponse, re.DOTALL)

    if not json_blocks:
        await parler(reponse)
        _skip_pc_audio = False
        # Reponse conversationnelle reussie : on declenche en arriere-plan le resume
        # d'historique (si trop long) et l'extraction proactive de faits (opt-in).
        # Ces taches ne bloquent jamais et degradent proprement si indisponibles.
        _lancer_taches_post_conversation(texte_utilisateur, reponse)
        return

    for block in json_blocks:
        try:
            print(f"[JARVIS] Execution de l'action : {block}")
            # Timeout de 15s pour chaque action pour eviter de freezer Jarvis
            data = json.loads(block)
            action = data.get("action", "")
            
            # On execute l'action avec un timeout
            try:
                # Note: On utilise asyncio.wait_for pour les actions asynchrones
                # Les actions synchrones comme ha_lumiere devraient idéalement être async aussi
                # mais pour l'instant on les laisse ainsi ou on les wrappe.
                pass 
            except asyncio.TimeoutError:
                print(f"[ACTION ERROR] Timeout sur l'action {action}")
                if grok_client:
                    await parler(f"C'est un peu long {USER_NAME}, je demande une vérification à Grok.")
                    rep_grok = await demander_grok(texte_utilisateur + " (L'action domotique a expiré, peux-tu répondre à l'utilisateur ?)")
                    if rep_grok: await parler(rep_grok)
                continue

            if action == "mode_iron_man":
                etat = data.get("etat", "off")
                MODE_IRON_MAN = (etat == "on")
                msg = "Mode Iron Man activé, Monsieur. Je reste à l'écoute de vos signaux." if MODE_IRON_MAN else "Mode Iron Man désactivé. Je repasse en veille domotique."
                await parler(msg)
            elif action == "memoriser":
                cle    = data.get("cle",    "info")
                valeur = data.get("valeur", "")
                ajouter_memoire(cle, valeur)
                await parler(f"Bien note {USER_NAME}, je me souviendrai que {valeur}.")
            elif action == "oublier":
                cle     = data.get("cle", "")
                success = supprimer_memoire(cle)
                if success:
                    await parler(f"Information oubliee, {USER_NAME}.")
                else:
                    await parler("Je n avais pas cette information en memoire.")
            elif action == "lister_memoire":
                memoire = charger_memoire()
                if not memoire:
                    await parler(f"Aucune information personnalisee en memoire, {USER_NAME}.")
                else:
                    lignes = [f"Voici ce que je sais sur vous {USER_NAME}."]
                    for cle, data_m in memoire.items():
                        lignes.append(f"{cle} : {data_m['valeur']}.")
                    await parler(" ".join(lignes))
            elif action == "ouvrir_dossier":
                chemin = data.get("chemin", "bureau")
                ok, resultat = ouvrir_dossier(chemin)
                if ok:
                    await parler(f"Dossier ouvert, {USER_NAME}. Dites-moi si vous voulez que je le trie.")
                else:
                    await parler(f"Je n ai pas trouve ce dossier, {USER_NAME}. {resultat}")
            elif action == "lister_dossier":
                contenu, err = lister_dossier()
                if err:
                    await parler(err)
                else:
                    nb_fichiers = len(contenu["fichiers"])
                    nb_dossiers = len(contenu["dossiers"])
                    await parler(f"Le dossier contient {nb_fichiers} fichiers et {nb_dossiers} sous-dossiers, {USER_NAME}.")
            elif action == "trier_par_type":
                await parler(f"Je trie vos fichiers par type, {USER_NAME}. Un instant.")
                ok, msg = trier_par_type()
                await parler(msg if ok else f"Probleme lors du tri : {msg}")
            elif action == "trier_par_date":
                await parler(f"Je trie vos fichiers par date, {USER_NAME}. Un instant.")
                ok, msg = trier_par_date()
                await parler(msg if ok else f"Probleme lors du tri : {msg}")
            elif action == "trier_complet":
                await parler(f"Je trie vos fichiers par type puis par date dans chaque categorie, {USER_NAME}.")
                ok, msg = trier_par_type_puis_date()
                await parler(msg if ok else f"Probleme lors du tri : {msg}")
            elif action == "creer_dossier":
                nom     = data.get("nom", "Nouveau Dossier")
                ok, msg = creer_sous_dossier(nom)
                await parler(msg if ok else f"Erreur : {msg}")
            elif action == "renommer_fichier":
                ancien  = data.get("ancien", "")
                nouveau = data.get("nouveau", "")
                ok, msg = renommer_fichier(ancien, nouveau)
                await parler(msg if ok else f"Erreur : {msg}")
            elif action == "deplacer_fichier":
                fichier = data.get("fichier",     "")
                dest    = data.get("destination", "")
                ok, msg = deplacer_fichier(fichier, dest)
                await parler(msg if ok else f"Erreur : {msg}")
            elif action == "chercher_fichier":
                nom        = data.get("nom", "")
                resultats, err = chercher_fichier(nom)
                if err:
                    await parler(err)
                elif not resultats:
                    await parler(f"Aucun fichier contenant {nom} n a ete trouve, {USER_NAME}.")
                else:
                    noms = [os.path.basename(r) for r in resultats[:5]]
                    await parler(f"J ai trouve {len(resultats)} fichier(s). Par exemple : {', '.join(noms)}.")
            elif action == "ha_lumiere":
                piece      = data.get("piece",      "salon")
                etat       = data.get("etat",       "on")
                couleur    = data.get("couleur",    None)
                luminosite = data.get("luminosite", None)
                entity_id  = PIECES_LUMIERES.get(piece, f"light.{piece}")
                rgb        = COULEURS_MAP.get(couleur) if couleur else None
                ha_lumiere(entity_id, etat, luminosite, rgb)
                
                # Message de confirmation amélioré
                if etat == "off":
                    msg = f"J'éteins {piece}."
                else:
                    details = []
                    if couleur: details.append(f"en {couleur}")
                    if luminosite is not None: 
                        pourcent = int((int(luminosite)/255)*100)
                        details.append(f"à {pourcent}%")
                    
                    if details:
                        msg = f"C'est fait, {piece} est réglé{' '.join(details)}."
                    else:
                        msg = f"Lumière {piece} allumée."
                await parler(msg)
            elif action == "ha_prise":
                piece     = data.get("piece", "bureau")
                etat      = data.get("etat",  "on")
                entity_id = PIECES_PRISES.get(piece, f"switch.prise_{piece}")
                ha_interrupteur(entity_id, etat)
                msg = f"Prise {piece} {'activée' if etat == 'on' else 'désactivée'}."
                await parler(msg)
            elif action == "ha_temperature":
                piece     = data.get("piece", "salon")
                entity_id = PIECES_CAPTEURS.get(piece)
                if entity_id:
                    temp = ha_get_etat(entity_id)
                    await parler(f"La température dans le {piece} est de {temp} degrés.")
                else:
                    await parler(f"Désolé, je n'ai pas de capteur configuré pour le {piece}.")
            elif action == "ha_humidite":
                piece     = data.get("piece", "bureau")
                entity_id = PIECES_HUMIDITE.get(piece)
                if entity_id:
                    humi = ha_get_etat(entity_id)
                    await parler(f"Le taux d'humidité dans le {piece} est de {humi}%.")
                else:
                    await parler(f"Je n'ai pas de capteur d'humidité pour le {piece}.")
            elif action == "ha_batterie":
                appareil  = data.get("appareil", "").lower()
                entity_id = APPAREILS_BATTERIE.get(appareil)
                if entity_id:
                    batt = ha_get_etat(entity_id)
                    if batt == "unknown":
                        await parler(f"Je n'arrive pas à récupérer l'état de la batterie pour {appareil}.")
                    else:
                        suff = ""
                        if "mon telephone" in appareil or "telephone" in appareil:
                            suff = "Ton téléphone est à "
                        else:
                            suff = f"La batterie de {appareil} est à "
                        await parler(f"{suff}{batt}%.")
                else:
                    await parler(f"Je n'ai pas l'appareil {appareil} dans ma liste de batterie.")
            elif action == "ha_thermostat":
                temp = data.get("temperature", 20)
                ha_thermostat("climate.thermostat", temp)
                await parler(f"Thermostat réglé à {temp} degrés.")
            elif action == "ha_scene":
                nom      = data.get("nom", "")
                scene_id = f"scene.{nom}"
                ha_scene(scene_id)
                await parler(f"Ambiance {nom} activée.")
            elif action == "ha_alarme":
                etat = data.get("etat", "on")
                if etat == "on":
                    ha_appeler_service("alarm_control_panel", "alarm_arm_away", "alarm_control_panel.home_base_2")
                    await parler("Alarme activée.")
                else:
                    ha_appeler_service("alarm_control_panel", "alarm_disarm", "alarm_control_panel.home_base_2")
                    await parler("Alarme désactivée.")
            elif action == "ha_simulation":
                etat = data.get("etat", "on")
                ha_interrupteur("switch.simulation", etat)
                msg = "Simulation de présence activée." if etat == "on" else "Simulation de présence désactivée."
                await parler(msg)
            elif action == "ha_anniversaires":
                events = ha_get_calendrier("calendar.anniversaires")
                if not events:
                    await parler("Rien de prévu aujourd'hui.")
                else:
                    noms = [e.get("summary", "Anniversaire sans nom") for e in events]
                    if len(noms) == 1:
                        await parler(f"Aujourd'hui, nous fêtons l'anniversaire de {noms[0]}. N'oubliez pas de lui souhaiter !")
                    else:
                        liste = ", ".join(noms[:-1]) + " et " + noms[-1]
                        await parler(f"Aujourd'hui, il y a plusieurs anniversaires : {liste}. C'est une journée chargée !")
            elif action == "ha_consommation":
                entity_id = PIECES_CAPTEURS.get("consommation")
                puissance = ha_get_etat(entity_id)
                if puissance == "unknown" or puissance == "inconnu":
                    await parler("Je n'arrive pas à lire la consommation électrique pour le moment.")
                else:
                    await parler(f"La consommation actuelle de la maison est de {puissance} Volt-Ampères.")
            elif action == "ha_tiktok":
                entity_id = PIECES_CAPTEURS.get("tiktok")
                followers = ha_get_etat(entity_id)
                await parler(f"Tu as actuellement {followers} abonnés sur ton compte TikTok, {USER_NAME}. Félicitations !")
            elif action == "ha_oeufs":
                entity_id = PIECES_CAPTEURS.get("oeufs")
                # On récupère l'état (le dernier choix) et le moment de la modif
                try:
                    r = requests.get(f"{HA_URL}/api/states/{entity_id}", headers=HA_HEADERS, timeout=5)
                    data = r.json()
                    last_changed = data.get("last_changed", "")
                    if last_changed:
                        dt = datetime.fromisoformat(last_changed.replace("Z", "+00:00"))
                        phrase = dt.strftime("le %d %B à %Hh%M")
                        await parler(f"Le dernier ramassage des œufs a été enregistré {phrase}.")
                    else:
                        await parler("Je n'ai pas d'historique pour le ramassage des œufs.")
                except:
                    await parler("Je n'arrive pas à accéder aux informations sur les œufs.")
            elif action == "ha_energie":
                periode  = data.get("periode", "mois")
                appareil = data.get("appareil", "")
                
                if appareil:
                    appareil_clean = appareil.lower()
                    entite = APPAREILS_ENERGIE.get(appareil_clean)
                    if entite:
                        val = ha_get_etat(entite)
                        if val != "inconnu" and val != "unknown":
                            kwh = float(val)
                            await parler(f"La consommation de {appareil} pour ce mois est de {kwh:.1f} kWh.")
                        else:
                            await parler(f"Je n'ai pas de données de consommation pour {appareil} pour le moment.")
                    else:
                        await parler(f"Je n'ai pas d'appareil nommé {appareil} dans mon suivi énergétique.")
                elif periode == "hier":
                    total_kwh = 0
                    total_cost = 0
                    try:
                        for i in range(1, 7):
                            e_id = f"sensor.lixee_zlinky_tic_zlinky_p{i}_daily"
                            val = ha_get_etat(e_id, attribut="last_period")
                            if val != "inconnu" and val != "unknown":
                                k = float(val)
                                total_kwh += k
                                total_cost += k * HA_TARIFS.get(f"p{i}", 0.16)
                        await parler(f"Hier, la maison a consommé {total_kwh:.1f} kWh, pour un coût estimé à {total_cost:.2f} euros.")
                    except:
                        await parler("J'ai eu un problème pour calculer la consommation d'hier.")
                else: # mois
                    total_kwh = 0
                    total_cost = 0
                    try:
                        for i in range(1, 7):
                            e_id = f"sensor.lixee_zlinky_tic_zlinky_p{i}_mensuel"
                            val = ha_get_etat(e_id)
                            if val != "inconnu" and val != "unknown":
                                k = float(val)
                                total_kwh += k
                                total_cost += k * HA_TARIFS.get(f"p{i}", 0.16)
                        await parler(f"Ce mois-ci, la consommation totale est de {total_kwh:.1f} kWh, pour un montant de {total_cost:.2f} euros.")
                    except:
                        await parler("Je n'ai pas pu calculer la consommation mensuelle.")
            elif action == "ha_aspirateur":
                commande = data.get("commande", "start")
                if commande == "start":
                    ha_appeler_service("vacuum", "start", "vacuum.bob")
                    await parler("C'est parti, Bob lance le nettoyage.")
                elif commande == "stop":
                    ha_appeler_service("vacuum", "stop", "vacuum.bob")
                    await parler("J'ai arrêté l'aspirateur.")
                elif commande == "pause":
                    ha_appeler_service("vacuum", "pause", "vacuum.bob")
                    await parler("Bob est en pause.")
                elif commande == "base":
                    ha_appeler_service("vacuum", "return_to_base", "vacuum.bob")
                    await parler("Bob retourne à sa base.")
            elif action == "create_doc":
                titre   = data.get("title",   "Document JARVIS")
                contenu = data.get("content", "")
                result  = creer_google_doc(titre, contenu)
                await parler(result)
            elif action == "write_doc":
                contenu = data.get("content", "")
                result  = modifier_google_doc(contenu)
                await parler(result)
            elif action == "create_sheet":
                titre  = data.get("title", "Feuille JARVIS")
                result = creer_google_sheet(titre)
                await parler(result)
            elif action == "read_emails":
                result = lire_emails()
                await parler(f"Voici vos derniers emails {USER_NAME}. {result}")
            elif action == "read_calendar":
                result = lister_evenements_calendar()
                await parler(f"Voici vos prochains evenements {USER_NAME}. {result}")
            elif action == "meteo":
                ville = data.get("ville") or None
                await parler(f"Je consulte la meteo, un instant {USER_NAME}.")
                result = get_meteo_actuelle(ville)
                await parler(result)
            elif action == "alerte_meteo":
                ville = data.get("ville") or None
                result = get_alertes_meteo(ville)
                await parler(result)
            elif action == "recherche_web":
                query = data.get("query", "")
                await parler(f"Je lance une recherche sur internet pour {query}.")
                result = recherche_web_serpapi(query)
                await parler(result)
            elif action == "sport_resultats":
                equipe = data.get("equipe") or None
                ligue  = data.get("ligue")  or None
                print(f"[SPORT] Action sport_resultats pour {equipe or ligue}")
                await parler(f"Je cherche les informations pour {equipe or ligue}, un instant.")
                result = get_resultats_football(equipe=equipe, ligue=ligue)
                if "pas trouvé" in result or "Impossible" in result:
                    print(f"[SPORT] Echec recherche locale. Verification avec Grok...")
                    if grok_client:
                        res_grok = await demander_grok(f"{USER_NAME} veut savoir : {texte_utilisateur}. Je n'ai pas trouvé l'info dans ma base de données football, peux-tu chercher pour lui ?")
                        if res_grok: result = res_grok
                await parler(result)
            elif action == "sport_classement":
                ligue  = data.get("ligue", "Ligue 1")
                await parler(f"Je recupere le classement {ligue}.")
                result = get_classement_football(ligue=ligue)
                await parler(result)
            elif action == "sport_live":
                question = data.get("question", "derniers resultats sportifs 2026")
                await parler(f"Je recherche les derniers resultats en direct, un instant {USER_NAME}.")
                result = get_resultats_sport_gemini(question)
                await parler(result)
            elif action == "voir_ecran":
                inst = data.get("instruction", "")
                res = await jarvis_vision_cliquer(inst)
                await parler(res)
            elif action == "whatsapp_appel":
                contact = data.get("contact", "")
                await action_whatsapp_appel(contact)
            elif action == "vision_ecrire":
                inst = data.get("instruction", "")
                txt  = data.get("texte", "")
                res  = await jarvis_vision_ecrire(inst, txt)
                await parler(res)

        except Exception as e:
            print(f"[ACTION ERROR] Block failed: {block} | Error: {e}")
            if grok_client:
                print("[JARVIS] Bascule sur Grok suite a une erreur d'action...")
                res_grok = await demander_grok(f"{USER_NAME} m'a demandé : {texte_utilisateur}. J'ai tenté de lancer une action mais j'ai eu une erreur technique ({e}). Peux-tu prendre le relais et lui répondre élégamment ?")
                if res_grok: await parler(res_grok)
            continue

    # Si du texte reste après les commandes, on ne fait rien de plus car `parler` a déjà été appelé pour chaque action ou la réponse globale.
    # Réinitialiser le flag audio PC
    _skip_pc_audio = False


# Verrou de SERIALISATION des commandes proactives : routines et triggers
# peuvent se chevaucher (une routine parle pendant qu'un trigger se declenche).
# Or traiter_reponse_ia/parler mutent des globals partages (STOP_PARLER,
# is_speaking, pygame.mixer...). Une seule commande proactive a la fois evite
# que deux TTS se telescopent et se corrompent mutuellement.
_PROACTIF_LOCK = asyncio.Lock()


async def _executer_commande_proactive(texte: str) -> None:
    """Exécute une commande déclenchée de façon proactive (routine ou trigger).

    Callable injectée dans les modules `routines` et `triggers` : elle se
    comporte comme si l'utilisateur avait prononcé `texte`, en passant par
    `traiter_reponse_ia`. Sérialisée par `_PROACTIF_LOCK` (une commande proactive
    à la fois) et encapsulée dans un try/except pour qu'une erreur n'interrompe
    jamais la boucle du planificateur ou de la surveillance.

    Args:
        texte: La commande à exécuter (ex: "quelle est la météo").
    """
    try:
        async with _PROACTIF_LOCK:
            print(f"[PROACTIF] Exécution commande proactive : '{texte}'")
            await traiter_reponse_ia(texte)
    except Exception as e:
        print(f"[PROACTIF] Echec exécution commande proactive '{texte}' : {e}")


async def _executer_commande_texte(texte: str) -> str:
    """Exécute une commande texte (ex: depuis Telegram) et RETOURNE la réponse.

    Contrairement à `traiter_reponse_ia` (qui vocalise via TTS PC et ne renvoie
    rien), cette coroutine fait passer le texte directement par la chaîne IA
    (`demander_ia`) et renvoie la réponse sous forme de chaîne, SANS TTS PC :
    le canal distant (Telegram) affiche le texte lui-même, on ne veut pas que le
    PC se mette à parler à chaque message reçu.

    Injectée dans `messaging_bridge.demarrer_telegram`. Toute erreur est capturée
    et transformée en message lisible — ne propage jamais d'exception (sinon la
    boucle de long-polling Telegram mourrait).

    Args:
        texte: La commande/question telle qu'envoyée par l'utilisateur distant.

    Returns:
        La réponse textuelle de Jarvis (ou un message d'erreur lisible).
    """
    texte = (texte or "").strip()
    if not texte:
        return "Message vide."
    try:
        reponse = await demander_ia(texte)
        if not reponse:
            return "Je n'ai pas de réponse à donner."
        return str(reponse)
    except Exception as e:
        print(f"[MESSAGING] Echec exécution commande texte '{texte}' : {e}")
        return "Désolé, une erreur est survenue lors du traitement."


WAKE_WORD       = "jarvis"
SESSION_TIMEOUT = 30
STOP_PARLER      = False
is_listening     = False
is_speaking      = False
jarvis_actif     = False
dernier_message  = 0
interface_deja_connectee = False

def ecouter():
    global is_listening, jarvis_actif, dernier_message, STOP_PARLER, is_speaking

    r   = sr.Recognizer()
    mic = sr.Microphone()

    r.pause_threshold        = 0.6
    r.non_speaking_duration  = 0.5
    r.energy_threshold       = 300
    r.dynamic_energy_threshold = True

    with mic as source:
        r.adjust_for_ambient_noise(source, duration=1)

    # Wake word local OPT-IN : detecteur openWakeWord cree une seule fois si le
    # flag JARVIS_WAKE_LOCAL est on et le module + un modele sont chargeables.
    # Sert de pre-gate : quand Jarvis n'est PAS actif, on n'appelle le STT couteux
    # QUE si le wake est detecte sur l'audio capture. Si le flag est OFF ou
    # openWakeWord indispo, detecteur_wake reste None -> logique de wake par texte
    # historique strictement inchangee.
    detecteur_wake = None
    if WAKE_LOCAL and wake_word is not None:
        try:
            if wake_word.disponible():
                detecteur_wake = wake_word.creer_detecteur()
        except Exception as e:
            print(f"[WAKE] Echec creation detecteur openWakeWord : {e}")
            detecteur_wake = None
        if detecteur_wake is not None:
            print("[WAKE] Pre-gate openWakeWord actif.")

    print("[JARVIS] Microphone pret. En attente de 'Jarvis' ou session active...")

    while True:
        try:
            # GESTION DU TIMEOUT DE SESSION
            if jarvis_actif and (time.time() - dernier_message > SESSION_TIMEOUT):
                print("[JARVIS] Timeout session. Retour en veille.")
                jarvis_actif = False

            with mic as source:
                is_listening = True
                loop_ws = asyncio.new_event_loop()
                state = "active" if jarvis_actif else "listening"
                loop_ws.run_until_complete(send_web_state(state))
                loop_ws.close()
                
                audio = r.listen(source, timeout=2, phrase_time_limit=10)
                
                is_listening = False
                loop_ws = asyncio.new_event_loop()
                loop_ws.run_until_complete(send_web_state("idle"))
                loop_ws.close()

            # PRE-GATE WAKE WORD LOCAL (OPT-IN) : si un detecteur openWakeWord est
            # actif et que Jarvis n'est PAS deja reveille, on n'appelle le STT
            # couteux QUE si le wake est detecte sur l'audio capture. Sinon on
            # reboucle sans transcrire (economie). Tout echec ici -> on laisse
            # passer au STT pour ne JAMAIS bloquer la boucle.
            if detecteur_wake is not None and not jarvis_actif:
                try:
                    # Audio capture -> PCM brut 16 kHz mono int16, decoupe en
                    # frames ~80 ms (1280 echantillons) pour openWakeWord.
                    pcm = audio.get_raw_data(convert_rate=16000, convert_width=2)
                    detecteur_wake.reset()
                    taille_frame = 1280 * 2  # 1280 echantillons * 2 octets (int16)
                    wake_detecte = False
                    for i in range(0, len(pcm) - taille_frame + 1, taille_frame):
                        if detecteur_wake.verifier_frame(pcm[i:i + taille_frame]):
                            wake_detecte = True
                            break
                    if not wake_detecte:
                        # Pas de wake detecte -> on ne transcrit pas, on reboucle.
                        continue
                    print("[WAKE] Wake word local detecte.")
                except Exception as e:
                    # Detecteur en echec : on n'interrompt pas la boucle, on
                    # poursuit avec le STT + wake par texte (repli universel).
                    print(f"[WAKE] Echec pre-gate (repli STT) : {e}")

            # STT : local (faster-whisper) UNIQUEMENT si le flag JARVIS_STT_LOCAL est
            # actif. Sinon on garde la ligne historique EXACTE (recognize_google qui
            # LEVE sr.UnknownValueError/sr.RequestError -> geres par les except plus
            # bas) pour ne RIEN changer au comportement actuel quand le flag est OFF.
            if STT_LOCAL and voice_stt is not None:
                texte = (voice_stt.transcrire(r, audio, language="fr-FR") or "").lower().strip()
                if not texte:
                    # whisper/repli n'a rien compris : on saute l'iteration comme le
                    # faisait UnknownValueError (pas de refresh de session, pas d'aval).
                    continue
            else:
                texte = r.recognize_google(audio, language="fr-FR").lower().strip()
            print(f"[ENTENDU] {texte}")

            # GESTION INTERRUPTION DURANT LA PAROLE
            if is_speaking and ("tais-toi" in texte or "silence" in texte or "tais toi" in texte):
                STOP_PARLER = True
                continue

            # MOTS-CLÉS DE SOMMEIL
            SLEEP_WORDS = ["merci", "ce sera tout", "repos", "au revoir", "silence", "tais-toi", "tais toi"]
            if any(word in texte for word in SLEEP_WORDS):
                if jarvis_actif:
                    jarvis_actif = False
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(parler(f"A votre service {USER_NAME}. Je me mets en veille."))
                    loop.close()
                continue

            # Detection texte du wake word. Par defaut : substring "jarvis"
            # (comportement historique strictement inchange). Quand le flag
            # JARVIS_WAKE_LOCAL est on, on ajoute le repli mot_present (insensible
            # casse/accents, gere les variantes de transcription whisper). Gate sur
            # WAKE_LOCAL pour ne RIEN changer quand le flag est OFF.
            wake_dans_texte = WAKE_WORD in texte
            if WAKE_LOCAL and not wake_dans_texte and wake_word is not None:
                try:
                    wake_dans_texte = wake_word.mot_present(texte)
                except Exception as e:
                    print(f"[WAKE] Echec mot_present (repli substring) : {e}")

            if wake_dans_texte or jarvis_actif:
                if wake_dans_texte:
                    print("[JARVIS] Mot-clé détecté.")
                    jarvis_actif = True

                dernier_message = time.time()
                commande = nettoyer_commande(texte)

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                if commande:
                    action_pc = executer_action_pc(commande)
                    if action_pc:
                        loop.run_until_complete(parler(action_pc))
                    else:
                        loop.run_until_complete(traiter_reponse_ia(commande))
                else:
                    if wake_dans_texte: # "Jarvis" tout seul
                        loop.run_until_complete(parler(f"Oui {USER_NAME}, je vous écoute."))

                loop.close()
            else:
                pass

        except sr.WaitTimeoutError:
            pass
        except sr.UnknownValueError:
            pass
        except Exception as e:
            print(f"Erreur écoute : {e}")
            time.sleep(1)

def monitor_claps():
    try:
        import audioop
        p = pyaudio.PyAudio()
        # On ouvre le flux
        stream = p.open(format=pyaudio.paInt16, channels=1, rate=44100, input=True, frames_per_buffer=1024)
        print("[CLAP] Détection des applaudissements activée.")
        
        print("[CLAP] Détection des doubles applaudissements activée.")
        
        last_clap_time = 0
        
        while True:
            try:
                data = stream.read(1024, exception_on_overflow=False)
                rms  = audioop.rms(data, 2)
                
                # ON IGNORE LE CLAP UNIQUEMENT SI LE MODE IRON MAN EST ÉTEINT OU SI JARVIS PARLE
                if not MODE_IRON_MAN or is_speaking or is_thinking:
                    last_clap_time = 0
                    continue

                if rms > CLAP_THRESHOLD:
                    current_time = time.time()
                    diff = current_time - last_clap_time
                    
                    if 0.1 < diff < 0.8:
                        global VIDEO_LANCEE
                        print(f"\n[CLAP] !!! DOUBLE CLAP DÉTECTÉ !!!")
                        entity_id = PIECES_LUMIERES.get("salon", "light.salon")
                        
                        # On vérifie l'état actuel
                        etat_actuel = ha_get_etat(entity_id)
                        
                        if etat_actuel != "on":
                            # ON ALLUME
                            print(f"[CLAP] Action : ALLUMER")
                            ha_lumiere(entity_id, "on")
                            
                            if not VIDEO_LANCEE:
                                print(f"[CLAP] Lancement initial de la vidéo...")
                                webbrowser.open("https://www.youtube.com/watch?v=KU5V5WZVcVE")
                                VIDEO_LANCEE = True
                                def seq():
                                    time.sleep(5)
                                    pyautogui.press('f')
                                threading.Thread(target=seq, daemon=True).start()
                            else:
                                print(f"[CLAP] Reprise de la vidéo (Play)...")
                                pyautogui.press('k')
                        else:
                            # ON ÉTEINT
                            print(f"[CLAP] Action : ÉTEINDRE")
                            ha_lumiere(entity_id, "off")
                            if VIDEO_LANCEE:
                                print(f"[CLAP] Mise en pause de la vidéo...")
                                pyautogui.press('k')
                            
                        # Gros debounce après une action réussie
                        time.sleep(3.0)
                        last_clap_time = 0 # Reset
                    else:
                        # C'est peut-être le premier clap
                        last_clap_time = current_time
            except Exception as e:
                # Si erreur de lecture (ex: micro débranché), on attend et on continue
                time.sleep(0.5)
                continue

    except Exception as e:
        print(f"[CLAP] Erreur fatale détection claps : {e}")

def start_ia():
    # monitor_claps desactive (domotique)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def start_ws():
        global _WS_LOOP
        _WS_LOOP = asyncio.get_running_loop()
        print("[WEB] Serveur WebSocket demarre sur ws://0.0.0.0:8765")
        print(f"[WEB] Accessible depuis le reseau : ws://{LAN_IP}:8765")
        # Connecte les serveurs MCP actifs et expose leurs tools a l'agent
        # (meme event loop que ws_handler : les sessions MCP y vivent).
        if mcp_client:
            asyncio.create_task(_init_mcp_tools())
        if claude_bridge:
            async def notif_inactivite(jours):
                msg = (
                    f"{USER_NAME}, ca fait {int(jours)} jours que tu n'as pas relance Claude Code. "
                    "Tu veux qu'on s'y remette ?"
                )
                print(f"[CLAUDE-WATCH] {msg}")
                await parler(msg)
            asyncio.create_task(claude_bridge.surveiller_inactivite(
                seuil_jours=CLAUDE_INACTIVITE_SEUIL_JOURS,
                callback=notif_inactivite,
                intervalle_check_s=3600.0,
            ))
            print(f"[CLAUDE-WATCH] Surveillance inactivite active (seuil : {CLAUDE_INACTIVITE_SEUIL_JOURS} jours).")
        # Proactivite (PR D) : planificateur de routines + surveillance de triggers.
        # Les deux tournent dans la meme event loop que le serveur WebSocket et
        # reçoivent _executer_commande_proactive comme callable d'exécution.
        if routines:
            try:
                asyncio.create_task(routines.demarrer_planificateur(_executer_commande_proactive))
                print("[ROUTINES] Planificateur de routines actif.")
            except Exception as e:
                print(f"[ROUTINES] Echec demarrage planificateur : {e}")
        if triggers and triggers.disponible():
            try:
                asyncio.create_task(triggers.demarrer_surveillance(_executer_commande_proactive))
                print("[TRIGGERS] Surveillance des triggers contextuels active.")
            except Exception as e:
                print(f"[TRIGGERS] Echec demarrage surveillance : {e}")
        elif triggers:
            print("[TRIGGERS] psutil indisponible : surveillance des triggers desactivee.")
        # Bridge Telegram (PR E) : long-polling getUpdates. Chaque message texte
        # passe par _executer_commande_texte (chaine IA, retourne la reponse) et
        # est renvoye via sendMessage. Tourne dans la meme event loop que le WS.
        if messaging_bridge and messaging_bridge.telegram_disponible():
            try:
                asyncio.create_task(messaging_bridge.demarrer_telegram(_executer_commande_texte))
                print("[MESSAGING] Bridge Telegram actif (long-polling getUpdates).")
            except Exception as e:
                print(f"[MESSAGING] Echec demarrage bridge Telegram : {e}")
        elif messaging_bridge:
            print("[MESSAGING] TELEGRAM_BOT_TOKEN absent : bridge Telegram desactive.")
        async with websockets.serve(ws_handler, "0.0.0.0", 8765):
            await asyncio.Future()

    threading.Thread(target=lambda: asyncio.run(start_ws()), daemon=True).start()

    # Mode serveur headless : pas de micro ni de sortie audio locale. Le serveur
    # WebSocket (thread ci-dessus) suffit ; on n'entre pas dans la boucle vocale.
    if HEADLESS:
        print("[HEADLESS] Mode serveur : greeting vocal et boucle micro desactives.")
        return

    loop.run_until_complete(parler(f"Bonjour, {USER_NAME}"))
    loop.close()
    ecouter()

# ==========================================
# LANCEMENT — MODE CONSOLE + FRONTEND WEB
# ==========================================
# Ursina desactive : l'interface est maintenant le frontend Three.js
# dans le dossier frontend/ (npm run dev -> http://localhost:5173)
# Le WebSocket est deja demarre par start_ia() sur ws://localhost:8765

if pygame is not None and not HEADLESS:
    try:
        pygame.init()
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    except Exception as _e:
        print(f"[AUDIO] Init pygame mixer echouee (mode sans audio ?) : {_e}")

def start_global_hotkey():
    """Ctrl+Shift+J depuis n'importe ou : ouvre/focus la fenetre Jarvis dans le navigateur."""
    try:
        import keyboard
    except ImportError:
        print("[HOTKEY] lib 'keyboard' indisponible, raccourci global desactive.")
        return

    target_url = "http://localhost:5173"

    def focus_or_open():
        try:
            import pygetwindow as gw
            wins = gw.getAllWindows()
            jarvis_win = None
            for w in wins:
                title = (w.title or "").lower()
                if "jarvis" in title or "localhost:5173" in title or "localhost:5174" in title or "localhost:5175" in title:
                    jarvis_win = w
                    break
            if jarvis_win:
                try:
                    if jarvis_win.isMinimized:
                        jarvis_win.restore()
                    jarvis_win.activate()
                    print("[HOTKEY] Fenetre Jarvis ramenee au premier plan.")
                    return
                except Exception:
                    pass
        except Exception:
            pass
        webbrowser.open(target_url)
        print("[HOTKEY] Fenetre Jarvis ouverte.")

    try:
        keyboard.add_hotkey("ctrl+shift+j", focus_or_open)
        print("[HOTKEY] Raccourci global Ctrl+Shift+J actif.")
        keyboard.wait()
    except Exception as e:
        print(f"[HOTKEY] Echec : {e}")


def start_mobile_http_server():
    """Serveur HTTP minimal pour servir l'interface mobile sur le port 8080."""
    import http.server
    mobile_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mobile")
    if not os.path.exists(mobile_dir):
        print("[MOBILE] Dossier mobile/ introuvable, serveur non demarre.")
        return
    class MobileHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=mobile_dir, **kwargs)
        def log_message(self, format, *args):
            pass  # Silencieux
    server = http.server.HTTPServer(("0.0.0.0", 8080), MobileHandler)
    print(f"[MOBILE] Serveur HTTP demarre sur http://{LAN_IP}:8080")
    server.serve_forever()


def start_frontend_static_server(port: int = 5173):
    """Sert le bundle frontend/dist/ pre-build sur le port 5173 (remplace Vite).
    Utilise par le mode app standalone (JARVIS_NO_BROWSER=1)."""
    import http.server
    dist_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "dist")
    if not os.path.exists(dist_dir):
        print(f"[FRONTEND-STATIC] Bundle introuvable a {dist_dir}. Lance d'abord : cd frontend && npm run build")
        return
    class StaticHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=dist_dir, **kwargs)
        def log_message(self, format, *args):
            pass
    # En conteneur (headless) on ecoute sur 0.0.0.0 pour etre joignable via le
    # port publie ; en mode desktop local on reste sur la loopback.
    host = "0.0.0.0" if HEADLESS else "127.0.0.1"
    try:
        server = http.server.HTTPServer((host, port), StaticHandler)
    except OSError as e:
        print(f"[FRONTEND-STATIC] Port {port} indisponible ({e}). Le frontend est peut-etre deja servi.")
        return
    print(f"[FRONTEND-STATIC] Bundle servi sur http://{host}:{port}")
    server.serve_forever()

def main():
    print()
    print("=" * 60)
    print("   J.A.R.V.I.S — Mode Console + Interface Web")
    print("=" * 60)
    print()
    print("  Backend   : actif (terminal)")
    print(f"  WebSocket : ws://localhost:8765  (LAN: ws://{LAN_IP}:8765)")
    print("  Frontend  : ouvrir http://localhost:5173")
    print(f"  Mobile    : ouvrir http://{LAN_IP}:8080 sur votre tel/tablette")
    print()
    print("  Commandes vocales actives.")
    print("  Dites 'Jarvis' pour activer la session.")
    print("=" * 60)
    print()

    # Mode app standalone : pas de Vite, pas de navigateur — sert le bundle build directement.
    # Le mode headless (Docker) l'implique toujours.
    no_browser = HEADLESS or os.getenv("JARVIS_NO_BROWSER", "0") == "1"

    frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")
    frontend_process = None
    if no_browser:
        print("[JARVIS] Mode app standalone : sert frontend/dist/ sur 5173, pas de Vite, pas de navigateur.")
        threading.Thread(target=start_frontend_static_server, args=(5173,), daemon=True).start()
        time.sleep(0.4)
    elif os.path.exists(frontend_dir):
        print("[JARVIS] Lancement automatique de l'interface Web (Vite)...")
        frontend_process = subprocess.Popen(["npm", "run", "dev"], cwd=frontend_dir, shell=True)
        time.sleep(2.5)  # Laisser le temps a Vite de demarrer
        try:
            webbrowser.open("http://localhost:5173")
        except Exception:
            pass

    # Lancer le serveur HTTP mobile dans un thread
    threading.Thread(target=start_mobile_http_server, daemon=True).start()

    # Raccourci global Ctrl+Shift+J pour ramener Jarvis au premier plan
    # (inutile et privilegie en conteneur : saute en mode headless).
    if not HEADLESS:
        threading.Thread(target=start_global_hotkey, daemon=True).start()

    # Lancer le backend IA dans un thread
    threading.Thread(target=start_ia, daemon=True).start()

    # Tourne indefiniment en arriere-plan : le navigateur peut etre ferme et reouvert
    # sans que Jarvis ne s'eteigne. Arret manuel uniquement (Ctrl+C ou taskkill).
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n[JARVIS] Arret du systeme demande manuellement.")
        
    if frontend_process:
        print("[JARVIS] Arret du serveur Web...")
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(frontend_process.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

if __name__ == "__main__":
    main()
