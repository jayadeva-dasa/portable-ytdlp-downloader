"""Base-directory resolution that works both from source and inside a
PyInstaller-frozen build (where files live under sys._MEIPASS instead of
next to this source file)."""
import os
import sys


def get_base_dir():
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
