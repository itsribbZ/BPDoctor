// Copyright (C) 2025-2026 Jacob Ribbe. All rights reserved.

#pragma once

#include "CoreMinimal.h"
#include "BPDoctorTypes.h"

class UBlueprint;

DECLARE_DELEGATE_TwoParams(FBPDoctorScanProgress, int32 /*Current*/, int32 /*Total*/);
DECLARE_DELEGATE_OneParam(FBPDoctorScanComplete, const TArray<FBPDoctorAssetInfo>& /*Results*/);

/**
 * Project-wide Blueprint scanner.
 * Discovers all AnimBP and Blueprint assets using FAssetRegistry,
 * runs all applicable checks, and reports results.
 */
class BPDOCTOR_API FBPDoctorScanner
{
public:
	FBPDoctorScanner();

	/** Scan all Blueprints in the project. */
	void ScanProject();

	/** Scan a specific directory path (e.g., /Game/Characters). */
	void ScanDirectory(const FString& ContentPath);

	/** Scan a single asset by path. */
	void ScanAsset(const FString& AssetPath);

	/** Get scan results. */
	const TArray<FBPDoctorAssetInfo>& GetResults() const { return ScanResults; }

	/** Get summary counts. */
	int32 GetAnimBPCount() const;
	int32 GetBlueprintCount() const;
	int32 GetErrorCount() const;
	int32 GetWarningCount() const;
	int32 GetInfoCount() const;

	/** Calculate grade for an asset based on its issues. */
	static FString CalculateGrade(const TArray<FBPDoctorResult>& Issues);

	/** Progress and completion delegates. */
	FBPDoctorScanProgress OnProgress;
	FBPDoctorScanComplete OnComplete;

	/** Cancel a running scan. */
	void Cancel() { bCancelled = true; }
	bool IsCancelled() const { return bCancelled; }

private:
	/** Internal: discover and collect asset paths. */
	TArray<FAssetData> DiscoverAssets(const FString& Path = FString()) const;

	/** Internal: scan a single loaded Blueprint. */
	FBPDoctorAssetInfo ScanBlueprint(UBlueprint* Blueprint);

	/** Post-scan: detect circular dependencies across all scanned assets. */
	void DetectCircularDeps();

	TArray<FBPDoctorAssetInfo> ScanResults;
	bool bCancelled = false;
};
