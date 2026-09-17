"""Plays synthesized WAV audio via sounddevice. Replaces the retired
extension's offscreen.js <audio> element (ADR-0002) -- this class lives in the
Python host, which survives page navigation on its own, so there is no
offscreen-document equivalent to build
(see docs/adr/0009-standalone-app-replaces-extension.md).

One stream, many chunks. A chunk is queued as samples and drained by the output
stream's own callback, so the next chunk is already in memory when the current
one runs out and there is no restart between them. The previous design called
`sd.play()` once per chunk, which cost a measured 94-130 ms of silence at every
Chunk boundary on the development machine: `sd.wait()` returns as soon as
PortAudio has *consumed* the buffer, which is one output latency (~90 ms here)
before that audio has actually been heard, and the replacement stream then took
another ~15 ms to spool up. Because VieNeu leaves only 8-10 ms of trailing
silence on a chunk, that hole was the whole audible gap between sentences.

Trade-off: skipping is a fade the length of `SKIP_FADE_SECONDS` rather than the
instant cut `sd.stop()` gives, because the stream is shared with whatever is
already queued.

Rate changes reopen the stream at a scaled samplerate -- sounddevice's own
resampling-via-samplerate trick -- not a real time-stretch. This keeps rate
changes instant (ADR-0003), but pitch shifts with speed since nothing free does
pitch-preserving time-stretch outside a browser. Accepted trade-off, see
ADR-0009.

ponytail: the callback runs on PortAudio's thread, so it only ever touches the
queue under `_lock` and never calls `sd.*` itself -- stream opens, restarts and
stops happen on an app thread. `on_finished` is what the App uses to advance a
Chapter, so it is reported exactly once per queued chunk, on a thread of its
own, and never while paused or after a stop/skip flush.
"""
import io
import threading

import numpy as np
import sounddevice as sd
import soundfile as sf

# A few milliseconds at each chunk edge: VieNeu's edges are already quiet
# (~0.005 of peak, and only 8-10 ms of trailing silence), so these only remove
# the step a cut would leave -- they are not there to fade the speech itself.
EDGE_FADE_SECONDS = 0.005
# How quickly a skip or stop takes the queued audio down, instead of cutting it
# off mid-cycle.
SKIP_FADE_SECONDS = 0.012


def play_once(wav_bytes: bytes) -> None:
    """A single, blocking playback on a stream of its own -- for previewing a
    voice sample from Options, which has no Chapter position or on_finished
    to coordinate with and must not disturb (or be disturbed by) whatever
    AudioPlayer is already doing for the reader. Call this from a thread of
    its own; `sd.wait()` blocks until playback finishes.
    """
    data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
    sd.play(data, sr)
    sd.wait()


class _Queued:
    """One chunk waiting for the callback: its samples, where the callback has
    read up to, and which frame the trailing fade starts at.

    The fade is anchored to an absolute frame, not to how much is left, because
    the callback sees the tail across several small blocks -- measuring from
    "remaining" would restart the ramp at every block and quietly attenuate the
    whole tail instead of its last few milliseconds.
    """

    def __init__(self, data, sample_rate):
        self.data = data
        self.sample_rate = sample_rate
        self.offset = 0
        self.fade_out = min(len(data), max(1, int(sample_rate * EDGE_FADE_SECONDS)))
        self.fade_start = max(0, len(data) - self.fade_out)


