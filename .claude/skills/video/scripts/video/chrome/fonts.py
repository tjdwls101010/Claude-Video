"""Which faces Chrome really drew a page's text with, asked through DevTools `CSS.getPlatformFontsForNode`.

That call names faces by their legacy family name ("Paperlogy 7 Bold" for CSS "Paperlogy"), so comparing names would fail correct pages. Instead each text is drawn twice more, offscreen, with its first family followed by one of two different installed Hangul faces: if the family really draws that text, both copies use the same face; if it is missing or lacks some glyphs, the copies diverge. Text in a script neither of those faces covers (Arabic, emoji) falls through to the same system face either way, so a third copy drops the family: if the text draws the same without it, and no face that drew it carries the family's name, another face stood in. `document.fonts.check` is not used: it answers true for families that do not exist."""

from __future__ import annotations

SENTINELS = ("Apple SD Gothic Neo", "AppleMyungjo")
ABSENT = "video-graphic-absent-family"
GENERIC = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-serif", "ui-sans-serif", "ui-monospace", "ui-rounded", "emoji", "math", "fangsong"}

# Elements with text of their own that can be seen now (not display:none, visibility:hidden, or under opacity 0), tagged for DevTools to find.
MARK = """() => {
  const seen = el => { for (let e = el; e; e = e.parentElement) if (parseFloat(getComputedStyle(e).opacity) === 0) return false; return true };
  const out = [];
  let n = 0;
  for (const el of document.body ? [document.body, ...document.body.querySelectorAll('*')] : []) {
    if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE'].includes(el.tagName)) continue;
    const text = [...el.childNodes].filter(c => c.nodeType === 3).map(c => c.textContent).join('');
    if (!text.trim()) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || el.getClientRects().length === 0 || !seen(el)) continue;
    const id = 'v' + (n++);
    el.setAttribute('data-video-text', id);
    out.push({id, family: cs.fontFamily, text, weight: cs.fontWeight, style: cs.fontStyle, stretch: cs.fontStretch});
  }
  return out;
}"""

# Probes hang off <html> in tags no page stylesheet names, every property set inline with !important, so page CSS cannot restyle them.
ADD_PROBES = """([items, sentinels, absent]) => {
  const set = (el, props) => { el.style.setProperty('all', 'initial', 'important'); for (const [k, v] of Object.entries(props)) el.style.setProperty(k, v, 'important') };
  const box = document.createElement('video-font-probes');
  set(box, {position: 'absolute', left: '-100000px', top: '0', display: 'block', visibility: 'visible', 'white-space': 'pre'});
  for (const it of items) [it.quoted + ', "' + sentinels[0] + '"', it.quoted + ', "' + sentinels[1] + '"', '"' + absent + '", "' + sentinels[0] + '"'].forEach((stack, i) => {
    const span = document.createElement('video-font-probe');
    span.setAttribute('data-video-probe', it.id + '-' + i);
    set(span, {display: 'inline', visibility: 'visible', 'white-space': 'pre', 'font-family': stack, 'font-weight': it.weight, 'font-style': it.style, 'font-stretch': it.stretch});
    span.textContent = it.text;
    box.appendChild(span);
  });
  document.documentElement.appendChild(box);
  return new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
}"""

CLEAN = """() => {
  document.querySelectorAll('video-font-probes').forEach(e => e.remove());
  document.querySelectorAll('[data-video-text]').forEach(e => e.removeAttribute('data-video-text'));
}"""


def first_family(css: str) -> str:
    """The first entry of a computed font-family list, unquoted."""
    out, quote, buf = [], None, ""
    for ch in css:
        if quote:
            if ch == quote:
                quote = None
            else:
                buf += ch
        elif ch in "\"'":
            quote = ch
        elif ch == ",":
            out.append(buf.strip())
            buf = ""
        else:
            buf += ch
    out.append(buf.strip())
    return out[0] if out else ""


def _faces(cdp, root: int, selector: str) -> list[dict]:
    node = cdp.send("DOM.querySelector", {"nodeId": root, "selector": selector})["nodeId"]
    return cdp.send("CSS.getPlatformFontsForNode", {"nodeId": node})["fonts"] if node else []


def sample(page, cdp) -> list[dict]:
    """Every visible text element now: {"family" (first family asked for), "faces": [(face, glyphs)], "fallback", "text"}."""
    items = page.evaluate(MARK)
    for it in items:
        it["first"] = first_family(it["family"])
        it["quoted"] = '"' + it["first"].replace('"', '\\"') + '"'
    probed = [it for it in items if it["first"].lower() not in GENERIC]
    try:
        if probed:
            page.evaluate(ADD_PROBES, [probed, list(SENTINELS), ABSENT])
        root = cdp.send("DOM.getDocument", {"depth": -1})["root"]["nodeId"]
        out = []
        for it in items:
            used = _faces(cdp, root, f'[data-video-text="{it["id"]}"]')
            faces = [(f["familyName"], int(f.get("glyphCount", 0))) for f in used]
            # a generic family is Chrome's per-script choice, not a face that was asked for
            fallback = it in probed and len(used) > 1
            if not fallback and it in probed:
                a, b, without = ([f["postScriptName"] for f in _faces(cdp, root, f'[data-video-probe="{it["id"]}-{i}"]')] for i in range(3))
                named = any(it["first"].lower() in f["familyName"].lower() for f in used)
                fallback = a != b or [f["postScriptName"] for f in used] != a or (without == a and not named)
            out.append({"family": it["first"], "faces": faces, "fallback": fallback, "text": " ".join(it["text"].split())[:40]})
        return out
    finally:
        page.evaluate(CLEAN)
