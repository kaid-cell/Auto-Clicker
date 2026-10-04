"""The click engine: one background worker thread that executes a ClickPlan.

A plan is a list of *steps* (a position, a button and a delay). The simple
"click every N ms" mode is just a one-step plan; sequences have many steps.
Before every click the worker evaluates the *gates* (Window Lock, Pixel
Trigger, self-protection, pause-while-moving) and between clicks it watches
the *guards* (stop request, fail-safe corner, time limit, Smart Takeover,
hold-to-click key). The GUI polls ``status``/counters, so the worker never
floods the Qt event loop with per-click signals.
"""

from __future__ import annotations

import math
import random
import threading
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from . import win32

MIN_INTERVAL_MS = 1
MAX_INTERVAL_MS = 24 * 60 * 60 * 1000  # 24 hours

_POLL_SLICE = 0.02     # max sleep before re-checking guards (stop wakes us instantly anyway)
_SPIN_WINDOW = 0.0015  # final stretch before a deadline that is busy-waited for accuracy
_GATE_POLL = 0.05      # how often a closed gate is re-checked
_MOVE_QUIET = 0.30     # pause-while-moving: resume after the mouse is still this long
_TAKEOVER_PX = 6       # Smart Takeover: pointer moved this far from where we put it


@dataclass(frozen=True)
class Step:
    x: int | None = None          # None = click wherever the pointer currently is
    y: int | None = None
    button: str = "left"          # left | right | middle | wheel_up | wheel_down
    clicks: int = 1               # 1 single, 2 double, 3 triple (wheel: notches)
    delay_ms: int = 100           # wait after this step before the next one

    @property
    def fixed(self) -> bool:
        return self.x is not None and self.y is not None


@dataclass(frozen=True)
class PixelTrigger:
    x: int
    y: int
    rgb: tuple[int, int, int]
    tolerance: int = 10            # max per-channel difference counted as a match
    mode: str = "match"            # match: click only when colour matches; differ: when it doesn't

    def satisfied(self, color: tuple[int, int, int] | None) -> bool:
        if color is None:
            return False
        same = all(abs(a - b) <= self.tolerance for a, b in zip(color, self.rgb))
        return same if self.mode == "match" else not same


@dataclass(frozen=True)
class ClickPlan:
    steps: tuple[Step, ...]
    hold_ms: int = 0               # how long each press is held down
    jitter_pct: int = 0            # +/- random variation of every delay
    scatter_px: int = 0            # random offset radius for fixed positions
    max_clicks: int = 0            # 0 = unlimited
    max_cycles: int = 0            # sequence loops; 0 = unlimited
    time_limit_s: float = 0        # 0 = no limit
    start_delay_s: int = 0         # countdown before the first click
    failsafe: bool = True          # stop when the pointer hits the top-left corner
    takeover_stop: bool = False    # stop when the user grabs the mouse (fixed positions)
    pause_while_moving: bool = False  # current-position clicks wait while the mouse moves
    window_lock: str = ""          # only click while this exe is in the foreground
    pixel: PixelTrigger | None = None
    hold_vk: int = 0               # hold-to-click: stop when this key is released
    protected_hwnds: frozenset[int] = field(default_factory=frozenset)  # never click these

    def validate(self) -> None:
        if not self.steps:
            raise ValueError("Add at least one step to the sequence.")
        for i, s in enumerate(self.steps, 1):
            if s.button not in win32.ALL_BUTTONS:
                raise ValueError(f"Step {i}: invalid button {s.button!r}.")
            if not 1 <= s.clicks <= 10:
                raise ValueError(f"Step {i}: clicks must be between 1 and 10.")
            if not MIN_INTERVAL_MS <= s.delay_ms <= MAX_INTERVAL_MS:
                raise ValueError(f"Step {i}: delay must be between 1 ms and 24 hours.")
        if not 0 <= self.jitter_pct <= 90:
            raise ValueError("Timing jitter must be between 0 and 90 %.")
        if self.hold_ms < 0 or self.scatter_px < 0 or self.max_clicks < 0 or self.max_cycles < 0:
            raise ValueError("Values cannot be negative.")
        if self.time_limit_s < 0 or self.start_delay_s < 0:
            raise ValueError("Times cannot be negative.")


class StopReason:
    USER = "Stopped"
    COMPLETED = "Finished: click limit reached"
    CYCLES = "Finished: sequence loops completed"
    TIME = "Finished: time limit reached"
    FAILSAFE = "Emergency stop: pointer hit the top-left corner"
    EMERGENCY = "Emergency stop hotkey pressed"
    TAKEOVER = "Smart Takeover: you moved the mouse, so clicking stopped"
    RELEASED = "Hold-to-click key released"
    SHUTDOWN = "Application closing"


