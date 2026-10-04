"""BleeClicker main window: sidebar navigation, pages, live dock, tray."""

from __future__ import annotations

import json
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTime, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QCloseEvent, QColor, QCursor, QDesktopServices, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QListWidget, QMainWindow,
    QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QStackedWidget,
    QSystemTrayIcon, QTableWidget, QTimeEdit, QVBoxLayout, QWidget,
)

from . import APP_NAME, APP_VERSION, theme, win32
from .engine import (
    MAX_INTERVAL_MS, MIN_INTERVAL_MS, ClickEngine, ClickPlan, PixelTrigger, Step, StopReason,
)
from .hotkeys import Hotkey, HotkeyListener
from .icons import icon
from .overlays import MiniHud, RippleOverlay
from .settings import SETTINGS_FILE, Settings, settings_dir
from .widgets import (
    Card, ColorSwatch, CpsGraph, HotkeyButton, PowerButton, Segmented, StatTile, StatusDot,
    ToggleSwitch, repolish,
)

HK_TOGGLE, HK_EMERGENCY, HK_ADD_POINT = 1, 2, 3
DEFAULT_HOTKEYS = {HK_TOGGLE: Hotkey("F6"), HK_EMERGENCY: Hotkey("F7"), HK_ADD_POINT: Hotkey("F8")}
HOTKEY_NAMES = {HK_TOGGLE: "Start / Stop", HK_EMERGENCY: "Emergency stop", HK_ADD_POINT: "Add sequence point"}
COUNTDOWN_S = 3
WIDE_LAYOUT_MIN = 1060       # window width for two-column pages
SIDEBAR_FULL_MIN = 900       # below this the sidebar collapses to icons
CPS_HISTORY = 120            # samples kept for the graph (one per 250 ms = 30 s)

BUTTON_OPTIONS = [("Left", "left"), ("Right", "right"), ("Middle", "middle"),
                  ("Scroll ↑", "wheel_up"), ("Scroll ↓", "wheel_down")]
BUTTON_LABELS = dict((d, l) for l, d in BUTTON_OPTIONS)
MODE_CLICKS = {"single": 1, "double": 2, "triple": 3}


class _HotkeyBridge(QObject):
    """Carries hotkey presses from the listener thread to the GUI thread."""

    triggered = Signal(int)


