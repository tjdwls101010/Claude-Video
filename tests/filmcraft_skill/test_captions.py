"""`captions`: Korean caption layout to Netflix's Korean rules, from a project's sequence-time transcript or from translated cues.

Expected layouts are worked by hand from the rules (16 units a line with Latin letters, digits, spaces and punctuation at half a unit; two lines; 12 characters a second; 5/6 s to 7 s; no full stop or comma at a line end; bottom line at least as long). Line width is checked against FilmCraft's own burn-in render, not against the formula the code uses."""

from __future__ import annotations

import json
import re
from fractions import Fraction
from pathlib import Path

import pytest
from PIL import Image

from filmcraft import captions
from support import FILMCRAFT, TICKS, fc, fc_json, fc_run, ffmpeg, make_av, needs_filmcraft, skill

FPS = Fraction(30)
RULES = captions.Rules()


def words(spec):
    """[("text", start, end), ...] → captions.Word list."""
    return [captions.Word(t, a, b) for t, a, b in spec]


def even(text, start, end):
    """Words of `text` spread evenly over [start, end)."""
    ws = text.split()
    step = (end - start) / len(ws)
    return [(w, start + i * step, start + (i + 1) * step) for i, w in enumerate(ws)]


def frame(t):
    return t * 30 == int(round(t * 30)) or abs(t * 30 - round(t * 30)) < 1e-6


# -- counting -------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, units", [("안녕하세요", 5), ("AI", 1), ("Claude에게는", 6), ("네, 맞아요", 5), ("2026년", 3), ("…", 1)])
def test_units_count_hangul_as_one_and_latin_digits_spaces_punctuation_as_half(text, units):
    assert captions.units(text) == units


# -- layout by hand ------------------------------------------------------------------------------------------------------

def test_a_sentence_over_16_units_splits_into_two_lines_at_the_clause_bottom_heavy():
    """25.5 units: top '오늘은 날씨가 정말 좋아서' = 12.5, bottom '산책을 나가기로 했습니다' = 13 (period dropped). Splitting after 정말 leaves 16.5 below; after 산책을, 16 above and a top-heavy pair."""
    cues = captions.layout(words(even("오늘은 날씨가 정말 좋아서 산책을 나가기로 했습니다.", 0.0, 3.0)), RULES, FPS)
    assert [c.lines for c in cues] == [["오늘은 날씨가 정말 좋아서", "산책을 나가기로 했습니다"]]


def test_one_line_when_it_fits_and_sentences_break_cues():
    spec = even("안녕하세요, 여러분.", 0.0, 1.2) + even("오늘은 자막 이야기를 해 볼게요.", 1.4, 3.4)
    cues = captions.layout(words(spec), RULES, FPS)
    assert [c.lines for c in cues] == [["안녕하세요, 여러분"], ["오늘은 자막 이야기를 해 볼게요"]]


def test_lines_split_evenly_and_bottom_heavy_when_the_text_does_not_choose():
    """Five 3-syllable words, no punctuation, 17 units: splits after word 1 (3 | 13), 2 (6.5 | 9.5), 3 (9.5 | 6.5) all fit. Bottom-heavy beats top-heavy, and the nearer to even, the better."""
    [cue] = captions.layout(words(even("가나다 라마바 사아자 차카타 파하가", 0.0, 3.0)), RULES, FPS)
    assert cue.lines == ["가나다 라마바", "사아자 차카타 파하가"]


def test_comma_at_a_line_end_goes_and_three_dots_become_an_ellipsis():
    """Only the split at the comma keeps both lines within 16 units (15 and 14.5), so the comma lands at a line end and goes."""
    spec = even("그러니까 제가 하고 싶은 말은요, 이건 중요한 문제라는 거예요...", 0.0, 4.0)
    [cue] = captions.layout(words(spec), RULES, FPS)
    assert cue.lines == ["그러니까 제가 하고 싶은 말은요", "이건 중요한 문제라는 거예요…"]


