"""ffmpeg and ffprobe as measuring instruments (stream facts, loudness, speech spans, still frames), and the encoder that turns rendered graphics into the alpha intermediate FilmCraft composites. Nothing here edits the user's media."""

from .encode import AlphaWriter
from .envelope import envelope
from .extract import extract_frame
from .loudness import Loudness, loudness
from .probe import AudioStream, Media, VideoStream, probe, tool

__all__ = ["probe", "Media", "VideoStream", "AudioStream", "loudness", "Loudness", "extract_frame", "envelope", "tool", "AlphaWriter"]
