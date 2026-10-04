"""Persistent settings stored as JSON in %APPDATA%\\AutoClicker\\settings.json."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import APP_NAME


def settings_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


SETTINGS_FILE = settings_dir() / "settings.json"


@dataclass
class Settings:
    button: str = "left"
    click_mode: str = "single"          # single | double
    hours: int = 0
    minutes: int = 0
    seconds: int = 0
    milliseconds: int = 100
    location_mode: str = "current"      # current | fixed
    fixed_x: int = 0
    fixed_y: int = 0
    repeat_mode: str = "unlimited"      # unlimited | count
    repeat_count: int = 100
    hotkey_toggle: str = "F6"
    hotkey_emergency: str = "F7"
    failsafe: bool = True
    always_on_top: bool = False
    theme: str = "system"               # system | light | dark
    window_x: int | None = None
    window_y: int | None = None

    # Allowed values / ranges used to sanitise whatever is loaded from disk.
    _CHOICES = {
        "button": ("left", "right", "middle"),
        "click_mode": ("single", "double"),
        "location_mode": ("current", "fixed"),
        "repeat_mode": ("unlimited", "count"),
        "theme": ("system", "light", "dark"),
    }
    _RANGES = {
        "hours": (0, 23),
        "minutes": (0, 59),
        "seconds": (0, 59),
        "milliseconds": (0, 999),
        "fixed_x": (-32768, 32767),
        "fixed_y": (-32768, 32767),
        "repeat_count": (1, 10_000_000),
    }

    @classmethod
    def load(cls, path: Path = SETTINGS_FILE) -> "Settings":
        """Load settings, silently falling back to defaults for bad values."""
        settings = cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return settings
        if not isinstance(data, dict):
            return settings

        for f in fields(cls):
            if f.name not in data:
                continue
            value = data[f.name]
            default = getattr(settings, f.name)
            if f.name in cls._CHOICES:
                if value in cls._CHOICES[f.name]:
                    setattr(settings, f.name, value)
            elif f.name in cls._RANGES:
                lo, hi = cls._RANGES[f.name]
                if isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi:
                    setattr(settings, f.name, value)
            elif isinstance(default, bool):
                if isinstance(value, bool):
                    setattr(settings, f.name, value)
            elif f.name in ("window_x", "window_y"):
                if value is None or (isinstance(value, int) and not isinstance(value, bool)):
                    setattr(settings, f.name, value)
            elif isinstance(default, str) and isinstance(value, str):
                setattr(settings, f.name, value)
        return settings

    def save(self, path: Path = SETTINGS_FILE) -> None:
        """Write atomically so a crash mid-write never corrupts the file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.replace(tmp, path)
