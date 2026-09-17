"""Native OS dialogs: folder picker and reveal-in-file-manager.

Kept isolated from server.py since both spawn native UI/subprocesses that
have no meaningful unit-test coverage in this repo.
"""

import datetime
import os
import subprocess
import sys

from app.paths import get_base_dir

BASE_DIR = get_base_dir()
LOG_FILE = os.path.join(BASE_DIR, "logs", "dialogs.log")


def _log(message):
    """Best-effort debug log for reveal-in-file-manager calls - added to
    diagnose a report of the folder icon in History opening some unrelated
    default location (e.g. Documents) instead of the file's actual folder.
    Records the exact path handed to us and the exact subprocess command run
    against it, so a wrong-location report can be traced to either bad input
    (wrong path resolved upstream) or the OS command itself misbehaving on a
    path it was given correctly. Mirrors `_log()` in app/ytdlp_manager.py.
    Never raises - a logging failure must not break the reveal action."""
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except OSError:
        pass


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
    _log(
        f"reveal request: path={path!r} isfile={os.path.isfile(path)} "
        f"isdir={os.path.isdir(path)}"
    )
    try:
        if sys.platform == "win32":
            # explorer.exe does its own ad-hoc parsing of "/select," rather
            # than standard argv - subprocess.run's own quoting (via
            # list2cmdline) wraps a single "/select,<path>" list element in
            # an extra layer of quotes as soon as `path` contains a space
            # (i.e. almost every real video title), which explorer's parser
            # doesn't expect and silently falls back to some default window
            # instead of erroring - "opens Documents instead of the actual
            # file" is exactly that failure mode, not a wrong `path` value.
            # Passing "/select," and the path as two separate argv elements
            # avoids that: neither one on its own needs the broken combined
            # quoting. `os.path.normpath` additionally fixes the mixed
            # forward/backslash paths this app can otherwise hand it (an
            # output dir picked via the folder browser returns forward
            # slashes; os.path.join-ing a filename onto it then mixes
            # separators), since explorer's parser has also been seen to
            # mishandle those.
            normalized = os.path.normpath(path)
            cmd = ["explorer", "/select,", normalized]
            result = subprocess.run(cmd)
            _log(f"reveal command: {cmd!r} returncode={result.returncode}")
        elif sys.platform == "darwin":
            cmd = ["open", "-R", path]
            result = subprocess.run(cmd)
            _log(f"reveal command: {cmd!r} returncode={result.returncode}")
        else:
            target = path if os.path.isdir(path) else os.path.dirname(path)
            cmd = ["xdg-open", target]
            result = subprocess.run(cmd)
            _log(f"reveal command: {cmd!r} returncode={result.returncode}")
    except FileNotFoundError as exc:
        _log(f"reveal command raised FileNotFoundError: {exc}")
        raise RuntimeError(f"Couldn't open the file manager for this OS: {exc}") from exc
