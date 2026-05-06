// Copyright (C) 2025-2026 Jacob Ribbe. All rights reserved.

#pragma once

#include "CoreMinimal.h"
#include "BPDoctorTypes.h"

class UBlueprint;

/**
 * Auto-fix system for BP Doctor.
 * Applies programmatic fixes to Blueprints for auto-fixable checks.
 *
 * Fixable checks (7):
 *   BROKEN_BLEND_WT  — Clamp blend weight to [0, 1]
 *   MISSING_SLOT     — Add a DefaultSlot node to AnimGraph
 *   DUP_SLOT         — Rename duplicate slot names to unique
 *   ORPHANED_NODE    — Delete AnimGraph nodes not reachable from Output Pose
 *   BP_SELF_CAST     — Remove self-cast nodes, reroute to Self (incl. CastFailed branch)
 *   BP_DEBUG_NODES   — Delete PrintString/DrawDebug nodes
 *   BLEND_WT_SUM     — Normalize LayeredBoneBlend weights so they sum to 1.0
 */
class BPDOCTOR_API FBPDoctorFixes
{
public:
	/** Preview a fix without applying it. Returns a description of what would change. */
	static FBPDoctorFixAction PreviewFix(const FBPDoctorResult& Issue, UBlueprint* Blueprint);

	/** Apply a fix. CustomValue allows manual override for checks that support it. */
	static bool ApplyFix(const FBPDoctorResult& Issue, UBlueprint* Blueprint, const FString& CustomValue = FString());

	/** Apply all auto-fixable issues for a Blueprint. Returns count of fixes applied. */
	static int32 ApplyAllFixes(const TArray<FBPDoctorResult>& Issues, UBlueprint* Blueprint);

private:
	static bool FixBrokenBlendWeight(UBlueprint* BP, const FString& CustomValue = FString());
	static bool FixMissingSlot(UBlueprint* BP);
	static bool FixDuplicateSlot(UBlueprint* BP, const FString& CustomValue = FString());
	static bool FixSelfCast(UBlueprint* BP);
	static bool FixDebugNodes(UBlueprint* BP);
	static bool FixOrphanedNode(UBlueprint* BP);
	static bool FixBlendWeightSum(UBlueprint* BP);
};
