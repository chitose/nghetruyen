"""The js_api bridge: methods content.js calls as window.pywebview.api.*.
See docs/adr/0009-standalone-app-replaces-extension.md -- JS sends intents,
this class (backed by Config and PlaybackEngine) owns all the state.
"""
import time

from chunker import build_paragraph_chunks
from config import KNOWN_SPEAKERS


class Api:
    def __init__(self, config, playback, sidecar_client):
        self._config = config
        self._playback = playback
        self._sidecar = sidecar_client

    def get_init_data(self, hostname: str) -> dict:
        return {
            "adapter": self._config.find_adapter(hostname),
            "defaultRate": self._config.get("defaultRate"),
            "speaker": self._config.get("speaker"),
            "autoNext": self._config.get("autoNext"),
            "knownSpeakers": KNOWN_SPEAKERS,
        }

    def chapter_ready(self, paragraphs: list, next_adapter, title: str) -> dict:
        chunks = build_paragraph_chunks(paragraphs)
        session_id = f"{title}-{time.time()}"
        self._playback.load_chapter(
            chunks, paragraphs, session_id,
            speaker=self._config.get("speaker"),
            rate=self._config.get("defaultRate"),
        )
        return {"chapterSessionId": session_id}

    def start_playback(self) -> None:
        self._playback.play_current()

    def toggle_play(self) -> None:
        self._playback.toggle_play()

    def skip(self, direction: int) -> None:
        self._playback.skip(direction)

    def set_rate(self, rate: float) -> None:
        self._config.set("defaultRate", rate)
        self._playback.set_rate(rate)

    def set_speaker(self, speaker: str) -> None:
        self._config.set("speaker", speaker)
        self._playback.set_speaker(speaker)

    def set_auto_next(self, enabled: bool) -> None:
        self._config.set("autoNext", enabled)

    def get_speakers(self) -> dict:
        try:
            return {"ok": True, "speakers": self._sidecar.speakers()}
        except Exception:
            return {"ok": False}

    def get_adapters(self) -> list:
        return self._config.get("adapters")

    def save_adapters(self, adapters: list) -> None:
        self._config.set("adapters", adapters)

    def get_settings(self) -> dict:
        return {
            "sidecarUrl": self._config.get("sidecarUrl"),
            "speaker": self._config.get("speaker"),
            "defaultRate": self._config.get("defaultRate"),
        }

    def save_settings(self, settings: dict) -> None:
        for key in ("sidecarUrl", "speaker", "defaultRate"):
            if key in settings:
                self._config.set(key, settings[key])
