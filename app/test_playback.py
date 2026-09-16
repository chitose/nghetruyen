# app/test_playback.py
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
        self.engine.load_chapter(CHUNKS, PARAGRAPHS, "session-1", speaker="Minh Quân", rate=1.0)

    def test_load_chapter_prefetches_all_chunks_when_fewer_than_prefetch_ahead(self):
        # PREFETCH_AHEAD is 6; only 3 chunks exist, all should be requested.
        time.sleep(0.05)  # background executor threads
        self.assertEqual(self.sidecar.synthesize.call_count, 3)

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

    def test_skip_past_start_or_end_is_a_noop(self):
        self.engine._index = 0
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

    def test_sidecar_error_notifies_error_and_paused(self):
        self.sidecar.synthesize.side_effect = RuntimeError("connection refused")
        engine = PlaybackEngine(self.sidecar, self.audio, notify=self.events.append)
        engine.load_chapter(CHUNKS, PARAGRAPHS, "session-2", speaker="x", rate=1.0)
        time.sleep(0.05)
        self.events.clear()
        engine.play_current()
        types = [e["type"] for e in self.events]
        self.assertIn("ERROR", types)
        self.assertIn("Sidecar unreachable", self.events[[e["type"] for e in self.events].index("ERROR")]["message"])


if __name__ == "__main__":
    unittest.main()
