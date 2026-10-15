"""`timeline`: a cheap summary on stdout and every clip in a detail file, read from a project the real filmcraft-cli built. Expected timecodes come from the frames the project was built with, worked by hand at 29.97 fps (30 frames per timecode second)."""

from __future__ import annotations

import json

import pytest

from video import timecode
from support import FFMPEG, FILMCRAFT, TICKS, fc, fc_run, make_av, needs_filmcraft, skill


# -- timecode: the shared arithmetic every command reports in ------------------------------------------------------------

@pytest.mark.parametrize("frame, rate, drop, expected", [
    (0, (30000, 1001), False, "00:00:00:00"),
    (90, (30000, 1001), False, "00:00:03:00"),
    (1799, (30000, 1001), False, "00:00:59:29"),
    (1800, (30000, 1001), True, "00:01:00;02"),     # SMPTE 12M: minute 1 starts at frame 1800 and skips ;00 and ;01
    (17982, (30000, 1001), True, "00:10:00;00"),    # every tenth minute keeps its first two numbers
    (24, (24000, 1001), False, "00:00:01:00"),
    (25 * 3600, (25, 1), False, "01:00:00:00"),
])
def test_timecode_from_frame(frame, rate, drop, expected):
    assert timecode.Rate(*rate).timecode(frame, drop=drop) == expected


def test_ticks_frames_round_trip_at_ntsc():
    r = timecode.Rate(30000, 1001)
    # one 29.97 frame is 1001/30000 s = 254 016 000 000 × 1001 / 30000 = 8 475 667 200 ticks
    assert r.tick_of(1) == 8_475_667_200
    assert r.frame_at(8_475_667_199) == 0 and r.frame_at(8_475_667_200) == 1
    # a rate whose frame is not a whole number of ticks starts each frame at the ceiling, so frame_at(tick_of(f)) == f
    odd = timecode.Rate(37516, 1000)
    assert all(odd.frame_at(odd.tick_of(f)) == f for f in range(0, 2000, 7))
    assert r.frame_at(TICKS * 3) == 89  # 3.000 s falls inside frame 89 (89.91)


