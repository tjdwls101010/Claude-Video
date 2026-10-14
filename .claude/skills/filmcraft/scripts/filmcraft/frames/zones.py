"""Where vertical platforms draw their UI over a 1080x1920 frame. Platforms move these without notice; the numbers live here and in `frames --help` only."""

from __future__ import annotations

# margins = (top, bottom, left, right) in pixels on 1080x1920; extra = further UI rectangles (x0, y0, x1, y1). Both scale to other 9:16 sizes.
SAFE_ZONES = {
    "shorts": {"margins": (288, 672, 48, 192), "extra": [], "color": (255, 64, 64),
               "authority": "Google Ads 'Universal safe zones for video ads on YouTube', vertical 1080x1920 image"},
    "reels": {"margins": (269, 672, 65, 65), "extra": [(853, 1152, 1080, 1920)], "color": (64, 160, 255),
              "authority": "Meta Business Help 'text overlays and the safe zone': 14% top, 35% bottom, 6% sides, a bottom-right block 40% tall x 21% wide"},
    "tiktok": {"margins": (240, 660, 120, 120), "extra": [(780, 840, 1080, 1920)], "color": (255, 200, 0),
               "authority": "TikTok In-Feed Standard safe-zone template scaled from 720x1280; the extra block is the button column"},
}

HELP_TABLE = """\
Safe zones drawn by --overlay on 9:16 frames, scaled from 1080x1920: UI margins top/bottom/left/right, plus further UI blocks. They come from the platforms' ad guidance, the only published numbers; organic posts carry similar UI, and a longer caption pushes TikTok's bottom UI higher.
""" + "\n".join(f"  {k:7} {v['margins'][0]}/{v['margins'][1]}/{v['margins'][2]}/{v['margins'][3]} px" + (f" + blocks {v['extra']}" if v["extra"] else "") + f"  [platform spec: {v['authority']}]" for k, v in SAFE_ZONES.items()) + """
  all     every platform's UI shaded and each safe box outlined in its own colour: text and faces clear of all shading are safe on all three (roughly x 120..780, y 290..1150)."""
