"""What both suites need to drive the installed filmcraft-cli and the skill's real entry point: where the binaries are, a runner for each, and media made with ffmpeg so expectations come from the generator's own parameters."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO / ".claude/skills/video"
CLI = SKILL_DIR / "scripts/cli.py"
TICKS = 254_016_000_000

FILMCRAFT = shutil.which("filmcraft-cli") or (str(Path.home() / ".local/bin/filmcraft-cli") if (Path.home() / ".local/bin/filmcraft-cli").exists() else None)
FFMPEG = shutil.which("ffmpeg")

needs_filmcraft = pytest.mark.skipif(FILMCRAFT is None, reason="filmcraft-cli is not installed (see SKILL.md 'Before the first command')")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not installed")


def fc(*args: str, project: Path | None = None, save: bool = False, stdin: str | None = None, cwd: Path | None = None, check: bool = True):
    """Run filmcraft-cli with a private data dir; returns the CompletedProcess. With check, a non-zero exit fails the test with its stderr."""
    cmd = [FILMCRAFT, "--compact"]
    if project is not None:
        cmd += ["--project", str(project)]
    if save:
        cmd.append("--save")
    cmd += list(args)
    env = dict(os.environ, FILMCRAFT_DATA_DIR=str((cwd or Path.cwd()) / ".fcdata"))
    r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, cwd=cwd, env=env, timeout=600)
    if check and r.returncode != 0:
        raise AssertionError(f"{' '.join(cmd)} exited {r.returncode}\nstdout: {r.stdout[-2000:]}\nstderr: {r.stderr[-2000:]}")
    return r


def fc_json(*args: str, **kw):
    return json.loads(fc(*args, **kw).stdout)


def fc_run(lines: list[dict], project: Path, save: bool = True, cwd: Path | None = None, check: bool = True) -> list[dict]:
    """Run commands as one `run -` session; returns each line's result object."""
    r = fc("run", "-", project=project, save=save, stdin="\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\n", cwd=cwd, check=check)
    return [json.loads(l) for l in r.stdout.splitlines() if l.strip()]


def skill(*args: str, cwd: Path | None = None, via_uv: bool = False):
    """Run the skill's cli.py the way the model does (via_uv) or with this interpreter (same file, faster). Returns (returncode, parsed stdout or None, stderr)."""
    cmd = (["uv", "run", "-q", str(CLI)] if via_uv else [sys.executable, str(CLI)]) + list(args)
    env = dict(os.environ)
    if cwd is not None:
        env["FILMCRAFT_DATA_DIR"] = str(Path(cwd) / ".fcdata")
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, env=env, timeout=1200)
    try:
        out = json.loads(r.stdout) if r.stdout.strip() else None
    except json.JSONDecodeError:
        out = None
    return r.returncode, out, r.stdout, r.stderr


def ffmpeg(*args: str):
    subprocess.run([FFMPEG, "-v", "error", "-y", *args], check=True, capture_output=True, timeout=600)


def make_av(path: Path, seconds: float, rate: str = "30000/1001", size: str = "1920x1080", tone: int = 440, src: str = "testsrc2", audio: bool = True) -> Path:
    """A test-pattern movie with a sine tone; `rate` is an ffmpeg rational."""
    args = ["-f", "lavfi", "-i", f"{src}=size={size}:rate={rate}:duration={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency={tone}:sample_rate=48000:duration={seconds}", "-c:a", "aac", "-shortest"]
    ffmpeg(*args, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path))
    return path
