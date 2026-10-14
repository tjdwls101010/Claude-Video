---
name: video
description: >-
  Make and edit video with FilmCraft, the open-source Premiere-style editor installed on this Mac, through `filmcraft-cli` (headless) or the running app (bridge), with graphics and motion graphics designed in code (HTML/CSS/SVG/Canvas) and rendered onto the edit: cuts and transcript-based edits, vertical Shorts/Reels/TikTok, montages, titles, lower thirds, callouts, data graphics, how inserted images are shown, intros and sound effects, standalone motion graphics, audio mix and loudness, color, Korean captions, QC-checked exports, and handoff to Premiere or Resolve. Use whenever the user wants a video cut, captioned, reframed, graded, mixed, given graphics, or exported, or mentions FilmCraft or a .fcproj. Triggers include: 영상 편집, 컷편집, 자막, 쇼츠, 릴스, 하이라이트, 몽타주, 모션 그래픽, 그래픽, 타이틀, 로워서드, 인트로, 효과음, 색보정, 내보내기, 유튜브 업로드용, .fcproj, FilmCraft. Not for downloading, summarizing or transcribing a video without editing it, still images such as thumbnails or posters, slide decks, or developing FilmCraft's own source code.
allowed-tools:
  - Bash(filmcraft-cli *)
  - Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)
  - Bash(ffprobe *)
---

# Making video with FilmCraft

FilmCraft exposes about 700 commands; `filmcraft-cli commands <filter>` and `filmcraft-cli describe <id>` own their parameters. This skill holds what those do not say: how the CLI fails, what platforms require, how to work with the user, and six tools FilmCraft lacks, called as `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" transcribe|captions|timeline|frames|qc|graphic …`; each `<tool> --help` owns its numbers, outputs and exit codes.

## Working with the user

