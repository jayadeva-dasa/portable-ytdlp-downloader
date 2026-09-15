"""Build a single-folder executable for the current OS with PyInstaller.

Must be run per-platform (Windows build on Windows, macOS on macOS, Linux on
Linux) — PyInstaller does not cross-compile. Run scripts/fetch_binaries.py
--current-os first so bin/ has this OS's yt-dlp binary to bundle.
"""
import os
import platform
import shutil
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEP = ";" if platform.system() == "Windows" else ":"

APP_NAME = "PortableVideoDownloader"


def main():
    dist_dir = os.path.join(BASE_DIR, "dist")
    build_dir = os.path.join(BASE_DIR, "build")
    for d in (dist_dir, build_dir):
        if os.path.isdir(d):
            shutil.rmtree(d)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--onedir",
        "--noconfirm",
        "--add-data", f"ui{SEP}ui",
        "--add-data", f"bin{SEP}bin",
        "--add-data", f"ffmpeg{SEP}ffmpeg",
        os.path.join(BASE_DIR, "launcher.py"),
    ]
    subprocess.run(cmd, cwd=BASE_DIR, check=True)
    print(f"Built {APP_NAME} in {dist_dir}")


if __name__ == "__main__":
    main()
