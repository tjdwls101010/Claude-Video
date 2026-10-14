"""Korean captions laid out to the subtitle rules and to the width FilmCraft will burn them at: from the active sequence's transcript (words already in sequence time), or from cues written elsewhere such as a translation. Writes SubRip for captions.import."""

from __future__ import annotations

import shlex
from fractions import Fraction
from pathlib import Path

from filmcraft.errors import InputError
from filmcraft.filmcraft_cli import Source, read_words
from filmcraft.timecode import Rate, seconds

from . import srt
from .fonts import measure_for
from .layout import Cue, Word, layout, relayout, violations
from .rules import HELP, Rules, units

__all__ = ["Word", "Cue", "Rules", "units", "layout", "relayout", "violations", "make", "HELP", "DEFAULT_FONT", "style_defaults"]

DEFAULT_FONT = "Apple SD Gothic Neo"


def style_defaults(width: int, height: int) -> dict:
    """Landscape: size 54 at the bottom, 8 % up. Vertical: size 40, raised to 40 % so two lines clear every platform's bottom UI and the Reels corner block (see frames --help)."""
    if height > width:
        return {"size": 40.0, "margin": 0.40}
    return {"size": 54.0, "margin": 0.08}


def make(out: Path, *, project: Path | None = None, bridge: str | None = None, cues_file: Path | None = None, fps: float | None = None, frame: tuple[int, int] | None = None,
         font: str | None = None, size: float | None = None, margin: float | None = None, anchor: str = "bottom", lines: int = 2, cps: float = 12.0,
         min_s: float = 5 / 6, max_s: float = 7.0) -> dict:
    rules = Rules(lines=lines, cps=cps, min_s=min_s, max_s=max_s)
    notes: list[str] = []
    if cues_file is None:
        source = Source(project=project, bridge=bridge)
        seq, seq_words = read_words(source)
        if not seq_words:
            raise InputError("the active sequence has no transcript words; apply one with transcribe first (transcript.set)")
        rate, (w, h) = seq.rate, (seq.width, seq.height)
        words = [Word(x.text, seconds(x.start), seconds(x.end), x.speaker, x.clip) for x in seq_words]
    else:
        rate = Rate.parse(str(fps or 30))
        w, h = frame or (1920, 1080)
        if fps is None:
            notes.append("no --fps: cue times aligned to 30 fps; FilmCraft snaps them to the sequence rate on import")
    d = style_defaults(w, h)
    style = {"font": font or DEFAULT_FONT, "size": float(size if size is not None else d["size"]), "margin": float(margin if margin is not None else d["margin"]), "anchor": anchor}
    m = measure_for(style["font"], style["size"], w, h)
    if m.source == "estimate":
        notes.append(f"no installed face of {style['font']!r} found; line widths estimated, so check a render (frames --project)")
    fr = Fraction(rate.num, rate.den)
    result = layout(words, rules, fr, m.fits) if cues_file is None else relayout(srt.read(cues_file), rules, fr, m.fits)
    srt.write(result, out)
    where = f"--project {shlex.quote(str(project))}" if project is not None else f"--bridge {bridge}" if bridge else "--project <P.fcproj>"
    style_args = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in style.items())
    return {
        "cues": len(result),
        "style": style,
        "max_line_units": min(rules.max_units, m.units_per_line()),
        "width": {"source": m.source, "face": m.face, "px": round(m.px, 1), "max_line_px": round(m.max_px)},
        "violations": violations(result, rules),
        "out": str(out),
        "notes": notes,
        "next": [f"filmcraft-cli {where} --save exec captions.import path={shlex.quote(str(out))}",
                 f"filmcraft-cli {where} --save exec captions.setStyle track=<track from the import result> {style_args}"],
    }
