import json
import os
import time

from flask import Flask, Response, jsonify, request, send_from_directory

from app.ytdlp_manager import get_job, list_formats, run_self_update, start_download

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(BASE_DIR, "ui")
DEFAULT_OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "portable-ytdlp-downloader")

app = Flask(__name__, static_folder=None)


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
    try:
        info = list_formats(url)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify(info)


@app.route("/api/download", methods=["POST"])
def api_download():
    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "missing url"}), 400
    job_id = start_download(url, data.get("format_id"), data.get("output_dir") or DEFAULT_OUTPUT_DIR)
    return jsonify({"job_id": job_id})


@app.route("/api/progress/<job_id>")
def api_progress(job_id):
    def stream():
        while True:
            job = get_job(job_id)
            if job is None:
                yield f"data: {json.dumps({'status': 'not_found'})}\n\n"
                return
            yield f"data: {json.dumps(job)}\n\n"
            if job["status"] in ("finished", "error"):
                return
            time.sleep(0.5)

    return Response(stream(), mimetype="text/event-stream")


@app.route("/api/update", methods=["POST"])
def api_update():
    return jsonify(run_self_update())


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
