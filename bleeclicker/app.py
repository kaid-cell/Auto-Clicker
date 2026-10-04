"""Application entry point."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME, APP_VERSION, ORG_NAME, theme, win32
from .main_window import MainWindow
from .settings import SETTINGS_FILE, Settings


def resource_path(relative: str) -> Path:
    """Locate bundled resources both from source and inside a PyInstaller exe."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / relative
    return Path(__file__).resolve().parent.parent / relative


def _excepthook(exc_type, exc, tb) -> None:
    """Show unexpected errors instead of silently dying (no console in the exe)."""
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    if sys.__stderr__ is not None:  # None in a windowed (no-console) exe
        sys.__stderr__.write(text)
    if QApplication.instance() is not None:
        QMessageBox.critical(None, f"{APP_NAME} error", f"An unexpected error occurred:\n\n{exc}")


def main() -> int:
    sys.excepthook = _excepthook
    win32.set_app_user_model_id(f"{ORG_NAME}.{APP_NAME}.{APP_VERSION}")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORG_NAME)

    icon_file = resource_path("assets/icon.ico")
    icon = QIcon(str(icon_file)) if icon_file.exists() else None
    if icon is not None:
        app.setWindowIcon(icon)

    # Two instances would fight over the same global hotkeys.
    lock = win32.SingleInstanceLock(f"Local\\{ORG_NAME}.{APP_NAME}.SingleInstance")
    if lock.already_running:
        QMessageBox.information(None, APP_NAME, f"{APP_NAME} is already running.")
        return 0

    settings = Settings.load(SETTINGS_FILE)
    theme.apply_theme(app, settings.theme, settings.accent)
    window = MainWindow(settings, icon)
    window.show()
    try:
        return app.exec()
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
