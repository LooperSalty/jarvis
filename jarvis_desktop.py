"""Jarvis en mode app desktop standalone — sans navigateur, en arriere-plan.

Utilise PyQt5 + QtWebEngine pour beneficier de la VRAIE transparence native
(WA_TranslucentBackground + page().setBackgroundColor(Qt.transparent)).
Edge WebView2 ne supporte pas la transparence sous Windows a cause de
DirectComposition, c'est pourquoi on a besoin de Qt ici.

Comportement :
- Au demarrage : aucune fenetre visible, juste icone dans le system tray
- Quand Jarvis devient actif (thinking/speaking) : la mini-fenetre orbe
  apparait par-dessus toutes les apps, centree au-dessus de la barre des
  taches, avec fond TOTALEMENT transparent (orbe flottante facon Siri)
- Quand Jarvis revient idle : la mini-fenetre disparait apres 3s
- Click droit tray : menu (Ouvrir interface, Cacher, Quitter)
- Click gauche tray : ouvre l'interface complete

Modes :
- Dev (.py)  : lance main2.py en sous-process
- Frozen .exe : importe main2 et le lance en thread du meme process
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import random
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

from PyQt5.QtCore import Qt, QUrl, pyqtSignal, QObject, QTimer, QPointF, QRect
from PyQt5.QtGui import QColor, QIcon, QPixmap, QPainter, QImage, QRegion
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWidgets import (
    QAction, QApplication, QMenu, QSystemTrayIcon, QWidget, QVBoxLayout,
)
import win32api
import win32con
import win32gui

# ============================================================
# Constantes
# ============================================================

ORB_TITLE = "Jarvis"
ORB_W = 280
ORB_H = 280
TASKBAR_MARGIN = 6
HIDE_DELAY_MS = 3000

FULL_W = 980
FULL_H = 720

# Configurateur (dashboard) — fenetre native dediee, plus large (formulaires).
DASH_W = 1180
DASH_H = 800

JARVIS_URL_MINI = "http://127.0.0.1:5173/?mini=1"
JARVIS_URL_FULL = "http://127.0.0.1:5173/"
JARVIS_URL_DASHBOARD = "http://127.0.0.1:5173/dashboard.html"
WS_URL = "ws://127.0.0.1:8765"

FROZEN = getattr(sys, "frozen", False)
ROOT = Path(getattr(sys, "_MEIPASS", str(Path(__file__).parent.resolve())))
BACKEND_CMD = [sys.executable, "-u", str(ROOT / "main2.py")]

LOG_PATH = Path(tempfile.gettempdir()) / "jarvis_desktop.log"
ICON_PATH = ROOT / "assets" / "jarvis.ico"


def _log(msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    print(line, end="", flush=True)


# ============================================================
# Backend (main2.py) — thread (frozen) ou subprocess (dev)
# ============================================================

def _start_backend_inprocess():
    os.chdir(str(ROOT))
    sys.path.insert(0, str(ROOT))
    os.environ["JARVIS_NO_BROWSER"] = "1"
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    import main2
    threading.Thread(target=main2.main, daemon=True).start()


def _start_backend_subprocess():
    dist_dir = ROOT / "frontend" / "dist"
    if not dist_dir.exists():
        _log("Bundle frontend/dist absent — build...")
        subprocess.run(
            ["npx", "vite", "build"],
            cwd=str(ROOT / "frontend"),
            check=True, shell=True,
        )
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["JARVIS_NO_BROWSER"] = "1"
    return subprocess.Popen(BACKEND_CMD, cwd=str(ROOT), env=env)


def _wait_for_frontend(host: str = "127.0.0.1", port: int = 5173, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.4)
    return False


# ============================================================
# Win32 helpers (positionnement + style WS_EX_TOOLWINDOW)
# ============================================================

def _get_work_area() -> tuple[int, int, int, int]:
    monitor = win32api.MonitorFromPoint((0, 0))
    rect = win32api.GetMonitorInfo(monitor)["Work"]
    x, y, r, b = rect
    return x, y, r - x, b - y


def _apply_toolwindow_style(hwnd: int):
    """WS_EX_TOOLWINDOW : la fenetre n'apparait pas dans Alt+Tab ni la barre
    des taches. WS_EX_NOACTIVATE : ne vole pas le focus."""
    if not hwnd:
        return
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    win32gui.SetWindowLong(
        hwnd, win32con.GWL_EXSTYLE,
        style | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE,
    )


# ============================================================
# Bridge WS thread → Qt main thread
# ============================================================

class WindowBridge(QObject):
    """Traduit les evenements WS (autre thread) en signaux Qt qui peuvent
    safely manipuler la fenetre depuis le thread principal."""
    # show_orb passe maintenant l'etat ('thinking'|'speaking') pour adapter la couleur
    show_orb_signal = pyqtSignal(str)
    show_full_signal = pyqtSignal()
    show_dashboard_signal = pyqtSignal()
    schedule_hide_signal = pyqtSignal()
    quit_signal = pyqtSignal()
    # Notification tray (titre, corps) — emise depuis n'importe quel thread,
    # affichee sur le thread Qt (showMessage n'est pas thread-safe).
    notify_signal = pyqtSignal(str, str)


# ============================================================
# Fenetre Orbe (transparente, frameless, on top)
# ============================================================

class OrbWebView(QWebEngineView):
    """QWebEngineView qui charge le vrai orbe Three.js (matche l'UI web).
    Mask circulaire pour donner l'illusion d'un disque flottant.
    L'etat (idle/listening/thinking/speaking + couleurs + animations) est
    gere automatiquement par la page elle-meme via sa connexion WS au backend."""

    def __init__(self, parent=None, size: int = ORB_W):
        super().__init__(parent)
        self._size = size
        self.resize(size, size)
        self.setMinimumSize(size, size)
        # Page noire au demarrage (pas blanche) pour eviter le flash
        self.page().setBackgroundColor(QColor(4, 6, 12))
        self.setUrl(QUrl(JARVIS_URL_MINI))
        self._apply_circular_mask()

    def _apply_circular_mask(self):
        """Mask en disque circulaire : les coins du rectangle deviennent
        invisibles, on voit un disque parfait avec l'orbe Three.js dedans."""
        region = QRegion(0, 0, self._size, self._size, QRegion.Ellipse)
        self.setMask(region)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._size = self.width()
        self._apply_circular_mask()


def _make_particle_sprite(color: tuple[int, int, int], diameter: int = 16) -> QPixmap:
    """Pre-rendu d'une particule "soft" : gradient gaussien centre + glow.
    Reproduit makeStarTexture de orb.ts. Plus dense (core 8.0 au lieu de 5.0)
    pour un rendu vif au lieu de delave."""
    r0, g0, b0 = color
    img = QImage(diameter, diameter, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    cx = cy = diameter / 2.0
    for y in range(diameter):
        for x in range(diameter):
            dx = (x - cx) / cx
            dy = (y - cy) / cy
            r2 = dx * dx + dy * dy
            if r2 > 1.0:
                continue
            core = math.exp(-r2 * 8.0)         # core plus serre (etait 5.0)
            glow = math.exp(-r2 * 1.6) * 0.55  # halo plus marque (etait 0.35)
            v = min(1.0, core + glow)
            a = int(v * 255)
            # Premultiplied : R*a/255, G*a/255, B*a/255, a
            r_chan = (r0 * a) // 255
            g_chan = (g0 * a) // 255
            b_chan = (b0 * a) // 255
            pix = (a << 24) | (r_chan << 16) | (g_chan << 8) | b_chan
            img.setPixel(x, y, pix)
    return QPixmap.fromImage(img)


# Harmoniques Lissajous (matche orb.ts ligne 204)
_HARMONICS = [(1, 1), (2, 3), (3, 2), (3, 4), (5, 4), (3, 5), (1, 2), (2, 5), (4, 5)]

# Couleurs par etat (matche STATE_COLOR de orb.ts)
_STATE_COLORS = {
    "idle":      (170, 220, 255),    # bleu clair
    "listening": (155, 230, 255),    # cyan
    "thinking":  (210, 170, 255),    # violet
    "speaking":  (160, 255, 220),    # mint vert-bleu
}


class OrbCanvas(QWidget):
    """Mini-orbe rendue en QPainter natif (pas de WebEngine).
    Particules sur courbes de Lissajous, sprite gaussien pre-calcule par etat.
    Transparence garantie. Couleur+vitesse adaptees a l'etat (thinking/speaking)."""

    # Vitesse de rotation par etat
    _SPEED = {"idle": 0.003, "listening": 0.004, "thinking": 0.008, "speaking": 0.012}

    def __init__(self, parent=None, size: int = ORB_W):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setMinimumSize(size, size)
        self.resize(size, size)
        self._size = size
        self._paint_count = 0
        self._state = "idle"

        # Cache des sprites par etat (regene une fois par etat utilise)
        self._sprite_cache: dict[str, QPixmap] = {}
        self._sprite = self._sprite_for("idle")
        self._sprite_radius = self._sprite.width() / 2.0

        # Orbites : 28 x 80 = 2240 particules. Rayon reduit (0.32) pour ne plus
        # toucher les bords de la fenetre 280x280.
        random.seed(7)
        n_orbits = 28
        n_points = 80
        max_r = size * 0.32
        self._particles: list[tuple[float, float, float]] = []
        for _ in range(n_orbits):
            n1, n2 = random.choice(_HARMONICS)
            phase_offset = random.uniform(0, 2 * math.pi)
            radius = random.uniform(max_r * 0.5, max_r)
            angle = random.uniform(0, 2 * math.pi)
            ux, uy = math.cos(angle), math.sin(angle)
            vx, vy = -uy, ux
            for p in range(n_points):
                t = (p / n_points) * 2 * math.pi
                cx_p = math.cos(n1 * t + phase_offset)
                sy_p = math.sin(n2 * t + phase_offset * 0.7)
                px = (ux * cx_p + vx * sy_p) * radius
                py = (uy * cx_p + vy * sy_p) * radius
                px += random.uniform(-1.5, 1.5)
                py += random.uniform(-1.5, 1.5)
                brightness = random.uniform(0.85, 1.0)  # range resserre = couleurs vives
                self._particles.append((px, py, brightness))

        self._rotation = 0.0
        self._pulse_t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)  # ~60 fps

    def _sprite_for(self, state: str) -> QPixmap:
        if state not in self._sprite_cache:
            color = _STATE_COLORS.get(state, _STATE_COLORS["idle"])
            self._sprite_cache[state] = _make_particle_sprite(color, 16)
        return self._sprite_cache[state]

    def set_state(self, state: str):
        if state == self._state:
            return
        self._state = state
        self._sprite = self._sprite_for(state)
        self._sprite_radius = self._sprite.width() / 2.0

    def _tick(self):
        self._rotation += self._SPEED.get(self._state, 0.004)
        self._pulse_t += 0.06
        self.update()

    def paintEvent(self, _):
        self._paint_count += 1
        if self._paint_count <= 2:
            _log(f"OrbCanvas paintEvent #{self._paint_count} size={self.size().width()}x{self.size().height()} particules={len(self._particles)}")
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        cx = self._size / 2
        cy = self._size / 2
        sr = self._sprite_radius
        cos_r = math.cos(self._rotation)
        sin_r = math.sin(self._rotation)
        # Pulse subtil : echelle 1.0 +/- 4% au rythme du state
        scale = 1.0 + 0.04 * math.sin(self._pulse_t)
        for (px, py, brightness) in self._particles:
            rx = (px * cos_r - py * sin_r) * scale
            ry = (px * sin_r + py * cos_r) * scale
            x = cx + rx - sr
            y = cy + ry - sr
            p.setOpacity(brightness)
            p.drawPixmap(QPointF(x, y), self._sprite)
        # Lens flare central — couleur basee sur l'etat
        p.setOpacity(1.0)
        p.setPen(Qt.NoPen)
        cr, cg, cb = _STATE_COLORS.get(self._state, _STATE_COLORS["idle"])
        p.setBrush(QColor(cr, cg, cb, 60))
        p.drawEllipse(QPointF(cx, cy), 16, 16)
        p.setBrush(QColor(min(cr + 30, 255), min(cg + 20, 255), min(cb + 10, 255), 150))
        p.drawEllipse(QPointF(cx, cy), 7, 7)
        p.setBrush(QColor(255, 255, 255, 240))
        p.drawEllipse(QPointF(cx, cy), 3, 3)
        p.end()


class OrbWindow(QWidget):
    """Mini-fenetre flottante au-dessus de la barre des taches.
    Transparente, frameless, on-top, Tool (pas dans Alt+Tab)."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(ORB_TITLE)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # Vraie orbe Three.js dans un QWebEngineView avec mask circulaire :
        # qualite parfaite, couleurs+animations par etat geres par la page
        # via sa propre connexion WS au backend.
        self.canvas = OrbWebView(self, ORB_W)
        layout.addWidget(self.canvas)

        self.resize(ORB_W, ORB_H)
        # Mask circulaire applique aussi au niveau de la fenetre pour qu'aucun
        # pixel de bordure ne s'echappe.
        self.setMask(QRegion(0, 0, ORB_W, ORB_H, QRegion.Ellipse))

    def _hwnd(self) -> int:
        return int(self.winId())

    def center_above_taskbar(self):
        wx, wy, ww, wh = _get_work_area()
        x = wx + (ww - ORB_W) // 2
        y = wy + wh - ORB_H - TASKBAR_MARGIN
        self.move(x, y)

    def show_floating(self):
        self.center_above_taskbar()
        self.show()
        _apply_toolwindow_style(self._hwnd())


class FullWindow(QWidget):
    """Fenetre complete avec QWebEngineView (chat + historique)."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Jarvis — Interface")
        self.resize(FULL_W, FULL_H)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = QWebEngineView(self)
        self.view.setUrl(QUrl(JARVIS_URL_FULL))
        layout.addWidget(self.view)

    def show_centered(self):
        wx, wy, ww, wh = _get_work_area()
        x = wx + (ww - FULL_W) // 2
        y = wy + (wh - FULL_H) // 2
        self.move(x, y)
        self.show()
        self.activateWindow()
        self.raise_()


