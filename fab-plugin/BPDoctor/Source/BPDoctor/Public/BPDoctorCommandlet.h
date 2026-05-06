// Copyright (C) 2025-2026 Jacob Ribbe. All rights reserved.

#pragma once

#include "Commandlets/Commandlet.h"
#include "BPDoctorCommandlet.generated.h"

/**
 * BP Doctor Commandlet — headless Blueprint scanning for CI/CD pipelines.
 *
 * Usage:
 *   UnrealEditor-Cmd.exe Project.uproject -run=BPDoctor [options]
 *
 * Options:
 *   -output=<path>                Plain text or JSON report path (default: stdout)
 *   -format=text|json             Report format for -output (default: text)
 *   -sarif=<path>                 SARIF 2.1.0 report path for GitHub / GitLab / Azure
 *   -severity=error|warning|info  Minimum severity to include (default: info)
 *   -fail-on=error|warning|info|none
 *                                 Severity that flips the exit code (default: none — exit 0
 *                                 even when issues are found; opt in via this flag or -failOnError)
 *   -failOnError                  Bare flag, alias for -fail-on=error (matches CI templates)
 *   -profile=silent_failures_only|standard|everything
 *                                 Tier set that runs (20 / 28 / 39 checks; default: silent_failures_only)
 *   -checks=CODE1,CODE2,...       Allowlist filter — only run the listed check codes
 *   -path=/Game/Subfolder         Scan only a content subfolder (default: /Game)
 *
 * Exit codes:
 *   0 = Clean — no issues at fail-on severity (or no fail-on flag set)
 *   1 = Warnings / info tripped the gate (errors absent but threshold met)
 *   2 = One or more error-severity issues — build should fail
 *   3 = Reserved for parse / config errors
 *
 * Examples:
 *   # Default — exit 0 even with issues. Useful for non-gating CI summary.
 *   UnrealEditor-Cmd.exe MyProject.uproject -run=BPDoctor -output=report.txt
 *
 *   # CI gate: fail on any error.
 *   UnrealEditor-Cmd.exe MyProject.uproject -run=BPDoctor -failOnError -sarif=bp.sarif
 *
 *   # Strict mode: fail on any warning or error.
 *   UnrealEditor-Cmd.exe MyProject.uproject -run=BPDoctor -fail-on=warning
 *
 *   # Filtered scan: only one check, only one folder.
 *   UnrealEditor-Cmd.exe MyProject.uproject -run=BPDoctor -checks=NULL_ANIM_REF -path=/Game/Characters
 */
UCLASS()
class UBPDoctorCommandlet : public UCommandlet
{
	GENERATED_BODY()

public:
	UBPDoctorCommandlet();
	virtual int32 Main(const FString& Params) override;

private:
	FString GenerateTextReport(const TArray<struct FBPDoctorResult>& Results, int32 TotalScanned) const;
	FString GenerateJSONReport(const TArray<struct FBPDoctorResult>& Results, int32 TotalScanned) const;
};
