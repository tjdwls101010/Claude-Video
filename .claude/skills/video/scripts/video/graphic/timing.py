"""Frame and sample arithmetic of a render, exact at fractional rates such as 30000/1001."""

from __future__ import annotations

import math
from fractions import Fraction

from video.timecode import Rate


def frame_count(seconds: float, rate: Rate) -> int:
    """Duration x fps rounded to the nearest whole frame (half up), at least 1. The duration is read as the decimal it was written as."""
    return max(1, math.floor(Fraction(str(seconds)) * rate.fps + Fraction(1, 2)))


def frame_times(n: int, rate: Rate) -> list[float]:
    """Page time of each frame: frame i at i / fps, the last at (n - 1) / fps."""
    return [float(Fraction(i) / rate.fps) for i in range(n)]


def length(n: int, rate: Rate) -> Fraction:
    return Fraction(n) / rate.fps


def sample_count(n: int, rate: Rate, sample_rate: int) -> int:
    """Samples covering n frames exactly, rounded half up: 90 frames at 30000/1001 and 48 kHz are 144144."""
    return math.floor(length(n, rate) * sample_rate + Fraction(1, 2))
