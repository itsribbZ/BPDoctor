// Copyright (C) 2025-2026 Jacob Ribbe. All rights reserved.

#include "BPDoctorCommands.h"

#define LOCTEXT_NAMESPACE "FBPDoctorModule"

void FBPDoctorCommands::RegisterCommands()
{
	UI_COMMAND(OpenBPDoctor,
		"BP Doctor",
		"Open BP Doctor — Blueprint diagnostic & auto-fix tool",
		EUserInterfaceActionType::Button,
		FInputChord());
}

#undef LOCTEXT_NAMESPACE
