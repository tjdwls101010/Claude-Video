"""One local page open in Chrome and held still: every animation is frozen from the moment the page opens (DevTools `Animation.setPlaybackRate(0)`), so nothing moves between frames except what a seek sets. Without the freeze, animations run on the wall clock while the page loads, and a short one is over, and gone from `document.getAnimations()`, before the first frame."""

from __future__ import annotations

import base64
import os
from array import array
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

from video.errors import ToolError

from . import fonts

# Schemes a page may load from. Everything else (http, https, ws) is refused so a re-render draws the same frames months later.
LOCAL_SCHEMES = {"file", "data", "blob"}

# Runs `body` (an async function body of `arg`) and parks its outcome in window.__videoGraphic, so wait_for_function can bound the wait.
RUN = """(arg) => {
  const box = window.__videoGraphic = {state: 'pending'};
  (async (arg) => { %s })(arg).then(v => { box.state = 'ok'; box.value = v === undefined ? null : v },
                                    e => { box.state = 'error'; box.error = String((e && e.stack) || e) });
}"""

IMAGES = """
  const blocked = new Set(arg), bad = [];
  await Promise.all([...document.images].map(async img => {
    const src = img.currentSrc || img.src;
    if (!src || blocked.has(src)) return;
    try { await img.decode() } catch (e) { bad.push(decodeURI(src)) }
  }));
  return bad;
"""

RECORD = """() => {
  window.__videoGraphicAnimations = document.getAnimations();
  const d = window.duration;
  return {animations: window.__videoGraphicAnimations.length, seek: typeof window.seek === 'function', audio: typeof window.renderAudio === 'function',
          duration: d === undefined ? null : (typeof d === 'number' ? d : String(d))};
}"""

# Calls the page's renderAudio and hands back each channel as base64 float32, which crosses the DevTools boundary far more compactly than a JSON number list.
AUDIO = """
  if (typeof window.renderAudio !== 'function') return null;
  const buf = await window.renderAudio(arg[0], arg[1]);
  if (buf === null || buf === undefined) return null;
  if (typeof buf.getChannelData !== 'function') throw new Error('window.renderAudio must give an AudioBuffer, a Promise of one, or null; got ' + Object.prototype.toString.call(buf));
  const b64 = a => { const u = new Uint8Array(a.buffer, a.byteOffset, a.byteLength); let s = '';
    for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000)); return btoa(s) };
  return {rate: buf.sampleRate, channels: Array.from({length: buf.numberOfChannels}, (_, c) => b64(buf.getChannelData(c)))};
"""

# Sets the animations the page had when it loaded to `arg` seconds, refuses CSS transitions (they run on the wall clock), then lets two frames pass.
SETTLE = """
  for (const a of window.__videoGraphicAnimations) { a.pause(); a.currentTime = arg * 1000 }
  const tr = document.getAnimations().find(a => typeof CSSTransition !== 'undefined' && a instanceof CSSTransition);
  if (tr) {
    const el = tr.effect && tr.effect.target;
    return (tr.transitionProperty || 'a property') + ' of ' + (el ? el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') : 'an element');
  }
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  return null;
"""


@dataclass(frozen=True)
class Timeouts:
    """Seconds each stage may take before the render fails naming that stage: loading the page, its fonts and its images (`assets`, each), one `window.seek` and the settle after it, and `window.renderAudio`."""

    load: float = 30
    assets: float = 15
    seek: float = 10
    audio: float = 60


@dataclass
class Pcm:
    """The page's sound: float samples per channel at `sample_rate`, as long as the page made them."""

    sample_rate: int
    channels: list[array]


@dataclass
class FontUse:
    """One requested font family across the page's visible text: the faces that drew it (name, glyph count) and whether another face stood in for some of it."""

    family: str
    drawn_by: list[tuple[str, int]] = field(default_factory=list)
    fallback: bool = False
    text: str = ""


