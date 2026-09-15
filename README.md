# Portable Video Downloader

A self-contained, cross-platform video downloader UI built around
[yt-dlp](https://github.com/yt-dlp/yt-dlp). A small local Flask server drives
yt-dlp as a subprocess and serves a plain HTML/JS front end; the whole thing
is meant to eventually ship as a single double-click executable per OS
(via PyInstaller), with no separate Python or yt-dlp install required.

## Why this architecture

- **yt-dlp as a subprocess binary, not a Python library.** Only the
  standalone yt-dlp release binaries support `yt-dlp -U` self-update in
  place. Shelling out to `bin/yt-dlp_<os>` gets click-to-update for free
  instead of building a custom updater.
- **Flask + local HTML/JS UI, not Electron/Tauri.** Smallest packaging
  surface: `launcher.py` starts a server on `localhost` and opens the
  system browser. Works today from source, and packages into one
  PyInstaller executable per platform later without an architecture
  change.
- **Per-OS binaries live in `bin/`, fetched separately, not committed.**
  They're large, platform-specific, and `yt-dlp -U` rewrites them in
  place — none of that belongs in git history. `scripts/fetch_binaries.py`
  downloads them from yt-dlp's own GitHub releases.

## Structure

```
app/
  server.py          # Flask app: routes + SSE progress endpoint
  ytdlp_manager.py    # binary resolution, subprocess calls, progress parsing
bin/                  # yt-dlp_win.exe / yt-dlp_macos / yt-dlp_linux (fetched, not committed)
ffmpeg/               # optional per-OS ffmpeg binary (fetched, not committed)
ui/
  index.html
  app.js
  style.css
scripts/
  fetch_binaries.py   # downloads the per-OS yt-dlp binaries into bin/
launcher.py           # entry point: starts the server, opens the browser
start.sh / start.bat  # dev launchers (venv + pip install + launcher.py)
```

## Running it locally

```bash
python3 scripts/fetch_binaries.py   # optional — falls back to `python3 -m yt_dlp` if skipped
./start.sh                          # macOS/Linux
start.bat                           # Windows
```

This creates a venv, installs `requirements.txt`, and opens
`http://127.0.0.1:5000` in your browser.

## API

- `GET /api/formats?url=<video url>` — returns the video title and available
  yt-dlp formats.
- `POST /api/download` — body `{ url, format_id, output_dir? }`, returns
  `{ job_id }` and starts the download in a background thread.
- `GET /api/progress/<job_id>` — Server-Sent Events stream of
  `{ status, percent, speed, eta, error }` until the job finishes or errors.
- `POST /api/update` — runs the bundled binary's `-U` self-update and
  returns its output.

## Packaging (later)

Once the app is feature-complete, run `scripts/fetch_binaries.py` for the
target OS, then package `launcher.py` with PyInstaller (one spec per
platform, bundling `ui/`, `bin/`, and `ffmpeg/` as data files) to produce a
single double-click executable with nothing to pre-install.