class DashboardWindow(QWidget):
    """Fenetre native du configurateur (dashboard de configuration).
    Charge la page Vite dashboard.html dans un QWebEngineView — vraie fenetre
    Windows, pas un onglet de navigateur."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Jarvis — Configuration")
        self.resize(DASH_W, DASH_H)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = QWebEngineView(self)
        self.view.setUrl(QUrl(JARVIS_URL_DASHBOARD))
        layout.addWidget(self.view)

    def show_centered(self):
        wx, wy, ww, wh = _get_work_area()
        x = wx + (ww - DASH_W) // 2
        y = wy + (wh - DASH_H) // 2
        self.move(x, y)
        self.show()
        self.activateWindow()
        self.raise_()


class WindowController(QObject):
    """Coordonne OrbWindow + FullWindow selon les signaux du bridge."""

    def __init__(self, bridge: WindowBridge):
        super().__init__()
        self.bridge = bridge
        self._mode = "hidden"  # hidden | orb | full
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._do_hide)

        self.orb_window = OrbWindow()
        self.full_window: FullWindow | None = None  # cree a la demande
        self.dashboard_window: DashboardWindow | None = None  # cree a la demande

        bridge.show_orb_signal.connect(self._show_orb)
        bridge.show_full_signal.connect(self._show_full)
        bridge.show_dashboard_signal.connect(self._show_dashboard)
        bridge.schedule_hide_signal.connect(self._schedule_hide)
        bridge.quit_signal.connect(self._quit)

    def _show_orb(self, state: str = "thinking"):
        self._hide_timer.stop()
        # L'etat est applique automatiquement par la page Three.js elle-meme
        # via sa connexion WS au backend (pas besoin de le pousser via Qt).
        self.orb_window.show_floating()
        self._mode = "orb"
        _log(f"show_orb (mode=orb, state={state})")

    def _show_full(self):
        self._hide_timer.stop()
        self.orb_window.hide()
        if self.full_window is None:
            self.full_window = FullWindow()
        self.full_window.show_centered()
        self._mode = "full"
        _log("show_full (mode=full)")

    def _show_dashboard(self):
        # Configurateur dans une vraie fenetre native (pas le navigateur).
        self._hide_timer.stop()
        self.orb_window.hide()
        if self.dashboard_window is None:
            self.dashboard_window = DashboardWindow()
        self.dashboard_window.show_centered()
        self._mode = "full"  # comme full : pas d'auto-hide de l'orbe
        _log("show_dashboard (fenetre native)")

    def _schedule_hide(self):
        if self._mode == "full":
            return
        self._hide_timer.start(HIDE_DELAY_MS)

    def _do_hide(self):
        self.orb_window.hide()
        self._mode = "hidden"
        _log("hide() applique")

    def _quit(self):
        try:
            self.orb_window.close()
        except Exception:
            pass
        if self.full_window:
            try:
                self.full_window.close()
            except Exception:
                pass
        if self.dashboard_window:
            try:
                self.dashboard_window.close()
            except Exception:
                pass
        QApplication.quit()


# ============================================================
# Client WebSocket (thread asyncio dedie)
# ============================================================

async def _ws_listener(bridge: WindowBridge, stop_event: asyncio.Event):
    import websockets
    backoff = 1.0
    while not stop_event.is_set():
        try:
            async with websockets.connect(WS_URL, ping_interval=20) as ws:
                _log("WS connecte au backend.")
                backoff = 1.0
                async for raw in ws:
                    if stop_event.is_set():
                        break
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue
                    if msg.get("action") != "set_state":
                        continue
                    state = msg.get("state", "idle")
                    # idle + listening = repos. show uniquement sur thinking/speaking.
                    if state in ("thinking", "speaking"):
                        _log(f"WS set_state={state} -> show")
                        bridge.show_orb_signal.emit(state)
                    else:
                        _log(f"WS set_state={state} -> hide")
                        bridge.schedule_hide_signal.emit()
        except Exception as e:
            _log(f"WS deco ({e}), retry dans {backoff}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.6, 10.0)


def _start_ws_thread(bridge: WindowBridge) -> threading.Event:
    stop_event = threading.Event()
    async_stop = asyncio.Event()

    def runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_ws_listener(bridge, async_stop))
        finally:
            loop.close()

    def watcher():
        stop_event.wait()
        async_stop.set()

    threading.Thread(target=runner, daemon=True).start()
    threading.Thread(target=watcher, daemon=True).start()
    return stop_event


# ============================================================
# System tray (QSystemTrayIcon)
# ============================================================

def _app_icon() -> QIcon:
    """Icone de l'app (assets/jarvis.ico), repli sur l'icone dessinee."""
    try:
        if ICON_PATH.exists():
            ic = QIcon(str(ICON_PATH))
            if not ic.isNull():
                return ic
    except Exception:
        pass
    return _make_tray_icon()


def _make_tray_icon() -> QIcon:
    """Petite icone bleue ronde (repli si assets/jarvis.ico absent)."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(76, 168, 232))
    p.setPen(Qt.NoPen)
    p.drawEllipse(6, 6, 52, 52)
    p.setBrush(QColor(255, 255, 255, 230))
    p.drawEllipse(22, 22, 20, 20)
    p.end()
    return QIcon(pix)


