"""`chrome`: contracts visible only within one page session, which the CLI (a fresh browser per call) cannot show: frames captured out of order are the same frames, and a stage that never settles fails under a short timeout naming its stage. Needs Playwright in the test environment: `uv run --with pytest --with pillow --with playwright pytest`."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="run pytest with --with playwright (the chrome unit drives Chrome in-process)")

from video import chrome  # noqa: E402
from video.errors import ToolError  # noqa: E402

pytestmark = pytest.mark.slow

HEAD = "<!doctype html><meta charset='utf-8'><style>html,body{margin:0;background:transparent}</style>"


def write(d: Path, body: str, name: str = "p.html") -> Path:
    p = d / name
    p.write_text(HEAD + body, encoding="utf-8")
    return p


def test_the_same_time_draws_the_same_frame_in_any_order(tmp_path):
    body = """<style>#c{position:absolute;left:0;width:40px;height:40px;background:#00f;animation:mv 2s linear}@keyframes mv{to{left:200px}}</style><div id=c></div>
<div id=s style="position:absolute;top:50px;width:40px;height:40px;background:#f00"></div>
<script>window.seek = t => { document.getElementById('s').style.left = (t * 100) + 'px' }</script>"""
    got = []
    with chrome.open_page(write(tmp_path, body), 320, 100) as pg:
        pg.frames([1.0, 0.5, 1.0], lambda t, png: got.append(png))
    assert got[0] == got[2] and got[0] != got[1]


def test_fonts_that_never_arrive_fail_as_fonts(tmp_path):
    """The @font-face source is a FIFO nobody writes to, so reading it never finishes. Text using it is added by the load handler: a font requested before the load event holds the load itself (failing as `load`)."""
    import os
    os.mkfifo(tmp_path / "stuck.woff2")
    body = """<style>@font-face{font-family:Stuck;src:url(stuck.woff2)}</style>
<script>addEventListener('load', () => { const p = document.createElement('p'); p.style.fontFamily = 'Stuck'; p.textContent = '글자'; document.body.appendChild(p) })</script>"""
    with pytest.raises(ToolError, match=r"^fonts:"):
        with chrome.open_page(write(tmp_path, body), 320, 100, chrome.Timeouts(load=5, assets=2)):
            pass


def test_sound_that_never_arrives_fails_as_audio(tmp_path):
    body = "<script>window.renderAudio = () => new Promise(() => {})</script>"
    with chrome.open_page(write(tmp_path, body), 320, 100, chrome.Timeouts(audio=2)) as pg:
        with pytest.raises(ToolError, match=r"^audio:"):
            pg.audio(48000, 1.0)
