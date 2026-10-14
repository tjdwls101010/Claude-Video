"""One render, from arguments to a verified file in place: frame size and rate from the sequence, the page's sound first, frames piped to the encoder, a check of what was written, and only then the swap over any earlier file (a project may be playing it)."""

from __future__ import annotations

import io
import math
import os
import time
from pathlib import Path

from PIL import Image

from video import chrome, ffmpeg
from video.errors import InputError, ToolError
from video.filmcraft import Source, read_sequence
from video.timecode import Rate

from . import place, timing

SAMPLE_RATE = 48_000
KINDS = {".mov": "video", ".png": "still"}


def render(page: Path, out: Path, *, source: Source | None = None, size: tuple[int, int] | None = None, rate: Rate | None = None,
           sequence: int | None = None, duration: float | None = None, frame_at: float = 0.0, timeouts: chrome.Timeouts = chrome.Timeouts()) -> dict:
    started = time.monotonic()
    kind = KINDS.get(out.suffix.lower())
    if kind is None:
        raise InputError(f"--out must end in .mov (a transparent movie) or .png (one transparent still), not {out.suffix or 'no extension'!r}")
    if not page.is_file():
        raise InputError(f"{page}: no such page")
    if out == page:
        raise InputError("--out is the page itself")
    if source is not None:
        seq = read_sequence(source, sequence)
        size, rate = (seq.width, seq.height), seq.rate
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise InputError(f"--out cannot go in {out.parent}: {e.strerror or e}")
    tmp = out.with_name(f".{out.stem}.rendering-{os.getpid()}{out.suffix}")
    raw = out.with_name(f".{out.stem}.rendering-{os.getpid()}.f32")
    try:
        with chrome.open_page(page, *size, timeouts=timeouts) as pg:
            if kind == "video":
                report = _movie(pg, tmp, raw, rate, duration, size)
            else:
                report = _still(pg, tmp, frame_at)
            report["fonts"] = [{"family": f.family, "drawn_by": [{"face": n, "glyphs": g} for n, g in f.drawn_by], "fallback": f.fallback, **({"text": f.text} if f.fallback else {})}
                               for f in pg.fonts(report.pop("_font_times"))]
            report["blocked"] = list(pg.blocked)
        after = report.pop("_shape")
        change = place.replaced(place.shape(out, kind), after)
        os.replace(tmp, out)
    except OSError as e:
        raise ToolError(f"write: {e}")
    finally:
        tmp.unlink(missing_ok=True)
        raw.unlink(missing_ok=True)
    head = {"out": str(out), "kind": kind, "size": f"{size[0]}x{size[1]}"}
    if kind == "video":
        head["fps"] = f"{rate.num}/{rate.den}" if rate.den != 1 else str(rate.num)
    return {**head, **report, "replaced": change, "took_s": round(time.monotonic() - started, 2),
            "next": place.next_steps(out, kind, bool(report.get("audio")), source, sequence, change)}


def _duration(given: float | None, declared) -> float:
    if given is not None:
        return given
    if declared is None:
        raise InputError("a .mov needs a length: pass --duration S, or set window.duration (seconds) in the page")
    if isinstance(declared, bool) or not isinstance(declared, (int, float)) or not math.isfinite(declared) or declared <= 0:
        raise InputError(f"the page's window.duration must be a positive number of seconds, got {declared!r}")
    return float(declared)


def _coverage(png: bytes, t: float) -> dict:
    """Share of the frame with any paint (alpha > 0) and with near-solid paint (alpha >= 250), which is what hides the picture under it."""
    with Image.open(io.BytesIO(png)) as img:
        hist = img.convert("RGBA").getchannel("A").histogram()
    total = sum(hist)
    return {"t": round(t, 3), "painted": round(1 - hist[0] / total, 4), "opaque": round(sum(hist[250:]) / total, 4)}


