"""A sequence read once and reported twice: a summary small enough to print whatever the clip count, and a detail document with every clip, transition, marker and caption track in timecode."""

from __future__ import annotations

import json
from pathlib import Path

from video.filmcraft_cli import Sequence, Source, read_sequence
from video.timecode import seconds

__all__ = ["summarize", "detail", "report"]


def summarize(seq: Sequence) -> dict:
    return {
        "name": seq.name,
        "fps": seq.rate.label(),
        "size": f"{seq.width}x{seq.height}",
        "duration_tc": seq.timecode(seq.duration_frames),
        "tracks": [{"name": t.label, "clips": len(t.clips), "locked": t.locked, "muted": t.muted} for t in seq.tracks]
                  + [{"name": c.label, "clips": len(c.captions), "locked": c.locked, "muted": not c.enabled} for c in seq.caption_tracks],
        "clips": sum(len(t.clips) for t in seq.tracks),
        "captions": sum(len(c.captions) for c in seq.caption_tracks),
        "markers": len(seq.markers),
        "transitions": sum(len(t.transitions) for t in seq.tracks),
    }


def detail(seq: Sequence) -> dict:
    tc = seq.timecode

    def frame(t: int) -> int:
        return seq.rate.frame_at(t)

    clips = []
    for t in seq.tracks:
        for c in t.clips:
            row = {
                "clip": c.id, "item": c.item, "name": c.name, "track": c.track,
                "start_tc": tc(c.start_frame), "end_tc": tc(c.end_frame),
                "src_in_s": round(seconds(c.source_in), 3), "src_out_s": round(seconds(c.source_out), 3),
                "speed": c.speed, "reverse": c.reverse, "gain_db": c.gain_db, "effects": c.effects, "enabled": c.enabled,
            }
            for k in ("scale", "position", "opacity"):
                if getattr(c, k) is not None:
                    row[k] = getattr(c, k)
            clips.append(row)
    return {
        "sequence": {
            "id": seq.id, "name": seq.name, "fps": seq.rate.label(), "drop_frame": seq.drop_frame, "size": f"{seq.width}x{seq.height}",
            "duration_tc": tc(seq.duration_frames), "duration_frames": seq.duration_frames,
            "in_tc": tc(frame(seq.mark_in)) if seq.mark_in is not None else None,
            "out_tc": tc(frame(seq.mark_out)) if seq.mark_out is not None else None,
        },
        "clips": clips,
        "transitions": [
            {"track": x.track, "effect": x.effect, "start_tc": tc(frame(x.start)), "end_tc": tc(frame(x.start + x.duration)), "from": x.from_clip, "to": x.to_clip}
            for t in seq.tracks for x in t.transitions
        ],
        "markers": [{"name": m.name, "kind": m.kind, "start_tc": tc(frame(m.start)), "duration_frames": frame(m.duration), "comment": m.comment} for m in seq.markers],
        "captions": [
            {"track": c.label, "name": c.name, "enabled": c.enabled, "cues": len(c.captions), "font": c.style.get("font"), "size": c.style.get("size"),
             "anchor": c.style.get("anchor"), "margin": round(c.style["margin"], 3) if isinstance(c.style.get("margin"), float) else c.style.get("margin"),
             "first_tc": tc(frame(c.captions[0].start)) if c.captions else None, "last_end_tc": tc(frame(c.captions[-1].end)) if c.captions else None}
            for c in seq.caption_tracks
        ],
    }


def _lines(doc: dict) -> str:
    """JSON with one record per line, so a grep for a clip name or timecode returns the whole record."""
    def one(v) -> str:
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))

    parts = []
    for k, v in doc.items():
        if isinstance(v, list) and v:
            parts.append(f"{one(k)}:[\n" + ",\n".join(one(x) for x in v) + "\n]")
        else:
            parts.append(f"{one(k)}:{one(v)}")
    return "{\n" + ",\n".join(parts) + "\n}\n"


def report(source: Source, out: Path, sequence: int | None = None) -> dict:
    seq = read_sequence(source, sequence)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_lines(detail(seq)))
    return {"summary": summarize(seq), "detail": str(out)}
