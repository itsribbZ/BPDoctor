// Copyright (C) 2025-2026 Jacob Ribbe. All rights reserved.

#include "BPDoctorScanner.h"
#include "BPDoctorChecks.h"

#include "Animation/AnimBlueprint.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "Engine/Blueprint.h"
#include "Misc/ScopedSlowTask.h"

FBPDoctorScanner::FBPDoctorScanner()
{
}

// ─────────────────────────────────────────────────────────────────
//  ASSET DISCOVERY
// ─────────────────────────────────────────────────────────────────

TArray<FAssetData> FBPDoctorScanner::DiscoverAssets(const FString& Path) const
{
	IAssetRegistry& AssetRegistry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();

	FARFilter Filter;
	Filter.ClassPaths.Add(UBlueprint::StaticClass()->GetClassPathName());
	Filter.ClassPaths.Add(UAnimBlueprint::StaticClass()->GetClassPathName());
	Filter.bRecursiveClasses = true;
	Filter.bRecursivePaths = true;

	if (!Path.IsEmpty())
	{
		Filter.PackagePaths.Add(FName(*Path));
	}
	else
	{
		Filter.PackagePaths.Add(FName("/Game"));
	}

	TArray<FAssetData> Assets;
	AssetRegistry.GetAssets(Filter, Assets);
	return Assets;
}

// ─────────────────────────────────────────────────────────────────
//  SCANNING
// ─────────────────────────────────────────────────────────────────

void FBPDoctorScanner::ScanProject()
{
	ScanDirectory(FString());
}

void FBPDoctorScanner::ScanDirectory(const FString& ContentPath)
{
	bCancelled = false;
	ScanResults.Empty();

	TArray<FAssetData> Assets = DiscoverAssets(ContentPath);

	FScopedSlowTask SlowTask(Assets.Num(), FText::FromString(TEXT("BP Doctor: Scanning project...")));
	SlowTask.MakeDialog(true);

	for (int32 i = 0; i < Assets.Num(); i++)
	{
		if (bCancelled || SlowTask.ShouldCancel())
		{
			bCancelled = true;
			break;
		}

		SlowTask.EnterProgressFrame(1.0f,
			FText::FromString(FString::Printf(TEXT("Scanning: %s (%d/%d)"),
				*Assets[i].AssetName.ToString(), i + 1, Assets.Num())));

		UBlueprint* BP = Cast<UBlueprint>(Assets[i].GetAsset());
		if (!BP) continue;

		FBPDoctorAssetInfo Info = ScanBlueprint(BP);
		ScanResults.Add(MoveTemp(Info));

		OnProgress.ExecuteIfBound(i + 1, Assets.Num());
	}

	// Post-scan: circular dependency detection
	DetectCircularDeps();

	OnComplete.ExecuteIfBound(ScanResults);
}

void FBPDoctorScanner::ScanAsset(const FString& AssetPath)
{
	bCancelled = false;

	IAssetRegistry& AssetRegistry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();
	FAssetData AssetData = AssetRegistry.GetAssetByObjectPath(FSoftObjectPath(AssetPath));

	if (AssetData.IsValid())
	{
		UBlueprint* BP = Cast<UBlueprint>(AssetData.GetAsset());
		if (BP)
		{
			FBPDoctorAssetInfo Info = ScanBlueprint(BP);
			ScanResults.Add(MoveTemp(Info));
		}
	}
}

FBPDoctorAssetInfo FBPDoctorScanner::ScanBlueprint(UBlueprint* Blueprint)
{
	FBPDoctorAssetInfo Info;
	Info.Name = Blueprint->GetName();
	Info.AssetPath = Blueprint->GetPathName();
	Info.bScanned = true;

	// Determine asset type
	UAnimBlueprint* AnimBP = Cast<UAnimBlueprint>(Blueprint);
	Info.AssetType = AnimBP ? EBPDoctorAssetType::AnimBP : EBPDoctorAssetType::Blueprint;

	// Get file size
	FString PackagePath = Blueprint->GetOutermost()->GetName();
	FString FilePath;
	if (FPackageName::DoesPackageExist(PackagePath, &FilePath))
	{
		Info.FileSize = IFileManager::Get().FileSize(*FilePath);
	}

	// Run built-in checks + custom rules
	Info.Issues = FBPDoctorChecks::RunChecks(Blueprint);
	Info.Issues.Append(FBPDoctorChecks::RunCustomRules(Blueprint));

	// Calculate grade
	Info.Grade = CalculateGrade(Info.Issues);

	return Info;
}

// ─────────────────────────────────────────────────────────────────
//  CIRCULAR DEPENDENCY DETECTION (post-scan)
// ─────────────────────────────────────────────────────────────────

