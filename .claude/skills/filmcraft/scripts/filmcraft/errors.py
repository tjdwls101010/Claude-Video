"""Errors every unit raises and `cli.py` turns into exit codes."""

from __future__ import annotations


class ToolError(Exception):
    """An external tool (filmcraft-cli, ffmpeg, mlx-whisper) failed or is missing; `cli.py` exits 1 with `message` and the tool's stderr tail."""

    def __init__(self, message: str, stderr_tail: str = "", command: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.stderr_tail = stderr_tail[-1500:]
        self.command = command

    def as_json(self) -> dict:
        out: dict = {"error": self.message}
        if self.stderr_tail:
            out["stderr_tail"] = self.stderr_tail
        if self.command:
            out["command"] = " ".join(self.command)
        return out


class InputError(Exception):
    """The arguments name something that does not work (a file that is not media, a sequence that does not exist); exit 2 like a parser error."""
