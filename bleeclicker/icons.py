"""Tiny built-in line-icon set (24x24 SVG), tinted to the current theme."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PATHS = {
    "clicker": '<path d="M7 3l11 9-5 1 3 6-2.5 1.2-3-6L7 18z"/>',
    "sequence": '<circle cx="5" cy="6" r="2"/><circle cx="5" cy="18" r="2"/><circle cx="19" cy="12" r="2"/>'
                '<path d="M7 6h5l5 5M7 18h5l5-5"/>',
    "smart": '<path d="M12 3l7 3v5c0 5-3 8.5-7 10-4-1.5-7-5-7-10V6z"/><path d="M9 12l2 2 4-4"/>',
    "profiles": '<path d="M6 3h12v18l-6-4-6 4z"/>',
    "stats": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1'
                'M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>',
    "crosshair": '<circle cx="12" cy="12" r="8"/><path d="M12 2v5M12 17v5M2 12h5M17 12h5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    "up": '<path d="M12 19V5M6 11l6-6 6 6"/>',
    "down": '<path d="M12 5v14M6 13l6 6 6-6"/>',
    "save": '<path d="M5 3h11l3 3v15H5z"/><path d="M8 3v5h7V3M8 21v-7h8v7"/>',
    "load": '<path d="M12 3v12M7 10l5 5 5-5M4 21h16"/>',
    "window": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/>',
    "pixel": '<path d="M12 3c3 4 6 7.5 6 11a6 6 0 0 1-12 0c0-3.5 3-7 6-11z"/>',
    "hud": '<rect x="3" y="8" width="18" height="8" rx="4"/><circle cx="8" cy="12" r="1.5"/>',
    "folder": '<path d="M3 6h6l2 2h10v11H3z"/>',
    "reset": '<path d="M4 4v6h6"/><path d="M5.5 15a7 7 0 1 0 1-8L4 10"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
}


def icon(name: str, color: str, size: int = 20) -> QIcon:
    """Render a named icon in ``color`` (hi-DPI aware)."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        f'{_PATHS[name]}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    result = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        renderer.render(p, QRectF(0, 0, size * scale, size * scale))
        p.end()
        pm.setDevicePixelRatio(scale)
        result.addPixmap(pm)
    return result
