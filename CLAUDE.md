# CLAUDE.md

Guidance for working in this repository. This file is about *how* to work
here safely and effectively — for *what* the app does and why it's built
this way, see [README.md](README.md). For current/past feature work, see
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## Project in one paragraph

A self-contained, cross-platform video/audio downloader UI built on yt-dlp.
`app/server.py` (Flask) shells out to a bundled per-OS yt-dlp binary via
`app/ytdlp_manager.py` and serves the plain HTML/JS/CSS front end in `ui/`.
No build step for the front end — it's served straight from disk.

## Critical operational notes

Read these before touching backend code — each one has already caused a
confusing debugging detour in this repo's history (see
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the incidents):

1. **The dev server does not auto-reload.** `launcher.py` starts Flask with
   `use_reloader=False`. After *any* change to `app/*.py`, kill the running
   `python launcher.py` process(es) and restart it, or you'll keep testing
   against stale code. `ui/*` files (HTML/CSS/JS) *are* re-read from disk on
   every request, so no restart is needed for front-end-only changes.
2. **Check for stale duplicate processes before restarting.** They
   accumulate across debugging sessions (`Get-CimInstance Win32_Process
   -Filter "Name='python.exe'"` on Windows) and if more than one is bound
   you may be testing the wrong instance.
3. **MP3 extraction and clip/trim downloads both require ffmpeg.** Run
   `python scripts/fetch_ffmpeg.py` once if `ffmpeg/` is empty (see
   `.gitkeep` — the real binaries are never committed). Without it, these
   features download fine and then fail at the postprocessing step with
   "ffprobe and ffmpeg not found" — don't mistake that for a download bug.
   Clip range is passed as separate `clip_start`/`clip_end` request fields
   (not a format-id sentinel like the ones below) validated by
   `CLIP_TIME_RE` in `app/ytdlp_manager.py` and `parseClipTime` in
   `ui/app.js` — keep both patterns in sync if the accepted time format
   changes. Both sides also reject `clip_end <= clip_start`
   (`_clip_seconds`/`clipTimeToSeconds`) — yt-dlp doesn't error on a
   zero/negative-length `--download-sections` range, it just hangs forever.
4. **No site allowlist.** Any URL is passed straight to yt-dlp, which
   supports 1000+ sites. DRM-protected sites (Spotify, Netflix, Disney+,
   etc.) are refused by yt-dlp itself with an `ERROR: [DRM] ...` message —
   that's expected behavior, not a bug in this app.
5. **Format-id sentinel schemes** in `app/ytdlp_manager.py` — the frontend
   sends real yt-dlp format IDs *except* for two made-up conventions that
   must stay in sync between `ui/app.js` and `app/ytdlp_manager.py`:
   - `mp3:<quality>` (`best`/`320`/`256`/`192`/`128`/`96`/`64`) → triggers
     `-x --audio-format mp3 --audio-quality <tier>`.
   - `best_mp4` (playlist mode only) → forces `--merge-output-format mp4`.
6. **Before writing a plan or making assumptions about `ui/*` structure**,
   re-read the actual current files. This UI has been redesigned more than
   once (see IMPLEMENTATION_PLAN.md) and a plan written against a stale
   mental model of the HTML/JS is worse than no plan.
7. **YouTube downloads need a JS runtime (`deno`/`node`/`bun`) on PATH, or
   they can silently stall.** Without one, yt-dlp warns "No supported
   JavaScript runtime could be found" and either fails to resolve some
   formats or falls back to throttled URLs that "download" at near-zero
   speed — from the UI this looks exactly like a job stuck at "downloading —
   0%", not an error. `resolve_ytdlp_command()` in `app/ytdlp_manager.py`
   auto-detects one via `shutil.which` and adds `--js-runtimes`, but nothing
   is bundled — a genuinely fresh portable install with neither runtime on
   PATH still hits this. See "Planned: bundle a portable JS runtime" in
   IMPLEMENTATION_PLAN.md.
8. **Two downloads racing to the same output file silently corrupts it.**
   `start_download()` in `app/ytdlp_manager.py` refuses a second in-flight
   request for the same `(url, format_id, output_dir, is_playlist,
   clip_start, clip_end)` (`POST /api/download` returns 409) via the
   in-memory `_active_targets` set — but that set doesn't survive a
   restart. Combined with note 1 (killing `launcher.py` doesn't kill an
   in-flight yt-dlp/ffmpeg child, since it's not spawned in the same
   process group), restarting the server while a download is running and
   then retrying that same download from the new process can still start a
   second writer against the same path. Symptom looks nothing like a
   download bug: the file appears to finish, but `ffprobe` reports things
   like "Invalid NAL unit size" and a bogus duration. If this happens,
   delete the file and re-download — don't restart mid-download if you can
   help it.
9. **Some formats download via a child `ffmpeg` process yt-dlp spawns
   itself, not yt-dlp's own downloader.** Confirmed for HLS-only 4K
   formats (e.g. itag 625) and past-livestream VODs regardless of quality:
   yt-dlp logs `Invoking ffmpeg downloader on ...` and ffmpeg does the
   actual transfer directly (`-ss/-t/-i <url>`). That path never prints a
   `[download] NN%` line by default, but it *can* report real progress -
   `_run_download_inner` passes `--downloader-args "ffmpeg_o:-progress
   pipe:1 -nostats"` for clip downloads, and `_apply_progress_line` turns
   the resulting `out_time=` lines into a percent (`_FFMPEG_OUT_TIME_RE`) -
   but only when both `clip_start` and `clip_end` are set, since that's
   what makes the clip's total duration known. For an open-ended clip (only
   one of the two set) or a non-clip download of this format type, no
   percent is available and the frontend's stall timer
   (`DOWNLOAD_STALL_MS` in `ui/app.js`) covers the UI side instead. This
   also means `cancel_download()` must kill the whole process tree, not
   just the yt-dlp PID (`_kill_process_tree` in `app/ytdlp_manager.py`) —
   the ffmpeg child doesn't die with its parent otherwise.
10. **Clipping a merged (video+audio) format normally forces
    `--merge-output-format mp4`, which on HLS-only formats (VP9/Opus
    source) means a full CPU-bound re-encode to H.264/AAC.** For
    `want_clip and is_merge` (`fast_clip` in `_run_download_inner`), that
    forced MP4 and `--force-keyframes-at-cuts` are both skipped so ffmpeg
    can stream-copy instead — faster and lossless, but the cut lands on the
    nearest keyframe rather than the exact requested second, and the
    output stays in its native container (`.webm`/`.mkv`) instead of
    `.mp4`. Measured: the speed gain from this alone is modest — for a deep
    clip, network/seek time within the HLS stream dominates over the
    encode, not the other way round.

## Keep this file and IMPLEMENTATION_PLAN.md updated

This pair of files exists because context was lost mid-project once
already: a UI redesign (toolbar + tabs layout) happened without being
recorded anywhere durable, and a later feature plan was written against the
pre-redesign HTML structure, only caught by re-reading the files before
editing. Don't let that repeat:

- **Before implementing a new feature or non-trivial change**, write or
  update its entry in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) —
  a plan that lives only in conversation history disappears across context
  compaction or a new session.
- **Whenever a change alters** the architecture, file/element structure
  referenced above, the format-id conventions, or any "critical operational
  note" above, update **this file** in the same change.
- **Whenever a planned feature's status changes** (started, done,
  abandoned, or its assumptions went stale because something else changed
  first), update its entry in IMPLEMENTATION_PLAN.md rather than leaving it
  as-is — a stale plan will be trusted at face value in a future session.
