"""FilmCraft behaviour the skill's prose relies on, checked against the installed filmcraft-cli. FilmCraft ships every day or two; when one of these fails after an update, the SKILL.md sentence (or `graphic --help` passage) named in its docstring is the one to rewrite (or delete), not the test to loosen.

Run after an update: `uv run --with pytest --with pillow pytest tests/filmcraft_facts`."""

from __future__ import annotations

import json
import math
import re
import subprocess
from fractions import Fraction

import pytest
from PIL import Image

from video import ffmpeg as ff, mp4
from support import FFMPEG, TICKS, fc, fc_json, fc_run, ffmpeg, make_av, needs_ffmpeg, needs_filmcraft

pytestmark = [needs_filmcraft, needs_ffmpeg]


@pytest.fixture
def proj(tmp_path):
    """A 12 s, 640x360, 30 fps movie with a 440 Hz tone, imported as item 1 into p.fcproj, with a sequence made from it (V1/A1 clips 6 and 7)."""
    make_av(tmp_path / "a.mp4", 12, rate="30", size="640x360")
    p = tmp_path / "p.fcproj"
    fc("--save-as", str(p), "import", str(tmp_path / "a.mp4"), cwd=tmp_path)
    fc("--save", "exec", "file.newSequenceFromClip", "items=[1]", project=p, cwd=tmp_path)
    return tmp_path, p


def seq(p, d):
    return fc_json("inspect", "sequence", project=p, cwd=d)


def words_line(item, spec):
    return {"id": "transcript.set", "params": {"item": item, "transcript": {"language": "ko", "speakers": [], "words": [
        {"text": t, "start": int(a * TICKS), "end": int(b * TICKS)} for t, a, b in spec]}}}


# -- How the CLI fails quietly -------------------------------------------------------------------------------------------

def test_01_an_edit_without_save_is_gone_next_call(proj):
    """SKILL.md › How the CLI fails quietly: every call is a new session; without --save the edit disappears."""
    d, p = proj
    r = fc_json("exec", "markers.add", "name=lost", project=p, cwd=d)
    assert "marker" in r
    assert seq(p, d)["markers"] == []


def test_02_a_run_with_a_failing_line_saves_nothing(proj):
    """SKILL.md › How the CLI fails quietly: a `run` stops at the first failing line before saving (unless --keep-going)."""
    d, p = proj
    rows = fc_run([{"id": "markers.add", "params": {"name": "kept?"}}, {"id": "nope.command", "params": {}}], p, save=True, cwd=d, check=False)
    assert rows[0]["ok"] and not rows[1]["ok"]
    assert seq(p, d)["markers"] == []


def test_03_an_unknown_option_is_ignored_and_the_session_is_empty(proj):
    """SKILL.md › How the CLI fails quietly: an unknown option (other than under `mcp`) is ignored without an error, so a misspelt --bridge runs on an empty headless session."""
    d, p = proj
    r = fc("--brige=127.0.0.1:9", "inspect", "project", cwd=d)
    assert r.returncode == 0
    assert json.loads(r.stdout)["path"] is None and json.loads(r.stdout)["root"]["children"] == []


def test_04_a_float_time_is_ignored(proj):
    """SKILL.md › How the CLI fails quietly: `time` takes integer ticks; a float there is silently treated as absent (`razor` then reports cuts:0)."""
    d, p = proj
    assert fc_json("exec", "timeline.razor", '{"time": 3.5}', project=p, cwd=d) == {"cuts": 0}
    assert fc_json("exec", "timeline.razor", '{"seconds": 3.5}', project=p, cwd=d)["cuts"] == 2


def test_14_sequence_from_clip_makes_only_the_tracks_it_needs(proj):
    """SKILL.md › How the CLI fails quietly: file.newSequenceFromClip makes only V1/A1, so placing on V2 needs sequence.addTracks first."""
    d, p = proj
    s = seq(p, d)
    assert (len(s["video"]), len(s["audio"])) == (1, 1)