class Page(QScrollArea):
    """A scrollable page with a header and cards that flow into 1 or 2 columns."""

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget(objectName="page")
        self.setWidget(host)
        outer = QVBoxLayout(host)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.setSpacing(16)
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(QLabel(title, objectName="pageTitle"))
        sub = QLabel(subtitle, objectName="pageSub")
        sub.setWordWrap(True)
        head.addWidget(sub)
        outer.addLayout(head)
        self.top = QVBoxLayout()          # full-width items (above the columns)
        self.top.setSpacing(14)
        outer.addLayout(self.top)
        cols = QHBoxLayout()
        cols.setSpacing(14)
        self.left, self.right = QVBoxLayout(), QVBoxLayout()
        for c in (self.left, self.right):
            c.setSpacing(14)
            cols.addLayout(c, 1)
        self._cols = cols
        outer.addLayout(cols)
        outer.addStretch(1)
        self.cards: list[tuple[QWidget, int]] = []
        self._two: bool | None = None

    def add(self, card: QWidget, column: int = 0) -> QWidget:
        self.cards.append((card, column))
        return card

    def relayout(self, two: bool) -> None:
        if two == self._two:
            return
        self._two = two
        for col in (self.left, self.right):
            while col.count():
                col.takeAt(0)
        for card, column in self.cards:
            (self.right if two and column == 1 else self.left).addWidget(card)
        self.left.addStretch(1)     # pack cards at the top of each column
        self.right.addStretch(1)
        self._cols.setStretch(1, 1 if two else 0)


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, app_icon: QIcon | None = None) -> None:
        super().__init__()
        self.settings = settings
        self.app_icon = app_icon or QIcon()
        self.colors = theme.resolve(settings.theme, settings.accent)
        self._loading = True
        self._running = False
        self._sequence: list[dict] = [dict(s) for s in settings.sequence]
        self._countdown: dict | None = None
        self._cps_samples: deque[tuple[float, int]] = deque(maxlen=12)
        self._cps_history: deque[float] = deque([0.0] * CPS_HISTORY, maxlen=CPS_HISTORY)
        self._cps_now = 0.0
        self._last_ripple = 0
        self._schedule_fired = ""
        self._run_started_wall = 0.0

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(self.app_icon)
        self.setMinimumSize(560, 520)

        # Core services
        self.engine = ClickEngine()
        self.engine.stopped.connect(self._on_engine_stopped)
        self._bridge = _HotkeyBridge()
        self._bridge.triggered.connect(self._on_hotkey)
        self.hotkeys = HotkeyListener(self._bridge.triggered.emit)
        self.ripple = RippleOverlay()
        self.hud = MiniHud()
        self.hud.activated.connect(self._show_from_background)

        self._build_ui()
        self._build_tray()
        self._load_settings_into_ui()
        self._loading = False
        self._apply_theme()

        self._save_timer = QTimer(self, singleShot=True, interval=500)
        self._save_timer.timeout.connect(self._save_settings)
        self._tick = 0
        self._refresh_timer = QTimer(self, interval=33)
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start()
        self._countdown_timer = QTimer(self, interval=1000)
        self._countdown_timer.timeout.connect(self._countdown_tick)
        self._schedule_timer = QTimer(self, interval=1000)
        self._schedule_timer.timeout.connect(self._check_schedule)
        self._schedule_timer.start()

        self.hotkeys.start()
        self._apply_hotkeys()
        self._update_all_hints()
        self._set_running_ui(False)

        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda *_: self.theme_seg.value() == "system" and self._apply_theme())

        if not win32.IS_WINDOWS:
            self._toast("Clicking and global hotkeys require Windows.", error=True)

    # ===================================================================== #
    # UI construction
    # ===================================================================== #
    def _build_ui(self) -> None:
        root = QWidget(objectName="content")
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._build_sidebar())

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.stack = QStackedWidget()
        self.pages = [
            self._page_clicker(), self._page_sequence(), self._page_smart(),
            self._page_profiles(), self._page_stats(), self._page_settings(),
        ]
        for p in self.pages:
            self.stack.addWidget(p)
        right.addWidget(self.stack, 1)
        right.addWidget(self._build_dock())
        h.addLayout(right, 1)
        self._relayout(force=True)
        self.resize(1120, 760)

    # -- sidebar ----------------------------------------------------------- #
    NAV = [("clicker", "Clicker"), ("sequence", "Sequence"), ("smart", "Smart Guards"),
           ("profiles", "Profiles"), ("stats", "Live Stats"), ("settings", "Settings")]

    def _build_sidebar(self) -> QFrame:
        self.sidebar = QFrame(objectName="sidebar")
        lay = QVBoxLayout(self.sidebar)
        lay.setContentsMargins(14, 18, 14, 14)
        lay.setSpacing(4)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        self.logo = QLabel()
        self.logo.setPixmap(self.app_icon.pixmap(34, 34))
        brand.addWidget(self.logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.brand_label = QLabel(APP_NAME, objectName="brand")
        self.brand_sub = QLabel(f"v{APP_VERSION} · smart auto clicker", objectName="brandSub")
        names.addWidget(self.brand_label)
        names.addWidget(self.brand_sub)
        brand.addLayout(names, 1)
        lay.addLayout(brand)
        lay.addSpacing(18)

        self.nav_buttons: list[QPushButton] = []
        for i, (key, label) in enumerate(self.NAV):
            b = QPushButton(label, objectName="nav")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(label)
            b.setProperty("navKey", key)
            b.setProperty("navLabel", label)
            b.clicked.connect(lambda _=False, i=i: self._go(i))
            self.nav_buttons.append(b)
            lay.addWidget(b)
        lay.addStretch(1)

        self.side_hint = QLabel(objectName="hint")
        self.side_hint.setWordWrap(True)
        lay.addWidget(self.side_hint)
        return self.sidebar

    def _go(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        self._update_nav_icons()
        if not self._loading:
            self.settings.last_page = index
            self._schedule_save()

    def _update_nav_icons(self) -> None:
        for b in self.nav_buttons:
            color = self.colors["accent"] if b.isChecked() else self.colors["subtext"]
            b.setIcon(icon(b.property("navKey"), color))

    # -- common helpers ---------------------------------------------------- #
    def _spin(self, lo: int, hi: int, tip: str = "", suffix: str = "") -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setButtonSymbols(QAbstractSpinBox.NoButtons)
        s.setSuffix(suffix)
        s.setToolTip((tip + "\n" if tip else "") + "Type a value, or use the mouse wheel / ↑ ↓ keys.")
        s.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        s.valueChanged.connect(self._changed)
        return s

    def _toggle(self, text: str, tip: str) -> ToggleSwitch:
        t = ToggleSwitch(text)
        t.setToolTip(tip)
        t.toggled.connect(self._changed)
        return t

    def _seg(self, options, tips=None) -> Segmented:
        s = Segmented(options, tips)
        s.changed.connect(self._changed)
        return s

    def _labeled(self, label: str, widget: QWidget, tip: str = "") -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        lab = QLabel(label, objectName="subtle")
        lab.setMinimumWidth(110)
        if tip:
            lab.setToolTip(tip)
        row.addWidget(lab)
        row.addWidget(widget, 1)
        return row

    def _icon_button(self, text: str, icon_name: str, tip: str = "", name: str = "") -> QPushButton:
        b = QPushButton(text)
        if name:
            b.setObjectName(name)
        b.setProperty("iconName", icon_name)
        b.setCursor(Qt.PointingHandCursor)
        if tip:
            b.setToolTip(tip)
        return b

    # -- Clicker page -------------------------------------------------------- #
    def _page_clicker(self) -> Page:
        page = Page("Clicker", "What to click, how fast, and where. Press the power button "
                               "(or your hotkey) to start.")

        action = Card("Action", "Mouse button and click type")
        self.button_seg = self._seg(BUTTON_OPTIONS, {
            "wheel_up": "Scroll the mouse wheel up instead of clicking.",
            "wheel_down": "Scroll the mouse wheel down instead of clicking."})
        self.button_seg.changed.connect(self._update_all_hints)
        self.mode_seg = self._seg([("Single", "single"), ("Double", "double"), ("Triple", "triple")], {
            "single": "One click per action.",
            "double": "A double click per action (counts as one action).",
            "triple": "A triple click per action, e.g. to select a paragraph."})
        action.body.addWidget(self.button_seg)
        action.body.addWidget(self.mode_seg)
        page.add(action, 0)

        speed = Card("Speed", "Set an interval, or type clicks per second directly")
        self.speed_seg = self._seg([("Interval", "interval"), ("Clicks / second", "cps")])
        self.speed_seg.changed.connect(self._update_speed_visibility)
        speed.body.addWidget(self.speed_seg)
        self.interval_box = QWidget()
        grid = QGridLayout(self.interval_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)
        self.hours_spin = self._spin(0, 23, "Hours between clicks.")
        self.minutes_spin = self._spin(0, 59, "Minutes between clicks.")
        self.seconds_spin = self._spin(0, 59, "Seconds between clicks.")
        self.ms_spin = self._spin(0, 999, "Milliseconds between clicks (minimum total: 1 ms).")
        for col, (lab, sp) in enumerate((("Hours", self.hours_spin), ("Minutes", self.minutes_spin),
                                          ("Seconds", self.seconds_spin), ("Milliseconds", self.ms_spin))):
            grid.addWidget(QLabel(lab, objectName="hint"), 0, col)
            grid.addWidget(sp, 1, col)
        speed.body.addWidget(self.interval_box)
        self.cps_spin = QDoubleSpinBox()
        self.cps_spin.setRange(0.01, 1000.0)
        self.cps_spin.setDecimals(2)
        self.cps_spin.setSuffix("  clicks / second")
        self.cps_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.cps_spin.setToolTip("How many click actions per second (0.01 – 1000).")
        self.cps_spin.valueChanged.connect(self._changed)
        speed.body.addWidget(self.cps_spin)
        self.speed_hint = QLabel(objectName="hint")
        speed.body.addWidget(self.speed_hint)
        page.add(speed, 0)

        target = Card("Target", "Where the clicks land")
        self.target_seg = self._seg([("Cursor", "current"), ("Fixed point", "fixed"), ("Sequence", "sequence")], {
            "current": "Click wherever the pointer is at the time of each click.",
            "fixed": "Move the pointer to an exact screen point before every click.",
            "sequence": "Click a list of points in order (edit it on the Sequence page)."})
        self.target_seg.changed.connect(self._update_target_visibility)
        target.body.addWidget(self.target_seg)
        self.fixed_box = QWidget()
        fl = QHBoxLayout(self.fixed_box)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(8)
        self.x_spin = self._spin(-32768, 32767, "Horizontal screen coordinate (physical pixels).")
        self.y_spin = self._spin(-32768, 32767, "Vertical screen coordinate (physical pixels).")
        self.x_spin.setPrefix("X  ")
        self.y_spin.setPrefix("Y  ")
        self.capture_btn = self._icon_button("Pick", "crosshair",
                                             f"{COUNTDOWN_S}-second countdown: point at the target and "
                                             "its position is recorded.")
        self.capture_btn.clicked.connect(lambda: self._start_countdown("position", self.capture_btn))
        fl.addWidget(self.x_spin, 1)
        fl.addWidget(self.y_spin, 1)
        fl.addWidget(self.capture_btn)
        target.body.addWidget(self.fixed_box)
        self.seq_box = QWidget()
        sl = QHBoxLayout(self.seq_box)
        sl.setContentsMargins(0, 0, 0, 0)
        self.seq_summary = QLabel(objectName="subtle")
        sl.addWidget(self.seq_summary, 1)
        open_seq = QPushButton("Edit sequence →", objectName="ghost")
        open_seq.setCursor(Qt.PointingHandCursor)
        open_seq.clicked.connect(lambda: self._go(1))
        sl.addWidget(open_seq)
        target.body.addWidget(self.seq_box)
        self.cursor_label = QLabel(objectName="hint")
        target.body.addWidget(self.cursor_label)
        page.add(target, 1)

        stop = Card("Stop after", "Run forever, or finish automatically")
        self.stop_seg = self._seg([("Never", "never"), ("Clicks", "clicks"), ("Time", "time")])
        self.stop_seg.changed.connect(self._update_stop_visibility)
        stop.body.addWidget(self.stop_seg)
        self.stop_clicks_spin = self._spin(1, 100_000_000, "Stop after this many click actions.", "  clicks")
        self.stop_clicks_spin.setGroupSeparatorShown(True)
        self.stop_seconds_spin = self._spin(1, 86_400, "Stop after clicking for this long.", "  seconds")
        stop.body.addWidget(self.stop_clicks_spin)
        stop.body.addWidget(self.stop_seconds_spin)
        page.add(stop, 1)

        human = Card("Humanize", "Natural-looking variation. Leave at 0 for machine precision.")
        self.jitter_spin = self._spin(0, 90, "Randomly vary every delay by up to ± this percentage.", " %")
        self.scatter_spin = self._spin(0, 500, "Fixed points / sequence steps land at a random spot within "
                                               "this radius.", " px")
        self.hold_spin = self._spin(0, 10_000, "Hold each button press down this long (0 = instant tap). "
                                               "Great for games that ignore very short clicks.", " ms")
        human.body.addLayout(self._labeled("Timing jitter ±", self.jitter_spin))
        human.body.addLayout(self._labeled("Position scatter", self.scatter_spin))
        human.body.addLayout(self._labeled("Hold duration", self.hold_spin))
        page.add(human, 0)
        return page

    # -- Sequence page ------------------------------------------------------- #
    def _page_sequence(self) -> Page:
        page = Page("Sequence", "Click several points in order, each with its own button and delay. "
                                "Select “Sequence” as the target on the Clicker page to use it.")
        steps = Card("Steps", None)
        self.seq_table = QTableWidget(0, 5)
        self.seq_table.setHorizontalHeaderLabels(["X", "Y", "BUTTON", "CLICKS", "DELAY AFTER (MS)"])
        self.seq_table.verticalHeader().setDefaultSectionSize(40)
        self.seq_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.seq_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.seq_table.setSelectionMode(QTableWidget.SingleSelection)
        self.seq_table.setMinimumHeight(260)
        self.seq_table.setShowGrid(False)
        steps.body.addWidget(self.seq_table)
        row = QHBoxLayout()
        self.seq_add_btn = self._icon_button("Add at pointer", "plus",
                                             f"{COUNTDOWN_S}-second countdown, then the point under the "
                                             "pointer is added.", "primary")
        self.seq_add_btn.clicked.connect(lambda: self._start_countdown("sequence", self.seq_add_btn))
        up = self._icon_button("", "up", "Move the selected step up")
        down = self._icon_button("", "down", "Move the selected step down")
        rem = self._icon_button("Remove", "trash", "Remove the selected step")
        clear = self._icon_button("Clear all", "reset", "Remove every step", "danger")
        up.clicked.connect(lambda: self._seq_move(-1))
        down.clicked.connect(lambda: self._seq_move(1))
        rem.clicked.connect(self._seq_remove)
        clear.clicked.connect(self._seq_clear)
        for w in (self.seq_add_btn, up, down, rem):
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(clear)
        steps.body.addLayout(row)
        self.seq_tip = QLabel(objectName="hint")
        self.seq_tip.setWordWrap(True)
        steps.body.addWidget(self.seq_tip)
        page.top.addWidget(steps)

        play = Card("Playback", "How many times to run through the list")
        self.loops_spin = self._spin(0, 1_000_000, "Number of passes through the list (0 = forever).", "  loops")
        self.loops_spin.setSpecialValueText("Forever")
        play.body.addLayout(self._labeled("Repeat", self.loops_spin))
        self.cycle_hint = QLabel(objectName="hint")
        play.body.addWidget(self.cycle_hint)
        page.add(play, 0)
        return page

    # -- Smart guards page -------------------------------------------------- #
    def _page_smart(self) -> Page:
        page = Page("Smart Guards", "Conditions that decide when clicks may happen, and safety nets "
                                    "that stop them. These rarely come together in one auto clicker.")

        wl = Card("Window Lock", "Only click while a chosen app is in the foreground. Switch away and "
                                 "BleeClicker pauses itself; switch back and it resumes.")
        self.wl_toggle = self._toggle("Enable Window Lock", "Pause automatically whenever another app is active.")
        wl.body.addWidget(self.wl_toggle)
        row = QHBoxLayout()
        self.wl_label = QLabel(objectName="badge")
        row.addWidget(self.wl_label)
        row.addStretch(1)
        self.wl_pick = self._icon_button("Pick app", "window",
                                         f"{COUNTDOWN_S}-second countdown: click into the app you want "
                                         "to lock to.")
        self.wl_pick.clicked.connect(lambda: self._start_countdown("window", self.wl_pick))
        row.addWidget(self.wl_pick)
        wl.body.addLayout(row)
        page.add(wl, 0)

        px = Card("Pixel Trigger", "Watch one screen pixel and click only when it shows a colour "
                                   "(e.g. a button lighting up), or only when that colour goes away.")
        self.px_toggle = self._toggle("Enable Pixel Trigger", "Gate every click on a pixel's colour.")
        px.body.addWidget(self.px_toggle)
        prow = QHBoxLayout()
        prow.setSpacing(8)
        self.px_swatch = ColorSwatch()
        self.px_label = QLabel(objectName="subtle")
        self.px_pick = self._icon_button("Pick pixel", "pixel",
                                         f"{COUNTDOWN_S}-second countdown: point at the pixel to watch; "
                                         "its position and current colour are recorded.")
        self.px_pick.clicked.connect(lambda: self._start_countdown("pixel", self.px_pick))
        prow.addWidget(self.px_swatch)
        prow.addWidget(self.px_label, 1)
        prow.addWidget(self.px_pick)
        px.body.addLayout(prow)
        self.px_mode = self._seg([("Click when it matches", "match"), ("Click when it differs", "differ")])
        px.body.addWidget(self.px_mode)
        self.px_tol = self._spin(0, 255, "How different each RGB channel may be and still count as a match.")
        px.body.addLayout(self._labeled("Colour tolerance", self.px_tol))
        self._px_pos = (0, 0)
        self._px_rgb = "#ffffff"
        page.add(px, 0)

        safety = Card("Safety nets", None)
        self.takeover_toggle = self._toggle(
            "Smart Takeover", "Fixed point / sequence: if you grab the mouse and move it away from where "
                              "BleeClicker put it, clicking stops instantly.")
        self.moving_toggle = self._toggle(
            "Pause while I move the mouse", "Cursor target: hold clicks while you are moving the mouse, "
                                            "resume once it's still.")
        self.failsafe_toggle = self._toggle(
            "Fail-safe corner", "Slam the pointer into the top-left corner of the screen to stop at once.")
        for t in (self.takeover_toggle, self.moving_toggle, self.failsafe_toggle):
            safety.body.addWidget(t)
        protect = QLabel("✓  Self-protection is always on: BleeClicker never clicks its own windows, "
                         "so it can't switch itself off or change your settings by accident.",
                         objectName="ok")
        protect.setWordWrap(True)
        safety.body.addWidget(protect)
        page.add(safety, 1)

        timing = Card("Start timing", None)
        self.delay_spin = self._spin(0, 60, "Count down before the first click, so you can move to "
                                            "the target window.", "  s countdown")
        self.delay_spin.setSpecialValueText("Start instantly")
        timing.body.addLayout(self._labeled("Start delay", self.delay_spin))
        self.sched_toggle = self._toggle("Scheduled start", "Start clicking automatically at a time of day "
                                                            "(BleeClicker must be running).")
        self.sched_time = QTimeEdit()
        self.sched_time.setDisplayFormat("HH:mm")
        self.sched_time.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.sched_time.timeChanged.connect(self._changed)
        srow = QHBoxLayout()
        srow.addWidget(self.sched_toggle, 1)
        srow.addWidget(self.sched_time)
        timing.body.addLayout(srow)
        page.add(timing, 1)
        return page

    # -- Profiles page ------------------------------------------------------ #
    def _page_profiles(self) -> Page:
        page = Page("Profiles", "Save complete setups (speed, target, sequence, humanize and smart "
                                "guards) and switch between them in one click.")
        card = Card("Saved profiles", None)
        self.profile_list = QListWidget()
        self.profile_list.setMinimumHeight(240)
        self.profile_list.itemDoubleClicked.connect(lambda *_: self._profile_load())
        card.body.addWidget(self.profile_list)
        row = QHBoxLayout()
        save = self._icon_button("Save current as…", "save", "Save the current setup as a new profile.", "primary")
        load = self._icon_button("Load", "load", "Apply the selected profile (double-click works too).")
        upd = self._icon_button("Update", "edit", "Overwrite the selected profile with the current setup.")
        dele = self._icon_button("Delete", "trash", "Delete the selected profile.", "danger")
        save.clicked.connect(self._profile_save_as)
        load.clicked.connect(self._profile_load)
        upd.clicked.connect(self._profile_update)
        dele.clicked.connect(self._profile_delete)
        for w in (save, load, upd):
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(dele)
        card.body.addLayout(row)
        page.top.addWidget(card)

        share = Card("Share", "Export your profiles to a file, or import someone else's.")
        r2 = QHBoxLayout()
        exp = self._icon_button("Export…", "save", "Save all profiles to a .json file.")
        imp = self._icon_button("Import…", "load", "Add profiles from a .json file.")
        exp.clicked.connect(self._profiles_export)
        imp.clicked.connect(self._profiles_import)
        r2.addWidget(exp)
        r2.addWidget(imp)
        r2.addStretch(1)
        share.body.addLayout(r2)
        page.add(share, 0)
        return page

    # -- Stats page --------------------------------------------------------- #
    def _page_stats(self) -> Page:
        page = Page("Live Stats", "Measured, not estimated: real clicks per second and how precisely "
                                  "BleeClicker hits its schedule.")
        tiles = QGridLayout()
        tiles.setSpacing(12)
        self.t_cps = StatTile("Live CPS", "0.0", "Clicks per second measured over the last second.")
        self.t_session = StatTile("Session clicks", "0", "Click actions in the current / last run.")
        self.t_time = StatTile("Run time", "0:00", "How long the current / last run has been clicking.")
        self.t_acc = StatTile("Timing accuracy", "–", "Average lateness of each click versus its "
                                                      "scheduled time. Lower is better.")
        self.t_life = StatTile("Lifetime clicks", "0", "Every click BleeClicker has ever made for you.")
        self.t_runs = StatTile("Runs", "0", "Number of times you've started clicking.")
        for i, t in enumerate((self.t_cps, self.t_session, self.t_time, self.t_acc, self.t_life, self.t_runs)):
            tiles.addWidget(t, i // 3, i % 3)
        holder = QWidget()
        holder.setLayout(tiles)
        page.top.addWidget(holder)
        graph_card = Card("Clicks per second · last 30 seconds", None)
        self.big_graph = CpsGraph()
        self.big_graph.setMinimumHeight(240)
        graph_card.body.addWidget(self.big_graph)
        page.top.addWidget(graph_card)
        return page

    # -- Settings page ------------------------------------------------------ #
    def _page_settings(self) -> Page:
        page = Page("Settings", "Hotkeys, look & feel and app behaviour.")

        hk = Card("Global hotkeys", "Work in any app. Click a key, then press the new combination "
                                    "(Esc cancels).")
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        self.hk_buttons: dict[int, HotkeyButton] = {}
        for hid, hk_default in DEFAULT_HOTKEYS.items():
            b = HotkeyButton(hk_default)
            b.captureStarted.connect(self._suspend_hotkeys)
            b.captureEnded.connect(self._apply_hotkeys)
            b.captured.connect(lambda hotkey, hid=hid: self._on_hotkey_captured(hid, hotkey))
            self.hk_buttons[hid] = b
            form.addRow(HOTKEY_NAMES[hid], b)
        hk.body.addLayout(form)
        self.activation_seg = self._seg([("Press to toggle", "toggle"), ("Hold to click", "hold")], {
            "toggle": "Press the Start/Stop hotkey once to start, again to stop.",
            "hold": "Clicks only while you hold the Start/Stop hotkey down, like a rapid-fire trigger."})
        self.activation_seg.changed.connect(self._update_all_hints)
        hk.body.addLayout(self._labeled("Activation", self.activation_seg))
        self.hotkey_error = QLabel(objectName="error")
        self.hotkey_error.setWordWrap(True)
        self.hotkey_error.hide()
        hk.body.addWidget(self.hotkey_error)
        page.add(hk, 0)

        look = Card("Appearance", None)
        self.theme_seg = self._seg([("System", "system"), ("Light", "light"), ("Dark", "dark")])
        self.theme_seg.changed.connect(lambda *_: self._loading or self._apply_theme())
        look.body.addLayout(self._labeled("Theme", self.theme_seg))
        acc_row = QHBoxLayout()
        acc_row.setSpacing(10)
        self.accent_buttons: dict[str, QPushButton] = {}
        for key, (label, a1, a2, _) in theme.ACCENTS.items():
            b = QPushButton(objectName="accentSwatch")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setToolTip(label)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"QPushButton#accentSwatch {{ background: qlineargradient(x1:0, y1:0, x2:1, "
                            f"y2:1, stop:0 {a1}, stop:1 {a2}); }}")
            b.clicked.connect(lambda _=False, k=key: self._set_accent(k))
            self.accent_buttons[key] = b
            acc_row.addWidget(b)
        acc_row.addStretch(1)
        lab = QLabel("Accent", objectName="subtle")
        lab.setMinimumWidth(110)
        acc_wrap = QHBoxLayout()
        acc_wrap.addWidget(lab)
        acc_wrap.addLayout(acc_row, 1)
        look.body.addLayout(acc_wrap)
        page.add(look, 1)

        fb = Card("Feedback", None)
        self.ripple_toggle = self._toggle("Click visualizer", "Show a ripple on screen wherever a click lands "
                                                             "(it never blocks the clicks).")
        self.sounds_toggle = self._toggle("Sound cues", "Play a short sound when clicking starts and stops.")
        self.hud_toggle = self._toggle("Mini HUD while clicking", "A small floating pill with live status, "
                                                                 "CPS and click count.")
        for t in (self.ripple_toggle, self.sounds_toggle, self.hud_toggle):
            fb.body.addWidget(t)
        page.add(fb, 1)

        win = Card("Window", None)
        self.ontop_toggle = self._toggle("Keep window on top", "Keep BleeClicker above other windows.")
        self.ontop_toggle.toggled.connect(self._on_always_on_top)
        self.tray_toggle = self._toggle("Minimize to tray", "Minimizing hides BleeClicker to the "
                                                            "notification area. Hotkeys keep working.")
        win.body.addWidget(self.ontop_toggle)
        win.body.addWidget(self.tray_toggle)
        page.add(win, 0)

        data = Card("Data", f"Settings are stored in {SETTINGS_FILE}")
        drow = QHBoxLayout()
        opn = self._icon_button("Open folder", "folder", "Open the settings folder.")
        opn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(settings_dir()))))
        rst = self._icon_button("Reset everything", "reset", "Restore all defaults (profiles are kept).", "danger")
        rst.clicked.connect(self._reset_settings)
        drow.addWidget(opn)
        drow.addStretch(1)
        drow.addWidget(rst)
        data.body.addLayout(drow)
        page.add(data, 0)
        return page

    # -- Dock --------------------------------------------------------------- #
    def _build_dock(self) -> QFrame:
        dock = QFrame(objectName="dock")
        lay = QHBoxLayout(dock)
        lay.setContentsMargins(22, 12, 26, 12)
        lay.setSpacing(18)
        self.power = PowerButton()
        self.power.setToolTip("Start / stop clicking")
        self.power.clicked.connect(self._power_clicked)
        lay.addWidget(self.power)

        col = QVBoxLayout()
        col.setSpacing(3)
        line = QHBoxLayout()
        line.setSpacing(8)
        self.status_dot = StatusDot()
        line.addWidget(self.status_dot)
        self.status_text = QLabel("Ready", objectName="statusText")
        line.addWidget(self.status_text)
        line.addStretch(1)
        col.addLayout(line)
        self.status_detail = QLabel(objectName="subtle")
        self.status_detail.setWordWrap(True)
        col.addWidget(self.status_detail)
        self.toast = QLabel(objectName="hint")
        self.toast.setWordWrap(True)
        col.addWidget(self.toast)
        lay.addLayout(col, 1)

        self.mini_graph = CpsGraph(compact=True)
        self.mini_graph.setFixedSize(200, 56)
        self.mini_graph.setToolTip("Live clicks per second")
        lay.addWidget(self.mini_graph)

        for attr, label in (("dock_cps", "CPS"), ("dock_clicks", "CLICKS")):
            box = QVBoxLayout()
            box.setSpacing(0)
            l1 = QLabel(label, objectName="tileLabel")
            l1.setAlignment(Qt.AlignRight)
            l2 = QLabel("0", objectName="big")
            l2.setAlignment(Qt.AlignRight)
            l2.setMinimumWidth(90)
            box.addWidget(l1)
            box.addWidget(l2)
            setattr(self, attr, l2)
            lay.addLayout(box)
        self._toast_timer = QTimer(self, singleShot=True, interval=7000)
        self._toast_timer.timeout.connect(lambda: self.toast.setText(""))
        return dock

    # -- Tray --------------------------------------------------------------- #
    def _build_tray(self) -> None:
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self.app_icon, self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        self.tray_toggle_action = QAction("Start clicking", menu)
        self.tray_toggle_action.triggered.connect(self._power_clicked)
        show = QAction(f"Show {APP_NAME}", menu)
        show.triggered.connect(self._show_from_background)
        quit_ = QAction("Quit", menu)
        quit_.triggered.connect(self._quit)
        menu.addAction(self.tray_toggle_action)
        menu.addAction(show)
        menu.addSeparator()
        menu.addAction(quit_)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: reason == QSystemTrayIcon.Trigger and self._show_from_background())
        self._tray_menu = menu
        self.tray.show()

    def _show_from_background(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit(self) -> None:
        self.close()

    # -- responsive layout --------------------------------------------------- #
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self, force: bool = False) -> None:
        w = self.width()
        two = w >= WIDE_LAYOUT_MIN
        for p in self.pages:
            p.relayout(two)
        full = w >= SIDEBAR_FULL_MIN
        if force or getattr(self, "_sidebar_full", None) != full:
            self._sidebar_full = full
            self.sidebar.setFixedWidth(224 if full else 68)
            self.brand_label.setVisible(full)
            self.brand_sub.setVisible(full)
            self.side_hint.setVisible(full)
            for b in self.nav_buttons:
                b.setText(b.property("navLabel") if full else "")
        self.mini_graph.setVisible(w >= 820)

    # ===================================================================== #
    # Settings <-> UI
    # ===================================================================== #
    def _load_settings_into_ui(self) -> None:
        s = self.settings
        was_loading, self._loading = self._loading, True
        self.button_seg.set_value(s.button)
        self.mode_seg.set_value(s.click_mode)
        self.speed_seg.set_value(s.speed_mode)
        self.hours_spin.setValue(s.hours)
        self.minutes_spin.setValue(s.minutes)
        self.seconds_spin.setValue(s.seconds)
        self.ms_spin.setValue(s.milliseconds)
        self.cps_spin.setValue(s.cps)
        self.target_seg.set_value(s.target_mode)
        self.x_spin.setValue(s.fixed_x)
        self.y_spin.setValue(s.fixed_y)
        self._sequence = [dict(step) for step in s.sequence]
        self.loops_spin.setValue(s.sequence_loops)
        self.stop_seg.set_value(s.stop_mode)
        self.stop_clicks_spin.setValue(s.stop_clicks)
        self.stop_seconds_spin.setValue(s.stop_seconds)
        self.jitter_spin.setValue(s.jitter_pct)
        self.scatter_spin.setValue(s.scatter_px)
        self.hold_spin.setValue(s.hold_ms)
        self.delay_spin.setValue(s.start_delay_s)
        self.sched_toggle.setChecked(s.schedule_enabled)
        self.sched_time.setTime(QTime.fromString(s.schedule_time, "HH:mm"))
        self.activation_seg.set_value(s.activation)
        self.failsafe_toggle.setChecked(s.failsafe)
        self.takeover_toggle.setChecked(s.takeover_stop)
        self.moving_toggle.setChecked(s.pause_while_moving)
        self.wl_toggle.setChecked(s.window_lock_enabled)
        self._wl_exe = s.window_lock_exe
        self.px_toggle.setChecked(s.pixel_enabled)
        self._px_pos = (s.pixel_x, s.pixel_y)
        self._px_rgb = s.pixel_rgb.lower()
        self.px_tol.setValue(s.pixel_tolerance)
        self.px_mode.set_value(s.pixel_mode)
        self.theme_seg.set_value(s.theme)
        self.accent_buttons.get(s.accent, self.accent_buttons["blee"]).setChecked(True)
        self.ripple_toggle.setChecked(s.ripple)
        self.sounds_toggle.setChecked(s.sounds)
        self.hud_toggle.setChecked(s.mini_hud)
        self.ontop_toggle.setChecked(s.always_on_top)
        self.tray_toggle.setChecked(s.minimize_to_tray)

        hotkeys = {HK_TOGGLE: s.hotkey_toggle, HK_EMERGENCY: s.hotkey_emergency, HK_ADD_POINT: s.hotkey_add_point}
        parsed = {hid: self._parse_hotkey(text, DEFAULT_HOTKEYS[hid]) for hid, text in hotkeys.items()}
        if len(set(parsed.values())) != len(parsed):
            parsed = dict(DEFAULT_HOTKEYS)
        for hid, hk in parsed.items():
            self.hk_buttons[hid].set_hotkey(hk)

        if s.always_on_top:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        if s.window_w and s.window_h:
            self.resize(max(s.window_w, self.minimumWidth()), max(s.window_h, self.minimumHeight()))
        if s.window_x is not None and s.window_y is not None:
            self._restore_position(s.window_x, s.window_y)
        self._refresh_profiles()
        self._rebuild_seq_table()
        self._update_px_label()
        self._update_wl_label()
        self._update_speed_visibility()
        self._update_target_visibility()
        self._update_stop_visibility()
        self._go(min(s.last_page, len(self.pages) - 1))
        self._loading = was_loading

    def _restore_position(self, x: int, y: int) -> None:
        for screen in QGuiApplication.screens():
            if screen.availableGeometry().adjusted(0, 0, -100, -60).contains(x + 50, y + 30):
                self.move(x, y)
                return

    @staticmethod
    def _parse_hotkey(text: str, fallback: Hotkey) -> Hotkey:
        try:
            hk = Hotkey.parse(text)
        except ValueError:
            return fallback
        return fallback if hk.validate() else hk

    def _collect_settings(self) -> Settings:
        s = self.settings
        s.button = self.button_seg.value()
        s.click_mode = self.mode_seg.value()
        s.speed_mode = self.speed_seg.value()
        s.hours, s.minutes = self.hours_spin.value(), self.minutes_spin.value()
        s.seconds, s.milliseconds = self.seconds_spin.value(), self.ms_spin.value()
        s.cps = round(self.cps_spin.value(), 2)
        s.target_mode = self.target_seg.value()
        s.fixed_x, s.fixed_y = self.x_spin.value(), self.y_spin.value()
        s.sequence = [dict(step) for step in self._sequence]
        s.sequence_loops = self.loops_spin.value()
        s.stop_mode = self.stop_seg.value()
        s.stop_clicks = self.stop_clicks_spin.value()
        s.stop_seconds = self.stop_seconds_spin.value()
        s.jitter_pct, s.scatter_px, s.hold_ms = self.jitter_spin.value(), self.scatter_spin.value(), self.hold_spin.value()
        s.start_delay_s = self.delay_spin.value()
        s.schedule_enabled = self.sched_toggle.isChecked()
        s.schedule_time = self.sched_time.time().toString("HH:mm")
        s.activation = self.activation_seg.value()
        s.failsafe = self.failsafe_toggle.isChecked()
        s.takeover_stop = self.takeover_toggle.isChecked()
        s.pause_while_moving = self.moving_toggle.isChecked()
        s.window_lock_enabled = self.wl_toggle.isChecked()
        s.window_lock_exe = self._wl_exe
        s.pixel_enabled = self.px_toggle.isChecked()
        s.pixel_x, s.pixel_y = self._px_pos
        s.pixel_rgb = self._px_rgb
        s.pixel_tolerance = self.px_tol.value()
        s.pixel_mode = self.px_mode.value()
        s.theme = self.theme_seg.value()
        s.accent = next((k for k, b in self.accent_buttons.items() if b.isChecked()), "blee")
        s.ripple = self.ripple_toggle.isChecked()
        s.sounds = self.sounds_toggle.isChecked()
        s.mini_hud = self.hud_toggle.isChecked()
        s.always_on_top = self.ontop_toggle.isChecked()
        s.minimize_to_tray = self.tray_toggle.isChecked()
        s.hotkey_toggle = str(self.hk_buttons[HK_TOGGLE].hotkey)
        s.hotkey_emergency = str(self.hk_buttons[HK_EMERGENCY].hotkey)
        s.hotkey_add_point = str(self.hk_buttons[HK_ADD_POINT].hotkey)
        if not self.isMinimized() and not self.isMaximized():
            g = self.geometry()
            s.window_x, s.window_y, s.window_w, s.window_h = self.x(), self.y(), g.width(), g.height()
        return s

    def _changed(self, *_args) -> None:
        if self._loading:
            return
        self._update_all_hints()
        self._schedule_save()

    def _schedule_save(self) -> None:
        if not self._loading and hasattr(self, "_save_timer"):
            self._save_timer.start()

    def _save_settings(self) -> None:
        try:
            self._collect_settings().save()
        except OSError as exc:
            self._toast(f"Could not save settings: {exc}", error=True)

    def _reset_settings(self) -> None:
        if QMessageBox.question(self, APP_NAME, "Reset all settings to their defaults?\n"
                                                "Your saved profiles and lifetime stats are kept.") != QMessageBox.Yes:
            return
        old = self.settings
        fresh = Settings()
        fresh.profiles = old.profiles
        fresh.stats_lifetime_clicks, fresh.stats_runs, fresh.stats_longest_s = (
            old.stats_lifetime_clicks, old.stats_runs, old.stats_longest_s)
        self.settings = fresh
        self._load_settings_into_ui()
        self._apply_theme()
        self._apply_hotkeys()
        self._update_all_hints()
        self._save_settings()
        self._toast("Settings reset to defaults.")

    # ===================================================================== #
    # Visibility / hints
    # ===================================================================== #
    def interval_ms(self) -> int:
        if self.speed_seg.value() == "cps":
            return max(MIN_INTERVAL_MS, round(1000.0 / self.cps_spin.value()))
        return (self.hours_spin.value() * 3_600_000 + self.minutes_spin.value() * 60_000
                + self.seconds_spin.value() * 1000 + self.ms_spin.value())

    def _update_speed_visibility(self, *_):
        cps = self.speed_seg.value() == "cps"
        self.interval_box.setVisible(not cps)
        self.cps_spin.setVisible(cps)
        self._update_all_hints()

    def _update_target_visibility(self, *_):
        mode = self.target_seg.value()
        self.fixed_box.setVisible(mode == "fixed")
        self.seq_box.setVisible(mode == "sequence")
        self._update_all_hints()

    def _update_stop_visibility(self, *_):
        mode = self.stop_seg.value()
        self.stop_clicks_spin.setVisible(mode == "clicks")
        self.stop_seconds_spin.setVisible(mode == "time")

    def _update_all_hints(self, *_):
        ms = self.interval_ms()
        if ms < MIN_INTERVAL_MS:
            self.speed_hint.setObjectName("error")
            self.speed_hint.setText(f"Interval must be at least {MIN_INTERVAL_MS} ms.")
        else:
            rate = 1000.0 / ms
            rate_txt = f"{rate:,.2f} clicks/s" if rate >= 1 else f"{rate * 60:,.2f} clicks/min"
            self.speed_hint.setObjectName("hint")
            self.speed_hint.setText(f"One action every {ms:,} ms  ·  {rate_txt}")
        repolish(self.speed_hint)

        wheel = self.button_seg.value() in ("wheel_up", "wheel_down")
        for data, label in (("single", "1 notch" if wheel else "Single"),
                            ("double", "2 notches" if wheel else "Double"),
                            ("triple", "3 notches" if wheel else "Triple")):
            self.mode_seg.button(data).setText(label)

        n = len(self._sequence)
        total = sum(s["delay_ms"] for s in self._sequence)
        self.seq_summary.setText(f"{n} step{'s' if n != 1 else ''} · {total:,} ms per loop" if n
                                 else "No steps yet. Add some on the Sequence page.")
        self.cycle_hint.setText(f"One loop takes about {total / 1000:,.2f} s ({n} steps)." if n else "")
        add_hk = self.hk_buttons[HK_ADD_POINT].hotkey
        self.seq_tip.setText(f"Tip: hover anywhere, in any app, and press {add_hk} to add the point under "
                             "the pointer instantly. Edit cells directly in the table.")
        tog = self.hk_buttons[HK_TOGGLE].hotkey
        emg = self.hk_buttons[HK_EMERGENCY].hotkey
        how = f"Hold {tog} to click" if self.activation_seg.value() == "hold" else f"{tog} start / stop"
        self.side_hint.setText(f"{how}\n{emg} emergency stop\n{add_hk} add sequence point")
        if not self._running:
            self.power.setEnabled(ms >= MIN_INTERVAL_MS or self.target_seg.value() == "sequence")
            self.status_detail.setText(self._idle_detail())

    def _idle_detail(self) -> str:
        tog = self.hk_buttons[HK_TOGGLE].hotkey
        if self.activation_seg.value() == "hold":
            text = f"Hold {tog} anywhere to click."
        else:
            text = f"Press {tog} anywhere, or the power button, to start."
        if self.sched_toggle.isChecked():
            text += f"  Scheduled start at {self.sched_time.time().toString('HH:mm')}."
        return text

    # ===================================================================== #
    # Countdown pickers (position, sequence point, window, pixel)
    # ===================================================================== #
    def _start_countdown(self, kind: str, button: QPushButton) -> None:
        if self._countdown:
            same = self._countdown["kind"] == kind
            self._cancel_countdown()
            if same:
                return
        self._countdown = {"kind": kind, "button": button, "left": COUNTDOWN_S, "text": button.text()}
        button.setText(f"{COUNTDOWN_S}…")
        prompts = {"position": "Point at the target…", "sequence": "Point at the next step…",
                   "window": "Click into the app to lock to…", "pixel": "Point at the pixel to watch…"}
        self._toast(prompts[kind])
        self._countdown_timer.start()

    def _cancel_countdown(self) -> None:
        if self._countdown:
            self._countdown["button"].setText(self._countdown["text"])
            self._countdown = None
        self._countdown_timer.stop()

    def _countdown_tick(self) -> None:
        cd = self._countdown
        if not cd:
            self._countdown_timer.stop()
            return
        cd["left"] -= 1
        if cd["left"] > 0:
            cd["button"].setText(f"{cd['left']}…")
            return
        self._cancel_countdown()
        x, y = self._cursor_pos()
        kind = cd["kind"]
        if kind == "position":
            self.x_spin.setValue(x)
            self.y_spin.setValue(y)
            self.target_seg.set_value("fixed")
            self._toast(f"Fixed point set to ({x}, {y}).")
        elif kind == "sequence":
            self._seq_add(x, y)
        elif kind == "window":
            if not win32.IS_WINDOWS:
                self._toast("Window Lock requires Windows.", error=True)
                return
            hwnd = win32.foreground_window()
            exe = win32.window_process_name(hwnd)
            if not exe or exe.lower() == Path(QApplication.applicationFilePath()).name.lower():
                self._toast("That was BleeClicker itself. Click into the other app during the countdown.",
                            error=True)
                return
            self._wl_exe = exe
            self.wl_toggle.setChecked(True)
            self._update_wl_label(win32.window_title(hwnd))
            self._changed()
            self._toast(f"Window Lock set to {exe}.")
        elif kind == "pixel":
            rgb = win32.get_pixel(x, y) if win32.IS_WINDOWS else None
            if rgb is None:
                self._toast("Couldn't read that pixel.", error=True)
                return
            self._px_pos = (x, y)
            self._px_rgb = "#{:02x}{:02x}{:02x}".format(*rgb)
            self.px_toggle.setChecked(True)
            self._update_px_label()
            self._changed()
            self._toast(f"Pixel Trigger watching ({x}, {y}) for {self._px_rgb}.")

    def _update_wl_label(self, title: str = "") -> None:
        if self._wl_exe:
            self.wl_label.setText(self._wl_exe)
            self.wl_label.setToolTip(title or self._wl_exe)
        else:
            self.wl_label.setText("No app picked")

    def _update_px_label(self) -> None:
        self.px_swatch.set_color(self._px_rgb)
        self.px_label.setText(f"{self._px_rgb.upper()}  at  ({self._px_pos[0]}, {self._px_pos[1]})")

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
    # Sequence editing
    # ===================================================================== #
    def _seq_add(self, x: int, y: int) -> None:
        if len(self._sequence) >= 500:
            self._toast("A sequence can have at most 500 steps.", error=True)
            return
        self._sequence.append({"x": x, "y": y, "button": self.button_seg.value(),
                               "clicks": MODE_CLICKS[self.mode_seg.value()],
                               "delay_ms": max(MIN_INTERVAL_MS, min(self.interval_ms(), MAX_INTERVAL_MS))})
        self._rebuild_seq_table()
        self.seq_table.selectRow(len(self._sequence) - 1)
        switched = ""
        if self.target_seg.value() != "sequence" and not self._running:
            self.target_seg.set_value("sequence")
            switched = " Target switched to Sequence."
        self._changed()
        self._toast(f"Added step {len(self._sequence)} at ({x}, {y}).{switched}")

    def _rebuild_seq_table(self) -> None:
        t = self.seq_table
        t.setRowCount(0)
        t.setRowCount(len(self._sequence))
        for row, step in enumerate(self._sequence):
            for col, key, lo, hi in ((0, "x", -32768, 32767), (1, "y", -32768, 32767),
                                     (3, "clicks", 1, 10), (4, "delay_ms", 1, MAX_INTERVAL_MS)):
                sp = QSpinBox()
                sp.setRange(lo, hi)
                sp.setButtonSymbols(QAbstractSpinBox.NoButtons)
                sp.setValue(step[key])
                sp.setFrame(False)
                if key == "delay_ms":
                    sp.setGroupSeparatorShown(True)
                sp.valueChanged.connect(lambda v, r=row, k=key: self._seq_edit(r, k, v))
                t.setCellWidget(row, col, sp)
            combo = QComboBox()
            for label, data in BUTTON_OPTIONS:
                combo.addItem(label, data)
            combo.setCurrentIndex(max(combo.findData(step["button"]), 0))
            combo.currentIndexChanged.connect(
                lambda _i, r=row, c=combo: self._seq_edit(r, "button", c.currentData()))
            t.setCellWidget(row, 2, combo)
        self._update_all_hints()

    def _seq_edit(self, row: int, key: str, value) -> None:
        if 0 <= row < len(self._sequence):
            self._sequence[row][key] = value
            self._changed()

    def _seq_selected(self) -> int:
        rows = self.seq_table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _seq_move(self, delta: int) -> None:
        r = self._seq_selected()
        n = r + delta
        if r < 0 or not 0 <= n < len(self._sequence):
            return
        self._sequence[r], self._sequence[n] = self._sequence[n], self._sequence[r]
        self._rebuild_seq_table()
        self.seq_table.selectRow(n)
        self._changed()

    def _seq_remove(self) -> None:
        r = self._seq_selected()
        if r < 0:
            self._toast("Select a step to remove.")
            return
        del self._sequence[r]
        self._rebuild_seq_table()
        if self._sequence:
            self.seq_table.selectRow(min(r, len(self._sequence) - 1))
        self._changed()

    def _seq_clear(self) -> None:
        if self._sequence and QMessageBox.question(self, APP_NAME, "Remove all steps?") == QMessageBox.Yes:
            self._sequence.clear()
            self._rebuild_seq_table()
            self._changed()

    # ===================================================================== #
    # Profiles
    # ===================================================================== #
    def _refresh_profiles(self, select: str | None = None) -> None:
        self.profile_list.clear()
        for name in sorted(self.settings.profiles, key=str.lower):
            self.profile_list.addItem(name)
            if name == select:
                self.profile_list.setCurrentRow(self.profile_list.count() - 1)
        if not self.settings.profiles:
            self.profile_list.addItem("No profiles yet. Set things up, then “Save current as…”.")
            self.profile_list.item(0).setFlags(Qt.NoItemFlags)

    def _selected_profile(self) -> str | None:
        item = self.profile_list.currentItem()
        if item and item.text() in self.settings.profiles:
            return item.text()
        self._toast("Select a profile first.")
        return None

    def _profile_save_as(self) -> None:
        name, ok = QInputDialog.getText(self, "Save profile", "Profile name:")
        name = name.strip()[:60]
        if not ok or not name:
            return
        if name in self.settings.profiles and QMessageBox.question(
                self, APP_NAME, f"Overwrite “{name}”?") != QMessageBox.Yes:
            return
        self.settings.profiles[name] = self._collect_settings().to_profile()
        self._refresh_profiles(name)
        self._save_settings()
        self._toast(f"Saved profile “{name}”.")

    def _profile_update(self) -> None:
        name = self._selected_profile()
        if name:
            self.settings.profiles[name] = self._collect_settings().to_profile()
            self._save_settings()
            self._toast(f"Updated “{name}”.")

    def _profile_load(self) -> None:
        name = self._selected_profile()
        if not name:
            return
        if self._running:
            self._toast("Stop clicking before loading a profile.", error=True)
            return
        self._collect_settings()
        self.settings.apply_dict(self.settings.profiles[name])
        page = self.stack.currentIndex()
        self._load_settings_into_ui()
        self._go(page)
        self._update_all_hints()
        self._save_settings()
        self._toast(f"Loaded profile “{name}”.")

    def _profile_delete(self) -> None:
        name = self._selected_profile()
        if name and QMessageBox.question(self, APP_NAME, f"Delete “{name}”?") == QMessageBox.Yes:
            del self.settings.profiles[name]
            self._refresh_profiles()
            self._save_settings()

    def _profiles_export(self) -> None:
        if not self.settings.profiles:
            self._toast("There are no profiles to export.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export profiles", "bleeclicker-profiles.json",
                                              "JSON (*.json)")
        if not path:
            return
        try:
            Path(path).write_text(json.dumps({"bleeclicker_profiles": self.settings.profiles}, indent=2),
                                  encoding="utf-8")
            self._toast(f"Exported {len(self.settings.profiles)} profile(s).")
        except OSError as exc:
            self._toast(f"Export failed: {exc}", error=True)

    def _profiles_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import profiles", "", "JSON (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            profiles = data.get("bleeclicker_profiles") if isinstance(data, dict) else None
            if not isinstance(profiles, dict):
                raise ValueError("not a BleeClicker profiles file")
        except (OSError, ValueError) as exc:
            self._toast(f"Import failed: {exc}", error=True)
            return
        count = 0
        for name, prof in profiles.items():
            if isinstance(name, str) and 0 < len(name) <= 60 and isinstance(prof, dict):
                probe = Settings()
                probe.apply_dict(prof)          # validate through the settings schema
                self.settings.profiles[name] = probe.to_profile()
                count += 1
        self._refresh_profiles()
        self._save_settings()
        self._toast(f"Imported {count} profile(s).")

    # ===================================================================== #
    # Hotkeys
    # ===================================================================== #
    def _suspend_hotkeys(self) -> None:
        # While recording a new hotkey the old ones must not be active,
        # otherwise Windows would swallow the key press (and act on it).
        self.hotkeys.set_hotkeys({})

    def _apply_hotkeys(self) -> None:
        if not self.hotkeys.available:
            self._set_hotkey_error("Global hotkeys are only available on Windows.")
            return
        results = self.hotkeys.set_hotkeys({hid: b.hotkey for hid, b in self.hk_buttons.items()})
        errors = []
        for hid, b in self.hk_buttons.items():
            b.set_invalid(bool(results.get(hid)))
            if results.get(hid):
                errors.append(results[hid])
        self._set_hotkey_error("\n".join(errors) + ("\nPick a different key." if errors else ""))

    def _on_hotkey_captured(self, hid: int, hotkey: Hotkey) -> None:
        error = hotkey.validate()
        if error is None:
            for other_id, b in self.hk_buttons.items():
                if other_id != hid and b.hotkey == hotkey:
                    error = f"{hotkey} is already used for “{HOTKEY_NAMES[other_id]}”."
        if error:
            self._set_hotkey_error(error)
            QApplication.beep()
            return
        self.hk_buttons[hid].set_hotkey(hotkey)
        self._apply_hotkeys()
        self._changed()

    def _set_hotkey_error(self, text: str) -> None:
        self.hotkey_error.setText(text)
        self.hotkey_error.setVisible(bool(text))

    def _on_hotkey(self, hotkey_id: int) -> None:
        if hotkey_id == HK_TOGGLE:
            if self.activation_seg.value() == "hold":
                if not self._running:
                    self.start_clicking(hold_vk=self.hk_buttons[HK_TOGGLE].hotkey.vk)
            elif self._running:
                self.stop_clicking()
            else:
                self.start_clicking()
        elif hotkey_id == HK_EMERGENCY:
            self.stop_clicking(StopReason.EMERGENCY)
        elif hotkey_id == HK_ADD_POINT:
            x, y = self._cursor_pos()
            self._seq_add(x, y)

    # ===================================================================== #
    # Start / stop
    # ===================================================================== #
    def _build_plan(self, hold_vk: int = 0) -> ClickPlan:
        mode = self.target_seg.value()
        clicks = MODE_CLICKS[self.mode_seg.value()]
        button = self.button_seg.value()
        failsafe = self.failsafe_toggle.isChecked()

        if mode == "sequence":
            if not self._sequence:
                raise ValueError("The sequence is empty. Add steps on the Sequence page.")
            steps = tuple(Step(s["x"], s["y"], s["button"], s["clicks"], s["delay_ms"]) for s in self._sequence)
        else:
            ms = self.interval_ms()
            if not MIN_INTERVAL_MS <= ms <= MAX_INTERVAL_MS:
                raise ValueError(f"Interval must be at least {MIN_INTERVAL_MS} ms.")
            if mode == "fixed":
                steps = (Step(self.x_spin.value(), self.y_spin.value(), button, clicks, ms),)
            else:
                steps = (Step(None, None, button, clicks, ms),)

        if win32.IS_WINDOWS:
            left, top, _, _ = win32.virtual_screen_rect()
            for i, s in enumerate(steps, 1):
                if not s.fixed:
                    continue
                where = f"Step {i}" if mode == "sequence" else "The fixed point"
                if not win32.point_on_any_monitor(s.x, s.y):
                    raise ValueError(f"{where} ({s.x}, {s.y}) is not on any screen.")
                if failsafe and abs(s.x - left) <= 1 and abs(s.y - top) <= 1:
                    raise ValueError(f"{where} is in the fail-safe corner. Move it or turn off the fail-safe.")

        window_lock = ""
        if self.wl_toggle.isChecked():
            if not self._wl_exe:
                raise ValueError("Window Lock is on but no app is picked (Smart Guards page).")
            window_lock = self._wl_exe
        pixel = None
        if self.px_toggle.isChecked():
            rgb = tuple(int(self._px_rgb[i:i + 2], 16) for i in (1, 3, 5))
            pixel = PixelTrigger(self._px_pos[0], self._px_pos[1], rgb, self.px_tol.value(), self.px_mode.value())

        protected = {int(self.winId())}
        if self.hud_toggle.isChecked():
            protected.add(int(self.hud.winId()))
        stop_mode = self.stop_seg.value()
        return ClickPlan(
            steps=steps,
            hold_ms=self.hold_spin.value(),
            jitter_pct=self.jitter_spin.value(),
            scatter_px=self.scatter_spin.value(),
            max_clicks=self.stop_clicks_spin.value() if stop_mode == "clicks" else 0,
            max_cycles=self.loops_spin.value() if mode == "sequence" else 0,
            time_limit_s=self.stop_seconds_spin.value() if stop_mode == "time" else 0,
            start_delay_s=0 if hold_vk else self.delay_spin.value(),
            failsafe=failsafe,
            takeover_stop=self.takeover_toggle.isChecked(),
            pause_while_moving=self.moving_toggle.isChecked(),
            window_lock=window_lock,
            pixel=pixel,
            hold_vk=hold_vk,
            protected_hwnds=frozenset(protected),
        )

    def _power_clicked(self) -> None:
        if self._running:
            self.stop_clicking()
        else:
            self.start_clicking()

    def start_clicking(self, hold_vk: int = 0) -> None:
        if self._running:
            return
        self._cancel_countdown()
        try:
            plan = self._build_plan(hold_vk)
            self.engine.start(plan)
        except Exception as exc:  # validation, platform or state errors
            self._toast(str(exc), error=True)
            QApplication.beep()
            return
        self._run_started_wall = time.time()
        self._cps_samples.clear()
        self._last_ripple = 0
        self._set_running_ui(True)
        if self.sounds_toggle.isChecked():
            win32.beep(True)
        if self.hud_toggle.isChecked():
            self.hud.show_hud()
        self._toast("")

    def stop_clicking(self, reason: str = StopReason.USER) -> None:
        # Sets the stop flag immediately; the worker checks it before every
        # click, so no further clicks happen after this returns.
        self.engine.stop(reason)

    def _on_engine_stopped(self, run_id: int, reason: str) -> None:
        if run_id != self.engine.run_id:
            return  # stale notification from an older run
        clicks = self.engine.click_count
        elapsed = time.time() - self._run_started_wall if self._run_started_wall else 0
        s = self.settings
        s.stats_lifetime_clicks += clicks
        s.stats_runs += 1
        s.stats_longest_s = max(s.stats_longest_s, elapsed)
        self._set_running_ui(False)
        self.hud.hide()
        if self.sounds_toggle.isChecked() and reason != StopReason.SHUTDOWN:
            win32.beep(False)
        self.dock_clicks.setText(f"{clicks:,}")
        self.status_text.setText(reason.split(":")[0])
        self.status_detail.setText(reason if ":" in reason else self._idle_detail())
        if reason.startswith(("Error", "Emergency")):
            self._toast(reason, error=True)
        self._schedule_save()

    def _set_running_ui(self, running: bool) -> None:
        self._running = running
        for idx in (0, 1):  # lock click setup while running
            self.pages[idx].widget().setEnabled(not running)
        if self.tray is not None:
            self.tray_toggle_action.setText("Stop clicking" if running else "Start clicking")
        if not running:
            self.power.set_state("idle")
            self.status_dot.set_color(self.colors["subtext"])
            self.status_text.setText("Ready")
            self.status_detail.setText(self._idle_detail())
            self._update_all_hints()

    # ===================================================================== #
    # Live refresh (30 fps)
    # ===================================================================== #
    def _refresh(self) -> None:
        self._tick += 1
        eng = self.engine
        now = time.perf_counter()
        count = eng.click_count

        if self._running:
            kind, text = eng.status
            if kind == "running":
                self.power.set_state("running")
                self.status_dot.set_color(self.colors["success"])
                self.status_text.setText("Clicking")
                step = f"step {eng.current_step + 1}/{len(self._sequence)} · " \
                    if self.target_seg.value() == "sequence" else ""
                self.status_detail.setText(f"{step}{self._fmt_time(eng.elapsed)} elapsed · press "
                                           f"{self.hk_buttons[HK_EMERGENCY].hotkey} to stop")
            elif kind in ("paused", "countdown"):
                self.power.set_state("waiting")
                self.status_dot.set_color(self.colors["warning"])
                self.status_text.setText("Starting" if kind == "countdown" else "Paused")
                self.status_detail.setText(text)
            self.dock_clicks.setText(f"{count:,}")

            # Ripple where the last click landed (at most once per refresh).
            seq, x, y = eng.last_click
            if seq != self._last_ripple:
                self._last_ripple = seq
                if self.ripple_toggle.isChecked() and win32.IS_WINDOWS:
                    self.ripple.ripple(x, y)

        # CPS measured over the last ~1 s of samples.
        self._cps_samples.append((now, count))
        t0, c0 = self._cps_samples[0]
        if self._running and now - t0 > 0.05:
            self._cps_now = max(0.0, (count - c0) / (now - t0))
        elif not self._running:
            self._cps_now = 0.0

        if self._tick % 8 == 0:   # ~4 Hz: graphs, tiles, HUD, cursor label
            self._cps_history.append(self._cps_now)
            target = None
            if self._running and self.target_seg.value() != "sequence":
                target = 1000.0 / max(self.interval_ms(), 1)
            hist = list(self._cps_history)
            self.big_graph.set_values(hist, target)
            self.mini_graph.set_values(hist[-60:])
            self.dock_cps.setText(f"{self._cps_now:,.1f}")
            self.t_cps.set_value(f"{self._cps_now:,.1f}")
            self.t_session.set_value(f"{count:,}")
            self.t_time.set_value(self._fmt_time(eng.elapsed if self._running else 0))
            err = eng.timing_error_ms
            self.t_acc.set_value("–" if err is None else f"±{err:.2f} ms")
            life = self.settings.stats_lifetime_clicks + (count if self._running else 0)
            self.t_life.set_value(f"{life:,}")
            self.t_runs.set_value(f"{self.settings.stats_runs:,}")
            x, y = self._cursor_pos()
            self.cursor_label.setText(f"Pointer now at ({x}, {y})")
            if self._running and self.hud.isVisible():
                kind, text = eng.status
                title = {"running": "Clicking", "paused": "Paused", "countdown": "Starting"}.get(kind, "…")
                dot = self.colors["success"] if kind == "running" else self.colors["warning"]
                detail = f"{self._cps_now:,.1f} CPS · {count:,}" if kind == "running" else text[:34]
                self.hud.set_info(title, detail, dot)

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        seconds = int(seconds)
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def _check_schedule(self) -> None:
        if not self.sched_toggle.isChecked() or self._running:
            return
        now = datetime.now()
        hhmm = now.strftime("%H:%M")
        key = now.strftime("%Y-%m-%d ") + hhmm
        if hhmm == self.sched_time.time().toString("HH:mm") and key != self._schedule_fired:
            self._schedule_fired = key
            self._toast("Scheduled start.")
            self.start_clicking()

    def _toast(self, text: str, error: bool = False) -> None:
        self.toast.setObjectName("error" if error else "hint")
        repolish(self.toast)
        self.toast.setText(text)
        if text:
            self._toast_timer.start()

    # ===================================================================== #
    # Theme & window behaviour
    # ===================================================================== #
    def _set_accent(self, key: str) -> None:
        self.accent_buttons[key].setChecked(True)
        self._apply_theme()
        self._changed()

    def _apply_theme(self) -> None:
        accent = next((k for k, b in self.accent_buttons.items() if b.isChecked()), "blee")
        c = theme.apply_theme(QApplication.instance(), self.theme_seg.value(), accent)
        self.colors = c
        for t in self.findChildren(ToggleSwitch):
            t.colors = c
            t.update()
        self.power.colors = c
        self.power.update()
        for g in (self.big_graph, self.mini_graph):
            g.colors = c
            g.update()
        self.hud.colors = c
        self.ripple.color = QColor(c["accent2"])
        self._update_nav_icons()
        for b in self.findChildren(QPushButton):
            name = b.property("iconName")
            if name:
                col = c["accent_text"] if b.objectName() == "primary" else (
                    c["danger"] if b.objectName() == "danger" else c["text"])
                b.setIcon(icon(name, col, 18))
        if not self._running:
            self.status_dot.set_color(c["subtext"])
        if not self._loading:
            self._changed()

    def _on_always_on_top(self, checked: bool) -> None:
        if self._loading:
            return
        self.setWindowFlag(Qt.WindowStaysOnTopHint, checked)
        self.show()   # changing window flags hides the window

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if (event.type() == event.Type.WindowStateChange and self.isMinimized()
                and self.tray_toggle.isChecked() and self.tray is not None):
            QTimer.singleShot(0, self.hide)
            self.tray.showMessage(APP_NAME, "Still running in the tray. Hotkeys keep working.",
                                  QSystemTrayIcon.Information, 2500)

    def closeEvent(self, event: QCloseEvent) -> None:
        # Stop everything cleanly: worker thread, hotkey thread, timers, overlays.
        for t in (self._refresh_timer, self._countdown_timer, self._save_timer, self._schedule_timer):
            t.stop()
        self.engine.shutdown()
        self.hotkeys.stop()
        self.ripple.close()
        self.hud.close()
        if self.tray is not None:
            self.tray.hide()
        self._save_settings()
        super().closeEvent(event)
        QApplication.quit()
