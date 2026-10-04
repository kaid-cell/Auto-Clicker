"""Persistent settings stored as JSON in %APPDATA%\\BleeClicker\\settings.json."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Callable

from . import APP_NAME


def _config_root() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def settings_dir() -> Path:
    return _config_root() / APP_NAME


SETTINGS_FILE = settings_dir() / "settings.json"
LEGACY_FILE = _config_root() / "AutoClicker" / "settings.json"   # v1 location


# --------------------------------------------------------------------------- #
# Validators: each returns the cleaned value or raises ValueError.
# --------------------------------------------------------------------------- #
def _choice(*options: str) -> Callable[[Any], str]:
    def check(v):
        if v in options:
            return v
        raise ValueError
    return check


def _int(lo: int, hi: int) -> Callable[[Any], int]:
    def check(v):
        if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi:
            return v
        raise ValueError
    return check


def _float(lo: float, hi: float) -> Callable[[Any], float]:
    def check(v):
        if isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi:
            return float(v)
        raise ValueError
    return check


def _bool(v):
    if isinstance(v, bool):
        return v
    raise ValueError


def _str(maxlen: int = 200) -> Callable[[Any], str]:
    def check(v):
        if isinstance(v, str) and len(v) <= maxlen:
            return v
        raise ValueError
    return check


def _regex(pattern: str) -> Callable[[Any], str]:
    rx = re.compile(pattern)

    def check(v):
        if isinstance(v, str) and rx.fullmatch(v):
            return v
        raise ValueError
    return check


def _optional_int(v):
    if v is None or (isinstance(v, int) and not isinstance(v, bool)):
        return v
    raise ValueError


BUTTONS = ("left", "right", "middle", "wheel_up", "wheel_down")
_step_button = _choice(*BUTTONS)
_coord = _int(-32768, 32767)


def _sequence(v):
    if not isinstance(v, list):
        raise ValueError
    out = []
    for item in v[:500]:
        if not isinstance(item, dict):
            continue
        try:
            out.append({
                "x": _coord(item["x"]),
                "y": _coord(item["y"]),
                "button": _step_button(item.get("button", "left")),
                "clicks": _int(1, 10)(item.get("clicks", 1)),
                "delay_ms": _int(1, 86_400_000)(item.get("delay_ms", 500)),
            })
        except (KeyError, ValueError):
            continue
    return out


ACCENTS = ("blee", "aqua", "mint", "sunset", "rose", "gold")

SPEC: dict[str, Callable[[Any], Any]] = {
    "button": _step_button,
    "click_mode": _choice("single", "double", "triple"),
    "speed_mode": _choice("interval", "cps"),
    "hours": _int(0, 23),
    "minutes": _int(0, 59),
    "seconds": _int(0, 59),
    "milliseconds": _int(0, 999),
    "cps": _float(0.01, 1000.0),
    "target_mode": _choice("current", "fixed", "sequence"),
    "fixed_x": _coord,
    "fixed_y": _coord,
    "sequence": _sequence,
    "sequence_loops": _int(0, 1_000_000),
    "stop_mode": _choice("never", "clicks", "time"),
    "stop_clicks": _int(1, 100_000_000),
    "stop_seconds": _int(1, 86_400),
    "jitter_pct": _int(0, 90),
    "scatter_px": _int(0, 500),
    "hold_ms": _int(0, 10_000),
    "start_delay_s": _int(0, 60),
    "schedule_enabled": _bool,
    "schedule_time": _regex(r"([01]\d|2[0-3]):[0-5]\d"),
    "hotkey_toggle": _str(40),
    "hotkey_emergency": _str(40),
    "hotkey_add_point": _str(40),
    "activation": _choice("toggle", "hold"),
    "failsafe": _bool,
    "takeover_stop": _bool,
    "pause_while_moving": _bool,
    "window_lock_enabled": _bool,
    "window_lock_exe": _str(260),
    "pixel_enabled": _bool,
    "pixel_x": _coord,
    "pixel_y": _coord,
    "pixel_rgb": _regex(r"#[0-9a-fA-F]{6}"),
    "pixel_tolerance": _int(0, 255),
    "pixel_mode": _choice("match", "differ"),
    "theme": _choice("system", "light", "dark"),
    "accent": _choice(*ACCENTS),
    "ripple": _bool,
    "sounds": _bool,
    "always_on_top": _bool,
    "mini_hud": _bool,
    "minimize_to_tray": _bool,
    "window_x": _optional_int,
    "window_y": _optional_int,
    "window_w": _optional_int,
    "window_h": _optional_int,
    "stats_lifetime_clicks": _int(0, 10**15),
    "stats_runs": _int(0, 10**12),
    "stats_longest_s": _float(0, 10**9),
    "last_page": _int(0, 10),
}

# Settings captured in a profile (the "what and how to click" part).
PROFILE_KEYS = (
    "button", "click_mode", "speed_mode", "hours", "minutes", "seconds", "milliseconds", "cps",
    "target_mode", "fixed_x", "fixed_y", "sequence", "sequence_loops", "stop_mode", "stop_clicks",
    "stop_seconds", "jitter_pct", "scatter_px", "hold_ms", "start_delay_s", "takeover_stop",
    "pause_while_moving", "window_lock_enabled", "window_lock_exe", "pixel_enabled", "pixel_x",
    "pixel_y", "pixel_rgb", "pixel_tolerance", "pixel_mode",
)


@dataclass
class Settings:
    button: str = "left"
    click_mode: str = "single"
    speed_mode: str = "interval"
    hours: int = 0
    minutes: int = 0
    seconds: int = 0
    milliseconds: int = 100
    cps: float = 10.0
    target_mode: str = "current"
    fixed_x: int = 0
    fixed_y: int = 0
    sequence: list = field(default_factory=list)
    sequence_loops: int = 0
    stop_mode: str = "never"
    stop_clicks: int = 100
    stop_seconds: int = 60
    jitter_pct: int = 0
    scatter_px: int = 0
    hold_ms: int = 0
    start_delay_s: int = 0
    schedule_enabled: bool = False
    schedule_time: str = "09:00"
    hotkey_toggle: str = "F6"
    hotkey_emergency: str = "F7"
    hotkey_add_point: str = "F8"
    activation: str = "toggle"
    failsafe: bool = True
    takeover_stop: bool = True
    pause_while_moving: bool = False
    window_lock_enabled: bool = False
    window_lock_exe: str = ""
    pixel_enabled: bool = False
    pixel_x: int = 0
    pixel_y: int = 0
    pixel_rgb: str = "#ffffff"
    pixel_tolerance: int = 10
    pixel_mode: str = "match"
    theme: str = "dark"
    accent: str = "blee"
    ripple: bool = True
    sounds: bool = True
    always_on_top: bool = False
    mini_hud: bool = True
    minimize_to_tray: bool = False
    window_x: int | None = None
    window_y: int | None = None
    window_w: int | None = None
    window_h: int | None = None
    stats_lifetime_clicks: int = 0
    stats_runs: int = 0
    stats_longest_s: float = 0.0
    last_page: int = 0
    profiles: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    def apply_dict(self, data: dict) -> None:
        """Copy every valid known key from ``data``; invalid values are ignored."""
        for f in fields(self):
            if f.name in data and f.name in SPEC:
                try:
                    setattr(self, f.name, SPEC[f.name](data[f.name]))
                except ValueError:
                    pass

    def to_profile(self) -> dict:
        data = asdict(self)
        return {k: data[k] for k in PROFILE_KEYS}

    @classmethod
    def load(cls, path: Path = SETTINGS_FILE) -> "Settings":
        """Load settings, falling back to defaults for anything invalid."""
        settings = cls()
        if not path.exists() and path == SETTINGS_FILE and LEGACY_FILE.exists():
            try:  # one-time import of AutoClicker v1 settings
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(LEGACY_FILE, path)
            except OSError:
                pass
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return settings
        if not isinstance(data, dict):
            return settings
        # v1 used different names for two settings.
        if "location_mode" in data and "target_mode" not in data:
            data["target_mode"] = data["location_mode"]
        if data.get("repeat_mode") == "count" and "stop_mode" not in data:
            data["stop_mode"], data["stop_clicks"] = "clicks", data.get("repeat_count", 100)
        settings.apply_dict(data)
        profiles = data.get("profiles")
        if isinstance(profiles, dict):
            for name, prof in list(profiles.items())[:200]:
                if isinstance(name, str) and 0 < len(name) <= 60 and isinstance(prof, dict):
                    settings.profiles[name] = prof
        return settings

    def save(self, path: Path = SETTINGS_FILE) -> None:
        """Write atomically so a crash mid-write never corrupts the file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.replace(tmp, path)
