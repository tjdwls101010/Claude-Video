"""mlx-whisper, run in its own uvx environment so cli.py stays light, and its JSON read into the skill's own terms: segments with Whisper's own failure signals, and words with leading spaces stripped."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from filmcraft.errors import InputError, ToolError

__all__ = ["DEFAULT_MODEL", "RawWord", "Segment", "Recognition", "recognise", "read"]

DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"
# mlx wheels lag new Pythons; this one is known to install.
_PYTHON = "3.12"


@dataclass
class RawWord:
    text: str
    start: float
    end: float
    prob: float


@dataclass
class Segment:
    start: float
    end: float
    text: str
    no_speech_prob: float
    avg_logprob: float
    compression_ratio: float
    words: list[RawWord] = field(default_factory=list)


@dataclass
class Recognition:
    language: str
    segments: list[Segment]


def read(path: Path) -> Recognition:
    try:
        d = json.loads(Path(path).read_text())
        if not isinstance(d, dict) or not isinstance(d.get("segments"), list):
            raise ValueError("no `segments` list")
        segs = []
        for s in d["segments"]:
            words = [RawWord(str(w.get("word", "")).strip(), float(w["start"]), float(w["end"]), float(w.get("probability", 1.0))) for w in s.get("words") or []]
            if not all(math.isfinite(x) for w in words for x in (w.start, w.end, w.prob)):
                raise ValueError("a word time or probability is not a finite number")
            segs.append(Segment(float(s.get("start", 0)), float(s.get("end", 0)), str(s.get("text") or "").strip(), float(s.get("no_speech_prob", 0.0)),
                                float(s.get("avg_logprob", 0.0)), float(s.get("compression_ratio", 1.0)), [w for w in words if w.text]))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        raise InputError(f"{path}: not mlx-whisper JSON with word timestamps ({e})")
    return Recognition(language=str(d.get("language") or ""), segments=segs)


def recognise(media: Path, out_dir: Path, language: str | None, model: str) -> Path:
    """Run the model with word timestamps; returns the JSON it wrote. Progress goes to this process's stderr. The model downloads to ~/.cache/huggingface on first use (about 1.6 GB for the default)."""
    uvx = shutil.which("uvx")
    if not uvx:
        raise ToolError("uvx is not installed (it comes with uv: https://docs.astral.sh/uv/)")
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [uvx, "--python", _PYTHON, "--from", "mlx-whisper", "mlx_whisper", str(media), "--model", model, "--word-timestamps", "True",
           "--output-format", "json", "--output-dir", str(out_dir), "--condition-on-previous-text", "False", "--verbose", "False"]
    if language:
        cmd += ["--language", language]
    r = subprocess.run(cmd, stdout=sys.stderr, stderr=subprocess.PIPE, text=True, env=dict(os.environ))
    produced = out_dir / (Path(media).stem + ".json")
    if r.returncode != 0 or not produced.exists():
        raise ToolError(f"mlx-whisper failed on {media}", r.stderr, cmd)
    return produced
