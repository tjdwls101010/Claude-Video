"""Speech to a word-timed FilmCraft transcript: Whisper's words, their edges moved onto measured speech, written as one `transcript.set` line for `filmcraft-cli run`, with the words a person should check listed for review."""

from __future__ import annotations

import json
import shlex
import shutil
import sys
from pathlib import Path

from filmcraft import ffmpeg, whisper
from filmcraft.errors import InputError
from filmcraft.timecode import ticks

from .core import Word, snap, speech_spans
from .review import LOW_PROB, flags

__all__ = ["Word", "snap", "speech_spans", "transcribe", "DEFAULT_MODEL", "LOW_PROB", "REVIEW_SHOWN"]

DEFAULT_MODEL = whisper.DEFAULT_MODEL
HOP = 0.01
REVIEW_SHOWN = 40


def transcribe(media: Path, item: int, out: Path, language: str | None = None, model: str = DEFAULT_MODEL, max_shift: float = 0.5, from_json: Path | None = None) -> dict:
    info = ffmpeg.probe(media)
    if not info.audio:
        raise InputError(f"{media}: no audio stream")
    out.parent.mkdir(parents=True, exist_ok=True)
    raw_json = out.with_suffix(".whisper.json")
    if from_json is None:
        print(f"transcribing {media.name} with {model} (first use downloads the model) …", file=sys.stderr)
        produced = whisper.recognise(media, out.parent / (out.stem + ".whisper"), language, model)
        shutil.move(produced, raw_json)
        shutil.rmtree(out.parent / (out.stem + ".whisper"), ignore_errors=True)
        source = raw_json
    else:
        source = from_json
    rec = whisper.read(source)
    words = [Word(w.text, w.start, w.end, w.prob, k) for k, s in enumerate(rec.segments) for w in s.words]
    fps = info.video[0].fps if info.video and info.video[0].fps else 30
    spans = speech_spans(ffmpeg.envelope(media, HOP), HOP)
    snapped, report = snap(words, spans, max_shift=max_shift, min_dur=1 / float(fps))
    lang = rec.language or language or ""
    line = {"id": "transcript.set", "params": {"item": item, "transcript": {
        "language": lang, "source": f"mlx-whisper {model.rsplit('/', 1)[-1]}", "speakers": [],
        "words": [{"text": w.text, "start": ticks(w.start), "end": ticks(w.end), "confidence": round(min(max(w.prob, 0.0), 1.0), 3)} for w in snapped]}}}
    out.write_text(json.dumps(line, ensure_ascii=False) + "\n")

    text_file = out.with_suffix(".txt")
    by_seg: dict[int, list[int]] = {}
    for i, w in enumerate(snapped):
        by_seg.setdefault(w.segment, []).append(i)
    text_file.write_text("".join(
        f"[w{ix[0]}-w{ix[-1]}] {snapped[ix[0]].start:8.2f}-{snapped[ix[-1]].end:8.2f}  {' '.join(snapped[i].text for i in ix)}\n" for _, ix in sorted(by_seg.items())))

    review = flags(snapped, report["unmatched"], rec.segments)
    result = {
        "item": item, "language": lang, "words": len(snapped), "seconds": round(info.duration or 0, 2),
        "speech_seconds": round(sum(b - a for a, b in spans), 2), "snapped": report["snapped"], "unmatched": len(report["unmatched"]),
        "review": review[:REVIEW_SHOWN], "review_total": len(review),
        "out": str(out), "text": str(text_file), "whisper_json": str(source),
        "next": f"filmcraft-cli --project <P.fcproj> --save run {shlex.quote(str(out))}",
    }
    if len(review) > REVIEW_SHOWN:
        rf = out.with_suffix(".review.json")
        rf.write_text(json.dumps(review, ensure_ascii=False, indent=0))
        result["review_file"] = str(rf)
    return result
