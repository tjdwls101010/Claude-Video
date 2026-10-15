"""Laying frames out as one labelled sheet, with optional safe-zone overlays."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .zones import SAFE_ZONES

LABEL_H = 26


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def overlay(tile: Image.Image, platforms: list[str]) -> Image.Image:
    """Shade the UI bands of every platform named and outline each one's safe box, scaled from 1080x1920."""
    w, h = tile.size
    sx, sy = w / 1080, h / 1920
    shade = Image.new("RGBA", tile.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(shade)
    for p in platforms:
        top, bottom, left, right = SAFE_ZONES[p]["margins"]
        r, g, b = SAFE_ZONES[p]["color"]
        boxes = [(0, 0, w, top * sy), (0, h - bottom * sy, w, h), (0, 0, left * sx, h), (w - right * sx, 0, w, h)]
        boxes += [(x0 * sx, y0 * sy, x1 * sx, y1 * sy) for x0, y0, x1, y1 in SAFE_ZONES[p]["extra"]]
        for box in boxes:
            d.rectangle(box, fill=(r, g, b, 70))
    out = Image.alpha_composite(tile.convert("RGBA"), shade)
    d = ImageDraw.Draw(out)
    for p in platforms:
        top, bottom, left, right = SAFE_ZONES[p]["margins"]
        d.rectangle((left * sx, top * sy, w - right * sx - 1, h - bottom * sy - 1), outline=SAFE_ZONES[p]["color"] + (255,), width=2)
    return out.convert("RGB")


def compose(images: list[Path], labels: list[str], out: Path, cols: int, platforms: list[str]) -> dict:
    tiles = [Image.open(p).convert("RGB") for p in images]
    tw, th = tiles[0].size
    tiles = [t if t.size == (tw, th) else t.resize((tw, th)) for t in tiles]
    if platforms:
        tiles = [overlay(t, platforms) for t in tiles]
    cols = max(1, min(cols, len(tiles)))
    rows = -(-len(tiles) // cols)
    cell_h = th + LABEL_H
    sheet = Image.new("RGB", (cols * tw, rows * cell_h), (16, 16, 16))
    draw = ImageDraw.Draw(sheet)
    font = _font(16)
    for i, (t, label) in enumerate(zip(tiles, labels)):
        x, y = (i % cols) * tw, (i // cols) * cell_h
        sheet.paste(t, (x, y))
        draw.text((x + 6, y + th + 4), label, fill=(235, 235, 235), font=font)
        draw.line((x, y, x, y + cell_h), fill=(16, 16, 16), width=1)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return {"cols": cols, "rows": rows, "tile_w": tw, "tile_h": th, "cell_h": cell_h}