class AudioPlayer:
    def __init__(self, on_finished):
        self.on_finished = on_finished
        self._lock = threading.Lock()
        self._stream_lock = threading.Lock()  # serializes sd.Stream open/restart
        self._queue = []
        self._stream = None
        self._playing = False
        self._paused = False
        self._rate = 1.0
        self._generation = 0
        self._started = threading.Event()
        # True once the queue has run dry and that has been reported, until the
        # App queues the next chunk or starts a new play. The callback keeps
        # running while the next chunk is still being synthesized, so without
        # this every dry block would report another finished chunk.
        self._drained = False
        # what current_samples/the visualizer needs
        self._current = None
        self._position = 0.0  # frames read out of _current
        self._chunk_sr = 0

    # --- what PlaybackEngine calls -------------------------------------------

    def load(self, wav_bytes: bytes) -> None:
        """Queue a chunk. Replaces anything still waiting -- the App always
        means "play this next", never "play this after what is queued"."""
        data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        data = np.ascontiguousarray(data, dtype="float32")
        if len(data) == 0:
            return  # nothing to play; the empty-audio case is not a chunk
        with self._lock:
            self._queue = [_Queued(data, sr)]
            self._current = None
            self._position = 0.0
            self._chunk_sr = sr
            self._drained = False
        # The stream carries whatever the Sidecar synthesized, so a chunk at a
        # different rate than the open stream means reopening it.
        if self._playing and not self._paused and self._stream is not None:
            self._restart_stream_if_needed(sr * self._rate)

    def play(self, rate: float = 1.0, start_frame: int = 0) -> None:
        """Start playing, or keep playing.

        The App calls this once per chunk (`PlaybackEngine.play_current`), but a
        stream that is already running is left alone: the chunk the caller just
        `load()`ed is queued behind whatever is still draining, which is what
        makes the join between chunks seamless. Restarting here would reopen the
        device between every pair of chunks and give back the very gap this
        class exists to avoid."""
        self._generation += 1
        self._paused = False
        with self._lock:
            self._rate = rate
            self._drained = False
            if start_frame:
                item = self._current or (self._queue[0] if self._queue else None)
                if item is not None:
                    item.offset = min(start_frame, len(item.data))
        self._playing = True
        if self._stream is not None:
            return
        self._started.clear()
        with self._stream_lock:
            if self._stream is None:
                self._open_stream()
        # The first callback that finds queued audio clears this. Waiting for it
        # means a device that opened but never called back is reported through
        # the App's error path instead of looking like silent playback.
        self._started.wait(1.0)

    def _restart_stream_if_needed(self, samplerate: float) -> None:
        with self._stream_lock:
            stream = self._stream
            if stream is not None and abs(stream.samplerate - samplerate) < 1:
                return
            self._close_stream()
            self._open_stream()

    def pause(self) -> None:
        self._paused = True
        self._playing = False
        self._close_stream()

    def resume(self) -> None:
        if self._paused:
            self.play(rate=self._rate)

    def set_rate(self, rate: float) -> None:
        with self._lock:
            unchanged = rate == self._rate
            self._rate = rate
        if unchanged:
            return
        if self._playing and not self._paused and self._stream is not None:
            # Already-played audio is behind us; the stream reopens at the new
            # samplerate and carries on from where this chunk got to.
            self._restart_stream_if_needed(self._stream_samplerate())

    def stop(self) -> None:
        """Silence playback now, drop anything queued, and close the stream.

        The App calls this as it closes, before anything slow (session save,
        Sidecar shutdown, which waits for the child to exit) can delay it --
        audio comes out of this process, not the Sidecar, so it would otherwise
        keep playing until the process finally went away."""
        self._generation += 1
        self._playing = False
        self._paused = False
        with self._lock:
            self._fade_out_locked()
        self._close_stream()

    def skip_to(self) -> None:
        """Drop what is queued and fade the current chunk out, but keep the
        stream open -- the App queues the jumped-to chunk immediately after, and
        reopening the device for that is the gap this class exists to avoid."""
        self._generation += 1  # a finish already on its way must not fire now
        with self._lock:
            self._fade_out_locked()
            self._drained = False

    # --- for the visualizer --------------------------------------------------

    @property
    def sample_rate(self) -> int:
        return self._chunk_sr

    def current_samples(self, count: int):
        """`count` mono samples starting at the playback position right now, or
        None when nothing is playing. Feeds the audio visualizer, which would
        rather have nothing than a stale frame."""
        if not self._playing or self._paused:
            return None
        with self._lock:
            current = self._current
            if current is None:
                return None
            start = int(self._position)
            segment = current.data[start:start + count]
            if len(segment) < count:
                return None
            return segment.copy()

    # --- stream plumbing -----------------------------------------------------

    def _stream_samplerate(self) -> float:
        """The device rate for the chunk on the queue at the current speed. A
        chunk is written sample-for-sample, so playing it `rate` times faster
        is the same as asking the device for `rate` times the rate."""
        with self._lock:
            chunk_sr = self._chunk_sr or 24000
            rate = self._rate
        return chunk_sr * rate

    def _open_stream(self):
        samplerate = self._stream_samplerate()
        stream = sd.OutputStream(
            samplerate=samplerate, channels=1, dtype="float32",
            blocksize=0, callback=self._callback,
        )
        stream.start()
        with self._lock:
            self._stream = stream
        # One zero-length call: it consumes nothing, but it gives the stream the
        # first callback it is waiting for, so the App can tell "device running
        # but silent" apart from "device never came up".
        self._callback(np.zeros((0, 1), dtype="float32"), 0, None, None)

    def _close_stream(self) -> None:
        with self._lock:
            stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.abort(ignore_errors=True)
        except TypeError:  # older sounddevice: no ignore_errors
            stream.abort()
        except Exception:
            pass

    def _fade_out_locked(self) -> None:
        """Call with `_lock` held: take the queued audio down over a few
        milliseconds instead of cutting whatever is mid-sample."""
        if self._current is not None:
            fade = max(1, int(self._current.sample_rate * SKIP_FADE_SECONDS))
            self._current.fade_out = fade
            self._current.fade_start = max(self._current.offset, len(self._current.data) - fade)
        for item in self._queue:
            item.offset = len(item.data)
        self._queue = []
        self._position = 0.0

    # --- the audio thread ----------------------------------------------------

    def _callback(self, outdata, frames, time_info, status):
        """Fill one block, moving to the next queued chunk as the current one
        runs out. Never calls back into sounddevice: `_flush_locked` marks the
        audio and `_report_finished` does the stream work on another thread."""
        with self._lock:
            generation = self._generation
            rate = self._rate
            out = outdata[:, 0]
            out.fill(0.0)
            written = 0
            ran_dry = False
            while written < frames:
                if self._current is None:
                    if not self._queue:
                        ran_dry = not self._drained
                        self._drained = True
                        break
                    self._current = self._queue.pop(0)
                    self._position = 0.0
                current = self._current
                remaining = len(current.data) - current.offset
                if remaining <= 0:  # spent: the next chunk, or silence
                    self._current = None
                    continue
                take = min(frames - written, remaining)
                block = current.data[current.offset:current.offset + take]
                if take and current.offset + take > current.fade_start:
                    # Squeeze the last few milliseconds to zero, so a chunk that
                    # ends on a live sample (or a skip that cuts one short) does
                    # not step to silence. The ramp runs 0..1 across the whole
                    # fade region, so the region's build-up is not affected by
                    # where the callback's blocks happen to fall.
                    span = len(current.data) - current.fade_start
                    ramp = np.linspace(
                        (current.offset - current.fade_start) / span,
                        (current.offset + take - current.fade_start) / span,
                        take, dtype="float32",
                    )
                    block = block * np.clip(ramp, 0.0, 1.0)
                out[written:written + take] = block
                current.offset += take
                written += take
                # Device frames come out at samplerate == chunk rate * rate, so
                # this is the position in the chunk's own samples.
                self._position += take / rate
            self._started.set()
        if ran_dry:
            self._report_finished(generation)

    def _report_finished(self, generation: int) -> None:
        if not self._playing or self._paused or generation != self._generation:
            return  # a skip/stop/load already took over
        # On its own thread: on_finished runs the App's chunk advance, which
        # synthesizes and calls back in here.
        threading.Thread(target=self.on_finished, daemon=True).start()
