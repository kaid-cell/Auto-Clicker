"""Global (system-wide) hotkeys.

Hotkeys are registered with the Win32 ``RegisterHotKey`` API on a dedicated
background thread that runs its own message loop. Windows posts ``WM_HOTKEY``
to that thread whenever the key combination is pressed, no matter which
application has focus, so the hotkeys keep working while the app is minimised
or another window is active.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import threading
from dataclasses import dataclass
from typing import Callable

from . import win32

# --------------------------------------------------------------------------- #
# Key table: display name -> Windows virtual-key code
# --------------------------------------------------------------------------- #
KEY_CODES: dict[str, int] = {}
KEY_CODES.update({f"F{i}": 0x70 + i - 1 for i in range(1, 25)})          # F1..F24
KEY_CODES.update({chr(c): c for c in range(ord("A"), ord("Z") + 1)})       # A..Z
KEY_CODES.update({str(d): 0x30 + d for d in range(10)})                    # 0..9
KEY_CODES.update({f"Num{d}": 0x60 + d for d in range(10)})                 # numpad 0..9
KEY_CODES.update({
    "Space": 0x20,
    "PageUp": 0x21,
    "PageDown": 0x22,
    "End": 0x23,
    "Home": 0x24,
    "Left": 0x25,
    "Up": 0x26,
    "Right": 0x27,
    "Down": 0x28,
    "Insert": 0x2D,
    "Delete": 0x2E,
    "Pause": 0x13,
    "ScrollLock": 0x91,
    "Num*": 0x6A,
    "Num+": 0x6B,
    "Num-": 0x6D,
    "Num.": 0x6E,
    "Num/": 0x6F,
})

# Keys that are safe to use without a modifier: they do not interfere with
# normal typing in other applications.
STANDALONE_KEYS = {f"F{i}" for i in range(1, 25)} | {
    "Pause", "ScrollLock", "Insert", "Home", "End", "PageUp", "PageDown",
} | {f"Num{d}" for d in range(10)} | {"Num*", "Num+", "Num-", "Num.", "Num/"}

# Order used when formatting a hotkey as text.
MODIFIERS: list[tuple[str, int]] = [
    ("Ctrl", win32.MOD_CONTROL),
    ("Alt", win32.MOD_ALT),
    ("Shift", win32.MOD_SHIFT),
    ("Win", win32.MOD_WIN),
]
_MODIFIER_ALIASES = {"ctrl": "Ctrl", "control": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}


@dataclass(frozen=True)
class Hotkey:
    """A key plus modifier set, e.g. ``Hotkey("F6", ("Ctrl",))``."""

    key: str
    modifiers: tuple[str, ...] = ()

    @property
    def vk(self) -> int:
        return KEY_CODES[self.key]

    @property
    def mod_flags(self) -> int:
        flags = 0
        for name, flag in MODIFIERS:
            if name in self.modifiers:
                flags |= flag
        return flags

    def __str__(self) -> str:
        parts = [name for name, _ in MODIFIERS if name in self.modifiers]
        return "+".join(parts + [self.key])

    @classmethod
    def parse(cls, text: str) -> "Hotkey":
        """Parse text such as ``"Ctrl+Shift+F6"``. Raises ``ValueError``."""
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Hotkey is empty.")
        parts = [p.strip() for p in text.split("+")]
        # "Num+" ends with a '+', which split() turns into ['Num', ''].
        if len(parts) >= 2 and parts[-1] == "" and parts[-2].lower() == "num":
            parts = parts[:-2] + ["Num+"]
        *mods, key = parts
        key_lookup = {k.lower(): k for k in KEY_CODES}
        if key.lower() not in key_lookup:
            raise ValueError(f"Unsupported key: {key!r}")
        modifiers = []
        for m in mods:
            canonical = _MODIFIER_ALIASES.get(m.lower())
            if canonical is None:
                raise ValueError(f"Unsupported modifier: {m!r}")
            if canonical not in modifiers:
                modifiers.append(canonical)
        ordered = tuple(name for name, _ in MODIFIERS if name in modifiers)
        return cls(key_lookup[key.lower()], ordered)

    def validate(self) -> str | None:
        """Return an error message if the hotkey is a poor choice, else None."""
        if self.key not in KEY_CODES:
            return f"Unsupported key: {self.key}"
        if self.key not in STANDALONE_KEYS:
            # Letters, digits, arrows, Space and Delete would be stolen from
            # every other program, so require Ctrl/Alt/Win with them.
            if not ({"Ctrl", "Alt", "Win"} & set(self.modifiers)):
                return f"'{self.key}' needs Ctrl, Alt or Win so it doesn't block normal typing."
        return None


# --------------------------------------------------------------------------- #
# Listener thread
# --------------------------------------------------------------------------- #
_WM_APP_UPDATE = win32.WM_APP + 1


class HotkeyListener:
    """Owns a background thread that registers hotkeys and receives WM_HOTKEY.

    ``callback(hotkey_id)`` is invoked *on the listener thread*; the caller
    must marshal it to the GUI thread (we use a Qt signal for that).
    """

    def __init__(self, callback: Callable[[int], None]) -> None:
        self._callback = callback
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._pending: dict[int, Hotkey] = {}
        self._results: dict[int, str | None] = {}
        self._applied = threading.Event()

    @property
    def available(self) -> bool:
        return win32.IS_WINDOWS

    def start(self) -> None:
        if not win32.IS_WINDOWS or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="HotkeyListener", daemon=True)
        self._thread.start()
        self._ready.wait(2.0)

    def set_hotkeys(self, hotkeys: dict[int, Hotkey], timeout: float = 2.0) -> dict[int, str | None]:
        """Replace all registered hotkeys.

        Returns ``{id: None}`` on success or ``{id: "error message"}`` for each
        hotkey that could not be registered (e.g. already used by another app).
        """
        if not win32.IS_WINDOWS:
            return {i: "Global hotkeys are only available on Windows." for i in hotkeys}
        if self._thread is None or not self._thread_id:
            return {i: "Hotkey listener is not running." for i in hotkeys}
        with self._lock:
            self._pending = dict(hotkeys)
            self._applied.clear()
        # Registration must happen on the listener thread: hotkeys registered
        # with hwnd=NULL are bound to the thread that registers them.
        win32.user32.PostThreadMessageW(self._thread_id, _WM_APP_UPDATE, 0, 0)
        if not self._applied.wait(timeout):
            return {i: "Timed out registering hotkey." for i in hotkeys}
        with self._lock:
            return dict(self._results)

    def stop(self, timeout: float = 2.0) -> None:
        if self._thread is None:
            return
        if self._thread_id:
            win32.user32.PostThreadMessageW(self._thread_id, win32.WM_QUIT, 0, 0)
        self._thread.join(timeout)
        self._thread = None
        self._thread_id = 0

    # -- runs on the listener thread ------------------------------------- #
    def _run(self) -> None:
        user32 = win32.user32
        msg = wintypes.MSG()
        self._thread_id = win32.kernel32.GetCurrentThreadId()
        # Force creation of this thread's message queue before anyone posts to it.
        user32.PeekMessageW(ctypes.byref(msg), None, win32.WM_USER, win32.WM_USER, win32.PM_NOREMOVE)
        self._ready.set()

        registered: set[int] = set()
        try:
            while True:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret == 0 or ret == -1:  # WM_QUIT or error
                    break
                if msg.message == win32.WM_HOTKEY:
                    try:
                        self._callback(int(msg.wParam))
                    except Exception:  # never let a callback kill the loop
                        pass
                elif msg.message == _WM_APP_UPDATE:
                    self._apply_pending(registered)
        finally:
            for hid in registered:
                user32.UnregisterHotKey(None, hid)

    def _apply_pending(self, registered: set[int]) -> None:
        user32 = win32.user32
        for hid in list(registered):
            user32.UnregisterHotKey(None, hid)
            registered.discard(hid)

        with self._lock:
            pending = dict(self._pending)
        results: dict[int, str | None] = {}
        for hid, hk in pending.items():
            ok = user32.RegisterHotKey(None, hid, hk.mod_flags | win32.MOD_NOREPEAT, hk.vk)
            if ok:
                registered.add(hid)
                results[hid] = None
            else:
                err = ctypes.get_last_error()
                if err == win32.ERROR_HOTKEY_ALREADY_REGISTERED:
                    results[hid] = f"{hk} is already in use by another program."
                else:
                    results[hid] = f"Could not register {hk} ({ctypes.FormatError(err).strip()})."
        with self._lock:
            self._results = results
        self._applied.set()
