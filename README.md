# BP Doctor

**Catches the silent animation bugs that make your character T-pose in shipped builds — the ones UE's compiler won't tell you about.**

UE5 editor plugin (5.3 - 5.7) that scans every Blueprint and Animation Blueprint in your project for **39 silent-failure patterns**: missing MotionMatching databases, broken cached-pose links, disconnected slot sources, empty state machines, skeleton mismatches, root-motion mismatches, broken curve-driven blends, and similar time-bombs. Auto-fix handles 7 of them with one click. Every fix is reversible via file-level `.uasset` backup.

## Highlights

- **39 checks** (25 AnimBP + 14 General Blueprint), 7 auto-fixable, three scan profiles (Silent Failures Only / Standard / Everything)
- **Health Grade per asset** — A+ to F based on severity + confidence weighting
- **Confidence badges** on every result (High / Medium / Low) so you know when to trust auto-fix
- **Per-Blueprint memoization** during scan — ~4× faster than naive scanning
- **Headless commandlet** for CI/CD — SARIF 2.1.0 output, GitHub Code Scanning ready
- **Custom rules engine** — banned_function / banned_node / required_node / node_limit, JSON or visual editor
- **Three experience modes** — Beginner (plain English) / Intermediate (default) / Expert (full detection method)
- **Dual build pipeline** — PyInstaller + Nuitka native binaries

## Repo Layout

| Path | Purpose |
|---|---|
| `fab-plugin/BPDoctor/` | UE5 plugin source (Source/, Resources/, Documentation/, .uplugin) |
| `dev/` | Standalone Python tooling — AnimBPDoctor GUI, test harness, build scripts |
| `Docs/` | Architecture blueprint PDFs |
| `landing-page/` | Static landing page assets |

## Quick Start (Plugin)

1. Drop `fab-plugin/BPDoctor/` into `YourProject/Plugins/`
2. Open your `.uproject` and accept the rebuild prompt
3. Inside the editor: **Window → BP Doctor**
4. Click **Scan Project** — results group by asset with health grades
5. Select an issue → see fix guide, or click **Fix All** for auto-fixable issues

Full plugin documentation: [`fab-plugin/BPDoctor/README.md`](fab-plugin/BPDoctor/README.md) (360 lines, every check + every flag).

## CI/CD Integration

```cmd
UnrealEditor-Cmd.exe YourProject.uproject -run=BPDoctor -format=json -sarif=scan.sarif -failOnError
```

Exit codes: `0` = clean, `1` = warning gate tripped, `2` = error gate tripped. SARIF output drops directly into GitHub Code Scanning, GitLab Security, Azure DevOps.

## Build

The plugin builds inside any UE5 project via standard `RunUAT BuildPlugin`:

```cmd
RunUAT.bat BuildPlugin -Plugin="path/to/BPDoctor.uplugin" -Package="dist/" -Rocket
```

Standalone Python tooling under `dev/` runs from a venv:

```bash
cd dev
python -m venv .venv && source .venv/Scripts/activate
python build.py
```

## Supported Platforms

- **Editor**: Win64, Mac, Linux (UE 5.3 - 5.7)
- **Runtime**: N/A — editor-only, zero cost in packaged builds
- **Module type**: `Editor`, `LoadingPhase: PostEngineInit`

## Project Status

Standalone UE5 editor plugin (39 checks, 7 auto-fixes). The check engine is also integrated into [Bionics](https://github.com/itsribbZ/Bionics), my primary project. Not published to a marketplace.

## Author

Jacob Ribbe — [github.com/itsribbZ](https://github.com/itsribbZ)
