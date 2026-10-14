"""How wide a caption line burns in. FilmCraft draws captions in the track's family at SemiBold (the nearest weight when there is none), at size × frame height / 1080 pixels, and wraps a line wider than 0.9 × frame width at its spaces; measuring the same face with Pillow says whether a line stays one line."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import ImageFont

_DIRS = [Path.home() / "Library/Fonts", Path("/Library/Fonts"), Path("/System/Library/Fonts"), Path("/System/Library/Fonts/Supplemental")]
_WEIGHTS = {"thin": 100, "hairline": 100, "extralight": 200, "ultralight": 200, "light": 300, "regular": 400, "normal": 400, "book": 400,
            "medium": 500, "semibold": 600, "demibold": 600, "bold": 700, "extrabold": 800, "ultrabold": 800, "heavy": 900, "black": 900}
SAFETY = 0.97  # FilmCraft and Pillow shape the same face; keep a little room for kerning and rounding


def _weight(style: str) -> int:
    s = style.lower().replace(" ", "").replace("-", "")
    return next((v for k, v in sorted(_WEIGHTS.items(), key=lambda kv: -len(kv[0])) if k in s), 400)


def _faces(path: Path):
    for index in range(64):
        try:
            f = ImageFont.truetype(str(path), 20, index=index)
        except OSError:
            return
        yield index, f.getname()
        if path.suffix.lower() not in (".ttc", ".otc"):
            return


def find_face(family: str) -> tuple[Path, int, str] | None:
    """The installed face of `family` FilmCraft would pick for captions: SemiBold, else the upright face nearest weight 600."""
    want = family.lower().replace(" ", "")
    files = [p for d in _DIRS if d.is_dir() for p in d.iterdir() if p.suffix.lower() in (".ttf", ".otf", ".ttc", ".otc")]
    likely = [p for p in files if want[:6] in p.name.lower().replace(" ", "").replace("-", "")]
    for group in (likely, [p for p in files if p not in likely]):
        found = [(p, i, style) for p in group for i, (fam, style) in _faces(p) if (fam or "").lower().replace(" ", "") == want]
        if found:
            upright = [x for x in found if "italic" not in x[2].lower() and "oblique" not in x[2].lower()] or found
            return min(upright, key=lambda x: abs(_weight(x[2]) - 600))
    return None


@dataclass
class Measure:
    source: str          # "font" or "estimate"
    face: str | None
    px: float
    max_px: float
    _font: object = None

    def width(self, line: str) -> float:
        if self._font is not None:
            return self._font.getlength(line)
        # no face found: Hangul and CJK about 1 em, Latin and digits about 0.6 em, a space 0.3 em
        return sum(self.px * (0.3 if c == " " else 0.6 if ord(c) < 0x2000 else 1.0) for c in line)

    def fits(self, line: str) -> bool:
        return self.width(line) <= self.max_px

    def units_per_line(self) -> float:
        """How many units of Hangul fit a line at this size, for reporting."""
        return round(self.max_px / (self.width("가") or 1), 1)


def measure_for(family: str, size: float, frame_w: int, frame_h: int) -> Measure:
    px = max(size * frame_h / 1080, 4.0)
    max_px = frame_w * 0.9 * SAFETY
    found = find_face(family)
    if found is None:
        return Measure("estimate", None, px, max_px * 0.95)
    path, index, style = found
    return Measure("font", f"{path}#{index} ({style})", px, max_px, ImageFont.truetype(str(path), round(px), index=index))

