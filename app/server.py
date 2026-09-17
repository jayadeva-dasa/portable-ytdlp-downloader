import json
import os
import time

from flask import Flask, Response, jsonify, request, send_from_directory

from app.dialogs import browse_for_folder, reveal_in_file_manager
from app.paths import get_base_dir
from app.ytdlp_manager import cancel_download, get_job, list_formats, run_self_update, start_download

BASE_DIR = get_base_dir()
UI_DIR = os.path.join(BASE_DIR, "ui")
DEFAULT_OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "portable-ytdlp-downloader")

app = Flask(__name__, static_folder=None)


@app.errorhandler(Exception)
def handle_unexpected_error(exc):
    """Without this, any route that raises outside its own try/except (a
    missing native dialog dependency, a subprocess that isn't on PATH, etc.)
    falls through to Flask's default HTML error page - which breaks every
    frontend call site, since they all do `await res.json()` and get a
    JSON-parse error instead of the actual message. One handler here means
    every API route reliably returns JSON on failure, even ones that don't
    wrap their own body in try/except."""
    from werkzeug.exceptions import HTTPException

    if isinstance(exc, HTTPException):
        return jsonify({"error": exc.description}), exc.code
    return jsonify({"error": str(exc) or exc.__class__.__name__}), 500


@app.route("/")
def index():
    return send_from_directory(UI_DIR, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(UI_DIR, filename)


@app.route("/api/formats")
def api_formats():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "missing url"}), 400
    is_playlist = request.args.get("playlist") == "1"
    try:
        info = list_formats(url, is_playlist=is_playlist)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify(info)


@app.route("/api/download", methods=["POST"])
def api_download():
    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "missing url"}), 400
    output_dir = (data.get("output_dir") or "").strip() or DEFAULT_OUTPUT_DIR
    job_id = start_download(
        url,
        data.get("format_id"),
        output_dir,
        is_playlist=bool(data.get("is_playlist")),
        clip_start=(data.get("clip_start") or "").strip() or None,
        clip_end=(data.get("clip_end") or "").strip() or None,
    )
    if job_id is None:
        return jsonify({"error": "An identical download is already in progress"}), 409
    return jsonify({"job_id": job_id, "output_dir": os.path.abspath(output_dir)})


@app.route("/api/cancel/<job_id>", methods=["POST"])
def api_cancel(job_id):
    cancelled = cancel_download(job_id)
    return jsonify({"cancelled": cancelled})


@app.route("/api/progress/<job_id>")
def api_progress(job_id):
    def stream():
        while True:
            job = get_job(job_id)
            if job is None:
                yield f"data: {json.dumps({'status': 'not_found'})}\n\n"
                return
            yield f"data: {json.dumps(job)}\n\n"
            if job["status"] in ("finished", "error", "cancelled"):
                return
            time.sleep(0.5)

    return Response(stream(), mimetype="text/event-stream")


@app.route("/api/browse-folder", methods=["POST"])
def api_browse_folder():
    path = browse_for_folder()
    return jsonify({"path": path})


@app.route("/api/reveal", methods=["POST"])
def api_reveal():
    data = request.get_json(force=True, silent=True) or {}
    path = (data.get("path") or "").strip()
    if not path or not os.path.exists(path):
        return jsonify({"error": "path does not exist"}), 404
    reveal_in_file_manager(path)
    return jsonify({"ok": True})


@app.route("/api/update", methods=["POST"])
def api_update():
    return jsonify(run_self_update())


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