def _verifier_maj(bridge: WindowBridge):
    """Verifie en arriere-plan si une release plus recente existe sur GitHub.

    Resultat notifie via le tray (signal -> thread Qt). Si une mise a jour est
    disponible, ouvre la page de la release dans le navigateur.
    """
    def worker():
        try:
            import jarvis_version
            info = jarvis_version.check_update()
        except Exception as e:
            bridge.notify_signal.emit("Jarvis", f"Verification impossible : {e}")
            return
        if info.get("disponible"):
            version = info.get("version_distante") or "?"
            bridge.notify_signal.emit(
                "Jarvis", f"Mise a jour {version} disponible — ouverture de la page."
            )
            if info.get("url"):
                webbrowser.open(info["url"])
        elif info.get("erreur"):
            bridge.notify_signal.emit("Jarvis", f"Verification impossible : {info['erreur']}")
        else:
            bridge.notify_signal.emit("Jarvis", f"Jarvis {info.get('version_locale')} est a jour.")

    threading.Thread(target=worker, daemon=True).start()


def _setup_tray(app: QApplication, bridge: WindowBridge) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(_app_icon(), parent=app)
    tray.setToolTip("Jarvis")

    menu = QMenu()
    open_act = QAction("Ouvrir l'interface", menu)
    config_act = QAction("Configuration", menu)
    update_act = QAction("Verifier les mises a jour", menu)
    hide_act = QAction("Cacher", menu)
    quit_act = QAction("Quitter", menu)

    open_act.triggered.connect(bridge.show_full_signal.emit)
    # Configurateur : fenetre native dediee (plus de navigateur systeme).
    config_act.triggered.connect(bridge.show_dashboard_signal.emit)
    update_act.triggered.connect(lambda: _verifier_maj(bridge))
    hide_act.triggered.connect(bridge.schedule_hide_signal.emit)
    quit_act.triggered.connect(bridge.quit_signal.emit)

    menu.addAction(open_act)
    menu.addAction(config_act)
    menu.addAction(update_act)
    menu.addAction(hide_act)
    menu.addSeparator()
    menu.addAction(quit_act)
    tray.setContextMenu(menu)

    # Notifications venant d'autres threads (ex. verification de mise a jour).
    bridge.notify_signal.connect(
        lambda titre, corps: tray.showMessage(titre, corps, QSystemTrayIcon.Information, 8000)
    )

    # Click gauche -> ouvrir interface
    def on_activated(reason):
        if reason == QSystemTrayIcon.Trigger:
            bridge.show_full_signal.emit()
    tray.activated.connect(on_activated)

    tray.show()
    return tray


