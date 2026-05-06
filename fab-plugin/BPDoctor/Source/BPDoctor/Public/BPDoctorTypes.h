// Copyright (C) 2025-2026 Jacob Ribbe. All rights reserved.

#pragma once

#include "CoreMinimal.h"

// Forward decl — TWeakObjectPtr only needs the class name, not the full UEdGraphNode definition.
// Sprint 5 Phase B P1: FBPDoctorResult now carries a stable node ptr so NavigateToIssue can land
// directly on the offending node without string-matching, and so the panel can render GraphPath.
class UEdGraphNode;

/** Severity levels for diagnostic checks. */
UENUM()
enum class EBPDoctorSeverity : uint8
{
	Error,
	Warning,
	Info
};

/** Detection confidence level. */
UENUM()
enum class EBPDoctorConfidence : uint8
{
	High,
	Medium,
	Low
};

/** Asset type being scanned. */
UENUM()
enum class EBPDoctorAssetType : uint8
{
	AnimBP,
	Blueprint
};

/** Experience / skill level — controls detail verbosity. */
UENUM()
enum class EBPDoctorExperienceMode : uint8
{
	Beginner,      // Full guidance — beginner tips, why-it-matters, step-by-step
	Intermediate,  // Standard — descriptions and fix steps, no hand-holding
	Expert         // Minimal — code, severity, one-line hint
};

/**
 * Scan profile — which checks run by default.
 * The 2026-04-23 real-world review flagged false positives from stylistic checks.
 * Profiles let the user trade breadth for signal: SilentFailuresOnly is the default
 * for new installs and runs only the checks whose findings cost hours of debug time.
 */
UENUM()
enum class EBPDoctorProfile : uint8
{
	SilentFailuresOnly, // Tier::SilentFailure only — ~19 checks (Phase D added 5), zero noise. Default.
	Standard,           // SilentFailure + Contextual tiers — ~28 checks, real-world dev.
	Everything          // All 39 checks including stylistic + deprecated-duplicate. Power users.
};

/**
 * Check tier — determines which profile(s) include a check.
 *  SilentFailure: always shown. Bug compiles clean, ships to prod, costs hours.
 *  Contextual:    shown in Standard/Everything. Real smell but intent-dependent.
 *  Stylistic:     shown in Everything only. Heuristic/preference, high false-positive rate.
 *  Deprecated:    shown in Everything only. UE compiler already warns — redundant.
 */
UENUM()
enum class EBPDoctorTier : uint8
{
	SilentFailure,
	Contextual,
	Stylistic,
	Deprecated
};

/** Fix approach type. */
UENUM()
enum class EBPDoctorFixType : uint8
{
	Programmatic,  // Direct graph modification via API
	Script,        // Generated Python/C++ script for user to run
	Manual         // Step-by-step instructions only
};

/** Custom rule match type. */
UENUM()
enum class EBPDoctorRuleType : uint8
{
	None,           // Built-in check (not a custom rule)
	BannedFunction, // Flag any call to a specific function name
	BannedNode,     // Flag any node whose class name contains a string
	RequiredNode,   // Flag if NO node of a class exists in the graph
	NodeLimit       // Flag if node count exceeds a threshold
};

/** Custom rule definition (loaded from JSON). */
struct FBPDoctorCustomRule
{
	EBPDoctorRuleType Type = EBPDoctorRuleType::None;
	FString MatchString;  // Function name, node class substring, etc.
	int32 MaxCount = 0;   // For NodeLimit type
	bool bAnimBPOnly = false;
};

/** Definition of a single diagnostic check. */
struct FBPDoctorCheckDef
{
	int32 Id;
	FString Name;
	FString Code;
	EBPDoctorSeverity Severity;
	EBPDoctorConfidence Confidence;
	EBPDoctorTier Tier;   // Which profiles include this check
	bool bAutoFixable;
	FString Description;
	FString WhyItMatters;
	FString BeginnerTip;
	FString HowToFix;     // Step-by-step fix instructions
	FString DetectionMethod; // How this check works (for confidence transparency)
	FBPDoctorCustomRule CustomRule; // Non-None if this is a user-defined custom rule

	FBPDoctorCheckDef()
		: Id(0)
		, Severity(EBPDoctorSeverity::Info)
		, Confidence(EBPDoctorConfidence::Medium)
		, Tier(EBPDoctorTier::Contextual)
		, bAutoFixable(false)
	{}
};

/** Result of running a single check on a single asset. */
struct FBPDoctorResult
{
	FString CheckCode;
	EBPDoctorSeverity Severity;
	FString AssetName;
	FString AssetPath;
	FString Description;
	FString NodeHint;
	bool bAutoFixable = false;
	bool bFixed = false;
	EBPDoctorAssetType AssetType = EBPDoctorAssetType::AnimBP;

	// Sprint 5 Phase B specificity layer — populated when the check has a concrete node target.
	// GraphPath: human-readable breadcrumb like "AnimGraph > LocomotionSM > Idle". Empty = top-level
	//            or no-node check (e.g. SKEL_MISMATCH, BP_BROKEN_REF).
	// Node:      stable weak ptr to the offending UEdGraphNode. Used by NavigateToIssue for direct
	//            zoom-to-node (no string matching). Weak so it's safe across BP recompiles.
	FString GraphPath;
	TWeakObjectPtr<UEdGraphNode> Node;

	FBPDoctorResult() = default;
};

/** Info about a scanned asset. */
struct FBPDoctorAssetInfo
{
	FString Name;
	FString AssetPath;
	int64 FileSize = 0;
	TArray<FBPDoctorResult> Issues;
	FString Grade;
	bool bScanned = false;
	EBPDoctorAssetType AssetType = EBPDoctorAssetType::AnimBP;

	FBPDoctorAssetInfo() = default;
};

/** A proposed fix action. */
struct FBPDoctorFixAction
{
	FString CheckCode;
	FString AssetName;
	FString AssetPath;
	EBPDoctorFixType FixType;
	FString Description;
	FString Preview;
	FString ScriptContent;

	FBPDoctorFixAction()
		: FixType(EBPDoctorFixType::Manual)
	{}
};

/** Record of an applied fix for undo tracking. */
struct FBPDoctorFixHistoryEntry
{
	FString CheckCode;
	FString AssetName;
	FString AssetPath;
	FString FixDescription;
	FDateTime Timestamp;
	bool bReverted = false;

	// Backup: maps original .uasset disk path -> backup .uasset path
	// Used for bulletproof revert — file copy, no engine API gamble
	TMap<FString, FString> Backups;

	FBPDoctorFixHistoryEntry()
		: Timestamp(FDateTime::Now())
	{}
};
