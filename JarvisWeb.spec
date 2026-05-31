# -*- mode: python ; coding: utf-8 -*-
# JarvisWeb.spec — Jarvis backend + ouverture du navigateur sur l'interface web.
# Pas de GUI desktop (pas de Qt/WebEngine) -> .exe beaucoup plus leger que Jarvis.exe.
#
# Build : python -m PyInstaller JarvisWeb.spec --clean --noconfirm

from PyInstaller.utils.hooks import collect_submodules
import os

ROOT = os.path.abspath(os.path.dirname(__name__) or '.')

datas = [
    ('frontend/dist', 'frontend/dist'),
    ('mobile', 'mobile'),
]
for opt in ('jarvis_memoire.json', '.env', 'credentials.json'):
    p = os.path.join(ROOT, opt)
    if os.path.exists(p):
        datas.append((opt, '.'))

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

# Pas de Qt ni de pywebview pour cette version legere — juste le backend
excludes = [
    'tkinter',
    'panda3d', 'ursina',
    'matplotlib', 'pandas', 'scipy', 'IPython',
    'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
    'PyQt5.QtWebEngineWidgets', 'PyQt5.QtWebEngineCore',
    'jupyter', 'notebook',
    'webview', 'pystray',
]

block_cipher = None

a = Analysis(
    ['jarvis_web.py'],
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
    name='JarvisWeb',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,         # mode windowed : pas de fenetre console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
