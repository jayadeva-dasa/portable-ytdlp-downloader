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
import shutil
import signal
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

# When a video-only format is merged with a separately-downloaded audio
# track (see MP4_MERGE_FORMAT_IDS / the "<id>+bestaudio/best" format specs
# below), yt-dlp logs a "Destination:" line for each temp stream and then
# deletes both after muxing them into this final file — so this line, not
# the last "Destination:", is the one whose path actually still exists on
# disk once the download is done.
_MERGE_RE = re.compile(r'Merging formats into "(?P<path>.+)"')

# Matches one line of ffmpeg's "-progress pipe:1" output (see the
# "--downloader-args ffmpeg_o:..." flag added for clip downloads on
# HLS-only formats): "out_time=00:00:15.000000". Deliberately not
# out_time_us/out_time_ms - some ffmpeg builds report those in
# microseconds despite the "_ms" name, while out_time is an unambiguous
# timestamp string (and occasionally "N/A", which this simply won't match).
_FFMPEG_OUT_TIME_RE = re.compile(r"^out_time=(?P<hours>\d+):(?P<mins>\d{2}):(?P<secs>\d{2}(?:\.\d+)?)$")


def _parse_ffmpeg_timestamp(match):
    return int(match.group("hours")) * 3600 + int(match.group("mins")) * 60 + float(match.group("secs"))

QUALITY_PRESETS = {
    "best": "bestvideo+bestaudio/best",
    "best_mp4": "bestvideo+bestaudio/best",
    "bestvideo": "bestvideo",
    "bestaudio": "bestaudio",
    "worst": "worst",
}

# format_id values that should force yt-dlp to remux/merge into an MP4
# container (it otherwise keeps whichever container the source streams use,
# often webm) — this is what the "Video (MP4)" playlist preset maps to.
MP4_MERGE_FORMAT_IDS = {"best_mp4"}

# format_id values of the form "mp3:<quality>" mean "extract audio to MP3 at
# this quality" rather than a real yt-dlp format spec (single-video formats
# fetched from `-J` are always numeric/string format IDs, so this prefix
# never collides with a real one). Values are yt-dlp `--audio-quality`
# arguments: "0" is libmp3lame's best VBR, others are constant bitrates.
MP3_FORMAT_PREFIX = "mp3:"
MP3_QUALITIES = {
    "best": "0",
    "320": "320K",
    "256": "256K",
    "192": "192K",
    "128": "128K",
    "96": "96K",
    "64": "64K",
}

# Accepts plain seconds ("90"), "MM:SS", or "HH:MM:SS" — matches the
# client-side pattern in ui/app.js's parseClipTime(). Kept lenient (yt-dlp's
# own timestamp parser does the real validation); this just rejects garbage
# early with a clear error instead of a confusing yt-dlp failure.
CLIP_TIME_RE = re.compile(r"^\d{1,4}(:\d{1,2}){0,2}$")


def _clip_seconds(value):
    """Total seconds for an already CLIP_TIME_RE-validated "SS"/"MM:SS"/"HH:MM:SS" string."""
    total = 0
    for part in value.split(":"):
        total = total * 60 + int(part)
    return total

jobs = {}
_jobs_lock = threading.Lock()
_processes = {}  # job_id -> subprocess.Popen, kept out of `jobs` so it never hits json.dumps

# Guards against two jobs writing to the same destination file at once. A
# duplicate request (double-clicked Download, or a retry fired while the
# first attempt is still running) resolves to the identical yt-dlp output
# path; two yt-dlp/ffmpeg processes racing to write and rename that same
# path produces exactly the "[WinError 32] Unable to rename file" seen in
# the wild plus, worse, a *silently* corrupted final file (interleaved H264
# NAL units - ffprobe errors like "Invalid NAL unit size" - if both
# processes get far enough to mux before either fails). Keyed on everything
# that determines the output path/content, so a genuinely different request
# (different clip range, format, etc.) is never blocked.
_active_targets = set()


_JS_RUNTIME_NAMES = ("deno", "node", "bun")


def _detect_js_runtime():
    """YouTube's signature/"n"-parameter decryption needs a JS runtime, but
    yt-dlp only auto-enables `deno` by default (it warns "No supported
    JavaScript runtime could be found" otherwise). Without one, throttled or
    higher-quality formats don't fail outright — they resolve to broken URLs
    that transfer at near-zero speed, which just looks like a download stuck
    at 0% instead of an actual error. `node` is far more commonly already
    installed than `deno`, so it's checked too."""
    for name in _JS_RUNTIME_NAMES:
        path = shutil.which(name)
        if path:
            return f"{name}:{path}"
    return None


