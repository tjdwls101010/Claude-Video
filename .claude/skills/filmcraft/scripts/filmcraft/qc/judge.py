"""Turning measurements into verdicts for one delivery target. Pure: no files, no tools, so the bands can be tested at their edges."""

from __future__ import annotations

from dataclasses import dataclass

from .criteria import LIMITS, TARGETS


@dataclass
class Measurements:
    container: str | None
    video_codec: str | None
    video_profile: str | None
    width: int | None
    height: int | None
    fps: float | None
    duration: float | None
    audio_codec: str | None
    audio_profile: str | None
    sample_rate: int | None
    channels: int | None
    integrated: float | None
    true_peak: float | None
    moov_first: bool | None
    has_elst: bool | None
    loudness_reason: str | None = None
    has_audio: bool = True
    has_video: bool = True


def _row(name, value, expected, tolerance, level, ok, reason=None):
    return {"name": name, "value": value, "expected": expected, "tolerance": tolerance, "level": level, "pass": ok, "reason": reason}


def judge(m: Measurements, target: str, expect_size: tuple[int, int] | None = None, expect_fps: float | None = None, expect_duration: float | None = None, lufs: float | None = None) -> dict:
    """Each check is `fail` (required), `warn` (advice) or `info` (recorded only). A required check that fails puts its name in `failed`; an advisory one that fails, a loudness inside the warn band, or a value that could not be measured puts it in `warnings`. `pass` is false when anything failed."""
    t = TARGETS[target]
    lim = LIMITS.get(target, {})
    rows: list[dict] = []
    warn_names: set[str] = set()

    def add(name, value, expected, tolerance, ok, reason=None, level=None):
        lv = level or t.get(name, "info")
        rows.append(_row(name, value, expected, tolerance, lv, ok, reason))
        if (ok is None and lv != "info") or (ok is False and lv == "warn"):
            warn_names.add(name)

    add("container", m.container, "mp4", None, None if m.container is None else m.container == "mp4")
    if m.has_video:
        add("video_codec", m.video_codec, "h264", None, None if m.video_codec is None else m.video_codec == "h264")
        add("video_profile", m.video_profile, "High", None, None if m.video_profile is None else m.video_profile == "High")
        size = f"{m.width}x{m.height}" if m.width else None
        want = expect_size or lim.get("size")
        if want:
            add("size", size, f"{want[0]}x{want[1]}", None, size == f"{want[0]}x{want[1]}", level="fail")
        else:
            add("size", size, None, None, True, level="info")
        if expect_fps is not None:
            ok = None if m.fps is None else abs(m.fps - expect_fps) < 0.01
            add("fps", round(m.fps, 3) if m.fps else None, expect_fps, 0.01, ok, level="fail")
        elif lim.get("min_fps"):
            add("fps", round(m.fps, 3) if m.fps else None, f">= {lim['min_fps']}", None, None if m.fps is None else m.fps >= lim["min_fps"] - 0.05, level="warn")
        else:
            add("fps", round(m.fps, 3) if m.fps else None, None, None, True, level="info")
    else:
        add("video", None, "a video stream", None, False, "no video stream", level="fail")
    frame = 1 / m.fps if m.fps else 1 / 24
    wants, oks = [], []
    if expect_duration is not None:
        wants.append(f"{expect_duration} ±1 frame")
        oks.append(None if m.duration is None else abs(m.duration - expect_duration) <= frame + 1e-6)
    if lim.get("max_duration"):
        wants.append(f"<= {lim['max_duration']}")
        oks.append(None if m.duration is None else m.duration <= lim["max_duration"] + frame)
    if wants:
        ok = None if None in oks else all(oks)
        add("duration", m.duration, ", ".join(wants), round(frame, 4), ok, level="fail")
        advised = lim.get("advised_duration")
        if ok and advised and m.duration is not None and m.duration > advised[0] + frame:
            warn_names.add("duration")
            rows[-1]["reason"] = f"over {advised[0]} s: {advised[1]}"
    else:
        add("duration", m.duration, None, None, True, level="info")

    add("audio", "present" if m.has_audio else None, "present", None, m.has_audio, None if m.has_audio else "no audio stream")
    if m.has_audio:
        add("audio_codec", m.audio_codec, "aac", None, None if m.audio_codec is None else m.audio_codec == "aac" and (m.audio_profile in (None, "LC")))
        add("sample_rate", m.sample_rate, 48000, None, None if m.sample_rate is None else m.sample_rate == 48000)
        add("channels", m.channels, 2, None, None if m.channels is None else m.channels == 2)

    band = dict(lim["loudness"], **({"target": float(lufs)} if lufs is not None else {}))
    reason = None if m.has_audio else "no audio stream"
    reason = reason or m.loudness_reason
    if m.integrated is None:
        add("integrated_loudness", None, band["target"], band["pass"], None, reason, level="fail")
    else:
        d = abs(m.integrated - band["target"])
        ok = d <= band["pass"] + 1e-9 or d <= band.get("warn", band["pass"]) + 1e-9
        add("integrated_loudness", round(m.integrated, 1), band["target"], band["pass"], ok, level="fail")
        if ok and d > band["pass"] + 1e-9:
            warn_names.add("integrated_loudness")
            rows[-1]["reason"] = f"within ±{band['warn']} LU but outside ±{band['pass']}"
    if m.true_peak is None:
        add("true_peak", None, f"<= {lim['true_peak']}", None, None, reason)
    else:
        add("true_peak", round(m.true_peak, 1), f"<= {lim['true_peak']}", None, m.true_peak <= lim["true_peak"] + 1e-9)

    pos = None if m.moov_first is None else ("start" if m.moov_first else "end")
    add("moov_position", pos, "start", None, None if pos is None else m.moov_first,
        None if pos != "end" else "remux losslessly: ffmpeg -i IN -c copy -movflags +faststart OUT")
    add("edit_list", m.has_elst, None, None, True, level="info")

    failed = [r["name"] for r in rows if r["pass"] is False and r["level"] == "fail"]
    return {"target": target, "pass": not failed, "failed": failed, "warnings": [r["name"] for r in rows if r["name"] in warn_names], "checks": rows}
