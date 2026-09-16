import unittest
from unittest.mock import patch, MagicMock
import numpy as np

from audio_player import AudioPlayer


def _sine_wav_bytes(seconds=1.0, sr=16000):
    import io
    import soundfile as sf
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    data = (0.1 * np.sin(2 * np.pi * 440 * t)).astype("float32")
    buf = io.BytesIO()
    sf.write(buf, data, sr, format="WAV")
    return buf.getvalue()


class TestAudioPlayer(unittest.TestCase):
    @patch("audio_player.sd")
    def test_play_starts_sounddevice_at_rate_adjusted_samplerate(self, mock_sd):
        player = AudioPlayer(on_finished=lambda: None)
        player.load(_sine_wav_bytes(seconds=0.1, sr=16000))
        player.play(rate=1.5)
        mock_sd.stop.assert_called()
        args, kwargs = mock_sd.play.call_args
        self.assertEqual(kwargs["samplerate"], 16000 * 1.5)

    @patch("audio_player.sd")
    def test_set_rate_restarts_playback_from_elapsed_position(self, mock_sd):
        player = AudioPlayer(on_finished=lambda: None)
        player.load(_sine_wav_bytes(seconds=1.0, sr=16000))
        with patch("audio_player.time.monotonic", side_effect=[0.0, 0.5, 0.5]):
            player.play(rate=1.0)
            player.set_rate(2.0)
        # second play() call should start partway through the buffer, not at 0
        last_call_args = mock_sd.play.call_args
        played_array = last_call_args[0][0]
        self.assertLess(len(played_array), 16000)  # started after frame 0

    @patch("audio_player.sd")
    def test_set_rate_before_any_playback_does_not_crash(self, mock_sd):
        player = AudioPlayer(on_finished=lambda: None)
        player.load(_sine_wav_bytes(seconds=1.0, sr=16000))
        player.set_rate(1.5)  # never played yet -- must not raise
        mock_sd.play.assert_not_called()

    @patch("audio_player.sd")
    def test_set_rate_while_paused_does_not_resume_playback(self, mock_sd):
        player = AudioPlayer(on_finished=lambda: None)
        player.load(_sine_wav_bytes(seconds=1.0, sr=16000))
        with patch("audio_player.time.monotonic", side_effect=[0.0, 0.3]):
            player.play(rate=1.0)
            player.pause()
        mock_sd.play.reset_mock()
        player.set_rate(1.5)
        mock_sd.play.assert_not_called()  # must stay paused, not silently resume

    @patch("audio_player.sd")
    def test_pause_then_resume_continues_from_paused_position(self, mock_sd):
        player = AudioPlayer(on_finished=lambda: None)
        player.load(_sine_wav_bytes(seconds=1.0, sr=16000))
        with patch("audio_player.time.monotonic", side_effect=[0.0, 0.3, 0.3]):
            player.play(rate=1.0)
            player.pause()
            mock_sd.stop.assert_called()
            player.resume()
        played_array = mock_sd.play.call_args[0][0]
        self.assertLess(len(played_array), 16000)

    @patch("audio_player.threading.Thread")
    @patch("audio_player.sd")
    def test_play_while_generation_stale_watcher_does_not_fire_on_finished(self, mock_sd, mock_thread):
        # Prevent play() from starting a real background thread (mock_thread) so
        # the only call to _watch_finish is the one we trigger manually below --
        # this keeps the test deterministic instead of racing a real thread.
        calls = []
        player = AudioPlayer(on_finished=lambda: calls.append("finished"))
        player.load(_sine_wav_bytes(seconds=1.0, sr=16000))
        player.play(rate=1.0)
        stale_gen = player._generation  # what the first play()'s watcher thread captured
        # Simulate the OLD watcher thread's sd.wait() unblocking exactly when the
        # NEXT play() call invokes sd.stop() -- that is the real race: the old
        # watcher wakes as a direct side effect of sd.stop(), so it matters
        # whether self._generation was bumped before or after that call.
        mock_sd.stop.side_effect = lambda: player._watch_finish(stale_gen)
        player.play(rate=1.5)  # bumps generation; sd.stop() wakes the stale watcher
        self.assertEqual(calls, [])  # must NOT have fired on_finished for the stale generation

    @patch("audio_player.sd")
    def test_stop_calls_sounddevice_stop(self, mock_sd):
        player = AudioPlayer(on_finished=lambda: None)
        player.load(_sine_wav_bytes(seconds=0.1, sr=16000))
        player.play(rate=1.0)
        player.stop()
        self.assertGreaterEqual(mock_sd.stop.call_count, 2)

    @patch("audio_player.sd")
    def test_current_samples_returns_the_window_being_played(self, mock_sd):
        player = AudioPlayer(on_finished=lambda: None)
        player.load(_sine_wav_bytes(seconds=1.0, sr=16000))
        with patch("audio_player.time.monotonic", return_value=0.0):
            player.play(rate=1.0)
            samples = player.current_samples(1024)
        self.assertIsNotNone(samples)
        self.assertEqual(len(samples), 1024)
        self.assertEqual(player.sample_rate, 16000)

    @patch("audio_player.sd")
    def test_current_samples_is_none_when_nothing_is_playing(self, mock_sd):
        player = AudioPlayer(on_finished=lambda: None)
        self.assertIsNone(player.current_samples(1024))
        player.load(_sine_wav_bytes(seconds=0.1, sr=16000))
        with patch("audio_player.time.monotonic", return_value=0.0):
            player.play(rate=1.0)
            player.pause()
        self.assertIsNone(player.current_samples(1024))

    @patch("audio_player.sd")
    def test_current_samples_is_none_past_the_end(self, mock_sd):
        player = AudioPlayer(on_finished=lambda: None)
        player.load(_sine_wav_bytes(seconds=0.1, sr=16000))  # 1600 frames
        with patch("audio_player.time.monotonic", side_effect=[0.0, 10.0]):
            player.play(rate=1.0)
            self.assertIsNone(player.current_samples(1024))

    @patch("audio_player.threading.Thread")
    @patch("audio_player.sd")
    def test_stop_while_generation_stale_watcher_does_not_fire_on_finished(self, mock_sd, mock_thread):
        # Same race as the play() test above, but for stop(): the watcher thread
        # from the original play() call wakes as a direct side effect of stop()'s
        # own sd.stop() call, so _generation must already be bumped by then.
        calls = []
        player = AudioPlayer(on_finished=lambda: calls.append("finished"))
        player.load(_sine_wav_bytes(seconds=1.0, sr=16000))
        player.play(rate=1.0)
        stale_gen = player._generation
        mock_sd.stop.side_effect = lambda: player._watch_finish(stale_gen)
        player.stop()  # bumps generation; sd.stop() wakes the stale watcher
        self.assertEqual(calls, [])  # must NOT have fired on_finished for the stale generation


if __name__ == "__main__":
    unittest.main()
