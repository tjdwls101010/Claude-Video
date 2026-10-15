"""The level of a media file's sound over time: RMS in dBFS per short window, from the first audio stream mixed to mono."""

from __future__ import annotations

import math
import subprocess
from array import array
from pathlib import Path

from video.errors import InputError, ToolError

from .probe import tool

RATE = 16000
FLOOR_DB = -100.0


def envelope(path: Path, hop: float = 0.01) -> list[float]:
    """One value per `hop` seconds from the start; digital silence reads as -100 dBFS."""
    cmd = [tool("ffmpeg"), "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"]
    r = subprocess.run(cmd, capture_output=True, timeout=3600)
    if r.returncode != 0:
        msg = r.stderr.decode(errors="replace")
        if "matches no streams" in msg or "Stream map" in msg:
            raise InputError(f"{path}: no audio stream")
        raise ToolError(f"ffmpeg could not decode the audio of {path}", msg, cmd)
    pcm = array("f")
    pcm.frombytes(r.stdout[: len(r.stdout) // 4 * 4])
    n = max(1, round(hop * RATE))
    out = []
    for i in range(0, len(pcm), n):
        chunk = pcm[i:i + n]
        ms = sum(x * x for x in chunk) / len(chunk)
        out.append(10 * math.log10(ms) if ms > 1e-10 else FLOOR_DB)
    return out
