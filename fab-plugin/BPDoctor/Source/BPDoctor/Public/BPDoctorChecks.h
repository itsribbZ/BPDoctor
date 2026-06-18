// Copyright (C) 2025-2026 Jacob Ribbe. All rights reserved.

#pragma once

#include "CoreMinimal.h"
#include "BPDoctorTypes.h"

class UBlueprint;
class UAnimBlueprint;

/**
 * BP Doctor Check Registry.
 * Contains all 39 diagnostic check definitions and their handler functions.
 * 25 AnimBP-specific + 14 General Blueprint checks.
 */
class FBPDoctorChecks
{
public:
	/** Get all check definitions. */
	static const TArray<FBPDoctorCheckDef>& GetAllChecks();

	/** Get a check definition by code. */
	static const FBPDoctorCheckDef* FindCheck(const FString& Code);

	/** Run all applicable checks on a Blueprint asset. Returns results. */
	static TArray<FBPDoctorResult> RunChecks(UBlueprint* Blueprint);

	/** Run a single check by code. */
	static TArray<FBPDoctorResult> RunCheck(const FString& CheckCode, UBlueprint* Blueprint);

	/** Run custom rules against a Blueprint. */
	static TArray<FBPDoctorResult> RunCustomRules(UBlueprint* Blueprint);

	/** Set which checks are disabled (skipped during scanning). */
	static void SetDisabledChecks(const TSet<FString>& Codes);

	/** Force reload of custom rules from disk on next GetAllChecks(). */
	static void RefreshCustomRules();

	/** Get the active scan profile (defaults to SilentFailuresOnly for new installs). */
	static EBPDoctorProfile GetActiveProfile();

	/** Set the active scan profile. Persisted via SBPDoctorPanel::SaveSettings. */
	static void SetActiveProfile(EBPDoctorProfile Profile);

	/** True if a check with the given tier runs under the given profile. */
	static bool IsTierInProfile(EBPDoctorTier Tier, EBPDoctorProfile Profile);

private:
	// ── AnimBP Checks (1-12) ──
	static TArray<FBPDoctorResult> CheckNullAnimRef(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);
	static TArray<FBPDoctorResult> CheckBrokenBlendWeight(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);
	static TArray<FBPDoctorResult> CheckSkeletonMismatch(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);
	static TArray<FBPDoctorResult> CheckMissingSlot(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);
	static TArray<FBPDoctorResult> CheckBrokenTransition(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);
	static TArray<FBPDoctorResult> CheckTPoseFallback(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);
	static TArray<FBPDoctorResult> CheckOrphanedNode(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);
	static TArray<FBPDoctorResult> CheckInvalidBlendSpace(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);
	static TArray<FBPDoctorResult> CheckMissingNotify(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);
	static TArray<FBPDoctorResult> CheckDuplicateSlot(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);
	static TArray<FBPDoctorResult> CheckUnusedVariable(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);
	static TArray<FBPDoctorResult> CheckDeprecatedNode(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);

	// ── AnimBP Checks v2 (27-34) — added 2026-04-16 per Phase 2C Bible-alignment audit.
	//   These catch Motion Matching, Linked Layer, slot-name, cached-pose, and state-machine
	//   anti-patterns that the original 12 checks don't cover. MM checks use class-name
	//   string comparison so BPDoctor stays compilable even without PoseSearch module linked.
	static TArray<FBPDoctorResult> CheckMMNoDatabase(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);
	static TArray<FBPDoctorResult> CheckMMNoInertialization(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);
	static TArray<FBPDoctorResult> CheckSlotNameMismatch(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);
	static TArray<FBPDoctorResult> CheckDeadCachedPose(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);
	static TArray<FBPDoctorResult> CheckEmptyStateMachine(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);
	static TArray<FBPDoctorResult> CheckBlendWeightSum(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);
	static TArray<FBPDoctorResult> CheckEmptyBranchFilter(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);
	static TArray<FBPDoctorResult> CheckDisconnectedSlotSource(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);

	// ── AnimBP Checks v3 (35-39) — added 2026-04-24 per Sprint 5 Phase D coverage expansion.
	//   These close five common silent-failure classes the audit + Lyra-validation prep
	//   surfaced as "ships to prod, costs hours, UE compiler doesn't warn."
	static TArray<FBPDoctorResult> CheckRootMotionModeMismatch(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);
	static TArray<FBPDoctorResult> CheckLinkedAnimLayerNoLayer(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);
	static TArray<FBPDoctorResult> CheckCurveAlphaMissing(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);
	static TArray<FBPDoctorResult> CheckMontageSectionLoop(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);
	static TArray<FBPDoctorResult> CheckBlendSpaceZeroAxis(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP);

	// ── General BP Checks (13-26) ──
	static TArray<FBPDoctorResult> CheckBrokenAssetRef(const FBPDoctorCheckDef& Check, UBlueprint* BP);
	static TArray<FBPDoctorResult> CheckComplexity(const FBPDoctorCheckDef& Check, UBlueprint* BP);
	static TArray<FBPDoctorResult> CheckEmptyGraph(const FBPDoctorCheckDef& Check, UBlueprint* BP);
	static TArray<FBPDoctorResult> CheckTickHeavy(const FBPDoctorCheckDef& Check, UBlueprint* BP);
	static TArray<FBPDoctorResult> CheckSelfCast(const FBPDoctorCheckDef& Check, UBlueprint* BP);
	static TArray<FBPDoctorResult> CheckDeprecatedFunc(const FBPDoctorCheckDef& Check, UBlueprint* BP);
	static TArray<FBPDoctorResult> CheckCircularDep(const FBPDoctorCheckDef& Check, UBlueprint* BP);
	static TArray<FBPDoctorResult> CheckMassiveAsset(const FBPDoctorCheckDef& Check, UBlueprint* BP);
	static TArray<FBPDoctorResult> CheckHardRef(const FBPDoctorCheckDef& Check, UBlueprint* BP);
	static TArray<FBPDoctorResult> CheckExpensiveTick(const FBPDoctorCheckDef& Check, UBlueprint* BP);
	static TArray<FBPDoctorResult> CheckDebugNodes(const FBPDoctorCheckDef& Check, UBlueprint* BP);
	static TArray<FBPDoctorResult> CheckConstructHeavy(const FBPDoctorCheckDef& Check, UBlueprint* BP);
	static TArray<FBPDoctorResult> CheckForEachPerf(const FBPDoctorCheckDef& Check, UBlueprint* BP);
	static TArray<FBPDoctorResult> CheckTimelineHeavy(const FBPDoctorCheckDef& Check, UBlueprint* BP);

	/** Initialize the check definitions array (called once). */
	static void InitChecks();

	/** Load user-defined custom rules from Saved/BPDoctor/CustomRules.json */
	static void LoadCustomRules();

	static TArray<FBPDoctorCheckDef> AllChecks;
	static bool bInitialized;
	static bool bCustomRulesLoaded;
	static TSet<FString> DisabledCheckCodes;
	static EBPDoctorProfile ActiveProfile;
};
