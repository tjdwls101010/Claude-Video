"""Technical delivery QC: measure a rendered file and judge it against one target's criteria. Editorial quality (whether cuts land, whether meaning survived) is not judged here."""

from __future__ import annotations

from pathlib import Path

from video import ffmpeg, mp4

from .criteria import HELP_TABLE, LIMITS, TARGETS
from .judge import Measurements, judge

__all__ = ["check", "judge", "Measurements", "TARGETS", "LIMITS", "HELP_TABLE"]

# ffprobe reports the MP4 family as one demuxer name list; the brand in `ftyp` tells QuickTime from MP4.
_MP4_FAMILY = {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}


def measure(path: Path) -> Measurements:
    media = ffmpeg.probe(path)
    container = media.format_names[0] if media.format_names else None
    moov_first = has_elst = None
    if _MP4_FAMILY & set(media.format_names):
        lay = mp4.layout(path)
        container = "mov" if lay.is_quicktime else "mp4"
        moov_first, has_elst = lay.moov_first, lay.has_elst
    v = media.video[0] if media.video else None
    a = media.audio[0] if media.audio else None
    loud = ffmpeg.loudness(path) if a else None
    w, h = v.display_size if v else (None, None)
    return Measurements(
        container=container, video_codec=v.codec if v else None, video_profile=v.profile if v else None, width=w, height=h,
        fps=float(v.fps) if v and v.fps else None, duration=media.duration,
        audio_codec=a.codec if a else None, audio_profile=a.profile if a else None, sample_rate=a.sample_rate if a else None, channels=a.channels if a else None,
        integrated=loud.integrated if loud else None, true_peak=loud.true_peak if loud else None, loudness_reason=loud.reason if loud else None,
        moov_first=moov_first, has_elst=has_elst, has_audio=a is not None, has_video=v is not None,
    )


def check(path: Path, target: str, expect_size: tuple[int, int] | None = None, expect_fps: float | None = None, expect_duration: float | None = None, lufs: float | None = None) -> dict:
    result = judge(measure(path), target, expect_size, expect_fps, expect_duration, lufs)
    return {"file": str(path), **result}
