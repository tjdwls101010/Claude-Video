"""Seeing an edit without playing it: frames of a project rendered by FilmCraft (captions and graphics included), or of a media file extracted by ffmpeg, laid out as one labelled contact sheet, optionally with vertical-platform safe zones."""

from __future__ import annotations

import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from video import ffmpeg
from video.errors import InputError
from video.filmcraft_cli import Source, read_sequence, render
from video.timecode import Rate

from .sheet import compose
from .zones import HELP_TABLE, SAFE_ZONES

__all__ = ["sheet", "SAFE_ZONES", "HELP_TABLE", "MAX_FRAMES"]

MAX_FRAMES = 100
_TC = re.compile(r"^\d+:\d{2}:\d{2}[:;]\d{2,3}$")


def _frame_of(value: str, rate: Rate, drop: bool) -> int:
    """`12.5` (seconds) or `HH:MM:SS:FF` / `HH:MM:SS;FF` at `rate` → frame index (the frame containing that instant)."""
    if _TC.match(value.strip()):
        return rate.frame_of_timecode(value, drop)
    try:
        return rate.frame_of_seconds(float(value))
    except ValueError:
        raise InputError(f"--at {value!r}: give seconds (12.5) or a timecode (00:00:12:15, or 00:00:12;15 drop-frame)")


def _clear_of_transitions(frame: int, track, rate: Rate) -> int:
    """A clip's first frame, or the first frame after a transition that covers it, so the tile shows the shot and not a mix."""
    for x in track.transitions:
        a, b = rate.frame_at(x.start), rate.frame_at(x.start + x.duration)
        if a <= frame < b:
            return b
    return frame


def _pick(rate: Rate, total_frames: int, at: list[str] | None, every: float | None, cuts: list[int] | None, drop: bool = False) -> list[int]:
    if at:
        frames = [_frame_of(a, rate, drop) for a in at]
    elif every:
        n = int((total_frames / float(rate.fps)) // every) + 1
        frames = [rate.frame_of_seconds(i * every) for i in range(n)]
        frames = [f for f in frames if f < total_frames]
    else:
        frames = list(cuts or [])
    if len(frames) > MAX_FRAMES:
        raise InputError(f"{len(frames)} frames asked for; the limit is {MAX_FRAMES}. Raise --every or narrow --at")
    if not frames:
        raise InputError("no frames to show (empty sequence, or times past the end)")
    return frames


def sheet(out: Path, *, project: Path | None = None, media: Path | None = None, at: list[str] | None = None, every: float | None = None,
          cuts: bool = False, overlay: str | None = None, cols: int = 4, width: int | None = None) -> dict:
    notes: list[str] = []
    if project is not None:
        seq = read_sequence(Source(project=project))
        rate, total, size, drop = seq.rate, seq.duration_frames, (seq.width, seq.height), seq.drop_frame
        cut_frames = sorted({_clear_of_transitions(c.start_frame, t, rate) for t in seq.video for c in t.clips if c.start_frame < total}) if cuts else None
    else:
        if cuts:
            raise InputError("--cuts reads clip boundaries from a project; with --media use --at or --every")
        m = ffmpeg.probe(media)
        if not m.video:
            raise InputError(f"{media}: no video stream")
        v = m.video[0]
        rate = Rate(v.fps.numerator, v.fps.denominator) if v.fps else Rate(30)
        total = int((m.duration or 0) * float(rate.fps))
        size, drop, cut_frames = v.display_size, False, None
        if v.transfer in ("smpte2084", "arib-std-b67"):
            notes.append("HDR source: ffmpeg frames are not tone-mapped, so colours look flat; judge colour from a --project render, where FilmCraft tone-maps to the sequence")
    frames = _pick(rate, total, at, every, cut_frames, drop)
    vertical = size[1] > size[0]
    platforms = [] if not overlay else (list(SAFE_ZONES) if overlay == "all" else [overlay])
    if platforms and not vertical:
        notes.append("overlay skipped: the frame is not vertical")
        platforms = []
    elif platforms and abs(size[0] / size[1] - 9 / 16) > 0.01:
        notes.append("safe zones are defined for 9:16; scaled to this frame anyway")
    w = width or (480 if not vertical else 320)
    with tempfile.TemporaryDirectory() as tmp:
        paths = [Path(tmp) / f"{i:04d}.png" for i in range(len(frames))]

        def grab(i: int) -> Path:
            f = frames[i]
            if project is not None:
                # the middle of the frame, so float seconds cannot round into its neighbour
                return render(project, (rate.tick_of(f) + rate.tick_of(f + 1)) / 2 / 254_016_000_000, paths[i], w / size[0])
            return ffmpeg.extract_frame(media, max(rate.seconds_of(f) - 1e-4, 0), paths[i], w)

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(grab, range(len(frames))))
        labels = [rate.timecode(f, drop) for f in frames]
        grid = compose(paths, labels, out, cols, platforms)
    return {"sheet": str(out), "frames": [{"t": round(rate.seconds_of(f), 3), "tc": lab} for f, lab in zip(frames, labels)],
            "size": f"{grid['tile_w']}x{grid['tile_h']}", "grid": grid, "notes": notes}
