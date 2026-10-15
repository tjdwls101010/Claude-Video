"""The installed Google Chrome as a frame-accurate renderer of one local page, driven by Playwright (channel "chrome"; nothing is downloaded). Playwright, the DevTools protocol and the page-side scripts stay inside this unit; callers get frames as PNG bytes, sound as float samples and font use in the skill's own terms. `VIDEO_CHROME_PATH` points it at another Chrome binary."""

from .page import FontUse, Page, Pcm, Timeouts, open_page

__all__ = ["open_page", "Page", "FontUse", "Pcm", "Timeouts"]