def test_a_fast_cue_lingers_into_silence_to_reach_12_cps():
    """18 characters (spaces count) spoken in 1.0 s, then 2 s of silence: the cue stays up for 18/12 = 1.5 s, frame 45."""
    spec = even("이건 진짜 빠르게 말한 문장이에요", 0.0, 1.0) + [("다음.", 3.0, 3.5)]
    cues = captions.layout(words(spec), RULES, FPS)
    assert cues[0].start == 0.0 and cues[0].end == pytest.approx(45 / 30)
    assert captions.violations(cues, RULES) == []


def test_two_fast_sentences_share_one_cue_when_that_meets_the_reading_speed():
    """18 characters in 1 s alone is 18 cps; with the next sentence as its second line, 35 characters over 3 s is 11.7 cps."""
    spec = even("이건 진짜 빠르게 말한 문장이에요.", 0.0, 1.0) + even("바로 다음 문장이 붙어서 나와요.", 1.0, 3.0)
    cues = captions.layout(words(spec), RULES, FPS)
    assert [c.lines for c in cues] == [["이건 진짜 빠르게 말한 문장이에요", "바로 다음 문장이 붙어서 나와요"]]
    assert captions.violations(cues, RULES) == []


def test_a_fast_cue_with_no_room_is_reported_not_stretched_over_the_next():
    """The next sentence is another speaker's, so it cannot share the cue: the fast one is reported."""
    spec = [captions.Word(t, a, b, speaker="A") for t, a, b in even("이건 진짜 빠르게 말한 문장이에요.", 0.0, 1.0)]
    spec += [captions.Word(t, a, b, speaker="B") for t, a, b in even("바로 다음 문장이 붙어서 나와요.", 1.0, 3.0)]
    cues = captions.layout(spec, RULES, FPS)
    assert cues[0].end <= cues[1].start
    v = captions.violations(cues, RULES)
    assert [(x["cue"], x["kind"]) for x in v] == [(1, "cps")] and v[0]["value"] > 12


def test_a_short_cue_is_held_for_five_sixths_of_a_second():
    cues = captions.layout(words([("네.", 1.0, 1.2), ("그래서요.", 4.0, 4.9)]), RULES, FPS)
    assert cues[0].end - cues[0].start == pytest.approx(25 / 30)  # 5/6 s = 25 frames


def test_long_unpunctuated_speech_never_exceeds_two_lines_or_seven_seconds():
    spec = even(" ".join(["가나다"] * 30), 0.0, 15.0)
    cues = captions.layout(words(spec), RULES, FPS)
    assert all(len(c.lines) <= 2 and all(captions.units(l) <= 16 for l in c.lines) for c in cues)
    assert all(c.end - c.start <= 7.0 + 1e-9 for c in cues)
    assert " ".join(" ".join(c.lines) for c in cues) == " ".join(["가나다"] * 30)


def test_cues_start_strictly_later_on_frames_and_keep_two_frames_apart_when_chained():
    spec = even("하나 둘 셋 넷 다섯 여섯 일곱 여덟 아홉 열.", 0.0, 2.0) + even("열하나 열둘 열셋 열넷 열다섯 열여섯 열일곱.", 2.0, 4.0)
    cues = captions.layout(words(spec), RULES, FPS)
    assert all(frame(c.start) and frame(c.end) for c in cues)
    assert all(b.start > a.start for a, b in zip(cues, cues[1:]))
    assert all(b.start - a.end >= 2 / 30 - 1e-9 for a, b in zip(cues, cues[1:]))


def test_a_speaker_change_starts_a_new_cue():
    ws = [captions.Word("질문은", 0.0, 0.5, speaker="A"), captions.Word("이거예요", 0.5, 1.0, speaker="A"),
          captions.Word("답은", 1.0, 1.5, speaker="B"), captions.Word("이겁니다", 1.5, 2.0, speaker="B")]
    cues = captions.layout(ws, RULES, FPS)
    assert [c.lines for c in cues] == [["질문은 이거예요"], ["답은 이겁니다"]]


