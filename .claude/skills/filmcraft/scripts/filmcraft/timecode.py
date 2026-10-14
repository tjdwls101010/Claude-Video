"""Time on a FilmCraft timeline: integer ticks (254 016 000 000 per second), frames at a rational rate, and SMPTE timecode. Frame math matches FilmCraft's own: a tick belongs to the frame that contains it (floor), and a frame starts at the ceiling of its rational boundary, so `frame_at(tick_of(f)) == f` at every rate."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

TICKS_PER_SECOND = 254_016_000_000


def ticks(seconds: float | Fraction) -> int:
    return round(Fraction(seconds) * TICKS_PER_SECOND)


def seconds(t: int) -> float:
    return t / TICKS_PER_SECOND


@dataclass(frozen=True)
class Rate:
    num: int
    den: int = 1

    @classmethod
    def parse(cls, text: str) -> "Rate":
        """`30000/1001`, `29.97`, `30`: decimal NTSC spellings map to their exact x/1001 rate."""
        if "/" in text:
            n, d = text.split("/", 1)
            return cls(int(n), int(d))
        f = float(text)
        for n in (24000, 30000, 60000, 120000):
            if abs(f - n / 1001) < 0.005:
                return cls(n, 1001)
        fr = Fraction(text).limit_denominator(1001)
        return cls(fr.numerator, fr.denominator)

    @property
    def fps(self) -> Fraction:
        return Fraction(self.num, self.den)

    def label(self) -> str:
        if self.den == 1:
            return str(self.num)
        return f"{self.num / self.den:.3f}".rstrip("0").rstrip(".")

    def frame_at(self, t: int) -> int:
        return (t * self.num) // (TICKS_PER_SECOND * self.den)

    def tick_of(self, frame: int) -> int:
        n = frame * TICKS_PER_SECOND * self.den
        return -((-n) // self.num)

    def frame_of_seconds(self, s: float) -> int:
        return self.frame_at(ticks(s))

    def seconds_of(self, frame: int) -> float:
        return seconds(self.tick_of(frame))

    @property
    def timecode_base(self) -> int:
        """Frames counted per timecode second: 30 for 29.97, 24 for 23.976."""
        return -((-self.num) // self.den)

    @property
    def supports_drop_frame(self) -> bool:
        return self.den == 1001 and self.timecode_base % 30 == 0

    def timecode(self, frame: int, drop: bool = False) -> str:
        """`HH:MM:SS:FF`, or `HH:MM:SS;FF` drop-frame (SMPTE 12M: skip the first 2 numbers per 30 of base each minute except every tenth)."""
        base = self.timecode_base
        sign = "-" if frame < 0 else ""
        frame = abs(frame)
        sep = ":"
        if drop and self.supports_drop_frame:
            sep = ";"
            d = 2 * (base // 30)
            per_min = base * 60 - d
            per_10 = per_min * 10 + d
            tens, rem = divmod(frame, per_10)
            frame += d * 9 * tens + (d * ((rem - d) // per_min) if rem > d else 0)
        ff = frame % base
        total = frame // base
        return f"{sign}{total // 3600:02d}:{total // 60 % 60:02d}:{total % 60:02d}{sep}{ff:02d}"
