# Claude-Video: FilmCraft 편집 스킬

이 맥에 설치된 [FilmCraft](https://github.com/storytold/filmcraft)(어도비 프리미어 프로를 클론한 오픈소스 편집기)를 Claude Code가 직접 다루게 하는 프로젝트 스킬입니다. "이 영상으로 ○○ 만들어줘"라고 하면, Claude가 사용자와 의논하며 편집합니다. 결과물은 검수를 통과한 영상과, 사용자가 FilmCraft에서 다시 열어 고칠 수 있는 `.fcproj` 프로젝트입니다.

- 스킬 본문: [`.claude/skills/video/SKILL.md`](.claude/skills/video/SKILL.md)(영어, 모델이 읽는 글)
- 번들 도구: [`.claude/skills/video/scripts/cli.py`](.claude/skills/video/scripts/cli.py)
- 개발 기록(대조 실험 수치, 버린 대안, 리뷰 내역): [PR #1](https://github.com/tjdwls101010/Claude-Video/pull/1)

## 무엇을 할 수 있나

| 작업 | 예 |
|---|---|
| 말 중심 편집 | 공백·필러 정리, 전사를 보며 문장 단위로 자르기, 긴 대담을 핵심 질의응답만 남긴 요약본으로 |
| 한국어 자막 | 넷플릭스 한국어 규칙(줄당 16자, 2줄, 초당 12자, 5/6~7초)과 실제 화면 폭에 맞춘 자막, 영어 대담의 번역 자막 |
| 세로 숏폼 | 쇼츠·릴스·틱톡용 리프레이밍(말하는 사람 따라가기), 플랫폼 UI 세이프존 확인 |
| 몽타주·B-roll | 클립 훑어보기, 장면 전환 감지, 음악 박자 측정과 컷 맞춤, 배경음악 더킹 |
| 색보정 | 스코프 수치로 중립 보정, S-Log3 등 로그 소스에 입력 LUT 적용 |
| 납품·검수 | 유튜브·쇼츠·릴스·틱톡·한국 방송 기준 기술 검수(라우드니스·트루피크·해상도·fps·길이·faststart), 유튜브 챕터 |
| 다른 편집기로 넘기기 | Premiere·Resolve용 FCP7 XML, OTIO, AAF/OMF, EDL |
| 실행 중인 앱과 함께 | 사용자가 FilmCraft 앱을 보며 작업할 때, 앱의 저장 안 된 편집 상태까지 읽고 그려 보기 |

## 일하는 방식

이 스킬의 Claude는 혼자 끝까지 만드는 편집자가 아니라, 사용자와 의논하며 만드는 동료입니다.

- 컷 리듬, 전환, 필러를 얼마나 남길지, 자막·타이틀 디자인, 룩, 음악을 어떻게 끝낼지 같은 취향은 사용자가 정합니다. Claude는 자기 판단으로 제안하고 이유를 한 줄로 말합니다.
- 바꾸기 쉬운 것은 먼저 해 보이고 프레임 시트로 보여 줍니다.
- 되돌리기 비싸거나 결과의 성격을 정하는 것은 후보와 근거를 보여 주고 먼저 묻습니다. 어느 구간을 쓸지, 전체 룩, 긴 내보내기, 모델 다운로드가 그렇습니다.
- 사용자가 자기 방식을 말하면 그쪽이 스킬보다 우선합니다.
- 결과를 넘길 때는 바꾼 것, 사용자 대신 내린 결정, 확인하지 못한 것을 보고합니다. Claude는 소리를 들을 수 없으므로 컷의 청감은 늘 미확인으로 남습니다.

## 준비

| 필요한 것 | 확인 방법 |
|---|---|
| macOS와 FilmCraft 앱 | `/Applications/FilmCraft.app` |
| 앱과 같은 버전의 `filmcraft-cli` | `filmcraft-cli --version`이 앱 버전과 같음 |
| [uv](https://docs.astral.sh/uv/) | `uv --version` (번들 도구와 mlx-whisper를 격리 실행) |
| ffmpeg, ffprobe | `brew install ffmpeg` (측정용으로만 씀) |
| Apple Silicon | 음성 인식(mlx-whisper)에 필요 |
| 한글 폰트 | `filmcraft-cli exec fonts.list`에 Apple SD Gothic Neo 또는 Noto Sans KR |

CLI가 없거나 앱과 버전이 다르면 앱 버전에 맞춰 설치합니다. 앱보다 새 CLI로 저장한 프로젝트는 앱이 열지 못할 수 있습니다.

```bash
VER=$(defaults read /Applications/FilmCraft.app/Contents/Info CFBundleShortVersionString)
gh release download v$VER -R storytold/filmcraft -p "filmcraft-cli-$VER-macos-universal.zip" -p SHA256SUMS.txt
shasum -a 256 -c --ignore-missing SHA256SUMS.txt
unzip -o "filmcraft-cli-$VER-macos-universal.zip"
install -m 755 "filmcraft-cli-$VER-macos-universal/filmcraft-cli" ~/.local/bin/filmcraft-cli
```

음성 인식 모델(`mlx-community/whisper-large-v3-turbo`, 약 1.6GB)은 처음 전사할 때 `~/.cache/huggingface`로 받습니다. Claude는 받기 전에 먼저 묻습니다.

## 쓰기

이 레포에서 Claude Code를 열고 평소처럼 요청하면 `video` 스킬이 열립니다.

- "`영상.mp4`에서 공백이랑 군더더기 잘라서 한국어 자막 넣고 유튜브용으로 뽑아줘"
- "이 40분 대담에서 핵심만 5분으로 요약하고 한국어 번역 자막 달아줘"
- "가장 임팩트 있는 장면 골라 50초 쇼츠로. 후보부터 보여줘"
- "이 클립들이랑 음악으로 30초 하이라이트 만들어줘"
- "S-Log로 찍은 거 자연스럽게 보정해서 마스터 뽑아줘"

기본은 앱 창 없이 CLI(헤드리스)로 작업합니다. 앱을 보며 같이 작업하려면 앱을 제어 포트로 띄웁니다. 이미 실행 중인 앱에는 인자가 전달되지 않으니, 저장 후 종료한 뒤 띄웁니다.

```bash
open -a FilmCraft --args --control 9876
```

레포의 [`.mcp.json`](.mcp.json)은 이 앱에 붙는 MCP 서버 `filmcraft`를 등록합니다. 새 세션 시작 때 한 번 승인하면 Claude가 앱 화면 스크린샷과 Program 모니터를 볼 수 있습니다. 앱이 꺼져 있으면 그 도구 호출만 실패하고 세션은 정상입니다.

## 번들 도구

FilmCraft에 없는 일만 합니다. 모두 `uv run .claude/skills/video/scripts/cli.py <명령>`으로 실행합니다. 각 `<명령> --help`가 인자, 출력(JSON 한 문서), 종료 코드, 기준 수치를 설명합니다.

| 명령 | 하는 일 |
|---|---|
| `transcribe` | mlx-whisper 전사의 단어 시간을 음량으로 잰 발화 구간에 맞춰 `transcript.set` JSONL로 씁니다. 확인할 단어(낮은 확신, 무음 위 단어, 배경음악 위 반복 환각)를 review로 줍니다 |
| `captions` | 시퀀스 전사, 또는 직접 쓴 번역 SRT(`--cues`)를 한국어 자막 규칙과 FilmCraft 번인 폭에 맞춰 SRT로 씁니다 |
| `timeline` | 시퀀스를 요약합니다(클립 수와 무관하게 짧음). 클립별 TC 상세는 파일로 줍니다 |
| `frames` | 렌더하거나 추출한 프레임을 TC 라벨 시트 한 장으로 만듭니다. 세로 영상이면 쇼츠·릴스·틱톡 세이프존을 겹쳐 그립니다 |
| `qc` | 결과 파일을 대상별 기준으로 검수합니다. 기준표와 각 기준의 근거(규정/플랫폼 사양/측정/관행/결정)는 `qc --help`에 있습니다. 실패가 있으면 종료 코드 3입니다 |

```bash
uv run .claude/skills/video/scripts/cli.py qc out/final.mp4 --target shorts
uv run .claude/skills/video/scripts/cli.py frames --project out/edit.fcproj --cuts --overlay all --out sheet.png
```

## 스킬이 있을 때와 없을 때

같은 과제를 스킬 없이, 그리고 스킬을 켜고 격리된 `claude -p`로 돌린 결과입니다(Opus 5.5, FilmCraft 0.7.2, 2026-10-14). 과제는 한 번 입력하고 끝까지 가는 단독 실행이라, 여러 턴에 걸친 협업 품질은 재지 않았습니다.

| 항목 | 스킬 없음 | 스킬 있음 |
|---|---|---|
| 음성 인식 | 비활성화된 FilmCraft 내장 모델 다운로드를 시도(2/2건) | 처음부터 `transcribe` 사용 |
| 단어 시간 오차(구절 경계) | 평균 약 0.34초 | 0.05초 미만 |
| 한국어 자막 규칙 위반 | 6큐 중 7건, 35큐 중 8건 | 0건, 0건 |
| 번역 자막 규칙 위반 | 47큐 중 110건 | 65큐 중 5건 |
| 납품 검수(qc) 통과 | 7건 중 3건(+1.0 dBTP 클리핑 포함) | 9건 중 7건(나머지 2건은 원인을 측정해 보고) |
| faststart | 5/5건 누락 | 검수 후 무손실 리먹스 |
| 60fps 소스 | 30fps로 낮춤 | 60fps 유지 |
| 작업 폴더 밖 쓰기 | 22회 | 0회 |
| 사용자에게 맡길 결정 보고 | 한 일만 보고 | 따로 정리(예: 몽타주 6건) |
| 비용 | 기준 | 평균 약 33% 증가(검수·프레임 확인 증가분) |

## 레포 구조

```
.claude/skills/video/
├── SKILL.md                 모델이 읽는 스킬 본문
└── scripts/
    ├── cli.py               유일한 진입점(파서·도움말·종료 코드)
    └── video/               유일한 패키지
        ├── transcribe/ captions/ timeline/ frames/ qc/   기능
        ├── filmcraft_cli/ whisper/ ffmpeg/ mp4/          외부 시스템·형식
        └── timecode.py errors.py                         공용
tests/
├── video_skill/             번들 도구 테스트(명령 프로토콜, 순수 코어, 구조 규칙)
├── filmcraft_facts/         스킬이 기대는 FilmCraft 동작 19개
└── support/                 테스트 공용 도우미
.mcp.json                    실행 중인 앱용 브리지 MCP
.tmp/filmcraft/              FilmCraft 0.7.2 소스(동작 확인용 참고)
```

기능 유닛은 시스템 유닛과 공용 모듈만 가져다 쓰고, 유닛 밖에서는 `__init__.py`의 `__all__`만 씁니다. 이 규칙은 `tests/video_skill/test_structure.py`가 지킵니다.

## 테스트

```bash
uv run --with pytest --with pillow pytest                       # 전부
uv run --with pytest --with pillow pytest tests/filmcraft_facts # FilmCraft 사실만
FILMCRAFT_TEST_WHISPER=1 uv run --with pytest --with pillow pytest -k real_whisper  # 실제 Whisper 경로
```

- 테스트 미디어는 ffmpeg와 macOS `say`로 그때그때 만듭니다. 기대값은 생성 조건이나 표준(EBU Tech 3341, SMPTE 드롭프레임)에서 옵니다.
- filmcraft-cli가 없으면 해당 테스트는 이유를 출력하며 건너뜁니다.

**FilmCraft는 1~2일마다 업데이트됩니다.** 업데이트 뒤 `tests/filmcraft_facts`가 실패하면, 실패한 테스트의 docstring이 가리키는 SKILL.md 문장을 고치거나 지우세요. 테스트를 느슨하게 고치는 것으로 해결하면 안 됩니다.

## 한계

- Claude는 소리를 들을 수 없습니다. 컷의 청감, 음악과 박자가 맞는지는 직접 들어 확인해야 합니다.
- 화자를 구분하지 못합니다. 질문자와 답변자의 말이 한 자막에 섞일 수 있습니다.
- 이 FilmCraft 빌드는 자체 음성 인식이 없고, 내레이션(TTS)은 영어만 됩니다.
- 세이프존 수치는 플랫폼의 광고 가이드 기준입니다. 일반 게시물 UI와는 조금 다를 수 있습니다.
- `.tmp/etc/`의 테스트 영상은 개인 테스트용이라 레포에 넣지 않습니다.
