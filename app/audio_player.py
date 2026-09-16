"""Plays synthesized WAV audio via sounddevice. Replaces the retired
extension's offscreen.js <audio> element (ADR-0002) -- this class lives in the
Python host, which survives page navigation on its own, so there is no
offscreen-document equivalent to build
(see docs/adr/0009-standalone-app-replaces-extension.md).

Rate changes are done by playing at samplerate * rate -- sounddevice's own
resampling-via-samplerate trick -- not a real time-stretch. This keeps rate
changes instant (ADR-0003), but pitch shifts with speed since nothing free
does pitch-preserving time-stretch outside a browser. Accepted trade-off,
see ADR-0009.

ponytail: finish detection is a background thread blocked on sd.wait(),
which also returns early when sd.stop() interrupts it -- the `_generation`
counter distinguishes "this play() call's audio actually finished" from
"someone called play()/pause()/stop() again before it did." Good enough for
one active playback at a time; would need real per-stream tracking if this
ever had to run two AudioPlayers concurrently.
"""
import io
import threading
import time

import sounddevice as sd
import soundfile as sf


class AudioPlayer:
    def __init__(self, on_finished):
        self.on_finished = on_finished
        self._data = None
        self._orig_sr = 0
        self._rate = 1.0
        self._offset_frames = 0
        self._start_time = None
        self._paused = False
        self._generation = 0

    def load(self, wav_bytes: bytes) -> None:
        data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
        self._data = data
        self._orig_sr = sr

    def play(self, rate: float = 1.0, start_frame: int = 0) -> None:
        self._generation += 1
        gen = self._generation
        sd.stop()
        self._rate = rate
        self._offset_frames = start_frame
        self._paused = False
        self._start_time = time.monotonic()
        remaining = self._data[start_frame:]
        sd.play(remaining, samplerate=self._orig_sr * rate)
        threading.Thread(target=self._watch_finish, args=(gen,), daemon=True).start()

    def _watch_finish(self, gen: int) -> None:
        # A PortAudio failure here has nowhere to go but the log/status line,
        # and it must not leave playback stuck on "playing" for a chunk that
        # never finished -- so it is treated as a finish, exactly like
        # sd.stop() interrupting the wait.
        try:
            sd.wait()
        except Exception:
            pass
        if gen == self._generation and not self._paused:
            self.on_finished()

    def _played_frames(self) -> int:
        elapsed = time.monotonic() - self._start_time
        return int(elapsed * self._orig_sr * self._rate)

    @property
    def sample_rate(self) -> int:
        return self._orig_sr

    def current_samples(self, count: int):
        """`count` mono samples starting at the playback position right now, or
        None when nothing is playing. Feeds the audio visualizer."""
        if self._data is None or self._paused or self._start_time is None:
            return None
        start = self._offset_frames + self._played_frames()
        segment = self._data[start:start + count]
        if len(segment) < count:
            return None
        if segment.ndim > 1:
            segment = segment.mean(axis=1)
        return segment

    def set_rate(self, rate: float) -> None:
        if self._data is None or self._paused or self._start_time is None:
            self._rate = rate
            return
        new_start = self._offset_frames + self._played_frames()
        self.play(rate=rate, start_frame=new_start)

    def pause(self) -> None:
        pause_offset = self._offset_frames + self._played_frames()
        sd.stop()
        self._paused = True
        self._offset_frames = pause_offset

    def resume(self) -> None:
        self.play(rate=self._rate, start_frame=self._offset_frames)

    def stop(self) -> None:
        self._generation += 1
        sd.stop()
        self._paused = False
