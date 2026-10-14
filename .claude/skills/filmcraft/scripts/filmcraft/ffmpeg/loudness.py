"""BS.1770 loudness from ffmpeg's ebur128 filter: integrated loudness, loudness range and true peak of the first audio stream."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from filmcraft.errors import ToolError

from .probe import tool

# BS.1770's absolute gate: ebur128 reports exactly this when no block passes it, i.e. the programme is silent.
ABSOLUTE_GATE = -70.0


@dataclass
class Loudness:
    integrated: float | None
    true_peak: float | None
    lra: float | None
    reason: str | None = None


def _last(pattern: str, text: str) -> float | None:
    found = re.findall(pattern, text)
    if not found:
        return None
    v = found[-1]
    return None if "inf" in v else float(v)


def loudness(path: Path) -> Loudness:
    cmd = [tool("ffmpeg"), "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        raise ToolError(f"ffmpeg could not measure loudness of {path}", r.stderr, cmd)
    summary = r.stderr[r.stderr.rfind("Integrated loudness:"):]
    i = _last(r"I:\s+(-?[\d.]+|-?inf) LUFS", summary)
    lra = _last(r"LRA:\s+(-?[\d.]+) LU", summary)
    tp = _last(r"Peak:\s+(-?[\d.]+|-?inf) dBFS", summary)
    if i is None or i <= ABSOLUTE_GATE:
        return Loudness(None, None, None, "silent: no audio passes the -70 LUFS absolute gate")
    return Loudness(i, tp, lra)
