"""`graphic`: a page rendered through the real entry point (`uv run cli.py`, so the PEP 723 header supplies Playwright) with the installed Chrome, ffmpeg and filmcraft-cli. Expected values come from what the page paints and from worked examples of the frame and sample arithmetic, never from the renderer's own output."""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from support import FFMPEG, needs_ffmpeg, skill

pytestmark = [needs_ffmpeg, pytest.mark.slow]

BLANK = "<!doctype html><meta charset='utf-8'><style>html,body{margin:0;background:transparent}</style>"


def page(d: Path, body: str = "", name: str = "g.html", head: str = "") -> Path:
    p = d / name
    p.write_text(BLANK + head + body, encoding="utf-8")
    return p


def graphic(d: Path, *args: str):
    return skill("graphic", *args, cwd=d, via_uv=True)


def ffprobe(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-count_frames", str(path)], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def video_stream(path: Path) -> dict:
    return next(s for s in ffprobe(path)["streams"] if s["codec_type"] == "video")


# -- length and rate ------------------------------------------------------------------------------------------------------

def test_three_seconds_at_ntsc_30_is_90_frames(tmp_path):
    """Worked example: 3 s x 30000/1001 = 89.91, rounded to 90 frames; the render lasts 90 x 1001/30000 = 3.003 s."""
    code, out, raw, err = graphic(tmp_path, str(page(tmp_path)), "--out", str(tmp_path / "g.mov"), "--size", "320x180", "--fps", "30000/1001", "--duration", "3")
    assert code == 0, raw + err
    assert (out["kind"], out["frames"], out["fps"], out["size"]) == ("video", 90, "30000/1001", "320x180")
    assert out["seconds"] == pytest.approx(3.003, abs=1e-6)
    v = video_stream(tmp_path / "g.mov")
    assert int(v["nb_read_frames"]) == 90 and v["r_frame_rate"] == "30000/1001" and (v["width"], v["height"]) == (320, 180)


def decode_rgba(path: Path, w: int, h: int) -> list[bytes]:
    """Every frame as straight RGBA bytes, converted with the BT.709 limited-range matrix the file is tagged with."""
    r = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-vf", "scale=in_color_matrix=bt709:in_range=tv,format=rgba", "-f", "rawvideo", "-"], capture_output=True, check=True)
    size = w * h * 4
    return [r.stdout[i:i + size] for i in range(0, len(r.stdout), size)]


def px(frame: bytes, w: int, x: int, y: int) -> tuple:
    i = (y * w + x) * 4
    return tuple(frame[i:i + 4])


def bg_project(d: Path, size: str = "640x360", rate: str = "30", color: str = "0x0000ff", seconds: float = 2, name: str = "p") -> Path:
    """A project whose active sequence is a solid-colour clip of this size and rate (V1/A1)."""
    from support import fc, ffmpeg
    src = d / f"{name}.mp4"
    ffmpeg("-f", "lavfi", "-i", f"color=c={color}:s={size}:r={rate}:d={seconds}", "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-c:a", "aac", "-shortest", str(src))
    p = d / f"{name}.fcproj"
    fc("--save-as", str(p), "import", str(src), cwd=d)
    fc("--save", "exec", "file.newSequenceFromClip", "items=[1]", project=p, cwd=d)
    return p


# Six columns, sized to any frame: opaque red, 50 % red, mid grey, a mid-tone skin colour, a white disc (antialiased edge), nothing.
SWATCHES = """<style>div.s{position:absolute;top:0;height:100%;width:16.6667%}
#disc{position:absolute;left:66.6667%;top:25%;width:16.6667vw;height:16.6667vw;max-height:50%;max-width:50vh;border-radius:50%;background:#fff}</style>
<div class=s style="left:0;background:#ff0000"></div><div class=s style="left:16.6667%;background:rgba(255,0,0,.5)"></div>
<div class=s style="left:33.3333%;background:#808080"></div><div class=s style="left:50%;background:#C8A08C"></div><div id=disc></div>"""


def column(w: int, i: int) -> int:
    return int(w * (i + 0.5) / 6)


@pytest.mark.parametrize("rate, frames", [("24000/1001", 24), ("25", 25), ("30000/1001", 30), ("60000/1001", 60)])
def test_frame_rate_and_count_follow_the_sequence(tmp_path, rate, frames):
    """One second at each common rate: 23.976 -> 24, 25, 29.97 -> 30, 59.94 -> 60 frames, written at the sequence's exact rate."""
    p = bg_project(tmp_path, rate=rate)
    code, out, raw, err = graphic(tmp_path, str(page(tmp_path, SWATCHES)), "--out", str(tmp_path / "g.mov"), "--project", str(p), "--duration", "1")
    assert code == 0, raw + err
    v = video_stream(tmp_path / "g.mov")
    assert out["frames"] == frames and int(v["nb_read_frames"]) == frames
    assert Fraction(v["r_frame_rate"]) == Fraction(rate) and out["fps"] == rate


def test_movie_is_straight_alpha_prores_4444_tagged_bt709(tmp_path):
    w, h = 600, 300
    code, out, raw, err = graphic(tmp_path, str(page(tmp_path, SWATCHES)), "--out", str(tmp_path / "g.mov"), "--size", f"{w}x{h}", "--fps", "30", "--duration", "0.1")
    assert code == 0, raw + err
    v = video_stream(tmp_path / "g.mov")
    assert (v["codec_name"], v["profile"]) == ("prores", "4444") and v["pix_fmt"].startswith("yuva")
    assert (v["color_primaries"], v["color_transfer"], v["color_space"], v["color_range"]) == ("bt709", "bt709", "bt709", "tv")
    f = decode_rgba(tmp_path / "g.mov", w, h)[0]
    near = lambda a, b, tol: all(abs(x - y) <= tol for x, y in zip(a, b))
    assert near(px(f, w, column(w, 0), h // 2), (255, 0, 0, 255), 2)
    assert near(px(f, w, column(w, 1), h // 2), (255, 0, 0, 128), 2)          # straight: colour kept, alpha halved
    assert near(px(f, w, column(w, 2), h // 2), (128, 128, 128, 255), 2)
    assert near(px(f, w, column(w, 3), h // 2), (0xC8, 0xA0, 0x8C, 255), 2)
    assert px(f, w, column(w, 5), 5)[3] == 0
    edge = [px(f, w, x, y) for y in range(h) for x in range(int(w * 4 / 6), int(w * 5 / 6)) if 30 < px(f, w, x, y)[3] < 225]
    assert edge and all(min(p[:3]) >= 248 for p in edge)                      # an antialiased edge stays white, not darkened


def srgb_to_linear(v: float) -> float:
    c = v / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(l: float) -> float:
    c = 12.92 * l if l <= 0.0031308 else 1.055 * l ** (1 / 2.4) - 0.055
    return c * 255


def fc_render(d: Path, p: Path, seconds: float, name: str):
    from PIL import Image
    from support import fc
    out = d / f"{name}.png"
    fc("render", "--seconds", str(seconds), "--out", str(out), project=p, cwd=d)
    return Image.open(out).convert("RGB")


def place_render(d: Path, p: Path, out: dict, start: float = 0.0, hold_ticks: int | None = None):
    """Run the render's `next` steps with the placeholders filled, as the model would."""
    import shlex
    from support import fc
    item = None
    for step in out["next"]["steps"]:
        step = step.replace("<start s>", f"{start}")
        if hold_ticks is not None:
            step = step.replace("<hold ticks>", str(hold_ticks))
        if item is not None:
            step = step.replace("<item>", str(item))
        args = shlex.split(step)
        assert args[0] == "filmcraft-cli"
        r = fc(*args[1:], cwd=d)
        if " import " in f" {step} ":
            item = json.loads(r.stdout)["items"][0]
    return item


@pytest.mark.parametrize("size", ["1920x1080", "1080x1920", "1080x1080", "3840x2160"])
def test_filmcraft_composites_the_page_as_painted(tmp_path, size):
    """FilmCraft round trip: over a blue clip, opaque colours come back as painted (within 2) and 50 % red is the blend in linear light, which is how FilmCraft composites (expected by the sRGB transfer function, IEC 61966-2-1)."""
    w, h = map(int, size.split("x"))
    p = bg_project(tmp_path, size=size, seconds=1)
    code, out, raw, err = graphic(tmp_path, str(page(tmp_path, SWATCHES)), "--out", str(tmp_path / "g.mov"), "--project", str(p), "--duration", "1")
    assert code == 0, raw + err
    bg = fc_render(tmp_path, p, 0.5, "bg").getpixel((column(w, 1), h // 2))
    place_render(tmp_path, p, out)
    img = fc_render(tmp_path, p, 0.5, "over")
    near = lambda a, b: all(abs(x - y) <= 2 for x, y in zip(a, b))
    assert near(img.getpixel((column(w, 0), h // 2)), (255, 0, 0))
    assert near(img.getpixel((column(w, 2), h // 2)), (128, 128, 128))
    assert near(img.getpixel((column(w, 3), h // 2)), (0xC8, 0xA0, 0x8C))
    a = 128 / 255
    blend = tuple(linear_to_srgb(a * srgb_to_linear(f) + (1 - a) * srgb_to_linear(b)) for f, b in zip((255, 0, 0), bg))
    assert near(img.getpixel((column(w, 1), h // 2)), blend), (img.getpixel((column(w, 1), h // 2)), blend)
    assert near(img.getpixel((column(w, 5), 5)), bg)


def test_hdr_sequence_takes_the_bt709_render_at_reference_white(tmp_path):
    """In a Rec. 2100 HLG sequence the render stays BT.709 and FilmCraft puts its white at the HLG reference level (75 % signal, ITU-R BT.2408)."""
    from PIL import Image
    from support import fc, fc_run, ffmpeg
    p = bg_project(tmp_path, color="black", seconds=1)
    fc_run([{"id": "sequence.settings", "params": {"workingSpace": "rec2100-hlg"}}], p, cwd=tmp_path)
    white = page(tmp_path, "<div style='position:absolute;inset:0;background:#fff'></div>")
    code, out, raw, err = graphic(tmp_path, str(white), "--out", str(tmp_path / "w.mov"), "--project", str(p), "--duration", "1")
    assert code == 0, raw + err
    v = video_stream(tmp_path / "w.mov")
    assert (v["color_primaries"], v["color_transfer"]) == ("bt709", "bt709")
    place_render(tmp_path, p, out)
    fc("exec", "file.exportMedia", json.dumps({"path": str(tmp_path / "hlg.mov"), "format": "prores", "range": "entire", "wait": True}), project=p, cwd=tmp_path)
    ffmpeg("-ss", "0.5", "-i", str(tmp_path / "hlg.mov"), "-frames:v", "1", "-pix_fmt", "rgb24", str(tmp_path / "hlg.png"))
    assert Image.open(tmp_path / "hlg.png").getpixel((320, 180))[1] / 255 == pytest.approx(0.75, abs=0.02)


# -- time ------------------------------------------------------------------------------------------------------------------

# A 50 px box moving left 0 -> 1000 px over 1 s, starting at 0.5 s: by CSS @keyframes (top row), by window.seek (middle row), and by a Web Animation that seek creates and runs at half speed (bottom row).
CSS_BOX = "<style>#c{position:absolute;top:0;left:0;width:50px;height:30px;background:#00f;animation:mv 1s linear .5s both}@keyframes mv{from{left:0}to{left:1000px}}</style><div id=c></div>"
SEEK_BOX = """<div id=s style="position:absolute;top:35px;left:0;width:50px;height:30px;background:#0f0"></div>
<script>window.seek = t => { document.getElementById('s').style.left = Math.min(1000, Math.max(0, (t - .5) * 1000)) + 'px' }</script>"""
OWN_BOX = """<div id=o style="position:absolute;top:70px;left:0;width:50px;height:30px;background:#f00"></div>
<script>let own; const prev = window.seek; window.seek = async t => { if (prev) prev(t);
  own = own || document.getElementById('o').animate([{left: '0px'}, {left: '1000px'}], {duration: 1000, delay: 500, fill: 'both'});
  own.pause(); own.currentTime = t * 500 }</script>"""


def left_edge(frame: bytes, w: int, y: int) -> int | None:
    return next((x for x in range(w) if px(frame, w, x, y)[3] > 128), None)


def expected_left(t: float, speed: float = 1.0) -> float:
    return min(1000.0, max(0.0, (t * speed - 0.5) * 1000))


@pytest.mark.parametrize("body, rows", [(CSS_BOX, {15: 1.0}), (SEEK_BOX, {50: 1.0}), (CSS_BOX + SEEK_BOX + OWN_BOX, {15: 1.0, 50: 1.0, 85: 0.5})], ids=["css", "seek", "mixed"])
def test_each_frame_shows_its_page_time(tmp_path, body, rows):
    """Frame n is page time n/30: CSS keyframes count from page open (delay included), seek draws t, and an animation seek creates is seek's to time (here half speed), not reset by the renderer."""
    w, h = 1100, 100
    code, out, raw, err = graphic(tmp_path, str(page(tmp_path, body)), "--out", str(tmp_path / "t.mov"), "--size", f"{w}x{h}", "--fps", "30", "--duration", "2")
    assert code == 0, raw + err
    frames = decode_rgba(tmp_path / "t.mov", w, h)
    assert len(frames) == 60
    for n in (0, 14, 15, 16, 25, 30, 44, 45, 59):
        for y, speed in rows.items():
            got = left_edge(frames[n], w, y)
            assert got is not None and abs(got - expected_left(n / 30, speed)) <= 1, (n, y, got, expected_left(n / 30, speed))


def test_a_css_transition_is_refused(tmp_path):
    body = """<style>#b{position:absolute;left:0;width:50px;height:50px;background:#00f;transition:left 1s}</style><div id=b></div>
<script>window.seek = t => { document.getElementById('b').style.left = (t * 100) + 'px' }</script>"""
    code, out, raw, err = graphic(tmp_path, str(page(tmp_path, body)), "--out", str(tmp_path / "t.mov"), "--size", "320x180", "--fps", "30", "--duration", "1")
    assert code == 1, raw + err
    assert out["error"].startswith("seek:") and "transition" in out["error"]
    assert not (tmp_path / "t.mov").exists()


# -- replacing a render ----------------------------------------------------------------------------------------------------

def test_a_failed_render_leaves_the_earlier_file_untouched(tmp_path):
    good = page(tmp_path, SWATCHES, name="good.html")
    code, out, raw, err = graphic(tmp_path, str(good), "--out", str(tmp_path / "g.mov"), "--size", "320x180", "--fps", "30", "--duration", "1")
    assert code == 0, raw + err
    before = (tmp_path / "g.mov").read_bytes()
    # seeded noise does not compress, so ffmpeg is already writing when the page breaks
    bad = page(tmp_path, """<canvas id=c width=640 height=360></canvas><script>
window.seek = t => { if (t > 0.95) throw new Error('broken at ' + t);
  const g = document.getElementById('c').getContext('2d'), img = g.createImageData(640, 360); let x = 1 + Math.round(t * 30);
  for (let i = 0; i < img.data.length; i++) { x = (x * 1103515245 + 12345) % 2147483648; img.data[i] = x >> 16 & 255 }
  g.putImageData(img, 0, 0) }</script>""", name="bad.html")
    code, out, raw, err = graphic(tmp_path, str(bad), "--out", str(tmp_path / "g.mov"), "--size", "640x360", "--fps", "30", "--duration", "1")
    assert code == 1 and out["error"].startswith("seek:"), raw + err
    assert (tmp_path / "g.mov").read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith(".g.")) == []     # no partial files left behind


def test_an_animation_shorter_than_the_load_still_plays_from_page_open(tmp_path):
    """Twenty 50 ms parser-blocking scripts after the animated box hold the load event about 1 s while Chrome renders frames between them, so a 0.3 s animation started at the first frame is over, and gone from the page's animations, before capture begins unless the clock was frozen from page open. Frame 3 at 20 fps (0.15 s) must show it halfway."""
    busy = "<script>{const t = performance.now(); while (performance.now() - t < 50) {}}</script>" * 20
    body = "<style>#c{position:absolute;top:0;left:0;width:50px;height:50px;background:#00f;animation:mv .3s linear}@keyframes mv{from{left:0}to{left:1000px}}</style><div id=c></div>" + busy
    w, h = 1100, 50
    code, out, raw, err = graphic(tmp_path, str(page(tmp_path, body)), "--out", str(tmp_path / "t.mov"), "--size", f"{w}x{h}", "--fps", "20", "--duration", "0.5")
    assert code == 0, raw + err
    frames = decode_rgba(tmp_path / "t.mov", w, h)
    assert abs(left_edge(frames[3], w, 25) - 500) <= 1


# -- stills ----------------------------------------------------------------------------------------------------------------

def test_a_still_keeps_straight_alpha_and_the_page_time_asked_for(tmp_path):
    from PIL import Image
    w, h = 600, 300
    body = SWATCHES + "<script>window.seek = t => { document.body.dataset.t = t; document.getElementById('disc').style.opacity = t >= 2 ? 0 : 1 }</script>"
    code, out, raw, err = graphic(tmp_path, str(page(tmp_path, body)), "--out", str(tmp_path / "g.png"), "--size", f"{w}x{h}", "--fps", "30", "--frame-at", "2.5")
    assert code == 0, raw + err
    assert (out["kind"], out["frames"], out["size"]) == ("still", 1, f"{w}x{h}") and out["coverage"][0]["t"] == 2.5
    img = Image.open(tmp_path / "g.png")
    assert img.mode == "RGBA" and img.size == (w, h)
    assert img.getpixel((column(w, 1), h // 2)) == (255, 0, 0, 128) and img.getpixel((column(w, 3), h // 2)) == (0xC8, 0xA0, 0x8C, 255)
    assert img.getpixel((column(w, 4), h // 2))[3] == 0                         # the disc is hidden from 2 s on


def test_a_placed_still_composites_as_painted_for_the_hold_asked(tmp_path):
    from support import TICKS
    w, h = 640, 360
    p = bg_project(tmp_path, seconds=3)
    code, out, raw, err = graphic(tmp_path, str(page(tmp_path, SWATCHES)), "--out", str(tmp_path / "g.png"), "--project", str(p))
    assert code == 0, raw + err
    bg = fc_render(tmp_path, p, 1.0, "bg").getpixel((column(w, 1), h // 2))
    place_render(tmp_path, p, out, start=1.0, hold_ticks=TICKS)
    from support import fc_json
    s = fc_json("inspect", "sequence", project=p, cwd=tmp_path)
    [clip] = s["video"][1]["items"]
    assert (clip["start"], clip["end"]) == (TICKS, 2 * TICKS)
    img = fc_render(tmp_path, p, 1.5, "over")
    near = lambda a, b: all(abs(x - y) <= 2 for x, y in zip(a, b))
    assert near(img.getpixel((column(w, 3), h // 2)), (0xC8, 0xA0, 0x8C))
    a = 128 / 255
    blend = tuple(linear_to_srgb(a * srgb_to_linear(f) + (1 - a) * srgb_to_linear(b)) for f, b in zip((255, 0, 0), bg))
    assert near(img.getpixel((column(w, 1), h // 2)), blend)


# -- reports ---------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("body, painted, opaque", [
    ("<div style='position:absolute;inset:0;background:rgba(0,0,0,.01)'></div>", 1.0, 0.0),
    ("<div style='position:absolute;left:0;top:0;width:50%;height:100%;background:#000'></div>", 0.5, 0.5),
    ("", 0.0, 0.0),
], ids=["faint everywhere", "half solid", "empty"])
def test_coverage_tells_paint_from_what_hides_the_picture(tmp_path, body, painted, opaque):
    code, out, raw, err = graphic(tmp_path, str(page(tmp_path, body)), "--out", str(tmp_path / "g.mov"), "--size", "320x180", "--fps", "30", "--duration", "1")
    assert code == 0, raw + err
    assert [c["t"] for c in out["coverage"]] == [0.0, 0.5, 0.967]
    for c in out["coverage"]:
        assert c["painted"] == pytest.approx(painted, abs=0.01) and c["opaque"] == pytest.approx(opaque, abs=0.01)


def test_fonts_report_the_face_that_drew_and_flag_substitutes(tmp_path):
    """macOS faces only, so the expectation holds on any Mac: a family that is missing, or one without Hangul, has its Korean drawn by another face."""
    body = """<p id=a style="font-family:'Apple SD Gothic Neo'">한글 제목</p><p id=b style="font-family:'NoSuchFamilyAnywhere'">한글 제목</p>
<p id=c style="font-family:'Inter','Helvetica'">한글 제목</p><p id=d style="font-family:'Apple SD Gothic Neo';opacity:0" class=later>나중</p>
<script>window.seek = t => { document.getElementById('d').style.opacity = t >= 1 ? 1 : 0; document.getElementById('d').style.fontFamily = t >= 1 ? "'NoSuchLaterFamily'" : "'Apple SD Gothic Neo'" }</script>"""
    code, out, raw, err = graphic(tmp_path, str(page(tmp_path, body)), "--out", str(tmp_path / "g.mov"), "--size", "640x360", "--fps", "30", "--duration", "1.5")
    assert code == 0, raw + err
    fonts = {f["family"]: f for f in out["fonts"]}
    assert fonts["Apple SD Gothic Neo"]["fallback"] is False and [d["face"] for d in fonts["Apple SD Gothic Neo"]["drawn_by"]] == ["Apple SD Gothic Neo"]
    assert fonts["NoSuchFamilyAnywhere"]["fallback"] is True and "한글" in fonts["NoSuchFamilyAnywhere"]["text"]
    assert any(d["face"] == "AppleMyungjo" for d in fonts["NoSuchFamilyAnywhere"]["drawn_by"])
    assert fonts["Inter"]["fallback"] is True and all(d["glyphs"] > 0 for d in fonts["Inter"]["drawn_by"])
    assert fonts["NoSuchLaterFamily"]["fallback"] is True                       # text that appears later is sampled too


def test_websockets_are_blocked_and_listed(tmp_path):
    body = "<script>window.opened = new WebSocket('wss://echo.websocket.org/feed')</script><div style='width:10px;height:10px;background:red'></div>"
    code, out, raw, err = graphic(tmp_path, str(page(tmp_path, body)), "--out", str(tmp_path / "g.png"), "--size", "320x180", "--fps", "30")
    assert code == 0, raw + err
    assert "wss://echo.websocket.org/feed" in out["blocked"]


def test_network_requests_are_blocked_and_listed(tmp_path):
    body = "<img src='https://example.com/a.png'><link rel=stylesheet href='https://fonts.googleapis.com/css2?family=Noto+Sans+KR'><div style='width:10px;height:10px;background:red'></div>"
    code, out, raw, err = graphic(tmp_path, str(page(tmp_path, body)), "--out", str(tmp_path / "g.png"), "--size", "320x180", "--fps", "30")
    assert code == 0, raw + err
    assert out["blocked"] == ["https://example.com/a.png", "https://fonts.googleapis.com/css2?family=Noto+Sans+KR"] or sorted(out["blocked"]) == sorted(["https://example.com/a.png", "https://fonts.googleapis.com/css2?family=Noto+Sans+KR"])


# -- failures --------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("body, stage", [
    ("<script>window.seek = t => new Promise(() => {})</script>", "seek:"),
    ("<script>window.seek = t => { if (t > 0.2) while (true) {} }</script>", "seek:"),
    ("<img src='missing.png'>", "files:"),
    ("<script>window.seek = t => { if (t > 0.2) undefinedFunction() }</script>", "seek:"),
    ("<script>throw new Error('at load')</script>", "page:"),
    ("<script>Promise.reject(new Error('nobody caught this'))</script>", "page:"),
    ("<script>window.seek = t => { if (t > 0.2) setTimeout(() => { throw new Error('later') }) }</script>", "page:"),
], ids=["seek never settles", "seek never returns", "missing local file", "seek throws", "uncaught at load", "unhandled rejection", "uncaught after seek"])
def test_a_failing_page_exits_1_naming_the_stage_and_keeps_the_earlier_file(tmp_path, body, stage):
    target = tmp_path / "g.mov"
    target.write_bytes(b"an earlier render")
    code, out, raw, err = graphic(tmp_path, str(page(tmp_path, body)), "--out", str(target), "--size", "320x180", "--fps", "30", "--duration", "1")
    assert code == 1, raw + err
    assert out["error"].startswith(stage), out["error"]
    assert target.read_bytes() == b"an earlier render"


@pytest.mark.parametrize("args, says", [
    (["--size", "320x180", "--fps", "29.97", "--duration", "1"], "--fps"),
    (["--size", "320x180", "--fps", "30", "--duration", "0"], "--duration"),
    (["--size", "320x180", "--fps", "30", "--duration", "-1"], "--duration"),
    (["--size", "320x180", "--fps", "30", "--duration", "inf"], "--duration"),
    (["--size", "320x180", "--duration", "1"], "--fps"),
    (["--size", "320x180", "--fps", "30"], "length"),
], ids=["decimal fps", "zero length", "negative length", "infinite length", "size without fps", "movie without length"])
def test_command_lines_that_must_change_exit_2(tmp_path, args, says):
    code, out, raw, err = graphic(tmp_path, str(page(tmp_path)), "--out", str(tmp_path / "g.mov"), *args)
    assert code == 2, raw + err
    assert says in out["error"] and out["help"].endswith("--help")


def test_an_out_folder_that_cannot_exist_exits_2(tmp_path):
    (tmp_path / "taken").write_text("a file where a folder would go")
    code, out, raw, err = graphic(tmp_path, str(page(tmp_path)), "--out", str(tmp_path / "taken" / "g.mov"), "--size", "320x180", "--fps", "30", "--duration", "1")
    assert code == 2, raw + err
    assert "--out" in out["error"]


@pytest.mark.parametrize("seconds, fps, frames", [("0.01", "30", 1), ("0.05", "30", 2), ("0.0166", "30", 1), ("2.5", "24000/1001", 60)],
                         ids=["under a frame is one", "1.5 rounds up", "0.498 rounds down to the minimum", "2.5 s at 23.976 is 59.94"])
def test_frame_count_worked_examples(tmp_path, seconds, fps, frames):
    code, out, raw, err = graphic(tmp_path, str(page(tmp_path)), "--out", str(tmp_path / "g.mov"), "--size", "64x64", "--fps", fps, "--duration", seconds)
    assert code == 0, raw + err
    assert out["frames"] == frames and int(video_stream(tmp_path / "g.mov")["nb_read_frames"]) == frames


def test_following_if_placed_after_a_length_change_gives_the_new_length(tmp_path):
    """Place a 1 s render, re-render it at 2 s to the same path, and do what `if_placed` says: clear the placed clip, then run the steps. The clip on the timeline then lasts 2 s."""
    from support import TICKS, fc, fc_json
    p = bg_project(tmp_path, seconds=4)
    g = page(tmp_path, SWATCHES)
    code, first, raw, err = graphic(tmp_path, str(g), "--out", str(tmp_path / "g.mov"), "--project", str(p), "--duration", "1")
    assert code == 0, raw + err
    place_render(tmp_path, p, first, start=0)
    code, second, raw, err = graphic(tmp_path, str(g), "--out", str(tmp_path / "g.mov"), "--project", str(p), "--duration", "2")
    assert code == 0, raw + err
    assert "edit.clear" in second["next"]["if_placed"]
    placed = [c["clip"] for t in fc_json("inspect", "sequence", project=p, cwd=tmp_path)["video"] for c in t["items"] if c["name"] == "g.mov"]
    fc("--save", "exec", "edit.clear", json.dumps({"clips": placed}), project=p, cwd=tmp_path)
    place_render(tmp_path, p, second, start=0)
    s = fc_json("inspect", "sequence", project=p, cwd=tmp_path)
    assert [(c["start"], c["end"]) for t in s["video"] for c in t["items"] if c["name"] == "g.mov"] == [(0, 2 * TICKS)]


@pytest.mark.parametrize("make", ["gif", "self", "no page", "bad window.duration"])
def test_paths_and_page_values_that_cannot_work_exit_2(tmp_path, make):
    p = page(tmp_path, "<script>window.duration = 'three'</script>" if make == "bad window.duration" else "")
    out_path = {"gif": tmp_path / "g.gif", "self": p}.get(make, tmp_path / "g.mov")
    target = str(tmp_path / "nothing.html") if make == "no page" else str(p)
    code, out, raw, err = graphic(tmp_path, target, "--out", str(out_path), "--size", "320x180", "--fps", "30")
    assert code == 2, raw + err
    assert p.read_text().startswith("<!doctype html>")


# -- replacing and placing -------------------------------------------------------------------------------------------------

def test_replaced_says_what_a_placed_clip_would_get_wrong(tmp_path):
    p = page(tmp_path, SWATCHES)
    run = lambda *a: graphic(tmp_path, str(p), "--out", str(tmp_path / "g.mov"), "--size", "320x180", *a)
    code, first, raw, err = run("--fps", "30", "--duration", "1")
    assert code == 0, raw + err
    assert first["replaced"] is None and "if_placed" not in first["next"]
    code, same, raw, err = run("--fps", "30", "--duration", "1")
    assert same["replaced"] == {"length_changed": False, "audio_changed": False, "size_changed": False, "fps_changed": False}
    assert "nothing else" in same["next"]["if_placed"]
    code, longer, raw, err = run("--fps", "30", "--duration", "2")
    assert longer["replaced"]["length_changed"] is True and "edit.clear" in longer["next"]["if_placed"]
    code, faster, raw, err = run("--fps", "60", "--duration", "2")
    assert faster["replaced"]["fps_changed"] is True and faster["replaced"]["length_changed"] is True


def test_next_places_a_silent_render_without_touching_the_speech(tmp_path):
    from support import TICKS, fc_json
    p = bg_project(tmp_path, seconds=4)
    code, out, raw, err = graphic(tmp_path, str(page(tmp_path, SWATCHES)), "--out", str(tmp_path / "g.mov"), "--project", str(p), "--duration", "1.5")
    assert code == 0, raw + err
    place_render(tmp_path, p, out, start=0.5)
    s = fc_json("inspect", "sequence", project=p, cwd=tmp_path)
    [clip] = s["video"][1]["items"]
    assert (clip["start"], clip["end"]) == (TICKS // 2, 2 * TICKS)
    assert [(c["start"], c["end"]) for c in s["audio"][0]["items"]] == [(0, 4 * TICKS)] and len(s["audio"]) == 1


def test_next_places_on_the_sequence_named(tmp_path):
    from support import TICKS, fc, fc_json, fc_run
    p = bg_project(tmp_path, seconds=3)
    # a second, vertical sequence that is not active
    fc_run([{"id": "file.newSequence", "params": {"name": "vertical", "width": 1080, "height": 1920, "fps": 30}}], p, cwd=tmp_path)
    tree = fc_json("inspect", "project", project=p, cwd=tmp_path)["root"]["children"]
    vertical = next(c["item"] for c in tree if c["type"] == "Sequence" and c["name"] == "vertical")
    main = next(c["item"] for c in tree if c["type"] == "Sequence" and c["name"] != "vertical")
    fc("--save", "exec", "sequence.open", json.dumps({"item": main}), project=p, cwd=tmp_path)
    code, out, raw, err = graphic(tmp_path, str(page(tmp_path, SWATCHES)), "--out", str(tmp_path / "v.mov"), "--project", str(p), "--sequence", str(vertical), "--duration", "1")
    assert code == 0, raw + err
    assert out["size"] == "1080x1920"
    place_render(tmp_path, p, out, start=0)
    s = fc_json("inspect", "sequence", project=p, cwd=tmp_path)
    assert s["id"] == vertical or s["name"] == "vertical"
    assert [c["name"] for t in s["video"] for c in t["items"]] == ["v.mov"]


# -- sound -----------------------------------------------------------------------------------------------------------------

def tone_page(d: Path, start: float = 0.5, amp: float = 0.1, buffer_s: str = "seconds", name: str = "s.html") -> Path:
    """A 1 kHz sine at `amp` (0.1 = -20 dBFS) from `start` seconds, rendered offline; `buffer_s` is the JS expression for the buffer's length."""
    return page(d, f"""<script>window.renderAudio = async (rate, seconds) => {{
  const ctx = new OfflineAudioContext(2, Math.round(({buffer_s}) * rate), rate);
  const osc = ctx.createOscillator(), gain = ctx.createGain();
  osc.frequency.value = 1000; gain.gain.value = {amp}; osc.connect(gain).connect(ctx.destination);
  osc.start({start}); return ctx.startRendering() }}</script>""", name=name)


def pcm(path: Path) -> list[float]:
    """The movie's first audio channel as floats."""
    from array import array
    r = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-map", "0:a:0", "-af", "pan=mono|c0=c0", "-f", "f32le", "-"], capture_output=True, check=True)
    a = array("f")
    a.frombytes(r.stdout)
    return list(a)


def audio_stream(path: Path) -> dict | None:
    return next((s for s in ffprobe(path)["streams"] if s["codec_type"] == "audio"), None)


def test_page_sound_starts_on_time_at_its_level_and_lasts_the_movie(tmp_path):
    """Worked example: 90 frames at 30000/1001 last 3.003 s = 144144 samples at 48 kHz; a tone from 0.5 s is first heard at sample 24000; amplitude 0.1 is -20 dBFS."""
    code, out, raw, err = graphic(tmp_path, str(tone_page(tmp_path)), "--out", str(tmp_path / "s.mov"), "--size", "320x180", "--fps", "30000/1001", "--duration", "3")
    assert code == 0, raw + err
    a = audio_stream(tmp_path / "s.mov")
    assert a["codec_name"].startswith("pcm_") and int(a["sample_rate"]) == 48000
    x = pcm(tmp_path / "s.mov")
    assert len(x) == 144144
    first = next(i for i, v in enumerate(x) if abs(v) > 1e-3)
    assert abs(first - 24000) <= 48                                               # within 1 ms
    import math
    assert 20 * math.log10(max(abs(v) for v in x)) == pytest.approx(-20, abs=0.2)
    assert out["audio"]["peak_dbfs"] == pytest.approx(-20, abs=0.2) and out["audio"]["lufs"] is not None


@pytest.mark.parametrize("buffer_s, tail_silent", [("seconds + 2", False), ("1", True)], ids=["longer buffer is cut", "shorter buffer is padded"])
def test_the_movie_sets_the_sound_length(tmp_path, buffer_s, tail_silent):
    code, out, raw, err = graphic(tmp_path, str(tone_page(tmp_path, start=0, buffer_s=buffer_s)), "--out", str(tmp_path / "s.mov"), "--size", "320x180", "--fps", "30", "--duration", "2")
    assert code == 0, raw + err
    x = pcm(tmp_path / "s.mov")
    assert len(x) == 96000
    assert (max(abs(v) for v in x[50000:]) == 0) is tail_silent


@pytest.mark.parametrize("script, stream, levels", [
    ("", False, None),
    ("<script>window.renderAudio = () => null</script>", False, None),
    ("<script>window.renderAudio = (rate, s) => new OfflineAudioContext(1, Math.round(rate * s), rate).startRendering()</script>", True, "null"),
], ids=["no renderAudio", "renderAudio gives null", "silent buffer"])
def test_no_sound_means_no_audio_stream(tmp_path, script, stream, levels):
    code, out, raw, err = graphic(tmp_path, str(page(tmp_path, script)), "--out", str(tmp_path / "s.mov"), "--size", "320x180", "--fps", "30", "--duration", "1")
    assert code == 0, raw + err
    assert (audio_stream(tmp_path / "s.mov") is not None) is stream
    if levels is None:
        assert out["audio"] is None
    else:
        assert out["audio"] == {"peak_dbfs": None, "lufs": None}


def test_next_puts_the_sound_on_its_own_track_and_leaves_the_speech(tmp_path):
    from support import TICKS, fc_json
    p = bg_project(tmp_path, seconds=4)
    code, out, raw, err = graphic(tmp_path, str(tone_page(tmp_path)), "--out", str(tmp_path / "s.mov"), "--project", str(p), "--duration", "2")
    assert code == 0, raw + err
    place_render(tmp_path, p, out, start=1)
    s = fc_json("inspect", "sequence", project=p, cwd=tmp_path)
    assert [(c["start"], c["end"]) for c in s["audio"][0]["items"]] == [(0, 4 * TICKS)]               # A1 speech whole
    assert [(c["name"], c["start"], c["end"]) for c in s["audio"][1]["items"]] == [("s.mov", TICKS, 3 * TICKS)]
    assert [(c["name"], c["start"], c["end"]) for c in s["video"][1]["items"]] == [("s.mov", TICKS, 3 * TICKS)]


def test_adding_sound_to_a_render_counts_as_a_change(tmp_path):
    run = lambda p: graphic(tmp_path, str(p), "--out", str(tmp_path / "s.mov"), "--size", "320x180", "--fps", "30", "--duration", "1")
    code, out, raw, err = run(page(tmp_path, SWATCHES, name="quiet.html"))
    assert code == 0, raw + err
    code, out, raw, err = run(tone_page(tmp_path))
    assert code == 0, raw + err
    assert out["replaced"] == {"length_changed": False, "audio_changed": True, "size_changed": False, "fps_changed": False}


def test_without_chrome_the_error_says_how_to_get_it(tmp_path, monkeypatch):
    """A machine without Chrome, imitated by pointing VIDEO_CHROME_PATH at nothing: exit 1 at launch, and the way out names both installs and that the download is the user's to approve."""
    monkeypatch.setenv("VIDEO_CHROME_PATH", str(tmp_path / "no-chrome"))
    code, out, raw, err = graphic(tmp_path, str(page(tmp_path)), "--out", str(tmp_path / "g.png"), "--size", "64x64", "--fps", "30")
    assert code == 1, raw + err
    assert out["error"].startswith("launch:") and "Install Google Chrome" in out["error"] and "asking the user" in out["error"]
