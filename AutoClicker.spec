# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for a single-file, windowed AutoClicker.exe
#
# Build with:   pyinstaller --clean --noconfirm AutoClicker.spec
# Output:       dist/AutoClicker.exe

block_cipher = None

# Qt modules the app never imports; excluding them keeps the exe small.
EXCLUDES = [
    "tkinter", "unittest", "pydoc", "test",
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtXml", "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets", "PySide6.QtPrintSupport", "PySide6.QtDBus",
    "PySide6.QtConcurrent", "PySide6.QtSvg", "PySide6.QtSvgWidgets",
    "PySide6.QtMultimedia", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtUiTools", "PySide6.QtBluetooth", "PySide6.QtPositioning",
]

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=[("assets/icon.ico", "assets")],   # loaded at runtime for the window icon
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AutoClicker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # UPX-packed exes trigger far more antivirus false positives
    runtime_tmpdir=None,
    console=False,           # windowed app: no console window
    disable_windowed_traceback=False,
    icon="assets/icon.ico",
    version="version_info.txt",
)
