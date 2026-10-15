"""Rendered graphics into the intermediate FilmCraft composites: straight-alpha ProRes 4444. Captures are sRGB; they are converted with the BT.709 matrix to limited range, and all four colour tags are written (`-color_primaries` and friends as output options alone leave primaries and transfer `unknown`, and FilmCraft reads an untagged SD-sized file as BT.601). FilmCraft decodes the BT.709 transfer with the sRGB curve, so its round trip returns the page's values."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from video.errors import ToolError
from video.timecode import Rate

from .probe import tool

VIDEO_FILTER = "scale=out_color_matrix=bt709:out_range=tv,format=yuva444p10le,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv"


class AlphaWriter:
    """Pipe PNG frames in with `write`; on leaving the block, the movie is finished at `out` with `audio` (raw interleaved float32 at 48 kHz, `channels` to a frame), if given, muxed from its first frame as 24-bit PCM. Raises ToolError (stage `encode`) if ffmpeg fails."""

    def __init__(self, out: Path, rate: Rate, audio: Path | None = None, channels: int = 2):
        self.out, self.rate, self.audio, self.channels = Path(out), rate, audio, channels
        self._proc = None
        self._log = None

    def __enter__(self) -> "AlphaWriter":
        rate = f"{self.rate.num}/{self.rate.den}"
        cmd = [tool("ffmpeg"), "-v", "error", "-y", "-f", "image2pipe", "-c:v", "png", "-framerate", rate, "-i", "-"]
        if self.audio is not None:
            cmd += ["-f", "f32le", "-ar", "48000", "-ac", str(self.channels), "-i", str(self.audio), "-map", "0:v", "-map", "1:a", "-c:a", "pcm_s24le"]
        cmd += ["-vf", VIDEO_FILTER, "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-r", rate, str(self.out)]
        self._cmd = cmd
        self._log = tempfile.TemporaryFile()
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self._log)
        return self

    def _stderr(self) -> str:
        self._log.seek(0)
        return self._log.read().decode("utf-8", "replace")

    def write(self, png: bytes) -> None:
        try:
            self._proc.stdin.write(png)
        except BrokenPipeError:
            self._proc.wait()
            raise ToolError("encode: ffmpeg stopped reading frames", self._stderr(), self._cmd)

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is not None:
                self._proc.kill()
                self._proc.wait()
                return
            try:
                self._proc.stdin.close()
            except BrokenPipeError:
                pass
            if self._proc.wait() != 0:
                raise ToolError(f"encode: ffmpeg exited {self._proc.returncode}", self._stderr(), self._cmd)
        finally:
            self._log.close()