class _Halt(Exception):
    """Internal: a guard tripped; carries the stop reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ClickEngine(QObject):
    """Starts/stops the click worker. Only one worker can run at a time."""

    started = Signal(int)        # run id
    stopped = Signal(int, str)   # run id, reason / error message

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._stop_reason = StopReason.USER
        self._run_id = 0
        self._reset_stats()

    def _reset_stats(self) -> None:
        # Written only by the worker; single attribute reads/writes are atomic in CPython.
        self.click_count = 0
        self.cycles = 0
        self.status = ("idle", "Ready")       # (kind, text): idle | countdown | running | paused
        self.started_at = 0.0                  # perf_counter at first click window
        self.last_click = (0, 0, 0)            # (sequence number, x, y) for the ripple overlay
        self.current_step = 0
        self._err_sum = 0.0
        self._err_n = 0

    # -- public API (GUI thread) ----------------------------------------- #
    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()

    @property
    def run_id(self) -> int:
        return self._run_id

    @property
    def timing_error_ms(self) -> float | None:
        """Average lateness of clicks versus their schedule (accuracy readout)."""
        n = self._err_n
        return (self._err_sum / n) * 1000 if n else None

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self.started_at if self.started_at else 0.0

    def start(self, plan: ClickPlan) -> int:
        """Start clicking. Returns the run id. Raises on invalid plan/state."""
        plan.validate()
        if not win32.IS_WINDOWS:
            raise win32.PlatformNotSupported("Clicking is only supported on Windows.")
        with self._lock:
            old = self._thread
            if old is not None and old.is_alive() and not self._stop_event.is_set():
                raise RuntimeError("BleeClicker is already running.")
        if old is not None and old.is_alive():
            # A previous run is finishing (stop was requested); joined outside
            # the lock because the worker takes the lock on exit.
            old.join(1.0)
            if old.is_alive():
                raise RuntimeError("The previous run is still shutting down. Try again.")
        with self._lock:
            if self._thread is not old:
                raise RuntimeError("BleeClicker is already running.")
            self._run_id += 1
            run_id = self._run_id
            self._stop_event = threading.Event()
            self._stop_reason = StopReason.USER
            self._reset_stats()
            self._thread = threading.Thread(
                target=self._worker, args=(plan, self._stop_event, run_id),
                name=f"ClickWorker-{run_id}", daemon=True,
            )
            self._thread.start()
        return run_id

    def stop(self, reason: str = StopReason.USER) -> None:
        """Request the worker to stop. Non-blocking; no further clicks occur."""
        with self._lock:
            if self._thread is not None and not self._stop_event.is_set():
                self._stop_reason = reason
                self._stop_event.set()

    def shutdown(self, timeout: float = 2.0) -> None:
        """Stop and wait for the worker thread (used on application exit)."""
        self.stop(StopReason.SHUTDOWN)
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout)

    # ===================================================================== #
    # Worker thread
    # ===================================================================== #
    def _worker(self, plan: ClickPlan, stop: threading.Event, run_id: int) -> None:
        reason = None
        high_res = win32.begin_high_res_timer()
        ctx = _RunContext(plan)
        try:
            self.started.emit(run_id)
            if plan.failsafe:
                left, top, _, _ = win32.virtual_screen_rect()
                ctx.corner = (left, top)
            ctx.last_cursor = win32.get_cursor_pos()
            ctx.last_move = 0.0

            # Optional countdown before the first click.
            if plan.start_delay_s > 0:
                end = time.perf_counter() + plan.start_delay_s
                while (remaining := end - time.perf_counter()) > 0:
                    self.status = ("countdown", f"Starting in {math.ceil(remaining)}…")
                    self._wait_until(min(end, time.perf_counter() + 0.1), stop, ctx)

            self.started_at = time.perf_counter()
            self._run_plan(plan, stop, ctx)
        except _Halt as halt:
            reason = halt.reason
        except Exception as exc:  # report any failure to the GUI
            reason = f"Error: {exc}"
        finally:
            if high_res:
                win32.end_high_res_timer()
            with self._lock:
                if reason is None:
                    reason = self._stop_reason
                stop.set()
            self.status = ("idle", reason)
            self.stopped.emit(run_id, reason)

    def _run_plan(self, plan: ClickPlan, stop: threading.Event, ctx: "_RunContext") -> None:
        steps = plan.steps
        index = 0
        next_time = time.perf_counter()   # first click right away (after any countdown)
        gated = False
        while True:
            step = steps[index]
            self.current_step = index
            self._wait_until(next_time, stop, ctx)

            # Gates: conditions that must hold for this click to happen.
            block = self._gate(plan, step, ctx)
            if block:
                self.status = ("paused", block)
                gated = True
                self._wait_until(time.perf_counter() + _GATE_POLL, stop, ctx)
                next_time = time.perf_counter()  # click as soon as the gate opens
                continue
            self.status = ("running", "Clicking")

            if stop.is_set():  # final check: no click after a stop request
                raise _Halt(self._stop_reason)

            now = time.perf_counter()
            if not gated:
                self._err_sum += max(0.0, now - next_time)
                self._err_n += 1
            gated = False

            x, y = self._position_for(step, plan, ctx)
            self._press(step, plan, stop)
            self.click_count += 1
            self.last_click = (self.last_click[0] + 1, x, y)

            if plan.max_clicks and self.click_count >= plan.max_clicks:
                raise _Halt(StopReason.COMPLETED)

            delay = step.delay_ms / 1000.0
            index += 1
            if index >= len(steps):
                index = 0
                self.cycles += 1
                if plan.max_cycles and self.cycles >= plan.max_cycles:
                    raise _Halt(StopReason.CYCLES)

            if plan.jitter_pct:
                spread = delay * plan.jitter_pct / 100.0
                delay = max(MIN_INTERVAL_MS / 1000.0, delay + random.uniform(-spread, spread))
            # Absolute deadlines (rather than sleeping after each click)
            # stop timing errors from accumulating.
            next_time += delay
            now = time.perf_counter()
            if now > next_time + delay:
                # Far behind (system busy / asleep): resume the cadence instead
                # of firing a burst of catch-up clicks.
                next_time = now + delay

    # -- gates --------------------------------------------------------------- #
    def _gate(self, plan: ClickPlan, step: Step, ctx: "_RunContext") -> str | None:
        if plan.window_lock:
            fg = win32.foreground_window()
            if win32.window_process_name(fg).lower() != plan.window_lock.lower():
                return f"Waiting for {plan.window_lock} to be the active window"
        target = (step.x, step.y) if step.fixed else win32.get_cursor_pos()
        if plan.protected_hwnds and win32.root_window_at(*target) in plan.protected_hwnds:
            return "Paused: the pointer is over BleeClicker"
        if plan.pixel is not None:
            if not plan.pixel.satisfied(win32.get_pixel(plan.pixel.x, plan.pixel.y)):
                return "Waiting for the Pixel Trigger colour"
        if plan.pause_while_moving and not step.fixed:
            if time.perf_counter() - ctx.last_move < _MOVE_QUIET:
                return "Paused while you move the mouse"
        return None

    # -- clicking ---------------------------------------------------------- #
    def _position_for(self, step: Step, plan: ClickPlan, ctx: "_RunContext") -> tuple[int, int]:
        if not step.fixed:
            ctx.expected = None
            return win32.get_cursor_pos()
        x, y = step.x, step.y
        if plan.scatter_px:
            # Uniform random point inside a circle (sqrt keeps it uniform).
            r = plan.scatter_px * math.sqrt(random.random())
            a = random.uniform(0, 2 * math.pi)
            x, y = round(x + r * math.cos(a)), round(y + r * math.sin(a))
        win32.set_cursor_pos(x, y)
        ctx.expected = (x, y)
        ctx.last_cursor = (x, y)
        return x, y

    def _press(self, step: Step, plan: ClickPlan, stop: threading.Event) -> None:
        if plan.hold_ms <= 0 or step.button in win32.WHEEL_BUTTONS:
            win32.send_click(step.button, step.clicks)
            return
        for n in range(step.clicks):
            win32.button_down(step.button)
            try:
                stop.wait(plan.hold_ms / 1000.0)   # a stop request releases early
            finally:
                win32.button_up(step.button)       # never leave a button stuck down
            if stop.is_set():
                return
            if n < step.clicks - 1:
                stop.wait(0.03)

    # -- guarded waiting --------------------------------------------------- #
    def _check_guards(self, stop: threading.Event, ctx: "_RunContext") -> None:
        if stop.is_set():
            raise _Halt(self._stop_reason)
        plan = ctx.plan
        cursor = win32.get_cursor_pos()
        if ctx.corner is not None and abs(cursor[0] - ctx.corner[0]) <= 1 and abs(cursor[1] - ctx.corner[1]) <= 1:
            raise _Halt(StopReason.FAILSAFE)
        if plan.takeover_stop and ctx.expected is not None:
            if math.dist(cursor, ctx.expected) > _TAKEOVER_PX:
                raise _Halt(StopReason.TAKEOVER)
        if cursor != ctx.last_cursor:
            ctx.last_cursor = cursor
            ctx.last_move = time.perf_counter()
        if plan.time_limit_s and self.started_at and time.perf_counter() - self.started_at >= plan.time_limit_s:
            raise _Halt(StopReason.TIME)
        if plan.hold_vk and not win32.is_key_down(plan.hold_vk):
            raise _Halt(StopReason.RELEASED)

    def _wait_until(self, deadline: float, stop: threading.Event, ctx: "_RunContext") -> None:
        """Sleep until ``deadline`` while watching the guards (raises _Halt)."""
        while True:
            self._check_guards(stop, ctx)
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return
            if remaining > _SPIN_WINDOW:
                stop.wait(min(remaining - _SPIN_WINDOW, _POLL_SLICE))  # wakes instantly on stop
            else:
                # Fine-grained spin for the last ~1.5 ms; sleep(0) yields the CPU.
                while time.perf_counter() < deadline:
                    if stop.is_set():
                        raise _Halt(self._stop_reason)
                    time.sleep(0)
                return


class _RunContext:
    """Mutable per-run state shared by the worker's helpers."""

    def __init__(self, plan: ClickPlan) -> None:
        self.plan = plan
        self.corner: tuple[int, int] | None = None
        self.expected: tuple[int, int] | None = None   # where we last put the pointer
        self.last_cursor: tuple[int, int] = (0, 0)
        self.last_move = 0.0
