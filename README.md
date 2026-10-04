# BleeClicker

A smart auto clicker for Windows. It sends real mouse clicks through the
Win32 `SendInput` API and has global hotkeys that work in any app.
Smart Guards decide when clicking is allowed. BleeClicker builds into one
standalone `BleeClicker.exe`, so the target PC doesn't need Python.

## Features

### Clicking
- **Left, right or middle click, or scroll up/down**, as single, double or
  triple clicks (or 1–3 scroll notches)
- **Speed** as an interval (h / m / s / ms) or as clicks per second (0.01–1000)
- **Target**: the cursor, a fixed point you pick on screen, or a
  **multi-point sequence**
- **Stop after** a number of clicks, an amount of time, or never

### Sequences
- A list of points, each with its own button, click count and delay
- **Global "add point" hotkey (F8)**: hover over a spot in any app and press
  F8. The step is added under the pointer without switching windows.
- Edit, reorder and remove steps in the table, and set how many loops to run
  (or loop forever)

### Humanize
- **Timing jitter**: each delay varies randomly by up to ±%
- **Position scatter**: fixed points land at a random spot within a radius
- **Hold duration**: each press is held down for a set time, for games that
  ignore very short clicks

### Smart Guards
- **Window Lock**: clicks only while a chosen app is in the foreground. If you
  switch away it pauses, and it resumes when you come back.
