# app/playback.py
"""Owns chapter playback: the prefetch cache, current index, and playback
state -- ported from the retired extension's offscreen.js, minus the multi-tab
guard (activeSessionId vs chapterSessionId) that only made sense when many
Chrome tabs could share one offscreen document. A single-window app has no
"other tabs" to guard against (docs/adr/0009-standalone-app-replaces-extension.md).
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
        self._generation = 0
        self._rate = 1.0
        self._speaker = ""
        self._cache = {}
        self._playing = False

    def load_chapter(self, chunks, paragraphs, speaker, rate) -> None:
        self._audio.stop()
        with self._lock:
            self._chunks = chunks
            self._paragraphs = paragraphs
            self._index = 0
            self._generation += 1
            self._speaker = speaker
            self._rate = rate
            self._cache = {}
        self._prefetch()

    def _prefetch(self) -> None:
        with self._lock:
            end = min(len(self._chunks), self._index + PREFETCH_AHEAD)
            todo = [i for i in range(self._index, end) if i not in self._cache]
            speaker = self._speaker
        for i in todo:
            self._submit(i, speaker)

    def _submit(self, index: int, speaker: str):
        """Submit a synthesize call and cache it, then wire up the purge.

        The cache write happens before add_done_callback is attached, and
        neither runs under self._lock: the callback can fire synchronously,
        on this thread, the moment it is attached (the Future may already be
        done by then) and it takes this same non-reentrant lock -- so the
        write has to already be visible, not racing it.
        """
        future = self._executor.submit(self._sidecar.synthesize, self._chunks[index]["text"], speaker)
        with self._lock:
            self._cache[index] = future
        future.add_done_callback(lambda f: self._drop_if_failed(index, f))
        return future

    def _drop_if_failed(self, index: int, future) -> None:
        """A prefetch that fails while the Sidecar is still starting must not
        poison that chunk forever: purged here, as soon as it fails, so the
        next _prefetch() resubmits it -- rather than waiting for a Play to
        stumble into the stale failure and replay it (this runs long before
        anyone may have tried to play it at all)."""
        if future.exception() is None:
            return
        with self._lock:
            if self._cache.get(index) is future:
                del self._cache[index]

    def play_current(self) -> None:
        with self._lock:
            index = self._index
            total = len(self._chunks)
            gen = self._generation
        if index >= total:
            with self._lock:
                self._playing = False
            self._notify({"type": "CHAPTER_DONE"})
            return
        self._prefetch()
        with self._lock:
            if gen != self._generation:
                return  # superseded by a skip/chunk-finish/load_chapter while prefetching
            chunk = self._chunks[index]
            total_paragraphs = len(self._paragraphs)
            paragraph_text = self._paragraphs[chunk["paragraphIndex"]]
            future = self._cache.get(index)
            speaker = self._speaker
        self._notify({
            "type": "CHUNK_INDEX",
            "paragraphIndex": chunk["paragraphIndex"],
            "totalParagraphs": total_paragraphs,
            "paragraphText": paragraph_text,
        })
        self._notify({"type": "PLAYBACK_STATE", "state": "buffering"})
        if future is None:
            future = self._submit(index, speaker)
        try:
            wav_bytes = future.result()
        except Exception as err:
            # _drop_if_failed has already purged this from the cache (it runs
            # as soon as the Future fails, before .result() raises here), so
            # the next Play resubmits instead of replaying this failure.
            # "idle", not "paused": nothing ever started, so the next Play
            # must retry play_current() rather than toggle_play() resuming
            # audio that was never loaded (see Controller.play_pause).
            self._notify({"type": "PLAYBACK_STATE", "state": "idle"})
            self._notify({"type": "ERROR", "message": f"Sidecar unreachable: {err}"})
            return
        with self._lock:
            if gen != self._generation:
                return  # superseded while waiting on synthesis
            try:
                self._audio.load(wav_bytes)
                self._audio.play(rate=self._rate)
            except Exception as err:
                # sounddevice raises PortAudioError when there is no usable
                # output device -- a box with no sound server, a missing
                # libportaudio, or a sample rate the backend refuses (the App
                # gets speed by scaling the rate, see audio_player). That used
                # to escape this thread and end the App; it belongs on the same
                # status line as a failed Sidecar request.
                self._playing = False
                self._notify({"type": "ERROR", "message": f"Could not play audio: {err}"})
                # "idle", not "paused" -- same reasoning as the synthesis
                # failure above: nothing ever started, so Play must retry.
                self._notify({"type": "PLAYBACK_STATE", "state": "idle"})
                return
            self._playing = True
        self._notify({"type": "PLAYBACK_STATE", "state": "playing"})

    def _on_chunk_finished(self) -> None:
        with self._lock:
            self._index += 1
            self._generation += 1
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

    def stop(self) -> None:
        """Silence playback right now.

        The App calls this as it closes, before anything slow (session save,
        Sidecar shutdown, which waits for the child to exit) can delay it --
        audio comes out of this process, not the Sidecar, so it would otherwise
        keep playing until the process finally went away. Bumping the
        generation also makes a play_current already blocked on synthesis bail
        out instead of starting the audio again on its way out."""
        with self._lock:
            self._playing = False
            self._generation += 1
        self._audio.stop()

    def skip(self, direction: int, steps: int = 1) -> None:
        """Jump `steps` paragraphs forward (direction > 0) or back.

        `steps` is clamped to the paragraphs that exist, so a coalesced burst
        past the end still lands on the last one instead of doing nothing."""
        if steps < 1 or direction == 0:
            return
        with self._lock:
            chunks = self._chunks
            index = self._index
            if index < len(chunks):
                current_paragraph = chunks[index]["paragraphIndex"]
            elif self._paragraphs:
                current_paragraph = len(self._paragraphs) - 1
            else:
                return
            paragraphs = sorted({chunk["paragraphIndex"] for chunk in chunks})
            if direction > 0:
                reachable = [p for p in paragraphs if p > current_paragraph]
            else:
                reachable = [p for p in paragraphs if p < current_paragraph]
            if not reachable:
                return
            desired = current_paragraph + direction * steps
            target_paragraph = min(reachable, key=lambda p: abs(p - desired))
            target = next(i for i, c in enumerate(chunks) if c["paragraphIndex"] == target_paragraph)
            self._index = target
            self._generation += 1
        # Fade the chunk being abandoned out and drop anything queued behind it
        # without closing the output stream: the target chunk is queued into
        # that same stream a moment from now, and reopening it would put the
        # same gap between two chunks that the join is supposed to have none of.
        self._audio.skip_to()
        self.play_current()
