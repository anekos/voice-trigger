"""Amplitude-based onset detection for short trigger sounds."""

from __future__ import annotations

from array import array


def peak_level(chunk: bytes) -> float:
    samples = array("h")
    samples.frombytes(chunk)
    if not samples:
        return 0.0
    return max(abs(sample) for sample in samples) / 32768


class OnsetDetector:
    def __init__(self, threshold: float, cooldown: float) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self._above = False
        self._last_trigger: float | None = None

    def process(self, chunk: bytes, now: float) -> bool:
        level = peak_level(chunk)
        was_above = self._above
        self._above = level >= self.threshold
        if not self._above or was_above:
            return False
        if self._last_trigger is not None and now - self._last_trigger < self.cooldown:
            return False
        self._last_trigger = now
        return True
