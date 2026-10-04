"""Custom widgets: cards, segmented control, toggle switch, power button,
live CPS graph, stat tiles and the hotkey recorder."""

from __future__ import annotations

import math

from PySide6.QtCore import (
    Property, QEasingCurve, QEvent, QPointF, QPropertyAnimation, QRectF, QSize, Qt,
    QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QFont, QKeyEvent, QLinearGradient, QPainter, QPainterPath, QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from . import win32
from .hotkeys import KEY_CODES, Hotkey


def _kv(key) -> int:
    """Qt key enums vs. ints differ between PySide6 versions; normalise."""
    return key.value if hasattr(key, "value") else int(key)


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


# =========================================================================== #
# Layout helpers
# =========================================================================== #
class Card(QFrame):
    """Rounded panel with a bold title (and optional subtitle)."""

    def __init__(self, title: str | None = None, subtitle: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 16)
        outer.setSpacing(10)
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        if title:
            titles = QVBoxLayout()
            titles.setSpacing(1)
            t = QLabel(title, objectName="cardTitle")
            titles.addWidget(t)
            if subtitle:
                s = QLabel(subtitle, objectName="cardSub")
                s.setWordWrap(True)
                titles.addWidget(s)
            self.header.addLayout(titles, 1)
            outer.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(9)
        outer.addLayout(self.body)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)


