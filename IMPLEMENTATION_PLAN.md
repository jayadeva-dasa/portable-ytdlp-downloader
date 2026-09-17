# Implementation Plan & Status

Companion to [CLAUDE.md](CLAUDE.md) (architecture/operational notes for this
repo). This file tracks feature work: what's shipped, what's planned, and
what's stale and needs re-checking before it's trusted.

## How to use this file

- **Before implementing** a new feature (or right as you start), add a
  `## Planned: <name>` section below using the same shape as existing
  entries (Context / Approach / Files / Status). Do this even for work
  requested mid-conversation — don't let the plan exist only in chat
  history.
- **Update the Status line** as work moves: `Not started` → `In progress` →
  `Done (<date>)` → or `Abandoned (<reason>)`.
- **If something else changes first and invalidates a planned entry's
  assumptions** (e.g. a UI redesign lands before a pending plan is
  implemented), mark that entry `Stale — needs re-scoping` and say what
  changed, instead of deleting it or leaving it looking current.
- **When you finish a feature**, move its entry from "Planned" to
  "Shipped" with a one-line summary and the key files touched — enough for
  a future session to find the code, not a full changelog.
- If a change here also affects an operational note or architectural fact
  in CLAUDE.md, update that file too, in the same change.

## Shipped

- **Automatic port fallback on launch** — `launcher.py` (`_find_open_port`)
  probes `127.0.0.1:5000`..`5004` and binds Flask to the first free one
  instead of crashing with "Address already in use" / "Port 5000 is in
  use". Needed because this app's users are expected to be non-technical
  (double-click launch, no terminal literacy assumed) and a raw port-bind
  traceback is not actionable for them — a stale duplicate process (see
  CLAUDE.md note 2) or an unrelated app on 5000 would otherwise block
  launch entirely. Only tries 5 ports; if all are taken it still raises a
  plain-language `SystemExit` rather than pretending success.
- **MP3 extraction**, multiple bitrate tiers (best VBR, 320/256/192/128/96/64
  kbps) — `app/ytdlp_manager.py` (`MP3_FORMAT_PREFIX`, `MP3_QUALITIES`),
  `ui/app.js` (`appendMp3Options`). Requires ffmpeg (`scripts/fetch_ffmpeg.py`).
- **Format classification** — raw yt-dlp formats grouped into Video
  (MP4/WebM/...) and Audio (M4A/WebM/...) optgroups by `vcodec`, ordered
  MP3 → Video → Audio in the dropdown — `ui/app.js` (`classifyFormats`).
- **Default format auto-selection** — backend returns `is_audio_source`
  (derived from `vcodec` for single videos; an extractor-name heuristic for
  playlists, since `--flat-playlist` never resolves per-entry formats);
  frontend preselects the best video format or `mp3:best` accordingly —
  `app/ytdlp_manager.py` (`list_formats`), `ui/app.js` (`pickBestFormat`).
- **Real yt-dlp error surfacing** — `_extract_error_message` in
  `app/ytdlp_manager.py` pulls yt-dlp's own `ERROR:` line out of captured
  output instead of showing a bare exit code. (Landed after a real incident:
  an MP3 download failed with "exited with code 1" while the actual cause —
  missing ffmpeg — was buried in output the UI never showed.)
- **`scripts/fetch_ffmpeg.py`** — downloads static ffmpeg/ffprobe binaries
  into `ffmpeg/`, mirroring `scripts/fetch_binaries.py`'s pattern for
  yt-dlp itself. `scripts/build.py` bundles whatever is already in `ffmpeg/`
  into the PyInstaller output, but does not run `fetch_ffmpeg.py` itself —
  the caller must run it first. **Incident (2026-09):** every OS's released
  zip from `.github/workflows/release.yml` shipped with an empty `ffmpeg/`
  (just `.gitkeep`) because the workflow called `fetch_binaries.py
  --current-os` for yt-dlp but never called `fetch_ffmpeg.py`. Symptom
  looked nothing like a missing-ffmpeg error: yt-dlp merges video+audio via
  its own ffmpeg postprocessing step, so with no ffmpeg available (bundled
  dir empty and none on PATH) it silently left the separate video-only and
  audio-only streams on disk instead of one merged file — video-only stream
  fails to play, indistinguishable at a glance from a download bug. Fixed
  by adding a "Fetch ffmpeg/ffprobe for this OS" step (`python
  scripts/fetch_ffmpeg.py`) to the release workflow for all three OS
  matrix entries, right after the yt-dlp fetch step and before
  `scripts/build.py`. Any other place that packages a distributable build
  (a future local packaging script, a different CI workflow) must call
  `fetch_ffmpeg.py` before `build.py` too — `build.py` bundles `ffmpeg/`
  as-is and has no way to tell an intentionally-empty dev checkout apart
  from a checkout that forgot this step.
