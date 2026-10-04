# AutoClicker

A compact Windows auto clicker built with Python and PySide6 (Qt 6). It sends
real mouse clicks with the Win32 `SendInput` API, and its global hotkeys work
while other programs have focus. It packages into one standalone
`AutoClicker.exe`, so the target PC doesn't need Python.

## Features

- Left, right or middle click, as single or double clicks
- Interval in hours, minutes, seconds and milliseconds (1 ms to 23:59:59.999)
- Click at the current mouse position, or at a fixed X/Y position, with a
  **Capture Position** button (3-second countdown)
- Unlimited clicks, or stop after a custom number of clicks
- Global **Start/Stop hotkey** (default **F6**) that you can change
- Three ways to stop in an emergency:
  - **Emergency stop hotkey** (default **F7**). It only ever stops clicking.
  - **Fail-safe corner**: move the mouse into the top-left corner of the screen.
  - The **STOP** button
- A status light and a live click counter
- Light, dark or system theme, and a "keep window on top" option
- Settings saved to `%APPDATA%\AutoClicker\settings.json`
- Only one copy can run at a time, so two copies never fight over the hotkeys

## Project layout

```
Auto-Clicker/
├── run.py                  # entry point (used by PyInstaller)
├── autoclicker/
│   ├── __init__.py         # app name / version
│   ├── __main__.py         # allows `python -m autoclicker`
│   ├── app.py              # QApplication setup, single-instance check, error hook
│   ├── main_window.py      # the GUI
│   ├── widgets.py          # Card, HotkeyButton (key recorder), StatusDot
│   ├── clicker.py          # ClickEngine: the background click worker thread
│   ├── hotkeys.py          # global hotkeys (RegisterHotKey on its own thread)
│   ├── win32.py            # ctypes bindings: SendInput, cursor, timers, mutex
│   ├── settings.py         # JSON settings with validation
│   └── theme.py            # light/dark palettes + stylesheet
├── assets/icon.ico         # app / exe icon
├── tools/make_icon.py      # regenerates the icon (optional, needs Pillow)
├── tests/                  # pytest tests (Win32 tests run only on Windows)
├── AutoClicker.spec        # PyInstaller spec (one-file, windowed)
├── version_info.txt        # Windows file-version resource for the exe
├── build.bat               # one-click build script
├── requirements.txt
└── .github/workflows/build.yml  # CI: tests + builds the exe on Windows
```

## Run from source

You need Windows 10 or 11 and Python 3.10 or newer (64-bit recommended).

```bat
cd Auto-Clicker
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

## Build the .exe

### Option A: one command

Double-click `build.bat`, or run it from a Command Prompt:

```bat
build.bat
```

It creates a virtual environment, installs the requirements and runs PyInstaller.

### Option B: manual

```bat
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pyinstaller --clean --noconfirm AutoClicker.spec
```

Either option produces:

```
dist/
└── AutoClicker.exe
```

This is a single-file, windowed executable (roughly 40–60 MB) with no other files
needed. Copy it anywhere and double-click it.

If you'd rather not use the spec file, this command gives an equivalent build:

```bat
pyinstaller --noconfirm --clean --onefile --windowed --name AutoClicker ^
  --icon assets\icon.ico --add-data "assets\icon.ico;assets" ^
  --version-file version_info.txt run.py
```

### Build in the cloud

The included GitHub Actions workflow runs the tests on `windows-latest`, builds
the exe and checks that it starts. It then uploads `AutoClicker.exe` as a build
artifact under the **Actions** tab.

## Using the app

1. Choose the click type, the click mode and the interval.
2. Choose a click location. For a fixed position, click **Capture Position**,
   point at the target within 3 seconds, and the X/Y fields fill in.
3. Choose **Unlimited**, or **Custom** with a number of clicks.
4. Press **F6**, or click **START**. Press **F6** again, or **F7**, or click
   **STOP**, to stop.

Tips:

- To change a hotkey, click the hotkey button, then press the new combination.
  **Esc** cancels. F-keys, Pause, Insert, Home/End, PageUp/PageDown and numpad
  keys work alone. Letters, digits, arrows, Space and Delete need **Ctrl**,
  **Alt** or **Win**, so they don't block normal typing in other programs.
- If a hotkey is already taken by another program, the app tells you and
  highlights it in red. Pick a different one.
- The first click happens one interval after you start. A double click counts
  as one click action for both the counter and the click limit.
- While clicking runs, the click settings are locked. Stop clicking to change them.

## Notes and limitations

- **Programs running as administrator**: Windows blocks a normal-privilege
  program from sending input to elevated windows (UIPI). To click inside an
  elevated program, run `AutoClicker.exe` as administrator too. Clicks are also
  blocked on secure screens such as the UAC prompt and the lock screen. If that
  happens, clicking stops with an error message.
- **Antivirus false positives**: PyInstaller one-file executables, especially
  ones that send input, are sometimes flagged by heuristic scanners. The build
  turns off UPX compression to keep this rare. If the exe gets quarantined,
  restore it or add an exclusion.
- **Timing**: the worker raises the Windows timer resolution to 1 ms while it
  runs. It schedules each click against an absolute deadline, so errors don't
  build up over time, and it busy-waits only for the last ~1.5 ms before each
  click. Intervals are typically accurate to well under a millisecond. Very
  short intervals (1–5 ms) depend on system load.
- **Coordinates** are physical screen pixels, so they stay correct with
  display scaling and multiple monitors. (0, 0) is the top-left of the primary
  monitor. Monitors to the left of or above it have negative coordinates.

## How it works (for maintainers)

- **Clicking** (`clicker.py`): `ClickEngine` runs one daemon worker thread. A
  lock and a check that the old thread has finished keep two click threads from
  ever running at once. Stopping sets a `threading.Event`. The worker waits
  with `Event.wait`, so a stop wakes it instantly, and it checks the flag again
  right before every click, so no click happens after a stop. Each click's
  down/up events go out in one `SendInput` call, so a button can never stay
  stuck down.
- **GUI updates**: the worker never touches widgets. It reports start and stop
  through Qt signals, which Qt delivers to the GUI thread as queued events. The
  GUI reads the click counter every 50 ms, so fast clicking can't flood the
  event loop.
- **Hotkeys** (`hotkeys.py`): `RegisterHotKey` runs on a dedicated thread with
  its own Win32 message loop. `WM_HOTKEY` messages are forwarded to the GUI
  through a Qt signal. Hotkeys are paused while you record a new one, otherwise
  Windows would swallow the key press.
- **Shutdown**: closing the window stops the worker (and waits for it to
  finish), posts `WM_QUIT` to the hotkey thread and joins it, then saves the
  settings.