void FBPDoctorScanner::DetectCircularDeps()
{
	const FBPDoctorCheckDef* Check = FBPDoctorChecks::FindCheck(TEXT("BP_CIRCULAR_DEP"));
	if (!Check) return;

	// Build reference map from scan results
	// This is a simplified version — the full implementation would use
	// FAssetRegistry dependency tracking
	IAssetRegistry& AssetRegistry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();

	TMap<FName, TArray<FName>> DependencyMap;
	for (const FBPDoctorAssetInfo& Info : ScanResults)
	{
		// GetDependencies expects package name (/Game/Path/BP), not object path (/Game/Path/BP.BP)
		FString PkgName = Info.AssetPath;
		int32 DotIdx;
		if (PkgName.FindChar('.', DotIdx))
		{
			PkgName.LeftInline(DotIdx);
		}
		FName AssetName(*PkgName);
		TArray<FName> Dependencies;
		AssetRegistry.GetDependencies(AssetName, Dependencies);
		DependencyMap.Add(AssetName, Dependencies);
	}

	// Check for bidirectional references
	for (const auto& Pair : DependencyMap)
	{
		for (const FName& Dep : Pair.Value)
		{
			if (const TArray<FName>* DepDeps = DependencyMap.Find(Dep))
			{
				if (DepDeps->Contains(Pair.Key))
				{
					// Found circular dependency — add to the appropriate asset's issues
					for (FBPDoctorAssetInfo& Info : ScanResults)
					{
						if (FName(*Info.AssetPath) == Pair.Key)
						{
							FBPDoctorResult Result;
							Result.CheckCode = Check->Code;
							Result.Severity = Check->Severity;
							Result.AssetName = Info.Name;
							Result.AssetPath = Info.AssetPath;
							Result.Description = FString::Printf(TEXT("%s Circular: %s <-> %s"),
								*Check->Description, *Pair.Key.ToString(), *Dep.ToString());
							Result.NodeHint = FString::Printf(TEXT("Circular dependency with %s"),
								*Dep.ToString());
							Result.AssetType = EBPDoctorAssetType::Blueprint;

							// Avoid duplicates
							bool bAlreadyReported = false;
							for (const auto& Existing : Info.Issues)
							{
								if (Existing.CheckCode == Result.CheckCode &&
									Existing.NodeHint == Result.NodeHint)
								{
									bAlreadyReported = true;
									break;
								}
							}
							if (!bAlreadyReported)
							{
								Info.Issues.Add(Result);
							}
							break;
						}
					}
				}
			}
		}
	}
}

// ─────────────────────────────────────────────────────────────────
//  GRADING
// ─────────────────────────────────────────────────────────────────

FString FBPDoctorScanner::CalculateGrade(const TArray<FBPDoctorResult>& Issues)
{
	int32 Errors = 0, Warnings = 0, Infos = 0;
	for (const auto& Issue : Issues)
	{
		switch (Issue.Severity)
		{
			case EBPDoctorSeverity::Error:   Errors++;   break;
			case EBPDoctorSeverity::Warning: Warnings++; break;
			case EBPDoctorSeverity::Info:    Infos++;    break;
		}
	}

	if (Errors == 0 && Warnings == 0 && Infos == 0) return TEXT("A+");
	if (Errors == 0 && Warnings == 0) return TEXT("A");
	if (Errors == 0 && Warnings <= 2) return TEXT("B+");
	if (Errors == 0) return TEXT("B");
	if (Errors == 1) return TEXT("C");
	if (Errors <= 3) return TEXT("D");
	return TEXT("F");
}

// ─────────────────────────────────────────────────────────────────
//  SUMMARY COUNTS
// ─────────────────────────────────────────────────────────────────

int32 FBPDoctorScanner::GetAnimBPCount() const
{
	int32 Count = 0;
	for (const auto& Info : ScanResults)
	{
		if (Info.AssetType == EBPDoctorAssetType::AnimBP) Count++;
	}
	return Count;
}

int32 FBPDoctorScanner::GetBlueprintCount() const
{
	int32 Count = 0;
	for (const auto& Info : ScanResults)
	{
		if (Info.AssetType == EBPDoctorAssetType::Blueprint) Count++;
	}
	return Count;
}

int32 FBPDoctorScanner::GetErrorCount() const
{
	int32 Count = 0;
	for (const auto& Info : ScanResults)
	{
		for (const auto& Issue : Info.Issues)
		{
			if (Issue.Severity == EBPDoctorSeverity::Error) Count++;
		}
	}
	return Count;
}

int32 FBPDoctorScanner::GetWarningCount() const
{
	int32 Count = 0;
	for (const auto& Info : ScanResults)
	{
		for (const auto& Issue : Info.Issues)
		{
			if (Issue.Severity == EBPDoctorSeverity::Warning) Count++;
		}
	}
	return Count;
}

int32 FBPDoctorScanner::GetInfoCount() const
{
	int32 Count = 0;
	for (const auto& Info : ScanResults)
	{
		for (const auto& Issue : Info.Issues)
		{
			if (Issue.Severity == EBPDoctorSeverity::Info) Count++;
		}
	}
	return Count;
}
