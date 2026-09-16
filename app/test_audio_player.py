import io
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import soundfile as sf

from audio_player import EDGE_FADE_SECONDS, AudioPlayer, _Queued


def _mono_wav_bytes(seconds=0.1, sr=16000, amplitude=0.25, frequency=440.0, lead_ms=0.0, tail_ms=0.0):
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    body = (amplitude * np.sin(2 * np.pi * frequency * t)).astype("float32")
    data = np.concatenate([
        np.zeros(int(sr * lead_ms / 1000), dtype="float32"),
        body,
        np.zeros(int(sr * tail_ms / 1000), dtype="float32"),
    ])
    buf = io.BytesIO()
    sf.write(buf, data, sr, format="WAV")
    return buf.getvalue()


def _flat_wav_bytes(seconds=0.1, sr=16000, amplitude=0.25):
    """A constant signal: silence in the output is then unambiguous."""
    buf = io.BytesIO()
    sf.write(buf, np.full(int(sr * seconds), amplitude, dtype="float32"), sr, format="WAV")
    return buf.getvalue()


class _FakeStream:
    """Stands in for sd.OutputStream, recording the calls the player makes on
    it. It never calls back on its own: the tests drive the callback by hand
    (`drain`) so that what is written can be inspected sample by sample."""

    def __init__(self, samplerate, callback):
        self.samplerate = samplerate
        self.callback = callback
        self.started = False
        self.aborted = False

    def start(self):
        self.started = True

    def abort(self, *args, **kwargs):
        self.aborted = True


class AudioPlayerTestCase(unittest.TestCase):
    """Everything runs with sounddevice mocked: the callback is driven by hand,
    which is the only way to test the sample-level join between chunks."""

    def setUp(self):
        self.patcher = patch("audio_player.sd")
        self.sd = self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.streams = []

        def make_stream(**kwargs):
            stream = _FakeStream(kwargs["samplerate"], kwargs["callback"])
            self.streams.append(stream)
            return stream

        self.sd.OutputStream.side_effect = make_stream
        self.finished = []
        self.player = AudioPlayer(on_finished=lambda: self.finished.append(True))

    def last_stream(self):
        return self.streams[-1]

    def drain(self, blocks=1, frames=512):
        """Run the callback the way the output stream would."""
        written = []
        for _ in range(blocks):
            out = np.zeros((frames, 1), dtype="float32")
            self.player._callback(out, frames, None, None)
            written.append(out[:, 0].copy())
        return np.concatenate(written)


