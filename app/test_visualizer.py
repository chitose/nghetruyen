import unittest
from unittest.mock import MagicMock

import numpy as np

from visualizer import BAND_COUNT, Visualizer, band_levels

SR = 16000


def sine(frequency=440.0, seconds=0.25, amplitude=0.5, sample_rate=SR):
    t = np.linspace(0, seconds, int(sample_rate * seconds), endpoint=False)
    return (amplitude * np.sin(2 * np.pi * frequency * t)).astype("float32")


class TestBandLevels(unittest.TestCase):
    def test_silence_is_flat(self):
        self.assertEqual(band_levels(np.zeros(2048, dtype="float32"), SR), [0.0] * BAND_COUNT)

    def test_a_loud_tone_raises_some_bands(self):
        levels = band_levels(sine(), SR)
        self.assertEqual(len(levels), BAND_COUNT)
        self.assertTrue(all(0.0 <= level <= 1.0 for level in levels))
        self.assertGreater(max(levels), 0.5)

    def test_the_tone_lands_in_the_low_bands(self):
        levels = band_levels(sine(440.0), SR, band_count=8)
        self.assertGreater(max(levels[:4]), max(levels[4:]))

    def test_a_higher_tone_lands_higher_up(self):
        low = band_levels(sine(200.0), SR).index(max(band_levels(sine(200.0), SR)))
        high = band_levels(sine(4000.0), SR).index(max(band_levels(sine(4000.0), SR)))
        self.assertGreater(high, low)

    def test_short_or_missing_input_is_flat(self):
        self.assertEqual(band_levels(None, SR), [0.0] * BAND_COUNT)
        self.assertEqual(band_levels(np.zeros(4, dtype="float32"), SR), [0.0] * BAND_COUNT)
        self.assertEqual(band_levels(np.zeros(2048, dtype="float32"), 0), [0.0] * BAND_COUNT)


def _player(samples):
    player = MagicMock()
    player.sample_rate = SR
    player.current_samples.return_value = samples
    return player


class TestVisualizer(unittest.TestCase):
    def test_snapshot_returns_one_level_per_band(self):
        viz = Visualizer(_player(sine()), band_count=8, window=2048)
        self.assertEqual(len(viz.snapshot()), 8)

    def test_snapshot_is_none_once_it_has_fallen_silent(self):
        player = _player(sine())
        viz = Visualizer(player, band_count=8, window=2048)
        self.assertIsNotNone(viz.snapshot())
        player.current_samples.return_value = None
        result = None
        for _ in range(20):
            result = viz.snapshot()
        self.assertIsNone(result)

    def test_bars_fall_instead_of_snapping_to_zero(self):
        player = _player(sine())
        viz = Visualizer(player, band_count=8, window=2048)
        loud = viz.snapshot()
        player.current_samples.return_value = None
        faded = viz.snapshot()
        self.assertIsNotNone(faded)
        self.assertLess(max(faded), max(loud))
        self.assertGreater(max(faded), 0.0)


if __name__ == "__main__":
    unittest.main()
