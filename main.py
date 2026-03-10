"""Gather — Home Video Maker.  Application entry point."""

import threading
import time
import urllib.error
import urllib.request

import uvicorn
from fastapi import FastAPI

from config import HOST, PORT
from routes import router

app = FastAPI(title="Gather", description="Home Video Maker")
app.include_router(router)


def _start_server():
    """Run the FastAPI server in a daemon thread."""
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


def _wait_for_server(url: str, timeout: float = 10.0):
    """Block until the server responds or *timeout* seconds elapse."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.1)


def _set_macos_app_name(name: str):
    """Override the menu-bar title so it shows *name* instead of 'Python'."""
    try:
        from Foundation import NSBundle

        bundle = NSBundle.mainBundle()
        info = bundle.infoDictionary()
        info["CFBundleName"] = name
    except ImportError:
        pass  # not on macOS


class _GatherApi:
    """Thin bridge so frontend JS can call native window methods."""

    def toggle_fullscreen(self):
        for w in webview.windows:
            w.toggle_fullscreen()


if __name__ == "__main__":
    import webview

    _set_macos_app_name("Gather")

    server_thread = threading.Thread(target=_start_server, daemon=True)
    server_thread.start()

    server_url = f"http://{HOST}:{PORT}"
    _wait_for_server(server_url)

    webview.create_window(
        "Gather",
        server_url,
        width=1280,
        height=860,
        min_size=(900, 600),
        js_api=_GatherApi(),
    )
    webview.start()
