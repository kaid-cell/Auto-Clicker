"""Always-on-top helper windows: the click ripple visualizer and the mini HUD."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import win32


def physical_to_logical(x: int, y: int) -> QPoint:
    """Map physical screen pixels (Win32) to Qt's device-independent pixels.

    With per-monitor DPI awareness Qt keeps each screen's top-left at its native
    position but scales its size by the screen's device pixel ratio.
    """
    for screen in QGuiApplication.screens():
        g = screen.geometry()
        dpr = screen.devicePixelRatio()
        native = QRect(g.topLeft(), g.size() * dpr)
        if native.contains(x, y):
            return QPoint(round(g.x() + (x - g.x()) / dpr), round(g.y() + (y - g.y()) / dpr))
    return QPoint(x, y)


_OVERLAY_FLAGS = (
    Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
    | Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint
)


class RippleOverlay(QWidget):
    """A small transparent window that draws an expanding ring where a click
    landed. It is click-through, so it never intercepts the clicks it shows."""

    SIZE = 84

    def __init__(self) -> None:
        super().__init__(None, _OVERLAY_FLAGS | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.color = QColor("#00d4ff")
        self._t = 1.0
        self._made_click_through = False
        self._anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=420)
        self._anim.valueChanged.connect(self._on_tick)
        self._anim.finished.connect(self.hide)

    def ripple(self, x: int, y: int) -> None:
        pos = physical_to_logical(x, y)
        self.move(pos.x() - self.SIZE // 2, pos.y() - self.SIZE // 2)
        if not self.isVisible():
            self.show()
            if not self._made_click_through:
                # Belt and braces: set WS_EX_TRANSPARENT ourselves so injected
                # clicks always pass straight through to the window below.
                win32.make_click_through(int(self.winId()))
                self._made_click_through = True
        self._anim.stop()
        self._anim.start()

    def _on_tick(self, v) -> None:
        self._t = float(v)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self._t
        c = QColor(self.color)
        center = QPointF(self.SIZE / 2, self.SIZE / 2)
        # Outer ring expands and fades; inner dot shrinks.
        c.setAlpha(int(230 * (1 - t)))
        p.setPen(QPen(c, 3 * (1 - t) + 1))
        p.setBrush(Qt.NoBrush)
        r = 6 + (self.SIZE / 2 - 8) * t
        p.drawEllipse(center, r, r)
        c.setAlpha(int(200 * (1 - t)))
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawEllipse(center, 5 * (1 - t) + 1, 5 * (1 - t) + 1)
        p.end()


class MiniHud(QWidget):
    """Floating, draggable status pill shown while clicking."""

    activated = Signal()   # double-clicked: bring the main window back

    def __init__(self) -> None:
        super().__init__(None, _OVERLAY_FLAGS)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(300, 46)
        self.setCursor(Qt.SizeAllCursor)
        self.setToolTip("Drag to move · double-click to open BleeClicker")
        self.colors = {"card": "#161922", "border": "#252a37", "text": "#eceff6",
                       "subtext": "#8a92a6", "accent": "#7c5cff"}
        self.dot = QColor("#2ee59d")
        self.title = "Running"
        self.detail = ""
        self._drag: QPoint | None = None
        self._placed = False

    def show_hud(self) -> None:
        if not self._placed:
            screen = QGuiApplication.primaryScreen().availableGeometry()
            self.move(screen.center().x() - self.width() // 2, screen.top() + 18)
            self._placed = True
        self.show()

    def set_info(self, title: str, detail: str, dot: str) -> None:
        self.title, self.detail, self.dot = title, detail, QColor(dot)
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e) -> None:
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e) -> None:
        self._drag = None

    def mouseDoubleClickEvent(self, _e) -> None:
        self.activated.emit()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self.colors
        bg = QColor(c["card"])
        bg.setAlpha(238)
        p.setBrush(bg)
        p.setPen(QPen(QColor(c["border"]), 1))
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        # status dot with halo
        halo = QColor(self.dot)
        halo.setAlpha(70)
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QPointF(24, rect.center().y()), 8, 8)
        p.setBrush(self.dot)
        p.drawEllipse(QPointF(24, rect.center().y()), 4.5, 4.5)
        f = p.font()
        f.setBold(True)
        f.setPointSizeF(10)
        p.setFont(f)
        p.setPen(QColor(c["text"]))
        p.drawText(QRectF(40, 0, 110, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.title)
        f.setBold(False)
        f.setPointSizeF(9)
        p.setFont(f)
        p.setPen(QColor(c["subtext"]))
        p.drawText(QRectF(130, 0, self.width() - 146, self.height()), Qt.AlignVCenter | Qt.AlignRight,
                   self.detail)
        p.end()
