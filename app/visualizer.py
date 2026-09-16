"""Turns the audio the App is playing right now into bar heights for the
control window's visualizer.

Audio plays in Python via sounddevice (ADR-0009), so there is no <audio>
element for the browser's Web Audio API to analyze. Instead this reads the
samples AudioPlayer is sending out at this moment and runs a small FFT over
them -- the bars show the Chapter being read, not a microphone.
"""
import numpy as np

BAND_COUNT = 28
WINDOW = 2048
MIN_DB = -60.0
DECAY = 0.72


def band_levels(samples, sample_rate, band_count=BAND_COUNT, min_db=MIN_DB):
    """Bar heights in 0..1 for `samples`, log-spaced from ~60 Hz to ~10 kHz."""
    if samples is None or len(samples) < 32 or not sample_rate:
        return [0.0] * band_count
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples)))) / (len(samples) / 2)
    frequencies = np.fft.rfftfreq(len(samples), d=1.0 / sample_rate)
    top = max(200.0, min(sample_rate / 2.0, 10000.0))
    edges = np.geomspace(60.0, top, band_count + 1)
    levels = []
    for low, high in zip(edges[:-1], edges[1:]):
        band = spectrum[(frequencies >= low) & (frequencies < high)]
        magnitude = float(band.max()) if band.size else 0.0
        decibels = 20.0 * np.log10(magnitude + 1e-9)
        levels.append(float(np.clip((decibels - min_db) / -min_db, 0.0, 1.0)))
    return levels


class Visualizer:
    """Smooths band_levels across frames, so bars fall instead of flickering."""

    def __init__(self, audio_player, band_count=BAND_COUNT, window=WINDOW, decay=DECAY):
        self._audio = audio_player
        self._band_count = band_count
        self._window = window
        self._decay = decay
        self._levels = [0.0] * band_count

    def snapshot(self):
        """Bar heights for this instant, or None once everything has fallen."""
        samples = self._audio.current_samples(self._window)
        if samples is None:
            self._levels = [level * self._decay for level in self._levels]
            if max(self._levels, default=0.0) < 0.01:
                self._levels = [0.0] * self._band_count
                return None
            return list(self._levels)
        levels = band_levels(samples, self._audio.sample_rate, self._band_count)
        self._levels = [
            max(level, previous * self._decay)
            for level, previous in zip(levels, self._levels)
        ]
        return list(self._levels)
