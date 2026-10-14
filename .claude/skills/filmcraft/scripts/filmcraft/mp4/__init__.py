"""The ISO base media (MP4/MOV) box layout delivery checks care about: the `ftyp` brand that tells MP4 from QuickTime, whether `moov` comes before `mdat` (fast start), and whether any track carries an edit list (`elst`)."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Layout", "layout"]

# Containers inside `moov` that hold the boxes we look for.
_CONTAINERS = {b"moov", b"trak", b"edts", b"mdia", b"minf", b"stbl"}


@dataclass
class Layout:
    brand: str | None
    top_level: list[str] = field(default_factory=list)
    has_elst: bool = False

    @property
    def is_quicktime(self) -> bool:
        return self.brand == "qt  "

    @property
    def moov_first(self) -> bool | None:
        """True when `moov` precedes `mdat` (players can start before the whole file arrives); None if either is missing."""
        if "moov" not in self.top_level or "mdat" not in self.top_level:
            return None
        return self.top_level.index("moov") < self.top_level.index("mdat")


def _boxes(f, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        head = f.read(8)
        if len(head) < 8:
            return
        size, kind = struct.unpack(">I4s", head)
        header = 8
        if size == 1:
            ext = f.read(8)
            if len(ext) < 8:
                return
            size = struct.unpack(">Q", ext)[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            return
        yield kind, pos + header, pos + size
        pos += size


def _find_elst(f, start: int, end: int, depth: int = 0) -> bool:
    if depth > 8:
        return False
    for kind, body, stop in _boxes(f, start, end):
        if kind == b"elst":
            return True
        if kind in _CONTAINERS and _find_elst(f, body, stop, depth + 1):
            return True
    return False


def layout(path: Path) -> Layout:
    size = Path(path).stat().st_size
    out = Layout(brand=None)
    with open(path, "rb") as f:
        for kind, body, stop in _boxes(f, 0, size):
            name = kind.decode("latin-1")
            out.top_level.append(name)
            if kind == b"ftyp":
                f.seek(body)
                out.brand = f.read(4).decode("latin-1")
            elif kind == b"moov":
                out.has_elst = out.has_elst or _find_elst(f, body, stop)
    return out
