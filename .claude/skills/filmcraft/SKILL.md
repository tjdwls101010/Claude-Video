---
name: filmcraft
description: >-
  Edit video with FilmCraft, the open-source Premiere-style editor installed on this Mac, through `filmcraft-cli` (headless) or the running app (bridge): cuts and transcript-based edits, vertical Shorts/Reels/TikTok, highlight and music montages, audio mix and loudness, color correction, Korean captions and titles, QC-checked exports, and handoff to Premiere or Resolve. Use whenever the user wants a video cut, captioned, reframed, graded, mixed or exported, or mentions FilmCraft or a .fcproj. Triggers include: 영상 편집, 컷편집, 자막, 쇼츠, 릴스, 하이라이트, 몽타주, 색보정, 내보내기, 유튜브 업로드용, .fcproj, FilmCraft. Not for developing FilmCraft's own source code.
allowed-tools:
  - Bash(filmcraft-cli *)
  - Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)
  - Bash(ffprobe *)
---

# Editing video with FilmCraft

FilmCraft exposes about 700 commands; `filmcraft-cli commands <filter>` and `filmcraft-cli describe <id>` own their parameters. This skill holds what those do not say, and five tools FilmCraft lacks, called as `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" transcribe|captions|timeline|frames|qc …`; each `<tool> --help` owns its numbers, outputs and exit codes.

## What finished means

