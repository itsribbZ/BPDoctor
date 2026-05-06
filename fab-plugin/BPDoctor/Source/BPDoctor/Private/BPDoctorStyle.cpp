// Copyright (C) 2025-2026 Jacob Ribbe. All rights reserved.

#include "BPDoctorStyle.h"
#include "BPDoctorLog.h"
#include "Styling/SlateStyleRegistry.h"
#include "Framework/Application/SlateApplication.h"
#include "Interfaces/IPluginManager.h"

#define RootToContentDir Style->RootToContentDir

TSharedPtr<FSlateStyleSet> FBPDoctorStyle::StyleInstance = nullptr;

void FBPDoctorStyle::Initialize()
{
	if (StyleInstance.IsValid()) return;

	// Skip the whole Create+Register flow if the plugin folder is missing / renamed.
	// Otherwise Create() returns a content-rootless style and we'd register a
	// half-initialized one that breaks toolbar icons (2026-04-23 audit P3-HIGH-2).
	if (!IPluginManager::Get().FindPlugin(TEXT("BPDoctor")).IsValid())
	{
		UE_LOG(LogBPDoctor, Warning,
			TEXT("FBPDoctorStyle::Initialize: BPDoctor plugin not found in manager - skipping style registration."));
		return;
	}

	StyleInstance = Create();
	FSlateStyleRegistry::RegisterSlateStyle(*StyleInstance);
}

void FBPDoctorStyle::Shutdown()
{
	if (!StyleInstance.IsValid()) return;  // Initialize may have skipped.
	FSlateStyleRegistry::UnRegisterSlateStyle(*StyleInstance);
	ensure(StyleInstance.IsUnique());
	StyleInstance.Reset();
}

FName FBPDoctorStyle::GetStyleSetName()
{
	static FName StyleSetName(TEXT("BPDoctorStyle"));
	return StyleSetName;
}

void FBPDoctorStyle::ReloadTextures()
{
	if (FSlateApplication::IsInitialized())
	{
		FSlateApplication::Get().GetRenderer()->ReloadTextureResources();
	}
}

const ISlateStyle& FBPDoctorStyle::Get()
{
	return *StyleInstance;
}

TSharedRef<FSlateStyleSet> FBPDoctorStyle::Create()
{
	TSharedRef<FSlateStyleSet> Style = MakeShareable(new FSlateStyleSet("BPDoctorStyle"));

	// Guard against a renamed / non-standard plugin folder — FindPlugin returns null if the folder name isn't "BPDoctor".
	TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("BPDoctor"));
	if (!Plugin.IsValid())
	{
		UE_LOG(LogBPDoctor, Warning, TEXT("FBPDoctorStyle::Create: plugin not found in manager — icon resources unavailable."));
		return Style;
	}
	Style->SetContentRoot(Plugin->GetBaseDir() / TEXT("Resources"));

	Style->Set("BPDoctor.OpenBPDoctor", new FSlateImageBrush(
		RootToContentDir(TEXT("Icon128"), TEXT(".png")), FVector2D(40.0f, 40.0f)));

	Style->Set("BPDoctor.TabIcon", new FSlateImageBrush(
		RootToContentDir(TEXT("Icon128"), TEXT(".png")), FVector2D(16.0f, 16.0f)));

	return Style;
}

#undef RootToContentDir
