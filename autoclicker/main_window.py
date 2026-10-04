"""Main application window."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QCursor, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QButtonGroup, QCheckBox, QComboBox, QFormLayout, QGridLayout,
    QHBoxLayout, QLabel, QMainWindow, QPushButton, QRadioButton, QScrollArea,
    QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from . import APP_NAME, APP_VERSION, theme, win32
from .clicker import MAX_INTERVAL_MS, MIN_INTERVAL_MS, ClickConfig, ClickEngine, StopReason
from .hotkeys import Hotkey, HotkeyListener
from .settings import Settings
from .widgets import Card, HotkeyButton, StatusDot

HOTKEY_TOGGLE = 1
HOTKEY_EMERGENCY = 2
DEFAULT_TOGGLE = Hotkey("F6")
DEFAULT_EMERGENCY = Hotkey("F7")
CAPTURE_COUNTDOWN = 3          # seconds before "Capture Position" records the cursor
TWO_COLUMN_MIN_WIDTH = 720     # window width at which cards flow into two columns


class _HotkeyBridge(QObject):
    """Carries hotkey presses from the listener thread to the GUI thread."""

    triggered = Signal(int)


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, icon: QIcon | None = None) -> None:
        super().__init__()
        self.settings = settings
        self.colors = theme.resolve(settings.theme)
        self._loading = True          # suppress saves while populating widgets
        self._running = False
        self._two_columns: bool | None = None
        self._capture_remaining = 0
        self._last_error = ""

        self.setWindowTitle(APP_NAME)
        if icon is not None:
            self.setWindowIcon(icon)
        self.setMinimumWidth(400)

        # Engine + hotkeys
        self.engine = ClickEngine()
        self.engine.stopped.connect(self._on_engine_stopped)
        self._bridge = _HotkeyBridge()
        self._bridge.triggered.connect(self._on_hotkey)
        self.hotkeys = HotkeyListener(self._bridge.triggered.emit)

        self._build_ui()
        self._load_settings_into_ui()
        self._loading = False

        # Debounced settings save
        self._save_timer = QTimer(self, singleShot=True, interval=400)
        self._save_timer.timeout.connect(self._save_settings)

        # Periodic UI refresh (click counter + live cursor position). Polling
        # keeps the worker thread from flooding the GUI with per-click signals.
        self._refresh_timer = QTimer(self, interval=50)
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start()

        self._capture_timer = QTimer(self, interval=1000)
        self._capture_timer.timeout.connect(self._capture_tick)

        self.hotkeys.start()
        self._apply_hotkeys()
        self._update_interval_hint()
        self._update_location_enabled()
        self._update_repeat_enabled()
        self._set_running_ui(False)

        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(self._on_system_theme_changed)

        if not win32.IS_WINDOWS:
            self._show_message("Clicking and global hotkeys require Windows.", error=True)

    # ===================================================================== #
    # UI construction
    # ===================================================================== #
    def _build_ui(self) -> None:
        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 14, 18, 10)
        outer.setSpacing(12)

        # Header ---------------------------------------------------------- #
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel(APP_NAME, objectName="appTitle")
        subtitle = QLabel(f"Version {APP_VERSION}", objectName="hint")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch(1)
        header.addWidget(QLabel("Theme", objectName="subtle"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("System", "system")
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.setToolTip("Follow the Windows app theme, or force light/dark.")
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        header.addWidget(self.theme_combo)
        outer.addLayout(header)

        # Cards (inside a scroll area so small screens still work) -------- #
        self.cards = [
            self._build_click_card(),
            self._build_interval_card(),
            self._build_location_card(),
            self._build_repeat_card(),
            self._build_hotkey_card(),
        ]
        self.click_card, self.interval_card, self.location_card, self.repeat_card, self.hotkey_card = self.cards

        # Two independent columns (not a grid) so each column packs its
        # cards tightly instead of sharing row heights with the other column.
        self.cards_host = QWidget(objectName="root")
        columns = QHBoxLayout(self.cards_host)
        columns.setContentsMargins(0, 0, 4, 0)
        columns.setSpacing(12)
        self.col_left = QVBoxLayout()
        self.col_right = QVBoxLayout()
        for col in (self.col_left, self.col_right):
            col.setSpacing(12)
            columns.addLayout(col, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(self.cards_host)
        outer.addWidget(scroll, 1)

        # Control bar ------------------------------------------------------- #
        outer.addWidget(self._build_control_bar())
        self.statusBar().setSizeGripEnabled(True)

        self._layout_cards(two_columns=True)
        self.resize(820, 600)

    def _build_click_card(self) -> Card:
        card = Card("Click")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)

        self.button_combo = QComboBox()
        self.button_combo.addItem("Left", "left")
        self.button_combo.addItem("Right", "right")
        self.button_combo.addItem("Middle", "middle")
        self.button_combo.setToolTip("Which mouse button to press.")
        self.button_combo.currentIndexChanged.connect(self._schedule_save)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Single", "single")
        self.mode_combo.addItem("Double", "double")
        self.mode_combo.setToolTip(
            "Single: one click per interval.\n"
            "Double: a double click per interval (counts as one click action)."
        )
        self.mode_combo.currentIndexChanged.connect(self._schedule_save)

        form.addRow("Click type", self.button_combo)
        form.addRow("Click mode", self.mode_combo)
        card.body.addLayout(form)
        return card

    def _build_interval_card(self) -> Card:
        card = Card("Click Interval")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        self.hours_spin = self._make_spin(0, 23, "Hours between clicks.")
        self.minutes_spin = self._make_spin(0, 59, "Minutes between clicks.")
        self.seconds_spin = self._make_spin(0, 59, "Seconds between clicks.")
        self.ms_spin = self._make_spin(0, 999, "Milliseconds between clicks (minimum total interval is 1 ms).")
        for col, (label, spin) in enumerate((
            ("Hours", self.hours_spin), ("Minutes", self.minutes_spin),
            ("Seconds", self.seconds_spin), ("Milliseconds", self.ms_spin),
        )):
            grid.addWidget(QLabel(label, objectName="subtle"), 0, col)
            grid.addWidget(spin, 1, col)
            spin.valueChanged.connect(self._on_interval_changed)
        card.body.addLayout(grid)
        self.interval_hint = QLabel(objectName="hint")
        card.body.addWidget(self.interval_hint)
        return card

    def _build_location_card(self) -> Card:
        card = Card("Click Location")
        self.loc_current = QRadioButton("Current mouse position")
        self.loc_current.setToolTip("Click wherever the mouse pointer is at the time of each click.")
        self.loc_fixed = QRadioButton("Fixed position")
        self.loc_fixed.setToolTip(
            "Move the pointer to the X/Y screen coordinates below before each click.\n"
            "Coordinates are physical screen pixels; (0, 0) is the top-left of the primary monitor."
        )
        self.loc_group = QButtonGroup(self)
        self.loc_group.addButton(self.loc_current)
        self.loc_group.addButton(self.loc_fixed)
        self.loc_current.toggled.connect(self._on_location_changed)
        card.body.addWidget(self.loc_current)
        card.body.addWidget(self.loc_fixed)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.x_spin = self._make_spin(-32768, 32767, "Horizontal screen coordinate in pixels.")
        self.y_spin = self._make_spin(-32768, 32767, "Vertical screen coordinate in pixels.")
        self.x_spin.valueChanged.connect(self._schedule_save)
        self.y_spin.valueChanged.connect(self._schedule_save)
        row.addWidget(QLabel("X"))
        row.addWidget(self.x_spin, 1)
        row.addSpacing(6)
        row.addWidget(QLabel("Y"))
        row.addWidget(self.y_spin, 1)
        card.body.addLayout(row)

        cap_row = QHBoxLayout()
        self.capture_btn = QPushButton("Capture Position")
        self.capture_btn.setToolTip(
            f"Starts a {CAPTURE_COUNTDOWN}-second countdown. Move the mouse to the target,\n"
            "and its position is recorded when the countdown ends. Click again to cancel."
        )
        self.capture_btn.clicked.connect(self._toggle_capture)
        cap_row.addWidget(self.capture_btn)
        cap_row.addStretch(1)
        self.cursor_label = QLabel(objectName="hint")
        self.cursor_label.setToolTip("Live mouse pointer position.")
        cap_row.addWidget(self.cursor_label)
        card.body.addLayout(cap_row)
        return card

    def _build_repeat_card(self) -> Card:
        card = Card("Number of Clicks")
        self.rep_unlimited = QRadioButton("Unlimited (until stopped)")
        self.rep_count = QRadioButton("Custom")
        self.rep_count.setToolTip("Stop automatically after this many click actions.")
        self.rep_group = QButtonGroup(self)
        self.rep_group.addButton(self.rep_unlimited)
        self.rep_group.addButton(self.rep_count)
        self.rep_unlimited.toggled.connect(self._on_repeat_changed)

        self.count_spin = self._make_spin(1, 10_000_000, "Number of click actions to perform.")
        self.count_spin.setGroupSeparatorShown(True)
        self.count_spin.valueChanged.connect(self._schedule_save)

        card.body.addWidget(self.rep_unlimited)
        row = QHBoxLayout()
        row.addWidget(self.rep_count)
        row.addWidget(self.count_spin, 1)
        row.addWidget(QLabel("clicks", objectName="subtle"))
        card.body.addLayout(row)
        return card

    def _build_hotkey_card(self) -> Card:
        card = Card("Hotkeys & Safety")
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)

        self.toggle_hk = HotkeyButton(DEFAULT_TOGGLE)
        self.toggle_hk.setToolTip(
            "Global hotkey that starts/stops clicking, even when another program is focused.\n"
            "Click, then press the new key combination (Esc cancels)."
        )
        self.emergency_hk = HotkeyButton(DEFAULT_EMERGENCY)
        self.emergency_hk.setToolTip(
            "Global hotkey that always stops clicking immediately (it never starts it).\n"
            "Click, then press the new key combination (Esc cancels)."
        )
        for btn in (self.toggle_hk, self.emergency_hk):
            btn.captureStarted.connect(self._suspend_hotkeys)
            btn.captureEnded.connect(self._apply_hotkeys)
        self.toggle_hk.captured.connect(lambda hk: self._on_hotkey_captured(self.toggle_hk, hk))
        self.emergency_hk.captured.connect(lambda hk: self._on_hotkey_captured(self.emergency_hk, hk))
        form.addRow("Start / Stop", self.toggle_hk)
        form.addRow("Emergency stop", self.emergency_hk)
        card.body.addLayout(form)

        self.hotkey_error = QLabel(objectName="error")
        self.hotkey_error.setWordWrap(True)
        self.hotkey_error.hide()
        card.body.addWidget(self.hotkey_error)

        self.failsafe_check = QCheckBox("Fail-safe: stop when mouse hits top-left corner")
        self.failsafe_check.setToolTip(
            "Emergency stop without the keyboard: slam the mouse pointer into the\n"
            "top-left corner of the screen and clicking stops instantly."
        )
        self.failsafe_check.toggled.connect(self._schedule_save)
        self.ontop_check = QCheckBox("Keep window on top")
        self.ontop_check.setToolTip("Keep this window above other windows.")
        self.ontop_check.toggled.connect(self._on_always_on_top)
        card.body.addWidget(self.failsafe_check)
        card.body.addWidget(self.ontop_check)
        return card

    def _build_control_bar(self) -> Card:
        bar = Card(None)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.start_btn = QPushButton("START", objectName="start")
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.setToolTip("Start clicking (or press the Start / Stop hotkey).")
        self.stop_btn = QPushButton("STOP", objectName="stop")
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.setToolTip("Stop clicking immediately.")
        self.start_btn.clicked.connect(self.start_clicking)
        self.stop_btn.clicked.connect(lambda: self.stop_clicking(StopReason.USER))
        row.addWidget(self.start_btn)
        row.addWidget(self.stop_btn)
        row.addStretch(1)

        counter_box = QVBoxLayout()
        counter_box.setSpacing(0)
        clicks_label = QLabel("Clicks", objectName="subtle")
        clicks_label.setAlignment(Qt.AlignRight)
        self.counter_label = QLabel("0", objectName="counter")
        self.counter_label.setAlignment(Qt.AlignRight)
        self.counter_label.setToolTip("Click actions performed in the current/last run.")
        counter_box.addWidget(clicks_label)
        counter_box.addWidget(self.counter_label)
        row.addLayout(counter_box)
        bar.body.addLayout(row)

        status_line = QHBoxLayout()
        status_line.setSpacing(6)
        status_line.addWidget(QLabel("Status:", objectName="subtle"))
        self.status_dot = StatusDot()
        status_line.addWidget(self.status_dot)
        self.status_text = QLabel("Stopped", objectName="statusText")
        status_line.addWidget(self.status_text)
        status_line.addStretch(1)
        self.hotkey_hint = QLabel(objectName="hint")
        status_line.addWidget(self.hotkey_hint)
        bar.body.addLayout(status_line)
        return bar

    @staticmethod
    def _make_spin(lo: int, hi: int, tip: str) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(lo, hi)
        # Fluent-style number box: type a value, or use the mouse wheel / arrow keys.
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        spin.setToolTip(tip + "\nType a value, or use the mouse wheel / Up and Down keys.")
        spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return spin

    # -- responsive layout ------------------------------------------------- #
    def _layout_cards(self, two_columns: bool) -> None:
        if two_columns == self._two_columns:
            return
        self._two_columns = two_columns
        for col in (self.col_left, self.col_right):
            while col.count():
                col.takeAt(0)  # detaches widgets/stretches; cards stay parented
        if two_columns:
            left = [self.click_card, self.interval_card, self.repeat_card]
            right = [self.location_card, self.hotkey_card]
        else:
            left = [self.click_card, self.interval_card, self.location_card,
                    self.repeat_card, self.hotkey_card]
            right = []
        for card in left:
            self.col_left.addWidget(card)
        for card in right:
            self.col_right.addWidget(card)
        self.col_left.addStretch(1)
        self.col_right.addStretch(1)
        self.hotkey_hint.setVisible(two_columns)
        # Collapse the empty right column in single-column mode.
        self.cards_host.layout().setStretch(1, 1 if two_columns else 0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_cards(self.width() >= TWO_COLUMN_MIN_WIDTH)

    # ===================================================================== #
    # Settings <-> UI
    # ===================================================================== #
    def _load_settings_into_ui(self) -> None:
        s = self.settings
        self._select_data(self.theme_combo, s.theme)
        self._select_data(self.button_combo, s.button)
        self._select_data(self.mode_combo, s.click_mode)
        self.hours_spin.setValue(s.hours)
        self.minutes_spin.setValue(s.minutes)
        self.seconds_spin.setValue(s.seconds)
        self.ms_spin.setValue(s.milliseconds)
        (self.loc_fixed if s.location_mode == "fixed" else self.loc_current).setChecked(True)
        self.x_spin.setValue(s.fixed_x)
        self.y_spin.setValue(s.fixed_y)
        (self.rep_count if s.repeat_mode == "count" else self.rep_unlimited).setChecked(True)
        self.count_spin.setValue(s.repeat_count)
        self.failsafe_check.setChecked(s.failsafe)
        self.ontop_check.setChecked(s.always_on_top)
        self.toggle_hk.set_hotkey(self._parse_hotkey(s.hotkey_toggle, DEFAULT_TOGGLE))
        self.emergency_hk.set_hotkey(self._parse_hotkey(s.hotkey_emergency, DEFAULT_EMERGENCY))
        if self.toggle_hk.hotkey == self.emergency_hk.hotkey:
            self.toggle_hk.set_hotkey(DEFAULT_TOGGLE)
            self.emergency_hk.set_hotkey(DEFAULT_EMERGENCY)
        if s.always_on_top:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        if s.window_x is not None and s.window_y is not None:
            self._restore_position(s.window_x, s.window_y)

    def _restore_position(self, x: int, y: int) -> None:
        # Only restore if the saved spot is still on a connected screen.
        for screen in QGuiApplication.screens():
            if screen.availableGeometry().adjusted(0, 0, -80, -40).contains(x + 40, y + 20):
                self.move(x, y)
                return

    @staticmethod
    def _parse_hotkey(text: str, fallback: Hotkey) -> Hotkey:
        try:
            hk = Hotkey.parse(text)
        except ValueError:
            return fallback
        return fallback if hk.validate() else hk

    @staticmethod
    def _select_data(combo: QComboBox, value) -> None:
        idx = combo.findData(value)
        combo.setCurrentIndex(max(idx, 0))

    def _collect_settings(self) -> Settings:
        s = self.settings
        s.theme = self.theme_combo.currentData()
        s.button = self.button_combo.currentData()
        s.click_mode = self.mode_combo.currentData()
        s.hours = self.hours_spin.value()
        s.minutes = self.minutes_spin.value()
        s.seconds = self.seconds_spin.value()
        s.milliseconds = self.ms_spin.value()
        s.location_mode = "fixed" if self.loc_fixed.isChecked() else "current"
        s.fixed_x = self.x_spin.value()
        s.fixed_y = self.y_spin.value()
        s.repeat_mode = "count" if self.rep_count.isChecked() else "unlimited"
        s.repeat_count = self.count_spin.value()
        s.hotkey_toggle = str(self.toggle_hk.hotkey)
        s.hotkey_emergency = str(self.emergency_hk.hotkey)
        s.failsafe = self.failsafe_check.isChecked()
        s.always_on_top = self.ontop_check.isChecked()
        pos = self.pos()
        s.window_x, s.window_y = pos.x(), pos.y()
        return s

    def _schedule_save(self, *_args) -> None:
        if not self._loading:
            self._save_timer.start()

    def _save_settings(self) -> None:
        try:
            self._collect_settings().save()
        except OSError as exc:
            self._show_message(f"Could not save settings: {exc}", error=True)

    # ===================================================================== #
    # Interval / location / repeat helpers
    # ===================================================================== #
    def interval_ms(self) -> int:
        return (
            self.hours_spin.value() * 3_600_000
            + self.minutes_spin.value() * 60_000
            + self.seconds_spin.value() * 1000
            + self.ms_spin.value()
        )

    def _on_interval_changed(self, *_args) -> None:
        self._update_interval_hint()
        self._schedule_save()

    def _update_interval_hint(self) -> None:
        ms = self.interval_ms()
        if ms < MIN_INTERVAL_MS:
            self.interval_hint.setObjectName("error")
            self.interval_hint.setText(f"Interval must be at least {MIN_INTERVAL_MS} ms.")
        else:
            self.interval_hint.setObjectName("hint")
            rate = 1000.0 / ms
            rate_text = f"{rate:,.1f} clicks/s" if rate >= 1 else f"{rate * 60:,.2f} clicks/min"
            self.interval_hint.setText(f"Every {ms:,} ms  ·  {rate_text}")
        self.interval_hint.style().unpolish(self.interval_hint)
        self.interval_hint.style().polish(self.interval_hint)
        if not self._running:
            self.start_btn.setEnabled(ms >= MIN_INTERVAL_MS)

    def _on_location_changed(self, *_args) -> None:
        self._update_location_enabled()
        self._schedule_save()

    def _update_location_enabled(self) -> None:
        fixed = self.loc_fixed.isChecked()
        self.x_spin.setEnabled(fixed)
        self.y_spin.setEnabled(fixed)

    def _on_repeat_changed(self, *_args) -> None:
        self._update_repeat_enabled()
        self._schedule_save()

    def _update_repeat_enabled(self) -> None:
        self.count_spin.setEnabled(self.rep_count.isChecked())

    # -- position capture -------------------------------------------------- #
    def _toggle_capture(self) -> None:
        if self._capture_timer.isActive():
            self._capture_timer.stop()
            self.capture_btn.setText("Capture Position")
            self._show_message("Position capture cancelled.")
            return
        self._capture_remaining = CAPTURE_COUNTDOWN
        self.capture_btn.setText(f"Capturing in {self._capture_remaining}…")
        self._show_message("Move the mouse to the target position…")
        self._capture_timer.start()

    def _capture_tick(self) -> None:
        self._capture_remaining -= 1
        if self._capture_remaining > 0:
            self.capture_btn.setText(f"Capturing in {self._capture_remaining}…")
            return
        self._capture_timer.stop()
        self.capture_btn.setText("Capture Position")
        x, y = self._cursor_pos()
        self.x_spin.setValue(x)
        self.y_spin.setValue(y)
        self.loc_fixed.setChecked(True)
        self._show_message(f"Captured position ({x}, {y}).")

    @staticmethod
    def _cursor_pos() -> tuple[int, int]:
        if win32.IS_WINDOWS:
            try:
                return win32.get_cursor_pos()
            except OSError:
                pass
        p = QCursor.pos()
        return p.x(), p.y()

    # ===================================================================== #
    # Hotkeys
    # ===================================================================== #
    def _suspend_hotkeys(self) -> None:
        # While recording a new hotkey the old ones must not be active,
        # otherwise Windows would swallow the key press (and toggle clicking).
        self.hotkeys.set_hotkeys({})

    def _apply_hotkeys(self) -> None:
        if not self.hotkeys.available:
            self._set_hotkey_error("Global hotkeys are only available on Windows.")
            self._update_hotkey_hint()
            return
        results = self.hotkeys.set_hotkeys({
            HOTKEY_TOGGLE: self.toggle_hk.hotkey,
            HOTKEY_EMERGENCY: self.emergency_hk.hotkey,
        })
        errors = []
        self.toggle_hk.set_invalid(bool(results.get(HOTKEY_TOGGLE)))
        self.emergency_hk.set_invalid(bool(results.get(HOTKEY_EMERGENCY)))
        for hid in (HOTKEY_TOGGLE, HOTKEY_EMERGENCY):
            if results.get(hid):
                errors.append(results[hid])
        self._set_hotkey_error("\n".join(errors) + ("\nPick a different key." if errors else ""))
        self._update_hotkey_hint()

    def _on_hotkey_captured(self, button: HotkeyButton, hotkey: Hotkey) -> None:
        other = self.emergency_hk if button is self.toggle_hk else self.toggle_hk
        error = hotkey.validate()
        if error is None and hotkey == other.hotkey:
            error = f"{hotkey} is already used for the other hotkey."
        if error:
            self._set_hotkey_error(error)
            QApplication.beep()
            # captureEnded already re-applied the previous (unchanged) hotkeys.
            return
        button.set_hotkey(hotkey)
        self._apply_hotkeys()
        self._schedule_save()

    def _set_hotkey_error(self, text: str) -> None:
        self.hotkey_error.setText(text)
        self.hotkey_error.setVisible(bool(text))

    def _update_hotkey_hint(self) -> None:
        self.hotkey_hint.setText(
            f"{self.toggle_hk.hotkey} start/stop  ·  {self.emergency_hk.hotkey} emergency stop"
        )

    def _on_hotkey(self, hotkey_id: int) -> None:
        if hotkey_id == HOTKEY_TOGGLE:
            if self._running:
                self.stop_clicking(StopReason.USER)
            else:
                self.start_clicking()
        elif hotkey_id == HOTKEY_EMERGENCY:
            self.stop_clicking(StopReason.EMERGENCY)

    # ===================================================================== #
    # Start / stop
    # ===================================================================== #
    def _build_config(self) -> ClickConfig:
        ms = self.interval_ms()
        if ms < MIN_INTERVAL_MS:
            raise ValueError(f"Interval must be at least {MIN_INTERVAL_MS} ms.")
        if ms > MAX_INTERVAL_MS:
            raise ValueError("Interval is too long.")

        fixed = None
        if self.loc_fixed.isChecked():
            x, y = self.x_spin.value(), self.y_spin.value()
            if win32.IS_WINDOWS:
                if not win32.point_on_any_monitor(x, y):
                    raise ValueError(f"Fixed position ({x}, {y}) is not on any screen.")
                left, top, _, _ = win32.virtual_screen_rect()
                if self.failsafe_check.isChecked() and abs(x - left) <= 1 and abs(y - top) <= 1:
                    raise ValueError("Fixed position is in the fail-safe corner. "
                                     "Choose another position or disable the fail-safe.")
            fixed = (x, y)

        return ClickConfig(
            button=self.button_combo.currentData(),
            double=self.mode_combo.currentData() == "double",
            interval_ms=ms,
            fixed_position=fixed,
            max_clicks=self.count_spin.value() if self.rep_count.isChecked() else 0,
            failsafe=self.failsafe_check.isChecked(),
        )

    def start_clicking(self) -> None:
        if self._running:
            return
        if self._capture_timer.isActive():
            self._toggle_capture()
        try:
            config = self._build_config()
            self.engine.start(config)
        except Exception as exc:  # validation, platform or state errors
            self._show_message(str(exc), error=True)
            QApplication.beep()
            return
        self._set_running_ui(True)
        self._show_message("Clicking…  Press "
                           f"{self.toggle_hk.hotkey} or {self.emergency_hk.hotkey} to stop.")

    def stop_clicking(self, reason: str = StopReason.USER) -> None:
        # Sets the stop flag immediately; the worker checks it before every
        # click, so no further clicks happen after this call returns.
        self.engine.stop(reason)

    def _on_engine_stopped(self, run_id: int, reason: str) -> None:
        if run_id != self.engine.run_id:
            return  # a stale notification from an older run
        self._set_running_ui(False)
        self.counter_label.setText(f"{self.engine.click_count:,}")
        self._show_message(reason, error=reason.startswith(("Error", "Emergency")))

    def _set_running_ui(self, running: bool) -> None:
        self._running = running
        self.start_btn.setEnabled(not running and self.interval_ms() >= MIN_INTERVAL_MS)
        self.stop_btn.setEnabled(running)
        for card in (self.click_card, self.interval_card, self.location_card, self.repeat_card):
            card.setEnabled(not running)
        if running:
            self.status_dot.set_color(self.colors["success"])
            self.status_text.setText("Running")
        else:
            self.status_dot.set_color("#8a8a8a")
            self.status_text.setText("Stopped")

    # ===================================================================== #
    # Misc
    # ===================================================================== #
    def _refresh(self) -> None:
        if self._running:
            self.counter_label.setText(f"{self.engine.click_count:,}")
        x, y = self._cursor_pos()
        self.cursor_label.setText(f"Mouse: {x}, {y}")

    def _show_message(self, text: str, error: bool = False) -> None:
        self.statusBar().setStyleSheet(f"color: {self.colors['danger']};" if error else "")
        self.statusBar().showMessage(text, 0 if error else 8000)

    def _on_theme_changed(self, *_args) -> None:
        if self._loading:
            return
        self._apply_theme()
        self._schedule_save()

    def _on_system_theme_changed(self, *_args) -> None:
        if self.theme_combo.currentData() == "system":
            self._apply_theme()

    def _apply_theme(self) -> None:
        self.colors = theme.apply_theme(QApplication.instance(), self.theme_combo.currentData())
        self._set_running_ui(self._running)

    def _on_always_on_top(self, checked: bool) -> None:
        if self._loading:
            return
        self.setWindowFlag(Qt.WindowStaysOnTopHint, checked)
        self.show()  # changing window flags hides the window
        self._schedule_save()

    def closeEvent(self, event: QCloseEvent) -> None:
        # Stop everything cleanly: worker thread, hotkey thread, timers.
        self._refresh_timer.stop()
        self._capture_timer.stop()
        self._save_timer.stop()
        self.engine.shutdown()
        self.hotkeys.stop()
        self._save_settings()
        super().closeEvent(event)