- You edit together with the user, usually over many turns, and users differ: some bring a method of their own, some want your eye. Whatever they tell you about how they work outranks anything in this skill, for the rest of the work.
- Taste is theirs to decide and yours to offer: cut rhythm, transitions, how much pause or filler to keep, caption and title design, graphics (how many, how they look and how much they move), the look, how music ends, shot order. Use your own judgment, and say in a line what you chose and why so they can redirect. When their choice departs from what you would do, do theirs; when it collides with a platform requirement or a fact below, say so once with the consequence and let them decide.
- `${CLAUDE_SKILL_DIR}/data/` is the user's own record of work: each earlier piece there (its project, the pages in its `graphics/`, the exported video) is what they chose. When you propose something taste decides, such as how graphics look or how a piece is built, and an earlier piece resembles this one, read their taste from it; it informs your proposal and does not bind it. Unless the user names another folder, a new piece goes in `data/<piece>/`, so it becomes the record for the next one.
- Cheap to change (a trim, a transition, a caption style, a title's wording): make the call, show it (a `frames` sheet, a `render`), and move on.
- Costly to undo, or setting what the piece is (which segments a highlight or summary keeps, the overall look, a long export, a model download): show candidates and your reasons, and ask first.

## Before you hand something over

- The saved `.fcproj` reopens in a fresh process with the edit intact: `timeline --project` on it matches what you report.
- A rendered deliverable passes `qc` for its target. Re-export at most twice for a qc failure; if it still fails (FilmCraft's true-peak limiter wins over a loudness target), stop and report the measurements.
- You looked at the result: `frames` at every cut and every frame with text, and the final cut's words (`transcript.inspect`) read through for a sentence cut off or a splice that changes what someone said.
- Each graphic was seen in FilmCraft's render (`frames --project`) as it enters, at its fullest and as it leaves; `graphic` reported no `fallback` font and nothing `blocked`, or the user accepted what it did; its page is in the piece's `graphics/`. How it looks and moves is yours and the user's to choose; these only make sure it was seen as delivered and can still be changed.
- Say what changed, the calls you made that the user did not, and what you could not verify. You cannot hear the cut, so how its audio flows is always unverified.
- Edit picture and sound only in FilmCraft, so the user can open the project and change it; graphics are pages rendered with `graphic` and placed there. ffmpeg and ffprobe otherwise only measure. The one exception changes no picture or sound: a lossless `ffmpeg -i IN -c copy -movflags +faststart OUT` on the final MP4.

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
- Placing media with sound: `timeline.place` puts the sound on the targeted audio track (A1 unless targeting changed), overwriting the speech there, unless `audioTrack` names another track; `graphics.newFromFile` leaves the sound out. Pass `"audioTrack": "new"` or a free track.
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

## What does not depend on taste

- A cut that lands inside a word, or clicks, is a defect unless it is the effect wanted (a stutter edit): cut in the silence at a word boundary, and a few frames of audio crossfade take out the click.
- Text on screen must be right. Correct misheard names and terms before captions: a wrong name burned into a published video stays wrong. When unsure, keep your best guess and list it for the user.
- Never splice speech into something the speaker did not mean. An answer shown without its question can read as answering something else; keep the question when it does.
- Check for text collisions before showing anything: captions over burned-in subtitles or broadcast supers, titles or faces under platform UI. How to resolve one (move, restyle, crop, cover) is a choice to offer.
- Where speech is meant to be understood, music and effects sit under it.

## Speech as material

When: talking heads, interviews, lectures, meetings, summaries, anything captioned.

- This release cannot transcribe (`transcript.generate` and `downloadModel` are disabled); do not chase models. `transcribe MEDIA --item ID --out X.jsonl`, read its `review`, fix misheard words in the text fields of X.jsonl (keep the times; delete `repeat` and `no_speech` lines over music), then apply with its `next`. The model downloads on first use; ask before that.
- Choosing: `transcript.inspect` and `transcript.search` give word indices; `transcript.select` plus `extract` (ripple) or `lift` cut by words.
- Fillers: `transcript.removeFillers` defaults to English fillers; pass Korean ones (음, 어, 아, 그, 저, 뭐 standing alone; discourse markers such as 그러니까, 이제, 약간 only if the user wants them gone). Remove fillers before pauses; the other order leaves a gap where each filler was.
- Pauses: `transcript.removePauses` leaves `keepSeconds` on both sides of each pause, so a pause shrinks to at least twice that (frame snapping can leave more, and a pause with nothing left after snapping stays). Set keep to half the gap you want; how tight to cut is the user's call.
- Captions: `captions` (from the sequence, or `--cues` for a translation you wrote as SubRip), then run both commands in its `next` and check the import's `warnings` is empty. Not `transcript.createCaptions` (English line lengths; it runs a short sentence into the next), and not `captions.add`/`setTimes` (they refuse overlaps; import is lenient). Rewrite any cue `violations` lists as too fast.
- `captions` styles (font, size, margin, anchor) are starting points to show and adjust. Burned-in captions plus a sidecar show twice on YouTube: one per delivery.

## On-screen text

When: captions, and titles or lower thirds made as FilmCraft text layers.

- The default font, Inter, has no Hangul: Korean draws as boxes. Set an installed Korean family (`fonts.list`; Apple SD Gothic Neo, Noto Sans KR) on every caption track and text layer, then look at a render.
- Caption `size` is relative to a 1080-line frame, so a size that looks right in landscape is far bigger in a vertical frame. `captions` accounts for it; a style set by hand does not.

## Graphics and motion graphics

When: a title, lower third, callout, number or chart, how an inserted image is shown, a layout element (a bar, a gradient, a frame), an intro or sting, or a motion graphic video on its own.

- Design them as HTML pages (CSS, SVG, Canvas, whatever the design needs) and render them with `graphic`. FilmCraft does the cut, timing, placement and track order, anything worked on the footage's own pixels (blurring or reframing the picture behind a graphic, color), sound, transitions between shots, and captions. Code gives the widest range of design; FilmCraft's graphics are text and shape layers moved by keyframes, which takes repeated test renders to get timing and easing right; and a rendered graphic survives an FCP7 XML handoff while a FilmCraft graphic is dropped. When the user wants to adjust a graphic themselves in FilmCraft, make it there instead.
- Two that look alike: pushing in on the person speaking works on the footage's pixels, so it is FilmCraft's Motion; pushing in on one spot of an image shown on screen is movement inside the graphic, so it belongs to the page. Where the line is unclear (word-by-word caption animation, a highlight following something in the footage), say which side you chose and why.
- Judge how a graphic sits in the picture from FilmCraft's render (`frames --project`); a browser is fine for working on the page itself. FilmCraft blends in linear light, so anything partly transparent (a gradient, a shadow, a 90 % box, a glow) comes out lighter over the picture than in a browser or an ffmpeg composite: a dark layer looks weaker and a light one stronger, so set its opacity against FilmCraft's render.
- A change request edits the page, not the render. Re-render to the same path and the project picks it up; `graphic`'s output says when the clip has to be placed again or relinked.
- Sound effects can come from the same page (`renderAudio` in `graphic --help`), so they stay attached to the frames they belong to.

## Changing the frame shape

When: the delivery's aspect ratio differs from the source's.

- The sequence takes the delivery's size and, unless the user wants otherwise, the source's frame rate: converting 60p to 30p throws motion away.
- A clip of another size lands at its own size: `clip.fillFrame` (or `clip.fitToFrame` to letterbox).
- Reframe with Motion position and scale (`effects.setParam`); in a two-shot or split screen, the person speaking is usually who the frame should follow. The `auto_reframe` effect guesses; check it with `frames --overlay`.
- Platform UI covers parts of a vertical frame: keep text and faces clear of every shaded area of `frames --overlay all`. Its numbers (in `frames --help`) are the platforms' ad guidance; organic posts carry similar UI, not identical.
- Upscaling loses detail; say by how much. Phone media: rotation metadata is honoured; HEIC stills and EXIF rotation are not supported; HDR (HLG, PQ) is tone-mapped automatically into an SDR sequence.

## Many clips and music

When: montages, highlight reels, B-roll, music-driven edits.

- Survey with `frames --media F --every N` and `clip.sceneEditDetection {wait:true, applyCuts:false, generateMarkers:true}`.
- Choose shots by what is in them and tell the user the idea behind the order; cycling through the sources in file order is not an idea.
- Measure the music's beat (ffmpeg energy onsets) instead of trusting a BPM in its title, and round cuts to frames without letting the rounding accumulate. Where a phrase ends near the target length is worth showing the user when they decide how the piece ends.
- Assemble with `timeline.place`, which takes several items back to back in one step.
- Ducking: `essentialSound.setType` (dialogue, music), the `ducking.*` keys of `essentialSound.set` on the music, then `essentialSound.generateDucking` (it refuses dialogue clips). Fades at the ends: `sequence.applyAudioTransition`.

## Color

When: a grade is asked for, or the picture is clearly off (log footage, a colour cast, under-exposure).

- The look is the user's; correction toward neutral is the part numbers can check. Judge by numbers: `scopes.read` (neutral RGB, waveform 0–100 %, skin tones). Lumetri parameter ids come from `effects.list detail=true`; `lumetri.applyMatch` reports `distanceBefore` and `distanceAfter`.
- Log footage takes an input LUT first (`lumetri.setInputLut`, built-in S-Log3 and others to Rec. 709); creative LUTs go in `lumetri.setLook`. Measure each clip before calling it log: a clip already in display range needs only a light touch.

## Delivery

- Every export: `range: "entire"` (the default is In to Out), `burnCaptions` and `captionSidecar` as intended, loudness at the qc target, `"wait": true` under `exec`.
- Loudness: `loudnessLufs` normalises (BS.1770) under a −2 dBTP limiter, so a peaky mix can land short of its target. The ceiling is `true_peak_dbtp` in `settings.effects.loudness` (with `"enabled": true`, or nothing is normalised), which is also the only form `export --settings` accepts (a top-level `loudnessLufs` there is refused). AAC encoding can raise true peak above the ceiling, which is why qc measures the encoded file.
- Presets: "YouTube 1080p Full HD" for YouTube, "Social Vertical 1080×1920" for vertical. `hardwareEncoding: "auto"` is much faster (not with CRF or 2-pass); H.265 needs hardware encoding, and there is no AV1 export.
- Offline media renders as placeholder frames: fix it with `media.findMissing`; never `--allow-offline` a deliverable.
- Then `qc FILE --target …`. When it warns `moov_position`, the faststart remux above, and nothing else: the edit list stays.
- YouTube chapters go in the description as timestamps (the first at 00:00, at least three in ascending order, each chapter at least 10 s), not into the MP4.

## Working files

- Every piece has the same shape, so a later session can find its way in: the project and its deliverables (the exported video, sidecar captions, handoff files) at the piece's root; `assets/` for material brought in (footage, music, logos, references), copied in with `cp -c` (a free clone on APFS) from wherever it came, `data/assets/` included, so the piece's folder alone opens the project; `graphics/` for pages and their renders, kept because the project plays them; `etc/` for the rest (other tools' files, transcripts and caption drafts worth keeping), with throwaway files such as frame sheets removed at the end. Write nothing outside the user's folders: a file in `/tmp` may be unreadable to you in a restricted session.
- No global installs; tools run through `uv run` and `uvx`.
- FilmCraft keeps `FilmCraft Previews/`, its render cache, next to every saved project with a sequence. It is not an output; say so rather than leaving the user to wonder.

## Working in the running app

When: the user wants to watch or work along, or the project is open in the app.

- Connect: `nc -z 127.0.0.1 9876`. If the app is not running, `open -a FilmCraft --args --control 9876` (arguments reach only a fresh launch). If it runs without the port, ask the user to save and quit it; never quit it yourself. The project's `filmcraft` MCP server appears once approved at session start.
- Commands: `filmcraft-cli --bridge 127.0.0.1:9876 exec|run|import|inspect|export`; `render` is headless only.
- Save trap: `--save` or `file.save` on an app project with no path opens a macOS save dialog, and every request then times out after 60 s. Send `file.saveAs {path}` first. Already stuck: `osascript -e 'tell application "System Events" to key code 53'` (Escape; needs Accessibility permission), or ask the user to click Cancel.
- Looking: MCP `ui_screenshot {panel, max_side}` and `render_frame {seconds}`; `ui_elements`/`ui_click` only for actions with no command.
- With this skill's tools: `timeline` and `captions` take `--bridge`. `frames` renders headless, so `file.saveCopy {path}` over the bridge first (it leaves the app's own path and unsaved state alone) and run it on the copy; `qc` checks an export, which the bridge's `export` produces from the app's current state. The project file on disk can lag the app's unsaved edits.
- Manners: do not drive the UI while the user is typing, and leave saving the open project to them. Leave the app open when done; if the user wants it closed, MCP `ui_control {"method": "app.quit"}` quits without a save prompt (the recovery journal keeps the work), while `exec app.quit` silently does nothing.
