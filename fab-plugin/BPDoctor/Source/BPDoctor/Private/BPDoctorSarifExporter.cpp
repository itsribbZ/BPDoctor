// Copyright (C) 2025-2026 Jacob Ribbe. All rights reserved.

#include "BPDoctorSarifExporter.h"
#include "BPDoctorChecks.h"

#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

namespace
{
	/** SARIF level enum: "error" | "warning" | "note" | "none". BP Doctor maps Info -> note. */
	const TCHAR* ToSarifLevel(EBPDoctorSeverity Severity)
	{
		switch (Severity)
		{
			case EBPDoctorSeverity::Error:   return TEXT("error");
			case EBPDoctorSeverity::Warning: return TEXT("warning");
			case EBPDoctorSeverity::Info:    return TEXT("note");
			default:                         return TEXT("none");
		}
	}

	/**
	 * Convert a UE5 content-root path (/Game/Foo/BP_Bar.BP_Bar) to a repo-relative artifact URI
	 * (Content/Foo/BP_Bar.uasset). SARIF consumers (GitHub, Azure) expect repo-relative URIs so
	 * they can link results to source-controlled files.
	 */
	FString ToArtifactUri(const FString& AssetPath)
	{
		FString Path = AssetPath;

		// Drop the class-name suffix (/Game/Foo/BP_Bar.BP_Bar -> /Game/Foo/BP_Bar).
		// Only trim if the last '.' appears AFTER the last '/'. Paths with a dot
		// in a folder name (e.g. /Game/Folder.WithDot/BP_Foo) would otherwise be
		// corrupted by a naive trim (2026-04-23 audit P3-03).
		int32 DotIdx = INDEX_NONE;
		int32 SlashIdx = INDEX_NONE;
		Path.FindLastChar(TCHAR('.'), DotIdx);
		Path.FindLastChar(TCHAR('/'), SlashIdx);
		if (DotIdx != INDEX_NONE && DotIdx > SlashIdx)
		{
			Path = Path.Left(DotIdx);
		}

		// Swap the UE content root for the repo's Content/ directory.
		if (Path.StartsWith(TEXT("/Game/")))
		{
			Path = TEXT("Content/") + Path.Mid(6);
		}

		return Path + TEXT(".uasset");
	}
}

