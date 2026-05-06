# BP Doctor — CI/CD Integration Guide

BP Doctor ships SARIF 2.1.0 output plus ready-to-paste pipeline templates. Studios can wire Blueprint / AnimBlueprint static analysis into the same CI they use for C++ linting, and reviewers see BP issues directly in GitHub / GitLab / Jenkins UIs.

> **Engine version note**: All single-version templates below use `UE_5.7` as the install path. Substitute with your engine version (`UE_5.3` / `UE_5.4` / `UE_5.5` / `UE_5.6` / `UE_5.7` are all supported). Section 2's matrix workflow shows the variable-substitution pattern if you target multiple engine versions.

---

## 1. Commandlet Reference

### Basic invocation

```
UnrealEditor-Cmd.exe <path/to/Project.uproject> -run=BPDoctor [options]
```

### Options

| Flag | Values | Default | Purpose |
|------|--------|---------|---------|
| `-output=<path>` | file path | stdout | Write plain text / JSON report |
| `-format=` | `text` \| `json` | `text` | Format of `-output` file |
| `-sarif=<path>` | file path | — | Write SARIF 2.1.0 report (for code-scanning platforms) |
| `-severity=` | `error` \| `warning` \| `info` | `info` | Minimum severity to include |
| `-fail-on=` | `error` \| `warning` \| `info` \| `none` | `none` | Severity that flips the exit code. `none` = always exit 0 even with issues found (default for non-CI runs). Pass `-failOnError` as a shortcut for `-fail-on=error` |
| `-failOnError` | (flag, no value) | — | Shortcut for `-fail-on=error` (matches common CI templates) |
| `-profile=` | `silent_failures_only` \| `standard` \| `everything` | `silent_failures_only` | Tier set that runs (20 / 28 / 39 checks) |
| `-checks=` | `CODE1,CODE2,...` | — | Allowlist filter — only run the listed check codes |
| `-path=` | content path | `/Game` | Scan only this content subfolder |

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Clean — no issues at fail-on severity or above |
| `1` | Warnings present (strict-mode fail when `-fail-on=warning`) |
| `2` | One or more error-severity issues — build should fail |
| `3` | Reserved for config / parse errors |

---

## 2. GitHub Actions

### Minimal workflow (single UE version)

```yaml
name: BP Doctor
on:
  pull_request:
  push:
    branches: [main]

jobs:
  bp-doctor:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run BP Doctor
        shell: pwsh
        run: |
          & "C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" `
            "${{ github.workspace }}\MyProject.uproject" `
            -run=BPDoctor `
            -sarif=bp_doctor.sarif `
            -fail-on=error

      - name: Upload SARIF to Code Scanning
        if: always()
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: bp_doctor.sarif
          category: bp-doctor
```

After the first run, every issue will appear under **Security → Code scanning alerts** in the repository, with direct links to the offending `.uasset` file.

### Matrix across supported UE versions

```yaml
jobs:
  bp-doctor:
    strategy:
      matrix:
        ue: ['5.3', '5.5', '5.7']
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4

      - name: Cache DDC + Intermediate
        uses: actions/cache@v4
        with:
          path: |
            Intermediate/
            DerivedDataCache/
          key: ue-${{ matrix.ue }}-${{ hashFiles('**/*.uasset') }}
          restore-keys: |
            ue-${{ matrix.ue }}-

      - name: Run BP Doctor (UE ${{ matrix.ue }})
        shell: pwsh
        run: |
          & "C:\Program Files\Epic Games\UE_${{ matrix.ue }}\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" `
            "${{ github.workspace }}\MyProject.uproject" `
            -run=BPDoctor `
            -sarif=bp_doctor.sarif

      - uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: bp_doctor.sarif
          category: bp-doctor-${{ matrix.ue }}
```

---

## 3. GitLab CI

```yaml
bp-doctor:
  stage: test
  tags: [windows]
  script:
    - >
      & "C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
      "$CI_PROJECT_DIR\MyProject.uproject"
      -run=BPDoctor
      -sarif=bp_doctor.sarif
      -output=bp_doctor.json
      -format=json
  artifacts:
    when: always
    reports:
      sast: bp_doctor.sarif
    paths:
      - bp_doctor.json
      - bp_doctor.sarif
    expire_in: 1 month
  allow_failure: false
