"""The Korean subtitle rules this skill lays out to (Netflix Korean Timed Text Style Guide, the de facto standard for Korean streaming subtitles; Korean broadcast guidance sets no character counts), and how text is counted against them."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rules:
    max_units: float = 16.0     # per line
    lines: int = 2
    cps: float = 12.0           # characters a second, spaces and punctuation included
    min_s: float = 5 / 6
    max_s: float = 7.0
    gap_frames: int = 2         # between cues that follow each other closely
    close_gap_s: float = 0.5    # a smaller gap is closed down to gap_frames


HELP = """\
Rules (Netflix Korean Timed Text Style Guide; Korean broadcast guidance gives no character counts) [practice]:
  a line holds 16 units: a Hangul syllable or CJK character is 1, a Latin letter, digit, space or punctuation mark 0.5, the ellipsis … 1
  at most 2 lines; when two, the bottom line is preferably the longer (pyramid), and a line breaks after a clause rather than inside one
  reading speed at most 12 characters a second (spaces and punctuation count); a fast cue stays up into the following silence to reach it
  each cue lasts 5/6 s to 7 s; cues that nearly touch are chained 2 frames apart
  no full stop or comma at the end of a line; ? and ! stay; three dots become …
  a cue ends at a speaker change and at a pause of 1.5 s, and prefers to end at a sentence end, then at a pause or a cut, then at a clause end"""


def units(text: str) -> float:
    total = 0.0
    for ch in text:
        o = ord(ch)
        if o < 0x2000:
            total += 0.5
        else:
            total += 1.0
    return total


def chars(lines: list[str]) -> int:
    return len(" ".join(lines))


_LINE_END = re.compile(r"[.,。，]+$")


def clean_line(line: str) -> str:
    """No full stop or comma at a line end; an ellipsis stays."""
    line = line.strip().replace("...", "…")
    if line.endswith("…"):
        return line
    return _LINE_END.sub("", line).rstrip()


# Where a Korean or English clause ends: a comma or semicolon, a connective ending (also with the polite 요 speech adds: 그래서요, 있는데요),
# or a sentence-final ending Whisper often leaves without a full stop (요, 니다, 죠).
_CLAUSE_END = re.compile(r"([,;:，、]|(?:고|서|며|면서|는데|은데|ㄴ데|지만|니까|으니까|아서|어서|해서|도록|려고|으면|면|거나|든지|다가|자마자)요?|요|니다|죠|(?:and|but|so|because))$")
_SENTENCE_END = re.compile(r"[.?!…。？！]['\"”’)]*$")


def is_sentence_end(word: str) -> bool:
    return bool(_SENTENCE_END.search(word.replace("...", "…")))


def is_clause_end(word: str) -> bool:
    return bool(_CLAUSE_END.search(word))
