"""Delivery criteria per target, with the kind of authority behind each number. Platforms change these without notice, so they live here and in `qc --help` (this table), not in prose."""

from __future__ import annotations

# Level of each check per target: fail = required, warn = advice, info = recorded only. Checks not named are info.
_SPEC = {"container": "fail", "video_codec": "warn", "audio": "fail", "integrated_loudness": "fail", "true_peak": "fail", "moov_position": "warn"}
TARGETS = {
    "youtube": {**_SPEC, "video_profile": "warn", "audio_codec": "warn", "sample_rate": "warn", "channels": "warn"},
    "shorts": dict(_SPEC),
    "reels": dict(_SPEC),
    "tiktok": dict(_SPEC),
    "broadcast-kr": {"audio": "fail", "integrated_loudness": "fail", "true_peak": "warn"},
}

_LOUD = {"target": -14.0, "pass": 1.0, "warn": 2.0}
LIMITS = {
    "youtube": {"loudness": _LOUD, "true_peak": -1.0},
    "shorts": {"size": (1080, 1920), "max_duration": 180, "loudness": _LOUD, "true_peak": -1.0},
    "reels": {"size": (1080, 1920), "max_duration": 1200, "advised_duration": (180, "Reels over 3 minutes are not recommended to new audiences"), "min_fps": 30, "loudness": _LOUD, "true_peak": -1.0},
    "tiktok": {"size": (1080, 1920), "max_duration": 3600, "advised_duration": (1800, "web uploads stop at 30 minutes; longer ones go through the app"), "loudness": _LOUD, "true_peak": -1.0},
    "broadcast-kr": {"loudness": {"target": -24.0, "pass": 2.0}, "true_peak": -1.0},
}

HELP_TABLE = """\
Criteria. Level: fail = required (exit 3), warn = advice, info = recorded only. Authority in brackets: [regulation] law; [platform spec] the platform's own help or upload-spec page; [measured] observed platform behaviour with no published number; [practice] industry convention; [decision] chosen for this skill.
  youtube
    container MP4 fail; H.264 warn, High profile warn; AAC-LC warn, 48 kHz warn, stereo warn; moov at the start (fast start) warn  [platform spec: support.google.com/youtube/answer/1722171]
    size, fps, duration: only what --expect-* names (fail; duration within ±1 frame)
    integrated loudness -14 LUFS: ±1 pass, ±2 warn, beyond fail  [measured: YouTube turns louder uploads down to about -14 and publishes no number]
    true peak <= -1 dBTP fail  [practice]
    edit list recorded only  [decision: FilmCraft writes one and it is kept, although the YouTube page above asks for none]
  shorts
    1080x1920 fail  [decision: FilmCraft's Social Vertical preset; Shorts are square or vertical and at most 1080p (platform spec)]
    duration <= 180 s fail  [platform spec: Shorts are up to 3 minutes]
    container, codec, fast start, loudness and true peak as youtube
  reels
    1080x1920 fail  [decision; the platform spec gives 9:16 to 1.91:1, at least 720 px and 30 fps]
    duration <= 1200 s fail, over 180 s warn  [platform spec: up to 20 minutes; over 3 minutes not recommended to new audiences]
    fps below 30 warn  [platform spec]
    loudness -14 LUFS bands as youtube  [practice: Meta publishes no number]; the rest as youtube
  tiktok
    1080x1920 fail  [decision; the platform spec asks for at least 720x1280]
    duration <= 3600 s fail, over 1800 s warn  [platform spec: in-app uploads up to 60 minutes, web uploads up to 30]
    loudness -14 LUFS bands as youtube  [practice: TikTok publishes no number]; the rest as youtube
  broadcast-kr
    integrated loudness -24 LKFS ±2 fail  [regulation: 디지털 텔레비전 방송프로그램 음량 등에 관한 기준 제3조]
    true peak <= -1 dBTP warn  [practice: the notice sets no true-peak limit; the TTA standard it cites was not checked]
    audio present fail; everything else recorded only
  every target: an audio stream is required (fail) [decision]; any --expect-* given is required (fail).
A value that cannot be measured (no audio stream; silence below the -70 LUFS gate) is null with a `reason` and counts as a warning."""
