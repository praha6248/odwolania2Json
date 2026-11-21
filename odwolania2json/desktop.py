"""Desktop launcher: runs the web interface locally and shows it in a native window or the default browser."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


def app_root() -> Path:
    """Return the folder holding config/, input/ and output/ for source and frozen (PyInstaller) runs."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def free_port() -> int:
    """Ask the OS for an unused local TCP port."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_until_up(url: str, timeout: float = 30.0) -> bool:
    """Poll the server until it answers or the timeout passes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except OSError:
            time.sleep(0.2)
    return False


def main() -> int:
    """Start the server in a background thread and open the user interface."""
    import uvicorn

    from .web.app import create_app

    root = app_root()
    bundled_config = Path(getattr(sys, "_MEIPASS", root)) / "config"
    config_dir = root / "config" if (root / "config").exists() else bundled_config
    os.environ.setdefault("O2J_CONFIG_DIR", str(config_dir))
    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    server = uvicorn.Server(uvicorn.Config(create_app(config_dir), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    if not wait_until_up(url):
        print("Server did not start", file=sys.stderr)
        return 1
    if sys.platform.startswith("linux"):
        # GTK and WebKit must load the distribution's matching libraries, outside the frozen runtime.
        env = os.environ.copy()
        if getattr(sys, "frozen", False):
            original = env.pop("LD_LIBRARY_PATH_ORIG", "")
            if original:
                env["LD_LIBRARY_PATH"] = original
            else:
                env.pop("LD_LIBRARY_PATH", None)
        host = Path(getattr(sys, "_MEIPASS", root)) / "packaging" / "linux_window.py"
        try:
            result = subprocess.run(["/usr/bin/python3", "-I", str(host), url], env=env)
            if result.returncode:
                print("Okno wymaga GTK 3, PyGObject i WebKit2GTK 4.1 lub 4.0.", file=sys.stderr)
            return result.returncode
        finally:
            server.should_exit = True
            thread.join(timeout=5)
    try:
        import webview

        webview.create_window("Odwołania2JSON", url, width=1440, height=900, min_size=(960, 640))
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.start()
    except Exception as error:
        if sys.platform == "win32" and getattr(sys, "frozen", False):
            import ctypes

            server.should_exit = True
            ctypes.windll.user32.MessageBoxW(0, f"Sprawdź instalację Microsoft Edge WebView2.\n{error}", "Odwołania2JSON", 16)
            return 1
        webbrowser.open(url)
        print(f"Odwołania2JSON działa pod adresem {url} (Ctrl+C kończy pracę)")
        try:
            while thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
    server.should_exit = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