def test_16_audio_gain_adjusts_by_default(proj):
    """SKILL.md › How the CLI fails quietly: clip.audioGain without `mode` adds to the current gain (adjust), so -6 twice is -12."""
    d, p = proj
    rows = fc_run([{"id": "clip.audioGain", "params": {"clips": [7], "db": -6}}, {"id": "clip.audioGain", "params": {"clips": [7], "db": -6}},
                   {"id": "sequence.inspect", "params": {}}], p, save=False, cwd=d)
    [clip] = [c for t in rows[-1]["result"]["audio"] for c in t["items"] if c["clip"] == 7]
    assert clip["gainDb"] == pytest.approx(-12.0)


# -- Speech as material --------------------------------------------------------------------------------------------------

def test_11_this_build_cannot_transcribe(proj):
    """SKILL.md › Speech as material: the release build has no speech-to-text and cannot download models; transcripts come in through transcript.set."""
    d, p = proj
    assert fc_json("describe", "transcript.generate", cwd=d)["enabled"] is False
    r = fc("exec", "transcript.downloadModel", project=p, cwd=d, check=False)
    assert r.returncode != 0 and "not available" in r.stderr


def test_08_remove_pauses_keeps_keep_on_both_sides_snapped_inward(proj):
    """SKILL.md › Speech as material: removePauses leaves `keepSeconds` on each side of every pause of at least `minSeconds`, removing [ceil-to-frame(end + keep), floor-to-frame(next start - keep)) and skipping it when that is empty. Expected frames are computed here from that rule."""
    d, p = proj
    spec = [("가", 0.10, 0.50), ("나", 2.013, 2.40), ("다", 2.45, 2.80), ("라", 3.40, 3.70), ("마", 4.20, 4.50), ("바", 4.85, 5.00), ("사", 5.49, 5.70), ("아", 8.00, 8.40)]
    keep, minimum = Fraction(15, 100), Fraction(1, 2)
    removed = 0
    for (_, _, a), (_, b, _) in zip(spec, spec[1:]):
        a, b = Fraction(a).limit_denominator(1000), Fraction(b).limit_denominator(1000)
        if b - a < minimum:
            continue
        s2, e2 = math.ceil((a + keep) * 30), math.floor((b - keep) * 30)
        removed += max(e2 - s2, 0)
    before = seq(p, d)["durationFrames"]
    rows = fc_run([words_line(1, spec), {"id": "transcript.removePauses", "params": {"minSeconds": 0.5, "keepSeconds": 0.15}},
                   {"id": "sequence.inspect", "params": {}}, {"id": "transcript.inspect", "params": {}}], p, save=False, cwd=d)
    assert rows[-2]["result"]["durationFrames"] == before - removed
    ws = rows[-1]["result"]["words"]
    for x, y in zip(ws, ws[1:]):
        gap = (y["start"] - x["end"]) / TICKS
        assert gap >= 0 and (gap >= 0.3 - 1 / 30 or gap < 0.5), (x["text"], y["text"], gap)


def test_09_create_captions_joins_sentences_and_fills_english_length_lines(proj):
    """SKILL.md › Speech as material: transcript.createCaptions fills lines greedily to 42 characters (an English length) and ends a block at a sentence end only once the block is half full, so a short sentence runs on into the next one's cue."""
    d, p = proj
    text = "네. 그래서 오늘은 여러분과 함께 자막을 만드는 방법을 처음부터 끝까지 차근차근 살펴보려고 합니다. 먼저 전사를 확인합니다."
    spec = [(w, 0.3 + i * 0.4, 0.65 + i * 0.4) for i, w in enumerate(text.split())]
    rows = fc_run([words_line(1, spec), {"id": "transcript.createCaptions", "params": {}}, {"id": "captions.list", "params": {}}], p, save=False, cwd=d)
    cues = [c["text"] for c in rows[-1]["result"]["tracks"][0]["captions"]]
    assert cues[0].startswith("네. 그래서")                       # the one-word sentence did not end its cue
    assert max(len(line) for c in cues for line in c.split("\n")) > 30