```

GitLab renders SARIF reports inline on merge requests under the **Security & Compliance** tab.

---

## 4. Jenkins (declarative pipeline)

```groovy
pipeline {
    agent { label 'windows && ue5' }

    stages {
        stage('BP Doctor') {
            steps {
                bat '''
                    "C:\\Program Files\\Epic Games\\UE_5.7\\Engine\\Binaries\\Win64\\UnrealEditor-Cmd.exe" ^
                        "%WORKSPACE%\\MyProject.uproject" ^
                        -run=BPDoctor ^
                        -sarif=bp_doctor.sarif ^
                        -output=bp_doctor.json ^
                        -format=json
                '''
            }
            post {
                always {
                    archiveArtifacts artifacts: 'bp_doctor.*', fingerprint: true

                    // Requires Warnings Next Generation plugin
                    recordIssues(
                        tools: [sarif(pattern: 'bp_doctor.sarif', id: 'bp-doctor', name: 'BP Doctor')],
                        qualityGates: [
                            [threshold: 1, type: 'TOTAL_ERROR', unstable: false],
                            [threshold: 10, type: 'TOTAL_HIGH', unstable: true]
                        ]
                    )
                }
            }
        }
    }
}
```

---

## 5. Pre-commit hook

For fast local validation on the changed Blueprints before every commit.

### `.git/hooks/pre-commit`

```bash
#!/usr/bin/env bash
set -e

# Opt out with BP_DOCTOR_SKIP=1 git commit
if [ "${BP_DOCTOR_SKIP:-0}" = "1" ]; then exit 0; fi

PROJECT="MyProject.uproject"
UE_BIN="/c/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-Cmd.exe"

"$UE_BIN" "$PWD/$PROJECT" -run=BPDoctor -fail-on=error -severity=warning
```

Set executable: `chmod +x .git/hooks/pre-commit`. Bypass with `BP_DOCTOR_SKIP=1 git commit -m "..."` when you need to commit despite errors (e.g. a WIP branch).

---

## 6. SARIF output schema

BP Doctor emits standard SARIF 2.1.0 with BP-specific extensions under `result.properties`:

```json
{
  "ruleId": "BP_COMPLEXITY",
  "level": "warning",
  "message": { "text": "Excessive Complexity 612 nodes detected." },
  "locations": [{
    "physicalLocation": {
      "artifactLocation": { "uri": "Content/Blueprints/BP_Player.uasset" }
    }
  }],
  "properties": {
    "nodeHint": "612 nodes -- consider refactoring to functions or C++",
    "autoFixable": false,
    "assetType": "Blueprint"
  }
}
```

- `ruleId` — one of the 39 check codes (`BP_COMPLEXITY`, `MISSING_SLOT`, `BROKEN_TRANS`, etc.)
- `level` — `error` / `warning` / `note`
- `artifactLocation.uri` — repo-relative path to the `.uasset` (follows the `/Game/Foo → Content/Foo.uasset` convention)
- `properties.autoFixable` — whether `BP Doctor` can fix this automatically via the editor panel
- `properties.nodeHint` — precise human-readable pointer to the offending node

Every consumer that reads SARIF (GitHub Code Scanning, Azure DevOps Advanced Security, SonarQube, Codacy, or custom dashboards) will display these issues without additional configuration.

---

## 7. Troubleshooting

| Symptom | Resolution |
|---------|------------|
| Commandlet runs but produces zero issues on a project you expect to have problems | Open the editor first and force a DDC rebuild. Fresh checkouts can have stale asset registry data. |
| GitHub upload-sarif action says "no results" | Check `bp_doctor.sarif` artifact — if it has `runs[0].results = []`, the scan ran but found nothing at your severity filter. Re-run with `-severity=info`. |
| Jenkins `recordIssues` step fails to parse SARIF | Install / update the Warnings Next Generation plugin — the bundled SARIF parser is updated for v2.1.0. |
| Pre-commit hook takes >30 s | That's normal on first invocation (DDC cold). Use `-checks=` and `-path=` to narrow the scan scope, or move the scan to a CI job rather than a local hook for large projects. |
| Exit code 2 but no errors in report | Check `-severity` filter — you may be suppressing errors from the report while still failing on them. Keep `-severity=info` for CI; use `-fail-on` to gate. |

---

## 8. Future Considerations

The current commandlet covers SARIF, JSON, and text output across GitHub / GitLab / Jenkins / pre-commit hooks. Areas under exploration for future releases (no commitment, no timeline — buyer feedback drives priority):

- Incremental scans (skip unchanged Blueprints from a git-diff file list)
- Additional report formats (JUnit XML, CheckStyle XML, Markdown summary)
- Bundled pre-commit helper script

If any of these would unblock your team, send feedback through the Fab support channel — usage signal directly affects the roadmap.
