# app/playback.py
"""Owns chapter playback: the prefetch cache, current index, and playback
state -- ported from extension/offscreen.js, minus the multi-tab guard
(activeSessionId vs chapterSessionId) that only made sense when many Chrome
tabs could share one offscreen document. A single-window app has no "other
tabs" to guard against (docs/adr/0009-standalone-app-replaces-extension.md).
"""
import threading
from concurrent.futures import ThreadPoolExecutor

PREFETCH_AHEAD = 6


class PlaybackEngine:
    def __init__(self, sidecar_client, audio_player, notify):
        self._sidecar = sidecar_client
        self._audio = audio_player
        self._notify = notify
        self._audio.on_finished = self._on_chunk_finished
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._lock = threading.Lock()
        self._chunks = []
        self._paragraphs = []
        self._index = 0
        self._rate = 1.0
        self._speaker = ""
        self._cache = {}
        self._chapter_session_id = None
        self._playing = False

    def load_chapter(self, chunks, paragraphs, chapter_session_id, speaker, rate) -> None:
        with self._lock:
            self._chunks = chunks
            self._paragraphs = paragraphs
            self._index = 0
            self._speaker = speaker
            self._rate = rate
            self._chapter_session_id = chapter_session_id
            self._cache = {}
        self._prefetch()

    def _prefetch(self) -> None:
        with self._lock:
            end = min(len(self._chunks), self._index + PREFETCH_AHEAD)
            todo = [i for i in range(self._index, end) if i not in self._cache]
            speaker = self._speaker
        for i in todo:
            future = self._executor.submit(self._sidecar.synthesize, self._chunks[i]["text"], speaker)
            with self._lock:
                self._cache[i] = future

    def play_current(self) -> None:
        with self._lock:
            index = self._index
            total = len(self._chunks)
        if index >= total:
            self._playing = False
            self._notify({"type": "CHAPTER_DONE"})
            return
        self._prefetch()
        chunk = self._chunks[index]
        self._notify({
            "type": "CHUNK_INDEX",
            "paragraphIndex": chunk["paragraphIndex"],
            "totalParagraphs": len(self._paragraphs),
            "paragraphText": self._paragraphs[chunk["paragraphIndex"]],
        })
        self._notify({"type": "PLAYBACK_STATE", "state": "buffering"})
        with self._lock:
            future = self._cache[index]
        try:
            wav_bytes = future.result()
        except Exception as err:
            self._notify({"type": "PLAYBACK_STATE", "state": "paused"})
            self._notify({"type": "ERROR", "message": f"Sidecar unreachable: {err}"})
            return
        self._audio.load(wav_bytes)
        self._audio.play(rate=self._rate)
        self._playing = True
        self._notify({"type": "PLAYBACK_STATE", "state": "playing"})

    def _on_chunk_finished(self) -> None:
        with self._lock:
            self._index += 1
        self.play_current()

    def toggle_play(self) -> None:
        if self._playing:
            self._audio.pause()
            self._playing = False
            self._notify({"type": "PLAYBACK_STATE", "state": "paused"})
        else:
            self._audio.resume()
            self._playing = True
            self._notify({"type": "PLAYBACK_STATE", "state": "playing"})

    def set_rate(self, rate: float) -> None:
        self._rate = rate
        self._audio.set_rate(rate)

    def set_speaker(self, speaker: str) -> None:
        self._speaker = speaker
        with self._lock:
            for i in [i for i in self._cache if i > self._index]:
                del self._cache[i]
        self._prefetch()

    def skip(self, direction: int) -> None:
        with self._lock:
            chunks = self._chunks
            index = self._index
        current_paragraph = chunks[index]["paragraphIndex"] if index < len(chunks) else 0
        target_paragraph = current_paragraph + direction
        target = next((i for i, c in enumerate(chunks) if c["paragraphIndex"] == target_paragraph), None)
        if target is None:
            return
        with self._lock:
            self._index = target
        self.play_current()