def test_a_width_limit_tighter_than_16_units_wraps_earlier():
    """A vertical frame can hold fewer than 16 Korean characters a line: with room for 10 units, each line stays within 10."""
    fits = lambda line: captions.units(line) <= 10
    cues = captions.layout(words(even("오늘은 날씨가 정말 좋아서 산책을 나가기로 했습니다.", 0.0, 3.0)), RULES, FPS, fits=fits)
    assert all(captions.units(l) <= 10 for c in cues for l in c.lines)
    assert all(len(c.lines) <= 2 for c in cues)


def test_translated_cues_are_relaid_out_within_their_own_time():
    long = captions.Cue(0.0, 9.63, ["정말로 배려하는 존재, 이상적으로는 스스로도 배려받는다고 느끼며 모든 일이 잘되길 바라는 존재예요."])
    ok = captions.Cue(10.0, 12.0, ["좋은 질문이에요."])
    cues = captions.relayout([long, ok], RULES, FPS)
    assert all(len(c.lines) <= 2 and all(captions.units(l) <= 16 for l in c.lines) for c in cues)
    assert all(c.end - c.start <= 7.0 + 1e-9 for c in cues)
    firsts = [c for c in cues if c.start < 10.0]
    assert firsts[0].start == 0.0 and firsts[-1].end <= 9.63 + 1e-9 and len(firsts) >= 2
    plain = lambda t: re.sub(r"[,.]", "", re.sub(r"\s+", " ", t))
    assert plain(" ".join(" ".join(c.lines) for c in firsts)) == plain("정말로 배려하는 존재, 이상적으로는 스스로도 배려받는다고 느끼며 모든 일이 잘되길 바라는 존재예요.")
    assert cues[-1].lines == ["좋은 질문이에요"] and cues[-1].start == 10.0


# -- the command ---------------------------------------------------------------------------------------------------------

def parse_srt(path):
    out = []
    for block in Path(path).read_text(encoding="utf-8").strip().split("\n\n"):
        lines = block.split("\n")
        a, b = lines[1].split(" --> ")
        sec = lambda s: int(s[:2]) * 3600 + int(s[3:5]) * 60 + int(s[6:8]) + int(s[9:12]) / 1000
        out.append((sec(a), sec(b), lines[2:]))
    return out


def transcript_line(item, spec):
    return {"id": "transcript.set", "params": {"item": item, "transcript": {"language": "ko", "speakers": [], "words": [
        {"text": t, "start": round(a * TICKS), "end": round(b * TICKS)} for t, a, b in spec]}}}


@pytest.fixture
def edited_project(tmp_path):
    """One 30 s item with a word every 2 s ("단어k." at 2k..2k+0.5 s of media), far enough apart at 200 % for each word to be one cue. Clip A: media 2..7 s at frame 0. Clip B: the same item again, media 10..18 s at 10 s, sped to 200 %. Then the sequence range [1, 2) s is extracted (ripple)."""
    if FILMCRAFT is None:
        pytest.skip("filmcraft-cli is not installed")
    make_av(tmp_path / "m.mp4", 30, rate="30")
    p = tmp_path / "p.fcproj"
    item = json.loads(fc("--save-as", str(p), "import", str(tmp_path / "m.mp4"), cwd=tmp_path).stdout)["items"][0]
    spec = [(f"단어{k}.", 2 * k + 0.0, 2 * k + 0.5) for k in range(15)]
    res = fc_run([
        transcript_line(item, spec),
        {"id": "file.newSequence", "params": {"name": "S", "fps": 30, "video": 1, "audio": 1}},
        {"id": "timeline.place", "params": {"item": item, "track": "V1", "frame": 0, "insert": False, "sourceIn": 2 * TICKS, "duration": 5 * TICKS}},
        {"id": "timeline.place", "params": {"item": item, "track": "V1", "frame": 300, "insert": False, "sourceIn": 10 * TICKS, "duration": 8 * TICKS}},
    ], p, cwd=tmp_path)
    assert all(l["ok"] for l in res), res
    b_clips = res[3]["result"]["clips"]
    res = fc_run([
        {"id": "clip.speedDuration", "params": {"clips": b_clips, "speed": 200}},
        {"id": "markers.markIn", "params": {"frame": 30}},
        {"id": "markers.markOut", "params": {"frame": 59}},
        {"id": "sequence.extract", "params": {}},
    ], p, cwd=tmp_path)
    assert all(l["ok"] for l in res), res
    return tmp_path, p


