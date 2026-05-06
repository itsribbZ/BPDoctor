// Copyright (C) 2025-2026 Jacob Ribbe. All rights reserved.

using UnrealBuildTool;

public class BPDoctor : ModuleRules
{
	public BPDoctor(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = ModuleRules.PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core",
		});

		PrivateDependencyModuleNames.AddRange(new string[]
		{
			"CoreUObject",
			"Engine",
			"Slate",
			"SlateCore",
			"UnrealEd",
			"InputCore",          // SListView keyboard nav (EKeys::PageDown/End/Home/A) — DO NOT REMOVE
			                      // even though no direct #include resolves to it; SListView templates
			                      // instantiate EKeys::* references that link against InputCore.
			"ApplicationCore",    // HAL/PlatformApplicationMisc.h (used by SBPDoctorPanel.cpp).
			"ToolMenus",
			"Projects",
			"AnimGraph",
			"AnimGraphRuntime",
			"BlueprintGraph",
			"Kismet",             // Kismet2/BlueprintEditorUtils.h (FBlueprintEditorUtils) — added v2.7.3
			"KismetCompiler",     // Kismet2/KismetEditorUtilities.h (FKismetEditorUtilities) — added v2.7.3
			"EditorFramework",    // IAssetTypeActions adjacent — keeps editor module init clean.
			"AssetRegistry",
			"DesktopPlatform",
			"Json",
			"WorkspaceMenuStructure",
		});
	}
}
