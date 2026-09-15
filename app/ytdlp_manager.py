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

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(BASE_DIR, "bin")

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

jobs = {}
_jobs_lock = threading.Lock()


def resolve_ytdlp_command():
    """Bundled per-OS binary if present, else fall back to the pip package for local dev."""
    binary_name = _BINARY_NAMES.get(platform.system())
    if binary_name:
        bundled = os.path.join(BIN_DIR, binary_name)
        if os.path.isfile(bundled):
            return [bundled]
    return ["python3", "-m", "yt_dlp"]


def list_formats(url):
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
    return {"title": info.get("title"), "formats": formats}


def start_download(url, format_id, output_dir):
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
    thread = threading.Thread(target=_run_download, args=(job_id, url, format_id, output_dir), daemon=True)
    thread.start()
    return job_id


def _run_download(job_id, url, format_id, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    ffmpeg_dir = os.path.join(BASE_DIR, "ffmpeg")
    cmd = resolve_ytdlp_command() + [
        "--newline",
        "-f", format_id or "bestvideo+bestaudio/best",
        "-o", os.path.join(output_dir, "%(title)s.%(ext)s"),
    ]
    if os.path.isdir(ffmpeg_dir) and os.listdir(ffmpeg_dir):
        cmd += ["--ffmpeg-location", ffmpeg_dir]
    cmd.append(url)

    with _jobs_lock:
        jobs[job_id]["status"] = "downloading"

    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in process.stdout:
            _apply_progress_line(job_id, line)
        process.wait()
        with _jobs_lock:
            if process.returncode == 0:
                jobs[job_id]["status"] = "finished"
                jobs[job_id]["percent"] = 100
            else:
                jobs[job_id]["status"] = "error"
                jobs[job_id]["error"] = f"yt-dlp exited with code {process.returncode}"
    except FileNotFoundError:
        with _jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = "yt-dlp binary not found (run scripts/fetch_binaries.py or install the yt-dlp package)"
    except Exception as exc:  # subprocess/IO failures during the download
        with _jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = str(exc)


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
