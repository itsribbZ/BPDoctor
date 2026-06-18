# BP Doctor

**Catches the silent animation bugs that make your character T-pose in shipped builds — the ones UE's compiler won't tell you about. Unreal Engine 5.3 - 5.7.**

BP Doctor scans every Blueprint and Animation Blueprint in your project for
**20 silent-failure patterns by default** — bugs that compile clean and ship
to production: missing MotionMatching databases, broken cached-pose links,
disconnected Slot sources, empty state machines, skeleton mismatches, root
motion mismatches, broken curve-driven blends, and similar time-bombs.
Auto-fix handles 7 of them with a single click. Every fix is reversible
via file-level `.uasset` backup.

Three scan profiles:
- **Silent Failures Only** (default, 20 checks) — zero noise. The bugs that
  wake you up at 2 AM because QA found a T-pose in the vertical slice.
- **Standard** (28 checks) — adds contextual perf / architecture smells.
- **Everything** (39 checks including stylistic heuristics) — power-user audit mode.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [How It Works](#how-it-works)
3. [Feature Reference](#feature-reference)
   - [Scan Engine](#1-scan-engine)
   - [Health Grade System](#2-health-grade-system)
   - [Auto-Fix Engine](#3-auto-fix-engine-7-fixes)
   - [Undo Fix (File-Level Backup)](#4-undo-fix--file-level-backup)
   - [Navigate to Issue](#5-navigate-to-issue)
   - [Experience Modes](#6-experience-modes)
   - [Filters, Search, Suppression](#7-filters-search-suppression)
   - [Enable / Disable Checks](#8-enable--disable-checks)
   - [Custom Rules](#9-custom-rules-json--visual-editor)
   - [Export Reports](#10-export-reports-text--html)
   - [Commandlet for CI/CD](#11-commandlet--headless-cicd)
   - [Settings & Config Portability](#12-settings--config-portability)
   - [In-Editor Documentation](#13-in-editor-documentation)
4. [Complete Check Reference (All 39)](#complete-check-reference)
5. [Supported Platforms](#supported-platforms)
6. [Documentation](#documentation)
7. [Support](#support)

---

## Quick Start

1. Drop the `BPDoctor` folder into `YourProject/Plugins/`.
2. Open your `.uproject` and accept the "Rebuild modules now?" prompt.
3. Inside the editor: **Window → BP Doctor** (also available under **Tools → BP Doctor**).
4. Click **Scan Project**. Results appear grouped by asset with a health grade.
5. Select an issue to see its details, or click **Fix All** to auto-fix everything safe.
6. Need the manual? Click the **Help** button in the toolbar, or use
   **Help → BP Doctor Documentation** from the main menu bar.

---

## How It Works

BP Doctor runs entirely inside the Unreal Editor as an editor-only plugin — it
has zero runtime cost in packaged builds. On scan, it walks every Blueprint
and Animation Blueprint in `/Game`, loads them via the Asset Registry, and runs
each enabled check against them in-process. Results appear in a dockable Slate
panel with severity icons, confidence badges, and a health grade per asset.

When you click Fix or Fix All, BP Doctor first backs up the affected `.uasset`
file to `YourProject/Saved/BPDoctor/Backups/backup_<guid>.uasset`, then applies
the fix via the Blueprint editor APIs (same APIs the editor uses internally).
Undo Fix restores the backup file and reloads the asset.

---

## Feature Reference

### 1. Scan Engine

- Walks every Blueprint (`UBlueprint`) and Animation Blueprint (`UAnimBlueprint`)
  under `/Game` via the Asset Registry.
- **Per-Blueprint memoization**: each graph walk is cached for the scan, so a
  BP with 17 checks only walks its graphs ONCE (~4× faster than naive scanning).
- **Async progress bar**: the scan reports progress without freezing the editor.
- **Confidence system**: every result carries a confidence badge
  (**High**, **Medium**, **Low**) indicating how reliable the detection is.
  High-confidence checks use exact API matches (e.g., class comparison); Low-confidence
  checks use heuristics (e.g., node-count thresholds) and should be verified manually.
- **Severity levels**: Error (red), Warning (yellow), Info (blue).
- **Auto-detection of `/Game` root**: scan works out-of-box on any project layout.

### 2. Health Grade System

Every scanned Blueprint gets a letter grade from **A+** (zero issues) down to
**F** (critical errors present). The grade is weighted by severity and confidence:

- **A+** — 0 errors, 0 warnings, 0 info (perfectly clean)
- **A**  — 0 errors, 0 warnings (any number of info is fine)
- **B+** — 0 errors, 1-3 warnings
- **B**  — 0 errors, 4+ warnings
- **C**  — 1-2 errors
- **D**  — 3-5 errors
- **F**  — 6+ errors (silent failures shipping to prod)

A project-wide rollup grade also appears at the top of the results panel.

### 3. Auto-Fix Engine (7 fixes)

BP Doctor auto-fixes the 7 issues where the correct fix is unambiguous. Each
fix creates a file-level backup BEFORE any modification. The seven auto-fixes:

| Check Code | Issue | What the Auto-Fix Does |
|---|---|---|
| `BROKEN_BLEND_WT` | Blend weight outside [0,1] | Clamps the value to the valid range. Supports custom target value. |
| `MISSING_SLOT` | AnimBP uses montages but has no Slot node | Creates a `DefaultSlot` node in the AnimGraph. You connect it into your pose chain. |
| `ORPHANED_NODE` | Nodes not reachable from Output Pose | BFS from Output Pose; deletes all unreachable AnimGraph nodes. State machine contents preserved. |
| `DUP_SLOT` | Two Slot nodes share the same name | Renames duplicates with `_2`, `_3` suffixes — probed against all existing slot names so manual `_2` collisions are avoided. Custom name override supported. |
| `BP_SELF_CAST` | Blueprint casts to its own class | Removes the Cast node; reroutes execution (Then + CastFailed branches) and object connections through the source pin. |
| `BP_DEBUG_NODES` | `PrintString`/`DrawDebug` nodes left in | Deletes all debug nodes; reroutes execution (white) pins around the deletion. |
| `BLEND_WT_SUM` | LayeredBoneBlend weights don't sum to ~1.0 | Normalizes each layer's BlendWeight so the total is exactly 1.0, preserving the ratio between layers. |

The **Fix All** button applies every auto-fixable issue in one click, with a
confirmation dialog showing the total count.

The remaining 27 checks are reported but NOT auto-fixed — they require human
judgment (e.g., which skeleton is correct, which variable should be deleted,
whether a deprecated node has a direct replacement). Each of those has a
step-by-step manual fix guide in its detail panel.

### 4. Undo Fix — File-Level Backup

Every auto-fix is reversible via a **file-level `.uasset` backup** written
BEFORE the fix is applied. This is more reliable than transactional undo
because it survives editor restarts and covers package-level changes.

- **Undo Fix** button — reverts the single most recent fix.
- **Revert Selected** — reverts a specific selected issue's fix.
- Backups are stored in `YourProject/Saved/BPDoctor/Backups/` as
  `backup_<guid>.uasset` files (8-character GUID suffix).

### 5. Navigate to Issue

Double-click any issue (or select it and click **Open Editor**) to:

1. Open the Blueprint editor for that asset.
2. Jump directly to the problematic node / graph in focus.
3. Highlight the node with a temporary selection ring so you can't miss it.

Works for Event Graph nodes, AnimGraph nodes, state machine contents, and
function graph nodes.

### 6. Experience Modes

Three modes adjust how much detail the detail panel shows per issue:

- **Beginner** — plain-English explanation, why it matters, and the beginner-friendly tip (no API jargon).
- **Intermediate** (default) — the beginner explanation plus the step-by-step fix guide.
- **Expert** — everything above, plus the detection method (e.g., "Scans AnimGraphNode_Slot nodes; exact SlotName string match") and confidence reasoning.

Toggle via the experience mode dropdown in the toolbar. The choice is persisted per-project.

### 7. Filters, Search, Suppression

- **Severity filters** — toggle Errors, Warnings, Info, and Suppressed via checkboxes in the toolbar.
- **Search field** — filters the visible issues by check code, asset name, or description (live as you type).
- **Suppress button** — marks a specific `CheckCode|AssetPath` combination as "suppressed". Suppressed issues are hidden by default but can be shown via the Suppressed checkbox. Suppression is persisted across scans.

Suppression is surgical: only the exact issue on the exact asset is hidden.
If the same check fires on a different asset, it still appears.

### 8. Enable / Disable Checks

The **Checks** dialog lists all 39 checks with a checkbox next to each. Disabling
a check globally skips it during scans — useful if your project has an
intentional pattern that always trips a specific heuristic (e.g., you use
10+ Timelines per BP on purpose).

The disabled-checks set is persisted per-project in the settings file.

### 9. Custom Rules (JSON + Visual Editor)

Beyond the 39 built-in checks, you can define your own checks via JSON.
Four rule types are supported:

- **`banned_function`** — flag BPs that call a specific function (e.g. ban
  `PrintString` in shipping builds).
- **`banned_node`** — flag BPs that contain a specific K2 node type.
- **`required_node`** — flag BPs that are MISSING a specific node type
  (e.g. enforce every player BP have a particular component reference).
- **`node_limit`** — flag BPs with more than N total nodes (project-wide
  complexity ceiling).

Custom rules can be authored in two ways:

1. **JSON file**: drop a `CustomRules.json` into your project's `Saved/BPDoctor/` folder.
   The bundled `Resources/CustomRules_Example.json` shows the schema.
2. **Visual Rules Editor**: use the in-editor GUI (toolbar → Checks → Custom Rules)
   to add/edit/remove rules without touching JSON.

**Import Custom Rules** — load a `.json` file from disk and merge into the rule set.

### 10. Export Reports (Text + HTML)

Two export formats:

- **Export Report (Text)** — plain-text scan report grouped by asset with
  severity prefixes, check codes, and detection notes. Ideal for ticketing
  systems (Jira, Linear) and code review artifacts.
- **Export HTML** — styled HTML report with color-coded severity, health grades,
  a table of contents, and collapsible sections per asset. Share with your team,
  attach to PRs, or render in CI/CD build summaries.

Both include a generation timestamp, total counts by severity, and the scan
configuration (which checks were enabled).

### 11. Commandlet — Headless CI/CD

BP Doctor ships with a `UBPDoctorCommandlet` that runs scans headlessly from the
command line — no editor window required. Perfect for CI/CD gates.

```cmd
UnrealEditor-Cmd.exe YourProject.uproject -run=BPDoctor -format=json -output=scan.json -failOnError
```

**Flags**:

- `-format=json` / `-format=text` — output format (default: text)
- `-output=PATH` — file to write the text/json report to (default: stdout)
- `-sarif=PATH` — additionally emit a SARIF 2.1.0 report at the given path (for GitHub Code Scanning, GitLab Security, Azure DevOps)
- `-severity=error|warning|info` — minimum severity to include in the report (default: info)
- `-fail-on=error|warning|info|none` — severity gate for non-zero exit (default: none — exit 0 even when issues are found)
- `-failOnError` — alias for `-fail-on=error` (matches common CI templates)
- `-profile=silent_failures_only|standard|everything` — which check tier set runs (default: silent_failures_only)
- `-checks=CODE1,CODE2,...` — allowlist filter, only run the listed check codes
- `-path=/Game/Subfolder` — scan only a specific content subfolder (default: /Game)

Use it in GitHub Actions, Jenkins, TeamCity — anywhere you can run
`UnrealEditor-Cmd.exe`. Exit codes: `0` = clean / gate not tripped, `1` = warning-or-info gate tripped, `2` = error-severity gate tripped. Default is non-failing — explicitly pass a `-fail-on=` or `-failOnError` flag to gate CI on severity.

### 12. Settings & Config Portability

All BP Doctor configuration is stored in a JSON settings file in your project's
`Saved/` directory:

- Disabled checks
- Suppressed issues
- Experience mode
- Custom rules
- Severity filter defaults

**Export Settings** — writes the current config to a file you pick.
**Import Settings** — loads a config from another project. Use this to share
a team-wide BP Doctor policy across multiple projects in a repo.

### 13. In-Editor Documentation

Two ways to reach the full user guide from inside the editor:

- **Help button** in the BP Doctor panel toolbar — opens the bundled HTML guide.
- **Main menu bar: Help → BP Doctor Documentation** — same guide, one click.

Both open `Documentation/BP_Doctor_User_Guide.html` in your default browser
(with a fallback to `Resources/BP_Doctor_User_Guide.html`).

---

## Complete Check Reference

### AnimBP Checks (25)

| # | Code | Name | Severity | Confidence | Auto-Fix |
|---|---|---|---|---|---|
| 1 | `NULL_ANIM_REF` | Null Anim Reference | Error | High | — |
| 2 | `BROKEN_BLEND_WT` | Broken Blend Weight | Warning | Medium | ✓ |
| 3 | `SKEL_MISMATCH` | Skeleton Mismatch | Error | Medium | — |
| 4 | `MISSING_SLOT` | Missing Default Slot | Warning | Medium | ✓ |
| 5 | `BROKEN_TRANS` | Broken Transition | Warning | Medium | — |
| 6 | `TPOSE_FALLBACK` | T-Pose Fallback | Error | Medium | — |
| 7 | `ORPHANED_NODE` | Orphaned Node | Info | Medium | ✓ |
| 8 | `INVALID_BSPACE` | Invalid BlendSpace | Warning | Medium | — |
| 9 | `MISSING_NOTIFY` | Missing Notify | Info | Medium | — |
| 10 | `DUP_SLOT` | Duplicate Slot Name | Warning | High | ✓ |
| 11 | `UNUSED_VAR` | Unused Variable | Info | Low | — |
| 12 | `DEPRECATED_NODE` | Deprecated Node | Warning | Medium | — |
| 27 | `MM_NO_DATABASE` | MotionMatching Node Missing Database | Error | High | — |
| 28 | `MM_NO_INERTIALIZATION` | MotionMatching Missing Inertialization | Warning | Medium | — |
| 29 | `SLOT_NAME_MISMATCH` | Slot Name Not Registered in Skeleton | Warning | Medium | — |
| 30 | `DEAD_CACHED_POSE` | Dead Cached Pose | Info | High | — |
| 31 | `EMPTY_SM` | Empty State Machine | Error | High | — |
| 32 | `BLEND_WT_SUM` | Blend Weights Don't Sum to 1 | Warning | Medium | ✓ |
| 33 | `EMPTY_BRANCH_FILTER` | LayeredBoneBlend Has Empty Bone Filter | Warning | High | — |
| 34 | `DISCONNECTED_SLOT_SRC` | Slot Node Source Pin Disconnected | Warning | High | — |
| 35 | `ROOTMOTION_MODE_MISMATCH` | RootMotion Mode Mismatch | Warning | High | — |
| 36 | `LINKED_LAYER_NO_LAYER` | LinkedAnimLayer No Layer Selected | Error | High | — |
| 37 | `CURVE_ALPHA_MISSING` | Curve-Alpha References Missing Skeleton Curve | Warning | High | — |
| 38 | `MONTAGE_SECTION_LOOP` | AnimMontage Section Loops With No Exit | Warning | High | — |
| 39 | `BLENDSPACE_ZERO_AXIS` | BlendSpace Axis Has Zero Range | Warning | High | — |

### General Blueprint Checks (14)

| # | Code | Name | Severity | Confidence | Auto-Fix |
|---|---|---|---|---|---|
| 13 | `BP_BROKEN_REF` | Broken Asset Reference | Error | High | — |
| 14 | `BP_COMPLEXITY` | Excessive Complexity | Warning | Medium | — |
| 15 | `BP_EMPTY_GRAPH` | Empty Event Graph | Info | High | — |
| 16 | `BP_TICK_HEAVY` | Tick Performance Risk | Warning | Medium | — |
| 17 | `BP_SELF_CAST` | Self-Cast Detected | Info | High | ✓ |
| 18 | `BP_DEPRECATED_FUNC` | Deprecated API Usage | Warning | Medium | — |
| 19 | `BP_CIRCULAR_DEP` | Circular Dependency | Warning | Medium | — |
| 20 | `BP_MASSIVE_ASSET` | Oversized Blueprint Asset | Warning | High | — |
| 21 | `BP_HARD_REF` | Hard Reference Bloat | Warning | Medium | — |
| 22 | `BP_EXPENSIVE_TICK` | Expensive Operations in Tick | Warning | Medium | — |
| 23 | `BP_DEBUG_NODES` | Debug Nodes in Production | Warning | High | ✓ |
| 24 | `BP_CONSTRUCT_HEAVY` | Construction Script Misuse | Warning | High | — |
| 25 | `BP_FOREACH_PERF` | ForEach Loop Performance | Info | Medium | — |
| 26 | `BP_TIMELINE_HEAVY` | Excessive Timeline Components | Info | Medium | — |

**Totals**: 39 checks (25 AnimBP + 14 Blueprint) | 7 auto-fixable | 18 High / 20 Medium / 1 Low confidence
| 6 Error / 20 Warning / 8 Info

Every check has a full detail panel with: plain-English description, why it
matters, beginner-friendly tip, step-by-step fix guide, and the exact detection
method used by the scanner. Open any issue in the panel to read it, or see
section 4 of the HTML user guide for the reference in one place.

---

## Supported Platforms

- **Editor**: Win64, Mac, Linux (Unreal Engine 5.3 - 5.7)
- **Runtime**: N/A — editor-only plugin, zero cost in packaged builds
- **LoadingPhase**: `PostEngineInit` (loads after core systems, before the editor UI)
- **Module type**: `Editor`

---

## Documentation

The complete user guide ships inside the plugin. Three ways to open it:

1. **`Documentation/BP_Doctor_User_Guide.html`** — open directly in any web browser
2. **Help button** in the BP Doctor panel toolbar (inside the editor)
3. **Help → BP Doctor Documentation** in the editor's main menu bar

The HTML guide has 10 sections covering every feature in step-by-step detail:
Getting Started, Scanning, Fixing Issues, the full 39-check reference,
Managing Checks, Custom Rules, Exporting Reports, CI/CD Integration, Settings,
and FAQ / Troubleshooting.

---

## Support

For issues, questions, or feedback, use the support channel listed on the Fab
product listing. The bundled HTML user guide answers most common questions —
check section 10 (FAQ & Troubleshooting) first.

---

**Version**: 2.7.4
**Engine**: Unreal Engine 5.3 - 5.7
**License**: See Fab EULA
