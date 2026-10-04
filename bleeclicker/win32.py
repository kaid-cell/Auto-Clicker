"""Thin ctypes wrappers around the Win32 APIs BleeClicker needs.

Everything here talks to Windows directly (user32 / kernel32 / gdi32 / winmm),
so the app has no third-party input dependencies. On other platforms the
module still imports, but input functions raise ``PlatformNotSupported`` so the
GUI can be developed and tested elsewhere.
"""

from __future__ import annotations

import ctypes
import os
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
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120

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
GA_ROOT = 2
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
CLR_INVALID = 0xFFFFFFFF
ERROR_ALREADY_EXISTS = 183
ERROR_HOTKEY_ALREADY_REGISTERED = 1409
MB_OK = 0x00000000
MB_ICONASTERISK = 0x00000040

# Mouse "buttons" -> (down flag, up flag). Wheel actions are handled separately.
_BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}
WHEEL_BUTTONS = {"wheel_up": 1, "wheel_down": -1}
ALL_BUTTONS = tuple(_BUTTON_FLAGS) + tuple(WHEEL_BUTTONS)


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
    gdi32 = ctypes.WinDLL("gdi32")
    winmm = ctypes.WinDLL("winmm")

    _LONG_PTR = ctypes.c_ssize_t

    def _bind(dll, name, argtypes, restype):
        fn = getattr(dll, name)
        fn.argtypes = argtypes
        fn.restype = restype
        return fn

    _bind(user32, "SendInput", (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int), wintypes.UINT)
    _bind(user32, "GetCursorPos", (ctypes.POINTER(wintypes.POINT),), wintypes.BOOL)
    _bind(user32, "SetCursorPos", (ctypes.c_int, ctypes.c_int), wintypes.BOOL)
    _bind(user32, "GetSystemMetrics", (ctypes.c_int,), ctypes.c_int)
    _bind(user32, "MonitorFromPoint", (wintypes.POINT, wintypes.DWORD), wintypes.HMONITOR)
    _bind(user32, "RegisterHotKey", (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT), wintypes.BOOL)
    _bind(user32, "UnregisterHotKey", (wintypes.HWND, ctypes.c_int), wintypes.BOOL)
    _bind(user32, "GetMessageW",
          (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT), wintypes.BOOL)
    _bind(user32, "PeekMessageW",
          (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT),
          wintypes.BOOL)
    _bind(user32, "PostThreadMessageW",
          (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM), wintypes.BOOL)
    _bind(user32, "GetForegroundWindow", (), wintypes.HWND)
    _bind(user32, "WindowFromPoint", (wintypes.POINT,), wintypes.HWND)
    _bind(user32, "GetAncestor", (wintypes.HWND, wintypes.UINT), wintypes.HWND)
    _bind(user32, "GetWindowThreadProcessId", (wintypes.HWND, ctypes.POINTER(wintypes.DWORD)), wintypes.DWORD)
    _bind(user32, "GetWindowTextW", (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int), ctypes.c_int)
    _bind(user32, "GetAsyncKeyState", (ctypes.c_int,), ctypes.c_short)
    _bind(user32, "GetDC", (wintypes.HWND,), wintypes.HDC)
    _bind(user32, "ReleaseDC", (wintypes.HWND, wintypes.HDC), ctypes.c_int)
    _bind(user32, "MessageBeep", (wintypes.UINT,), wintypes.BOOL)
    _bind(user32, "GetWindowLongPtrW", (wintypes.HWND, ctypes.c_int), _LONG_PTR)
    _bind(user32, "SetWindowLongPtrW", (wintypes.HWND, ctypes.c_int, _LONG_PTR), _LONG_PTR)
    _bind(gdi32, "GetPixel", (wintypes.HDC, ctypes.c_int, ctypes.c_int), wintypes.DWORD)
    _bind(kernel32, "GetCurrentThreadId", (), wintypes.DWORD)
    _bind(kernel32, "CreateMutexW", (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR), wintypes.HANDLE)
    _bind(kernel32, "CloseHandle", (wintypes.HANDLE,), wintypes.BOOL)
    _bind(kernel32, "OpenProcess", (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD), wintypes.HANDLE)
    _bind(kernel32, "QueryFullProcessImageNameW",
          (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)), wintypes.BOOL)
    _bind(winmm, "timeBeginPeriod", (wintypes.UINT,), wintypes.UINT)
    _bind(winmm, "timeEndPeriod", (wintypes.UINT,), wintypes.UINT)
else:  # pragma: no cover - non-Windows development only
    user32 = kernel32 = gdi32 = winmm = None


def _require_windows() -> None:
    if not IS_WINDOWS:
        raise PlatformNotSupported("This feature is only available on Windows.")


