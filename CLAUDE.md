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
   actual transfer directly. That path never prints a `[download] NN%`
   line, so `job["percent"]` doesn't move for the whole transfer — the
   frontend's stall timer (`DOWNLOAD_STALL_MS` in `ui/app.js`) covers this
   by switching to an indeterminate spinner instead of looking hung. This
   also means `cancel_download()` must kill the whole process tree, not
   just the yt-dlp PID (`_kill_process_tree` in `app/ytdlp_manager.py`) —
   the ffmpeg child doesn't die with its parent otherwise.
10. **Clip/trim downloads always use one instant, stream-copy method,
    regardless of format — there is no re-encode/frame-exact variant.**
    `_run_download_inner` never asks yt-dlp to cut during the download
    itself; it always downloads the complete video first (normal
    `[download] NN%` progress throughout, to a temp filename tagged with
    `_FULL_DOWNLOAD_MARKER`), then `_trim_clip` runs one local `ffmpeg -ss
    <start> -to <end> -i <full file> -c copy <final file>` and deletes the
    temp full download. Fast (no re-encode), but the cut lands on the
    nearest keyframe rather than the exact requested second, and — being a
    raw stream copy — it inherits whatever bitstream issues already exist
    in the source: past-livestream VODs recorded over HLS can carry small
    pre-existing NAL-framing corruption at segment-splice points (invisible
    during normal playback, since players silently conceal a bad frame, but
    caught loudly by ffmpeg's strict `-c copy` demuxer as "Invalid NAL unit
    size" with visibly missing frames in the trimmed output — nothing to do
    with this app's merge/download logic). Playlists ignore
    `clip_start`/`clip_end` entirely (no single output file to trim). Every
    clip request logs its phase-1 (download) command, the yt-dlp
    `Destination:`/`Merging formats into` lines it derives `job["filepath"]`
    from, and its phase-2 (trim) ffmpeg command/output to
    `logs/ytdlp_manager.log` (`_log()` in `app/ytdlp_manager.py`, gitignored,
    created on first use).
11. **yt-dlp silently drops characters from the filenames it *prints*
    (fullwidth punctuation, CJK, etc.) when its stdout is piped rather than
    a real console — independent of `PYTHONIOENCODING`/`PYTHONUTF8` (tried
    and confirmed to make no difference) — while still writing the real
    Unicode filename to disk.** Confirmed by direct testing against a title
    containing `：`/`｜` (fullwidth colon/vertical bar): the `Destination:`/
    `Merging formats into` lines this app parses to find the just-downloaded
    file had those characters missing entirely, producing a plausible-looking
    but wrong path — surfacing as "Download finished but the output file
    couldn't be found" on an otherwise fully successful clip download. Fix:
    `_find_full_download()` in `app/ytdlp_manager.py` never trusts that
    printed path alone for a clip request — if it doesn't exist, it falls
    back to scanning `output_dir` for the one file containing
    `_FULL_DOWNLOAD_MARKER` (an `os.listdir()` call sees the real filename
    correctly regardless of this printing quirk). The same risk applies to a
    regular (non-clip, non-playlist) download's `job["filepath"]`, which is
    parsed the same way — `_run_download_inner` verifies it with
    `os.path.isfile()` after the download finishes and, if missing, falls
    back to `_find_recent_download()` (the one file in `output_dir` modified
    at/after the download started; ambiguous — zero or multiple matches —
    still returns `None` rather than guessing wrong, since there's no
    `_FULL_DOWNLOAD_MARKER`-style tag to search for outside the clip path).
    Playlists are skipped (many files land in `output_dir` per run, so a
    newest-file guess isn't reliable). History's reveal-in-folder
    (`revealHistoryEntry` in `ui/app.js`, `POST /api/reveal`) is the main
    consumer of `job["filepath"]` for a finished job, and shows a clear
    "couldn't be found" message rather than a generic error if this
    fallback still can't resolve a real file. Any future code that needs a
    just-downloaded filename from yt-dlp's stdout should assume the same
    risk for non-ASCII titles.
12. **On Windows, `explorer /select,<path>` silently opens some unrelated
    default folder (confirmed: the user's Documents folder) instead of
    erroring, whenever `path` contains a space** — which is nearly every
    real video title, so this hit essentially every "show in folder" click,
    not an edge case. Root cause: `subprocess.run(["explorer",
    f"/select,{path}"])` passes `/select,` and `path` as one combined argv
    element; since Python's `subprocess.list2cmdline` wraps that whole
    element in quotes as soon as it contains whitespace, explorer receives
    `explorer "/select,C:\Some Folder\file.mp4"` — and explorer's own
    hand-rolled command-line parsing for `/select,` (it does not use
    standard `CommandLineToArgvW` argument splitting) can't handle the
    combined quoting and falls back to a default location instead of
    erroring, which is what made this so easy to miss in testing. Confirmed
    empirically (not just by inspection) via PowerShell's `Shell.Application`
    COM object to read the actually-opened window's `LocationURL`/
    `SelectedItems()` before and after the fix — no human needed to look at
    a screen to verify this one. Fix in `reveal_in_file_manager()`
    (`app/dialogs.py`): pass `/select,` and the path as two separate argv
    elements (`["explorer", "/select,", path]`) — neither element alone
    triggers the broken combined-quoting case — and `os.path.normpath()`
    the path first, since this app can also hand explorer a path with mixed
    forward/backslashes (e.g. an output dir from the folder-browse dialog,
    which returns forward slashes, with `os.path.join`-ed backslash path
    separators appended by yt-dlp's own output template) that explorer's
    parser has also been seen to mishandle. `reveal_in_file_manager()` now
    logs every reveal request's path and the exact command run to
    `logs/dialogs.log` (gitignored, mirrors the `_log()` pattern in
    `app/ytdlp_manager.py`) — check there first if "show in folder" ever
    opens the wrong place again, since explorer.exe returns exit code 1 on
    an entirely normal, successful `/select,` call, so the subprocess return
    code alone can't tell success from failure here.

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
