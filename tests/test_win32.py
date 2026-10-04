"""Sanity checks for the Win32 layer. Run on Windows:  python -m pytest tests"""

import ctypes
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def test_input_struct_size():
    from autoclicker import win32
    assert ctypes.sizeof(win32.INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)


def test_cursor_roundtrip():
    from autoclicker import win32
    left, top, width, height = win32.virtual_screen_rect()
    x, y = left + width // 2, top + height // 2
    win32.set_cursor_pos(x, y)
    assert win32.get_cursor_pos() == (x, y)
    assert win32.point_on_any_monitor(x, y)


def test_send_click_does_not_raise():
    from autoclicker import win32
    win32.send_click("middle", 1)


def test_hotkey_register_and_unregister():
    from autoclicker.hotkeys import Hotkey, HotkeyListener
    listener = HotkeyListener(lambda _id: None)
    listener.start()
    try:
        results = listener.set_hotkeys({1: Hotkey.parse("Ctrl+Alt+Shift+F11")})
        assert results == {1: None}
        assert listener.set_hotkeys({}) == {}
    finally:
        listener.stop()


def test_engine_clicks_with_real_sendinput():
    from PySide6.QtCore import QCoreApplication
    from autoclicker.clicker import ClickConfig, ClickEngine
    app = QCoreApplication.instance() or QCoreApplication([])
    engine = ClickEngine()
    engine.start(ClickConfig(button="middle", interval_ms=10, max_clicks=5, failsafe=False))
    deadline = time.time() + 3
    while engine.running and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    engine.shutdown()
    assert engine.click_count == 5
