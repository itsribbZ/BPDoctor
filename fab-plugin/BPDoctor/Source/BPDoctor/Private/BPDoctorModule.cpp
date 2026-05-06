// Copyright (C) 2025-2026 Jacob Ribbe. All rights reserved.

#include "BPDoctorModule.h"
#include "BPDoctorLog.h"
#include "BPDoctorStyle.h"
#include "BPDoctorCommands.h"
#include "SBPDoctorPanel.h"

#include "ToolMenus.h"
#include "Widgets/Docking/SDockTab.h"
#include "Styling/AppStyle.h"
#include "WorkspaceMenuStructure.h"
#include "WorkspaceMenuStructureModule.h"
#include "Interfaces/IPluginManager.h"
#include "HAL/PlatformProcess.h"
#include "Misc/Paths.h"
#include "Misc/MessageDialog.h"

static const FName BPDoctorTabName("BPDoctorTab");

#define LOCTEXT_NAMESPACE "FBPDoctorModule"

namespace BPDoctorDocs
{
	static void OpenUserGuide()
	{
		TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("BPDoctor"));
		if (!Plugin.IsValid())
		{
			UE_LOG(LogBPDoctor, Warning, TEXT("[BPDoctor] Help menu: plugin directory not found"));
			FMessageDialog::Open(EAppMsgType::Ok,
				LOCTEXT("DocsPluginMissing", "BP Doctor plugin directory not found."));
			return;
		}

		const FString BaseDir = Plugin->GetBaseDir();
		FString GuidePath = BaseDir / TEXT("Documentation/BP_Doctor_User_Guide.html");
		if (!FPaths::FileExists(GuidePath))
		{
			GuidePath = BaseDir / TEXT("Resources/BP_Doctor_User_Guide.html");
		}
		if (!FPaths::FileExists(GuidePath))
		{
			UE_LOG(LogBPDoctor, Warning, TEXT("[BPDoctor] Help menu: guide not found under %s"), *BaseDir);
			FMessageDialog::Open(EAppMsgType::Ok,
				FText::Format(LOCTEXT("DocsMissing", "User guide not found under:\n{0}"),
					FText::FromString(BaseDir)));
			return;
		}

		const FString FullPath = FPaths::ConvertRelativePathToFull(GuidePath);
		UE_LOG(LogBPDoctor, Log, TEXT("[BPDoctor] Opening user guide: %s"), *FullPath);

		// Use LaunchFileInDefaultExternalApplication — correct UE5 API for local files.
		FPlatformProcess::LaunchFileInDefaultExternalApplication(*FullPath, nullptr, ELaunchVerb::Open);
	}
}

void FBPDoctorModule::StartupModule()
{
	FBPDoctorStyle::Initialize();
	FBPDoctorStyle::ReloadTextures();
	FBPDoctorCommands::Register();

	// Register the tab spawner
	FGlobalTabmanager::Get()->RegisterNomadTabSpawner(
		BPDoctorTabName,
		FOnSpawnTab::CreateRaw(this, &FBPDoctorModule::OnSpawnPluginTab))
		.SetDisplayName(LOCTEXT("TabTitle", "BP Doctor"))
		.SetTooltipText(LOCTEXT("TabTooltip", "Scan and fix Blueprint issues"))
		.SetGroup(WorkspaceMenu::GetMenuStructure().GetToolsCategory())
		.SetIcon(FSlateIcon(FAppStyle::GetAppStyleSetName(), "ClassIcon.AnimBlueprint"));

	// Register menus after ToolMenus is ready
	UToolMenus::RegisterStartupCallback(
		FSimpleMulticastDelegate::FDelegate::CreateRaw(this, &FBPDoctorModule::RegisterMenus));
}

void FBPDoctorModule::ShutdownModule()
{
	UToolMenus::UnRegisterStartupCallback(this);
	UToolMenus::UnregisterOwner(this);
	FBPDoctorCommands::Unregister();
	FBPDoctorStyle::Shutdown();
	FGlobalTabmanager::Get()->UnregisterNomadTabSpawner(BPDoctorTabName);
}

void FBPDoctorModule::RegisterMenus()
{
	FToolMenuOwnerScoped OwnerScoped(this);

	// Add to Window menu
	UToolMenu* WindowMenu = UToolMenus::Get()->ExtendMenu("LevelEditor.MainMenu.Window");
	FToolMenuSection& Section = WindowMenu->FindOrAddSection("WindowLayout");
	Section.AddMenuEntry(
		"BPDoctor",
		LOCTEXT("MenuTitle", "BP Doctor"),
		LOCTEXT("MenuTooltip", "Open BP Doctor — scan and fix Blueprint issues"),
		FSlateIcon(FAppStyle::GetAppStyleSetName(), "ClassIcon.AnimBlueprint"),
		FUIAction(FExecuteAction::CreateLambda([]()
		{
			FGlobalTabmanager::Get()->TryInvokeTab(BPDoctorTabName);
		}))
	);

	// Add to Tools menu
	UToolMenu* ToolsMenu = UToolMenus::Get()->ExtendMenu("LevelEditor.MainMenu.Tools");
	FToolMenuSection& ToolsSection = ToolsMenu->FindOrAddSection("Animation");
	ToolsSection.AddMenuEntry(
		"BPDoctor",
		LOCTEXT("ToolsMenuTitle", "BP Doctor"),
		LOCTEXT("ToolsMenuTooltip", "Scan and auto-fix Blueprint issues"),
		FSlateIcon(FAppStyle::GetAppStyleSetName(), "ClassIcon.AnimBlueprint"),
		FUIAction(FExecuteAction::CreateLambda([]()
		{
			FGlobalTabmanager::Get()->TryInvokeTab(BPDoctorTabName);
		}))
	);

	// Add to Help menu — BP Doctor Documentation entry (Fab TRC: in-editor documentation)
	if (UToolMenu* HelpMenu = UToolMenus::Get()->ExtendMenu("LevelEditor.MainMenu.Help"))
	{
		FToolMenuSection& HelpSection = HelpMenu->FindOrAddSection("BPDoctorHelp");
		HelpSection.AddMenuEntry(
			"BPDoctorDocs",
			LOCTEXT("HelpMenuTitle", "BP Doctor Documentation"),
			LOCTEXT("HelpMenuTooltip", "Open the BP Doctor user guide in your default browser"),
			FSlateIcon(FAppStyle::GetAppStyleSetName(), "Icons.Help"),
			FUIAction(FExecuteAction::CreateStatic(&BPDoctorDocs::OpenUserGuide))
		);
	}
}

TSharedRef<SDockTab> FBPDoctorModule::OnSpawnPluginTab(const FSpawnTabArgs& SpawnTabArgs)
{
	return SNew(SDockTab)
		.TabRole(ETabRole::NomadTab)
		[
			SNew(SBPDoctorPanel)
		];
}

#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FBPDoctorModule, BPDoctor)
