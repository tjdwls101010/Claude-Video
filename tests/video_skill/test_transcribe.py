"""`transcribe`: Whisper words snapped to measured speech, written as one `transcript.set` line.

Two layers of evidence that snapping helps, both with boundaries known independently of the code: tone bursts at times the generator chose (exact edges), and Korean phrases synthesised one by one with `say` and joined with silences of known length (phrase edges). Whisper itself is replaced by JSON recorded from a real run, except when FILMCRAFT_TEST_WHISPER=1."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from video import transcribe
from support import FILMCRAFT, TICKS, fc, fc_json, fc_run, ffmpeg, needs_ffmpeg, needs_filmcraft, skill

FIXTURES = Path(__file__).parent / "fixtures"
pytestmark = needs_ffmpeg


def W(text, start, end, prob=1.0):
    return transcribe.Word(text, start, end, prob)


def spans_of(words):
    return [(round(w.start, 3), round(w.end, 3)) for w in words]


# -- the pure snap: words and speech spans in, words out ------------------------------------------------------------------

def test_edges_move_to_the_speech_they_belong_to():
    """Whisper 0.3 s late on two phrases: each phrase's outer edges land on its span; interior boundaries stay."""
    spans = [(1.0, 2.0), (3.0, 4.5)]
    words = [W("a", 1.3, 1.7), W("b", 1.7, 2.3), W("c", 3.3, 4.0), W("d", 4.0, 4.8)]
    out, report = transcribe.snap(words, spans, max_shift=0.5, min_dur=1 / 30)
    assert spans_of(out) == [(1.0, 1.7), (1.7, 2.0), (3.0, 4.0), (4.0, 4.5)]
    assert report["snapped"] == 4 and report["unmatched"] == []


def test_a_word_in_silence_keeps_its_time_and_is_reported():
    out, report = transcribe.snap([W("a", 1.1, 1.9), W("x", 6.0, 6.4)], [(1.0, 2.0)], max_shift=0.5, min_dur=1 / 30)
    assert spans_of(out)[1] == (6.0, 6.4)
    assert report["unmatched"] == [1]


def test_no_edge_moves_outward_further_than_max_shift():
    out, _ = transcribe.snap([W("a", 1.8, 2.2)], [(1.0, 3.0)], max_shift=0.5, min_dur=1 / 30)
    assert spans_of(out) == [(1.8, 2.2)]


def test_an_edge_whisper_put_in_silence_moves_inward_onto_speech_however_far():
    """Whisper often starts the first word at the top of a leading silence; moving inward stays inside the word, so it cannot reorder or overlap anything."""
    out, _ = transcribe.snap([W("a", 0.0, 1.6)], [(1.0, 3.0)], max_shift=0.5, min_dur=1 / 30)
    assert spans_of(out) == [(1.0, 1.6)]


def test_no_word_ends_up_shorter_than_one_frame():
    words = [W("a", 0.9, 1.01), W("b", 1.01, 1.02), W("c", 1.02, 1.6)]
    out, _ = transcribe.snap(words, [(1.0, 1.6)], max_shift=0.5, min_dur=1 / 30)
    assert all(w.end - w.start >= 1 / 30 - 1e-9 for w in out), spans_of(out)


def test_order_and_non_overlap_survive_overlapping_input():
    words = [W("a", 1.0, 1.5), W("b", 1.4, 1.8), W("c", 1.7, 2.6)]
    out, _ = transcribe.snap(words, [(1.0, 2.5)], max_shift=0.5, min_dur=1 / 30)
    assert [w.text for w in out] == ["a", "b", "c"]
    assert all(out[i].end <= out[i + 1].start + 1e-9 for i in range(len(out) - 1)), spans_of(out)
    assert all(w.start < w.end for w in out)


# -- through the command: real audio, recorded Whisper JSON ---------------------------------------------------------------

def whisper_json(path, segments, language="ko"):
    path.write_text(json.dumps({"language": language, "text": "", "segments": [
        {"start": s[0][1], "end": s[-1][2], "text": " ".join(w[0] for w in s), "no_speech_prob": 0.0, "avg_logprob": -0.2, "compression_ratio": 1.2,
         "words": [{"word": " " + w[0], "start": w[1], "end": w[2], "probability": w[3] if len(w) > 3 else 0.99} for w in s]} for s in segments]}, ensure_ascii=False))
    return path


def tone_bursts(path, bursts, total):
    """A 1 kHz tone exactly inside each (start, end) burst, digital silence elsewhere."""
    expr = "+".join(f"between(t\\,{a}\\,{b})" for a, b in bursts)  # commas escaped for the filtergraph
    ffmpeg("-f", "lavfi", "-i", f"aevalsrc=0.3*sin(2*PI*1000*t)*({expr}):s=48000:d={total}", "-c:a", "pcm_s16le", str(path))
    return path


