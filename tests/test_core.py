"""Platform-independent tests for hotkey parsing and settings."""

import json

from bleeclicker.hotkeys import Hotkey
from bleeclicker.settings import Settings


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

    path.write_text(json.dumps({"milliseconds": 5000, "button": "nope", "failsafe": "yes",
                                "sequence": [{"x": 1, "y": 2}, {"x": "bad"}], "pixel_rgb": "red"}))
    bad = Settings.load(path)
    assert (bad.milliseconds, bad.button, bad.failsafe, bad.pixel_rgb) == (100, "left", True, "#ffffff")
    assert bad.sequence == [{"x": 1, "y": 2, "button": "left", "clicks": 1, "delay_ms": 500}]

    path.write_text("{corrupt")
    assert Settings.load(path) == Settings()


def test_v1_settings_are_migrated(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"location_mode": "fixed", "repeat_mode": "count", "repeat_count": 7}))
    s = Settings.load(path)
    assert (s.target_mode, s.stop_mode, s.stop_clicks) == ("fixed", "clicks", 7)


def test_profile_roundtrip():
    s = Settings(cps=42.0, scatter_px=9)
    prof = s.to_profile()
    fresh = Settings()
    fresh.apply_dict(prof)
    assert (fresh.cps, fresh.scatter_px) == (42.0, 9)
    assert "theme" not in prof and "profiles" not in prof
