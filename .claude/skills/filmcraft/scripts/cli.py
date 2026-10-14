# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow>=10"]
# ///
"""Tools FilmCraft lacks for editing from the shell: speech to word-timed transcripts, Korean caption layout, a compact timeline readout, frame contact sheets, and delivery QC. This file is the whole command surface (parser, help, dispatch, exit codes); what each command does lives in the `filmcraft` package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from filmcraft import frames, qc, timeline, transcribe
from filmcraft.errors import InputError, ToolError
from filmcraft.filmcraft_cli import Source

EXIT_OK, EXIT_TOOL, EXIT_USAGE, EXIT_QC_FAIL = 0, 1, 2, 3

ROOT_EPILOG = """\
Every command prints one JSON document on stdout; progress and diagnostics go to stderr.
Exit codes: 0 success; 1 an external tool (filmcraft-cli, ffmpeg, mlx-whisper) failed or is missing, and the JSON carries `error` and `stderr_tail`; 2 the command line must change, and the JSON carries `error` and the `help` to read; 3 only from `qc`, when a required check failed.
Commands that read a project take exactly one of --project P.fcproj (headless, the file on disk) or --bridge 127.0.0.1:PORT (the running app, including unsaved edits)."""

TIMELINE_DESC = """\
Read a sequence once and report it twice: a summary small enough to print for any clip count, and a detail file with every clip.
Prints: {"summary": {name, fps, size, duration_tc, tracks: [{name, clips, locked, muted}], clips, captions, markers, transitions}, "detail": "<--out path>"}. Tracks are named V1…, A1…, C1… as commands address them.
Detail file: {"sequence": {id, name, fps, drop_frame, size, duration_tc, duration_frames, in_tc, out_tc}, "clips": [{clip, item, name, track, start_tc, end_tc, src_in_s, src_out_s, speed, reverse, gain_db, effects, enabled, scale?, position?, opacity?}], "transitions": [{track, effect, start_tc, end_tc, from, to}], "markers": [{name, kind, start_tc, duration_frames, comment}], "captions": [{track, name, enabled, cues, font, size, anchor, margin, first_tc, last_end_tc}]}.
Timecodes count from 00:00:00:00 at the sequence's rate (drop-frame when the sequence uses it), ignoring any start timecode. end_tc is exclusive: the first frame after the clip. src_in_s/src_out_s are seconds of the source media. effects lists only effects applied on top of the built-in Motion/Opacity/Time Remapping/Volume/Channel Volume/Panner; scale, position and opacity appear only when changed from their defaults.
Exits: 0 written; 1 filmcraft-cli failed (no such project, no active sequence, the app not listening on the port); 2 the command line must change (both or neither of --project and --bridge)."""


QC_DESC = """\
Measure a rendered file (ffprobe streams, BS.1770 loudness and true peak via ffmpeg ebur128, MP4 box layout) and judge it against one delivery target. Technical QC only: whether cuts land or meaning survived is not judged.
Prints: {"file", "target", "pass", "failed": [check names], "warnings": [check names], "checks": [{name, value, expected, tolerance, level, pass, reason}]}. `pass` per check is true, false, or null when the value could not be measured (then `reason` says why).
Exits: 0 nothing required failed (warnings allowed); 3 a required check failed, named in `failed`; 2 the file is missing or not media, or the command line must change; 1 ffmpeg/ffprobe is missing or failed.
When a loudness fix is needed, re-export with file.exportMedia loudnessLufs set to the target; FilmCraft's true-peak limiter wins over the integrated target, so a file that still misses after two re-exports is reported with its measurements instead of exported again.