@needs_filmcraft
def test_cues_follow_sequence_time_through_trim_reuse_speed_and_ripple(edited_project):
    """By hand: clip A shows media 2..7 at 0..5 s, so words 1, 2, 3 (media 2, 4, 6) sit at 0, 2, 4 s; extracting [1, 2) s pulls everything after it 1 s left: 0, 1, 3.
    Clip B shows media 10..18 at 200 % from 10 s, moved to 9 s by the ripple, so word k (media 2k) starts at 9 + (2k - 10) / 2 for k = 5..8; word 9 (media 18) is past the clip."""
    d, p = edited_project
    code, out, raw, err = skill("captions", "--project", str(p), "--out", str(d / "c.srt"), cwd=d)
    assert code == 0, raw + err
    got = [(round(a, 3), lines[0]) for a, b, lines in parse_srt(d / "c.srt")]
    want = [(0.0, "단어1"), (1.0, "단어2"), (3.0, "단어3")] + [(9 + (2 * k - 10) / 2, f"단어{k}") for k in range(5, 9)]
    assert got == [(round(a, 3), t) for a, t in want]


@needs_filmcraft
def test_import_keeps_every_cue_and_style_then_applies(edited_project):
    d, p = edited_project
    code, out, raw, err = skill("captions", "--project", str(p), "--out", str(d / "c.srt"), "--font", "Apple SD Gothic Neo", "--size", "50", cwd=d)
    assert code == 0, raw + err
    assert out["style"] == {"font": "Apple SD Gothic Neo", "size": 50.0, "margin": 0.08, "anchor": "bottom"}
    written = parse_srt(d / "c.srt")
    imp = fc_json("exec", "captions.import", f"path={d / 'c.srt'}", project=p, save=True, cwd=d)
    assert imp["warnings"] == [] and imp["captions"] == len(written) == out["cues"]
    listed = fc_json("exec", "captions.list", project=p, cwd=d)["tracks"][0]["captions"]
    assert [(round(c["start"] / TICKS, 3), c["text"]) for c in listed] == [(round(a, 3), "\n".join(l)) for a, b, l in written]
    assert any("captions.setStyle" in n and "Apple SD Gothic Neo" in n for n in out["next"])


def box_rows(img: Image.Image, color=(0, 0, 0), tol=8):
    """Rows of the frame where the caption background (opaque black over a white frame) spans at least 20 pixels."""
    w, h = img.size
    px = img.load()
    rows = []
    for y in range(h):
        run = sum(1 for x in range(0, w, 2) if all(abs(px[x, y][i] - color[i]) <= tol for i in range(3)))
        if run >= 10:
            rows.append(y)
    return rows


