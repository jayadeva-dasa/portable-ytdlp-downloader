"""Entry point: starts the local Flask server and opens the UI in the default browser.

This is the module PyInstaller should target when packaging per-OS builds later
(see README.md) — the app is designed to be launched by double-clicking, not
by running a Python script from a terminal.
"""
import socket
import threading
import time
import webbrowser

from app.server import app

HOST = "127.0.0.1"
PORT = 5000
# How many ports to try (PORT, PORT+1, ...) before giving up — covers the
# common case of a leftover instance (or an unrelated app) already bound to
# the default port, without surfacing a raw "address already in use" error
# to a non-technical user.
MAX_PORT_ATTEMPTS = 5


def _find_open_port():
    for port in range(PORT, PORT + MAX_PORT_ATTEMPTS):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex((HOST, port)) != 0:
                return port
    raise SystemExit(
        f"Ports {PORT}-{PORT + MAX_PORT_ATTEMPTS - 1} are all in use. "
        "Close other programs using them and try again."
    )


def main():
    port = _find_open_port()
    server_thread = threading.Thread(
        target=lambda: app.run(host=HOST, port=port, threaded=True, use_reloader=False),
        daemon=True,
    )
    server_thread.start()
    time.sleep(1)
    webbrowser.open(f"http://{HOST}:{port}")
    server_thread.join()


if __name__ == "__main__":
    main()
