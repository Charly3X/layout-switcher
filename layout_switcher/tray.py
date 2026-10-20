"""System tray icon: flashes on every automatic switch; menu for pausing and autostart."""

import logging
import signal
import sys
import threading

from PyQt6.QtCore import QObject, QRectF, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import autostart

log = logging.getLogger("layout_switcher")

FLASH_TOGGLES = 6
FLASH_INTERVAL_MS = 120

COLOR_ON = "#3daee9"
COLOR_FLASH = "#f67400"
COLOR_OFF = "#7f8c8d"


class DaemonEvents(QObject):
    """Carries daemon-thread events into the Qt thread."""

    switched = pyqtSignal()
    failed = pyqtSignal(str)


def _badge(color):
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
    font = QFont()
    font.setBold(True)
    font.setPixelSize(30)
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "Ая")
    painter.end()
    return QIcon(pixmap)


class Tray:
    def __init__(self, app, typist):
        self.typist = typist
        self.switches = 0
        self.error = None
        self.flashes_left = 0
        self.icons = {"on": _badge(COLOR_ON), "flash": _badge(COLOR_FLASH), "off": _badge(COLOR_OFF)}

        menu = QMenu()
        self.enabled_action = menu.addAction("Fix keyboard layout")
        self.enabled_action.setCheckable(True)
        self.enabled_action.toggled.connect(self._set_enabled)
        self.autostart_action = menu.addAction("Start at login")
        self.autostart_action.setCheckable(True)
        self.autostart_action.setChecked(autostart.is_enabled())
        self.autostart_action.toggled.connect(autostart.set_enabled)
        menu.addAction("Edit autoreplace list…", self._open_autoreplace)
        menu.addSeparator()
        menu.addAction("Quit", app.quit)
        self.menu = menu

        self.icon = QSystemTrayIcon(self.icons["on"])
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._on_activated)

        self.events = DaemonEvents()
        # Tray is not a QObject, so Qt cannot tell its thread: queue explicitly.
        self.events.switched.connect(self._on_switched, Qt.ConnectionType.QueuedConnection)
        self.events.failed.connect(self._on_failed, Qt.ConnectionType.QueuedConnection)

        self.flash_timer = QTimer()
        self.flash_timer.setInterval(FLASH_INTERVAL_MS)
        self.flash_timer.timeout.connect(self._flash_step)

        self.refresh()
        self.icon.show()

    def toggle(self):
        self.enabled_action.toggle()

    def refresh(self):
        enabled = not self.typist.paused and self.error is None
        self.enabled_action.blockSignals(True)
        self.enabled_action.setChecked(not self.typist.paused)
        self.enabled_action.blockSignals(False)
        if not self.flash_timer.isActive():
            self.icon.setIcon(self.icons["on" if enabled else "off"])
        if self.error is not None:
            state = f"stopped: {self.error}"
        else:
            state = "paused" if self.typist.paused else "on"
        self.icon.setToolTip(f"Layout Switcher — {state}\nFixes and expansions: {self.switches}")

    def _set_enabled(self, enabled):
        self.typist.paused = not enabled
        log.info("resumed" if enabled else "paused")
        self.refresh()

    def _open_autoreplace(self):
        path = self.typist.autoreplace.ensure_file()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle()

    def _on_switched(self):
        self.switches += 1
        self.flashes_left = FLASH_TOGGLES
        self.flash_timer.start()
        self._flash_step()

    def _flash_step(self):
        self.flashes_left -= 1
        if self.flashes_left <= 0:
            self.flash_timer.stop()
            self.refresh()
            return
        self.icon.setIcon(self.icons["flash" if self.flashes_left % 2 else "on"])

    def _on_failed(self, message):
        self.error = message
        self.icon.showMessage("Layout Switcher", f"Layout fixing stopped: {message}",
                              QSystemTrayIcon.MessageIcon.Warning)
        self.refresh()


def _run_daemon(daemon, events):
    try:
        daemon.run()
    except Exception as error:
        log.exception("daemon stopped")
        events.failed.emit(str(error))


def run_with_tray(daemon):
    app = QApplication(sys.argv)
    app.setApplicationName("Layout Switcher")
    app.setDesktopFileName("layout-switcher")
    app.setQuitOnLastWindowClosed(False)

    tray = Tray(app, daemon.typist)
    daemon.typist.on_switch = tray.events.switched.emit
    worker = threading.Thread(target=_run_daemon, args=(daemon, tray.events), daemon=True)
    worker.start()

    signal.signal(signal.SIGUSR1, lambda *_: tray.toggle())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    # Python runs signal handlers only between bytecodes; keep the interpreter ticking under Qt.
    ticker = QTimer()
    ticker.timeout.connect(lambda: None)
    ticker.start(300)

    app.exec()
    # Let a retype in progress finish before the virtual keyboard is destroyed.
    daemon.stopping.set()
    worker.join(timeout=2)
