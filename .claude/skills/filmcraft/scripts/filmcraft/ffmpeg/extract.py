"""Still frames out of a media file."""

from __future__ import annotations

import subprocess
from pathlib import Path

from filmcraft.errors import ToolError

from .probe import tool


def extract_frame(path: Path, seconds: float, out: Path, width: int) -> Path:
    """The frame whose presentation time is the first at or after `seconds`, scaled to `width` (rotation metadata applied). HDR sources are not tone-mapped: this ffmpeg build may lack zscale, so colours of PQ/HLG frames look flat."""
    cmd = [tool("ffmpeg"), "-v", "error", "-y", "-ss", f"{max(seconds, 0):.6f}", "-i", str(path), "-frames:v", "1", "-vf", f"scale={width}:-2", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not Path(out).exists():
        raise ToolError(f"ffmpeg could not extract a frame at {seconds:.3f} s from {path}", r.stderr, cmd)
    return out
