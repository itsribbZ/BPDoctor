// Copyright (C) 2025-2026 Jacob Ribbe. All rights reserved.
//
// SARIF 2.1.0 report exporter for BP Doctor scan results.
//
// SARIF (Static Analysis Results Interchange Format) is the OASIS standard consumed by every
// major CI/code-scanning platform: GitHub Code Scanning, Azure DevOps Advanced Security,
// GitLab Security Reports, SonarQube, Codacy, etc. Emitting SARIF from the BP Doctor
// commandlet unlocks first-class BP static analysis in every studio's CI pipeline.
//
// Specification: https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html
// GitHub support: https://docs.github.com/en/code-security/code-scanning/integrating-with-code-scanning/sarif-support-for-code-scanning

#pragma once

#include "CoreMinimal.h"
#include "BPDoctorTypes.h"

class BPDOCTOR_API FBPDoctorSarifExporter
{
public:
	/**
	 * Build a SARIF 2.1.0 JSON document from a scan's results.
	 *
	 * @param Results         Every FBPDoctorResult emitted by the commandlet after severity filtering.
	 * @param TotalScanned    Count of Blueprints that were inspected.
	 * @param PluginVersion   Version string that populates tool.driver.version (e.g. "2.1.0").
	 * @return                A pretty-printed JSON string conforming to the SARIF 2.1.0 schema.
	 */
	static FString Generate(
		const TArray<FBPDoctorResult>& Results,
		int32 TotalScanned,
		const FString& PluginVersion);
};