FString FBPDoctorSarifExporter::Generate(
	const TArray<FBPDoctorResult>& Results,
	int32 TotalScanned,
	const FString& PluginVersion)
{
	// -------------------------------------------------------------------------
	// tool.driver.rules : every check BP Doctor knows about, regardless of whether
	// it fired this run. SARIF viewers let users filter by rule, and GitHub Code
	// Scanning uses ruleId for issue grouping across runs.
	// -------------------------------------------------------------------------
	TArray<TSharedPtr<FJsonValue>> RulesArray;
	for (const FBPDoctorCheckDef& Check : FBPDoctorChecks::GetAllChecks())
	{
		TSharedRef<FJsonObject> Rule = MakeShared<FJsonObject>();
		Rule->SetStringField(TEXT("id"), Check.Code);
		Rule->SetStringField(TEXT("name"), Check.Name);

		TSharedRef<FJsonObject> ShortDesc = MakeShared<FJsonObject>();
		ShortDesc->SetStringField(TEXT("text"), Check.Description);
		Rule->SetObjectField(TEXT("shortDescription"), ShortDesc);

		if (!Check.WhyItMatters.IsEmpty())
		{
			TSharedRef<FJsonObject> FullDesc = MakeShared<FJsonObject>();
			FullDesc->SetStringField(TEXT("text"), Check.WhyItMatters);
			Rule->SetObjectField(TEXT("fullDescription"), FullDesc);
		}

		if (!Check.HowToFix.IsEmpty())
		{
			TSharedRef<FJsonObject> Help = MakeShared<FJsonObject>();
			Help->SetStringField(TEXT("text"), Check.HowToFix);
			Rule->SetObjectField(TEXT("help"), Help);
		}

		TSharedRef<FJsonObject> DefaultCfg = MakeShared<FJsonObject>();
		DefaultCfg->SetStringField(TEXT("level"), ToSarifLevel(Check.Severity));
		Rule->SetObjectField(TEXT("defaultConfiguration"), DefaultCfg);

		// helpUri deep-links to the published docs site per check (populated when docs host is live).
		Rule->SetStringField(
			TEXT("helpUri"),
			FString::Printf(TEXT("https://bpdoctor.dev/docs/checks/%s"), *Check.Code));

		RulesArray.Add(MakeShared<FJsonValueObject>(Rule));
	}

	// -------------------------------------------------------------------------
	// runs[0].results : one entry per FBPDoctorResult that passed severity filtering.
	// -------------------------------------------------------------------------
	TArray<TSharedPtr<FJsonValue>> ResultsArray;
	for (const FBPDoctorResult& R : Results)
	{
		TSharedRef<FJsonObject> Result = MakeShared<FJsonObject>();
		Result->SetStringField(TEXT("ruleId"), R.CheckCode);
		Result->SetStringField(TEXT("level"), ToSarifLevel(R.Severity));

		TSharedRef<FJsonObject> Message = MakeShared<FJsonObject>();
		Message->SetStringField(TEXT("text"), R.Description);
		Result->SetObjectField(TEXT("message"), Message);

		// physicalLocation.artifactLocation.uri : where the issue was found.
		// uriBaseId references run.originalUriBaseIds["%SRCROOT%"] so consumers (GitHub
		// Code Scanning, Azure DevOps, GitLab Security) can resolve repo-relative paths
		// against their own checkout root. Without this, file links are dead in those
		// tools (SARIF 2.1.0 §3.4.4 — v2.7.2 audit fix).
		TSharedRef<FJsonObject> ArtifactLocation = MakeShared<FJsonObject>();
		ArtifactLocation->SetStringField(TEXT("uri"), ToArtifactUri(R.AssetPath));
		ArtifactLocation->SetStringField(TEXT("uriBaseId"), TEXT("%SRCROOT%"));

		TSharedRef<FJsonObject> PhysicalLocation = MakeShared<FJsonObject>();
		PhysicalLocation->SetObjectField(TEXT("artifactLocation"), ArtifactLocation);

		TSharedRef<FJsonObject> Location = MakeShared<FJsonObject>();
		Location->SetObjectField(TEXT("physicalLocation"), PhysicalLocation);

		TArray<TSharedPtr<FJsonValue>> LocationsArray;
		LocationsArray.Add(MakeShared<FJsonValueObject>(Location));
		Result->SetArrayField(TEXT("locations"), LocationsArray);

		// properties.* : vendor-specific extensions (BP Doctor node hint + fixability).
		TSharedRef<FJsonObject> Props = MakeShared<FJsonObject>();
		if (!R.NodeHint.IsEmpty())
		{
			Props->SetStringField(TEXT("nodeHint"), R.NodeHint);
		}
		Props->SetBoolField(TEXT("autoFixable"), R.bAutoFixable);
		Props->SetStringField(TEXT("assetType"),
			R.AssetType == EBPDoctorAssetType::AnimBP ? TEXT("AnimBlueprint") : TEXT("Blueprint"));
		Result->SetObjectField(TEXT("properties"), Props);

		ResultsArray.Add(MakeShared<FJsonValueObject>(Result));
	}

	// -------------------------------------------------------------------------
	// tool.driver : the analyzer's identity. GitHub Code Scanning keys results by
	// (tool.driver.name, rule.id) pairs, so these fields are load-bearing.
	// -------------------------------------------------------------------------
	TSharedRef<FJsonObject> Driver = MakeShared<FJsonObject>();
	Driver->SetStringField(TEXT("name"), TEXT("BP Doctor"));
	Driver->SetStringField(TEXT("version"), PluginVersion);
	Driver->SetStringField(TEXT("informationUri"), TEXT("https://bpdoctor.dev"));
	Driver->SetStringField(TEXT("semanticVersion"), PluginVersion);
	Driver->SetArrayField(TEXT("rules"), RulesArray);

	TSharedRef<FJsonObject> Tool = MakeShared<FJsonObject>();
	Tool->SetObjectField(TEXT("driver"), Driver);

	// Invocation metadata — helps CI consumers correlate SARIF uploads with runs.
	TSharedRef<FJsonObject> Invocation = MakeShared<FJsonObject>();
	Invocation->SetStringField(TEXT("endTimeUtc"), FDateTime::UtcNow().ToIso8601());
	Invocation->SetBoolField(TEXT("executionSuccessful"), true);

	TSharedRef<FJsonObject> InvocationProps = MakeShared<FJsonObject>();
	InvocationProps->SetNumberField(TEXT("totalScanned"), TotalScanned);
	InvocationProps->SetNumberField(TEXT("totalIssues"), Results.Num());
	Invocation->SetObjectField(TEXT("properties"), InvocationProps);

	TArray<TSharedPtr<FJsonValue>> Invocations;
	Invocations.Add(MakeShared<FJsonValueObject>(Invocation));

	TSharedRef<FJsonObject> Run = MakeShared<FJsonObject>();
	Run->SetObjectField(TEXT("tool"), Tool);
	Run->SetArrayField(TEXT("invocations"), Invocations);
	Run->SetArrayField(TEXT("results"), ResultsArray);

	// originalUriBaseIds : declares the %SRCROOT% base referenced by every artifactLocation.
	// SARIF 2.1.0 §3.14.14 — required when results use uriBaseId. GitHub Code Scanning
	// resolves %SRCROOT% to the repo root automatically; other consumers fall back to
	// the description text. v2.7.2 audit fix.
	TSharedRef<FJsonObject> SrcRootBase = MakeShared<FJsonObject>();
	SrcRootBase->SetStringField(TEXT("description"),
		TEXT("Project root containing the .uproject and Content/ directory."));
	TSharedRef<FJsonObject> OriginalUriBaseIds = MakeShared<FJsonObject>();
	OriginalUriBaseIds->SetObjectField(TEXT("%SRCROOT%"), SrcRootBase);
	Run->SetObjectField(TEXT("originalUriBaseIds"), OriginalUriBaseIds);

	TArray<TSharedPtr<FJsonValue>> Runs;
	Runs.Add(MakeShared<FJsonValueObject>(Run));

	TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
	Root->SetStringField(TEXT("$schema"),
		TEXT("https://json.schemastore.org/sarif-2.1.0.json"));
	Root->SetStringField(TEXT("version"), TEXT("2.1.0"));
	Root->SetArrayField(TEXT("runs"), Runs);

	FString Out;
	TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer =
		TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&Out);
	FJsonSerializer::Serialize(Root, Writer);
	return Out;
}
