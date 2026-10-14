"""Calling the installed filmcraft-cli: where it is, how a project or the running app is addressed, and how its failures look."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from filmcraft.errors import ToolError


def binary() -> str:
    found = shutil.which("filmcraft-cli")
    if found:
        return found
    local = Path.home() / ".local/bin/filmcraft-cli"
    if local.exists():
        return str(local)
    raise ToolError("filmcraft-cli is not installed; SKILL.md 'Before the first command' installs the version matching the app")


@dataclass(frozen=True)
class Source:
    """A project file opened headless, or the running app over its control port. Exactly one is set."""

    project: Path | None = None
    bridge: str | None = None

    def args(self) -> list[str]:
        return ["--project", str(self.project)] if self.project is not None else ["--bridge", str(self.bridge)]


def call(args: list[str], stdin: str | None = None, timeout: float = 900) -> subprocess.CompletedProcess:
    cmd = [binary(), "--compact", *args]
    try:
        return subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout, env=dict(os.environ))
    except subprocess.TimeoutExpired as e:
        raise ToolError(f"filmcraft-cli did not finish in {timeout:.0f} s", str(e.stderr or ""), cmd) from e


def run(source: Source, commands: list[tuple[str, dict]], save: bool = False) -> list:
    """Run commands as one session (`run -`) and return each one's result; the first failing command raises with its error."""
    stdin = "".join(json.dumps({"id": c, "params": p}, ensure_ascii=False) + "\n" for c, p in commands)
    args = [*source.args(), *(["--save"] if save else []), "run", "-"]
    r = call(args, stdin)
    results, failure = [], None
    for line in r.stdout.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("ok"):
            results.append(row.get("result"))
        elif failure is None:
            failure = row
    if failure is not None or r.returncode != 0 or len(results) != len(commands):
        where = source.project if source.project is not None else f"the app at {source.bridge}"
        last = next((l for l in reversed(r.stderr.splitlines()) if l.strip()), "")
        msg = f"{failure['id']}: {failure.get('error')}" if failure else (last or f"filmcraft-cli exited {r.returncode} on {where}")
        raise ToolError(msg, r.stderr, [binary(), *args])
    return results


def render(project: Path, seconds: float, out: Path, scale: float) -> Path:
    """One Program frame of the project's active sequence, drawn by FilmCraft (captions and graphics included). Headless only: the CLI refuses `render` with --bridge."""
    args = ["--project", str(project), "render", "--seconds", f"{seconds:.6f}", "--out", str(out), "--scale", f"{scale:.4f}"]
    r = call(args, timeout=600)
    if r.returncode != 0 or not Path(out).exists():
        last = next((l for l in reversed(r.stderr.splitlines()) if l.strip()), f"exit {r.returncode}")
        raise ToolError(f"render at {seconds:.3f} s failed: {last}", r.stderr, [binary(), *args])
    return out