def test_10_import_is_lenient_and_add_refuses_overlap(proj):
    """SKILL.md › Speech as material: captions.import accepts overlapping and too-short cues (cutting and stretching them, no warning); captions.add and setTimes refuse a time another caption covers."""
    d, p = proj
    srt = d / "ov.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:03,000\na\n\n2\n00:00:02,000 --> 00:00:04,000\nb\n\n3\n00:00:04,000 --> 00:00:04,020\nc\n", encoding="utf-8")
    imp = fc_json("exec", "captions.import", f"path={srt}", project=p, cwd=d)
    assert imp["captions"] == 3 and imp["warnings"] == []
    rows = fc_run([{"id": "captions.newTrack", "params": {"format": "Subtitle"}}, {"id": "captions.add", "params": {"text": "a", "seconds": 1, "durationSeconds": 2}},
                   {"id": "captions.add", "params": {"text": "b", "seconds": 2, "durationSeconds": 2}}], p, save=False, cwd=d, check=False)
    assert rows[1]["ok"] and not rows[2]["ok"] and "already covers" in rows[2]["error"]


# -- On-screen text ------------------------------------------------------------------------------------------------------

def caption_project(d, size, srt_text, style=None):
    white = d / f"w{size}.mp4"
    ffmpeg("-f", "lavfi", "-i", f"color=c=white:s={size}:r=30:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(white))
    p = d / f"c{size}.fcproj"
    item = json.loads(fc("--save-as", str(p), "import", str(white), cwd=d).stdout)["items"][0]
    srt = d / "c.srt"
    srt.write_text(srt_text, encoding="utf-8")
    lines = [{"id": "file.newSequenceFromClip", "params": {"items": [item]}}, {"id": "captions.import", "params": {"path": str(srt)}},
             {"id": "captions.setStyle", "params": {"track": "C1", "background": True, "backgroundColor": "#000000ff", **(style or {})}}]
    assert all(r["ok"] for r in fc_run(lines, p, cwd=d))
    return p


def box_height(png) -> int:
    img = Image.open(png).convert("RGB")
    w, h = img.size
    px = img.load()
    rows = [y for y in range(h) if sum(1 for x in range(0, w, 2) if max(px[x, y]) < 30) >= 10]
    return rows[-1] - rows[0] + 1 if rows else 0


def test_05_default_caption_font_is_inter_and_has_no_hangul(tmp_path):
    """SKILL.md › On-screen text: captions (and text layers) default to Inter, which has no Hangul; set a Korean family on every caption track and text layer."""
    srt = "1\n00:00:01,000 --> 00:00:03,000\n한글 자막\n"
    p = caption_project(tmp_path, "640x360", srt)
    assert fc_json("exec", "captions.list", project=p, cwd=tmp_path)["tracks"][0]["style"]["font"] == "Inter"
    fc("render", "--seconds", "2", "--out", str(tmp_path / "inter.png"), project=p, cwd=tmp_path)
    fc("--save", "exec", "captions.setStyle", "track=C1", "font=Apple SD Gothic Neo", project=p, cwd=tmp_path)
    fc("render", "--seconds", "2", "--out", str(tmp_path / "ko.png"), project=p, cwd=tmp_path)
    a, b = Image.open(tmp_path / "inter.png").convert("L"), Image.open(tmp_path / "ko.png").convert("L")
    diff = sum(1 for x, y in zip(a.tobytes(), b.tobytes()) if abs(x - y) > 60)
    assert diff > 200  # the default face draws placeholder boxes where the Korean face draws Hangul


def test_12_caption_size_scales_with_frame_height(tmp_path):
    """SKILL.md › On-screen text: caption `size` is relative to a 1080-line frame, so the same size is 1920/1080 = 1.78 times taller in a 1080x1920 frame (\"far bigger in a vertical frame\")."""
    srt = "1\n00:00:01,000 --> 00:00:03,000\n자막\n"
    hs = {}
    for size in ("1920x1080", "1080x1920"):
        p = caption_project(tmp_path, size, srt, {"font": "Apple SD Gothic Neo", "size": 54})
        fc("render", "--seconds", "2", "--out", str(tmp_path / f"{size}.png"), project=p, cwd=tmp_path)
        hs[size] = box_height(tmp_path / f"{size}.png")
    assert hs["1080x1920"] / hs["1920x1080"] == pytest.approx(1920 / 1080, rel=0.05)


# -- Seeing and hearing the edit, Delivery -------------------------------------------------------------------------------

def test_06_export_does_not_burn_captions_unless_asked(tmp_path):
    """SKILL.md › Seeing and hearing the edit: `render` draws captions, but file.exportMedia burns them only with burnCaptions:true."""
    p = caption_project(tmp_path, "640x360", "1\n00:00:00,000 --> 00:00:04,000\n자막\n", {"font": "Apple SD Gothic Neo"})
    fc("render", "--seconds", "2", "--out", str(tmp_path / "r.png"), project=p, cwd=tmp_path)
    assert box_height(tmp_path / "r.png") > 0
    for burn in (False, True):
        out = tmp_path / f"e{burn}.mp4"
        fc("exec", "file.exportMedia", json.dumps({"path": str(out), "format": "h264", "range": "entire", "burnCaptions": burn, "wait": True}), project=p, cwd=tmp_path)
        ff.extract_frame(out, 2.0, tmp_path / f"e{burn}.png", 640)
        assert (box_height(tmp_path / f"e{burn}.png") > 0) is burn


def test_07_export_defaults_to_the_in_out_range(proj):
    """SKILL.md › Delivery: without a range, export renders In to Out when marks are set (Mark Out includes its frame), so say range entire."""
    d, p = proj
    fc_run([{"id": "markers.markIn", "params": {"seconds": 1}}, {"id": "markers.markOut", "params": {"seconds": 3}}], p, cwd=d)
    fc("export", str(d / "io.mp4"), project=p, cwd=d)
    fc("exec", "file.exportMedia", json.dumps({"path": str(d / "all.mp4"), "format": "h264", "range": "entire", "wait": True}), project=p, cwd=d)
    assert ff.probe(d / "io.mp4").duration == pytest.approx(61 / 30, abs=0.05)
    assert ff.probe(d / "all.mp4").duration == pytest.approx(12.0, abs=0.05)


def test_13_mp4_has_moov_at_the_end_and_an_edit_list(proj):
    """SKILL.md › Delivery: FilmCraft's MP4 puts moov after mdat and writes an edit list; a lossless `-c copy -movflags +faststart` remux fixes the first, the second is left alone."""
    d, p = proj
    fc("export", str(d / "o.mp4"), "--range", "entire", project=p, cwd=d)
    lay = mp4.layout(d / "o.mp4")
    assert lay.moov_first is False and lay.has_elst is True


def test_15_loudness_target_is_met(proj):
    """SKILL.md › Delivery: file.exportMedia loudnessLufs normalises the mix (BS.1770, true-peak limited) to within half an LU of the target."""
    d, p = proj
    out = d / "l.mp4"
    fc("exec", "file.exportMedia", json.dumps({"path": str(out), "format": "h264", "range": "entire", "loudnessLufs": -14, "wait": True}), project=p, cwd=d)
    assert ff.loudness(out).integrated == pytest.approx(-14.0, abs=0.5)


# -- Command families by job ---------------------------------------------------------------------------------------------

def test_17_narration_speaks_english_only(proj):
    """SKILL.md › Command families by job: tts voices are English (en-US); Korean text is refused ("nothing to say"), so Korean narration has to come from elsewhere."""
    d, p = proj
    voices = fc_json("exec", "tts.voices", cwd=d)
    assert [l["id"] for l in voices["languages"]] == ["en-US"]
    r = fc("exec", "tts.preview", json.dumps({"text": "안녕하세요 반갑습니다", "path": str(d / "ko.wav")}), cwd=d, check=False)
    assert r.returncode != 0 and "nothing to say" in r.stderr


def test_18_headless_export_without_wait_writes_nothing(proj):
    """SKILL.md › How the CLI fails quietly: `exec file.exportMedia` returns a job id at once (wait defaults to false) and the headless process exits with it, so no file is written; pass wait:true, or use the `export` subcommand, which waits."""
    d, p = proj
    r = fc_json("exec", "file.exportMedia", json.dumps({"path": str(d / "nowait.mp4"), "format": "h264", "range": "entire"}), project=p, cwd=d)
    assert "job" in r
    assert not (d / "nowait.mp4").exists()


def test_19_loudness_normalisation_limits_true_peak_at_minus_2_unless_told(tmp_path):
    """SKILL.md › Delivery: loudnessLufs normalises under a -2 dBTP limiter, so a peaky mix can land short; `settings.effects.loudness` (the form `export --settings` accepts) sets the target and the ceiling. `export --settings` refuses a top-level loudnessLufs. AAC adds true peak above the PCM ceiling."""
    wave = "0.7*sin(2*PI*60*t)*exp(-25*mod(t\\,0.5))+0.15*sin(2*PI*440*t)*exp(-8*mod(t\\,0.5))"
    ffmpeg("-f", "lavfi", "-i", "color=c=gray:s=320x180:r=30:d=8", "-f", "lavfi", "-i", f"aevalsrc={wave}|{wave}:s=48000:d=8",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(tmp_path / "kick.mp4"))
    p = tmp_path / "k.fcproj"
    fc("--save-as", str(p), "import", str(tmp_path / "kick.mp4"), cwd=tmp_path)
    fc("--save", "exec", "file.newSequenceFromClip", "items=[1]", project=p, cwd=tmp_path)
    fc("exec", "file.exportMedia", json.dumps({"path": str(tmp_path / "a.mp4"), "format": "h264", "range": "entire", "loudnessLufs": -14, "wait": True}), project=p, cwd=tmp_path)
    a = ff.loudness(tmp_path / "a.mp4")
    assert a.true_peak <= -1.9 and a.integrated < -14.5
    r = fc("export", str(tmp_path / "x.mp4"), "--range", "entire", "--settings", '{"loudnessLufs": -14}', project=p, cwd=tmp_path, check=False)
    assert r.returncode != 0 and "loudnessLufs" in r.stderr
    fc("export", str(tmp_path / "b.mp4"), "--range", "entire", "--settings", '{"effects": {"loudness": {"enabled": true, "target_lufs": -14, "true_peak_dbtp": -1}}}', project=p, cwd=tmp_path)
    b = ff.loudness(tmp_path / "b.mp4")
    assert -1.3 <= b.true_peak <= -0.3 and b.integrated > a.integrated
    # the limiter holds its ceiling on PCM; the AAC encode is what adds true peak above it
    fc("exec", "file.exportMedia", json.dumps({"path": str(tmp_path / "c.wav"), "format": "wav", "range": "entire", "loudnessLufs": -14, "wait": True}), project=p, cwd=tmp_path)
    assert ff.loudness(tmp_path / "c.wav").true_peak <= -1.9


# -- Graphics ------------------------------------------------------------------------------------------------------------

def srgb_to_linear(v: float) -> float:
    """IEC 61966-2-1 decoding, 0–255 code value to linear light 0–1."""
    c = v / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(l: float) -> float:
    c = 12.92 * l if l <= 0.0031308 else 1.055 * l ** (1 / 2.4) - 0.055
    return c * 255


def prores_4444(path, seconds, color="red@0.5", size="640x360", tone_hz=None, rate="30"):
    """A straight-alpha ProRes 4444 MOV like the ones `graphic` writes, optionally with a sine (amplitude 1/8) as 48 kHz PCM."""
    args = ["-f", "lavfi", "-i", f"color=c={color}:s={size}:r={rate}:d={seconds},format=rgba"]
    if tone_hz:
        args += ["-f", "lavfi", "-i", f"sine=frequency={tone_hz}:sample_rate=48000:duration={seconds}", "-c:a", "pcm_s16le", "-shortest"]
    ffmpeg(*args, "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", str(path))
    return path


def tracks(p, d) -> dict:
    """{"V1": [(name, start_s, end_s)], "A1": [...]} for the active sequence."""
    s = seq(p, d)
    return {f"{k[0].upper()}{i + 1}": [(c["name"], round(c["start"] / TICKS, 3), round(c["end"] / TICKS, 3)) for c in t["items"]]
            for k in ("video", "audio") for i, t in enumerate(s[k])}


def peak_db(path, start, seconds) -> float:
    """Sample peak in dBFS of [start, start + seconds) (ffmpeg volumedetect); -91 stands for digital silence."""
    r = subprocess.run([FFMPEG, "-v", "info", "-ss", str(start), "-t", str(seconds), "-i", str(path), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True, timeout=120)
    m = re.search(r"max_volume: (-?[\d.]+|-inf) dB", r.stderr)
    return -91.0 if m is None or m.group(1) == "-inf" else float(m.group(1))


def centre(png) -> tuple:
    img = Image.open(png).convert("RGB")
    return img.getpixel((img.width // 2, img.height // 2))


def test_20_compositing_is_in_linear_light(tmp_path):
    """SKILL.md › Graphics and motion graphics: FilmCraft composites in linear light, so a partly transparent layer comes out lighter over a dark picture than in a browser or an ffmpeg (sRGB) blend; judge how a graphic sits from a FilmCraft render. Expected: 50 % red over the measured background, blended in linear light by the sRGB transfer function (an sRGB blend would give about (128, 0, 127))."""
    ffmpeg("-f", "lavfi", "-i", "color=c=0x0000ff:s=640x360:r=30:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", str(tmp_path / "blue.mp4"))
    Image.new("RGBA", (640, 360), (255, 0, 0, 128)).save(tmp_path / "red50.png")
    p = tmp_path / "p.fcproj"
    fc("--save-as", str(p), "import", str(tmp_path / "blue.mp4"), str(tmp_path / "red50.png"), cwd=tmp_path)
    fc("--save", "exec", "file.newSequenceFromClip", "items=[1]", project=p, cwd=tmp_path)
    fc("render", "--seconds", "1", "--out", str(tmp_path / "bg.png"), project=p, cwd=tmp_path)
    fc_run([{"id": "timeline.place", "params": {"item": 2, "track": "new", "seconds": 0, "duration": 4 * TICKS}}], p, cwd=tmp_path)
    fc("render", "--seconds", "1", "--out", str(tmp_path / "r.png"), project=p, cwd=tmp_path)
    a = 128 / 255
    expected = [linear_to_srgb(a * srgb_to_linear(fg) + (1 - a) * srgb_to_linear(bg)) for fg, bg in zip((255, 0, 0), centre(tmp_path / "bg.png"))]
    got = centre(tmp_path / "r.png")
    assert all(abs(g - e) <= 2 for g, e in zip(got, expected)), (got, expected)
    assert got[0] > 128 + 40  # far from the sRGB blend


def test_21_placing_media_with_sound_overwrites_the_targeted_audio_track(tmp_path):
    """SKILL.md › How the CLI fails quietly: `timeline.place` puts a clip's sound on the targeted audio track (A1 by default), overwriting the speech there, unless `audioTrack` names another; `"audioTrack": "new"` leaves A1 whole, and `graphics.newFromFile` places the picture without its sound."""
    make_av(tmp_path / "talk.mp4", 4, rate="30", size="640x360")
    prores_4444(tmp_path / "g.mov", 3, tone_hz=1000)

    def setup(name):
        p = tmp_path / f"{name}.fcproj"
        fc("--save-as", str(p), "import", str(tmp_path / "talk.mp4"), str(tmp_path / "g.mov"), cwd=tmp_path)
        fc("--save", "exec", "file.newSequenceFromClip", "items=[1]", project=p, cwd=tmp_path)
        return p

    p = setup("default")
    fc_run([{"id": "timeline.place", "params": {"item": 2, "track": "new", "seconds": 0.5}}], p, cwd=tmp_path)
    t = tracks(p, tmp_path)
    assert t["V2"] == [("g.mov", 0.5, 3.5)]
    assert t["A1"] == [("talk.mp4", 0.0, 0.5), ("g.mov", 0.5, 3.5), ("talk.mp4", 3.5, 4.0)]

    p = setup("new_audio")
    fc_run([{"id": "timeline.place", "params": {"item": 2, "track": "new", "audioTrack": "new", "seconds": 0.5}}], p, cwd=tmp_path)
    t = tracks(p, tmp_path)
    assert t["A1"] == [("talk.mp4", 0.0, 4.0)] and t["A2"] == [("g.mov", 0.5, 3.5)]

    p = setup("graphics")
    fc_run([{"id": "graphics.newFromFile", "params": {"path": str(tmp_path / "g.mov"), "time": TICKS // 2}}], p, cwd=tmp_path)
    t = tracks(p, tmp_path)
    assert t["V2"] == [("g.mov", 0.5, 3.5)] and t["A1"] == [("talk.mp4", 0.0, 4.0)] and "A2" not in t


def test_22_a_file_rewritten_at_the_same_path_is_read_anew(tmp_path):
    """SKILL.md › Graphics and motion graphics: re-render a graphic to the same path and the project plays the new render; headless `render` and `export` read the file as it is now, not a cached copy."""
    ffmpeg("-f", "lavfi", "-i", "color=c=black:s=640x360:r=30:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(tmp_path / "bg.mp4"))
    prores_4444(tmp_path / "g.mov", 2, color="0x2030C0")
    p = tmp_path / "p.fcproj"
    fc("--save-as", str(p), "import", str(tmp_path / "bg.mp4"), str(tmp_path / "g.mov"), cwd=tmp_path)
    fc("--save", "exec", "file.newSequenceFromClip", "items=[1]", project=p, cwd=tmp_path)
    fc_run([{"id": "timeline.place", "params": {"item": 2, "track": "new", "audioTrack": "new", "seconds": 0}}], p, cwd=tmp_path)
    fc("render", "--seconds", "1", "--out", str(tmp_path / "a.png"), project=p, cwd=tmp_path)
    prores_4444(tmp_path / "g.mov", 2, color="0xC80000")
    fc("render", "--seconds", "1", "--out", str(tmp_path / "b.png"), project=p, cwd=tmp_path)
    a, b = centre(tmp_path / "a.png"), centre(tmp_path / "b.png")
    assert a[2] > 150 and a[0] < 60
    assert b[0] > 150 and b[2] < 60
    fc("export", str(tmp_path / "e.mp4"), "--range", "entire", project=p, cwd=tmp_path)
    ff.extract_frame(tmp_path / "e.mp4", 1.0, tmp_path / "e.png", 640)
    e = centre(tmp_path / "e.png")
    assert e[0] > 150 and e[2] < 60


def test_23_a_placed_clip_keeps_the_length_and_streams_read_at_import(tmp_path):
    """`graphic --help` and its `next` (re-placing after a re-render): the project keeps the length and sound streams it read when the file was imported. Rewritten at the same path, a longer render still plays only the old length, a shorter one holds its last frame to the old end with its sound silent there, sound added to a silent render is not heard (no sound clip was made), and a render that lost its sound plays silence; `media.refreshChanged` changes none of it. So a placed render whose length or sound changed is cleared and placed again."""
    ffmpeg("-f", "lavfi", "-i", "color=c=black:s=640x360:r=30:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(tmp_path / "bg.mp4"))

    def place(name, seconds, tone):
        g = prores_4444(tmp_path / f"{name}.mov", seconds, color="red", tone_hz=1000 if tone else None)
        p = tmp_path / f"{name}.fcproj"
        fc("--save-as", str(p), "import", str(tmp_path / "bg.mp4"), str(g), cwd=tmp_path)
        fc("--save", "exec", "file.newSequenceFromClip", "items=[1]", project=p, cwd=tmp_path)
        fc_run([{"id": "timeline.place", "params": {"item": 2, "track": "new", "audioTrack": "new", "seconds": 1}}], p, cwd=tmp_path)
        return g, p

    def tone_peak(p, name, start):
        out = tmp_path / f"{name}.wav"
        fc("exec", "file.exportMedia", json.dumps({"path": str(out), "format": "wav", "range": "entire", "wait": True}), project=p, cwd=tmp_path)
        return peak_db(out, start, 0.4)

    def lime_at(p, name, t):
        fc("render", "--seconds", str(t), "--out", str(tmp_path / f"{name}{t}.png"), project=p, cwd=tmp_path)
        r, g, b = centre(tmp_path / f"{name}{t}.png")
        return g > 150 and r < 60

    g, p = place("longer", 2, False)
    prores_4444(g, 3, color="lime")
    fc("--save", "exec", "media.refreshChanged", project=p, cwd=tmp_path)
    assert tracks(p, tmp_path)["V2"] == [("longer.mov", 1.0, 3.0)]
    assert lime_at(p, "longer", 2.5) and not lime_at(p, "longer", 3.5)

    g, p = place("shorter", 3, True)
    prores_4444(g, 1, color="lime", tone_hz=1000)
    assert tracks(p, tmp_path)["V2"] == [("shorter.mov", 1.0, 4.0)] and tracks(p, tmp_path)["A2"] == [("shorter.mov", 1.0, 4.0)]
    assert lime_at(p, "shorter", 3.5)                                   # the last frame holds to the old end
    assert tone_peak(p, "shorter_in", 1.2) > -25 and tone_peak(p, "shorter_past", 2.5) < -60

    g, p = place("gained", 3, False)
    prores_4444(g, 3, color="lime", tone_hz=1000)
    assert "A2" not in tracks(p, tmp_path)
    assert tone_peak(p, "gained", 1.2) < -60

    g, p = place("lost", 3, True)
    prores_4444(g, 3, color="lime")
    assert tracks(p, tmp_path)["A2"] == [("lost.mov", 1.0, 4.0)]
    assert tone_peak(p, "lost", 1.2) < -60


def test_24_an_sdr_overlay_lands_at_reference_white_in_an_hdr_sequence(tmp_path):
    """`graphic --help` (HDR sequences): in a Rec. 2100 HLG sequence FilmCraft converts a BT.709-tagged overlay like any SDR clip, placing SDR white at the HLG reference level (75 % signal, ITU-R BT.2408), so a render needs no HDR-specific encoding. Checked on the exported HLG master: the overlay's white and grey equal those of an SDR H.264 clip with the same values, and white is 75 % ± 2 %."""
    # top half: an ordinary SDR clip with a white and a grey band; bottom half: an overlay with the same bands
    ffmpeg("-f", "lavfi", "-i", "color=c=black:s=640x360:r=30:d=2", "-vf", "drawbox=x=0:y=0:w=320:h=180:c=white:t=fill,drawbox=x=320:y=0:w=320:h=180:c=0x808080:t=fill",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", str(tmp_path / "sdr.mp4"))
    img = Image.new("RGBA", (640, 360), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (320, 180), (255, 255, 255, 255)), (0, 180))
    img.paste(Image.new("RGBA", (320, 180), (128, 128, 128, 255)), (320, 180))
    img.save(tmp_path / "o.png")
    ffmpeg("-loop", "1", "-framerate", "30", "-i", str(tmp_path / "o.png"), "-t", "2",
           "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuva444p10le,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv",
           "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", str(tmp_path / "o.mov"))
    p = tmp_path / "hlg.fcproj"
    fc("--save-as", str(p), "import", str(tmp_path / "sdr.mp4"), str(tmp_path / "o.mov"), cwd=tmp_path)
    fc("--save", "exec", "file.newSequenceFromClip", "items=[1]", project=p, cwd=tmp_path)
    fc_run([{"id": "sequence.settings", "params": {"workingSpace": "rec2100-hlg"}}, {"id": "timeline.place", "params": {"item": 2, "track": "new", "audioTrack": "new", "seconds": 0}}], p, cwd=tmp_path)
    out = tmp_path / "hlg.mov"
    fc("exec", "file.exportMedia", json.dumps({"path": str(out), "format": "prores", "range": "entire", "wait": True}), project=p, cwd=tmp_path)
    [v] = ff.probe(out).video
    assert (v.transfer, v.primaries) == ("arib-std-b67", "bt2020")
    ffmpeg("-ss", "1", "-i", str(out), "-frames:v", "1", "-pix_fmt", "rgb24", str(tmp_path / "hlg.png"))   # code values: matrix only, no transfer
    px = Image.open(tmp_path / "hlg.png").convert("RGB")
    clip_white, clip_grey = px.getpixel((160, 90)), px.getpixel((480, 90))
    over_white, over_grey = px.getpixel((160, 270)), px.getpixel((480, 270))
    assert all(abs(a - b) <= 2 for a, b in zip(clip_white, over_white)), (clip_white, over_white)
    assert all(abs(a - b) <= 2 for a, b in zip(clip_grey, over_grey)), (clip_grey, over_grey)
    assert over_white[1] / 255 == pytest.approx(0.75, abs=0.02)
