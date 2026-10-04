"""Custom widgets: section cards, hotkey recorder and status indicator."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from . import win32
from .hotkeys import KEY_CODES, Hotkey


def _kv(key) -> int:
    """Qt key enums vs. ints differ between PySide6 versions; normalise."""
    return key.value if hasattr(key, "value") else int(key)


# Qt key -> our key name (fallback when the native virtual-key is unavailable)
_QT_KEYS: dict[int, str] = {}
_QT_KEYS.update({_kv(Qt.Key.Key_F1) + i: f"F{i + 1}" for i in range(24)})
_QT_KEYS.update({c: chr(c) for c in range(ord("A"), ord("Z") + 1)})
_QT_KEYS.update({ord(str(d)): str(d) for d in range(10)})
_QT_KEYS.update({
    _kv(Qt.Key.Key_Space): "Space",
    _kv(Qt.Key.Key_PageUp): "PageUp",
    _kv(Qt.Key.Key_PageDown): "PageDown",
    _kv(Qt.Key.Key_End): "End",
    _kv(Qt.Key.Key_Home): "Home",
    _kv(Qt.Key.Key_Left): "Left",
    _kv(Qt.Key.Key_Up): "Up",
    _kv(Qt.Key.Key_Right): "Right",
    _kv(Qt.Key.Key_Down): "Down",
    _kv(Qt.Key.Key_Insert): "Insert",
    _kv(Qt.Key.Key_Delete): "Delete",
    _kv(Qt.Key.Key_Pause): "Pause",
    _kv(Qt.Key.Key_ScrollLock): "ScrollLock",
})
_VK_TO_NAME = {vk: name for name, vk in KEY_CODES.items()}
_MODIFIER_KEYS = {
    _kv(Qt.Key.Key_Control), _kv(Qt.Key.Key_Shift), _kv(Qt.Key.Key_Alt),
    _kv(Qt.Key.Key_Meta), _kv(Qt.Key.Key_AltGr),
}


class Card(QFrame):
    """A rounded panel with a bold title, used to group related settings."""

    def __init__(self, title: str | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 14)
        outer.setSpacing(10)
        if title:
            label = QLabel(title)
            label.setObjectName("cardTitle")
            outer.addWidget(label)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        outer.addLayout(self.body)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)


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
        self.setObjectName("hotkey")
        self.setCursor(Qt.PointingHandCursor)
        self._hotkey = hotkey
        self._capturing = False
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
        self._repolish()

    # -- capture handling -------------------------------------------------- #
    def _toggle_capture(self) -> None:
        if self._capturing:
            self._end_capture()
        else:
            self._begin_capture()

    def _begin_capture(self) -> None:
        self._capturing = True
        self.setProperty("capturing", True)
        self._repolish()
        self.setText("Press a key…")
        self.captureStarted.emit()
        self.setFocus(Qt.OtherFocusReason)
        self.grabKeyboard()

    def _end_capture(self) -> None:
        if not self._capturing:
            return
        self._capturing = False
        self.releaseKeyboard()
        self.setProperty("capturing", False)
        self._repolish()
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
            self.setText("+".join(mods + ["…"]) if mods else "Press a key…")
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

    def _repolish(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)


class StatusDot(QWidget):
    """A small filled circle with a soft halo, used as the status light."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor("#8a8a8a")
        self.setFixedSize(QSize(16, 16))

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        halo = QColor(self._color)
        halo.setAlpha(60)
        p.setBrush(halo)
        p.drawEllipse(QRectF(0, 0, 16, 16))
        p.setBrush(self._color)
        p.drawEllipse(QRectF(3.5, 3.5, 9, 9))
        p.end()
