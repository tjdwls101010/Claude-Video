"""Words with times → caption cues: where each cue ends (a least-cost search over word boundaries), how its text splits into lines, and when it shows. Pure; widths come in as a `fits(line)` predicate."""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Callable

from .rules import Rules, chars, clean_line, is_clause_end, is_sentence_end, units


@dataclass
class Word:
    text: str
    start: float
    end: float
    speaker: str | None = None
    clip: int | None = None
    group: int = 0


@dataclass
class Cue:
    start: float
    end: float
    lines: list[str]


Fits = Callable[[str], bool]

HARD_PAUSE = 1.5
CUE_COST = 3.0


def _boundary_cost(ws: list[Word], j: int) -> float:
    """Cost of ending a cue after word j (0-based)."""
    w, nxt = ws[j], ws[j + 1]
    if is_sentence_end(w.text):
        return 0.0
    gap = nxt.start - w.end
    cost = 6.0
    if is_clause_end(w.text):
        cost = 2.0
    if gap >= 0.3 or (w.clip is not None and nxt.clip != w.clip):
        cost = min(cost, 1.0)
    return cost


def _hard(ws: list[Word], j: int) -> bool:
    w, nxt = ws[j], ws[j + 1]
    return w.speaker != nxt.speaker or w.group != nxt.group or nxt.start - w.end >= HARD_PAUSE


def split_lines(texts: list[str], rules: Rules, fits: Fits) -> tuple[list[str], float] | None:
    """Best 1- or 2-line layout of these words, with its cost; None when no split fits."""
    one = clean_line(" ".join(texts))
    if units(one) <= rules.max_units and fits(one):
        return [one], 0.0
    if rules.lines < 2 or len(texts) < 2:
        return None
    best = None
    for k in range(1, len(texts)):
        top, bottom = clean_line(" ".join(texts[:k])), clean_line(" ".join(texts[k:]))
        ut, ub = units(top), units(bottom)
        if ut > rules.max_units or ub > rules.max_units or not fits(top) or not fits(bottom):
            continue
        quality = 0.0 if is_sentence_end(texts[k - 1]) else 0.5 if is_clause_end(texts[k - 1]) else 2.0
        balance = 1.0 + (ut - ub) * 0.15 if ut > ub else (ub - ut) * 0.05
        cost = quality + balance
        if best is None or cost < best[1]:
            best = ([top, bottom], cost)
    return best


def _cue_cost(ws: list[Word], i: int, j: int, rules: Rules, fits: Fits):
    """Cost of words i..j (inclusive) as one cue, with its lines; None when it cannot be one cue."""
    if any(_hard(ws, k) for k in range(i, j)):
        return None
    dur = ws[j].end - ws[i].start
    if j > i and dur > rules.max_s:
        return None
    laid = split_lines([w.text for w in ws[i:j + 1]], rules, fits)
    if laid is None:
        if j > i:
            return None
        laid = ([clean_line(ws[i].text)], 10.0)  # one word too long for a line: unavoidable, reported later
    lines, cost = laid
    cost += CUE_COST + 4.0 * sum(1 for k in range(i, j) if is_sentence_end(ws[k].text))
    speed = chars(lines) / max(dur, 1e-3)
    if speed > rules.cps:
        cost += min(speed - rules.cps, 20.0) * 0.5
    if j + 1 < len(ws):
        cost += _boundary_cost(ws, j)
    return cost, lines


def group(ws: list[Word], rules: Rules, fits: Fits) -> list[tuple[int, int, list[str]]]:
    n = len(ws)
    best = [math.inf] * (n + 1)
    back: list[tuple[int, list[str]] | None] = [None] * (n + 1)
    best[0] = 0.0
    for j in range(1, n + 1):
        for i in range(j - 1, -1, -1):
            if j - 1 > i and ws[j - 1].end - ws[i].start > rules.max_s:
                break
            r = _cue_cost(ws, i, j - 1, rules, fits)
            if r is None:
                if any(_hard(ws, k) for k in range(i, j - 1)):
                    break
                continue
            c = best[i] + r[0]
            if c < best[j]:
                best[j], back[j] = c, (i, r[1])
    out = []
    j = n
    while j > 0:
        i, lines = back[j]
        out.append((i, j - 1, lines))
        j = i
    return out[::-1]


def time_cues(ws: list[Word], groups, rules: Rules, fps: Fraction, caps: dict[int, float] | None = None) -> list[Cue]:
    """Frame-aligned times: a cue starts on its first word and stays up long enough to read (and at least `min_s`), but not past the next cue less a small gap, nor past `caps[group]` when given."""
    f = float(fps)
    starts = []
    for i, _, _ in groups:
        s = math.floor(ws[i].start * f + 1e-6)
        if starts and s <= starts[-1]:
            s = starts[-1] + 1
        starts.append(s)
    cues = []
    for k, (i, j, lines) in enumerate(groups):
        s = starts[k]
        want = max(ws[j].end, s / f + chars(lines) / rules.cps, s / f + rules.min_s)
        want = min(want, s / f + rules.max_s)
        e = math.ceil(want * f - 1e-6)
        if k + 1 < len(groups):
            nxt = starts[k + 1]
            if e > nxt - rules.gap_frames or nxt - e < round(rules.close_gap_s * f):
                e = nxt - rules.gap_frames
        if caps and ws[j].group in caps:
            e = min(e, math.floor(caps[ws[j].group] * f + 1e-6))
        e = max(e, s + 1)
        cues.append(Cue(s / f, e / f, lines))
    return cues


def layout(words: list[Word], rules: Rules, fps, fits: Fits | None = None, caps: dict[int, float] | None = None) -> list[Cue]:
    ws = sorted((w for w in words if w.text.strip()), key=lambda w: (w.start, w.end))
    if not ws:
        return []
    fits = fits or (lambda line: True)
    return time_cues(ws, group(ws, rules, fits), rules, Fraction(fps), caps)


def relayout(cues: list[Cue], rules: Rules, fps, fits: Fits | None = None) -> list[Cue]:
    """Cues written elsewhere (a translation) laid out again: each cue's words share its time in proportion to their length, and every new cue stays inside the old cue it came from (a cue too short to read is reported, not stretched)."""
    words: list[Word] = []
    caps: dict[int, float] = {}
    for g, c in enumerate(sorted(cues, key=lambda c: c.start)):
        caps[g] = c.end
        toks = " ".join(c.lines).split()
        if not toks:
            continue
        weights = [max(units(t), 0.5) for t in toks]
        total, t = sum(weights), c.start
        for tok, wgt in zip(toks, weights):
            d = (c.end - c.start) * wgt / total
            words.append(Word(tok, t, t + d, group=g))
            t += d
    return layout(words, rules, fps, fits, caps)


def violations(cues: list[Cue], rules: Rules, fits: Fits | None = None) -> list[dict]:
    out = []
    for n, c in enumerate(cues, 1):
        dur = c.end - c.start
        speed = chars(c.lines) / max(dur, 1e-6)
        if speed > rules.cps + 1e-9:
            out.append({"cue": n, "kind": "cps", "value": round(speed, 1), "text": " / ".join(c.lines)})
        if dur < rules.min_s - 1e-6:
            out.append({"cue": n, "kind": "short", "value": round(dur, 3), "text": " / ".join(c.lines)})
        if len(c.lines) > rules.lines or any(units(l) > rules.max_units or (fits is not None and not fits(l)) for l in c.lines):
            out.append({"cue": n, "kind": "long_line", "value": max(units(l) for l in c.lines), "text": " / ".join(c.lines)})
    return out
