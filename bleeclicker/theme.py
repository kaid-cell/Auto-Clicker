"""BleeClicker design system: light/dark palettes, accent gradients, stylesheet."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

DARK = {
    "bg": "#0e1016",
    "sidebar": "#0a0c11",
    "card": "#161922",
    "card_hi": "#1c202b",
    "border": "#252a37",
    "text": "#eceff6",
    "subtext": "#8a92a6",
    "input": "#10131a",
    "input_border": "#2a3041",
    "hover": "#1f2430",
    "track": "#2b3142",
    "success": "#2ee59d",
    "warning": "#ffb020",
    "danger": "#ff5470",
    "disabled": "#5b6273",
    "shadow": "#000000",
}

LIGHT = {
    "bg": "#f3f5fa",
    "sidebar": "#e9edf5",
    "card": "#ffffff",
    "card_hi": "#f7f8fc",
    "border": "#e0e5ee",
    "text": "#131722",
    "subtext": "#5c6477",
    "input": "#f6f7fb",
    "input_border": "#d3d9e5",
    "hover": "#e3e8f2",
    "track": "#cfd5e2",
    "success": "#0fa968",
    "warning": "#d48806",
    "danger": "#e0294a",
    "disabled": "#a3aaba",
    "shadow": "#5c6477",
}

# name -> (label, primary, secondary, text-on-accent)
ACCENTS = {
    "blee":   ("Blee",   "#7c5cff", "#00d4ff", "#ffffff"),
    "aqua":   ("Aqua",   "#0aa2ff", "#00e0c6", "#ffffff"),
    "mint":   ("Mint",   "#12d39a", "#8ef08a", "#06281c"),
    "sunset": ("Sunset", "#ff7a45", "#ff3d81", "#ffffff"),
    "rose":   ("Rose",   "#ff4d8d", "#b44dff", "#ffffff"),
    "gold":   ("Gold",   "#ffb020", "#ff6a3d", "#2a1600"),
}


def system_prefers_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt < 6.5
        return False


def resolve(theme: str, accent: str = "blee") -> dict[str, str]:
    dark = theme == "dark" or (theme == "system" and system_prefers_dark())
    colors = dict(DARK if dark else LIGHT)
    _, a1, a2, at = ACCENTS.get(accent, ACCENTS["blee"])
    colors.update(accent=a1, accent2=a2, accent_text=at, is_dark="1" if dark else "")
    colors["accent_soft"] = _alpha(a1, 0.16 if dark else 0.12)
    colors["accent_line"] = _alpha(a1, 0.55)
    return colors


def _alpha(hex_color: str, a: float) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {int(a * 255)})"


def apply_theme(app: QApplication, theme: str, accent: str) -> dict[str, str]:
    c = resolve(theme, accent)
    app.setStyle("Fusion")
    pal = QPalette()
    for role, key in (
        (QPalette.Window, "bg"), (QPalette.WindowText, "text"), (QPalette.Base, "input"),
        (QPalette.AlternateBase, "card_hi"), (QPalette.Text, "text"), (QPalette.Button, "card"),
        (QPalette.ButtonText, "text"), (QPalette.Highlight, "accent"),
        (QPalette.HighlightedText, "accent_text"), (QPalette.ToolTipBase, "card"),
        (QPalette.ToolTipText, "text"), (QPalette.PlaceholderText, "subtext"),
    ):
        pal.setColor(role, QColor(c[key]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(c["disabled"]))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET.format(**c))
    return c


STYLESHEET = """
* {{ outline: none; }}
QWidget {{
    font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif;
    font-size: 10pt;
    color: {text};
}}
QMainWindow, QWidget#content, QWidget#page, QScrollArea, QScrollArea > QWidget > QWidget {{
    background: {bg};
}}
QScrollArea {{ border: none; }}

/* ---------- sidebar ---------- */
QFrame#sidebar {{ background: {sidebar}; border-right: 1px solid {border}; }}
QLabel#brand {{ font-size: 15pt; font-weight: 700; letter-spacing: 0.5px; }}
QLabel#brandSub {{ color: {subtext}; font-size: 8.5pt; }}
QPushButton#nav {{
    background: transparent; border: none; border-radius: 10px;
    text-align: left; padding: 9px 12px; color: {subtext}; font-weight: 600;
}}
QPushButton#nav:hover {{ background: {hover}; color: {text}; }}
QPushButton#nav:checked {{ background: {accent_soft}; color: {text}; }}