"""


FRAMES_DESC = """\
Look at an edit without playing it: frames laid out as one contact sheet, each labelled with its timecode.
--project renders through FilmCraft (headless), so captions, titles and effects show as exported (captions are drawn even when an export would not burn them). --media extracts from a file with ffmpeg, for scanning source material.
To check what the running app shows, unsaved edits included: send `file.saveCopy {"path": "/abs/copy.fcproj"}` over --bridge (it leaves the app's own path and dirty state alone), then run frames --project on that copy. One frame from the app itself: the MCP tool render_frame.
Prints: {"sheet": "<--out path>", "frames": [{"t": seconds, "tc": "HH:MM:SS:FF"}], "size": "WxH of one tile", "grid": {cols, rows, tile_w, tile_h, cell_h}, "notes": [...]}. Read the sheet image to see the frames.
Exits: 0 written; 2 the command line must change (--cuts without --project, more than 100 frames, a time that cannot be read, a file that is not video); 1 filmcraft-cli or ffmpeg failed (offline media in the project, no active sequence).

"""


TRANSCRIBE_DESC = f"""\
Speech to a word-timed FilmCraft transcript, because this FilmCraft build cannot transcribe (transcript.generate and transcript.downloadModel are disabled).
Runs mlx-whisper (default {transcribe.DEFAULT_MODEL}, about 1.6 GB, downloaded to ~/.cache/huggingface on first use; ask before that first download) with word timestamps, measures where speech is from the audio level, and moves Whisper's word edges onto it: an edge Whisper put in silence moves inward to the speech edge, however far, staying inside the word; the first word of a stretch of speech may start earlier, and the last may end later, by at most --max-shift. A word with no speech under it keeps Whisper's time. Under continuous music the level never drops, so only the outer edges of that passage can move.
Writes --out as one `transcript.set` line (media-time ticks, Whisper's word probability as confidence), plus <out>.txt (one line per Whisper segment: [w<first>-w<last>] start-end text, the word indices those commands take) and <out>.whisper.json (the raw recognition, reusable with --from-json).
Before applying: correct misrecognised words (names, terms) by editing the text fields of --out in place, keeping start/end. Then apply with the `next` command; the transcript attaches to the media item, so every clip of it in every sequence gets it.
Prints: {{"item", "language", "words", "seconds", "speech_seconds", "snapped" (words with an edge moved), "unmatched" (words over no speech), "review": [{{"i", "text", "start_s", "reason"}}] (at most {transcribe.REVIEW_SHOWN}; the rest in review_file), "review_total", "out", "text", "whisper_json", "next"}}.
Review reasons: low_prob (Whisper's word probability below {transcribe.LOW_PROB}); unmatched (no speech measured under the word); repeat (the same line in three or more consecutive segments, Whisper's usual hallucination over music or silence); no_speech (a segment Whisper's own no-speech test rejects). Listen-free check: a repeat or no_speech line over background music is almost always invented; delete those words from --out before applying.
Exits: 0 written; 2 the media is missing or has no audio, or --from-json is not mlx-whisper JSON; 1 ffmpeg, uvx or mlx-whisper failed.

"""


def size_arg(text: str) -> tuple[int, int]:
    try:
        w, h = text.lower().split("x")
        return int(w), int(h)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected WxH like 1080x1920, got {text!r}")


class Parser(argparse.ArgumentParser):
    """Usage errors print JSON on stdout like every other reply, naming the --help to read."""

    def error(self, message):
        print(json.dumps({"error": message, "help": f"{self.prog} --help"}, ensure_ascii=False))
        sys.exit(EXIT_USAGE)


def add_source(p: argparse.ArgumentParser) -> None:
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--project", type=Path, metavar="P.fcproj", help="read this project file headless (what is saved on disk)")
    g.add_argument("--bridge", metavar="127.0.0.1:PORT", help="read the running app started with --control PORT (includes unsaved edits)")


def source_of(a) -> Source:
    return Source(project=a.project.resolve()) if a.project is not None else Source(bridge=a.bridge)


def build_parser() -> argparse.ArgumentParser:
    fmt = argparse.RawTextHelpFormatter
    root = Parser(prog="cli.py", description=__doc__, epilog=ROOT_EPILOG, formatter_class=fmt)
    sub = root.add_subparsers(dest="command", required=True, metavar="<command>", parser_class=Parser)

    p = sub.add_parser("timeline", help="summary of a sequence on stdout, every clip in a detail file", description=TIMELINE_DESC, formatter_class=fmt)
    add_source(p)
    p.add_argument("--sequence", type=int, metavar="ITEM", help="the sequence's project item id (default: the active sequence). Naming one makes it active, which in the app brings its timeline tab to the front")
    p.add_argument("--out", type=Path, required=True, metavar="DETAIL.json", help="where to write the detail document (parent folders are created)")
    p.set_defaults(run=lambda a: timeline.report(source_of(a), a.out.resolve(), a.sequence))

    p = sub.add_parser("qc", help="technical delivery checks of a rendered file against a target", description=QC_DESC + qc.HELP_TABLE, formatter_class=fmt)
    p.add_argument("file", type=Path, metavar="FILE", help="the rendered file (MP4 expected)")
    p.add_argument("--target", required=True, choices=list(qc.TARGETS), help="which delivery the file is for")
    p.add_argument("--expect-size", type=size_arg, metavar="WxH", help="required frame size, e.g. 1920x1080 (display size, after rotation metadata)")
    p.add_argument("--expect-fps", type=float, metavar="F", help="required frame rate, e.g. 29.97 (within 0.01)")
    p.add_argument("--expect-duration", type=float, metavar="S", help="required duration in seconds, within one frame")
    p.set_defaults(run=run_qc)

    p = sub.add_parser("frames", help="contact sheet of rendered or extracted frames, optionally with safe zones", description=FRAMES_DESC + frames.HELP_TABLE, formatter_class=fmt)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--project", type=Path, metavar="P.fcproj", help="render the project's active sequence through FilmCraft (headless)")
    src.add_argument("--media", type=Path, metavar="FILE", help="extract frames from a media file with ffmpeg")
    pick = p.add_mutually_exclusive_group(required=True)
    pick.add_argument("--at", nargs="+", metavar="T", help="times: seconds (12.5) or timecode (00:00:12:15) at the sequence's or file's rate")
    pick.add_argument("--cuts", action="store_true", help="the first frame of every video clip (needs --project)")
    pick.add_argument("--every", type=float, metavar="SEC", help="one frame every SEC seconds from the start")
    p.add_argument("--overlay", choices=[*frames.SAFE_ZONES, "all"], help="draw a vertical platform's UI areas and safe box (9:16 frames only)")
    p.add_argument("--cols", type=int, default=4, metavar="N", help="tiles per row (default 4)")
    p.add_argument("--width", type=int, metavar="PX", help="width of one tile (default 480 landscape, 320 vertical)")
    p.add_argument("--out", type=Path, required=True, metavar="SHEET.png", help="where to write the sheet")
    p.set_defaults(run=lambda a: frames.sheet(a.out.resolve(), project=a.project.resolve() if a.project else None, media=a.media.resolve() if a.media else None,
                                              at=a.at, every=a.every, cuts=a.cuts, overlay=a.overlay, cols=a.cols, width=a.width))

    p = sub.add_parser("transcribe", help="mlx-whisper words snapped to measured speech, as a transcript.set line", description=TRANSCRIBE_DESC, formatter_class=fmt)
    p.add_argument("media", type=Path, metavar="MEDIA", help="the media file the project item points at")
    p.add_argument("--item", type=int, required=True, metavar="ID", help="its project item id (inspect project lists them)")
    p.add_argument("--out", type=Path, required=True, metavar="X.jsonl", help="where to write the transcript.set line (siblings .txt and .whisper.json go next to it)")
    p.add_argument("--language", metavar="CODE", help="spoken language, e.g. ko or en (default: Whisper detects it)")
    p.add_argument("--model", default=transcribe.DEFAULT_MODEL, metavar="REPO", help=f"mlx-whisper model (default {transcribe.DEFAULT_MODEL})")
    p.add_argument("--max-shift", type=float, default=0.5, metavar="SEC", help="how far an outer edge of a stretch of speech may move outward (default 0.5)")
    p.add_argument("--from-json", type=Path, metavar="W.json", help="reuse an mlx-whisper JSON from an earlier run instead of running the model")
    p.set_defaults(run=lambda a: transcribe.transcribe(a.media.resolve(), a.item, a.out.resolve(), a.language, a.model, a.max_shift, a.from_json.resolve() if a.from_json else None))
    return root


def run_qc(a) -> dict:
    out = qc.check(a.file.resolve(), a.target, a.expect_size, a.expect_fps, a.expect_duration)
    out["_exit"] = EXIT_OK if out["pass"] else EXIT_QC_FAIL
    return out


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        out = args.run(args)
    except InputError as e:
        print(json.dumps({"error": str(e), "help": f"cli.py {args.command} --help"}, ensure_ascii=False))
        return EXIT_USAGE
    except ToolError as e:
        print(json.dumps(e.as_json(), ensure_ascii=False))
        return EXIT_TOOL
    code = out.pop("_exit", EXIT_OK) if isinstance(out, dict) else EXIT_OK
    print(json.dumps(out, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
