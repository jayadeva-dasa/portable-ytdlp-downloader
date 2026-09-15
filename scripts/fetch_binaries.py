"""Download the standalone yt-dlp release binaries for each platform into bin/.

Run this once before local testing without a pip-installed yt-dlp, and again
before packaging with PyInstaller for each OS. The app shells out to these
binaries instead of `import yt_dlp` because `yt-dlp -U` self-update only
works on the standalone release builds.
"""
import os
import stat
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(BASE_DIR, "bin")

RELEASES = {
    "yt-dlp_win.exe": "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe",
    "yt-dlp_macos": "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos",
    "yt-dlp_linux": "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_linux",
}


def main():
    os.makedirs(BIN_DIR, exist_ok=True)
    for filename, url in RELEASES.items():
        dest = os.path.join(BIN_DIR, filename)
        print(f"Downloading {filename} ...")
        urllib.request.urlretrieve(url, dest)
        if not filename.endswith(".exe"):
            st = os.stat(dest)
            os.chmod(dest, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print("Done. Binaries are in", BIN_DIR)


if __name__ == "__main__":
    main()
