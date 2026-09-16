# app/main.py
"""Entry point: spawns the Sidecar, opens the main Web View window with the
content script injected on every navigation, and wires the js_api bridge.
See docs/adr/0009-standalone-app-replaces-extension.md.
"""
import json
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

import webview

from api import Api
from audio_player import AudioPlayer
from config import Config
from playback import PlaybackEngine
from sidecar_client import SidecarClient
from sidecar_manager import SidecarManager

APP_DIR = Path(__file__).parent
REPO_DIR = APP_DIR.parent
WEB_DIR = APP_DIR / "web"
CONFIG_PATH = Path.home() / "AppData" / "Roaming" / "reading-web" / "config.json"

READERABLE_JS = (WEB_DIR / "readerable.js").read_text(encoding="utf-8")
CONTENT_JS = (WEB_DIR / "content.js").read_text(encoding="utf-8")
PLAYER_BAR_CSS = (WEB_DIR / "player-bar.css").read_text(encoding="utf-8")
ADDRESSBAR_JS = (WEB_DIR / "addressbar.js").read_text(encoding="utf-8")

_main_window = None


def push_to_js(event: dict) -> None:
    if _main_window is None:
        return
    if event["type"] == "CHUNK_INDEX":
        _main_window.evaluate_js(
            f"window.__vnTtsChunkIndex({event['paragraphIndex']}, {event['totalParagraphs']}, {json.dumps(event['paragraphText'])})"
        )
    elif event["type"] == "PLAYBACK_STATE":
        _main_window.evaluate_js(f"window.__vnTtsPlaybackState({json.dumps(event['state'])})")
    elif event["type"] == "ERROR":
        _main_window.evaluate_js(f"window.__vnTtsError({json.dumps(event['message'])})")
    elif event["type"] == "CHAPTER_DONE":
        auto_next = config.get("autoNext")
        if auto_next:
            api.set_pending_auto_start(True)
        _main_window.evaluate_js(f"window.__vnTtsChapterDone({json.dumps(auto_next)})")


def inject_content_script(window) -> None:
    window.evaluate_js(
        "document.getElementById('vn-tts-style') || "
        "(function(){const s=document.createElement('style'); s.id='vn-tts-style'; "
        f"s.textContent = {json.dumps(PLAYER_BAR_CSS)}; document.head.appendChild(s);}})()"
    )
    window.evaluate_js(ADDRESSBAR_JS)
    # readerable.js must run first -- content.js's genericExtract() calls
    # isProbablyReaderable() at call time and expects it already defined.
    window.evaluate_js(READERABLE_JS)
    window.evaluate_js(CONTENT_JS)


def open_options_window() -> None:
    webview.create_window(
        "Reading Web -- Options",
        url=str(WEB_DIR / "options.html"),
        js_api=api,
        width=680, height=600,
    )


if __name__ == "__main__":
    config = Config(CONFIG_PATH)
    sidecar_manager = SidecarManager(
        python_exe=str(REPO_DIR / "sidecar" / "venv" / "Scripts" / "python.exe"),
        cwd=str(REPO_DIR / "sidecar"),
        port=urlparse(config.get("sidecarUrl")).port or 8934,
    )
    sidecar_manager.start()

    def warn_if_sidecar_unhealthy():
        if not sidecar_manager.wait_healthy():
            print("Warning: Sidecar did not become healthy within the timeout.", file=sys.stderr)

    threading.Thread(target=warn_if_sidecar_unhealthy, daemon=True).start()

    sidecar_client = SidecarClient(config.get("sidecarUrl"))
    audio_player = AudioPlayer(on_finished=lambda: None)  # PlaybackEngine overwrites on_finished
    playback = PlaybackEngine(sidecar_client, audio_player, notify=push_to_js)
    api = Api(config, playback, sidecar_client)

    _main_window = webview.create_window(
        "Reading Web",
        url="https://metruyenchu.co",  # starting page; address bar lets the reader go anywhere
        js_api=api,
        width=1200, height=900,
    )
    _main_window.events.loaded += lambda: inject_content_script(_main_window)

    def on_closed():
        sidecar_manager.stop()

    _main_window.events.closed += on_closed

    webview.start()
