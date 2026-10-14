"""SubRip, the file the model writes translated cues in and FilmCraft's captions.import reads."""

from __future__ import annotations

import re
from pathlib import Path

from filmcraft.errors import InputError

from .layout import Cue

_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{1,3})")


def _sec(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def read(path: Path) -> list[Cue]:
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise InputError(f"{path}: cannot read as UTF-8 SubRip ({e})")
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "").strip()):
        lines = block.split("\n")
        for k, line in enumerate(lines):
            m = _TIME.search(line)
            if m:
                g = m.groups()
                body = [l for l in lines[k + 1:] if l.strip()]
                if body:
                    cues.append(Cue(_sec(*g[:4]), _sec(*g[4:]), body))
                break
    if not cues:
        raise InputError(f"{path}: no SubRip cues found")
    return cues


def _stamp(t: float) -> str:
    ms = round(t * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write(cues: list[Cue], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{n}\n{_stamp(c.start)} --> {_stamp(c.end)}\n" + "\n".join(c.lines) + "\n\n" for n, c in enumerate(cues, 1)), encoding="utf-8")
