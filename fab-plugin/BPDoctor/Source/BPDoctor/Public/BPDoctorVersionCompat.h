// Copyright (C) 2025-2026 Jacob Ribbe. All rights reserved.
//
// Cross-version compatibility shim for BP Doctor.
//
// Target floor: UE 5.3 (documented in BPDoctor.uplugin "EngineVersion": "5.3.0").
// Target ceiling: latest stable (5.7 as of 2026-04-23).
//
// Use UE_VERSION_OLDER_THAN / UE_VERSION_NEWER_THAN macros from Misc/EngineVersionComparison.h
// rather than raw ENGINE_MINOR_VERSION comparisons — the raw macros reset to 0 on UE5 major
// bumps and give wrong answers across 4.x -> 5.x boundaries.

#pragma once

#include "CoreMinimal.h"
#include "Misc/EngineVersionComparison.h"

// -----------------------------------------------------------------------------
// Named version flags (convenience — prefer these over raw UE_VERSION_* calls).
// -----------------------------------------------------------------------------

#if !UE_VERSION_OLDER_THAN(5, 5, 0)
	#define BP_DOCTOR_UE55_PLUS 1
#else
	#define BP_DOCTOR_UE55_PLUS 0
#endif

#if !UE_VERSION_OLDER_THAN(5, 4, 0)
	#define BP_DOCTOR_UE54_PLUS 1
#else
	#define BP_DOCTOR_UE54_PLUS 0
#endif

#if !UE_VERSION_OLDER_THAN(5, 3, 0)
	#define BP_DOCTOR_UE53_PLUS 1
#else
	#define BP_DOCTOR_UE53_PLUS 0
#endif

// -----------------------------------------------------------------------------
// GetCompiledAnimBPClass — wrapper around UAnimBlueprint::GetAnimBlueprintGeneratedClass.
//
// In 5.5+ the base call can return the SKELETON-generated class for AnimBPs modified since
// last compile. That class has ExcludeSuper return zero properties, which produces silent
// false negatives in variable-scanning checks. This wrapper returns nullptr in that case so
// the caller can skip the check cleanly.
//
// Behavior across versions:
//   5.3 / 5.4   -> returns the generated class directly (no skeleton-class drift)
//   5.5 / 5.6 / 5.7 -> returns the generated class ONLY if it has CLASS_CompiledFromBlueprint
// -----------------------------------------------------------------------------

class UAnimBlueprint;
class UAnimBlueprintGeneratedClass;

namespace BPDoctorCompat
{
	UAnimBlueprintGeneratedClass* GetCompiledAnimBPClass(UAnimBlueprint* AnimBP);
}