- **Toolbar + tabs UI redesign** — sticky toolbar (brand + dark-mode toggle),
  Download/History tabs, empty state — `ui/index.html`, `ui/style.css`,
  `ui/app.js` (`switchTab`, `tabButtons`/`tabPanels`).
- **URL input moved into the Download tab** — the URL field, playlist
  checkbox, and "Get formats" button live in a `.url-card` at the top of
  `#tab-download` instead of the header toolbar, so they're scoped to the
  tab they act on — `ui/index.html`, `ui/style.css` (`.url-card`/`.url-row`).
- **Settings moved from a tab to a header popover** — the "Settings" tab was
  removed; a gear icon (`#settings-toggle`) next to the dark-mode toggle
  opens a `.settings-panel` popover (yt-dlp update check/output), closed on
  outside click or Escape — `ui/index.html` (`.settings-menu`), `ui/style.css`
  (`.settings-panel`), `ui/app.js` (`settingsToggleBtn` listener,
  `closeSettingsPanel`).
- **Friendly format list, folder browse, and reveal-in-folder** — format
  dropdown shows human-readable labels ("1080p · 3.80 GB") instead of raw
  format IDs, and video-only qualities auto-merge with `bestaudio` so every
  download has sound (`app/ytdlp_manager.py` `list_formats`/`_run_download`,
  `ui/app.js` `formatOptionLabel`/`formatOptionValue`); a native OS
  folder-picker for "Save to" and click-to-reveal History rows in the OS
  file explorer (new `app/dialogs.py`, `POST /api/browse-folder` and
  `POST /api/reveal` in `app/server.py`, `#browse-folder` button in
  `ui/index.html`). Built across 4 parallel sessions per file ownership;
  verification caught and fixed two cross-task integration bugs (stale
  Download-tab progress badge; `_apply_progress_line` capturing a
  since-deleted temp file's path instead of the final merged file — now
  also matches yt-dlp's `Merging formats into "..."` line). See git history
  for the full original plan if needed.
- **Clip (start/end trim) downloads** *(superseded — see "Simplified
  clip/trim downloads to one instant method" further down: the
  `--download-sections`/`--force-keyframes-at-cuts` approach described here
  was replaced entirely)* — optional "Clip start"/"Clip end"
  fields in `#formats-card` (plain seconds, `MM:SS`, or `HH:MM:SS`,
  validated client-side by `parseClipTime` in `ui/app.js`) send
  `clip_start`/`clip_end` to `POST /api/download`. `app/ytdlp_manager.py`'s
  `_run_download` re-validates with `CLIP_TIME_RE`, then adds
  `--download-sections "*<start or 0>-<end or inf>" --force-keyframes-at-cuts`
  (needs ffmpeg, same as MP3) and appends a `" [clip <start>-<end>]"`
  filename suffix (colons replaced with `-`, since they're illegal in Windows
  filenames) so a clip never overwrites a full download of the same title.
  Works with any format including MP3 extraction and merged video+audio
  specs. History entries show the clip range (`ui/app.js` `renderHistory`,
  the `.clip` field). This plan went stale once already (written against the
  pre-tabs/toolbar layout) before being re-scoped against the current
  `#formats-card`/`.field-grow` structure and implemented — see prior git
  history in this file for that lesson. Verified end-to-end against the real
  bundled yt-dlp/ffmpeg binaries via the running API: a raw-format clip and
  an MP3-format clip each produced ffprobe-confirmed exact-duration output,
  empty fields left a normal download unaffected, and an invalid time value
  (`"garbage"`) surfaced a clear `error` status instead of being sent to
  yt-dlp.
- **Fixed clip downloads of the same title colliding on one output file** —
  the clip filename suffix used to be a bare `" [clip]"` with no range in it,
  so re-trimming the same video with a different start/end (normal while
  hunting for the right range) reused the exact same output path; a later
  attempt overwriting or erroring out could leave an earlier "finished"
  History entry's `filepath` pointing at a file that was since replaced or
  deleted entirely, surfacing as "path does not exist" when clicked to
  reveal. Root-caused from a History list (see git history around
  2026-09-15) showing several `starting`/`error`/`finished` entries for one
  title with different clip ranges. Fixed in `app/ytdlp_manager.py`
  `_run_download_inner` by embedding the (colon-stripped) start/end in the
  suffix so each distinct range gets its own file; re-running the *same*
  exact range still intentionally overwrites its own prior output.
- **Calculator-style input mask for clip-start/clip-end** — typed digits
  fill in from the right like a stopwatch display (`2`, `3`, `0` ->
  `0:02` -> `0:23` -> `2:30`) instead of requiring a manually-typed colon;
  paste is supported too (non-digits stripped, last 6 digits kept) —
  `ui/app.js` (`formatDurationDigits`, `setupDurationMask`). Output stays
  colon-separated so it's unchanged as far as `parseClipTime` and the
  backend's `CLIP_TIME_RE` are concerned — no changes needed there.
- **Download-progress status labels** — the progress card/tab badge now
  says what stage a job is actually in (`Searching…` while `/api/formats`
  is in flight; `Downloading — NN%`; `Clipping…` / `Converting to MP3…` /
  `Merging…` for post-download ffmpeg steps) instead of sitting on
  "downloading — 100%" during post-processing — `app/ytdlp_manager.py`
  (`_run_download` tracks `post_status` once `[download]` progress lines
  stop), `ui/app.js` (`STATUS_LABELS`, `fetchFormatsBtn` label swap).
- **Fixed downloads silently stalling at "downloading — 0%"** — root-caused
  by testing the bundled `yt-dlp_win.exe` directly (see git history around
  2026-09-15 for the terminal transcript): without a JS runtime on PATH,
  yt-dlp itself warns "No supported JavaScript runtime could be found" and
  YouTube's throttled/higher-quality formats resolve to URLs that transfer
  at near-zero speed instead of failing outright — from the UI this is
  indistinguishable from a hang. `resolve_ytdlp_command()` in
  `app/ytdlp_manager.py` now auto-detects `deno`/`node`/`bun` via
  `shutil.which` and adds `--js-runtimes`. Also bumped
  `--file-access-retries`/`--retry-sleep file_access:...` in `_run_download`
  after hitting a separate `[WinError 32] Unable to rename file` failure
  (Windows AV/indexing transiently holding the freshly-written file open) —
  yt-dlp's default of 3 quick retries wasn't enough headroom. See "Planned:
  bundle a portable JS runtime" below for the remaining portability gap.
- **Fixed silently corrupted output from duplicate concurrent downloads** —
  a retried/double-clicked request for the same `(url, format_id,
  output_dir, is_playlist, clip_start, clip_end)` combo resolves to the
  identical yt-dlp output path; two yt-dlp/ffmpeg processes racing to write
  and rename that same path can interleave writes into the same final file.
  Root-caused a real corrupted clip (`ffprobe` reported "Invalid NAL unit
  size" throughout, and a bogus duration) found alongside the WinError 32
  incident above — almost certainly caused by a download still in flight
  against the pre-restart server process colliding with a user retry
  against the freshly-restarted one, both writing to the same title-derived
  filename. `start_download()` in `app/ytdlp_manager.py` now tracks
  in-flight destinations in `_active_targets` and rejects a duplicate
  request outright (`POST /api/download` returns 409) instead of letting a
  second job start against the same target; released in `_run_download`'s
  `finally`. Only guards within one running server process — an orphaned
  subprocess left over from a killed pre-restart server (see CLAUDE.md note
  1) isn't tracked by the new process's in-memory set, so restarting
  `launcher.py` mid-download is still a known way to hit this. Corrupted
  files from before this fix aren't recoverable; delete and re-download.
- **Fixed clip downloads hanging forever when clip end <= clip start** —
  e.g. clip start and clip end both set to the same value. yt-dlp doesn't
  reject a zero/negative-length `--download-sections` range with an error;
  it just hangs indefinitely, which looks identical to the "stuck at 0%"
  bug two entries up (same symptom, different cause — caught this instance
  from a live screenshot showing clip start = clip end = "2:30"). Now
  rejected with a clear message before it ever reaches yt-dlp: client-side
  in `ui/app.js`'s `downloadBtn` handler (`clipTimeToSeconds` comparison)
  and, since the backend must not trust the frontend alone, again
  server-side in `app/ytdlp_manager.py`'s `_run_download_inner`
  (`_clip_seconds`).
- **Fixed the progress bar looking stuck during clipping/merging/MP3
  conversion, then snapping straight to 100%** — those are ffmpeg
  post-processing steps and none of them print a `[download] NN%` line, so
  the bar just held whatever percent the raw download last reported (often
  low, since a short clip section downloads in a couple seconds) for the
  whole post-processing duration, then jumped to 100% when the job
  finished. `ui/app.js`'s SSE `onmessage` handler now switches the bar to
  an indeterminate sliding animation (`.progress-bar.indeterminate`,
  `ui/style.css`) whenever the job is in one of those in-between statuses,
  instead of showing a stale/frozen number.
- **Progress bar now also covers the "searching for formats" stage** — it
  previously only appeared once an actual download job started; the "Get
  formats" lookup (can take a few seconds on a slow connection or a large
  playlist) had zero visible progress beyond the button's own label
  changing to "Searching…". `fetchFormatsBtn`'s click handler in
  `ui/app.js` now shows the same `#progress-card` (indeterminate, Cancel
  button hidden since there's no job to cancel yet) for the duration of the
  `/api/formats` request, and hides it again in `finally` — skipped
  entirely if a download job's progress is already being shown, so it never
  steals or resets an in-progress download's display.
- **Fixed the "downloading" progress bar looking permanently stuck (and
  Cancel not actually stopping it) for HLS-only 4K formats** —
  root-caused by reproducing it directly against the bundled binary (itag
  625 on a real video): for these formats yt-dlp hands the transfer to a
  child `ffmpeg` process it spawns itself (`Invoking ffmpeg downloader
  on ...`) instead of its usual fragment downloader, and that path never
  prints a `[download] NN%` line - so `job["percent"]` never moves for the
  whole (potentially multi-minute) transfer. Two fixes: (1) `ui/app.js`'s
  SSE handler now tracks how long `percent` has gone unchanged
  (`DOWNLOAD_STALL_MS`, 4s) and switches to the same indeterminate
  animation used for post-processing if it stalls, regardless of the
  reason - a general fix, not specific to this one code path. (2)
  `cancel_download()` in `app/ytdlp_manager.py` previously only called
  `process.terminate()` on the top-level yt-dlp process, which doesn't
  touch that ffmpeg child - confirmed via `Get-CimInstance` that both
  stayed running well after a cancel click. `_run_download_inner` now
  starts yt-dlp in its own process group (`start_new_session=True`), and
  `_kill_process_tree` (Windows: `taskkill /F /T /PID`; POSIX:
  `os.killpg`) kills the whole tree on cancel. This closes the same
  corruption class as the duplicate-download fix above - an
  orphaned-but-still-writing ffmpeg process is exactly what a "cancel then
  retry" would race against.
- **Real percent for clip downloads on HLS-only formats, instead of just an
  indeterminate spinner** *(superseded — clip downloads no longer use
  `--download-sections` at all, so this `_FFMPEG_OUT_TIME_RE`/
  `_parse_ffmpeg_timestamp` progress hack was removed; see "Simplified
  clip/trim downloads" further down)* — now that "downloading via a raw ffmpeg child"
  (see above) is understood, it turns out ffmpeg *can* report real
  progress there, yt-dlp just wasn't asking it to. Verified against the
  real binary: `--downloader-args "ffmpeg_o:-progress pipe:1 -nostats"`
  makes ffmpeg emit clean, newline-terminated `out_time=HH:MM:SS.ffffff` /
  `progress=continue|end` lines (doesn't affect the download itself,
  confirmed by letting a test run finish, exit code 0). Since a clip's
  duration is known whenever both `clip_start` and `clip_end` are given,
  `_apply_progress_line` in `app/ytdlp_manager.py` now converts
  `out_time=` into a real percent (`_FFMPEG_OUT_TIME_RE`,
  `_parse_ffmpeg_timestamp`) the same way `[download] NN%` lines already
  were - unit-tested against real captured log lines before wiring in. As
  a side effect this also fixes the status label never advancing past
  "Downloading" for these formats: `download_started` only got set once a
  progress line was recognized, and previously none ever were for this
  path, so the `downloading` → `clipping`/`merging` transition never fired
  either.
- **Stream-copy instead of forced-MP4-transcode for clips on HLS-only
  formats** *(superseded — the `fast_clip`/HLS-detection split described
  here was removed; every clip now always stream-copies, see "Simplified
  clip/trim downloads" further down)* — user-chosen trade-off after asking why clipping these
  formats was so much slower than a full download of the same video (see
  the entries above): normally, clipping a merged video+audio format
  forces `--merge-output-format mp4`, and since the source here is
  VP9/Opus (not MP4-native), that meant a full CPU-bound re-encode to
  H.264/AAC for the whole clip length. `_run_download_inner` now skips
  `--merge-output-format mp4` and `--force-keyframes-at-cuts` specifically
  when `want_clip and is_merge` (`fast_clip`), letting ffmpeg stream-copy
  instead - verified against the real binary (`Stream mapping: ... (copy)`
  for both streams, valid output, exit code 0). Honest caveat from
  measuring both paths back to back on the same clip: stream-copy was only
  modestly faster in this environment (~16.6s ffmpeg-internal time vs
  ~18.8s transcoding a 15s clip) - the dominant cost for a *deep* clip
  turned out to be network/seek time within the HLS stream, not the
  transcode itself, so this trade doesn't turn "minutes" into "seconds" on
  its own. Still worth having: no quality loss from re-encoding, no wasted
  CPU, and it removes one variable when diagnosing future slow-clip
  reports. Trade-off: the cut lands on the nearest keyframe instead of the
  exact requested second, and output stays in its native container
  (`.webm`/`.mkv` via the existing `%(ext)s` template) instead of always
  `.mp4`.
- **Clip-size hint** — the format dropdown's size (e.g. "1440p · 700 MB")
  is fetched once from the full video's metadata and has no idea a clip
  range exists, so a clip finishing in a fraction of that size/time looked
  broken rather than merely smaller than expected - the incident that
  prompted this: a format showing "700 MB" produced a much smaller file
  almost immediately once clipped, which read as a bug. `#clip-size-hint`
  in `ui/index.html` (styled via the new generic `.hint` class in
  `ui/style.css`) shows "The size shown below is for the full video — your
  clip will be much smaller" whenever either clip field is non-empty,
  toggled by `updateClipSizeHint()` in `ui/app.js` (hooked into
  `setupDurationMask`'s keydown/paste handlers, since those set `.value`
  programmatically and don't fire a native `input` event).
- **Simplified clip/trim downloads to one instant stream-copy method for
  every format** — user-requested simplification after repeatedly hitting
  the HLS-livestream bitstream-corruption issue (see CLAUDE.md note 10)
  while manually reproducing this app's clip logic on the command line, and
  concluding the three-way branching (`_is_hls_format` detection, the
  `fast_clip` merge/non-merge split, plus the ffmpeg-`out_time=` progress
  workaround) was more complexity than the feature was worth. Removed
  entirely: `_is_hls_format`, `_run_hls_clip_download` (folded into a much
  smaller `_trim_clip`), `fast_clip`, `--download-sections`,
  `--force-keyframes-at-cuts`, `--downloader-args ffmpeg_o:...`,
  `_FFMPEG_OUT_TIME_RE`/`_parse_ffmpeg_timestamp`. New flow in
  `app/ytdlp_manager.py`'s `_run_download_inner`/`_trim_clip`, used
  unconditionally for every clip request (any format, merged or not, HLS or
  not): download the complete video first with yt-dlp's own downloader
  (real `[download] NN%` progress the entire time — no progress hack
  needed since nothing is ever cut mid-download), to a temp filename tagged
  with `_FULL_DOWNLOAD_MARKER`; once that finishes, run one local `ffmpeg
  -ss <start> -to <end> -i <full file> -c copy <final file>` trim; delete
  the temp full download. Always instant (no re-encode) and always
  keyframe-snapped — the frame-exact/re-encode variant for non-HLS
  single-stream formats is also gone, traded for one code path instead of
  three. Playlists now ignore `clip_start`/`clip_end` entirely (a playlist
  download has no single output file to trim against). Known trade-off,
  accepted knowingly: every clip now costs the bandwidth/disk of the whole
  video instead of just the requested range.
- **Debug logging for the clip download pipeline** — added after a real
  "Download finished but the output file couldn't be found" report (clip
  range `00:01:00`-`00:02:05`) where the untrimmed temp file was left
  sitting in the output folder with no way to tell, from the job's `error`
  field alone, whether yt-dlp never printed a usable path or printed one
  that didn't match reality. `_log()` in `app/ytdlp_manager.py` appends to
  `logs/ytdlp_manager.log` (gitignored): the phase-1 (full download) yt-dlp
  command, every `Destination:`/`Merging formats into` line it saw (these
  are what `job["filepath"]` is derived from), the resulting path and
  whether it existed on disk, and the phase-2 (`_trim_clip`) ffmpeg command
  plus its last output lines. The in-app error message for this failure now
  also states the exact path it expected, instead of just the generic
  "couldn't be found".
- **Fixed clip downloads failing on titles with fullwidth/CJK-style
  punctuation** — root-caused using the debug log above: a real report
  (title containing `：`/`｜`, clip range `00:01:00`-`00:02:05`) showed the
  download and merge both succeeded, but `job["filepath"]` (parsed from
  yt-dlp's own `Merging formats into "..."` line) was missing those exact
  characters, so `os.path.isfile()` on it correctly returned false - the
  real file, confirmed present via `os.listdir()` in the same log entry,
  had them. First hypothesis (yt-dlp falling back to the system codepage
  for piped, non-console stdout) turned out wrong: setting
  `PYTHONIOENCODING=utf-8`/`PYTHONUTF8=1` on the child process and
  `encoding="utf-8"` on every `subprocess.run`/`Popen` call in
  `app/ytdlp_manager.py` made no measurable difference on retest against
  the same video - yt-dlp evidently sanitizes what it *prints* through its
  own internal logic, not Python's normal stdout text-encoding, so it
  can't be fixed from the caller's side of the pipe. Real fix: stopped
  trusting the printed path for a clip download at all when it doesn't
  resolve - `_find_full_download()` in `app/ytdlp_manager.py` falls back
  to scanning `output_dir` for the one file containing
  `_FULL_DOWNLOAD_MARKER` (`os.listdir()` isn't subject to whatever yt-dlp
  does to its own stdout, so it always sees the real name). Verified
  end-to-end by re-running the exact failing video/format/clip-range
  combo: full download, fallback path lookup, trim, and cleanup all
  succeeded, final clip file confirmed on disk with the correct duration.
  The `encoding="utf-8"`/`errors="replace"` additions to the subprocess
  calls were kept (harmless, marginally safer against other decode edge
  cases) even though they didn't fix this specific issue.
- **General exception/error-handling audit** — an unhandled exception in any
  route (a missing tkinter display for the folder picker, `explorer`/`open`/
  `xdg-open` not found for reveal-in-folder, yt-dlp's binary missing or
  timing out during a formats lookup or self-update, a malformed JSON
  response from yt-dlp) used to fall through to Flask's default HTML error
  page, which breaks every frontend call site since they all do `await
  res.json()` and got a JSON-parse error instead of the real message.
  Added: a catch-all `@app.errorhandler(Exception)` in `app/server.py` so
  every route reliably returns `{"error": ...}` JSON on failure, even ones
  that don't wrap their own body in try/except; clearer, source-specific
  messages in `app/dialogs.py` (`browse_for_folder`, `reveal_in_file_manager`
  now raise `RuntimeError` with what actually failed, instead of a bare
  `TclError`/`FileNotFoundError`); `run_self_update` in
  `app/ytdlp_manager.py` catches `TimeoutExpired`/`FileNotFoundError`/
  `OSError` and returns them in its normal `{returncode, output}` shape
  instead of raising, matching what the frontend already expects; a new
  `_run_ytdlp_json` helper in `app/ytdlp_manager.py` centralizes
  `list_formats`'s two near-identical subprocess-run-then-`json.loads`
  blocks with the same timeout/missing-binary/bad-JSON handling. On the
  frontend (`ui/app.js`): `cancelBtn`'s click handler previously had no
  `catch` at all (an unhandled promise rejection on network failure, no
  user feedback); the SSE `onerror` handler's already-correct
  transient-vs-fatal distinction (see git history) now also shows an error
  message on the fatal (`CLOSED`) case instead of just silently resetting
  state; `res.json()` calls that lacked it now use `.catch(() => ({}))` for
  resilience against a non-JSON response reaching the browser at all (a
  dropped connection mid-body, a proxy in between, etc.), matching the
  pattern `revealHistoryEntry` (see below; formerly named `revealPath`)
  already used.
- **Dedicated per-row reveal icon in History, and fixed reveal failing for
  completed non-clip downloads** — reveal used to be a whole-row click with
  no visible affordance, and reported "path does not exist" as a generic
  top-of-page error banner. `renderHistory` in `ui/app.js` now appends a
  `.history-reveal-btn` folder icon (📁) to each row instead of making the
  whole `<li>` clickable (`.history-item`/`.history-info` in `ui/style.css`
  replace the old `.clickable` rule); its click handler,
  `revealHistoryEntry`, distinguishes "no location recorded at all" (no
  `filepath`/`outputDir` on the entry — shows "No save location was recorded
  for this download.") from a `404` from `POST /api/reveal` (file/folder
  since moved or deleted — shows a specific "couldn't be found" message)
  rather than one generic error either way. While rebuilding this,
  `renderHistory` was also switched from an `innerHTML` string build to DOM
  text nodes for the title/url fields, since those come from yt-dlp metadata
  pulled from whatever site the user pastes a URL for — untrusted input that
  was a stored-XSS vector otherwise (a crafted video title containing
  markup) even though nothing had exploited it yet.
  Root-caused separately why reveal so often failed once a *regular*
  (non-clip) download actually finished: `job["filepath"]` for that path was
  only ever set from parsing yt-dlp's own `Destination:`/`Merging formats
  into` stdout lines, with no fallback — meaning it inherited the exact same
  non-ASCII/fullwidth-character printing bug already root-caused and fixed
  for clip downloads only (see "Fixed clip downloads failing on titles with
  fullwidth/CJK-style punctuation" above / CLAUDE.md note 11), confirmed via
  the untracked test files already sitting in this repo's working tree with
  fullwidth `｜` in their names. `_run_download_inner` in
  `app/ytdlp_manager.py` now runs the same verify-then-fallback step for the
  non-clip, non-playlist case too: a new `_find_recent_download(output_dir,
  since_ts)` looks for the one file in `output_dir` modified at/after the
  download started (no `_FULL_DOWNLOAD_MARKER` exists in this path to search
  for like the clip case has, so this uses a start-time heuristic instead;
  ambiguous — zero or multiple matches — still returns `None` rather than
  guessing wrong, same caution as `_find_full_download`). Playlists are
  skipped (many files land in `output_dir` per run, so a newest-file guess
  isn't reliable there) and keep their pre-existing behavior. Verified via
  `/api/reveal` directly against the running dev server: a nonexistent path
  now returns the same `404 {"error": "path does not exist"}` the frontend's
  new not-found message expects, and an existing folder returns `{"ok":
  true}` and opens it in Explorer.
- **Fixed "show in folder" opening an unrelated default folder (Documents)
  instead of the file's real location** — real report: clicking the new
  History reveal icon on a finished download opened Documents, not the
  download's actual folder. First added logging (`_log()` in the new
  `app/dialogs.py`, writing to `logs/dialogs.log`, gitignored) to capture
  every reveal request's exact path and command before guessing at a fix.
  Root-caused via that log plus a from-scratch repro: with the exact path
  logged for a real finished download (containing `｜`, a fullwidth
  character, and — separately — a space, since almost every real video
  title has one), running the app's exact old
  `subprocess.run(["explorer", f"/select,{path}"])` call directly reproduced
  Documents opening instead of the download's folder. Diagnosed why using
  `subprocess.list2cmdline` on that exact call: `/select,` and `path` are
  one combined argv element, and since it contains a space,
  `list2cmdline` wraps the *whole* element in quotes — explorer.exe parses
  `/select,` by hand rather than via normal argument splitting and can't
  handle that combined quoting, so it silently falls back to some default
  location instead of erroring (explaining why this never surfaced as a
  visible error before). Verified the diagnosis and the fix empirically
  (no human needed to look at a screen) using PowerShell's
  `Shell.Application` COM object to read the actually-opened window's
  `LocationURL` and `Document.SelectedItems()`: the old code opened
  `file:///C:/Users/.../Documents` for a real fullwidth/space-containing
  path; the fixed `reveal_in_file_manager()` — passing `/select,` and
  `os.path.normpath(path)` as two separate argv elements instead of one
  combined, quoted string — opened the correct parent folder with the
  target file itself present in `SelectedItems()`. The `os.path.normpath()`
  call also incidentally fixes a second, unrelated issue seen in
  `logs/ytdlp_manager.log`: a mixed forward/backslash path (e.g.
  `C:/Videos/Testing\title.mp4` — the folder half from the tkinter
  folder-browse dialog, which returns forward slashes, with the filename
  half `os.path.join`-ed on using the OS's native separator) that explorer's
  parser has also been seen to mishandle. Documented as CLAUDE.md note 12,
  since `explorer /select,` returning a normal-looking exit code 1 on
  success (not just failure) makes this exact bug easy to reintroduce and
  hard to notice from the subprocess return code alone.
- **Progress card swaps to a compact result view instead of sitting frozen
  at 100%/"Finished"** — previously a finished/errored/cancelled job left
  the progress bar and its "Finished"/"Error"/"Cancelled" label on screen
  indefinitely, with no way to jump to the file it just produced short of
  switching to the History tab. `ui/index.html`'s `#progress-card` now holds
  two sibling views instead of one: the existing `#progress-view` (progress
  bar, status text, Cancel button, unchanged) and a new `#result-view`
  (`#result-text` message + a `#result-reveal` 📁 icon, both hidden by
  default). `showDownloadResult(job, outputDir)` in `ui/app.js` — called
  from the SSE `onmessage` handler's existing terminal-status branch
  alongside the status bookkeeping that was already there — hides
  `#progress-view` and shows `#result-view` with a status-appropriate
  message (`RESULT_MESSAGES`, or the job's own `error` text), and shows the
  reveal icon only for a `finished` job that actually has a `filepath` or
  `outputDir` to point at (wired to the same `revealHistoryEntry` History
  rows use, passed a synthetic `{filepath, outputDir}` entry, so reveal
  behavior/messaging - including CLAUDE.md note 12's explorer fix and the
  "couldn't be found"/"no location recorded" messages - is identical between
  the two). `downloadBtn`'s click handler (starting a new download) and
  `fetchFormatsBtn`'s click handler (searching formats, which also borrows
  this same card when no download is already showing) both flip back to
  `#progress-view`/hide `#result-view` before doing anything else, so a
  leftover finished/error card from a previous job never lingers once a new
  action starts - exactly one of the two views is visible in the card at any
  time. Verified by cross-checking every new element ID between
  `ui/index.html` and `ui/app.js` (`progress-view`/`result-view`/
  `result-text`/`result-reveal`) and full manual trace of the
  download/fetch-formats/SSE code paths; not click-tested in a live browser
  in this pass (no browser-automation tool available in this environment) -
  worth an actual click-through before considering this fully verified.

## Planned: bundle a portable JS runtime

**Status:** Not started.

**Context:** the stuck-at-0% fix above (`--js-runtimes` auto-detected via
`shutil.which`) only works if `deno`, `node`, or `bun` happens to already be
on the end user's PATH. It was verified against `node` on the dev machine;
a genuinely fresh portable install (this app's whole premise) on a machine
with none of the three installed gets no benefit and is back to the
original silent-stall behavior.

**Approach (not yet validated):** mirror `scripts/fetch_ffmpeg.py` /
`scripts/fetch_binaries.py` — add a `scripts/fetch_js_runtime.py` that
downloads a portable `deno` binary per OS into a new `deno/` dir (with a
`.gitkeep`, real binary never committed, same pattern as `ffmpeg/`), wire it
into `scripts/build.py`'s PyInstaller bundle, and have
`_detect_js_runtime()` in `app/ytdlp_manager.py` check the bundled path
before falling back to `shutil.which`. Needs a real check of deno's binary
size/licensing before committing to it over node/bun.

**Files expected to change:** new `scripts/fetch_js_runtime.py`, new
`deno/.gitkeep`, `scripts/build.py`, `app/ytdlp_manager.py`
(`_detect_js_runtime`), `README.md`.
