"""ffprobe's stream and format report, read into the skill's own types."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from filmcraft.errors import InputError, ToolError


def tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise ToolError(f"{name} is not installed (brew install ffmpeg)")
    return found


@dataclass
class VideoStream:
    codec: str
    profile: str | None
    width: int
    height: int
    fps: Fraction | None
    pix_fmt: str | None
    transfer: str | None
    primaries: str | None
    rotation: int = 0

    @property
    def display_size(self) -> tuple[int, int]:
        """Width and height as shown, after the rotation a phone records in metadata."""
        return (self.height, self.width) if self.rotation % 180 else (self.width, self.height)


@dataclass
class AudioStream:
    codec: str
    profile: str | None
    sample_rate: int | None
    channels: int | None


@dataclass
class Media:
    path: Path
    format_names: list[str]
    duration: float | None
    video: list[VideoStream] = field(default_factory=list)
    audio: list[AudioStream] = field(default_factory=list)


def _fraction(text: str | None) -> Fraction | None:
    try:
        f = Fraction(text) if text else None
    except (ValueError, ZeroDivisionError):
        return None
    return f if f else None


def probe(path: Path) -> Media:
    if not Path(path).exists():
        raise InputError(f"{path}: no such file")
    cmd = [tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise InputError(f"{path}: ffprobe cannot read it ({r.stderr.strip()[-300:]})")
    d = json.loads(r.stdout)
    fmt = d.get("format") or {}
    m = Media(path=Path(path), format_names=(fmt.get("format_name") or "").split(","), duration=float(fmt["duration"]) if fmt.get("duration") else None)
    for s in d.get("streams") or []:
        disposition = s.get("disposition") or {}
        if s.get("codec_type") == "video" and not disposition.get("attached_pic"):
            rot = 0
            for sd in s.get("side_data_list") or []:
                if "rotation" in sd:
                    rot = int(sd["rotation"])
            m.video.append(VideoStream(
                codec=s.get("codec_name") or "", profile=s.get("profile"), width=int(s.get("width") or 0), height=int(s.get("height") or 0),
                fps=_fraction(s.get("avg_frame_rate")) or _fraction(s.get("r_frame_rate")), pix_fmt=s.get("pix_fmt"),
                transfer=s.get("color_transfer"), primaries=s.get("color_primaries"), rotation=rot,
            ))
        elif s.get("codec_type") == "audio":
            m.audio.append(AudioStream(codec=s.get("codec_name") or "", profile=s.get("profile"),
                                       sample_rate=int(s["sample_rate"]) if s.get("sample_rate") else None, channels=s.get("channels")))
    return m
