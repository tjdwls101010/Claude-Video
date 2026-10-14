"""A sequence as the skill sees it, read from `sequence.inspect` and `captions.list`. Their field names and the Rust debug strings effect values arrive as (`Float(100.0)`, `Vec2(Vec2 { x: 960.0, y: 540.0 })`) stop here."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from filmcraft.timecode import Rate

from .process import Source, run

# Effects every clip carries (FilmCraft's intrinsic video and audio attributes); listing them per clip says nothing.
INTRINSIC = {"motion", "opacity", "time_remap", "volume", "channel_volume", "panner"}


@dataclass
class Clip:
    id: int
    item: int
    name: str
    track: str
    start: int
    end: int
    start_frame: int
    end_frame: int
    source_in: int
    source_out: int
    speed: float
    reverse: bool
    gain_db: float
    enabled: bool
    effects: list[str]
    scale: float | None = None
    position: tuple[float, float] | None = None
    opacity: float | None = None


@dataclass
class Transition:
    track: str
    effect: str
    start: int
    duration: int
    from_clip: int | None
    to_clip: int | None


@dataclass
class Marker:
    name: str
    kind: str
    start: int
    duration: int
    comment: str


@dataclass
class Caption:
    id: int
    start: int
    end: int
    text: str


@dataclass
class CaptionTrack:
    id: int
    label: str
    name: str
    enabled: bool
    locked: bool
    style: dict
    captions: list[Caption]


@dataclass
class Track:
    label: str
    name: str
    kind: str
    locked: bool
    muted: bool
    enabled: bool
    clips: list[Clip]
    transitions: list[Transition]


@dataclass
class Sequence:
    id: int
    name: str
    rate: Rate
    drop_frame: bool
    width: int
    height: int
    duration: int
    duration_frames: int
    mark_in: int | None
    mark_out: int | None
    video: list[Track]
    audio: list[Track]
    markers: list[Marker]
    caption_tracks: list[CaptionTrack] = field(default_factory=list)

    @property
    def tracks(self) -> list[Track]:
        return self.video + self.audio

    def timecode(self, frame: int) -> str:
        return self.rate.timecode(frame, self.drop_frame)


def _value(debug: str):
    """A Rust `{:?}` of a parameter value: numbers, booleans and 2-vectors become Python values, anything else stays a string."""
    m = re.fullmatch(r"(?:Float|Int|Choice)\((-?[\d.eE+-]+|NaN|inf|-inf)\)", debug)
    if m:
        return float(m.group(1))
    m = re.fullmatch(r"Bool\((true|false)\)", debug)
    if m:
        return m.group(1) == "true"
    m = re.search(r"x: (-?[\d.eE+-]+), y: (-?[\d.eE+-]+)", debug)
    if debug.startswith("Vec2") and m:
        return (float(m.group(1)), float(m.group(2)))
    return debug


def _params(effect: dict) -> dict:
    return {k: _value(v.get("value", "")) for k, v in (effect.get("params") or {}).items()}


def _clip(raw: dict, track: str, width: int, height: int) -> Clip:
    effects = raw.get("effects") or []
    c = Clip(
        id=raw["clip"], item=raw["item"], name=raw.get("name") or "", track=track,
        start=raw["start"], end=raw["end"], start_frame=raw["startFrame"], end_frame=raw["endFrame"],
        source_in=raw["sourceIn"], source_out=raw["sourceOut"], speed=float(raw.get("speed", 1.0)), reverse=bool(raw.get("reverse")),
        gain_db=float(raw.get("gainDb", 0.0)), enabled=bool(raw.get("enabled", True)),
        effects=[e["effect"] for e in effects if e.get("effect") not in INTRINSIC],
    )
    for e in effects:
        p = _params(e)
        if e.get("effect") == "motion":
            scale, pos = p.get("scale"), p.get("position")
            if isinstance(scale, float) and scale != 100.0:
                c.scale = scale
            if isinstance(pos, tuple) and pos != (width / 2, height / 2):
                c.position = pos
        elif e.get("effect") == "opacity":
            o = p.get("opacity")
            if isinstance(o, float) and o != 100.0:
                c.opacity = o
    return c


def _track(raw: dict, label: str, kind: str, width: int, height: int) -> Track:
    return Track(
        label=label, name=raw.get("name") or label, kind=kind, locked=bool(raw.get("locked")), muted=bool(raw.get("muted")), enabled=bool(raw.get("enabled", True)),
        clips=[_clip(c, label, width, height) for c in raw.get("items") or []],
        transitions=[Transition(label, t.get("effect", ""), t["start"], t["duration"], t.get("from"), t.get("to")) for t in raw.get("transitions") or []],
    )


def parse(inspect: dict, captions: dict | None) -> Sequence:
    st = inspect.get("settings") or {}
    fr = st.get("frame_rate") or {"num": 30, "den": 1}
    w, h = int(st.get("width", 1920)), int(st.get("height", 1080))
    seq = Sequence(
        id=inspect["id"], name=inspect.get("name") or "", rate=Rate(int(fr["num"]), int(fr["den"])), drop_frame=bool(st.get("drop_frame")),
        width=w, height=h, duration=inspect.get("duration", 0), duration_frames=inspect.get("durationFrames", 0),
        mark_in=inspect.get("in"), mark_out=inspect.get("out"),
        video=[_track(t, f"V{i + 1}", "video", w, h) for i, t in enumerate(inspect.get("video") or [])],
        audio=[_track(t, f"A{i + 1}", "audio", w, h) for i, t in enumerate(inspect.get("audio") or [])],
        markers=[Marker(m.get("name") or "", m.get("kind") or "", m["start"], m.get("duration", 0), m.get("comment") or "") for m in inspect.get("markers") or []],
    )
    for t in (captions or {}).get("tracks") or []:
        seq.caption_tracks.append(CaptionTrack(
            id=t["id"], label=t.get("label") or "", name=t.get("name") or "", enabled=bool(t.get("enabled", True)), locked=bool(t.get("locked")), style=dict(t.get("style") or {}),
            captions=[Caption(c["id"], c["start"], c["end"], c.get("text") or "") for c in t.get("captions") or []],
        ))
    return seq


def read_sequence(source: Source, sequence: int | None = None) -> Sequence:
    """The active sequence, or the one named by its item id. Naming one makes it active (in the app, its timeline tab comes to the front), because caption tracks are listed for the active sequence only."""
    cmds = ([("sequence.open", {"item": sequence})] if sequence is not None else []) + [("sequence.inspect", {}), ("captions.list", {})]
    results = run(source, cmds)
    return parse(results[-2], results[-1])
