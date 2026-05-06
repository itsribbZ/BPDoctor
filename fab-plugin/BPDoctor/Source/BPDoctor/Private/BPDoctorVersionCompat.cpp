// Copyright (C) 2025-2026 Jacob Ribbe. All rights reserved.

#include "BPDoctorVersionCompat.h"

#include "Animation/AnimBlueprint.h"
#include "Animation/AnimBlueprintGeneratedClass.h"

namespace BPDoctorCompat
{
	UAnimBlueprintGeneratedClass* GetCompiledAnimBPClass(UAnimBlueprint* AnimBP)
	{
		if (!AnimBP)
		{
			return nullptr;
		}

		UAnimBlueprintGeneratedClass* GenClass = AnimBP->GetAnimBlueprintGeneratedClass();
		if (!GenClass)
		{
			return nullptr;
		}

#if BP_DOCTOR_UE55_PLUS
		// 5.5+ can hand back the skeleton-generated class for AnimBPs modified since last compile.
		// Reject that case so callers don't iterate an empty property set.
		if (!GenClass->HasAnyClassFlags(CLASS_CompiledFromBlueprint))
		{
			return nullptr;
		}
#endif

		return GenClass;
	}
}
