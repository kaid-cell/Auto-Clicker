"""Launcher script (also the PyInstaller entry point).

Run from source with:  python run.py
"""

import sys

from bleeclicker.app import main

if __name__ == "__main__":
    sys.exit(main())
