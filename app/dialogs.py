"""Native OS dialogs: folder picker and reveal-in-file-manager.

Kept isolated from server.py since both spawn native UI/subprocesses that
have no meaningful unit-test coverage in this repo.
"""

import os
import subprocess
import sys


def browse_for_folder():
    """Open a native folder picker. Returns the chosen path, or None if cancelled.

    Raises RuntimeError with a clear message on environments where tkinter
    itself can't come up (e.g. no display on a headless/remote session) -
    left uncaught, that would otherwise surface as a raw TclError/ImportError
    whose message doesn't say what actually failed.
    """
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError as exc:
        raise RuntimeError(f"Folder picker unavailable (tkinter not installed): {exc}") from exc

    try:
        root = tkinter.Tk()
    except Exception as exc:
        raise RuntimeError(f"Folder picker unavailable: {exc}") from exc
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory()
    finally:
        root.destroy()
    return path or None


def reveal_in_file_manager(path):
    """Open the OS file manager at `path` (selecting it, where supported).

    Raises RuntimeError if the OS-specific file manager command isn't
    available, instead of letting a bare FileNotFoundError (just "[WinError
    2] The system cannot find the file specified" with no indication *which*
    file - it's the command, not `path`) reach the caller.
    """
    try:
        if sys.platform == "win32":
            subprocess.run(["explorer", f"/select,{path}"])
        elif sys.platform == "darwin":
            subprocess.run(["open", "-R", path])
        else:
            target = path if os.path.isdir(path) else os.path.dirname(path)
            subprocess.run(["xdg-open", target])
    except FileNotFoundError as exc:
        raise RuntimeError(f"Couldn't open the file manager for this OS: {exc}") from exc
