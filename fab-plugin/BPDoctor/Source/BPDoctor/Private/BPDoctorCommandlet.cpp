// Copyright (C) 2025-2026 Jacob Ribbe. All rights reserved.

#include "BPDoctorCommandlet.h"
#include "BPDoctorChecks.h"
#include "BPDoctorLog.h"
#include "BPDoctorSarifExporter.h"
#include "BPDoctorTypes.h"

#include "Engine/Blueprint.h"
#include "Animation/AnimBlueprint.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "Interfaces/IPluginManager.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Serialization/JsonSerializer.h"

// LogBPDoctor is defined in BPDoctorLog.cpp so every translation unit shares one category.

UBPDoctorCommandlet::UBPDoctorCommandlet()
{
	IsClient = false;
	IsEditor = true;
	IsServer = false;
	LogToConsole = true;
}

int32 UBPDoctorCommandlet::Main(const FString& Params)
{
	UE_LOG(LogBPDoctor, Display, TEXT(""));
	UE_LOG(LogBPDoctor, Display, TEXT("========================================"));
	UE_LOG(LogBPDoctor, Display, TEXT("  BP Doctor — Blueprint Diagnostics"));
	UE_LOG(LogBPDoctor, Display, TEXT("========================================"));

	// Parse command line
	FString OutputPath, FormatStr, SeverityStr, FailOnStr, SarifPath, ProfileStr, ChecksStr, PathFilter;
	FParse::Value(*Params, TEXT("-output="), OutputPath);
	FParse::Value(*Params, TEXT("-format="), FormatStr);
	FParse::Value(*Params, TEXT("-severity="), SeverityStr);
	FParse::Value(*Params, TEXT("-fail-on="), FailOnStr);
	FParse::Value(*Params, TEXT("-sarif="), SarifPath);
	FParse::Value(*Params, TEXT("-profile="), ProfileStr);
	FParse::Value(*Params, TEXT("-checks="), ChecksStr);
	FParse::Value(*Params, TEXT("-path="), PathFilter);

	// v2.7.1 audit fix: -failOnError is an alias for -fail-on=error so the README's
	// documented usage actually works. Wraps the existing fail-on= machinery — bare
	// flag with no value, FParse::Param returns true if it appears in the param list.
	const bool bFailOnErrorFlag = FParse::Param(*Params, TEXT("failOnError"));

	if (FormatStr.IsEmpty()) FormatStr = TEXT("text");
	if (SeverityStr.IsEmpty()) SeverityStr = TEXT("info");
	// v2.7.2 audit fix: default fail-on=none so a bare commandlet run reports issues but
	// returns exit 0. Previous default was "error", which silently broke CI pipelines that
	// expected exit 0 unless they explicitly opted in via -failOnError. README documents
	// -failOnError as opt-in, so default must be non-failing.
	if (FailOnStr.IsEmpty()) FailOnStr = TEXT("none");

	// -failOnError beats -fail-on= when both are present (most-restrictive wins; users
	// passing both are typically copy-pasting from CI templates and want errors to gate).
	if (bFailOnErrorFlag) FailOnStr = TEXT("error");

	// Default profile in CI mirrors the UI default — silent failures only.
	// Override with -profile=standard or -profile=everything for broader audits.
	EBPDoctorProfile Profile = EBPDoctorProfile::SilentFailuresOnly;
	const FString PS = ProfileStr.ToLower();
	if (PS == TEXT("standard"))        Profile = EBPDoctorProfile::Standard;
	else if (PS == TEXT("everything")) Profile = EBPDoctorProfile::Everything;
	FBPDoctorChecks::SetActiveProfile(Profile);
	UE_LOG(LogBPDoctor, Display, TEXT("Scan profile: %s"),
		(Profile == EBPDoctorProfile::Everything)   ? TEXT("everything") :
		(Profile == EBPDoctorProfile::Standard)     ? TEXT("standard") :
		                                              TEXT("silent_failures_only"));

	// v2.7.1 audit fix: -checks=A,B,C allowlist wires through the existing DisabledChecks
	// machinery — every check NOT in the requested set goes onto the disabled list. Profile
	// gate still applies on top, so -checks=BLEND_WT_SUM -profile=silent_failures_only
	// produces "BLEND_WT_SUM if it's a SilentFailure tier check" (it is).
	if (!ChecksStr.IsEmpty())
	{
		TArray<FString> RequestedChecks;
		ChecksStr.ParseIntoArray(RequestedChecks, TEXT(","), /*bCullEmpty=*/true);

		TSet<FString> RequestedSet;
		for (const FString& R : RequestedChecks)
		{
			RequestedSet.Add(R.TrimStartAndEnd().ToUpper());
		}

		TSet<FString> DisabledSet;
		for (const FBPDoctorCheckDef& Check : FBPDoctorChecks::GetAllChecks())
		{
			if (!RequestedSet.Contains(Check.Code.ToUpper()))
			{
				DisabledSet.Add(Check.Code);
			}
		}

		FBPDoctorChecks::SetDisabledChecks(DisabledSet);
		UE_LOG(LogBPDoctor, Display, TEXT("-checks= filter active: running %d of %d checks"),
			RequestedSet.Num(), FBPDoctorChecks::GetAllChecks().Num());
	}

	// Severity mapping
	auto ParseSeverity = [](const FString& Str) -> EBPDoctorSeverity
	{
		if (Str == TEXT("error")) return EBPDoctorSeverity::Error;
		if (Str == TEXT("warning")) return EBPDoctorSeverity::Warning;
		return EBPDoctorSeverity::Info;
	};

	EBPDoctorSeverity MinSeverity = ParseSeverity(SeverityStr.ToLower());
	EBPDoctorSeverity FailSeverity = ParseSeverity(FailOnStr.ToLower());

	// v2.7.3 audit fix: gate-disable sentinel. ParseSeverity has no "none" branch
	// (it falls through to Info), so without this flag a default `-fail-on=none`
	// would silently fall through to Info-severity gating and exit 1 on any info
	// result — defeating the v2.7.2 "exit 0 by default" contract. The bool is
	// explicit; the FailSeverity parsed above is unused when the gate is disabled.
	const bool bFailGateEnabled = (FailOnStr.ToLower() != TEXT("none"));

	// Discover all Blueprint assets
	IAssetRegistry& AssetRegistry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();
	AssetRegistry.SearchAllAssets(true);

	FARFilter Filter;
	Filter.ClassPaths.Add(UBlueprint::StaticClass()->GetClassPathName());
	// Explicit UAnimBlueprint entry — bRecursiveClasses should catch it as a UBlueprint subclass,
	// but some AssetRegistry implementations stop recursion at one level. Being explicit avoids
	// silently skipping AnimBlueprints in CI reports.
	Filter.ClassPaths.Add(UAnimBlueprint::StaticClass()->GetClassPathName());
	Filter.bRecursiveClasses = true;

	// v2.7.1 audit fix: honor -path= so the README's documented "scan only a subfolder"
	// flag actually works. Defaults to /Game when unset (preserves existing behavior).
	// Trims trailing slash for AssetRegistry compatibility.
	// v2.7.4 audit fix: normalize Windows-style backslashes to forward-slashes so
	// `-path=\Game\Characters` (common Windows CLI mistake) doesn't silently scan zero
	// assets and exit clean. AssetRegistry path comparison is forward-slash-only.
	FString ScanRoot = PathFilter.IsEmpty() ? TEXT("/Game") : PathFilter;
	ScanRoot.ReplaceInline(TEXT("\\"), TEXT("/"), ESearchCase::CaseSensitive);
	if (ScanRoot.EndsWith(TEXT("/")) && ScanRoot.Len() > 1)
	{
		ScanRoot = ScanRoot.LeftChop(1);
	}
	if (!ScanRoot.StartsWith(TEXT("/")))
	{
		// User passed `Game/Foo` instead of `/Game/Foo` — also a common typo.
		ScanRoot = TEXT("/") + ScanRoot;
		UE_LOG(LogBPDoctor, Display, TEXT("-path= was missing leading slash; normalized to %s"), *ScanRoot);
	}
	Filter.PackagePaths.Add(*ScanRoot);
	Filter.bRecursivePaths = true;
	if (!PathFilter.IsEmpty())
	{
		UE_LOG(LogBPDoctor, Display, TEXT("Path filter active: scanning %s"), *ScanRoot);
	}

	TArray<FAssetData> BlueprintAssets;
	AssetRegistry.GetAssets(Filter, BlueprintAssets);

	UE_LOG(LogBPDoctor, Display, TEXT("Found %d Blueprint assets in /Game"), BlueprintAssets.Num());

	// Scan each Blueprint
	TArray<FBPDoctorResult> AllResults;
	int32 Scanned = 0;
	int32 Errors = 0, Warnings = 0, Infos = 0;

	for (const FAssetData& AssetData : BlueprintAssets)
	{
		UBlueprint* BP = Cast<UBlueprint>(AssetData.GetAsset());
		if (!BP) continue;

		Scanned++;

		TArray<FBPDoctorResult> Results = FBPDoctorChecks::RunChecks(BP);
		Results.Append(FBPDoctorChecks::RunCustomRules(BP));

		for (const FBPDoctorResult& R : Results)
		{
			// Filter: include this severity and more severe (Error=0 < Warning=1 < Info=2)
			// Skip anything LESS severe than the minimum (higher enum value = less severe)
			if (static_cast<int32>(R.Severity) > static_cast<int32>(MinSeverity))
				continue;

			AllResults.Add(R);

			switch (R.Severity)
			{
				case EBPDoctorSeverity::Error:   Errors++;   break;
				case EBPDoctorSeverity::Warning: Warnings++; break;
				case EBPDoctorSeverity::Info:    Infos++;    break;
			}
		}

		if (Scanned % 50 == 0)
		{
			UE_LOG(LogBPDoctor, Display, TEXT("  Scanned %d / %d ..."), Scanned, BlueprintAssets.Num());
		}
	}

	// Generate report
	FString Report;
	if (FormatStr.ToLower() == TEXT("json"))
	{
		Report = GenerateJSONReport(AllResults, Scanned);
	}
	else
	{
		Report = GenerateTextReport(AllResults, Scanned);
	}

	// Output (text / json)
	if (OutputPath.IsEmpty() && SarifPath.IsEmpty())
	{
		UE_LOG(LogBPDoctor, Display, TEXT("\n%s"), *Report);
	}
	else if (!OutputPath.IsEmpty())
	{
		// v2.7.4 audit fix: warn (non-fatal) if -output= path resolves outside the
		// project tree. CI scripts with bad args can write anywhere the OS user
		// can write to; surfacing a clear warning lets sec-ops spot misconfigured
		// pipelines without blocking legitimate cross-tree integrations.
		const FString AbsOut = FPaths::ConvertRelativePathToFull(OutputPath);
		const FString ProjRoot = FPaths::ConvertRelativePathToFull(FPaths::ProjectDir());
		if (!AbsOut.StartsWith(ProjRoot))
		{
			UE_LOG(LogBPDoctor, Warning,
				TEXT("-output= path is outside project tree: %s (project root: %s) — proceeding."),
				*AbsOut, *ProjRoot);
		}
		FFileHelper::SaveStringToFile(Report, *OutputPath,
			FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
		UE_LOG(LogBPDoctor, Display, TEXT("Report written to: %s"), *OutputPath);
	}

	// SARIF 2.1.0 export (parallel to text/json — CI pipelines consume this format).
	if (!SarifPath.IsEmpty())
	{
		// Read plugin version at runtime so SARIF tool.driver.version always matches
		// the actual shipped .uplugin, not a hardcoded string (2026-04-23 audit NEW-05).
		TSharedPtr<IPlugin> P = IPluginManager::Get().FindPlugin(TEXT("BPDoctor"));
		const FString Ver = P.IsValid() ? P->GetDescriptor().VersionName : TEXT("unknown");

		// v2.7.4 audit fix: same out-of-tree warning as -output= above.
		const FString AbsSarif = FPaths::ConvertRelativePathToFull(SarifPath);
		const FString ProjRoot = FPaths::ConvertRelativePathToFull(FPaths::ProjectDir());
		if (!AbsSarif.StartsWith(ProjRoot))
		{
			UE_LOG(LogBPDoctor, Warning,
				TEXT("-sarif= path is outside project tree: %s (project root: %s) — proceeding."),
				*AbsSarif, *ProjRoot);
		}
		const FString Sarif = FBPDoctorSarifExporter::Generate(AllResults, Scanned, Ver);
		FFileHelper::SaveStringToFile(Sarif, *SarifPath,
			FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
		UE_LOG(LogBPDoctor, Display, TEXT("SARIF 2.1.0 report written to: %s"), *SarifPath);
	}

	// Summary
	UE_LOG(LogBPDoctor, Display, TEXT(""));
	UE_LOG(LogBPDoctor, Display, TEXT("SUMMARY: Scanned %d BPs | Errors: %d | Warnings: %d | Info: %d"),
		Scanned, Errors, Warnings, Infos);

	// Exit code contract (standard static-analyzer convention):
	//   0 = clean (no issue at or above fail-on severity)
	//   1 = warning-or-info-severity issue tripped the gate (errors absent)
	//   2 = error-severity issue tripped the gate (errors present)
	//   3 = scanner config / input error (reserved — caller-parse failures)
	//
	// Sprint 5 Phase B P8 — gate logic rewritten:
	// (a) Compute the worst severity that fired (Error<Warning<Info).
	// (b) Check if it crosses the FailSeverity threshold.
	// (c) Pick exit code from worst that fired (so error+warning still returns 2).
	// Previous code had no Info-severity branch — fail-on=info on an info-only project
	// silently returned 0 instead of 1, so CI gates with -fail-on=info never fired.
	auto SeverityName = [](EBPDoctorSeverity S) -> const TCHAR*
	{
		switch (S)
		{
			case EBPDoctorSeverity::Error:   return TEXT("ERROR");
			case EBPDoctorSeverity::Warning: return TEXT("WARNING");
			default:                         return TEXT("INFO");
		}
	};

	// Worst severity actually fired. 999 sentinel = nothing fired.
	int32 WorstSeverity = 999;
	if (Errors > 0)        WorstSeverity = static_cast<int32>(EBPDoctorSeverity::Error);
	else if (Warnings > 0) WorstSeverity = static_cast<int32>(EBPDoctorSeverity::Warning);
	else if (Infos > 0)    WorstSeverity = static_cast<int32>(EBPDoctorSeverity::Info);

	const int32 FailLevel = static_cast<int32>(FailSeverity);
	// Gate-disabled short-circuits: bare commandlet (no fail-on flag) ALWAYS exits 0
	// regardless of issue counts. Opt-in via -failOnError or -fail-on=<sev>.
	const bool bGateTripped = bFailGateEnabled && (WorstSeverity <= FailLevel); // numerically lower = more severe

	if (bGateTripped)
	{
		UE_LOG(LogBPDoctor, Warning, TEXT("FAIL: worst severity = %s (fail-on=%s)"),
			SeverityName(static_cast<EBPDoctorSeverity>(WorstSeverity)), *FailOnStr);
		if (Errors > 0)   return 2;   // error present, dominant
		if (Warnings > 0) return 1;   // warnings tripped the gate
		return 1;                     // info-only tripped a fail-on=info gate
	}

	UE_LOG(LogBPDoctor, Display, TEXT("PASS: %d issue(s) found, none at '%s' severity or above"),
		Errors + Warnings + Infos, *FailOnStr);
	return 0;
}

FString UBPDoctorCommandlet::GenerateTextReport(const TArray<FBPDoctorResult>& Results, int32 TotalScanned) const
{
	FString Out;
	Out += TEXT("BP Doctor Scan Report\n");
	Out += FString::Printf(TEXT("Generated: %s\n"), *FDateTime::Now().ToString());
	Out += FString::Printf(TEXT("Scanned: %d Blueprints\n"), TotalScanned);
	Out += TEXT("=============================================\n\n");

	for (const FBPDoctorResult& R : Results)
	{
		FString SevStr = (R.Severity == EBPDoctorSeverity::Error) ? TEXT("ERROR") :
			(R.Severity == EBPDoctorSeverity::Warning) ? TEXT("WARN") : TEXT("INFO");
		Out += FString::Printf(TEXT("[%s] %s — %s: %s\n"), *SevStr, *R.CheckCode, *R.AssetName, *R.Description);
		if (!R.NodeHint.IsEmpty())
			Out += FString::Printf(TEXT("  > %s\n"), *R.NodeHint);
	}

	return Out;
}

FString UBPDoctorCommandlet::GenerateJSONReport(const TArray<FBPDoctorResult>& Results, int32 TotalScanned) const
{
	TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
	Root->SetStringField(TEXT("scan_date"), FDateTime::Now().ToString());
	Root->SetNumberField(TEXT("total_scanned"), TotalScanned);
	Root->SetNumberField(TEXT("total_issues"), Results.Num());

	int32 E = 0, W = 0, I = 0;
	TArray<TSharedPtr<FJsonValue>> IssueArray;

	for (const FBPDoctorResult& R : Results)
	{
		switch (R.Severity)
		{
			case EBPDoctorSeverity::Error: E++; break;
			case EBPDoctorSeverity::Warning: W++; break;
			case EBPDoctorSeverity::Info: I++; break;
		}

		TSharedRef<FJsonObject> Issue = MakeShared<FJsonObject>();
		Issue->SetStringField(TEXT("check_code"), R.CheckCode);
		Issue->SetStringField(TEXT("severity"),
			(R.Severity == EBPDoctorSeverity::Error) ? TEXT("ERROR") :
			(R.Severity == EBPDoctorSeverity::Warning) ? TEXT("WARNING") : TEXT("INFO"));
		Issue->SetStringField(TEXT("asset_name"), R.AssetName);
		Issue->SetStringField(TEXT("asset_path"), R.AssetPath);
		Issue->SetStringField(TEXT("description"), R.Description);
		if (!R.NodeHint.IsEmpty())
			Issue->SetStringField(TEXT("node_hint"), R.NodeHint);
		Issue->SetBoolField(TEXT("auto_fixable"), R.bAutoFixable);

		IssueArray.Add(MakeShared<FJsonValueObject>(Issue));
	}

	Root->SetNumberField(TEXT("errors"), E);
	Root->SetNumberField(TEXT("warnings"), W);
	Root->SetNumberField(TEXT("info"), I);
	Root->SetArrayField(TEXT("issues"), IssueArray);

	FString OutputString;
	TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer =
		TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&OutputString);
	FJsonSerializer::Serialize(Root, Writer);

	return OutputString;
}