@needs_filmcraft
@pytest.mark.parametrize("size, font_size, style_first", [("1920x1080", None, False), ("1080x1920", None, True), ("1080x1920", 54, False)])
def test_the_longest_cue_burns_in_as_at_most_two_lines(tmp_path, size, font_size, style_first):
    """FilmCraft's own render is the oracle: the background box of the longest cue is at most two line heights tall. One vertical case starts from a project that already has a differently styled caption track; in the other, size 54 becomes 96 px, so 16 Hangul units no longer fit 0.9 of the width and lines must break earlier."""
    w, h = map(int, size.split("x"))
    white = tmp_path / "w.mp4"
    ffmpeg("-f", "lavfi", "-i", f"color=c=white:s={size}:r=30:d=12", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "12", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(white))
    p = tmp_path / "p.fcproj"
    item = json.loads(fc("--save-as", str(p), "import", str(white), cwd=tmp_path).stdout)["items"][0]
    text = "정말로 배려하는 존재이면서 이상적으로는 스스로도 배려받는다고 느끼며 모든 일이 잘되길 바라는 존재예요."
    lines = [transcript_line(item, even(text, 0.5, 6.5)), {"id": "file.newSequenceFromClip", "params": {"items": [item]}}]
    if style_first:
        (tmp_path / "old.srt").write_text("1\n00:00:08,000 --> 00:00:09,000\nold\n", encoding="utf-8")
        lines += [{"id": "captions.import", "params": {"path": str(tmp_path / "old.srt")}}, {"id": "captions.setStyle", "params": {"track": "C1", "font": "Inter", "size": 90}}]
    assert all(l["ok"] for l in fc_run(lines, p, cwd=tmp_path))
    extra = ["--size", str(font_size)] if font_size else []
    code, out, raw, err = skill("captions", "--project", str(p), "--out", str(tmp_path / "c.srt"), *extra, cwd=tmp_path)
    assert code == 0, raw + err
    st = out["style"]
    imp = fc_json("exec", "captions.import", f"path={tmp_path / 'c.srt'}", project=p, save=True, cwd=tmp_path)
    fc("exec", "captions.setStyle", f"track={imp['track']}", f"font={st['font']}", f"size={st['size']}", f"margin={st['margin']}", f"anchor={st['anchor']}", "background=true", "backgroundColor=#000000ff",
       project=p, save=True, cwd=tmp_path)
    cues = parse_srt(tmp_path / "c.srt")
    longest = max(cues, key=lambda c: sum(captions.units(l) for l in c[2]))
    fc("render", "--seconds", str((longest[0] + longest[1]) / 2), "--out", str(tmp_path / "f.png"), project=p, cwd=tmp_path)
    rows = box_rows(Image.open(tmp_path / "f.png").convert("RGB"))
    px = st["size"] * h / 1080
    line_h = px * 1.25
    assert rows, "no caption box found"
    assert rows[-1] - rows[0] + 1 <= 2 * line_h + 4, (rows[0], rows[-1], line_h, longest)


def test_cues_mode_reads_an_srt_and_writes_one(tmp_path):
    src = tmp_path / "ko.srt"
    src.write_text("1\n00:00:00,000 --> 00:00:09,630\n정말로 배려하는 존재, 이상적으로는 스스로도 배려받는다고 느끼며 모든 일이 잘되길 바라는 존재예요.\n\n"
                   "2\n00:00:10,000 --> 00:00:12,000\n좋은 질문이에요.\n", encoding="utf-8")
    code, out, raw, err = skill("captions", "--cues", str(src), "--fps", "30", "--out", str(tmp_path / "o.srt"), cwd=tmp_path)
    assert code == 0, raw + err
    cues = parse_srt(tmp_path / "o.srt")
    assert out["cues"] == len(cues) >= 3
    assert all(len(l) <= 2 for _, _, l in cues) and all(b - a <= 7.0 for a, b, _ in cues)


def test_source_options_are_exclusive(tmp_path):
    code, *_ = skill("captions", "--project", "p.fcproj", "--cues", "x.srt", "--out", "o.srt", cwd=tmp_path)
    assert code == 2


def test_help_owns_the_numbers():
    code, out, raw, err = skill("captions", "--help")
    assert code == 0
    for word in ("16", "12", "5/6", "7", "0.5", "--font", "--size", "--margin", "--anchor", "--cues", "captions.import", "captions.setStyle", "Prints:", "Exits:", "Netflix"):
        assert word in raw, word


