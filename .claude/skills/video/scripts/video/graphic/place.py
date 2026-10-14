"""What the model runs after a render: the filmcraft-cli commands that import and place it, and whether a render replacing an earlier file still fits a clip already placed from it. FilmCraft keeps the length and sound streams it read when the file was imported, so a placed clip plays a same-shape re-render as is but keeps the old length (holding the last frame) and the old sound clip when those changed."""

from __future__ import annotations

import shlex
from pathlib import Path

from PIL import Image

from video import ffmpeg
from video.errors import InputError
from video.filmcraft import Source

PLACEHOLDERS = "<item>: the id in the import's `items`; <start s>: where the graphic starts on the timeline, in seconds; <hold ticks>: how long a still stays on screen, in ticks (254016000000 a second); <P.fcproj>: the project to create"


def shape(path: Path, kind: str) -> dict | None:
    """What a placed clip depends on: frames, sound, size, rate. None if `path` does not exist; {"unreadable": True} if it is not media this skill wrote."""
    if not path.exists():
        return None
    try:
        if kind == "still":
            with Image.open(path) as img:
                return {"frames": 1, "audio": False, "size": img.size, "fps": None}
        m = ffmpeg.probe(path)
        v = m.video[0]
        return {"frames": v.frames, "audio": bool(m.audio), "size": (v.width, v.height), "fps": v.fps}
    except (OSError, InputError, IndexError):
        return {"unreadable": True}


def replaced(before: dict | None, after: dict) -> dict | None:
    if before is None:
        return None
    if before.get("unreadable"):
        return {"length_changed": True, "audio_changed": True, "size_changed": True, "fps_changed": True}
    return {"length_changed": before["frames"] != after["frames"], "audio_changed": before["audio"] != after["audio"],
            "size_changed": tuple(before["size"]) != tuple(after["size"]), "fps_changed": before["fps"] != after["fps"]}


def next_steps(out: Path, kind: str, audio: bool, source: Source | None, sequence: int | None, change: dict | None) -> dict:
    q = shlex.quote
    if source is None:
        result = {"steps": [f"filmcraft-cli --save-as <P.fcproj> import {q(str(out))}",
                            "filmcraft-cli --project <P.fcproj> --save exec file.newSequenceFromClip '{\"items\":[<item>]}'"],
                  "placeholders": PLACEHOLDERS, "note": "No sequence yet: these make a project whose sequence is this render, at its size and rate."}
    else:
        where = f"--project {q(str(source.project))} --save" if source.project is not None else f"--bridge {q(str(source.bridge))}"
        steps = [f"filmcraft-cli {where} exec sequence.open '{{\"item\":{sequence}}}'"] if sequence is not None else []
        params = '"item":<item>,"track":"new"' + (',"audioTrack":"new"' if audio else "") + ',"seconds":<start s>' + (',"duration":<hold ticks>' if kind == "still" else "")
        steps += [f"filmcraft-cli {where} import {q(str(out))}", f"filmcraft-cli {where} exec timeline.place '{{{params}}}'"]
        result = {"steps": steps, "placeholders": PLACEHOLDERS}
    if change is not None:
        changed = [k.removesuffix("_changed") for k, v in change.items() if v]
        if changed:
            result["if_placed"] = (f"This render changed {', '.join(changed)} from the file it replaced, and a clip already placed from that file keeps what FilmCraft read at import "
                                   "(the old length, holding its last frame; the old sound clip or none). If it is placed, clear that clip and its sound clip first "
                                   "(exec edit.clear '{\"clips\":[...]}'; `timeline` lists clip ids), then run the steps. If it is not placed yet, just run them.")
        else:
            result["if_placed"] = "Same length, sound, size and rate as the file it replaced: if that file is already placed, the clip now plays this render and nothing else is needed. If not, run the steps."
    return result
