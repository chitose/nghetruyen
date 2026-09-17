# app/test_playback.py
import threading
import time
import unittest
from unittest.mock import MagicMock

from playback import PlaybackEngine

CHUNKS = [
    {"text": "Câu một.", "paragraphIndex": 0},
    {"text": "Câu hai.", "paragraphIndex": 0},
    {"text": "Đoạn hai.", "paragraphIndex": 1},
]
PARAGRAPHS = ["Câu một. Câu hai.", "Đoạn hai."]


class TestPlaybackEngine(unittest.TestCase):
    def setUp(self):
        self.sidecar = MagicMock()
        self.sidecar.synthesize.return_value = b"WAVDATA"
        self.audio = MagicMock()
        self.events = []
        self.engine = PlaybackEngine(self.sidecar, self.audio, notify=self.events.append)
        self.engine.load_chapter(CHUNKS, PARAGRAPHS, speaker="Minh Quân", rate=1.0)

    def test_load_chapter_prefetches_all_chunks_when_fewer_than_prefetch_ahead(self):
        # PREFETCH_AHEAD is 6; only 3 chunks exist, all should be requested.
        time.sleep(0.05)  # background executor threads
        self.assertEqual(self.sidecar.synthesize.call_count, 3)

    def test_prefetching_is_true_while_an_upcoming_chunk_is_still_synthesizing(self):
        release = threading.Event()
        sidecar = MagicMock()
        sidecar.synthesize.side_effect = lambda *_args: (release.wait(1), b"WAVDATA")[1]
        engine = PlaybackEngine(sidecar, MagicMock(), notify=lambda _e: None)
        engine.load_chapter(CHUNKS, PARAGRAPHS, speaker="Minh Quân", rate=1.0)
        time.sleep(0.02)  # let the executor threads pick the submitted futures up
        self.assertTrue(engine.prefetching)
        release.set()
        time.sleep(0.05)
        self.assertFalse(engine.prefetching)

    def test_prefetching_is_false_once_nothing_is_queued(self):
        time.sleep(0.05)  # setUp's load_chapter, with the default instant synthesize
        self.assertFalse(self.engine.prefetching)

    def test_the_chunk_about_to_play_does_not_itself_count_as_prefetching(self):
        # Synthesizing the *current* index is "buffering" (PLAYBACK_STATE),
        # not prefetching -- only chunks beyond it are lookahead work.
        release = threading.Event()
        sidecar = MagicMock()
        sidecar.synthesize.side_effect = lambda *_args: (release.wait(1), b"WAVDATA")[1]
        engine = PlaybackEngine(sidecar, MagicMock(), notify=lambda _e: None)
        engine.load_chapter([CHUNKS[0]], [PARAGRAPHS[0]], speaker="Minh Quân", rate=1.0)
        time.sleep(0.02)
        self.assertFalse(engine.prefetching)
        release.set()

    def test_play_current_loads_audio_and_notifies_chunk_index_then_playing(self):
        self.engine.play_current()
        self.audio.load.assert_called_with(b"WAVDATA")
        self.audio.play.assert_called_with(rate=1.0)
        types = [e["type"] for e in self.events]
        self.assertEqual(types, ["CHUNK_INDEX", "PLAYBACK_STATE", "PLAYBACK_STATE"])
        self.assertEqual(self.events[0]["paragraphText"], "Câu một. Câu hai.")
        self.assertEqual(self.events[-1]["state"], "playing")

    def test_chapter_done_notified_once_past_last_chunk(self):
        self.engine._index = len(CHUNKS)
        self.engine.play_current()
        self.assertEqual(self.events[-1], {"type": "CHAPTER_DONE"})

    def test_skip_jumps_to_first_chunk_of_adjacent_paragraph(self):
        self.engine._index = 0
        self.engine.skip(1)
        self.assertEqual(self.engine._index, 2)  # first chunk of paragraph 1

    def test_skip_keeps_the_output_stream_open(self):
        # skip() used to call audio.stop(), which closed the device. The
        # jumped-to chunk is queued into that same stream a moment later, and
        # reopening it there would put a gap between two chunks that the
        # streaming player exists to remove (ADR-0018).
        self.engine._index = 0
        self.audio.reset_mock()  # setUp's load_chapter legitimately stopped audio
        self.engine.skip(1)
        self.audio.skip_to.assert_called_once()
        self.audio.stop.assert_not_called()

    def test_skip_past_start_or_end_is_a_noop(self):
        self.engine._index = 0
        self.engine.skip(-1)
        self.assertEqual(self.engine._index, 0)

    def test_a_multi_paragraph_skip_clamps_to_the_last_paragraph(self):
        self.engine._index = 0
        self.engine.skip(1, steps=9)  # only paragraph 1 exists ahead
        self.assertEqual(self.engine._index, 2)

    def test_a_multi_paragraph_skip_back_clamps_to_the_first_paragraph(self):
        self.engine._index = 2  # in paragraph 1
        self.engine.skip(-1, steps=9)
        self.assertEqual(self.engine._index, 0)

    def test_skip_next_after_the_chapter_is_done_is_a_noop(self):
        self.engine._index = len(CHUNKS)  # the last chunk has finished
        self.engine.skip(1)
        self.assertEqual(self.engine._index, len(CHUNKS))

    def test_skip_back_after_the_chapter_is_done_reaches_the_previous_paragraph(self):
        self.engine._index = len(CHUNKS)
        self.engine.skip(-1)
        self.assertEqual(self.engine._index, 0)

    def test_stale_generation_play_current_does_not_touch_audio(self):
        # Simulate skip()/_on_chunk_finished running concurrently with
        # play_current()'s (blocking) call to _prefetch(): by the time
        # play_current() re-acquires the lock afterward to check the
        # generation, it must notice it moved on and bail out before
        # touching audio, rather than loading/playing a now-superseded chunk.
        self.engine._index = 0
        original_prefetch = self.engine._prefetch

        def prefetch_then_supersede():
            original_prefetch()
            self.engine._generation += 1  # simulate a concurrent skip()

        self.engine._prefetch = prefetch_then_supersede
        self.engine.play_current()
        self.audio.load.assert_not_called()
        self.audio.play.assert_not_called()

    def test_stop_silences_audio_and_marks_not_playing(self):
        self.engine.play_current()
        self.audio.reset_mock()
        self.engine.stop()
        self.audio.stop.assert_called_once()
        self.assertFalse(self.engine._playing)

    def test_stop_makes_a_pending_play_current_bail_out(self):
        # play_current() blocked in _prefetch() when the App closes must not
        # start audio on its way out.
        self.engine._index = 0
        original_prefetch = self.engine._prefetch

        def prefetch_then_close():
            original_prefetch()
            self.engine.stop()

        self.engine._prefetch = prefetch_then_close
        self.engine.play_current()
        self.audio.load.assert_not_called()
        self.audio.play.assert_not_called()

    def test_sidecar_error_notifies_error_and_idle(self):
        # "idle", not "paused": nothing ever started, so the next Play must
        # retry play_current() instead of toggle_play() resuming nothing.
        self.sidecar.synthesize.side_effect = RuntimeError("connection refused")
        engine = PlaybackEngine(self.sidecar, self.audio, notify=self.events.append)
        engine.load_chapter(CHUNKS, PARAGRAPHS, speaker="x", rate=1.0)
        time.sleep(0.05)
        self.events.clear()
        engine.play_current()
        types = [e["type"] for e in self.events]
        self.assertIn("ERROR", types)
        self.assertIn("Sidecar unreachable", self.events[[e["type"] for e in self.events].index("ERROR")]["message"])
        last_state = [e for e in self.events if e["type"] == "PLAYBACK_STATE"][-1]
        self.assertEqual(last_state["state"], "idle")

    def test_the_first_play_succeeds_if_the_sidecar_recovers_before_anyone_clicks(self):
        # The reported bug: Chapter load prefetches immediately, before the
        # Sidecar answers; by the time the reader sees it turn healthy and
        # presses Play, that first click must not replay the initial failure
        # -- _drop_if_failed purges it in the background, with no Play
        # involved at all.
        self.sidecar.synthesize.side_effect = RuntimeError("connection refused")
        engine = PlaybackEngine(self.sidecar, self.audio, notify=self.events.append)
        engine.load_chapter(CHUNKS, PARAGRAPHS, speaker="x", rate=1.0)
        time.sleep(0.05)  # the Sidecar was down for all of the initial prefetch
        self.sidecar.synthesize.side_effect = None
        self.sidecar.synthesize.return_value = b"WAVDATA"  # ... and now it is up
        engine.play_current()
        types = [e["type"] for e in self.events]
        self.assertNotIn("ERROR", types)
        self.audio.load.assert_called_with(b"WAVDATA")

    def test_play_after_a_sidecar_error_retries_instead_of_replaying_it(self):
        # A prefetch that failed while the Sidecar was still starting must not
        # poison that chunk forever -- once it recovers, the next Play has to
        # ask again rather than replay the cached failure.
        self.sidecar.synthesize.side_effect = RuntimeError("connection refused")
        engine = PlaybackEngine(self.sidecar, self.audio, notify=self.events.append)
        engine.load_chapter(CHUNKS, PARAGRAPHS, speaker="x", rate=1.0)
        time.sleep(0.05)
        engine.play_current()
        self.sidecar.synthesize.side_effect = None
        self.sidecar.synthesize.return_value = b"WAVDATA"
        self.events.clear()
        engine.play_current()
        types = [e["type"] for e in self.events]
        self.assertNotIn("ERROR", types)
        self.audio.load.assert_called_with(b"WAVDATA")

    def test_an_audio_device_that_refuses_to_play_is_reported_not_raised(self):
        # sounddevice raises PortAudioError with no output device, no
        # libportaudio, or a rate the backend rejects -- which on Linux is a
        # PipeWire question, not a hypothetical (ADR-0017). It used to escape
        # this thread and end the App.
        self.audio.play.side_effect = RuntimeError("Error opening OutputStream: Invalid sample rate")
        self.engine.play_current()
        types = [e["type"] for e in self.events]
        self.assertIn("ERROR", types)
        message = self.events[types.index("ERROR")]["message"]
        self.assertIn("Could not play audio", message)
        self.assertIn("Invalid sample rate", message)
        # ...and it must not claim to be playing, nor leave the chunk as if it
        # were merely paused (nothing ever started, so Play must retry it).
        self.assertEqual(self.events[-1], {"type": "PLAYBACK_STATE", "state": "idle"})
        self.assertFalse(self.engine._playing)

    def test_a_failing_audio_load_is_reported_too(self):
        # load() decodes with soundfile, so a truncated WAV surfaces here.
        self.audio.load.side_effect = RuntimeError("Error opening file: unknown format")
        self.engine.play_current()
        message = [e for e in self.events if e["type"] == "ERROR"][-1]["message"]
        self.assertIn("Could not play audio", message)


if __name__ == "__main__":
    unittest.main()