# -- the command --------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """V1: a [0,90) and b [90,210) from b's 2 s, with a 10-frame dissolve centred on the cut; V2: a's 5 s..7 s at frame 30, video only, then sped to 200 %; A2: b's sound alone at frame 150 for 45 frames. Six clips: V1 a, V1 b, their linked A1 halves, V2, A2."""
    if FILMCRAFT is None or FFMPEG is None:
        pytest.skip("filmcraft-cli and ffmpeg are needed")
    d = tmp_path_factory.mktemp("timeline")
    make_av(d / "a.mp4", 12)
    make_av(d / "b.mp4", 12, src="smptehdbars", tone=660)
    p = d / "p.fcproj"
    r = fc("--save-as", str(p), "import", str(d / "a.mp4"), str(d / "b.mp4"), cwd=d)
    items = json.loads(r.stdout)["items"]
    a, b = items
    res = fc_run([
        {"id": "file.newSequence", "params": {"name": "Main", "fps": 29.97, "video": 3, "audio": 3}},
        {"id": "timeline.place", "params": {"item": a, "track": "V1", "frame": 0, "insert": False, "sourceIn": 0, "duration": TICKS * 3}},
        {"id": "timeline.place", "params": {"item": b, "track": "V1", "frame": 90, "insert": False, "sourceIn": TICKS * 2, "duration": TICKS * 4}},
        {"id": "timeline.place", "params": {"item": a, "track": "V2", "frame": 30, "insert": False, "sourceIn": TICKS * 5, "duration": TICKS * 2, "audio": False}},
        {"id": "timeline.place", "params": {"item": b, "track": "A2", "frame": 150, "insert": False, "sourceIn": 0, "duration": TICKS * 45 * 1001 // 30000, "video": False}},
        {"id": "markers.add", "params": {"time": TICKS * 4, "name": "Chapter A"}},
    ], p, cwd=d)
    b_clip = res[2]["result"]["clips"][0]
    assert all(l["ok"] for l in res), res
    v2 = res[3]["result"]["clips"][0]
    seq = res[0]["result"]["sequence"]
    res = fc_run([
        {"id": "clip.speedDuration", "params": {"clips": [v2], "speed": 200}},
        {"id": "sequence.applyVideoTransition", "params": {"clip": b_clip, "edge": "in", "frames": 10}},
    ], p, cwd=d)
    assert all(l["ok"] for l in res), res
    return d, p, seq


@needs_filmcraft
def test_detail_timecodes_match_the_frames_built(built):
    d, p, _ = built
    code, out, raw, err = skill("timeline", "--project", str(p), "--out", str(d / "detail.json"), cwd=d)
    assert code == 0, err
    detail = json.loads((d / "detail.json").read_text())
    got = sorted((c["track"], c["start_tc"], c["end_tc"]) for c in detail["clips"])
    assert got == sorted([
        ("V1", "00:00:00:00", "00:00:03:00"), ("A1", "00:00:00:00", "00:00:03:00"),
        ("V1", "00:00:03:00", "00:00:07:00"), ("A1", "00:00:03:00", "00:00:07:00"),
        ("V2", "00:00:01:00", "00:00:02:00"),   # 60 frames of source at 200 % fill 30
        ("A2", "00:00:05:00", "00:00:06:15"),
    ])
    v2 = next(c for c in detail["clips"] if c["track"] == "V2")
    assert v2["speed"] == 2.0 and v2["src_in_s"] == pytest.approx(5.0, abs=1e-3)
    b = next(c for c in detail["clips"] if c["track"] == "V1" and c["start_tc"] == "00:00:03:00")
    assert b["src_in_s"] == pytest.approx(2.0, abs=1e-3)
    [x] = detail["transitions"]
    assert (x["track"], x["start_tc"], x["end_tc"]) == ("V1", "00:00:02:25", "00:00:03:05")  # 10 frames centred on frame 90: 85..95
    [m] = detail["markers"]
    assert (m["name"], m["start_tc"]) == ("Chapter A", "00:00:03:29")  # 4.000 s lies inside frame 119 (119.88)


@needs_filmcraft
def test_summary_is_cheap_and_counts_what_is_there(built):
    d, p, _ = built
    code, out, raw, err = skill("timeline", "--project", str(p), "--out", str(d / "detail2.json"), cwd=d)
    assert code == 0, err
    s = out["summary"]
    assert s["name"] == "Main" and s["fps"] == "29.97" and s["size"] == "1920x1080"
    assert s["duration_tc"] == "00:00:07:00"
    assert s["clips"] == 6 and s["markers"] == 1 and s["captions"] == 0 and s["transitions"] == 1
    assert [t["name"] for t in s["tracks"] if t["clips"]] == ["V1", "V2", "A1", "A2"]
    assert out["detail"] == str(d / "detail2.json")


@needs_filmcraft
def test_three_hundred_clips_keep_stdout_small_and_detail_complete(tmp_path):
    make_av(tmp_path / "a.mp4", 4, audio=False)
    p = tmp_path / "p.fcproj"
    item = json.loads(fc("--save-as", str(p), "import", str(tmp_path / "a.mp4"), cwd=tmp_path).stdout)["items"][0]
    lines = [{"id": "file.newSequence", "params": {"name": "Long", "fps": 30, "video": 1, "audio": 1}}]
    lines += [{"id": "timeline.place", "params": {"item": item, "track": "V1", "frame": i * 10, "insert": False, "sourceIn": 0, "duration": TICKS // 3, "audio": False}} for i in range(300)]
    assert all(l["ok"] for l in fc_run(lines, p, cwd=tmp_path))
    code, out, raw, err = skill("timeline", "--project", str(p), "--out", str(tmp_path / "d.json"), cwd=tmp_path)
    assert code == 0, err
    assert len(raw.encode()) <= 2048
    assert out["summary"]["clips"] == 300
    assert len(json.loads((tmp_path / "d.json").read_text())["clips"]) == 300


@needs_filmcraft
def test_named_sequence_and_captions_are_read(built, tmp_path):
    d, p, seq = built
    srt = d / "c.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\n하나\n\n2\n00:00:03,000 --> 00:00:04,000\n둘\n", encoding="utf-8")
    copy = d / "with_captions.fcproj"
    fc("--save-as", str(copy), "exec", "captions.import", f"path={srt}", project=p, cwd=d)
    code, out, raw, err = skill("timeline", "--project", str(copy), "--sequence", str(seq), "--out", str(d / "d3.json"), cwd=d)
    assert code == 0, err
    assert out["summary"]["captions"] == 2
    cap = json.loads((d / "d3.json").read_text())["captions"]
    assert cap[0]["track"] == "C1" and cap[0]["cues"] == 2 and cap[0]["font"] == "Inter"


def test_project_and_bridge_together_is_a_usage_error(tmp_path):
    code, out, raw, err = skill("timeline", "--project", "x.fcproj", "--bridge", "127.0.0.1:9876", "--out", "d.json", cwd=tmp_path)
    assert code == 2


def test_neither_project_nor_bridge_is_a_usage_error(tmp_path):
    code, *_ = skill("timeline", "--out", "d.json", cwd=tmp_path)
    assert code == 2


@needs_filmcraft
def test_a_missing_project_fails_with_the_tools_message(tmp_path):
    code, out, raw, err = skill("timeline", "--project", str(tmp_path / "nope.fcproj"), "--out", str(tmp_path / "d.json"), cwd=tmp_path)
    assert code == 1
    assert out["error"] and "nope.fcproj" in json.dumps(out)


def test_help_explains_arguments_output_and_failures():
    code, out, raw, err = skill("timeline", "--help")
    assert code == 0
    for word in ("--project", "--bridge", "--sequence", "--out", "Prints:", "Exits:", "end_tc"):
        assert word in raw, word


def test_drop_frame_timecode_reads_back_to_the_frame_it_names():
    """SMPTE 12M: one hour of 29.97 drop-frame is frame 107892; ten minutes is 17982."""
    r = timecode.Rate(30000, 1001)
    assert r.frame_of_timecode("01:00:00;00", drop=True) == 107892
    assert r.frame_of_timecode("00:10:00;00", drop=True) == 17982
    assert r.frame_of_timecode("00:01:00;02", drop=True) == 1800
    assert r.frame_of_timecode("00:00:03:00", drop=False) == 90
    assert all(r.frame_of_timecode(r.timecode(f, drop=True), drop=True) == f for f in range(0, 40000, 37))


def test_three_digit_frame_fields_at_120_fps_read_back():
    for rate, drop in ((timecode.Rate(120000, 1001), True), (timecode.Rate(120), False)):
        assert all(rate.frame_of_timecode(rate.timecode(f, drop=drop), drop=drop) == f for f in range(0, 30000, 113))
