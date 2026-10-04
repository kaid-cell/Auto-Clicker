"""Thin ctypes wrappers around the Win32 APIs the app needs.

Everything here talks to Windows directly (user32 / kernel32 / winmm), so the
app has no third-party input dependencies. On non-Windows platforms the module
still imports, but every input function raises ``PlatformNotSupported`` so the
GUI can be developed and smoke-tested elsewhere.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

IS_WINDOWS = sys.platform == "win32"


class PlatformNotSupported(OSError):
    """Raised when a Windows-only API is used on another platform."""


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
INPUT_MOUSE = 0

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040

# Hotkey modifiers for RegisterHotKey
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000  # holding the key down does not fire repeatedly

WM_QUIT = 0x0012
WM_HOTKEY = 0x0312
WM_USER = 0x0400
WM_APP = 0x8000
PM_NOREMOVE = 0x0000

SM_SWAPBUTTON = 23
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

MONITOR_DEFAULTTONULL = 0
ERROR_ALREADY_EXISTS = 183
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

# Button name -> (down flag, up flag)
_BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


# --------------------------------------------------------------------------- #
# Structures (SendInput). The union must contain every member so that
# ctypes.sizeof(INPUT) matches the native size (40 bytes on x64).
# --------------------------------------------------------------------------- #
ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


# --------------------------------------------------------------------------- #
# DLL bindings (only on Windows)
# --------------------------------------------------------------------------- #
if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    winmm = ctypes.WinDLL("winmm")

    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT

    user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
    user32.GetCursorPos.restype = wintypes.BOOL

    user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
    user32.SetCursorPos.restype = wintypes.BOOL

    user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
    user32.GetSystemMetrics.restype = ctypes.c_int

    user32.MonitorFromPoint.argtypes = (wintypes.POINT, wintypes.DWORD)
    user32.MonitorFromPoint.restype = wintypes.HMONITOR

    user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
    user32.RegisterHotKey.restype = wintypes.BOOL

    user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.UnregisterHotKey.restype = wintypes.BOOL

    user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
    user32.GetMessageW.restype = wintypes.BOOL

    user32.PeekMessageW.argtypes = (
        ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT,
    )
    user32.PeekMessageW.restype = wintypes.BOOL

    user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user32.PostThreadMessageW.restype = wintypes.BOOL

    kernel32.GetCurrentThreadId.argtypes = ()
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CreateMutexW.restype = wintypes.HANDLE

    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    winmm.timeBeginPeriod.argtypes = (wintypes.UINT,)
    winmm.timeBeginPeriod.restype = wintypes.UINT
    winmm.timeEndPeriod.argtypes = (wintypes.UINT,)
    winmm.timeEndPeriod.restype = wintypes.UINT
else:  # pragma: no cover - non-Windows development only
    user32 = kernel32 = winmm = None


def _require_windows() -> None:
    if not IS_WINDOWS:
        raise PlatformNotSupported("This feature is only available on Windows.")


# --------------------------------------------------------------------------- #
# Mouse
# --------------------------------------------------------------------------- #
def _mouse_input(flags: int) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi = MOUSEINPUT(0, 0, 0, flags, 0, 0)
    return inp


def send_click(button: str, count: int = 1) -> None:
    """Inject ``count`` real mouse clicks of ``button`` at the cursor position.

    All down/up events are sent in a single ``SendInput`` call, so they are
    inserted atomically into the input stream and a button can never be left
    "stuck" down. Two clicks sent this way are recognised by Windows as a
    double click (they arrive well within the system double-click time).
    """
    _require_windows()
    button = button.lower()
    if button not in _BUTTON_FLAGS:
        raise ValueError(f"Unknown mouse button: {button!r}")

    # SendInput's LEFT/RIGHT flags refer to *physical* buttons. If the user has
    # swapped primary/secondary buttons in Windows settings, swap them back so
    # "Left click" always means the primary click the user expects.
    if button in ("left", "right") and user32.GetSystemMetrics(SM_SWAPBUTTON):
        button = "right" if button == "left" else "left"

    down, up = _BUTTON_FLAGS[button]
    events = []
    for _ in range(count):
        events.append(_mouse_input(down))
        events.append(_mouse_input(up))

    array = (INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), array, ctypes.sizeof(INPUT))
    if sent != len(events):
        # Usually means input was blocked by UIPI (target app runs elevated)
        # or by a secure desktop such as the UAC prompt / lock screen.
        raise ctypes.WinError(ctypes.get_last_error())


def get_cursor_pos() -> tuple[int, int]:
    """Cursor position in physical screen pixels."""
    _require_windows()
    pt = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(pt)):
        raise ctypes.WinError(ctypes.get_last_error())
    return pt.x, pt.y


def set_cursor_pos(x: int, y: int) -> None:
    _require_windows()
    if not user32.SetCursorPos(int(x), int(y)):
        raise ctypes.WinError(ctypes.get_last_error())


def virtual_screen_rect() -> tuple[int, int, int, int]:
    """(left, top, width, height) of the bounding box of all monitors."""
    _require_windows()
    return (
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def point_on_any_monitor(x: int, y: int) -> bool:
    _require_windows()
    return bool(user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), MONITOR_DEFAULTTONULL))


# --------------------------------------------------------------------------- #
# Timer resolution
# --------------------------------------------------------------------------- #
def begin_high_res_timer() -> bool:
    """Request 1 ms system timer resolution (improves sleep accuracy)."""
    if not IS_WINDOWS:
        return False
    return winmm.timeBeginPeriod(1) == 0


def end_high_res_timer() -> None:
    if IS_WINDOWS:
        winmm.timeEndPeriod(1)


# --------------------------------------------------------------------------- #
# Single instance
# --------------------------------------------------------------------------- #
class SingleInstanceLock:
    """Named mutex that detects a second running copy of the app."""

    def __init__(self, name: str) -> None:
        self._handle = None
        self.already_running = False
        if not IS_WINDOWS:
            return
        self._handle = kernel32.CreateMutexW(None, False, name)
        self.already_running = ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    def release(self) -> None:
        if self._handle:
            kernel32.CloseHandle(self._handle)
            self._handle = None


def set_app_user_model_id(app_id: str) -> None:
    """Give the process its own taskbar identity so our icon is shown."""
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(app_id))
    except (AttributeError, OSError):
        pass
