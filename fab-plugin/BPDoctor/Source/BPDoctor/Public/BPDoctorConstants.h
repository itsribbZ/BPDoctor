// Copyright (C) 2025-2026 Jacob Ribbe. All rights reserved.
//
// Named constants for every check threshold BP Doctor ships with.
//
// Rationale: magic numbers scattered through check implementations were flagged in the
// 2026-04-23 source audit (P3-03) as a shipping blocker for configurability. This header
// centralizes them so:
//   1. a single search surfaces every tunable threshold
//   2. UDeveloperSettings (v2.2) can override them from Project Settings without touching
//      check code
//   3. CI pipelines can assert against known thresholds when analyzing SARIF output
//
// Convention: all constants are UPPER_SNAKE, grouped by check code prefix, typed explicitly.

#pragma once

#include "CoreMinimal.h"

namespace BPDoctorConstants
{
	// -------------------------------------------------------------------------
	// Blueprint (general) thresholds
	// -------------------------------------------------------------------------

	/** BP_COMPLEXITY: a Blueprint with more than this many total graph nodes is flagged. */
	constexpr int32 BP_COMPLEXITY_NODE_THRESHOLD = 100;

	/** BP_EMPTY_GRAPH: any Blueprint with fewer than this many nodes is treated as empty. */
	constexpr int32 BP_EMPTY_GRAPH_MIN_NODES = 3;

	/** BP_TICK_HEAVY: EventTick enabled AND more than this many total nodes. */
	constexpr int32 BP_TICK_HEAVY_NODE_THRESHOLD = 30;

	/** BP_HARD_REF: count of distinct Cast-to-Blueprint nodes that triggers the warning. */
	constexpr int32 BP_HARD_REF_THRESHOLD = 5;

	/** BP_TIMELINE_HEAVY: Timeline component count that flags perf concern.
	 *  Raised from 3 → 6 in v2.3: 3+ Timelines is routine for UI / doors / breathing FX.
	 *  6+ is where hidden-tick cost starts to matter (2026-04-23 product review). */
	constexpr int32 BP_TIMELINE_HEAVY_THRESHOLD = 6;

	/** BP_MASSIVE_ASSET: .uasset file size threshold in bytes (5 MB). */
	constexpr int64 BP_MASSIVE_ASSET_BYTES = 5LL * 1024LL * 1024LL;

	// -------------------------------------------------------------------------
	// AnimBlueprint thresholds
	// -------------------------------------------------------------------------

	/** BP_ORPHANED / ORPHANED_NODE: count of unreachable anim nodes that triggers the warning. */
	constexpr int32 ANIMBP_ORPHANED_NODE_THRESHOLD = 3;

	/** BROKEN_TRANSITION: state machine must have more than this many states for reachability check. */
	constexpr int32 ANIMBP_STATE_MACHINE_MIN_STATES = 2;

	/** ORPHANED_NODE: skip AnimBPs below this total-node count (too small to matter). */
	constexpr int32 ANIMBP_ORPHANED_GATE = 15;

	/** UNUSED_VAR: AnimBP has more than this many user properties... */
	constexpr int32 ANIMBP_UNUSED_VAR_MAX_PROPS = 12;
	/** ... AND fewer than this many VariableGet references -> warning. */
	constexpr int32 ANIMBP_UNUSED_VAR_MIN_GETS = 3;

	/** BLEND_WT_SUM: sum of layer weights must stay within [1 - EPS, 1 + EPS] or flag. */
	constexpr float ANIMBP_BLEND_WEIGHT_EPSILON = 0.05f;

	// -------------------------------------------------------------------------
	// Custom rule IDs
	// -------------------------------------------------------------------------

	/** Custom rules begin at this ID to stay clear of built-in checks 1-99. */
	constexpr int32 CUSTOM_RULE_ID_BASE = 100;
}