class TestQueueAndGaplessJoin(AudioPlayerTestCase):
    def test_a_chunk_is_queued_exactly_as_decoded(self):
        wav = _mono_wav_bytes(seconds=0.1, sr=16000)
        self.player.load(wav)
        queued = self.player._queue[0]
        self.assertEqual(queued.sample_rate, 16000)
        self.assertEqual(len(queued.data), 1600)

    def test_The_join_between_two_chunks_has_no_silence_in_it(self):
        # The whole point of the queue: the next chunk is already in memory as
        # samples, so it follows the previous one inside the same callback block.
        # A flat signal is used so that any hole shows up as exact zeros rather
        # than being confused with a sine's own zero crossings.
        chunk = 800  # 0.05 s at 16 kHz
        self.player.load(_flat_wav_bytes(seconds=0.05))
        self.player._playing = True
        self.player.load(_flat_wav_bytes(seconds=0.05))
        audio = self.drain(blocks=2, frames=chunk)  # exactly two chunks' worth
        # The fade region of chunk 1 is the only quiet part; chunk 2 follows it
        # immediately, with no silent block in between.
        fade = max(1, int(16000 * EDGE_FADE_SECONDS))
        joined = audio[chunk - fade // 2:chunk + fade // 2]
        self.assertGreater(float(np.max(np.abs(joined))), 0.2)
        # ...and there is no all-zero stretch spanning the boundary.
        self.assertGreater(np.count_nonzero(audio[chunk - 4:chunk + 4]), 3)

    def test_a_chunk_queued_mid_chunk_plays_before_the_chapter_advances(self):
        # What the prefetch does: the next chunk is queued while this one is
        # still playing. Nothing is reported finished until both are done.
        self.player.load(_flat_wav_bytes(seconds=0.05))  # 800 frames
        self.player._playing = True
        self.drain(blocks=1, frames=400)  # half of chunk 1
        self.assertEqual(self.finished, [])
        self.player.load(_flat_wav_bytes(seconds=0.05))  # next chunk arrives
        self.drain(blocks=1, frames=400)  # second half of chunk 1
        self.assertEqual(self.finished, [])  # chunk 2 is playing, not done
        self.drain(blocks=2, frames=400)  # chunk 2 drains
        self.assertEqual(len(self.finished), 1)

    def test_the_finish_is_reported_once_the_queue_runs_dry(self):
        self.player.load(_mono_wav_bytes(seconds=0.01))  # 160 frames
        self.player._playing = True
        self.drain(blocks=4, frames=160)
        self.assertEqual(len(self.finished), 1)

    def test_an_empty_queue_is_reported_only_once(self):
        # The stream keeps calling the callback while the next chunk is still
        # being synthesized, so "ran dry" must not be reported on every block.
        self.player.load(_mono_wav_bytes(seconds=0.01))
        self.player._playing = True
        self.drain(blocks=10, frames=160)
        self.assertEqual(len(self.finished), 1)

    def test_loading_the_next_chunk_rearms_the_finish_report(self):
        self.player.load(_mono_wav_bytes(seconds=0.01))
        self.player._playing = True
        self.drain(blocks=4, frames=160)
        self.player.load(_mono_wav_bytes(seconds=0.01))
        self.drain(blocks=4, frames=160)
        self.assertEqual(len(self.finished), 2)


class TestEdgeFade(AudioPlayerTestCase):
    def test_the_tail_is_faded_to_silence(self):
        # A chunk that ends on a live sample must not step straight to zero:
        # that step is the click between chunks.
        self.player.load(_flat_wav_bytes(seconds=0.02))  # 320 frames
        item = self.player._queue[0]
        self.player._playing = True
        audio = self.drain(blocks=1, frames=400)
        self.assertEqual(abs(float(audio[-1])), 0.0)  # fully faded by the end
        self.assertLess(abs(float(audio[item.fade_start + item.fade_out // 2])), 0.25 * 0.8)

    def test_the_fade_does_not_restart_at_every_callback_block(self):
        # The tail spans several small blocks; measuring the fade from "how much
        # is left" instead of an absolute frame would ramp it down repeatedly and
        # attenuate far more than the last few milliseconds.
        frames = 4800  # 0.3 s at 16 kHz
        self.player.load(_flat_wav_bytes(seconds=0.3))
        item = self.player._queue[0]
        fade = max(1, int(16000 * EDGE_FADE_SECONDS))
        self.assertEqual(item.fade_start, frames - fade)
        self.player._playing = True
        audio = self.drain(blocks=12, frames=400)
        # Well before the fade starts the signal is still at full amplitude.
        self.assertGreater(float(np.max(np.abs(audio[400:800]))), 0.24)


class TestStreamLifecycle(AudioPlayerTestCase):
    def test_play_opens_a_stream_at_the_chunks_own_rate(self):
        self.player.load(_mono_wav_bytes(seconds=0.1, sr=16000))
        self.player.play(rate=1.0)
        self.assertEqual(self.sd.OutputStream.call_args.kwargs["samplerate"], 16000)
        self.assertEqual(self.sd.OutputStream.call_args.kwargs["channels"], 1)

    def test_speed_scales_the_stream_rate_instead_of_resampling(self):
        self.player.load(_mono_wav_bytes(seconds=0.1, sr=16000))
        self.player.play(rate=1.5)
        self.assertEqual(self.sd.OutputStream.call_args.kwargs["samplerate"], 16000 * 1.5)

    def test_play_leaves_an_already_running_stream_alone(self):
        # This is the fix for the gap: PlaybackEngine calls play() once per
        # chunk, and reopening the device there would put the hole back.
        self.player.load(_mono_wav_bytes(seconds=0.1, sr=16000))
        self.player.play(rate=1.0)
        opened = self.sd.OutputStream.call_count
        self.player.load(_mono_wav_bytes(seconds=0.1, sr=16000))
        self.player.play(rate=1.0)
        self.assertEqual(self.sd.OutputStream.call_count, opened)

    def test_pause_closes_the_stream_and_resume_reopens_it(self):
        self.player.load(_mono_wav_bytes(seconds=0.1, sr=16000))
        self.player.play(rate=1.0)
        stream = self.player._stream
        self.player.pause()
        self.assertTrue(stream.aborted)
        self.assertIsNone(self.player._stream)
        self.assertFalse(self.player._playing)
        self.player.resume()
        self.assertIsNotNone(self.player._stream)
        self.assertTrue(self.player._playing)

    def test_stop_silences_and_closes(self):
        self.player.load(_mono_wav_bytes(seconds=0.1, sr=16000))
        self.player.play(rate=1.0)
        self.player.stop()
        self.assertIsNone(self.player._stream)
        self.assertFalse(self.player._playing)
        self.assertEqual(self.player._queue, [])

    def test_skip_to_keeps_the_stream_open(self):
        # Skipping queues the jumped-to chunk into the same stream a moment
        # later, so the device must not be closed here.
        self.player.load(_mono_wav_bytes(seconds=0.1, sr=16000))
        self.player.play(rate=1.0)
        self.player.skip_to()
        self.assertIsNotNone(self.player._stream)
        self.assertEqual(self.player._queue, [])

    def test_a_rate_change_reopens_the_stream_at_the_new_rate(self):
        self.player.load(_mono_wav_bytes(seconds=0.1, sr=16000))
        self.player.play(rate=1.0)
        self.player.set_rate(2.0)
        self.assertEqual(self.sd.OutputStream.call_args.kwargs["samplerate"], 32000)

    def test_a_rate_change_before_playback_does_not_open_anything(self):
        self.player.load(_mono_wav_bytes(seconds=0.1, sr=16000))
        self.player.set_rate(1.5)
        self.sd.OutputStream.assert_not_called()

    def test_a_rate_change_while_paused_does_not_resume(self):
        self.player.load(_mono_wav_bytes(seconds=0.1, sr=16000))
        self.player.play(rate=1.0)
        self.player.pause()
        self.sd.OutputStream.reset_mock()
        self.player.set_rate(1.5)
        self.sd.OutputStream.assert_not_called()
        self.assertFalse(self.player._playing)

    def test_play_while_paused_resumes(self):
        self.player.load(_mono_wav_bytes(seconds=0.1, sr=16000))
        self.player.play(rate=1.0)
        self.player.pause()
        self.player.play(rate=1.0)
        self.assertTrue(self.player._playing)
        self.assertIsNotNone(self.player._stream)

    def test_a_stale_finish_after_a_skip_is_not_reported(self):
        # The callback captured the generation before the skip bumped it.
        self.player.load(_mono_wav_bytes(seconds=0.01))
        self.player.play(rate=1.0)
        stale = self.player._generation
        self.player.skip_to()
        self.player._report_finished(stale)
        self.assertEqual(self.finished, [])

    def test_an_empty_wav_is_not_queued_as_a_chunk(self):
        buf = io.BytesIO()
        sf.write(buf, np.zeros(0, dtype="float32"), 16000, format="WAV")
        self.player.load(buf.getvalue())
        self.assertEqual(self.player._queue, [])


class TestCurrentSamples(AudioPlayerTestCase):
    def test_current_samples_follows_the_playback_position(self):
        self.player.load(_mono_wav_bytes(seconds=0.1, sr=16000))
        self.player._playing = True
        self.drain(blocks=1, frames=160)  # 160 frames consumed
        self.player._chunk_sr = 16000
        samples = self.player.current_samples(64)
        self.assertIsNotNone(samples)
        self.assertEqual(len(samples), 64)
        # It is the window 160 frames into the chunk, not the start of it.
        self.assertFalse(np.allclose(samples, np.zeros(64)))

    def test_current_samples_is_none_when_nothing_is_loaded_or_playing(self):
        self.assertIsNone(self.player.current_samples(64))
        self.player.load(_mono_wav_bytes(seconds=0.1, sr=16000))
        self.assertIsNone(self.player.current_samples(64))  # not playing yet

    def test_current_samples_is_none_while_paused(self):
        self.player.load(_mono_wav_bytes(seconds=0.1, sr=16000))
        self.player._playing = True
        self.drain(blocks=1, frames=160)
        self.player.pause()
        self.assertIsNone(self.player.current_samples(64))

    def test_current_samples_is_none_past_the_end_of_the_chunk(self):
        self.player.load(_mono_wav_bytes(seconds=0.01, sr=16000))  # 160 frames
        self.player._playing = True
        self.drain(blocks=1, frames=160)
        self.assertIsNone(self.player.current_samples(64))

    def test_sample_rate_is_the_chunks_own(self):
        self.player.load(_mono_wav_bytes(seconds=0.1, sr=22050))
        self.assertEqual(self.player.sample_rate, 22050)


class TestQueuedItem(unittest.TestCase):
    def test_the_fade_is_anchored_to_the_end_of_the_chunk(self):
        item = _Queued(np.ones(16000, dtype="float32"), 16000)
        self.assertEqual(item.offset, 0)
        self.assertEqual(item.fade_out, int(16000 * EDGE_FADE_SECONDS))
        self.assertEqual(item.fade_start, 16000 - item.fade_out)

    def test_a_chunk_shorter_than_the_fade_still_fades(self):
        item = _Queued(np.ones(10, dtype="float32"), 16000)
        self.assertEqual(item.fade_out, 10)
        self.assertEqual(item.fade_start, 0)


if __name__ == "__main__":
    unittest.main()
