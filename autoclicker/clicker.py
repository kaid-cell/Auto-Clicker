"""The click engine: a single background worker thread that injects clicks."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from . import win32

MIN_INTERVAL_MS = 1
MAX_INTERVAL_MS = 24 * 60 * 60 * 1000  # 24 hours

# How long the worker may sleep in one go before re-checking the stop flag and
# the fail-safe corner. Stop requests wake it instantly anyway (Event.wait);
# this only bounds how often the fail-safe corner is polled.
_POLL_SLICE = 0.02
# Final stretch before a deadline that is busy-waited for sub-millisecond accuracy.
_SPIN_WINDOW = 0.0015


@dataclass(frozen=True)
class ClickConfig:
    button: str = "left"            # left | right | middle
    double: bool = False            # single or double click
    interval_ms: int = 100          # time between click actions
    fixed_position: tuple[int, int] | None = None  # None = current cursor position
    max_clicks: int = 0             # 0 = unlimited
    failsafe: bool = True           # stop when cursor hits top-left corner

    def validate(self) -> None:
        if self.button not in ("left", "right", "middle"):
            raise ValueError(f"Invalid click type: {self.button}")
        if not isinstance(self.interval_ms, int) or self.interval_ms < MIN_INTERVAL_MS:
            raise ValueError(f"Interval must be at least {MIN_INTERVAL_MS} ms.")
        if self.interval_ms > MAX_INTERVAL_MS:
            raise ValueError("Interval must not exceed 24 hours.")
        if self.max_clicks < 0:
            raise ValueError("Number of clicks cannot be negative.")


class StopReason:
    USER = "Stopped"
    COMPLETED = "Finished: click limit reached"
    FAILSAFE = "Emergency stop: cursor moved to the top-left corner"
    EMERGENCY = "Emergency stop hotkey pressed"
    SHUTDOWN = "Application closing"


class ClickEngine(QObject):
    """Starts/stops the click worker. Only one worker can run at a time.

    Signals are emitted from the worker thread; Qt delivers them to slots in
    the GUI thread via queued connections automatically.
    """

    started = Signal(int)        # run id
    stopped = Signal(int, str)   # run id, reason / error message

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._stop_reason = StopReason.USER
        self._run_id = 0
        self._clicks = 0  # written only by the worker; int reads are atomic in CPython

    # -- public API (GUI thread) ----------------------------------------- #
    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()

    @property
    def click_count(self) -> int:
        return self._clicks

    @property
    def run_id(self) -> int:
        return self._run_id

    def start(self, config: ClickConfig) -> int:
        """Start clicking. Returns the run id. Raises on invalid config/state."""
        config.validate()
        if not win32.IS_WINDOWS:
            raise win32.PlatformNotSupported("Auto clicking is only supported on Windows.")
        with self._lock:
            old = self._thread
            if old is not None and old.is_alive() and not self._stop_event.is_set():
                raise RuntimeError("The auto clicker is already running.")
        if old is not None and old.is_alive():
            # A previous run is finishing (stop was requested); its wait is
            # interrupted immediately, so this join is effectively instant.
            # Joined outside the lock because the worker takes it on exit.
            old.join(1.0)
            if old.is_alive():
                raise RuntimeError("The previous run is still shutting down. Try again.")
        with self._lock:
            if self._thread is not old:
                raise RuntimeError("The auto clicker is already running.")
            self._run_id += 1
            run_id = self._run_id
            self._stop_event = threading.Event()
            self._stop_reason = StopReason.USER
            self._clicks = 0
            self._thread = threading.Thread(
                target=self._worker,
                args=(config, self._stop_event, run_id),
                name=f"ClickWorker-{run_id}",
                daemon=True,
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

    # -- worker thread ----------------------------------------------------- #
    def _worker(self, cfg: ClickConfig, stop: threading.Event, run_id: int) -> None:
        reason = None
        high_res = win32.begin_high_res_timer()
        try:
            self.started.emit(run_id)
            interval = cfg.interval_ms / 1000.0
            clicks_per_action = 2 if cfg.double else 1
            corner = None
            if cfg.failsafe:
                left, top, _, _ = win32.virtual_screen_rect()
                corner = (left, top)

            # Absolute deadlines (rather than sleeping `interval` after each
            # click) prevent timing drift from accumulating.
            next_time = time.perf_counter() + interval
            while True:
                if not self._wait_until(next_time, stop, corner):
                    break  # stop requested or fail-safe triggered

                # Re-check right before clicking so a stop request that arrives
                # during the final spin never results in one more click.
                if stop.is_set():
                    break
                if cfg.fixed_position is not None:
                    win32.set_cursor_pos(*cfg.fixed_position)
                win32.send_click(cfg.button, clicks_per_action)
                self._clicks += 1

                if cfg.max_clicks and self._clicks >= cfg.max_clicks:
                    reason = StopReason.COMPLETED
                    break

                next_time += interval
                now = time.perf_counter()
                if now > next_time + interval:
                    # We fell far behind (system was busy / asleep). Don't
                    # fire a burst of catch-up clicks; resume the cadence.
                    next_time = now + interval
        except Exception as exc:  # report any failure to the GUI
            reason = f"Error: {exc}"
        finally:
            if high_res:
                win32.end_high_res_timer()
            with self._lock:
                if reason is None:
                    reason = self._stop_reason
                stop.set()
            self.stopped.emit(run_id, reason)

    def _wait_until(self, deadline: float, stop: threading.Event,
                    corner: tuple[int, int] | None) -> bool:
        """Sleep until ``deadline``. Returns False if we must stop instead."""
        while True:
            if stop.is_set():
                return False
            if corner is not None and self._in_corner(corner):
                with self._lock:
                    self._stop_reason = StopReason.FAILSAFE
                    stop.set()
                return False
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return True
            if remaining > _SPIN_WINDOW:
                # Coarse sleep; returns immediately if stop is set.
                stop.wait(min(remaining - _SPIN_WINDOW, _POLL_SLICE))
            else:
                # Fine-grained spin for the last ~1.5 ms; sleep(0) yields the CPU.
                while time.perf_counter() < deadline:
                    if stop.is_set():
                        return False
                    time.sleep(0)
                return True

    @staticmethod
    def _in_corner(corner: tuple[int, int]) -> bool:
        x, y = win32.get_cursor_pos()
        return abs(x - corner[0]) <= 1 and abs(y - corner[1]) <= 1
