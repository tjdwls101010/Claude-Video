"""`frames`: a labelled contact sheet from a project (FilmCraft's own renderer, so captions and graphics show) or straight from a media file. The media is one solid colour per second, so which colour each tile must show follows from the times asked for."""

from __future__ import annotations

import json

import pytest
from PIL import Image

from video import frames
from support import FFMPEG, FILMCRAFT, TICKS, fc, fc_run, ffmpeg, needs_ffmpeg, needs_filmcraft, skill

pytestmark = needs_ffmpeg

COLORS = [("red", (255, 0, 0)), ("lime", (0, 255, 0)), ("blue", (0, 0, 255)), ("yellow", (255, 255, 0))]


def color_media(path, size="640x360", rate="30"):
    """Four seconds: red, lime, blue, yellow, one second each."""
    inputs, chains = [], []
    for i, (name, _) in enumerate(COLORS):
        inputs += ["-f", "lavfi", "-i", f"color=c={name}:s={size}:r={rate}:d=1"]
    ffmpeg(*inputs, "-filter_complex", "".join(f"[{i}:v]" for i in range(len(COLORS))) + f"concat=n={len(COLORS)}:v=1:a=0[v]",
           "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "1", str(path))
    return path


def close(px, rgb, tol=40):
    return all(abs(a - b) <= tol for a, b in zip(px[:3], rgb))


def tile_center(sheet, out, i):
    """Centre pixel of tile i, from the geometry the command reports."""
    g = out["grid"]
    col, row = i % g["cols"], i // g["cols"]
    x = col * g["tile_w"] + g["tile_w"] // 2
    y = row * g["cell_h"] + g["tile_h"] // 2
    return sheet.getpixel((x, y))


def test_media_mode_samples_the_times_asked_for(tmp_path):
    m = color_media(tmp_path / "c.mp4")
    code, out, raw, err = skill("frames", "--media", str(m), "--at", "0.5", "2.5", "1.5", "--out", str(tmp_path / "s.png"), cwd=tmp_path)
    assert code == 0, raw + err
    assert [f["tc"] for f in out["frames"]] == ["00:00:00:15", "00:00:02:15", "00:00:01:15"]
    sheet = Image.open(out["sheet"]).convert("RGB")
    assert close(tile_center(sheet, out, 0), (255, 0, 0)) and close(tile_center(sheet, out, 1), (0, 0, 255)) and close(tile_center(sheet, out, 2), (0, 255, 0))


def test_every_covers_the_duration(tmp_path):
    m = color_media(tmp_path / "c.mp4")
    code, out, raw, err = skill("frames", "--media", str(m), "--every", "1", "--cols", "2", "--out", str(tmp_path / "s.png"), cwd=tmp_path)
    assert code == 0, raw + err
    assert [f["t"] for f in out["frames"]] == [0, 1, 2, 3]
    assert out["grid"]["cols"] == 2 and out["grid"]["rows"] == 2
    sheet = Image.open(out["sheet"]).convert("RGB")
    for i, (_, rgb) in enumerate(COLORS):
        assert close(tile_center(sheet, out, i), rgb), i


def test_timecode_input_is_read_at_the_media_rate(tmp_path):
    m = color_media(tmp_path / "c.mp4")
    code, out, raw, err = skill("frames", "--media", str(m), "--at", "00:00:03:00", "--out", str(tmp_path / "s.png"), cwd=tmp_path)
    assert code == 0, raw + err
    assert out["frames"][0]["t"] == pytest.approx(3.0)
    assert close(tile_center(Image.open(out["sheet"]).convert("RGB"), out, 0), (255, 255, 0))


@needs_filmcraft
def test_project_mode_renders_through_filmcraft_and_cuts_list_each_shot(tmp_path):
    m = color_media(tmp_path / "c.mp4", size="1920x1080")
    p = tmp_path / "p.fcproj"
    item = json.loads(fc("--save-as", str(p), "import", str(m), cwd=tmp_path).stdout)["items"][0]
    # shots: blue (src 2 s) for 1 s, then red (src 0 s) for 1 s, then yellow (src 3 s) for 1 s
    res = fc_run([
        {"id": "file.newSequence", "params": {"name": "S", "fps": 30, "video": 1, "audio": 1}},
        {"id": "timeline.place", "params": {"item": item, "track": "V1", "frame": 0, "insert": False, "sourceIn": TICKS * 2, "duration": TICKS}},
        {"id": "timeline.place", "params": {"item": item, "track": "V1", "frame": 30, "insert": False, "sourceIn": 0, "duration": TICKS}},
        {"id": "timeline.place", "params": {"item": item, "track": "V1", "frame": 60, "insert": False, "sourceIn": TICKS * 3, "duration": TICKS}},
    ], p, cwd=tmp_path)
    assert all(l["ok"] for l in res), res
    code, out, raw, err = skill("frames", "--project", str(p), "--cuts", "--out", str(tmp_path / "s.png"), cwd=tmp_path)
    assert code == 0, raw + err
    assert [f["tc"] for f in out["frames"]] == ["00:00:00:00", "00:00:01:00", "00:00:02:00"]
    sheet = Image.open(out["sheet"]).convert("RGB")
    for i, rgb in enumerate([(0, 0, 255), (255, 0, 0), (255, 255, 0)]):
        assert close(tile_center(sheet, out, i), rgb), i


@needs_filmcraft
def test_shorts_overlay_marks_the_ui_areas_on_a_vertical_frame(tmp_path):
    """Shorts margins on 1080x1920 (top, bottom, left, right): the overlay tints exactly those bands, and the safe box stays untouched."""
    gray = tmp_path / "g.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=0x808080:s=1080x1920:r=30:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "1", str(gray))
    p = tmp_path / "v.fcproj"
    item = json.loads(fc("--save-as", str(p), "import", str(gray), cwd=tmp_path).stdout)["items"][0]
    assert all(l["ok"] for l in fc_run([
        {"id": "file.newSequence", "params": {"name": "V", "width": 1080, "height": 1920, "fps": 30, "video": 1, "audio": 1}},
        {"id": "timeline.place", "params": {"item": item, "track": "V1", "frame": 0, "insert": False}},
    ], p, cwd=tmp_path))
    code, out, raw, err = skill("frames", "--project", str(p), "--at", "1", "--overlay", "shorts", "--width", "540", "--out", str(tmp_path / "s.png"), cwd=tmp_path)
    assert code == 0, raw + err
    sheet = Image.open(out["sheet"]).convert("RGB")
    top, bottom, left, right = (v / 2 for v in frames.SAFE_ZONES["shorts"]["margins"])  # tile is half size
    w, h = 540, 960
    inside = sheet.getpixel((int(left + 20), int(top + 20)))
    assert close(inside, (128, 128, 128), tol=12), inside
    for x, y in [(w // 2, int(top) - 6), (w // 2, int(h - bottom) + 6), (int(left) - 4, h // 2), (int(w - right) + 6, h // 2)]:
        assert not close(sheet.getpixel((x, y)), (128, 128, 128), tol=12), (x, y)


def test_overlay_on_a_landscape_frame_is_skipped_with_a_note(tmp_path):
    m = color_media(tmp_path / "c.mp4")
    code, out, raw, err = skill("frames", "--media", str(m), "--at", "1", "--overlay", "shorts", "--out", str(tmp_path / "s.png"), cwd=tmp_path)
    assert code == 0 and any("not vertical" in n for n in out["notes"])


def test_cuts_needs_a_project(tmp_path):
    m = color_media(tmp_path / "c.mp4")
    code, out, raw, err = skill("frames", "--media", str(m), "--cuts", "--out", str(tmp_path / "s.png"), cwd=tmp_path)
    assert code == 2


def test_too_many_frames_is_refused_with_the_count(tmp_path):
    m = color_media(tmp_path / "c.mp4")
    code, out, raw, err = skill("frames", "--media", str(m), "--every", "0.01", "--out", str(tmp_path / "s.png"), cwd=tmp_path)
    assert code == 2 and "400" in out["error"]


def test_help_names_modes_overlay_table_and_outputs():
    code, out, raw, err = skill("frames", "--help")
    assert code == 0
    for word in ("--project", "--media", "--at", "--cuts", "--every", "--overlay", "shorts", "reels", "tiktok", "Prints:", "Exits:", "file.saveCopy"):
        assert word in raw, word


@needs_filmcraft
def test_cuts_step_past_a_dissolve_to_show_the_shot_itself(tmp_path):
    """Blue then red with a 10-frame dissolve centred on frame 30 (frames 25..35): the red tile is frame 35, clear of the mix."""
    m = color_media(tmp_path / "c.mp4", size="1920x1080")
    p = tmp_path / "p.fcproj"
    item = json.loads(fc("--save-as", str(p), "import", str(m), cwd=tmp_path).stdout)["items"][0]
    res = fc_run([
        {"id": "file.newSequence", "params": {"name": "S", "fps": 30, "video": 1, "audio": 1}},
        {"id": "timeline.place", "params": {"item": item, "track": "V1", "frame": 0, "insert": False, "sourceIn": TICKS * 2, "duration": TICKS}},
        {"id": "timeline.place", "params": {"item": item, "track": "V1", "frame": 30, "insert": False, "sourceIn": 0, "duration": TICKS}},
    ], p, cwd=tmp_path)
    red = res[2]["result"]["clips"][0]
    assert fc_run([{"id": "sequence.applyVideoTransition", "params": {"clip": red, "edge": "in", "frames": 10}}], p, cwd=tmp_path)[0]["ok"]
    code, out, raw, err = skill("frames", "--project", str(p), "--cuts", "--out", str(tmp_path / "s.png"), cwd=tmp_path)
    assert code == 0, raw + err
    assert [f["tc"] for f in out["frames"]] == ["00:00:00:00", "00:00:01:05"]
    assert close(tile_center(Image.open(out["sheet"]).convert("RGB"), out, 1), (255, 0, 0))  # no blue left from the mix


@needs_filmcraft
def test_tiktok_overlay_shades_the_button_column_below_its_top(tmp_path):
    gray = tmp_path / "g.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=0x808080:s=1080x1920:r=30:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "1", str(gray))
    p = tmp_path / "v.fcproj"
    item = json.loads(fc("--save-as", str(p), "import", str(gray), cwd=tmp_path).stdout)["items"][0]
    assert all(l["ok"] for l in fc_run([
        {"id": "file.newSequence", "params": {"name": "V", "width": 1080, "height": 1920, "fps": 30, "video": 1, "audio": 1}},
        {"id": "timeline.place", "params": {"item": item, "track": "V1", "frame": 0, "insert": False}},
    ], p, cwd=tmp_path))
    code, out, raw, err = skill("frames", "--project", str(p), "--at", "1", "--overlay", "tiktok", "--width", "1080", "--out", str(tmp_path / "s.png"), cwd=tmp_path)
    assert code == 0, raw + err
    sheet = Image.open(out["sheet"]).convert("RGB")
    x0, y0, _, _ = frames.SAFE_ZONES["tiktok"]["extra"][0]
    assert close(sheet.getpixel((x0 - 30, y0 - 100)), (128, 128, 128), tol=12)      # inside the safe box, above the column
    assert not close(sheet.getpixel((x0 + 30, y0 + 100)), (128, 128, 128), tol=12)  # in the button column
