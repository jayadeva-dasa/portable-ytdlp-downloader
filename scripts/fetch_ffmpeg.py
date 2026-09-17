"""Download a static ffmpeg/ffprobe pair into ffmpeg/.

MP3 extraction (`yt-dlp -x --audio-format mp3`) shells out to ffmpeg for the
transcode step; without it yt-dlp downloads the audio fine and then fails at
postprocessing with "ffprobe and ffmpeg not found". ytdlp_manager.py already
passes `--ffmpeg-location ffmpeg/` whenever that directory is non-empty, so
dropping the two binaries in there is all that's needed.

Not committed for the same reason bin/ isn't: large, platform-specific
binaries that don't belong in git history.
"""
import argparse
import io
import os
import platform
import stat
import tarfile
import urllib.request
import zipfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG_DIR = os.path.join(BASE_DIR, "ffmpeg")

# BtbN publishes a rolling "latest" release tag for Windows/Linux static
# builds; evermeet.cx does the same for macOS via a redirect-to-versioned-zip
# endpoint, so all three URLs stay valid without pinning a version here.
_SOURCES = {
    "Windows": {
        "url": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
        "archive": "zip",
        "members": {"ffmpeg.exe": "bin/ffmpeg.exe", "ffprobe.exe": "bin/ffprobe.exe"},
    },
    "Linux": {
        "url": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz",
        "archive": "tar",
        "members": {"ffmpeg": "bin/ffmpeg", "ffprobe": "bin/ffprobe"},
    },
    "Darwin": {
        "urls": {
            "ffmpeg": "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip",
            "ffprobe": "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip",
        },
        "archive": "zip-per-file",
    },
}


def _extract_from_zip(data, members, dest_dir):
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        for out_name, suffix in members.items():
            match = next((n for n in names if n.replace("\\", "/").endswith(suffix)), None)
            if match is None:
                raise SystemExit(f"Could not find {suffix} inside the downloaded archive")
            with zf.open(match) as src, open(os.path.join(dest_dir, out_name), "wb") as dst:
                dst.write(src.read())


def _extract_from_tar(data, members, dest_dir):
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as tf:
        names = tf.getnames()
        for out_name, suffix in members.items():
            match = next((n for n in names if n.endswith(suffix)), None)
            if match is None:
                raise SystemExit(f"Could not find {suffix} inside the downloaded archive")
            src = tf.extractfile(match)
            with open(os.path.join(dest_dir, out_name), "wb") as dst:
                dst.write(src.read())


def fetch_current_os():
    system = platform.system()
    source = _SOURCES.get(system)
    if not source:
        raise SystemExit(f"Unsupported platform: {system}")

    os.makedirs(FFMPEG_DIR, exist_ok=True)

    if source["archive"] == "zip-per-file":
        for out_name, url in source["urls"].items():
            print(f"Downloading {out_name} ...")
            data = urllib.request.urlopen(url).read()
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                inner = zf.namelist()[0]
                with zf.open(inner) as src, open(os.path.join(FFMPEG_DIR, out_name), "wb") as dst:
                    dst.write(src.read())
    else:
        print(f"Downloading ffmpeg/ffprobe for {system} ...")
        data = urllib.request.urlopen(source["url"]).read()
        if source["archive"] == "zip":
            _extract_from_zip(data, source["members"], FFMPEG_DIR)
        else:
            _extract_from_tar(data, source["members"], FFMPEG_DIR)

    if system != "Windows":
        for name in ("ffmpeg", "ffprobe"):
            path = os.path.join(FFMPEG_DIR, name)
            st = os.stat(path)
            os.chmod(path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    print("Done. ffmpeg/ffprobe are in", FFMPEG_DIR)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    fetch_current_os()