def read_jsonl(path):
    [line] = [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
    return line


def test_command_snaps_to_bursts_and_writes_one_transcript_set_line(tmp_path):
    audio = tone_bursts(tmp_path / "b.wav", [(1.0, 2.0), (3.0, 4.5)], 6)
    wj = whisper_json(tmp_path / "w.json", [[("가", 1.3, 1.7), ("나", 1.7, 2.3)], [("다", 3.3, 4.0), ("라", 4.0, 4.8, 0.2)]])
    out = tmp_path / "t.jsonl"
    code, res, raw, err = skill("transcribe", str(audio), "--item", "7", "--out", str(out), "--from-json", str(wj), cwd=tmp_path)
    assert code == 0, raw + err
    line = read_jsonl(out)
    assert line["id"] == "transcript.set" and line["params"]["item"] == 7
    words = line["params"]["transcript"]["words"]
    got = [(w["text"], round(w["start"] / TICKS, 2), round(w["end"] / TICKS, 2)) for w in words]
    assert got == [("가", 1.0, 1.7), ("나", 1.7, 2.0), ("다", 3.0, 4.0), ("라", 4.0, 4.5)]
    assert res["words"] == 4 and res["snapped"] == 4 and res["language"] == "ko"
    assert {"i": 3, "text": "라", "reason": "low_prob"}.items() <= res["review"][0].items()
    assert res["speech_seconds"] == pytest.approx(2.5, abs=0.05)
    assert "run" in res["next"] and str(out) in res["next"]


def test_hallucinated_repeats_are_flagged_for_review(tmp_path):
    audio = tone_bursts(tmp_path / "b.wav", [(0.5, 1.5)], 8)
    segs = [[("안녕", 0.5, 1.5)]] + [[("시리야", 2.0 + i, 2.6 + i)] for i in range(4)]
    wj = whisper_json(tmp_path / "w.json", segs)
    code, res, raw, err = skill("transcribe", str(audio), "--item", "1", "--out", str(tmp_path / "t.jsonl"), "--from-json", str(wj), cwd=tmp_path)
    assert code == 0, raw + err
    reasons = {r["reason"] for r in res["review"] if r["text"] == "시리야"}
    assert "repeat" in reasons


SAY = [("오늘은 편집 이야기를 해볼게요", 0.6), ("자막은 문장 단위로 끊어야 읽기 편합니다", 0.9), ("그럼 바로 시작하겠습니다", 1.2)]


def say_reference(d: Path):
    """Each phrase synthesised alone, then joined after the silence listed with it; returns the audio and each phrase's (start, end)."""
    if shutil.which("say") is None:
        pytest.skip("macOS `say` is needed for the speech reference")
    parts, edges, t = [], [], 0.0
    for i, (text, gap) in enumerate(SAY):
        aiff, wav, sil = d / f"p{i}.aiff", d / f"p{i}.wav", d / f"s{i}.wav"
        subprocess.run(["say", "-v", "Yuna", "-o", str(aiff), text], check=True)
        ffmpeg("-i", str(aiff), "-ar", "48000", "-ac", "1", str(wav))
        ffmpeg("-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", str(gap), str(sil))
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(wav)], capture_output=True, text=True).stdout)
        parts += [sil, wav]
        edges.append((t + gap, t + gap + dur))
        t += gap + dur
    tail = d / "tail.wav"
    ffmpeg("-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "0.5", str(tail))
    parts.append(tail)
    out = d / "speech.wav"
    ffmpeg(*sum((["-i", str(p)] for p in parts), []), "-filter_complex", f"concat=n={len(parts)}:v=0:a=1", str(out))
    return out, edges


def phrase_edges(words, n):
    """First start and last end of each phrase, phrases being Whisper's segments in order (one per `say` phrase here)."""
    groups, cur = [], []
    for w in words:
        cur.append(w)
        if w["text"].endswith("."):
            groups.append((cur[0]["start"] / TICKS, cur[-1]["end"] / TICKS))
            cur = []
    assert len(groups) == n, groups
    return groups


def test_snapping_brings_real_speech_edges_closer_to_the_truth(tmp_path):
    audio, truth = say_reference(tmp_path)
    recorded = json.loads((FIXTURES / "say_ko.whisper.json").read_text())
    raw_edges = [(s["words"][0]["start"], s["words"][-1]["end"]) for s in recorded["segments"]]
    code, res, raw, err = skill("transcribe", str(audio), "--item", "1", "--out", str(tmp_path / "t.jsonl"), "--from-json", str(FIXTURES / "say_ko.whisper.json"), cwd=tmp_path)
    assert code == 0, raw + err
    snapped = phrase_edges(read_jsonl(tmp_path / "t.jsonl")["params"]["transcript"]["words"], len(SAY))

    def err_of(edges):
        return sum(abs(a - ta) + abs(b - tb) for (a, b), (ta, tb) in zip(edges, truth)) / (2 * len(truth))

    assert err_of(raw_edges) > 0.25           # what Whisper alone gets wrong here: about a third of a second per edge
    assert err_of(snapped) < 0.05, (snapped, truth)


@needs_filmcraft
def test_the_jsonl_round_trips_through_filmcraft_word_for_word(tmp_path):
    audio, _ = say_reference(tmp_path)
    movie = tmp_path / "talk.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=gray:s=640x360:r=30:d=11", "-i", str(audio), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(movie))
    p = tmp_path / "p.fcproj"
    item = json.loads(fc("--save-as", str(p), "import", str(movie), cwd=tmp_path).stdout)["items"][0]
    assert all(l["ok"] for l in fc_run([{"id": "file.newSequenceFromClip", "params": {"items": [item]}}], p, cwd=tmp_path))
    out = tmp_path / "t.jsonl"
    code, res, raw, err = skill("transcribe", str(movie), "--item", str(item), "--out", str(out), "--from-json", str(FIXTURES / "say_ko.whisper.json"), cwd=tmp_path)
    assert code == 0, raw + err
    fc("run", str(out), project=p, save=True, cwd=tmp_path)
    got = fc_json("exec", "transcript.inspect", project=p, cwd=tmp_path)["words"]
    want = read_jsonl(out)["params"]["transcript"]["words"]
    assert [(w["text"], w["start"], w["end"]) for w in got] == [(w["text"], w["start"], w["end"]) for w in want]