class StatTile(QFrame):
    def __init__(self, label: str, value: str = "–", tip: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tile")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(2)
        self.label = QLabel(label.upper(), objectName="tileLabel")
        self.value = QLabel(value, objectName="tileValue")
        lay.addWidget(self.label)
        lay.addWidget(self.value)
        if tip:
            self.setToolTip(tip)

    def set_value(self, text: str) -> None:
        self.value.setText(text)


# =========================================================================== #
# Inputs
# =========================================================================== #
class Segmented(QFrame):
    """A row of mutually exclusive pill buttons (like a Fluent segmented control)."""

    changed = Signal(object)

    def __init__(self, options: list[tuple[str, object]], tips: dict | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("segbar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[object, QPushButton] = {}
        for label, data in options:
            b = QPushButton(label, objectName="seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            if tips and data in tips:
                b.setToolTip(tips[data])
            self._group.addButton(b)
            self._buttons[data] = b
            lay.addWidget(b, 1)
            b.toggled.connect(lambda on, d=data: on and self.changed.emit(d))
        next(iter(self._buttons.values())).setChecked(True)

    def value(self):
        for data, b in self._buttons.items():
            if b.isChecked():
                return data
        return None

    def set_value(self, data) -> None:
        if data in self._buttons:
            self._buttons[data].setChecked(True)

    def button(self, data) -> QPushButton:
        return self._buttons[data]


class ToggleSwitch(QCheckBox):
    """A checkbox drawn as an animated on/off switch with its label on the right."""

    _W, _H = 38, 22

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)
        self.colors = {"accent": "#7c5cff", "accent2": "#00d4ff", "track": "#2b3142", "text": "#eceff6",
                       "disabled": "#5b6273"}

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def setChecked(self, on: bool) -> None:  # noqa: N802 - Qt naming
        super().setChecked(on)
        self._anim.stop()
        self._pos = 1.0 if on else 0.0
        self.update()

    def _get_knob(self) -> float:
        return self._pos

    def _set_knob(self, v: float) -> None:
        self._pos = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        w = self._W + (10 + fm.horizontalAdvance(self.text()) if self.text() else 0)
        return QSize(w, max(self._H, fm.height()) + 4)

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self.colors
        y = (self.height() - self._H) / 2
        track = QRectF(0, y, self._W, self._H)
        enabled = self.isEnabled()
        if self._pos > 0:
            g = QLinearGradient(track.topLeft(), track.topRight())
            on1, on2 = QColor(c["accent"]), QColor(c["accent2"])
            off = QColor(c["track"])
            g.setColorAt(0, _mix(off, on1, self._pos))
            g.setColorAt(1, _mix(off, on2, self._pos))
            p.setBrush(QBrush(g))
        else:
            p.setBrush(QColor(c["track"]))
        if not enabled:
            p.setOpacity(0.45)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(track, self._H / 2, self._H / 2)
        d = self._H - 6
        x = 3 + (self._W - d - 6) * self._pos
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(x, y + 3, d, d))
        p.setOpacity(1.0)
        if self.text():
            p.setPen(QColor(c["text"] if enabled else c["disabled"]))
            p.drawText(QRectF(self._W + 10, 0, self.width() - self._W - 10, self.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.end()


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


# =========================================================================== #
# Power button
# =========================================================================== #
class PowerButton(QAbstractButton):
    """Big round start/stop button with an animated glow ring while running."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(96, 96)
        self.state = "idle"          # idle | running | waiting
        self.colors = {"accent": "#7c5cff", "accent2": "#00d4ff", "track": "#2b3142",
                       "warning": "#ffb020", "card": "#161922", "text": "#eceff6"}
        self._phase = 0.0
        self._hover = False
        self._anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=1600, loopCount=-1)
        self._anim.valueChanged.connect(self._tick)

    def set_state(self, state: str) -> None:
        if state == self.state:
            return
        self.state = state
        if state == "idle":
            self._anim.stop()
            self._phase = 0.0
        elif self._anim.state() != QVariantAnimation.Running:
            self._anim.start()
        self.update()

    def _tick(self, v) -> None:
        self._phase = float(v)
        self.update()

    def enterEvent(self, e) -> None:
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self.colors
        r = self.rect().adjusted(6, 6, -6, -6)
        center = QPointF(r.center())
        a1, a2 = QColor(c["accent"]), QColor(c["accent2"])
        if self.state == "waiting":
            a1 = a2 = QColor(c["warning"])

        # Pulsing outer glow while active.
        if self.state != "idle":
            pulse = 0.5 + 0.5 * math.sin(self._phase * 2 * math.pi)
            glow = QRadialGradient(center, r.width() / 2 + 6)
            gc = QColor(a1)
            gc.setAlpha(int(40 + 70 * pulse))
            glow.setColorAt(0.75, gc)
            gc2 = QColor(a1)
            gc2.setAlpha(0)
            glow.setColorAt(1.0, gc2)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(glow))
            p.drawEllipse(QRectF(self.rect()))

        # Body
        body = QRectF(r)
        if self.state == "idle":
            p.setBrush(QColor(c["card"]))
            p.setPen(QPen(QColor(c["track"]), 2))
        else:
            g = QLinearGradient(body.topLeft(), body.bottomRight())
            g.setColorAt(0, a1)
            g.setColorAt(1, a2)
            p.setBrush(QBrush(g))
            p.setPen(Qt.NoPen)
        p.drawEllipse(body)

        # Idle: gradient ring that brightens on hover. Active: spinning arc.
        ring = body.adjusted(3, 3, -3, -3)
        if self.state == "idle":
            g = QLinearGradient(ring.topLeft(), ring.bottomRight())
            g.setColorAt(0, a1)
            g.setColorAt(1, a2)
            pen = QPen(QBrush(g), 4 if self._hover else 3)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(ring)
        else:
            pen = QPen(QColor(255, 255, 255, 170), 3)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawArc(ring, int(-self._phase * 360 * 16), 70 * 16)

        # Power glyph
        icon_color = QColor(c["text"]) if self.state == "idle" else QColor("#ffffff")
        pen = QPen(icon_color, 4)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        s = body.width() * 0.2
        arc = QRectF(center.x() - s, center.y() - s + 2, 2 * s, 2 * s)
        p.drawArc(arc, 120 * 16, 300 * 16)
        p.drawLine(QPointF(center.x(), center.y() - s - 4), QPointF(center.x(), center.y() + 1))
        p.end()


# =========================================================================== #
# Live CPS graph
# =========================================================================== #
class CpsGraph(QWidget):
    """Smooth area chart of recent clicks-per-second samples."""

    def __init__(self, parent: QWidget | None = None, compact: bool = False) -> None:
        super().__init__(parent)
        self.values: list[float] = []
        self.target: float | None = None
        self.compact = compact
        self.colors = {"accent": "#7c5cff", "accent2": "#00d4ff", "subtext": "#8a92a6", "border": "#252a37"}
        self.setMinimumHeight(46 if compact else 150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding if not compact else QSizePolicy.Fixed)

    def set_values(self, values: list[float], target: float | None = None) -> None:
        self.values = values
        self.target = target
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self.colors
        pad_l = 4 if self.compact else 40
        rect = QRectF(self.rect()).adjusted(pad_l, 6, -4, -(4 if self.compact else 20))
        vals = self.values
        peak = max([*vals, self.target or 0, 1.0])
        top = _nice_ceiling(peak * 1.15)

        if not self.compact:
            # Grid + axis labels
            p.setFont(QFont(self.font().family(), 8))
            for i in range(5):
                y = rect.bottom() - rect.height() * i / 4
                p.setPen(QPen(QColor(c["border"]), 1, Qt.DashLine if i else Qt.SolidLine))
                p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
                p.setPen(QColor(c["subtext"]))
                p.drawText(QRectF(0, y - 8, pad_l - 6, 16), Qt.AlignRight | Qt.AlignVCenter,
                           _fmt_axis(top * i / 4))
            p.drawText(QRectF(rect.left(), rect.bottom() + 4, rect.width(), 14),
                       Qt.AlignLeft, "−30 s")
            p.drawText(QRectF(rect.left(), rect.bottom() + 4, rect.width(), 14),
                       Qt.AlignRight, "now")
        if self.target and not self.compact:
            y = rect.bottom() - rect.height() * min(self.target / top, 1)
            pen = QPen(QColor(c["subtext"]), 1, Qt.DotLine)
            p.setPen(pen)
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            p.drawText(QRectF(rect.left() + 4, y - 16, 160, 14), Qt.AlignLeft, "target")

        if len(vals) >= 2:
            n = len(vals)
            pts = [QPointF(rect.left() + rect.width() * i / (n - 1),
                           rect.bottom() - rect.height() * min(v / top, 1.0)) for i, v in enumerate(vals)]
            line = QPainterPath(pts[0])
            for a, b in zip(pts, pts[1:]):   # smooth curve through the samples
                mid = (a.x() + b.x()) / 2
                line.cubicTo(QPointF(mid, a.y()), QPointF(mid, b.y()), b)
            area = QPainterPath(line)
            area.lineTo(pts[-1].x(), rect.bottom())
            area.lineTo(pts[0].x(), rect.bottom())
            area.closeSubpath()
            fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            f1 = QColor(c["accent"])
            f1.setAlpha(110)
            f2 = QColor(c["accent2"])
            f2.setAlpha(0)
            fill.setColorAt(0, f1)
            fill.setColorAt(1, f2)
            p.fillPath(area, QBrush(fill))
            stroke = QLinearGradient(rect.topLeft(), rect.topRight())
            stroke.setColorAt(0, QColor(c["accent"]))
            stroke.setColorAt(1, QColor(c["accent2"]))
            pen = QPen(QBrush(stroke), 2.2)
            p.setPen(pen)
            p.drawPath(line)
            p.setBrush(QColor(c["accent2"]))
            p.setPen(Qt.NoPen)
            p.drawEllipse(pts[-1], 3.5, 3.5)
        p.end()


def _nice_ceiling(v: float) -> float:
    exp = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * exp:
            return m * exp
    return 10 * exp


def _fmt_axis(v: float) -> str:
    return f"{v:.0f}" if v >= 10 or v == int(v) else f"{v:.1f}"


class StatusDot(QWidget):
    """A small filled circle with a soft halo, used as the status light."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor("#8a8a8a")
        self.setFixedSize(QSize(14, 14))

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        halo = QColor(self._color)
        halo.setAlpha(70)
        p.setBrush(halo)
        p.drawEllipse(QRectF(0, 0, 14, 14))
        p.setBrush(self._color)
        p.drawEllipse(QRectF(3, 3, 8, 8))
        p.end()


class ColorSwatch(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("swatch")
        self.setFixedSize(30, 30)

    def set_color(self, hex_color: str) -> None:
        self.setStyleSheet(f"QFrame#swatch {{ background: {hex_color}; }}")


# =========================================================================== #
# Hotkey recorder
# =========================================================================== #
_QT_KEYS: dict[int, str] = {}
_QT_KEYS.update({_kv(Qt.Key.Key_F1) + i: f"F{i + 1}" for i in range(24)})
_QT_KEYS.update({c: chr(c) for c in range(ord("A"), ord("Z") + 1)})
_QT_KEYS.update({ord(str(d)): str(d) for d in range(10)})
_QT_KEYS.update({
    _kv(Qt.Key.Key_Space): "Space", _kv(Qt.Key.Key_PageUp): "PageUp",
    _kv(Qt.Key.Key_PageDown): "PageDown", _kv(Qt.Key.Key_End): "End",
    _kv(Qt.Key.Key_Home): "Home", _kv(Qt.Key.Key_Left): "Left", _kv(Qt.Key.Key_Up): "Up",
    _kv(Qt.Key.Key_Right): "Right", _kv(Qt.Key.Key_Down): "Down",
    _kv(Qt.Key.Key_Insert): "Insert", _kv(Qt.Key.Key_Delete): "Delete",
    _kv(Qt.Key.Key_Pause): "Pause", _kv(Qt.Key.Key_ScrollLock): "ScrollLock",
})
_VK_TO_NAME = {vk: name for name, vk in KEY_CODES.items()}
_MODIFIER_KEYS = {
    _kv(Qt.Key.Key_Control), _kv(Qt.Key.Key_Shift), _kv(Qt.Key.Key_Alt),
    _kv(Qt.Key.Key_Meta), _kv(Qt.Key.Key_AltGr),
}


class HotkeyButton(QPushButton):
    """Click it, then press a key combination to record a hotkey.

    Emits ``captureStarted`` / ``captureEnded`` so the window can suspend the
    global hotkeys while recording (otherwise Windows would swallow the key),
    and ``captured(Hotkey)`` when a combination was recorded.
    """

    captureStarted = Signal()
    captureEnded = Signal()
    captured = Signal(object)

    def __init__(self, hotkey: Hotkey, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._capturing = False
        self.setObjectName("hotkey")
        self.setCursor(Qt.PointingHandCursor)
        self._hotkey = hotkey
        self.setProperty("capturing", False)
        self.setProperty("invalid", False)
        self.clicked.connect(self._toggle_capture)
        self.setText(str(hotkey))

    @property
    def hotkey(self) -> Hotkey:
        return self._hotkey

    def set_hotkey(self, hotkey: Hotkey) -> None:
        self._hotkey = hotkey
        if not self._capturing:
            self.setText(str(hotkey))

    def set_invalid(self, invalid: bool) -> None:
        self.setProperty("invalid", invalid)
        repolish(self)

    def _toggle_capture(self) -> None:
        if self._capturing:
            self._end_capture()
        else:
            self._begin_capture()

    def _begin_capture(self) -> None:
        self._capturing = True
        self.setProperty("capturing", True)
        repolish(self)
        self.setText("Press keys…")
        self.captureStarted.emit()
        self.setFocus(Qt.OtherFocusReason)
        self.grabKeyboard()

    def _end_capture(self) -> None:
        if not self._capturing:
            return
        self._capturing = False
        self.releaseKeyboard()
        self.setProperty("capturing", False)
        repolish(self)
        self.setText(str(self._hotkey))
        self.captureEnded.emit()

    def event(self, event) -> bool:
        # Tab/Backtab are normally consumed for focus navigation before
        # keyPressEvent runs; while recording, route every key to us.
        if getattr(self, "_capturing", False) and event.type() == QEvent.KeyPress:
            self.keyPressEvent(event)
            return True
        return super().event(event)

    def focusOutEvent(self, event) -> None:
        self._end_capture()
        super().focusOutEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._capturing:
            super().keyPressEvent(event)
            return
        key = _kv(event.key())
        mods = self._modifier_names(event)
        if key == _kv(Qt.Key.Key_Escape) and not mods:
            self._end_capture()  # cancel
            return
        if key in _MODIFIER_KEYS:
            self.setText("+".join(mods + ["…"]))
            return
        name = self._key_name(event, key)
        if name is None:
            self.setText("Unsupported key")
            return
        hotkey = Hotkey(name, tuple(mods))
        self._end_capture()
        self.captured.emit(hotkey)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if self._capturing and _kv(event.key()) in _MODIFIER_KEYS:
            mods = self._modifier_names(event)
            self.setText("+".join(mods + ["…"]) if mods else "Press keys…")
            return
        super().keyReleaseEvent(event)

    @staticmethod
    def _modifier_names(event: QKeyEvent) -> list[str]:
        m = event.modifiers()
        names = []
        if m & Qt.ControlModifier:
            names.append("Ctrl")
        if m & Qt.AltModifier:
            names.append("Alt")
        if m & Qt.ShiftModifier:
            names.append("Shift")
        if m & Qt.MetaModifier:  # the Windows key on Windows
            names.append("Win")
        return names

    @staticmethod
    def _key_name(event: QKeyEvent, key: int) -> str | None:
        # On Windows the native virtual-key code is layout-independent and
        # exactly what RegisterHotKey needs (and distinguishes the numpad).
        if win32.IS_WINDOWS:
            name = _VK_TO_NAME.get(event.nativeVirtualKey())
            if name:
                return name
        return _QT_KEYS.get(key)