# -- review findings ----------------------------------------------------------------------------------------------------

def test_relaid_cues_never_outlast_the_cue_they_came_from():
    cues = captions.relayout([captions.Cue(1.0, 1.1, ["네."]), captions.Cue(5.0, 14.63, ["정말로 배려하는 존재, 이상적으로는 스스로도 배려받는다고 느끼며 모든 일이 잘되길 바라는 존재예요."])], RULES, FPS)
    assert cues[0].end <= 1.1 + 1e-9
    assert max(c.end for c in cues if c.start >= 5.0) <= 14.63 + 1e-9
    assert ("short" in {v["kind"] for v in captions.violations(cues, RULES) if v["cue"] == 1})


def test_a_single_word_wider_than_the_line_is_reported():
    fits = lambda line: captions.units(line) <= 10
    cues = captions.layout(words([("가나다라마바사아자차카타파하", 0.0, 3.0)]), RULES, FPS, fits=fits)
    assert any(v["kind"] == "long_line" for v in captions.violations(cues, RULES, fits))


def test_next_survives_a_path_with_spaces_and_shell_metacharacters(tmp_path):
    import shlex
    src = tmp_path / "ko.srt"
    src.write_text("1\n00:00:00,000 --> 00:00:02,000\n좋은 질문이에요.\n", encoding="utf-8")
    out = tmp_path / "a b; echo INJECTED #.srt"
    code, res, raw, err = skill("captions", "--cues", str(src), "--out", str(out), cwd=tmp_path)
    assert code == 0, raw + err
    assert shlex.split(res["next"][0])[-1] == f"path={out}"


def test_a_malformed_srt_is_refused_with_the_blocks_named(tmp_path):
    src = tmp_path / "bad.srt"
    src.write_text("1\n00:00:02,000 --> 00:00:01,000\n거꾸로\n\n2\n00:00:0x,000 --> 00:00:03,000\n잘못된 시간\n\n3\n00:00:04,000 --> 00:00:05,000\n정상\n", encoding="utf-8")
    code, res, raw, err = skill("captions", "--cues", str(src), "--out", str(tmp_path / "o.srt"), cwd=tmp_path)
    assert code == 2 and "1" in res["error"] and "2" in res["error"]


@pytest.mark.parametrize("args", [["--cps", "0"], ["--fps", "-1"], ["--min", "0"], ["--max", "-2"]])
def test_impossible_rule_values_are_usage_errors(tmp_path, args):
    src = tmp_path / "ko.srt"
    src.write_text("1\n00:00:00,000 --> 00:00:02,000\n좋은 질문이에요.\n", encoding="utf-8")
    code, res, raw, err = skill("captions", "--cues", str(src), "--out", str(tmp_path / "o.srt"), *args, cwd=tmp_path)
    assert code == 2 and res and "error" in res


def test_relaid_cues_start_inside_their_source_and_a_sub_frame_cue_is_reported():
    cues = captions.relayout([captions.Cue(1.01, 2.0, ["네."]), captions.Cue(3.0, 3.01, ["예."])], RULES, FPS)
    assert cues[0].start >= 1.01
    assert any(v["cue"] == 2 and v["kind"] == "short" for v in captions.violations(cues, RULES))


@pytest.mark.parametrize("args", [["--fps", "inf"], ["--cps", "nan"]])
def test_non_finite_rule_values_are_usage_errors(tmp_path, args):
    src = tmp_path / "ko.srt"
    src.write_text("1\n00:00:00,000 --> 00:00:02,000\n좋은 질문이에요.\n", encoding="utf-8")
    code, res, raw, err = skill("captions", "--cues", str(src), "--out", str(tmp_path / "o.srt"), *args, cwd=tmp_path)
    assert code == 2 and res and "error" in res
