"""Light/dark themes built on Qt's Fusion style plus a stylesheet."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

LIGHT = {
    "bg": "#f3f3f3",
    "card": "#ffffff",
    "border": "#e1e1e1",
    "text": "#1b1b1b",
    "subtext": "#5f5f5f",
    "input": "#ffffff",
    "input_border": "#c9c9c9",
    "hover": "#f0f0f0",
    "accent": "#0067c0",
    "accent_hover": "#1975c5",
    "accent_text": "#ffffff",
    "danger": "#c42b1c",
    "danger_hover": "#d13c2e",
    "success": "#0f7b0f",
    "disabled": "#a0a0a0",
}

DARK = {
    "bg": "#202020",
    "card": "#2b2b2b",
    "border": "#3a3a3a",
    "text": "#f3f3f3",
    "subtext": "#a8a8a8",
    "input": "#323232",
    "input_border": "#474747",
    "hover": "#3a3a3a",
    "accent": "#4cc2ff",
    "accent_hover": "#62cbff",
    "accent_text": "#000000",
    "danger": "#ff6b5e",
    "danger_hover": "#ff8277",
    "success": "#6ccb5f",
    "disabled": "#6e6e6e",
}


def system_prefers_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt < 6.5
        return False


def resolve(theme: str) -> dict[str, str]:
    if theme == "dark" or (theme == "system" and system_prefers_dark()):
        return DARK
    return LIGHT


def apply_theme(app: QApplication, theme: str) -> dict[str, str]:
    c = resolve(theme)
    app.setStyle("Fusion")

    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(c["bg"]))
    pal.setColor(QPalette.WindowText, QColor(c["text"]))
    pal.setColor(QPalette.Base, QColor(c["input"]))
    pal.setColor(QPalette.AlternateBase, QColor(c["card"]))
    pal.setColor(QPalette.Text, QColor(c["text"]))
    pal.setColor(QPalette.Button, QColor(c["card"]))
    pal.setColor(QPalette.ButtonText, QColor(c["text"]))
    pal.setColor(QPalette.Highlight, QColor(c["accent"]))
    pal.setColor(QPalette.HighlightedText, QColor(c["accent_text"]))
    pal.setColor(QPalette.ToolTipBase, QColor(c["card"]))
    pal.setColor(QPalette.ToolTipText, QColor(c["text"]))
    pal.setColor(QPalette.PlaceholderText, QColor(c["subtext"]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(c["disabled"]))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET.format(**c))
    return c


STYLESHEET = """
QWidget {{
    font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif;
    font-size: 10pt;
    color: {text};
}}
QMainWindow, QWidget#root {{ background: {bg}; }}

QFrame#card {{
    background: {card};
    border: 1px solid {border};
    border-radius: 8px;
}}
QLabel#cardTitle {{ font-size: 10.5pt; font-weight: 600; }}
QLabel#appTitle {{ font-size: 15pt; font-weight: 600; }}
QLabel#subtle, QLabel#hint {{ color: {subtext}; }}
QLabel#hint {{ font-size: 9pt; }}
QLabel#counter {{ font-size: 17pt; font-weight: 600; }}
QLabel#statusText {{ font-weight: 600; }}
QLabel#error {{ color: {danger}; font-size: 9pt; }}

QComboBox, QSpinBox, QLineEdit {{
    background: {input};
    border: 1px solid {input_border};
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 20px;
}}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{ border: 1px solid {accent}; }}
QComboBox:disabled, QSpinBox:disabled {{ color: {disabled}; }}
QComboBox QAbstractItemView {{
    background: {card};
    border: 1px solid {border};
    selection-background-color: {accent};
    selection-color: {accent_text};
    outline: none;
}}

QPushButton {{
    background: {input};
    border: 1px solid {input_border};
    border-radius: 4px;
    padding: 6px 14px;
}}
QPushButton:hover {{ background: {hover}; }}
QPushButton:disabled {{ color: {disabled}; }}
QPushButton#hotkey {{ font-weight: 600; min-width: 110px; }}
QPushButton#hotkey[capturing="true"] {{ border: 1px solid {accent}; color: {accent}; }}
QPushButton#hotkey[invalid="true"] {{ border: 1px solid {danger}; }}

QPushButton#start {{
    background: {accent}; color: {accent_text}; border: none;
    font-weight: 600; font-size: 11pt; padding: 9px 22px;
}}
QPushButton#start:hover {{ background: {accent_hover}; }}
QPushButton#stop {{
    background: {danger}; color: #ffffff; border: none;
    font-weight: 600; font-size: 11pt; padding: 9px 22px;
}}
QPushButton#stop:hover {{ background: {danger_hover}; }}
QPushButton#start:disabled, QPushButton#stop:disabled {{
    background: {border}; color: {disabled};
}}

QRadioButton, QCheckBox {{ spacing: 7px; }}
QToolTip {{
    background: {card}; color: {text};
    border: 1px solid {border}; padding: 5px;
}}
QStatusBar {{ background: {bg}; color: {subtext}; }}
QScrollArea {{ border: none; background: transparent; }}
"""
