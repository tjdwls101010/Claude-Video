"""One render, from arguments to a verified file in place: frame size and rate from the sequence, the page's sound first, frames piped to the encoder, a check of what was written, and only then the swap over any earlier file (a project may be playing it)."""

from __future__ import annotations

import io
import math
import os
import time
import wave
from array import array
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
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.stem}.rendering-{os.getpid()}{out.suffix}")
    wav = out.with_name(f".{out.stem}.rendering-{os.getpid()}.wav")
    try:
        with chrome.open_page(page, *size, timeouts=timeouts) as pg:
            if kind == "video":
                report = _movie(pg, tmp, wav, rate, duration)
            else:
                report = _still(pg, tmp, frame_at)
            report["fonts"] = [{"family": f.family, "drawn_by": [{"face": n, "glyphs": g} for n, g in f.drawn_by], "fallback": f.fallback, **({"text": f.text} if f.fallback else {})}
                               for f in pg.fonts(report.pop("_font_times"))]
            report["blocked"] = list(pg.blocked)
        after = report.pop("_shape")
        change = place.replaced(place.shape(out, kind), after)
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)
        wav.unlink(missing_ok=True)
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


def _movie(pg, tmp: Path, wav: Path, rate: Rate, duration: float | None) -> dict:
    seconds = _duration(duration, pg.declared_duration)
    n = timing.frame_count(seconds, rate)
    times = timing.frame_times(n, rate)
    length = timing.length(n, rate)
    samples = timing.sample_count(n, rate, SAMPLE_RATE)
    audio = _sound(pg.audio(SAMPLE_RATE, float(length)), samples, wav)
    keep = {0, n // 2, n - 1}
    kept: dict[int, tuple[float, bytes]] = {}
    count = [0]

    def on_frame(t: float, png: bytes) -> None:
        enc.write(png)
        if count[0] in keep:
            kept[count[0]] = (t, png)
        count[0] += 1

    with ffmpeg.AlphaWriter(tmp, rate, wav if audio else None) as enc:
        pg.frames(times, on_frame)
    _verify_movie(tmp, n, rate, samples if audio else None)
    font_times = sorted({0.0, *(float(s) for s in range(1, math.ceil(length))), times[-1]})
    return {"frames": n, "seconds": round(float(length), 6), "coverage": [_coverage(png, t) for _, (t, png) in sorted(kept.items())],
            "audio": audio, "_font_times": font_times, "_shape": place.shape(tmp, "video")}


def _still(pg, tmp: Path, frame_at: float) -> dict:
    shots: list[bytes] = []
    pg.frames([frame_at], lambda t, png: shots.append(png))
    tmp.write_bytes(shots[0])
    return {"frames": 1, "coverage": [_coverage(shots[0], frame_at)], "audio": None, "_font_times": [frame_at], "_shape": place.shape(tmp, "still")}


def _sound(pcm: chrome.Pcm | None, samples: int, wav: Path) -> dict | None:
    """Write the page's sound as a WAV exactly `samples` long (cut or padded with silence: the movie sets the length) and report its levels. Peak is measured before clipping, so above 0 dBFS means the page's sound clipped."""
    if pcm is None:
        return None
    chans = [list(c[:samples]) + [0.0] * (samples - len(c)) for c in pcm.channels] or [[0.0] * samples]
    peak = max((abs(v) for c in chans for v in c), default=0.0)
    top = 2**31 - 1
    frames = array("i", (round(max(-1.0, min(1.0, c[i])) * top) for i in range(samples) for c in chans))
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(len(chans))
        w.setsampwidth(4)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(frames.tobytes())
    if peak == 0:
        return {"peak_dbfs": None, "lufs": None}
    lufs = ffmpeg.loudness(wav).integrated
    return {"peak_dbfs": round(20 * math.log10(peak), 2), "lufs": round(lufs, 1) if lufs is not None else None}


def _verify_movie(path: Path, frames: int, rate: Rate, samples: int | None) -> None:
    """Measure what was written rather than trust the encoder: a wrong tag or a dropped frame would otherwise only show in FilmCraft, if at all."""
    m = ffmpeg.probe(path)
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
    if samples is not None:
        a = m.audio[0] if m.audio else None
        if a is None or a.sample_rate != SAMPLE_RATE or a.samples != samples:
            problems.append(f"sound {a and (a.codec, a.sample_rate, a.samples)}, expected {SAMPLE_RATE} Hz and {samples} samples")
    elif m.audio:
        problems.append("a sound stream nobody asked for")
    if problems:
        raise ToolError(f"verify: the encoded movie is not what was asked for: {'; '.join(problems)}")