def _movie(pg, tmp: Path, raw: Path, rate: Rate, duration: float | None, size: tuple[int, int]) -> dict:
    seconds = _duration(duration, pg.declared_duration)
    n = timing.frame_count(seconds, rate)
    times = timing.frame_times(n, rate)
    length = timing.length(n, rate)
    samples = timing.sample_count(n, rate, SAMPLE_RATE)
    pcm = pg.audio(SAMPLE_RATE, float(length), samples)
    if pcm is not None:
        raw.write_bytes(pcm.data)
    keep = {0, n // 2, n - 1}
    kept: dict[int, tuple[float, bytes]] = {}
    count = [0]

    def on_frame(t: float, png: bytes) -> None:
        enc.write(png)
        if count[0] in keep:
            kept[count[0]] = (t, png)
        count[0] += 1

    with ffmpeg.AlphaWriter(tmp, rate, raw if pcm else None, pcm.channels if pcm else 2) as enc:
        pg.frames(times, on_frame)
    _verify_movie(tmp, n, rate, size, (samples, pcm.channels) if pcm else None)
    audio = _levels(pcm, tmp)
    font_times = sorted({0.0, *(float(s) for s in range(1, math.ceil(length))), times[-1]})
    return {"frames": n, "seconds": round(float(length), 6), "coverage": [_coverage(png, t) for _, (t, png) in sorted(kept.items())],
            "audio": audio, "_font_times": font_times, "_shape": place.shape(tmp, "video")}


def _still(pg, tmp: Path, frame_at: float) -> dict:
    shots: list[bytes] = []
    pg.frames([frame_at], lambda t, png: shots.append(png))
    tmp.write_bytes(shots[0])
    return {"frames": 1, "coverage": [_coverage(shots[0], frame_at)], "audio": None, "_font_times": [frame_at], "_shape": place.shape(tmp, "still")}


def _levels(pcm: chrome.Pcm | None, movie: Path) -> dict | None:
    """Peak (before clipping, so above 0 dBFS means the page's sound clipped) and integrated loudness of the sound as delivered; null levels for silence."""
    if pcm is None:
        return None
    if pcm.peak == 0:
        return {"peak_dbfs": None, "lufs": None}
    lufs = ffmpeg.loudness(movie).integrated
    return {"peak_dbfs": round(20 * math.log10(pcm.peak), 2), "lufs": round(lufs, 1) if lufs is not None else None}


def _verify_movie(path: Path, frames: int, rate: Rate, size: tuple[int, int], sound: tuple[int, int] | None) -> None:
    """Measure what was written rather than trust the encoder: a wrong tag or a dropped frame would otherwise only show in FilmCraft, if at all. `sound` is (samples, channels) when the movie must carry the page's sound."""
    try:
        m = ffmpeg.probe(path)
    except InputError as e:
        raise ToolError(f"verify: the encoded movie cannot be read: {e}")
    problems = []
    v = m.video[0] if m.video else None
    if v is None:
        problems.append("no video stream")
    else:
        if (v.codec, v.profile) != ("prores", "4444"):
            problems.append(f"codec {v.codec} {v.profile}, expected prores 4444")
        if not v.has_alpha:
            problems.append(f"pixel format {v.pix_fmt} has no alpha")
        tags = (v.primaries, v.transfer, v.color_space, v.color_range)
        if tags != ("bt709", "bt709", "bt709", "tv"):
            problems.append(f"colour tags {tags}, expected bt709 x3 and tv")
        if v.frames != frames:
            problems.append(f"{v.frames} frames, expected {frames}")
        if v.fps != rate.fps:
            problems.append(f"rate {v.fps}, expected {rate.fps}")
        if (v.width, v.height) != tuple(size):
            problems.append(f"size {v.width}x{v.height}, expected {size[0]}x{size[1]}")
    if sound is not None:
        samples, channels = sound
        a = m.audio[0] if m.audio else None
        if a is None or (a.codec, a.sample_rate, a.channels, a.samples) != ("pcm_s24le", SAMPLE_RATE, channels, samples):
            problems.append(f"sound {a and (a.codec, a.sample_rate, a.channels, a.samples)}, expected pcm_s24le at {SAMPLE_RATE} Hz, {channels} channels, {samples} samples")
    elif m.audio:
        problems.append("a sound stream nobody asked for")
    if problems:
        raise ToolError(f"verify: the encoded movie is not what was asked for: {'; '.join(problems)}")
