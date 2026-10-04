"""Engine behaviour tests with the Win32 layer faked (run on any OS)."""

import time

import pytest
from PySide6.QtCore import QCoreApplication

from bleeclicker import win32
from bleeclicker.engine import ClickEngine, ClickPlan, PixelTrigger, Step, StopReason


@pytest.fixture
def fake(monkeypatch):
    state = {"log": [], "cur": [500, 500], "fg": "game.exe", "root": 0, "pixel": (255, 0, 0), "key": True}

    def click(button, n=1):
        state["log"].append(("click", button, n, tuple(state["cur"]), time.perf_counter()))

    def setpos(x, y):
        state["cur"][:] = [x, y]

    for name, value in {
        "IS_WINDOWS": True,
        "send_click": click,
        "button_down": lambda b: state["log"].append(("down", b, time.perf_counter())),
        "button_up": lambda b: state["log"].append(("up", b, time.perf_counter())),
        "get_cursor_pos": lambda: tuple(state["cur"]),
        "set_cursor_pos": setpos,
        "virtual_screen_rect": lambda: (0, 0, 1920, 1080),
        "begin_high_res_timer": lambda: False,
        "foreground_window": lambda: 1,
        "window_process_name": lambda h: state["fg"],
        "root_window_at": lambda x, y: state["root"],
        "get_pixel": lambda x, y: state["pixel"],
        "is_key_down": lambda vk: state["key"],
    }.items():
        monkeypatch.setattr(win32, name, value)
    return state


@pytest.fixture
def engine():
    app = QCoreApplication.instance() or QCoreApplication([])
    eng = ClickEngine()
    eng.reasons = []
    eng.stopped.connect(lambda _rid, why: eng.reasons.append(why))

    def pump(seconds):
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            time.sleep(0.003)

    eng.pump = pump
    yield eng
    eng.shutdown()


def clicks(state):
    return [e for e in state["log"] if e[0] == "click"]


def run(engine, plan, seconds):
    engine.start(plan)
    engine.pump(seconds)
    engine.stop()
    engine.pump(0.05)


def test_sequence_runs_in_order_and_stops_after_loops(fake, engine):
    seq = (Step(10, 10, "left", 1, 20), Step(20, 20, "right", 2, 20), Step(30, 30, "wheel_up", 3, 20))
    run(engine, ClickPlan(seq, max_cycles=2, failsafe=False), 0.4)
    got = [(e[1], e[2], e[3]) for e in clicks(fake)]
    assert got == [("left", 1, (10, 10)), ("right", 2, (20, 20)), ("wheel_up", 3, (30, 30))] * 2
    assert engine.reasons[-1] == StopReason.CYCLES


def test_click_limit_is_exact(fake, engine):
    run(engine, ClickPlan((Step(delay_ms=5),), max_clicks=7), 0.3)
    assert len(clicks(fake)) == 7 and engine.reasons[-1] == StopReason.COMPLETED


def test_no_clicks_after_stop(fake, engine):
    engine.start(ClickPlan((Step(delay_ms=2),)))
    engine.pump(0.1)
    engine.stop()
    n = len(clicks(fake))
    engine.pump(0.15)
    assert len(clicks(fake)) == n


def test_smart_takeover_stops(fake, engine):
    engine.start(ClickPlan((Step(100, 100, "left", 1, 10),), takeover_stop=True))
    engine.pump(0.08)
    fake["cur"][:] = [300, 300]
    engine.pump(0.1)
    assert engine.reasons[-1] == StopReason.TAKEOVER


def test_window_lock_and_self_protection_gate_clicks(fake, engine):
    fake["fg"] = "other.exe"
    run(engine, ClickPlan((Step(delay_ms=5),), window_lock="game.exe"), 0.15)
    assert clicks(fake) == []
    fake["fg"], fake["root"] = "game.exe", 77
    run(engine, ClickPlan((Step(delay_ms=5),), protected_hwnds=frozenset({77})), 0.15)
    assert clicks(fake) == []


def test_pixel_trigger(fake, engine):
    trig = PixelTrigger(5, 5, (0, 255, 0), 10, "match")
    engine.start(ClickPlan((Step(delay_ms=5),), pixel=trig))
    engine.pump(0.1)
    assert clicks(fake) == []
    fake["pixel"] = (5, 250, 3)
    engine.pump(0.1)
    assert len(clicks(fake)) > 3


def test_hold_duration_always_releases(fake, engine):
    engine.start(ClickPlan((Step(delay_ms=1000),), hold_ms=5000))
    engine.pump(0.05)
    engine.stop()
    engine.pump(0.05)
    assert [e[0] for e in fake["log"]] == ["down", "up"]


def test_hold_to_click_key_release(fake, engine):
    engine.start(ClickPlan((Step(delay_ms=10),), hold_vk=0x75))
    engine.pump(0.08)
    fake["key"] = False
    engine.pump(0.08)
    assert engine.reasons[-1] == StopReason.RELEASED


def test_scatter_stays_in_radius(fake, engine):
    run(engine, ClickPlan((Step(500, 500, "left", 1, 5),), scatter_px=20), 0.2)
    pts = [e[3] for e in clicks(fake)]
    assert all(((x - 500) ** 2 + (y - 500) ** 2) ** 0.5 <= 21 for x, y in pts)
    assert len(set(pts)) > 3


def test_failsafe_corner(fake, engine):
    engine.start(ClickPlan((Step(delay_ms=10),), failsafe=True))
    engine.pump(0.05)
    fake["cur"][:] = [0, 0]
    engine.pump(0.05)
    assert engine.reasons[-1] == StopReason.FAILSAFE


@pytest.mark.parametrize("plan", [
    ClickPlan(()), ClickPlan((Step(button="x"),)), ClickPlan((Step(delay_ms=0),)),
    ClickPlan((Step(),), jitter_pct=95),
])
def test_invalid_plans_rejected(fake, engine, plan):
    with pytest.raises(ValueError):
        engine.start(plan)