def resolve_ytdlp_command():
    """Bundled per-OS binary if present, else fall back to the pip package for local dev."""
    binary_name = _BINARY_NAMES.get(platform.system())
    bundled = os.path.join(BIN_DIR, binary_name) if binary_name else None
    cmd = [bundled] if bundled and os.path.isfile(bundled) else ["python3", "-m", "yt_dlp"]
    js_runtime = _detect_js_runtime()
    if js_runtime:
        cmd += ["--js-runtimes", js_runtime]
    return cmd


# Extractors that are audio-first platforms, used as a fallback signal for
# playlists: --flat-playlist never resolves per-video formats (too slow, one
# yt-dlp call per entry), so there's no vcodec to inspect like there is for a
# single video.
_AUDIO_ONLY_EXTRACTOR_HINTS = ("soundcloud", "bandcamp", "mixcloud", "audiomack", "deezer", "audius")


def _run_ytdlp_json(cmd, timeout, context):
    """Runs a `yt-dlp -J ...` inspection command and returns the parsed
    JSON. Raises RuntimeError with a message that says what actually went
    wrong (missing binary, timeout, non-zero exit, unparseable output)
    instead of letting the caller's generic `except Exception` in
    api_formats() show a bare "[WinError 2] ..." or a JSONDecodeError whose
    message doesn't mention yt-dlp at all. `context` is a short phrase like
    "this URL" or "this playlist" used in the timeout/not-found messages."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Timed out inspecting {context} (waited {timeout}s)")
    except FileNotFoundError:
        raise RuntimeError("yt-dlp binary not found (run scripts/fetch_binaries.py or install the yt-dlp package)")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"yt-dlp failed to inspect {context}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"yt-dlp returned unparseable output for {context}: {exc}") from exc


# Marks the temp file produced by phase 1 of an HLS clip download (see
# _run_hls_clip_download) so phase 2 can reliably derive the final clip
# filename from it and so a crash-interrupted temp file is recognizable if
# ever found on disk later.
_FULL_DOWNLOAD_MARKER = " [full download - temp]"


def _is_hls_format(url, format_spec):
    """True if any concrete format_id referenced by `format_spec` (e.g.
    "625+bestaudio/best" -> "625") is HLS-sourced (protocol starting with
    "m3u8"). HLS-sourced *video* is what forces yt-dlp to hand
    --download-sections off to a raw ffmpeg process seeking deep into the
    live network stream instead of fetching just the needed byte range -
    confirmed by direct testing (see "Fixed clip downloads on HLS-only
    formats" in IMPLEMENTATION_PLAN.md). Audio-only components (bestaudio,
    a plain numeric audio format_id) are never the bottleneck - YouTube
    serves those over plain HTTP even when the video track is HLS - so
    generic preset keywords like "bestaudio"/"best" simply won't match
    anything in `by_id` and are correctly ignored. Returns False (falls
    back to the direct-section path) if the lookup itself fails - this is
    an optimization, not a correctness requirement."""
    try:
        cmd = resolve_ytdlp_command() + ["-J", "--no-playlist", url]
        info = _run_ytdlp_json(cmd, timeout=60, context="this URL")
    except RuntimeError:
        return False
    by_id = {f.get("format_id"): f for f in info.get("formats", [])}
    format_ids = format_spec.split("+") if isinstance(format_spec, str) else []
    return any((by_id.get(fid) or {}).get("protocol", "").startswith("m3u8") for fid in format_ids)


def _run_hls_clip_download(job_id, url, format_spec, output_dir, is_merge, clip_start, clip_end, clip_suffix):
    """Downloads the full video (yt-dlp's own efficient downloader - real
    "[download] NN%" progress, no deep network seeking) and then trims the
    requested clip locally with a stream-copy ffmpeg call. User-chosen
    trade-off for HLS-only formats (4K, past-livestream VODs) after
    diagnosing that seeking directly into the remote HLS stream (the
    previous approach) is what made these clips take minutes: uses far more
    bandwidth/disk (the whole video, not just the clip's slice) but avoids
    the slow/unreliable deep seek entirely - a local trim only takes as
    long as it takes to mux, typically seconds."""
    full_template = os.path.join(output_dir, f"%(title)s{_FULL_DOWNLOAD_MARKER}.%(ext)s")
    cmd = resolve_ytdlp_command() + [
        "--newline",
        "-f", format_spec,
        "-o", full_template,
        "--file-access-retries", "10",
        "--retry-sleep", "file_access:exp=1:20",
        "--no-playlist",
    ]
    if is_merge:
        cmd += ["--merge-output-format", "mp4"]
    if os.path.isdir(FFMPEG_DIR) and os.listdir(FFMPEG_DIR):
        cmd += ["--ffmpeg-location", FFMPEG_DIR]
    cmd.append(url)

    with _jobs_lock:
        jobs[job_id]["status"] = "downloading"

    output_lines = []
    try:
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True
        )
        _processes[job_id] = process
        for line in process.stdout:
            output_lines.append(line.rstrip("\n"))
            _apply_progress_line(job_id, line)
        process.wait()
    except FileNotFoundError:
        with _jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = "yt-dlp binary not found (run scripts/fetch_binaries.py or install the yt-dlp package)"
        return
    except Exception as exc:
        with _jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = str(exc)
        return
    finally:
        _processes.pop(job_id, None)

    with _jobs_lock:
        job = jobs[job_id]
        if job["status"] == "cancelled":
            return  # cancel_download() already set the final state
        if process.returncode != 0:
            job["status"] = "error"
            job["error"] = _extract_error_message(output_lines) or f"yt-dlp exited with code {process.returncode}"
            return
        full_path = job["filepath"]

    if not full_path or not os.path.isfile(full_path):
        with _jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = "Download finished but the output file couldn't be found"
        return

    base, ext = os.path.splitext(full_path)
    if base.endswith(_FULL_DOWNLOAD_MARKER):
        base = base[: -len(_FULL_DOWNLOAD_MARKER)]
    final_path = f"{base}{clip_suffix}{ext}"

    with _jobs_lock:
        jobs[job_id]["status"] = "clipping"
        jobs[job_id]["percent"] = 100
        jobs[job_id]["speed"] = None
        jobs[job_id]["eta"] = None

    ffmpeg_bin = os.path.join(FFMPEG_DIR, "ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg")
    if not os.path.isfile(ffmpeg_bin):
        ffmpeg_bin = "ffmpeg"  # fall back to PATH
    start_seconds = _clip_seconds(clip_start) if clip_start else 0
    trim_cmd = [ffmpeg_bin, "-y", "-ss", str(start_seconds)]
    if clip_end:
        trim_cmd += ["-t", str(_clip_seconds(clip_end) - start_seconds)]
    trim_cmd += ["-i", full_path, "-c", "copy", final_path]

    trim_output_lines = []
    try:
        process = subprocess.Popen(
            trim_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True
        )
        _processes[job_id] = process
        for line in process.stdout:
            trim_output_lines.append(line.rstrip("\n"))
        process.wait()
    except Exception as exc:
        with _jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = f"Local clip trim failed: {exc}. The full download is kept at {full_path}"
        return
    finally:
        _processes.pop(job_id, None)

    with _jobs_lock:
        job = jobs[job_id]
        if job["status"] == "cancelled":
            return
        if process.returncode != 0:
            job["status"] = "error"
            job["error"] = (
                f"Local clip trim failed (exit {process.returncode}). "
                f"The full download is kept at {full_path}: "
                + (trim_output_lines[-1].strip() if trim_output_lines else "")
            )
            return
        job["status"] = "finished"
        job["percent"] = 100
        job["filepath"] = final_path

    # Best-effort - the clip is already written and correct either way, so a
    # locked/undeletable temp file (e.g. still scanned by AV) isn't fatal.
    try:
        os.remove(full_path)
    except OSError:
        pass


def list_formats(url, is_playlist=False):
    if is_playlist:
        cmd = resolve_ytdlp_command() + ["-J", "--flat-playlist", url]
        info = _run_ytdlp_json(cmd, timeout=60, context="this playlist")
        entries = info.get("entries", [])
        extractor = (info.get("extractor") or info.get("extractor_key") or "").lower()
        is_audio_source = any(hint in extractor for hint in _AUDIO_ONLY_EXTRACTOR_HINTS)
        return {
            "is_playlist": True,
            "title": info.get("title") or "Playlist",
            "entry_count": len(entries),
            "entries": [e.get("title") for e in entries[:10]],
            "is_audio_source": is_audio_source,
        }

    cmd = resolve_ytdlp_command() + ["-J", "--no-playlist", url]
    info = _run_ytdlp_json(cmd, timeout=60, context="this URL")
    formats = [
        {
            "format_id": f.get("format_id"),
            "ext": f.get("ext"),
            "resolution": f.get("resolution") or f.get("format_note") or "audio only",
            "filesize": f.get("filesize") or f.get("filesize_approx"),
            "vcodec": f.get("vcodec"),
            "acodec": f.get("acodec"),
            "height": f.get("height"),
            "fps": f.get("fps"),
            "abr": f.get("abr"),
        }
        for f in info.get("formats", [])
    ]
    is_audio_source = bool(formats) and all(f["vcodec"] in (None, "none") for f in formats)
    return {
        "is_playlist": False,
        "title": info.get("title"),
        "formats": formats,
        "is_audio_source": is_audio_source,
    }


def start_download(url, format_id, output_dir, is_playlist=False, clip_start=None, clip_end=None):
    target_key = (url, format_id, os.path.abspath(output_dir), is_playlist, clip_start, clip_end)
    with _jobs_lock:
        if target_key in _active_targets:
            return None
        _active_targets.add(target_key)

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
        target=_run_download,
        args=(job_id, url, format_id, output_dir, is_playlist, clip_start, clip_end, target_key),
        daemon=True,
    )
    thread.start()
    return job_id


def _run_download(job_id, url, format_id, output_dir, is_playlist, clip_start, clip_end, target_key):
    try:
        _run_download_inner(job_id, url, format_id, output_dir, is_playlist, clip_start, clip_end)
    finally:
        with _jobs_lock:
            _active_targets.discard(target_key)


def _run_download_inner(job_id, url, format_id, output_dir, is_playlist, clip_start, clip_end):
    os.makedirs(output_dir, exist_ok=True)

    for label, value in (("start", clip_start), ("end", clip_end)):
        if value and not CLIP_TIME_RE.match(value):
            with _jobs_lock:
                jobs[job_id]["status"] = "error"
                jobs[job_id]["error"] = f"Invalid clip {label} time: {value!r}"
            return
    # A zero-or-negative-length --download-sections range (e.g. start ==
    # end) isn't rejected by yt-dlp - it just hangs indefinitely instead of
    # erroring, which looks identical to the "stuck at 0%" bug this was
    # already mistaken for once (see IMPLEMENTATION_PLAN.md).
    if clip_start and clip_end and _clip_seconds(clip_start) >= _clip_seconds(clip_end):
        with _jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = "Clip end must be after clip start"
        return

    want_mp3 = isinstance(format_id, str) and format_id.startswith(MP3_FORMAT_PREFIX)
    mp3_quality = MP3_QUALITIES.get(format_id[len(MP3_FORMAT_PREFIX):], "0") if want_mp3 else None
    want_clip = bool(clip_start or clip_end)
    # Must include the actual range, not just a bare " [clip]" tag - otherwise
    # two clip downloads of the same title with different start/end (a very
    # normal thing to do while trimming to find the right range) collide on
    # one output path and each new attempt overwrites/deletes the last, so an
    # earlier "finished" History entry ends up pointing at a file that no
    # longer exists or belongs to a different range. ":" is stripped since
    # it's illegal in Windows filenames (clip_start/clip_end use "MM:SS").
    clip_suffix = (
        f" [clip {(clip_start or '0').replace(':', '-')}-{(clip_end or 'end').replace(':', '-')}]"
        if want_clip
        else ""
    )

    if is_playlist:
        format_spec = "bestaudio/best" if want_mp3 else QUALITY_PRESETS.get(format_id, QUALITY_PRESETS["best"])
        out_template = os.path.join(
            output_dir, "%(playlist_title)s", f"%(playlist_index)s - %(title)s{clip_suffix}.%(ext)s"
        )
    else:
        format_spec = "bestaudio/best" if want_mp3 else (format_id or QUALITY_PRESETS["best"])
        out_template = os.path.join(output_dir, f"%(title)s{clip_suffix}.%(ext)s")

    is_merge = format_id in MP4_MERGE_FORMAT_IDS or (isinstance(format_id, str) and "+" in format_id)

    # Clipping an HLS-sourced format normally means yt-dlp seeking deep into
    # the *live network stream* via a raw ffmpeg-as-downloader process,
    # which measured minutes and could even fail outright (TLS handshake
    # timeouts talking to Google's manifest server - see "Fixed downloads
    # silently stalling"/"Fixed clip downloads on HLS-only formats" in
    # IMPLEMENTATION_PLAN.md). User-chosen trade-off after that diagnosis:
    # download the full video with yt-dlp's normal (fast, reliable)
    # downloader, then trim locally - see _run_hls_clip_download. Skipped
    # for playlists (format specs there are presets like "bestvideo+bestaudio",
    # not concrete IDs _is_hls_format can resolve) and MP3 extraction
    # (audio-only; YouTube serves audio over plain HTTP even when the video
    # track is HLS, so it was never the slow part).
    if want_clip and not want_mp3 and not is_playlist and _is_hls_format(url, format_spec):
        _run_hls_clip_download(job_id, url, format_spec, output_dir, is_merge, clip_start, clip_end, clip_suffix)
        return

    cmd = resolve_ytdlp_command() + [
        "--newline",
        "-f", format_spec,
        "-o", out_template,
        # Windows AV/indexing can transiently hold the final rename target
        # open right after it's written; give that more time to clear
        # instead of yt-dlp's default 3 quick retries (see the WinError 32
        # "Unable to rename file" incident this was added for).
        "--file-access-retries", "10",
        "--retry-sleep", "file_access:exp=1:20",
    ]
    # Clipping a merged video+audio format normally forces the pieces into
    # MP4 via --merge-output-format, which (for a non-HLS source that still
    # needs a codec conversion to fit) can mean a slower re-encode. Skipping
    # the forced MP4 (and --force-keyframes-at-cuts, which forces its own
    # re-encode) lets ffmpeg stream-copy instead where possible - at the
    # cost of the cut landing on the nearest keyframe rather than the exact
    # requested second, and the output staying in its native container
    # (webm/mkv, via %(ext)s) instead of always .mp4. Only the non-HLS path
    # still reaches here - see the HLS branch above for the other case.
    fast_clip = want_clip and is_merge
    if want_mp3:
        cmd += ["-x", "--audio-format", "mp3", "--audio-quality", mp3_quality]
    elif is_merge and not fast_clip:
        cmd += ["--merge-output-format", "mp4"]
    if want_clip:
        cmd += ["--download-sections", f"*{clip_start or '0'}-{clip_end or 'inf'}"]
        if not fast_clip:
            cmd.append("--force-keyframes-at-cuts")
        # Some non-HLS section downloads still route through ffmpeg as an
        # external downloader too (not just the HLS case above), and that
        # path never prints a "[download] NN%" line at all. Asking ffmpeg
        # itself for machine-readable progress (verified against the real
        # binary: clean newline-terminated "out_time=HH:MM:SS.ffffff" /
        # "progress=..." lines, doesn't affect the download) lets
        # _apply_progress_line compute a real percent instead of leaving the
        # UI on a bare "waiting for data" spinner for however long it takes.
        cmd += ["--downloader-args", "ffmpeg_o:-progress pipe:1 -nostats"]
    if not is_playlist:
        cmd.append("--no-playlist")
    if os.path.isdir(FFMPEG_DIR) and os.listdir(FFMPEG_DIR):
        cmd += ["--ffmpeg-location", FFMPEG_DIR]
    cmd.append(url)

    with _jobs_lock:
        jobs[job_id]["status"] = "downloading"

    # The raw "downloading" status covers yt-dlp's own [download] progress
    # lines; once those stop (the file itself is fully fetched) and yt-dlp
    # moves on to ffmpeg post-processing, surface *what* that post-processing
    # step is doing instead of leaving the UI stuck on "downloading — 100%".
    # Priority mirrors what a clip request actually goes through: the section
    # gets trimmed first, then (if requested) the trimmed file is converted.
    post_status = "clipping" if want_clip else "converting" if want_mp3 else "merging" if is_merge else None

    # Only computable when both ends of the clip are given - needed to turn
    # the ffmpeg-as-downloader "out_time=" lines above into a percent.
    clip_duration = (
        _clip_seconds(clip_end) - _clip_seconds(clip_start)
        if clip_start and clip_end
        else None
    )

    output_lines = []
    download_started = False
    post_status_applied = False
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            # Puts yt-dlp in its own process group so cancel_download() can
            # kill it *and* any ffmpeg child it spawns together - see
            # _kill_process_tree.
            start_new_session=True,
        )
        _processes[job_id] = process
        for line in process.stdout:
            output_lines.append(line.rstrip("\n"))
            is_progress = _apply_progress_line(job_id, line, clip_duration)
            if is_progress:
                download_started = True
            elif download_started and not post_status_applied and post_status and line.strip():
                with _jobs_lock:
                    job = jobs.get(job_id)
                    if job and job["status"] == "downloading":
                        job["status"] = post_status
                post_status_applied = True
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
                job["error"] = _extract_error_message(output_lines) or (
                    f"yt-dlp exited with code {process.returncode}"
                )
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
        _kill_process_tree(process)
    return True


def _kill_process_tree(process):
    """process.terminate() alone only kills the top-level yt-dlp process.
    For some clip qualities (confirmed: HLS-only 4K formats) yt-dlp hands
    the actual transfer to a child ffmpeg process it spawns directly
    (`Invoking ffmpeg downloader on ...`) rather than downloading it itself
    - terminating just the parent leaves that child running orphaned,
    which is what made a cancelled job look like it was still in progress
    (it silently kept running - and, worse, kept writing to the same
    output path a retry would then also write to, the same corruption
    class as "Fixed silently corrupted output from duplicate concurrent
    downloads" in IMPLEMENTATION_PLAN.md). `_run_download_inner` starts the
    process in its own process group (`start_new_session=True`) so the
    whole tree can be killed together here."""
    if platform.system() == "Windows":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.kill()
    except OSError:
        pass


def _extract_error_message(output_lines):
    """Pull yt-dlp's own ERROR: line out of its captured output, since that's
    far more useful than a bare exit code (e.g. a missing-ffmpeg failure)."""
    error_lines = [line.strip() for line in output_lines if line.strip().startswith("ERROR:")]
    if error_lines:
        return error_lines[-1]
    return output_lines[-1].strip() if output_lines else None


def _apply_progress_line(job_id, line, clip_duration=None):
    """Updates job progress fields from one line of yt-dlp output. Returns
    True if the line carried real progress info - either a "[download] NN%"
    line, or (when `clip_duration` is known) one of the "out_time=..." lines
    ffmpeg emits when it's the one doing the download (see the
    "--downloader-args ffmpeg_o:-progress pipe:1" flag in
    _run_download_inner) - used by the caller to tell raw downloading apart
    from later post-processing."""
    match = _PROGRESS_RE.search(line)
    ffmpeg_match = None
    if not match and clip_duration:
        ffmpeg_match = _FFMPEG_OUT_TIME_RE.match(line.strip())
    with _jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return bool(match) or bool(ffmpeg_match)
        if match:
            job["percent"] = float(match.group("percent"))
            job["speed"] = match.group("speed")
            job["eta"] = match.group("eta")
        elif ffmpeg_match:
            elapsed = _parse_ffmpeg_timestamp(ffmpeg_match)
            job["percent"] = min(100.0, round(elapsed / clip_duration * 100, 1))
            job["speed"] = None
            job["eta"] = None
        merge_match = _MERGE_RE.search(line)
        if merge_match:
            job["filepath"] = merge_match.group("path")
        elif "Destination:" in line:
            job["filepath"] = line.split("Destination:", 1)[1].strip()
    return bool(match) or bool(ffmpeg_match)


def get_job(job_id):
    with _jobs_lock:
        job = jobs.get(job_id)
        return dict(job) if job is not None else None


def run_self_update():
    """Returns a {returncode, output} dict even on failure - api_update()
    just forwards this as JSON, so errors need to live in the return value,
    not an exception (the global Flask error handler would still catch a
    raised one, but this keeps failure and success on the same shape the
    frontend already expects instead of a 500 for what's really just "the
    update check didn't work")."""
    cmd = resolve_ytdlp_command() + ["-U"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "output": "Update check timed out after 120s."}
    except FileNotFoundError:
        return {"returncode": -1, "output": "yt-dlp binary not found - run scripts/fetch_binaries.py."}
    except OSError as exc:
        return {"returncode": -1, "output": f"Couldn't run yt-dlp: {exc}"}
    return {
        "returncode": result.returncode,
        "output": (result.stdout + result.stderr).strip(),
    }
