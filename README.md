# Portable Video Downloader

A self-contained, cross-platform video downloader UI built around
[yt-dlp](https://github.com/yt-dlp/yt-dlp). A small local Flask server drives
yt-dlp as a subprocess and serves a plain HTML/JS front end, packaged as a
single double-click executable per OS via PyInstaller, with no separate
Python or yt-dlp install required.

## Why this architecture

- **yt-dlp as a subprocess binary, not a Python library.** Only the
  standalone yt-dlp release binaries support `yt-dlp -U` self-update in
  place. Shelling out to `bin/yt-dlp_<os>` gets click-to-update for free
  instead of building a custom updater.
- **Flask + local HTML/JS UI, not Electron/Tauri.** Smallest packaging
  surface: `launcher.py` starts a server on `localhost` and opens the
  system browser. Works today from source, and packages into one
  PyInstaller executable per platform without an architecture change.
- **Per-OS binaries live in `bin/`, fetched separately, not committed.**
  They're large, platform-specific, and `yt-dlp -U` rewrites them in
  place — none of that belongs in git history. `scripts/fetch_binaries.py`
  downloads them from yt-dlp's own GitHub releases.
- **Path resolution goes through `app/paths.py`** so the same code finds
  `ui/`, `bin/`, and `ffmpeg/` whether running from source or frozen inside
  a PyInstaller bundle (`sys._MEIPASS`).

## Structure

```
app/
  server.py           # Flask app: routes, cancel, SSE progress endpoint
  ytdlp_manager.py     # binary resolution, subprocess calls, progress parsing, cancel
  paths.py             # base-dir resolution (source vs. PyInstaller-frozen)
bin/                    # yt-dlp_win.exe / yt-dlp_macos / yt-dlp_linux (fetched, not committed)
ffmpeg/                 # optional per-OS ffmpeg binary (not committed)
ui/
  index.html
  app.js
  style.css
scripts/
  fetch_binaries.py    # downloads per-OS yt-dlp binaries into bin/ (--current-os for CI)
  fetch_ffmpeg.py       # downloads a static ffmpeg/ffprobe pair into ffmpeg/ (needed for MP3)
  build.py             # runs PyInstaller for the current OS -> dist/PortableVideoDownloader
.github/workflows/
  release.yml           # builds + zips Windows/macOS/Linux and attaches to a GitHub Release
launcher.py             # entry point: starts the server, opens the browser
start.sh / start.bat    # dev launchers (venv + pip install + launcher.py)
```

## UI features

- **Format picker** — fetches every yt-dlp format (resolution, codec, size)
  for a single video URL.
- **Audio only (MP3)** — an "Audio only (MP3)" group in the format dropdown
  (single video or playlist) with multiple bitrate tiers (best VBR, 320,
  256, 192, 128, 96, 64 kbps). Downloads the best audio stream and
  transcodes it with `yt-dlp -x --audio-format mp3 --audio-quality <tier>`.
  Requires an `ffmpeg` binary in `ffmpeg/` (or on `PATH` for local dev) —
  yt-dlp can't remux to MP3 without it. Run `python3 scripts/fetch_ffmpeg.py`
  to fetch one; without it, MP3 downloads fail after the audio download
  finishes with an "ffprobe and ffmpeg not found" error.
- **Clip (start/end trim)** — optional "Clip start" / "Clip end" fields
  (plain seconds, `MM:SS`, or `HH:MM:SS`) download only that range instead
  of the full file, via `yt-dlp --download-sections "*start-end"
  --force-keyframes-at-cuts`. Works with any format, including MP3. Requires
  ffmpeg, same as MP3 extraction above. Clipped files get a `[clip]` suffix
  so they never overwrite a full download of the same title.
- **Playlist / channel support** — a checkbox switches to `--flat-playlist`
  inspection and a quality-preset dropdown (best / best video / best audio /
  worst / MP3), since per-video format IDs aren't consistent across a
  playlist. Downloads land in
  `<output>/<playlist title>/<index> - <title>.<ext>`.
- **Live progress bar** — Server-Sent Events stream percent/speed/ETA parsed
  from yt-dlp's own `--newline` output.
- **Cancel** — terminates the in-flight yt-dlp subprocess mid-download.
- **Output folder field** — optional override of the default
  `~/Downloads/portable-ytdlp-downloader`.
- **Download history** — a `localStorage`-backed list of past jobs (title,
  status, timestamp) with a "Clear" button; per-viewer only, not shared.
- **Dark mode toggle** — follows system `prefers-color-scheme` by default,
  with a manual override persisted in `localStorage`.
- **Self-update** — runs the bundled binary's `yt-dlp -U` and shows the raw
  output.

## Running it locally

```bash
python3 scripts/fetch_binaries.py   # optional — falls back to `python3 -m yt_dlp` if skipped
python3 scripts/fetch_ffmpeg.py     # optional — only needed for MP3 downloads
./start.sh                          # macOS/Linux
start.bat                           # Windows
```

This creates a venv, installs `requirements.txt`, and opens
`http://127.0.0.1:5000` in your browser.

## API

- `GET /api/formats?url=<video url>&playlist=1` — returns the video/playlist
  title and available formats (or quality presets + entry count for a
  playlist).
- `POST /api/download` — body
  `{ url, format_id, output_dir?, is_playlist?, clip_start?, clip_end? }`,
  returns `{ job_id, output_dir }` and starts the download in a background
  thread.
- `POST /api/cancel/<job_id>` — terminates that job's subprocess.
- `GET /api/progress/<job_id>` — Server-Sent Events stream of
  `{ status, percent, speed, eta, error }` until the job finishes, errors,
  or is cancelled.
- `POST /api/update` — runs the bundled binary's `-U` self-update and
  returns its output.

## Building a release locally

PyInstaller does not cross-compile — run this on each target OS:

```bash
pip install -r requirements.txt -r requirements-build.txt
python scripts/fetch_binaries.py --current-os
python scripts/fetch_ffmpeg.py      # optional — bundles MP3 support into the release
python scripts/build.py
```

Produces `dist/PortableVideoDownloader/` — zip that folder and it's a
double-click app on that OS with nothing to pre-install.

## Releases (Windows / macOS / Linux)

`.github/workflows/release.yml` builds all three platforms on GitHub's own
Windows/macOS/Linux runners (PyInstaller can't cross-build, so this is the
actual mechanism for producing all three from one push) and attaches
`portable-ytdlp-downloader-{windows,macos,linux}.zip` to a GitHub Release.

Trigger it by pushing a tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

or run it manually from the Actions tab (`workflow_dispatch`). Each zip
unpacks to a `PortableVideoDownloader` folder — run the executable inside
(`PortableVideoDownloader.exe` on Windows, `PortableVideoDownloader` on
macOS/Linux) to launch the app.
