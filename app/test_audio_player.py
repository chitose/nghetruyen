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

    @patch("audio_player.sd")
    def test_stop_calls_sounddevice_stop(self, mock_sd):
        player = AudioPlayer(on_finished=lambda: None)
        player.load(_sine_wav_bytes(seconds=0.1, sr=16000))
        player.play(rate=1.0)
        player.stop()
        self.assertGreaterEqual(mock_sd.stop.call_count, 2)


if __name__ == "__main__":
    unittest.main()