# --------------------------------------------------------------------------- #
# Mouse
# --------------------------------------------------------------------------- #
def _mouse_input(flags: int, data: int = 0) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi = MOUSEINPUT(0, 0, data & 0xFFFFFFFF, flags, 0, 0)
    return inp


def _send(events: list[INPUT]) -> None:
    array = (INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), array, ctypes.sizeof(INPUT))
    if sent != len(events):
        # Usually means input was blocked by UIPI (target app runs elevated)
        # or by a secure desktop such as the UAC prompt / lock screen.
        raise ctypes.WinError(ctypes.get_last_error())


def _physical_button(button: str) -> str:
    # SendInput's LEFT/RIGHT flags refer to *physical* buttons. If the user has
    # swapped primary/secondary buttons in Windows settings, swap them back so
    # "Left" always means the primary click the user expects.
    if button in ("left", "right") and user32.GetSystemMetrics(SM_SWAPBUTTON):
        return "right" if button == "left" else "left"
    return button


def send_click(button: str, count: int = 1) -> None:
    """Inject ``count`` real clicks (or wheel notches) at the cursor position.

    All down/up events go out in a single ``SendInput`` call, so they are
    inserted atomically and a button can never be left "stuck" down. Clicks
    sent this way are recognised by Windows as double/triple clicks.
    """
    _require_windows()
    if button in WHEEL_BUTTONS:
        delta = WHEEL_BUTTONS[button] * WHEEL_DELTA
        _send([_mouse_input(MOUSEEVENTF_WHEEL, delta) for _ in range(count)])
        return
    if button not in _BUTTON_FLAGS:
        raise ValueError(f"Unknown mouse button: {button!r}")
    down, up = _BUTTON_FLAGS[_physical_button(button)]
    events = []
    for _ in range(count):
        events += [_mouse_input(down), _mouse_input(up)]
    _send(events)


def button_down(button: str) -> None:
    _require_windows()
    _send([_mouse_input(_BUTTON_FLAGS[_physical_button(button)][0])])


def button_up(button: str) -> None:
    _require_windows()
    _send([_mouse_input(_BUTTON_FLAGS[_physical_button(button)][1])])


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


def is_key_down(vk: int) -> bool:
    """Physical key state, regardless of which app has focus."""
    _require_windows()
    return bool(user32.GetAsyncKeyState(int(vk)) & 0x8000)


# --------------------------------------------------------------------------- #
# Windows & processes
# --------------------------------------------------------------------------- #
def _process_name(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        kernel32.CloseHandle(handle)


def window_process_name(hwnd) -> str:
    """Executable name (e.g. ``"chrome.exe"``) owning ``hwnd``; '' if unknown."""
    _require_windows()
    if not hwnd:
        return ""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return _process_name(pid.value) if pid.value else ""


def window_title(hwnd) -> str:
    _require_windows()
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def foreground_window():
    _require_windows()
    return user32.GetForegroundWindow()


def root_window_at(x: int, y: int) -> int:
    """Handle (as int) of the top-level window under a screen point, or 0."""
    _require_windows()
    hwnd = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    if not hwnd:
        return 0
    root = user32.GetAncestor(hwnd, GA_ROOT)
    return int(root or hwnd)


def make_click_through(hwnd: int) -> None:
    """Force a window to ignore all mouse input (clicks pass to what's below)."""
    if not IS_WINDOWS or not hwnd:
        return
    style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongPtrW(
        hwnd, GWL_EXSTYLE,
        style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
    )


# --------------------------------------------------------------------------- #
# Screen pixels
# --------------------------------------------------------------------------- #
def get_pixel(x: int, y: int) -> tuple[int, int, int] | None:
    """RGB colour of a screen pixel, or None if it can't be read."""
    _require_windows()
    hdc = user32.GetDC(None)
    if not hdc:
        return None
    try:
        value = gdi32.GetPixel(hdc, int(x), int(y))
    finally:
        user32.ReleaseDC(None, hdc)
    if value == CLR_INVALID:
        return None
    return value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF  # COLORREF is 0x00BBGGRR


# --------------------------------------------------------------------------- #
# Misc
# --------------------------------------------------------------------------- #
def begin_high_res_timer() -> bool:
    """Request 1 ms system timer resolution (improves sleep accuracy)."""
    if not IS_WINDOWS:
        return False
    return winmm.timeBeginPeriod(1) == 0


def end_high_res_timer() -> None:
    if IS_WINDOWS:
        winmm.timeEndPeriod(1)


def beep(start: bool) -> None:
    """Short, non-blocking system sound used as start/stop feedback."""
    if IS_WINDOWS:
        user32.MessageBeep(MB_ICONASTERISK if start else MB_OK)


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
