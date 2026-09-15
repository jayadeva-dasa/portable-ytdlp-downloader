"""Entry point: starts the local Flask server and opens the UI in the default browser.

This is the module PyInstaller should target when packaging per-OS builds later
(see README.md) — the app is designed to be launched by double-clicking, not
by running a Python script from a terminal.
"""
import threading
import time
import webbrowser

from app.server import app

HOST = "127.0.0.1"
PORT = 5000


def main():
    server_thread = threading.Thread(
        target=lambda: app.run(host=HOST, port=PORT, threaded=True, use_reloader=False),
        daemon=True,
    )
    server_thread.start()
    time.sleep(1)
    webbrowser.open(f"http://{HOST}:{PORT}")
    server_thread.join()


if __name__ == "__main__":
    main()
