"""Platform-independent tests for hotkey parsing and settings."""

import json

from autoclicker.hotkeys import Hotkey
from autoclicker.settings import Settings


def test_hotkey_parse_and_format():
    assert str(Hotkey.parse("shift+ctrl+f6")) == "Ctrl+Shift+F6"
    assert Hotkey.parse("F6").vk == 0x75
    assert Hotkey.parse("Ctrl+Num+").key == "Num+"


def test_hotkey_validation():
    assert Hotkey.parse("F6").validate() is None
    assert Hotkey.parse("A").validate() is not None          # would block typing
    assert Hotkey.parse("Shift+A").validate() is not None
    assert Hotkey.parse("Ctrl+A").validate() is None


def test_settings_roundtrip_and_sanitising(tmp_path):
    path = tmp_path / "settings.json"
    s = Settings(milliseconds=250, button="right", hotkey_toggle="Ctrl+F9")
    s.save(path)
    loaded = Settings.load(path)
    assert (loaded.milliseconds, loaded.button, loaded.hotkey_toggle) == (250, "right", "Ctrl+F9")

    path.write_text(json.dumps({"milliseconds": 5000, "button": "nope", "failsafe": "yes"}))
    bad = Settings.load(path)
    assert (bad.milliseconds, bad.button, bad.failsafe) == (100, "left", True)

    path.write_text("{corrupt")
    assert Settings.load(path) == Settings()
