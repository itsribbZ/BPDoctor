// Copyright (C) 2025-2026 Jacob Ribbe. All rights reserved.

#pragma once

#include "CoreMinimal.h"
#include "Framework/Commands/Commands.h"
#include "BPDoctorStyle.h"

class FBPDoctorCommands : public TCommands<FBPDoctorCommands>
{
public:
	FBPDoctorCommands()
		: TCommands<FBPDoctorCommands>(
			TEXT("BPDoctor"),
			NSLOCTEXT("Contexts", "BPDoctor", "BP Doctor Plugin"),
			NAME_None,
			FBPDoctorStyle::GetStyleSetName())
	{}

	virtual void RegisterCommands() override;

	TSharedPtr<FUICommandInfo> OpenBPDoctor;
};
