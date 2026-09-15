"""Resolves the yt-dlp binary and drives it as a subprocess.

We shell out to the standalone yt-dlp executable rather than importing
yt_dlp as a Python library because only the standalone release binary
supports `yt-dlp -U` self-update in place. That's also why the bundled
binary always wins over any fallback here.
"""
import json
import os
import platform
import re
import subprocess
import threading
import uuid

from app.paths import get_base_dir

BASE_DIR = get_base_dir()
BIN_DIR = os.path.join(BASE_DIR, "bin")
FFMPEG_DIR = os.path.join(BASE_DIR, "ffmpeg")

_BINARY_NAMES = {
    "Windows": "yt-dlp_win.exe",
    "Darwin": "yt-dlp_macos",
    "Linux": "yt-dlp_linux",
}

_PROGRESS_RE = re.compile(
    r"\[download\]\s+(?P<percent>[\d.]+)%"
    r"(?:\s+of\s+(?P<size>[\w.~]+))?"
    r"(?:\s+at\s+(?P<speed>[\w./]+))?"
    r"(?:\s+ETA\s+(?P<eta>[\d:]+))?"
)

QUALITY_PRESETS = {
    "best": "bestvideo+bestaudio/best",
    "bestvideo": "bestvideo",
    "bestaudio": "bestaudio",
    "worst": "worst",
}

jobs = {}
_jobs_lock = threading.Lock()
_processes = {}  # job_id -> subprocess.Popen, kept out of `jobs` so it never hits json.dumps


def resolve_ytdlp_command():
    """Bundled per-OS binary if present, else fall back to the pip package for local dev."""
    binary_name = _BINARY_NAMES.get(platform.system())
    if binary_name:
        bundled = os.path.join(BIN_DIR, binary_name)
        if os.path.isfile(bundled):
            return [bundled]
    return ["python3", "-m", "yt_dlp"]


def list_formats(url, is_playlist=False):
    if is_playlist:
        cmd = resolve_ytdlp_command() + ["-J", "--flat-playlist", url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "yt-dlp failed to inspect this playlist")
        info = json.loads(result.stdout)
        entries = info.get("entries", [])
        return {
            "is_playlist": True,
            "title": info.get("title") or "Playlist",
            "entry_count": len(entries),
            "entries": [e.get("title") for e in entries[:10]],
        }

    cmd = resolve_ytdlp_command() + ["-J", "--no-playlist", url]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "yt-dlp failed to inspect this URL")

    info = json.loads(result.stdout)
    formats = [
        {
            "format_id": f.get("format_id"),
            "ext": f.get("ext"),
            "resolution": f.get("resolution") or f.get("format_note") or "audio only",
            "filesize": f.get("filesize") or f.get("filesize_approx"),
            "vcodec": f.get("vcodec"),
            "acodec": f.get("acodec"),
        }
        for f in info.get("formats", [])
    ]
    return {"is_playlist": False, "title": info.get("title"), "formats": formats}


def start_download(url, format_id, output_dir, is_playlist=False):
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        jobs[job_id] = {
            "status": "starting",
            "percent": 0,
            "speed": None,
            "eta": None,
            "error": None,
            "filepath": None,
        }
    thread = threading.Thread(
        target=_run_download, args=(job_id, url, format_id, output_dir, is_playlist), daemon=True
    )
    thread.start()
    return job_id


def _run_download(job_id, url, format_id, output_dir, is_playlist):
    os.makedirs(output_dir, exist_ok=True)

    if is_playlist:
        format_spec = QUALITY_PRESETS.get(format_id, QUALITY_PRESETS["best"])
        out_template = os.path.join(output_dir, "%(playlist_title)s", "%(playlist_index)s - %(title)s.%(ext)s")
    else:
        format_spec = format_id or QUALITY_PRESETS["best"]
        out_template = os.path.join(output_dir, "%(title)s.%(ext)s")

    cmd = resolve_ytdlp_command() + ["--newline", "-f", format_spec, "-o", out_template]
    if not is_playlist:
        cmd.append("--no-playlist")
    if os.path.isdir(FFMPEG_DIR) and os.listdir(FFMPEG_DIR):
        cmd += ["--ffmpeg-location", FFMPEG_DIR]
    cmd.append(url)

    with _jobs_lock:
        jobs[job_id]["status"] = "downloading"

    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        _processes[job_id] = process
        for line in process.stdout:
            _apply_progress_line(job_id, line)
        process.wait()
        with _jobs_lock:
            job = jobs[job_id]
            if job["status"] == "cancelled":
                pass  # cancel_download() already set the final state
            elif process.returncode == 0:
                job["status"] = "finished"
                job["percent"] = 100
            else:
                job["status"] = "error"
                job["error"] = f"yt-dlp exited with code {process.returncode}"
    except FileNotFoundError:
        with _jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = "yt-dlp binary not found (run scripts/fetch_binaries.py or install the yt-dlp package)"
    except Exception as exc:  # subprocess/IO failures during the download
        with _jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = str(exc)
    finally:
        _processes.pop(job_id, None)


def cancel_download(job_id):
    process = _processes.get(job_id)
    with _jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return False
        if job["status"] in ("finished", "error", "cancelled"):
            return False
        job["status"] = "cancelled"
        job["error"] = "Cancelled by user"
    if process is not None:
        process.terminate()
    return True


def _apply_progress_line(job_id, line):
    match = _PROGRESS_RE.search(line)
    with _jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return
        if match:
            job["percent"] = float(match.group("percent"))
            job["speed"] = match.group("speed")
            job["eta"] = match.group("eta")
        if "Destination:" in line:
            job["filepath"] = line.split("Destination:", 1)[1].strip()


def get_job(job_id):
    with _jobs_lock:
        job = jobs.get(job_id)
        return dict(job) if job is not None else None


def run_self_update():
    cmd = resolve_ytdlp_command() + ["-U"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return {
        "returncode": result.returncode,
        "output": (result.stdout + result.stderr).strip(),
    }
