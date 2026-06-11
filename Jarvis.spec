# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec pour packager Jarvis en .exe standalone.
# Build : python -m PyInstaller Jarvis.spec --clean --noconfirm

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
import os

ROOT = os.path.abspath(os.path.dirname(__name__) or '.')

# Tous les fichiers a embarquer dans le .exe
datas = [
    ('frontend/dist', 'frontend/dist'),
    ('mobile', 'mobile'),
]

# Skills auto-decouverts (charges via importlib depuis jarvis_skills/)
if os.path.isdir(os.path.join(ROOT, 'jarvis_skills')):
    datas.append(('jarvis_skills', 'jarvis_skills'))

# Inclure assets optionnels seulement s'ils existent.
# NB : on ne bundle PAS jarvis_profile.json / jarvis_mcp.json (donnees perso :
# famille, adresse, env locaux) — ils seraient extractibles du binaire. Ces
# fichiers sont lus/ecrits a cote de l'exe au runtime (cf. _dossier_donnees).
for opt in ('jarvis_memoire.json', '.env', 'credentials.json'):
    p = os.path.join(ROOT, opt)
    if os.path.exists(p):
        datas.append((opt, '.'))

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
]

block_cipher = None

a = Analysis(
    ['jarvis_desktop.py'],
    pathex=[ROOT],
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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Jarvis',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,             # UPX peut casser pywebview / bibliotheques natives
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,         # mode windowed : pas de fenetre console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,             # Mettre le chemin d'un .ico ici si tu en as un
)