/* ---------- headings & text ---------- */
QLabel#pageTitle {{ font-size: 18pt; font-weight: 700; }}
QLabel#pageSub {{ color: {subtext}; }}
QLabel#cardTitle {{ font-size: 10.5pt; font-weight: 700; }}
QLabel#cardSub, QLabel#subtle {{ color: {subtext}; }}
QLabel#hint {{ color: {subtext}; font-size: 9pt; }}
QLabel#error {{ color: {danger}; font-size: 9pt; }}
QLabel#ok {{ color: {success}; font-size: 9pt; }}
QLabel#big {{ font-size: 22pt; font-weight: 700; }}
QLabel#tileValue {{ font-size: 19pt; font-weight: 700; }}
QLabel#tileLabel {{ color: {subtext}; font-size: 8.5pt; font-weight: 600; }}
QLabel#statusText {{ font-size: 12pt; font-weight: 700; }}
QLabel#badge {{
    background: {accent_soft}; color: {accent}; border-radius: 9px;
    padding: 2px 9px; font-size: 8.5pt; font-weight: 700;
}}

/* ---------- cards ---------- */
QFrame#card {{ background: {card}; border: 1px solid {border}; border-radius: 14px; }}
QFrame#dock {{ background: {card}; border-top: 1px solid {border}; }}
QFrame#tile {{ background: {card}; border: 1px solid {border}; border-radius: 14px; }}
QFrame#swatch {{ border-radius: 6px; border: 1px solid {border}; }}

/* ---------- inputs ---------- */
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QTimeEdit {{
    background: {input}; border: 1px solid {input_border}; border-radius: 8px;
    padding: 5px 10px; min-height: 20px; selection-background-color: {accent};
    selection-color: {accent_text};
}}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus, QTimeEdit:focus {{
    border: 1px solid {accent};
}}
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QLineEdit:disabled, QTimeEdit:disabled {{
    color: {disabled};
}}
QComboBox QAbstractItemView {{
    background: {card}; border: 1px solid {border}; border-radius: 8px;
    selection-background-color: {accent_soft}; selection-color: {text}; padding: 4px;
}}

/* ---------- buttons ---------- */
QPushButton {{
    background: {card_hi}; border: 1px solid {input_border}; border-radius: 9px;
    padding: 7px 14px; font-weight: 600;
}}
QPushButton:hover {{ border-color: {accent_line}; }}
QPushButton:pressed {{ background: {accent_soft}; }}
QPushButton:disabled {{ color: {disabled}; border-color: {border}; }}
QPushButton#primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {accent}, stop:1 {accent2});
    color: {accent_text}; border: none;
}}
QPushButton#primary:disabled {{ background: {track}; color: {disabled}; }}
QPushButton#danger {{ background: transparent; color: {danger}; border: 1px solid {danger}; }}
QPushButton#ghost {{ background: transparent; border: none; color: {subtext}; padding: 6px 8px; }}
QPushButton#ghost:hover {{ color: {text}; }}
QPushButton#hotkey {{ min-width: 120px; font-family: "Cascadia Mono", "Consolas", monospace; }}
QPushButton#hotkey[capturing="true"] {{ border: 1px solid {accent}; color: {accent}; }}
QPushButton#hotkey[invalid="true"] {{ border: 1px solid {danger}; color: {danger}; }}

/* segmented control */
QFrame#segbar {{ background: {input}; border: 1px solid {input_border}; border-radius: 10px; }}
QPushButton#seg {{
    background: transparent; border: none; border-radius: 7px;
    padding: 6px 10px; color: {subtext}; font-weight: 600;
}}
QPushButton#seg:hover {{ color: {text}; }}
QPushButton#seg:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {accent}, stop:1 {accent2});
    color: {accent_text};
}}
QPushButton#seg:disabled {{ color: {disabled}; }}
QPushButton#accentSwatch {{ border-radius: 14px; min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; padding: 0; }}
QPushButton#accentSwatch:checked {{ border: 3px solid {text}; }}

QRadioButton, QCheckBox {{ spacing: 8px; }}

/* ---------- tables ---------- */
QTableWidget {{
    background: {input}; border: 1px solid {input_border}; border-radius: 10px;
    gridline-color: {border}; selection-background-color: {accent_soft}; selection-color: {text};
}}
QHeaderView::section {{
    background: {card_hi}; color: {subtext}; border: none; border-bottom: 1px solid {border};
    padding: 6px; font-weight: 700; font-size: 8.5pt;
}}
QTableCornerButton::section {{ background: {card_hi}; border: none; }}
QListWidget {{
    background: {input}; border: 1px solid {input_border}; border-radius: 10px; padding: 4px;
}}
QListWidget::item {{ padding: 8px; border-radius: 7px; }}
QListWidget::item:selected {{ background: {accent_soft}; color: {text}; }}

/* ---------- misc ---------- */
QToolTip {{
    background: {card}; color: {text}; border: 1px solid {border};
    border-radius: 6px; padding: 6px;
}}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {track}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QMenu {{ background: {card}; border: 1px solid {border}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {accent_soft}; }}
"""