@pytest.mark.skipif(os.environ.get("FILMCRAFT_TEST_WHISPER") != "1", reason="set FILMCRAFT_TEST_WHISPER=1 to run the real mlx-whisper model (about 1.6 GB, cached under ~/.cache/huggingface)")
def test_real_whisper_path(tmp_path):
    audio, truth = say_reference(tmp_path)
    code, res, raw, err = skill("transcribe", str(audio), "--item", "1", "--language", "ko", "--out", str(tmp_path / "t.jsonl"), cwd=tmp_path)
    assert code == 0, raw + err
    assert res["words"] >= 10 and res["language"] == "ko"
    text = " ".join(w["text"] for w in read_jsonl(tmp_path / "t.jsonl")["params"]["transcript"]["words"])
    assert "편집" in text and "자막" in text


def test_missing_media_is_a_usage_error(tmp_path):
    code, res, raw, err = skill("transcribe", str(tmp_path / "none.wav"), "--item", "1", "--out", str(tmp_path / "t.jsonl"), cwd=tmp_path)
    assert code == 2


def test_help_explains_snapping_review_and_next_step():
    code, res, raw, err = skill("transcribe", "--help")
    assert code == 0
    for word in ("--item", "--out", "--language", "--model", "--max-shift", "--from-json", "review", "low_prob", "unmatched", "repeat", "transcript.set", "Prints:", "Exits:"):
        assert word in raw, word


# -- review findings ----------------------------------------------------------------------------------------------------

def test_next_survives_a_path_with_spaces_and_shell_metacharacters(tmp_path):
    import shlex
    audio = tone_bursts(tmp_path / "b.wav", [(1.0, 2.0)], 3)
    wj = whisper_json(tmp_path / "w.json", [[("가", 1.0, 2.0)]])
    out = tmp_path / "a b; echo INJECTED #.jsonl"
    code, res, raw, err = skill("transcribe", str(audio), "--item", "1", "--out", str(out), "--from-json", str(wj), cwd=tmp_path)
    assert code == 0, raw + err
    assert shlex.split(res["next"])[-1] == str(out)


def test_a_json_that_is_not_mlx_whisper_output_is_a_usage_error(tmp_path):
    audio = tone_bursts(tmp_path / "b.wav", [(1.0, 2.0)], 3)
    (tmp_path / "w.json").write_text("[]")
    code, res, raw, err = skill("transcribe", str(audio), "--item", "1", "--out", str(tmp_path / "t.jsonl"), "--from-json", str(tmp_path / "w.json"), cwd=tmp_path)
    assert code == 2 and res and "w.json" in res["error"]


def test_a_non_finite_word_time_is_a_usage_error(tmp_path):
    audio = tone_bursts(tmp_path / "b.wav", [(1.0, 2.0)], 3)
    (tmp_path / "w.json").write_text(json.dumps({"language": "ko", "segments": [{"start": 1, "end": 2, "text": "가", "words": [{"word": "가", "start": "NaN", "end": 2, "probability": 1}]}]}))
    code, res, raw, err = skill("transcribe", str(audio), "--item", "1", "--out", str(tmp_path / "t.jsonl"), "--from-json", str(tmp_path / "w.json"), cwd=tmp_path)
    assert code == 2 and res and "w.json" in res["error"]
