# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec pour packager Jarvis en .exe standalone.
# Build : python -m PyInstaller Jarvis.spec --clean --noconfirm

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
import importlib.util
import os

ROOT = os.path.abspath(os.path.dirname(__name__) or '.')

# Garde-fou : refuse de builder si les deps critiques manquent dans CE Python.
# Sans ca, PyInstaller "reussit" quand meme et produit un .exe qui crashe au
# lancement (ModuleNotFoundError sur les imports top-level de main2/desktop).
_CRITIQUES = ('websockets', 'edge_tts', 'pygame', 'PyQt5', 'google.genai', 'openai', 'dotenv')
_manquants = [m for m in _CRITIQUES if importlib.util.find_spec(m) is None]
if _manquants:
    raise SystemExit(
        f"[Jarvis.spec] Deps manquantes dans cet environnement : {_manquants}. "
        "Lance d'abord : python -m pip install -r requirements.txt"
    )

# Tous les fichiers a embarquer dans le .exe
datas = [
    ('frontend/dist', 'frontend/dist'),
    ('mobile', 'mobile'),
]

# Skills auto-decouverts (charges via importlib depuis jarvis_skills/)
if os.path.isdir(os.path.join(ROOT, 'jarvis_skills')):
    datas.append(('jarvis_skills', 'jarvis_skills'))

# Icone de l'app (fenetres Qt + tray, charges au runtime depuis assets/)
if os.path.isdir(os.path.join(ROOT, 'assets')):
    datas.append(('assets', 'assets'))

ICON_PATH = os.path.join(ROOT, 'assets', 'jarvis.ico')
ICON = ICON_PATH if os.path.exists(ICON_PATH) else None
VERSION_FILE = os.path.join(ROOT, 'version_info.txt')
VERSION = VERSION_FILE if os.path.exists(VERSION_FILE) else None

# NB : on ne bundle AUCUNE donnee perso ni secret (.env, credentials.json,
# token.pickle, jarvis_memoire.json, jarvis_profile.json, jarvis_mcp.json) —
# ils seraient extractibles du binaire et figes a la date du build. Tous ces
# fichiers sont lus/ecrits a cote de l'exe au runtime (cf. _dossier_donnees
# dans jarvis_profile / jarvis_security / main2 / jarvis_dashboard_api).

# Qt + WebEngine ressources runtime (DLLs, locales, QtWebEngineProcess.exe, etc.)
datas += collect_data_files('PyQt5', subdir='Qt5/resources')
datas += collect_data_files('PyQt5', subdir='Qt5/translations')

# Modules dynamiquement importes que PyInstaller ne detecte pas tout seul
hiddenimports = [
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
    'win32api',
    'win32con',
    'win32gui',
    'win32com',
    'pythoncom',
    'pywintypes',
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'numpy',
    # Qt5
    'PyQt5',
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtWidgets',
    'PyQt5.QtWebEngineWidgets',
    'PyQt5.QtWebEngineCore',
    'PyQt5.QtNetwork',
    'PyQt5.QtPrintSupport',
    'PyQt5.sip',
]
hiddenimports += [
    # Modules racine de l'app de configuration (dashboard)
    'jarvis_profile',
    'jarvis_dashboard_api',
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
# Imports lazy dans voice_stt.py / wake_word.py + data files indispensables
# (assets ONNX Silero VAD, modeles openwakeword) sans lesquels les flags
# JARVIS_STT_LOCAL / JARVIS_WAKE_LOCAL retombent silencieusement sur le cloud.
# Installer requirements-voice.txt AVANT le build pour les embarquer.
for _pkg_voix in ('faster_whisper', 'openwakeword'):
    try:
        hiddenimports += collect_submodules(_pkg_voix)
        datas += collect_data_files(_pkg_voix)
    except Exception:
        # Visible dans les logs de build (CI incluse) : sans ce warning, le
        # binaire sort sans voix locale et personne ne le sait.
        print(f"[Jarvis.spec] ATTENTION : {_pkg_voix} non installe — voix locale "
              "(JARVIS_STT_LOCAL/JARVIS_WAKE_LOCAL) NON embarquee dans le .exe")

# Modules lourds qui ne servent pas a la version desktop — on les exclut pour reduire la taille
# NB : pas d'exclusion de 'unittest' (pyparsing/httplib2 en dependent transitivement)
# NB : on a vire pywebview et pystray, remplaces par PyQt5
excludes = [
    'tkinter',
    'panda3d', 'ursina',  # 3D engines qu'on n'utilise pas en desktop
    'matplotlib', 'pandas', 'scipy', 'IPython',
    'PyQt6', 'PySide2', 'PySide6',
    'jupyter', 'notebook',
    'webview', 'pystray',  # remplaces par PyQt5
    # Config Home Assistant PERSO (gitignoree) : ne jamais la geler dans le
    # binaire (donnees perso extractibles). Au runtime, main2 ajoute le dossier
    # de l'exe a sys.path : un jarvis_home_config.py pose a cote de l'exe est
    # charge en priorite, sinon repli sur l'exemple generique embarque.
    'jarvis_home_config',
]

block_cipher = None

a = Analysis(
    ['jarvis_core/jarvis_desktop.py'],
    # jarvis_core/ ajoute au pathex : les modules core sont importes A PLAT
    # (import jarvis_config, jarvis_dashboard_api...) depuis jarvis_core/.
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

# Build ONEDIR (et non onefile) : en onefile, le bootloader decompresse tout le
# bundle dans un dossier temporaire (sys._MEIPASS) AU LANCEMENT puis l'execute —
# comportement de "dropper/packer" que Defender/SmartScreen flaguent en faux
# positif (Trojan:Win32/Wacatac.B!ml). En onedir rien ne se decompresse au
# runtime : le heuristique principal disparait, et c'est aussi plus rapide a
# demarrer. La distribution finale passe par l'installateur (JarvisSetup.exe),
# donc le dossier _internal/ reste invisible pour l'utilisateur.
#
# CONTRAINTE PARTAGE DE DONNEES : Jarvis.exe et JarvisWeb.exe doivent rester
# DANS LE MEME DOSSIER pour partager .env / memoire / profil (tous les
# _dossier_donnees() resolvent Path(sys.executable).parent). On garde donc les
# deux exes a la racine de {app} et on isole leurs payloads dans des dossiers de
# contenu DISTINCTS via contents_directory ('_internal' ici, '_internal_web'
# pour JarvisWeb) : aucune collision, aucun changement cote code Python.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # onedir : les binaires vont dans COLLECT, pas dans l'exe
    name='Jarvis',
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
    contents_directory='_internal',  # distinct de JarvisWeb pour cohabiter dans {app}
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,             # idem : ne jamais activer UPX (faux positifs)
    upx_exclude=[],
    name='Jarvis',         # sortie : dist/Jarvis/Jarvis.exe + dist/Jarvis/_internal/
)