# ============================================================
# Main
# ============================================================

def main():
    _log(f"Demarrage (frozen={FROZEN}, root={ROOT})")

    # 1) Backend
    backend_proc = None
    if FROZEN:
        _start_backend_inprocess()
    else:
        backend_proc = _start_backend_subprocess()

    if not _wait_for_frontend():
        _log("Frontend non pret. Sortie.")
        if backend_proc:
            backend_proc.terminate()
        return

    # AppUserModelID : sans ca, Windows regroupe l'app sous python.exe et n'utilise
    # pas notre icone dans la barre des taches. A faire avant toute fenetre.
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LooperSalty.Jarvis")
    except Exception:
        pass

    # 2) Qt application
    # Empêche Qt de quitter quand la dernière fenêtre se ferme (tray reste actif)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv if not FROZEN else [])
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(_app_icon())  # icone barre des taches + toutes les fenetres

    bridge = WindowBridge()

    # 3) Controleur de fenetres (orbe + full a la demande)
    # Reference attachee a l'app pour empecher le garbage collector de la free.
    app._controller = WindowController(bridge)

    # Prechauffe la fenetre orbe : show puis hide immediat. Force Qt a creer
    # le handle natif Win32 + initialiser le compositor maintenant. Sans ca,
    # le 1er show real prend ~500ms-1s (creation lazy du handle).
    QTimer.singleShot(50, lambda: (
        app._controller.orb_window.show_floating(),
        QTimer.singleShot(50, app._controller.orb_window.hide),
    ))

    # 4) Tray
    tray = _setup_tray(app, bridge)

    # 5) WS listener
    ws_stop = _start_ws_thread(bridge)

    _log("Pret. Jarvis tourne en arriere-plan, icone dans le system tray.")

    # 6) Boucle Qt (bloque jusqu'a quit)
    try:
        exit_code = app.exec_()
    finally:
        _log("Fermeture...")
        ws_stop.set()
        try:
            tray.hide()
        except Exception:
            pass
        if backend_proc:
            try:
                backend_proc.terminate()
                backend_proc.wait(timeout=5)
            except Exception:
                try:
                    backend_proc.kill()
                except Exception:
                    pass
        else:
            os._exit(0)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