class Page:
    """A loaded page. `declared_duration` is the page's `window.duration` as it gave it (None when unset); `blocked` lists network URLs refused so far."""

    def __init__(self, browser, path: Path, width: int, height: int, timeouts: Timeouts):
        from playwright.sync_api import Error, TimeoutError

        self._Error, self._Timeout = Error, TimeoutError
        self._timeouts = timeouts
        self._errors: list[str] = []
        self._missing: list[str] = []
        self.blocked: list[str] = []
        self._context = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1)
        self._context.route("**/*", self._route)
        self._page = self._context.new_page()
        cdp = self._context.new_cdp_session(self._page)
        cdp.send("Animation.enable")
        cdp.send("Animation.setPlaybackRate", {"playbackRate": 0})
        self._page.on("pageerror", lambda e: self._errors.append(" ".join(str(e).split())[:300]))
        self._page.on("requestfailed", self._failed)
        self._load(path)

    # -- loading ---------------------------------------------------------------------------------------------------------

    def _route(self, route) -> None:
        url = route.request.url
        if urlparse(url).scheme in LOCAL_SCHEMES:
            route.continue_()
            return
        if url not in self.blocked:
            self.blocked.append(url)
        route.abort("blockedbyclient")

    def _failed(self, request) -> None:
        if request.url.startswith("file:"):
            self._missing.append(f"{unquote(urlparse(request.url).path)} ({request.failure})")

    def _check(self) -> None:
        if self._missing:
            raise ToolError(f"files: the page could not load {'; '.join(self._missing[:5])}")
        if self._errors:
            raise ToolError(f"page: uncaught error in the page: {self._errors[0]}")

    def _load(self, path: Path) -> None:
        t = self._timeouts
        try:
            self._page.goto(path.resolve().as_uri(), wait_until="load", timeout=t.load * 1000)
        except self._Timeout:
            raise ToolError(f"load: the page did not finish loading in {t.load:g} s")
        except self._Error as e:
            raise ToolError(f"load: {' '.join(str(e).split())[:300]}")
        self._check()
        try:
            self._page.wait_for_function("() => document.fonts.status === 'loaded'", timeout=t.assets * 1000)
        except self._Timeout:
            raise ToolError(f"fonts: the page's fonts did not finish loading in {t.assets:g} s")
        bad = self._run(IMAGES, self.blocked, t.assets, "images", "decoding the page's images")
        self._check()
        if bad:
            raise ToolError(f"images: cannot load or decode {'; '.join(bad[:5])}")
        info = self._page.evaluate(RECORD)
        self.declared_duration = info["duration"]
        self._has_seek = info["seek"]
        self._has_audio = info["audio"]

    def _run(self, body: str, arg, seconds: float, stage: str, what: str):
        """Run `body` in the page and wait at most `seconds` for it to settle; a rejection or the time running out fails the render, naming `stage`."""
        self._page.evaluate(RUN % body, arg)
        try:
            self._page.wait_for_function("() => window.__videoGraphic.state !== 'pending'", timeout=seconds * 1000)
        except self._Timeout:
            raise ToolError(f"{stage}: {what} did not finish in {seconds:g} s")
        box = self._page.evaluate("() => window.__videoGraphic")
        if box["state"] == "error":
            raise ToolError(f"{stage}: {what} failed: {' '.join(box['error'].split())[:300]}")
        return box["value"]

    # -- time ------------------------------------------------------------------------------------------------------------

    def _seek(self, t: float) -> None:
        if self._has_seek:
            self._run("return await window.seek(arg)", t, self._timeouts.seek, "seek", f"window.seek({t:g})")
        transition = self._run(SETTLE, t, self._timeouts.seek, "seek", f"settling the page at {t:g} s")
        if transition:
            raise ToolError(f"seek: a CSS transition ({transition}) started at {t:g} s; transitions run on the wall clock, so use @keyframes or window.seek")
        self._check()

    def frames(self, times: list[float], on_frame: Callable[[float, bytes], None]) -> None:
        """Seek to each page time in order given (any order; the same time draws the same frame) and hand its transparent PNG to `on_frame`."""
        for t in times:
            self._seek(t)
            try:
                png = self._page.screenshot(type="png", omit_background=True, timeout=self._timeouts.seek * 1000)
            except self._Error as e:
                raise ToolError(f"capture: the frame at {t:g} s could not be captured: {' '.join(str(e).split())[:300]}")
            on_frame(t, png)

    def audio(self, sample_rate: int, seconds: float) -> Pcm | None:
        """The page's `window.renderAudio(sample_rate, seconds)`, or None when it has none or returns null. A buffer at another rate fails: it would play at the wrong pitch."""
        got = self._run(AUDIO, [sample_rate, seconds], self._timeouts.audio, "audio", "window.renderAudio")
        self._check()
        if got is None:
            return None
        if got["rate"] != sample_rate:
            raise ToolError(f"audio: window.renderAudio gave a buffer at {got['rate']:g} Hz; make it at the sampleRate it is called with ({sample_rate})")
        channels = []
        for data in got["channels"]:
            a = array("f")
            a.frombytes(base64.b64decode(data))
            channels.append(a)
        return Pcm(sample_rate, channels)

    def fonts(self, at_times: list[float]) -> list[FontUse]:
        """The faces that drew each requested family across the visible text at these page times, in the order families were first seen."""
        cdp = self._context.new_cdp_session(self._page)
        cdp.send("DOM.enable")
        cdp.send("CSS.enable")
        uses: dict[str, FontUse] = {}
        glyphs: dict[str, dict[str, int]] = {}
        for t in at_times:
            self._seek(t)
            now: dict[tuple[str, str], int] = {}
            for rec in fonts.sample(self._page, cdp):
                use = uses.setdefault(rec["family"], FontUse(rec["family"]))
                if rec["fallback"] and not use.fallback:
                    use.fallback, use.text = True, rec["text"]
                for face, n in rec["faces"]:
                    now[(rec["family"], face)] = now.get((rec["family"], face), 0) + n
            for (family, face), n in now.items():
                faces = glyphs.setdefault(family, {})
                faces[face] = max(faces.get(face, 0), n)
        cdp.detach()
        for family, use in uses.items():
            use.drawn_by = sorted(glyphs.get(family, {}).items(), key=lambda kv: -kv[1])
        return list(uses.values())


@contextmanager
def open_page(path: Path, width: int, height: int, timeouts: Timeouts = Timeouts()) -> Iterator[Page]:
    """Launch Chrome, open `path` at a `width` x `height` viewport, wait for it, its fonts and images, and freeze its clock. Raises ToolError naming the stage that failed: launch, load, files, fonts, images, page."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ToolError("launch: Playwright is not installed; run cli.py through `uv run`, whose PEP 723 header installs it")
    override = os.environ.get("VIDEO_CHROME_PATH")
    with sync_playwright() as p:
        try:
            # srgb: captures must not depend on the display's colour profile
            options = {"args": ["--force-color-profile=srgb"]}
            browser = p.chromium.launch(executable_path=override, **options) if override else p.chromium.launch(channel="chrome", **options)
        except Exception as e:  # noqa: BLE001 -- any launch failure means this machine cannot render
            raise ToolError("launch: Google Chrome cannot be started (" + " ".join(str(e).split())[:200] + "). Install Google Chrome; or, after asking the user, "
                            "`uvx playwright install chromium` (about 150 MB) and point VIDEO_CHROME_PATH at the Chromium it installs")
        try:
            page = Page(browser, path, width, height, timeouts)
            yield page
        finally:
            browser.close()
