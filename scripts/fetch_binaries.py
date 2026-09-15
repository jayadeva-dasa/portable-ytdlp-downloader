"""Download the standalone yt-dlp release binaries into bin/.

Run this once before local testing without a pip-installed yt-dlp, and again
before packaging with PyInstaller for each OS. The app shells out to these
binaries instead of `import yt_dlp` because `yt-dlp -U` self-update only
works on the standalone release builds.

By default downloads all three platform binaries (handy for local dev, e.g.
testing the resolution fallback logic). Pass --current-os in CI to fetch only
the binary this runner actually needs.
"""
import argparse
import os
import platform
import stat
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(BASE_DIR, "bin")

RELEASES = {
    "yt-dlp_win.exe": "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe",
    "yt-dlp_macos": "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos",
    "yt-dlp_linux": "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_linux",
}

_CURRENT_OS_BINARY = {
    "Windows": "yt-dlp_win.exe",
    "Darwin": "yt-dlp_macos",
    "Linux": "yt-dlp_linux",
}


def download(filename, url):
    dest = os.path.join(BIN_DIR, filename)
    print(f"Downloading {filename} ...")
    urllib.request.urlretrieve(url, dest)
    if not filename.endswith(".exe"):
        st = os.stat(dest)
        os.chmod(dest, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--current-os",
        action="store_true",
        help="Only fetch the binary for the OS this script is running on (used in CI)",
    )
    args = parser.parse_args()

    os.makedirs(BIN_DIR, exist_ok=True)

    if args.current_os:
        filename = _CURRENT_OS_BINARY.get(platform.system())
        if not filename:
            raise SystemExit(f"Unsupported platform: {platform.system()}")
        download(filename, RELEASES[filename])
    else:
        for filename, url in RELEASES.items():
            download(filename, url)

    print("Done. Binaries are in", BIN_DIR)


if __name__ == "__main__":
    main()