- The saved `.fcproj` reopens in a fresh process with the edit intact: `timeline --project` on it matches what you report.
- Every rendered deliverable passes `qc` for its target. Re-export at most twice for a qc failure; if it still fails (FilmCraft's true-peak limiter wins over a loudness target), stop and report the measurements.
- You looked at the result: `frames` at every cut and every frame with text, and the final cut's words (`transcript.inspect`) read through for a sentence cut off or a splice that changes what someone said.
- The report says what changed, the editorial calls you made (fillers cut or kept, a name you guessed), and what you could not verify. You cannot hear the cut, so how its audio flows is always unverified.
- Edit only in FilmCraft, so the user can open the project and change it; ffmpeg and ffprobe only measure. The one exception, the user's decision: a lossless `ffmpeg -i IN -c copy -movflags +faststart OUT` on the final MP4.
- Fixed: what people said and meant, the length, aspect and platform the user named, a project that reopens, the target's qc criteria. Yours to choose, with the reason in the report: shots, rhythm, caption and title design, transition style.

## Before the first command

- Compare `filmcraft-cli --version` with the app's version (`defaults read /Applications/FilmCraft.app/Contents/Info CFBundleShortVersionString`). If the CLI is missing or differs, install the matching one: `gh release download v<ver> -R storytold/filmcraft -p 'filmcraft-cli-<ver>-macos-universal.zip' -p SHA256SUMS.txt`, check `shasum -a 256` against SHA256SUMS.txt, unzip, put `filmcraft-cli` in `~/.local/bin`. A project saved by a CLI newer than the app can have a schema the app refuses to open.
- FilmCraft ships every day or two. When this skill, `describe` and what actually happens disagree, trust what happens and say so. After an update, `uv run --with pytest --with pillow pytest tests/filmcraft_facts` in this repository shows which sentences here went stale.

## Headless or the running app

- By default work headless: `filmcraft-cli --project P.fcproj --save …`. There is no window, no autosave and no recovery journal, so saving is your job.
- When the user wants to watch or work along, or the project is open in the app, use the last section.
- Never edit on disk a `.fcproj` the app has open: whichever saves second throws the other's work away.

## How the CLI fails quietly

- Unfiltered `commands` prints about 160 000 characters; filter it (`commands caption`) and `describe` the one you need.
- Every call is a fresh session. Without `--save` (or `--save-as`) the edit is gone, though the call printed new ids and exited 0. Chain dependent steps in one `run steps.jsonl --save`: a failing line stops the run before anything is saved (`--keep-going` runs the rest and saves the partial result). Selection, track targeting and the Source monitor do not carry over between calls, so pass ids (`clips`, `items`) wherever `describe` offers them.
- Wrong values are dropped without an error: a float in `time` (ticks are integers; use `seconds`), a misspelt key, an unknown CLI option (`--brige=…` runs on an empty headless session). Read every result: `cuts:0`, `null`, an unchanged `durationFrames` or `path:null` means nothing happened.
- `exec file.exportMedia` returns a job id at once and a headless process exits with it, writing nothing. Pass `"wait": true`, or use the `export` subcommand, which waits.
- zsh does not split an unquoted `$OPTS` into words; write the options out.
- Time and ids: `timecode` ignores the sequence's start timecode, and Mark Out includes its frame. `timeline.razor` without `track` or `clip` cuts every track, and the right-hand pieces get new ids, so read them back before the next step. `graphics.*` take `track` as a 0-based index. `file.newSequenceFromClip` makes only the tracks the clip needs (V1/A1); `sequence.addTracks` before placing on V2.
- Defaults `describe` does not show: `clip.audioGain` without `mode` adds to the current gain; `clip.speedDuration` without `reverse` turns reverse playback off; `sequence.linkedSelection` without `on` toggles.

## Command families by job

- Assemble and trim: `timeline.*` (`place`, `move`, `trim`, `roll`, `slip`, `slide`), `sequence.*`. Headless, use `timeline.*` rather than `trim.*` or `source.*`, which act on monitor state that does not survive between calls.
- Speech: `transcript.*`. Captions: `captions.*`. Text and shapes: `graphics.*` (template names contain an en dash –).
- Effects and keyframes: `effects.*`; hiding a region (a face, a plate): `masks.*` with a blur effect, tracked.
- Color: `lumetri.*`, `lut.*`, `scopes.read`. Sound: `essentialSound.*`, `clip.audioGain`, `mixer.*`.
- Multicam: `clip.synchronize {method:"audio"}` → `clip.createMulticam` → `multicam.*`. Speed and holds: `clip.speedDuration`, `clip.frameHold*`; time-remapping keyframes do not render.
- Media: `media.*`. Markers: `markers.*`. Export: `export` or `file.exportMedia`. Narration (`tts.*`) speaks English only; Korean text is refused.
- Handoff: FCP7 XML (`file.exportFcp7Xml`) for Premiere and Resolve, OTIO for Resolve, AAF/OMF for Avid and Pro Tools, EDL for a plain cut list. Lumetri and FilmCraft-only effects do not travel; say which.
- A `.prproj` cannot be opened: ask for an FCP7 XML, AAF or OTIO export from Premiere. Importing one merges it into the open project.

## Seeing and hearing the edit

- You cannot play anything. Sources: `frames --media` for picture, `transcribe` for speech. The edit: `timeline` (raw `inspect sequence` runs about 2 KB per clip), `frames --project` (`--overlay` on vertical), and `qc` on the export.
- `render` and `frames --project` draw captions; an export burns them only with `burnCaptions: true`.
- FilmCraft renders on the CPU and slowly from 10-bit AV1/HEVC (seconds a frame, even at quarter size): ask for the frames you need, not `--every 1` over a long timeline.

## Editorial judgment

- Cut what carries no meaning (false starts, retakes, dead air, fillers) and keep breath, 0.15–0.3 s each side, so speech does not run into itself. A filler that carries meaning (the hesitation is the point, a laugh) stays, and the report says so.
- Cut in the silence at a word boundary, never inside a word, and give each dialogue cut a 2–4 frame audio crossfade.
- Cut straight by default. A dissolve says time passed or the place changed; one at every cutaway in and out, or between shots of one scene, reads as a beginner's habit. Dissolve for a real change of time or place, for a montage styled that way on purpose, or when asked.
- Keep whoever is speaking in frame; reframing a two-shot or split screen to vertical means following the speaker section by section.
- Text on screen must be right. Correct misheard names and terms before captions: a wrong name burned into a published video stays wrong. When unsure, keep your best guess and list it in the report. Never splice speech into something the speaker did not mean.
- Do not stack text: no captions over burned-in subtitles or broadcast supers, no titles under platform UI. If the source already carries burned-in subtitles, deliver captions as a sidecar or place yours where they do not collide.
- Dialogue intelligibility comes before music and effects.

## Speech as material

When: talking heads, interviews, lectures, meetings, summaries, anything captioned.

- This release cannot transcribe (`transcript.generate` and `downloadModel` are disabled); do not chase models. `transcribe MEDIA --item ID --out X.jsonl`, read its `review`, fix misheard words in the text fields of X.jsonl (keep the times; delete `repeat` and `no_speech` lines over music), then apply with its `next`. Ask before the first model download (about 1.6 GB).
- Choosing: `transcript.inspect` and `transcript.search` give word indices; `transcript.select` plus `extract` (ripple) or `lift` cut by words. A summary cuts at sentence ends and keeps each question with its answer.
- Fillers: `transcript.removeFillers` defaults to English fillers. Korean candidates are 음, 어, 아, 그, 저, 뭐 standing alone; discourse markers (그러니까, 이제, 약간) are a judgment call. Remove fillers before pauses; the other order leaves a gap where each filler was.
- Pauses: `transcript.removePauses` leaves `keepSeconds` on both sides of each pause, so a pause shrinks to at least twice that (frame snapping can leave more, and a pause with nothing left after snapping stays). Set keep to half the gap you want.
- Captions: `captions` (from the sequence, or `--cues` for a translation you wrote as SubRip), then run both commands in its `next` and check the import's `warnings` is empty. Not `transcript.createCaptions` (English line lengths; it runs a short sentence into the next), and not `captions.add`/`setTimes` (they refuse overlaps; import is lenient). Rewrite any cue `violations` lists as too fast.
- Captions go bottom centre; when burned-in text holds the bottom, `--anchor top` or a larger `--margin`. Burned-in captions plus a sidecar show twice on YouTube: one per delivery.

## On-screen text

When: captions, titles, lower thirds, any text layer.

- The default font, Inter, has no Hangul: Korean draws as boxes. Set an installed Korean family (`fonts.list`; Apple SD Gothic Neo, Noto Sans KR) on every caption track and text layer, then look at a render.
- Caption `size` is relative to a 1080-line frame, so the same size is 1.78 times taller at 1080×1920. `captions` accounts for it; a style set by hand does not.
- Broadcast supers: never repeat them in captions; cover one only on purpose (a re-edit for another outlet), and say so.

## Changing the frame shape

When: the delivery's aspect ratio differs from the source's.

- The sequence takes the delivery's size and the source's frame rate (60p stays 60p).
- A clip of another size lands at its own size: `clip.fillFrame` (or `clip.fitToFrame` to letterbox).
- Place the subject inside the safe box with Motion position and scale (`effects.setParam`). The `auto_reframe` effect guesses; check it with `frames --overlay`.
- Platform UI covers parts of a vertical frame: keep text and faces clear of every shaded area of `frames --overlay all`. Its numbers (in `frames --help`) are the platforms' ad guidance; organic posts carry similar UI, not identical.
- Upscaling loses detail; say by how much. Phone media: rotation metadata is honoured; HEIC stills and EXIF rotation are not supported; HDR (HLG, PQ) is tone-mapped automatically into an SDR sequence.

## Many clips and music

When: montages, highlight reels, B-roll, music-driven edits.

- Survey with `frames --media F --every N` and `clip.sceneEditDetection {wait:true, applyCuts:false, generateMarkers:true}`.
- Choose by content: variety, a strong first shot, no shot twice, cut on action. Cycling through the sources in order regardless of what they show is the failure to avoid.
- Measure the music's beat (ffmpeg energy onsets) instead of trusting a BPM in its title. Put cuts on beats rounded to frames without letting the rounding accumulate, and end on the end of a phrase; fade out only when no phrase ends near the target length.
- B-roll: straight cuts that cover a gap in the speech or show what is being said, with the dialogue carried under by J/L cuts.
- Assemble with `timeline.place {item|items, track, frame|seconds, sourceIn, duration}` (ticks are integers).
- Ducking: `essentialSound.setType` (dialogue, music), the `ducking.*` keys of `essentialSound.set` on the music, then `essentialSound.generateDucking` (it refuses dialogue clips). Fades at the ends: `sequence.applyAudioTransition`.

## Color

When: a grade is asked for, or the picture is clearly off (log footage, a colour cast, under-exposure).

- Order: basic correction (exposure, white balance), then shot matching, then a look, then a vignette.
- Judge by numbers: `scopes.read` (neutral RGB, waveform 0–100 %, skin tones). Lumetri parameter ids come from `effects.list detail=true`; `lumetri.applyMatch` reports `distanceBefore` and `distanceAfter`.
- Log footage takes an input LUT first (`lumetri.setInputLut`, built-in S-Log3 and others to Rec. 709); creative LUTs go in `lumetri.setLook`. Measure each clip before calling it log: a clip already in display range needs only a light touch.
- Never derive a correction from a test chart or pattern in the footage; grade the picture people will watch.

## Delivery

- Every export: `range: "entire"` (the default is In to Out), `burnCaptions` and `captionSidecar` as intended, `loudnessLufs` at the qc target (BS.1770 with a true-peak limiter), `"wait": true` under `exec`.
- Presets: "YouTube 1080p Full HD" for YouTube, "Social Vertical 1080×1920" for vertical. `hardwareEncoding: "auto"` is much faster (not with CRF or 2-pass); H.265 needs hardware encoding, and there is no AV1 export.
- Offline media renders as placeholder frames: fix it with `media.findMissing`; never `--allow-offline` a deliverable.
- Then `qc FILE --target …`. When it warns `moov_position`, the faststart remux above, and nothing else: the edit list stays.
- YouTube chapters go in the description as timestamps (the first at 00:00, at least three in ascending order, each chapter at least 10 s), not into the MP4.

## Working files

- Intermediates go in `<project>.work/` next to the project, and what is no longer needed goes at the end. Write nothing outside the user's folders: a file in `/tmp` may be unreadable to you in a restricted session.
- No global installs; tools run through `uv run` and `uvx`.
- FilmCraft keeps `FilmCraft Previews/`, its render cache, next to every saved project with a sequence. It is not an output; say so rather than leaving the user to wonder.

## Working in the running app

When: the user wants to watch or work along, or the project is open in the app.

- Connect: `nc -z 127.0.0.1 9876`. If the app is not running, `open -a FilmCraft --args --control 9876` (arguments reach only a fresh launch). If it runs without the port, ask the user to save and quit it; never quit it yourself. The project's `filmcraft` MCP server appears once approved at session start.
- Commands: `filmcraft-cli --bridge 127.0.0.1:9876 exec|run|import|inspect|export`; `render` is headless only.
- Save trap: `--save` or `file.save` on an app project with no path opens a macOS save dialog, and every request then times out after 60 s. Send `file.saveAs {path}` first. Already stuck: `osascript -e 'tell application "System Events" to key code 53'` (Escape; needs Accessibility permission), or ask the user to click Cancel.
- Looking: MCP `ui_screenshot {panel, max_side}` and `render_frame {seconds}`; `ui_elements`/`ui_click` only for actions with no command.
- With this skill's tools: `timeline` and `captions` take `--bridge`. `frames` and `qc` read files: `file.saveCopy {path}` over the bridge (it leaves the app's own path and unsaved state alone), then run them on the copy. The project file on disk can lag the app's unsaved edits.
- Manners: do not drive the UI while the user is typing; leave the app open when done. `app.quit` quits without a save prompt (the recovery journal keeps the work).
