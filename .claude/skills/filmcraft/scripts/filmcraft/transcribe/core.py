"""Where speech is, from a level envelope, and Whisper's word edges moved onto it. Pure: lists in, lists out."""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass
class Word:
    text: str
    start: float
    end: float
    prob: float = 1.0
    segment: int = -1


def speech_spans(env_db: list[float], hop: float, min_gap: float = 0.12, min_span: float = 0.08) -> list[tuple[float, float]]:
    """Stretches louder than a threshold set 30 % of the way from the noise floor (10th percentile, at least -70 dBFS) to the speech level (95th), joined across dips shorter than `min_gap`. Under continuous music nothing drops below the threshold, so speech comes back as one long stretch and only its outer edges can snap."""
    if not env_db:
        return []
    ordered = sorted(env_db)
    # digital silence would put the floor at -100 dBFS and the threshold among resampler ringing; nothing below -70 is audible speech
    floor = max(ordered[int(0.10 * (len(ordered) - 1))], -70.0)
    peak = ordered[int(0.95 * (len(ordered) - 1))]
    if peak - floor < 6:
        return []
    threshold = floor + 0.3 * (peak - floor)
    runs: list[list[int]] = []
    for i, v in enumerate(env_db):
        if v > threshold:
            if runs and i - runs[-1][1] - 1 < round(min_gap / hop):
                runs[-1][1] = i
            else:
                runs.append([i, i])
    return [(a * hop, (b + 1) * hop) for a, b in runs if (b + 1 - a) * hop >= min_span]


def _normalized(words: list[Word]) -> list[Word]:
    out = sorted((replace(w, text=w.text.strip(), end=max(w.end, w.start)) for w in words if w.text.strip()), key=lambda w: (w.start, w.end))
    for i in range(1, len(out)):
        if out[i - 1].end > out[i].start:
            out[i - 1].end = max(out[i].start, out[i - 1].start)
    return out


def snap(words: list[Word], spans: list[tuple[float, float]], max_shift: float, min_dur: float) -> tuple[list[Word], dict]:
    """Each word belongs to the speech span it overlaps most. An edge Whisper put in silence moves inward to the span edge (it stays inside the word, so order cannot break); the first word of a span may start earlier, and the last may end later, by at most `max_shift`. A word overlapping no speech keeps its time and is reported. Afterwards no word overlaps the one before it or lasts less than `min_dur`."""
    ws = _normalized(words)
    owner: list[int | None] = []
    for w in ws:
        best, best_ov = None, 0.0
        for k, (a, b) in enumerate(spans):
            ov = min(w.end, b) - max(w.start, a)
            if ov > best_ov:
                best, best_ov = k, ov
        owner.append(best)
    first: dict[int, int] = {}
    last: dict[int, int] = {}
    for i, k in enumerate(owner):
        if k is not None:
            first.setdefault(k, i)
            last[k] = i
    out: list[Word] = []
    for i, (w, k) in enumerate(zip(ws, owner)):
        if k is None:
            out.append(replace(w))
            continue
        a, b = spans[k]
        s, e = w.start, w.end
        if s < a < e:
            s = a
        elif a < s and first[k] == i and s - a <= max_shift:
            s = a
        if s < b < e:
            e = b
        elif e < b and last[k] == i and b - e <= max_shift:
            e = b
        out.append(replace(w, start=s, end=e))
    prev_end = float("-inf")
    for w in out:
        w.start = max(w.start, prev_end)
        w.end = max(w.end, w.start + min_dur)
        prev_end = w.end
    snapped = sum(1 for a, b in zip(ws, out) if abs(a.start - b.start) > 1e-6 or abs(a.end - b.end) > 1e-6)
    return out, {"snapped": snapped, "unmatched": [i for i, k in enumerate(owner) if k is None]}