- **Pixel Trigger**: watches one screen pixel and clicks only when it shows a
  colour (or only when it doesn't), with an adjustable tolerance
- **Smart Takeover**: if you move the mouse away from where BleeClicker put
  it, clicking stops
- **Pause while I move the mouse** (cursor target): clicks wait while you move
  the mouse
- **Self-protection**: BleeClicker never clicks its own windows, so it can't
  switch itself off or change your settings by accident
- **Fail-safe corner**: move the pointer into the top-left corner of the
  screen to stop
- **Start countdown** and a **scheduled start** at a time of day

### Feedback and stats
- **Live CPS graph** (last 30 s), with a dashed target line
- **Timing accuracy**: the average lateness of each click, measured live
- Session clicks, run time, lifetime clicks and number of runs
- **Click visualizer**: an on-screen ripple wherever a click lands. It doesn't
  intercept the clicks it shows.
- **Mini HUD**: a floating pill with live status, CPS and click count. You can
  drag it, and double-clicking it opens BleeClicker.
- Sound cues when clicking starts and stops

### Control and app
- Global hotkeys you can change: **F6** start/stop, **F7** emergency stop,
  **F8** add sequence point
- **Hold-to-click** activation: clicks only while you hold the hotkey down
- **Profiles**: save, load, update and delete complete setups, and
  export/import them as JSON
- Dark, light or system theme, and **6 accent colours** (Blee, Aqua, Mint,
  Sunset, Rose, Gold)
- Tray icon, minimize to tray, keep on top. The layout adapts to the window
  size, and the sidebar collapses to icons when the window is narrow.
- Settings are saved to `%APPDATA%\BleeClicker\settings.json`. Settings from
  AutoClicker v1 are imported automatically.

## Project layout

```
Auto-Clicker/
├── run.py                   # entry point (used by PyInstaller)
├── bleeclicker/
│   ├── app.py               # QApplication setup, single-instance check, error hook
│   ├── main_window.py       # sidebar, the six pages, live dock, tray, scheduler
│   ├── engine.py            # ClickEngine worker: plans, steps, gates, guards
│   ├── widgets.py           # PowerButton, CpsGraph, ToggleSwitch, Segmented, HotkeyButton…
│   ├── overlays.py          # click-ripple visualizer + mini HUD windows
│   ├── hotkeys.py           # global hotkeys (RegisterHotKey on its own thread)
│   ├── win32.py             # ctypes: SendInput, cursor, windows, pixels, key state
│   ├── settings.py          # validated JSON settings, profiles, v1 migration
│   ├── theme.py             # design tokens, accent gradients, stylesheet
│   └── icons.py             # built-in SVG line icons
├── assets/icon.ico
├── tools/make_icon.py       # regenerates the icon (needs Pillow)
├── tests/                   # pytest (engine tests run anywhere; Win32 tests on Windows)
├── BleeClicker.spec         # PyInstaller spec (one-file, windowed)
├── version_info.txt         # Windows file-version resource
├── build.bat                # one-click build
├── requirements.txt
└── .github/workflows/build.yml   # CI: tests + builds the exe on Windows
```

## Build the .exe (on Windows)

PyInstaller has to run on Windows to produce a Windows `.exe`.

**One command:** install Python 3.10 or newer from python.org, then
double-click `build.bat` or run:

```bat
build.bat
```

**Manual:**

```bat
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pyinstaller --clean --noconfirm BleeClicker.spec
```

Both give you:

```
dist/
└── BleeClicker.exe
```

It's a single, windowed file of roughly 40–60 MB with nothing else to install.

**In the cloud:** the GitHub Actions workflow builds the exe on
`windows-latest` and uploads it as a build artifact. GitHub Actions must be
enabled for the repository, and for private repos the account needs Actions
minutes available.

## Run from source

```bat
pip install -r requirements.txt
python run.py
```

## Quick start

1. **Clicker page:** choose a button, click type and speed, then a target.
   For a fixed point, click **Pick** and point at the target within 3 seconds.
2. Press **F6**, or click the round power button. Press **F6** again or
   **F7** to stop.
3. To click several spots, open **Sequence**, hover over each spot (in any
   app) and press **F8**. Then select **Sequence** as the target.
4. Use **Smart Guards** to make it conditional: lock it to one app, or wait
   for a pixel colour.

Notes:

- Clicking starts right away (after the countdown, if you set one). If the
  pointer is over BleeClicker when you press the power button, it waits until
  you move the pointer to your target. That's self-protection at work.
- A double or triple click counts as one action for the counter and the
  click limit.
- Hotkeys: F-keys, Pause, Insert, Home/End, PageUp/PageDown and numpad keys
  work alone. Letters, digits, arrows, Space and Delete need Ctrl, Alt or Win,
  so they don't block typing in other apps.

## Limitations

- **Programs running as administrator**: Windows blocks input from normal
  programs into elevated windows. Run BleeClicker as administrator to click
  inside them. Clicks are always blocked on the UAC prompt and the lock
  screen; if that happens, BleeClicker stops with an error.
- **Antivirus**: PyInstaller one-file executables that send input are
  sometimes flagged by heuristic scanners. The build turns off UPX to reduce
  this.
- **Coordinates** are physical screen pixels, so they stay correct with
  display scaling and multiple monitors.
- Pixel Trigger reads the screen with GDI. Some full-screen exclusive games
  don't expose their pixels this way; borderless-windowed mode works.

## How it works (for maintainers)

- **Engine** (`engine.py`): a run is a `ClickPlan` made of `Step`s. One
  daemon worker thread runs it. A lock and a check that the old thread has
  finished mean two click threads can never run at once.
- **Timing**: clicks are scheduled against absolute deadlines with
  `perf_counter`. The worker waits with `Event.wait` and busy-waits only for
  the last ~1.5 ms before each click, so there's no drift and a stop takes
  effect instantly.
- **Gates** are checked before every click (Window Lock, self-protection,
  Pixel Trigger, pause-while-moving). **Guards** are checked while waiting
  (stop request, fail-safe corner, time limit, Smart Takeover, hold-key
  release).
- **Presses**: a press that is held down always gets its release in a
  `finally`, so a button can't stay stuck down.
- **GUI**: the worker never touches widgets. The GUI reads its counters and
  status about 30 times a second (CPS graph, stats, ripple, HUD), and the
  worker sends only start/stop signals.
- **Hotkeys**: `RegisterHotKey` runs on its own thread with a Win32 message
  loop, and presses reach the GUI through a Qt signal.
- **Shutdown**: closing the window stops and joins the worker, posts
  `WM_QUIT` to the hotkey thread and joins it, closes the overlays and the
  tray icon, then saves settings.
