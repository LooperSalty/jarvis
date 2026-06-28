# -*- mode: python ; coding: utf-8 -*-
# JarvisWeb.spec — Jarvis backend + ouverture du navigateur sur l'interface web.
# Pas de GUI desktop (pas de Qt/WebEngine) -> .exe beaucoup plus leger que Jarvis.exe.
#
# Build : python -m PyInstaller JarvisWeb.spec --clean --noconfirm

from PyInstaller.utils.hooks import collect_submodules
import importlib.util
import os

ROOT = os.path.abspath(os.path.dirname(__name__) or '.')

# Garde-fou : refuse de builder si les deps critiques manquent dans CE Python.
# Sans ca, PyInstaller "reussit" quand meme et produit un .exe qui crashe au
# lancement (ModuleNotFoundError sur les imports top-level de main2).
_CRITIQUES = ('websockets', 'edge_tts', 'pygame', 'google.genai', 'openai', 'dotenv')
_manquants = [m for m in _CRITIQUES if importlib.util.find_spec(m) is None]
if _manquants:
    raise SystemExit(
        f"[JarvisWeb.spec] Deps manquantes dans cet environnement : {_manquants}. "
        "Lance d'abord : python -m pip install -r requirements.txt"
    )

datas = [
    ('frontend/dist', 'frontend/dist'),
    ('mobile', 'mobile'),
]
# Skills auto-decouverts (charges via importlib depuis jarvis_skills/)
if os.path.isdir(os.path.join(ROOT, 'jarvis_skills')):
    datas.append(('jarvis_skills', 'jarvis_skills'))
# NB : aucune donnee perso ni secret bundle (.env, credentials.json,
# jarvis_memoire.json, ...) — extractibles du binaire et figes au build.
# Tout est lu/ecrit a cote de l'exe au runtime (cf. _dossier_donnees).

ICON_PATH = os.path.join(ROOT, 'assets', 'jarvis.ico')
ICON = ICON_PATH if os.path.exists(ICON_PATH) else None
VERSION_FILE = os.path.join(ROOT, 'version_info.txt')
VERSION = VERSION_FILE if os.path.exists(VERSION_FILE) else None

# Icone de l'app (chargee au runtime pour le tray/fenetres si besoin)
if os.path.isdir(os.path.join(ROOT, 'assets')):
    datas.append(('assets', 'assets'))

hiddenimports = [
    'jarvis_profile',
    'jarvis_dashboard_api',
    'websockets',
    'websockets.legacy',
    'websockets.legacy.server',
    'websockets.legacy.client',
    'edge_tts',
    'google.genai',
    'google.generativeai',
    'pygame',
    'pygame.mixer',
    'speech_recognition',
    'pyaudio',
    'pyautogui',
    'pygetwindow',
    'keyboard',
    'win32api', 'win32con', 'win32gui', 'win32com',
    'pythoncom', 'pywintypes',
    'PIL', 'PIL.Image',
    'numpy',
]
hiddenimports += collect_submodules('google.genai')
hiddenimports += collect_submodules('jarvis_actions')
hiddenimports += collect_submodules('meross_iot')
hiddenimports += collect_submodules('playwright')

# OpenJarvis SDK (cerveau optionnel via USE_OPENJARVIS=1).
# Imports lazy dans openjarvis_brain.py donc PyInstaller ne les detecte pas seul.
try:
    hiddenimports += collect_submodules('openjarvis')
except Exception:
    pass  # OpenJarvis non installe au moment du build : skip silencieux

# Voix locale opt-in (requirements-voice.txt) : faster-whisper + openwakeword.
# Imports lazy + data files indispensables (assets ONNX, modeles openwakeword).
# Installer requirements-voice.txt AVANT le build pour les embarquer.
from PyInstaller.utils.hooks import collect_data_files
for _pkg_voix in ('faster_whisper', 'openwakeword'):
    try:
        hiddenimports += collect_submodules(_pkg_voix)
        datas += collect_data_files(_pkg_voix)
    except Exception:
        # Visible dans les logs de build (CI incluse) : sans ce warning, le
        # binaire sort sans voix locale et personne ne le sait.
        print(f"[JarvisWeb.spec] ATTENTION : {_pkg_voix} non installe — voix locale "
              "(JARVIS_STT_LOCAL/JARVIS_WAKE_LOCAL) NON embarquee dans le .exe")

# Operator : fpdf2 (devis PDF) en import lazy dans devis_pdf.py — hiddenimport
# explicite sinon PyInstaller peut le rater (devis sans PDF dans le .exe).
try:
    hiddenimports += collect_submodules('fpdf')
except Exception:
    print("[JarvisWeb.spec] ATTENTION : fpdf2 non installe — devis PDF (Operator) "
          "NON embarques dans le .exe")

# Pas de Qt ni de pywebview pour cette version legere — juste le backend
excludes = [
    'tkinter',
    'panda3d', 'ursina',
    'matplotlib', 'pandas', 'scipy', 'IPython',
    'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
    'PyQt5.QtWebEngineWidgets', 'PyQt5.QtWebEngineCore',
    'jupyter', 'notebook',
    'webview', 'pystray',
    # Config Home Assistant PERSO (gitignoree) : jamais dans le binaire.
    # Chargee a cote de l'exe au runtime (sys.path), repli sur l'exemple.
    'jarvis_home_config',
]

block_cipher = None

a = Analysis(
    ['jarvis_core/jarvis_web.py'],
    # jarvis_core/ ajoute au pathex : modules core importes A PLAT depuis jarvis_core/.
    pathex=[ROOT, os.path.join(ROOT, 'jarvis_core')],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Build ONEDIR (cf. Jarvis.spec pour le detail) : evite l'auto-extraction
# runtime qui declenche les faux positifs antivirus. contents_directory distinct
# ('_internal_web') pour que JarvisWeb.exe cohabite avec Jarvis.exe dans le meme
# dossier {app} (partage de .env / memoire / profil) sans collision de payload.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # onedir : les binaires vont dans COLLECT, pas dans l'exe
    name='JarvisWeb',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,             # UPX amplifie les faux positifs antivirus : laisser OFF
    console=False,         # mode windowed : pas de fenetre console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,             # assets/jarvis.ico
    version=VERSION,       # version_info.txt (metadonnees Windows)
    contents_directory='_internal_web',  # distinct de Jarvis pour cohabiter dans {app}
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='JarvisWeb',      # sortie : dist/JarvisWeb/JarvisWeb.exe + dist/JarvisWeb/_internal_web/
)
