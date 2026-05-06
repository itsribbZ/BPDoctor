// Copyright (C) 2025-2026 Jacob Ribbe. All rights reserved.

#include "SBPDoctorPanel.h"
#include "BPDoctorLog.h"
#include "BPDoctorChecks.h"
#include "BPDoctorFixes.h"

#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SCheckBox.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/Layout/SSplitter.h"
#include "Widgets/Layout/SSeparator.h"
#include "Widgets/Text/STextBlock.h"
#include "Widgets/Views/SHeaderRow.h"
#include "Widgets/SBoxPanel.h"

#include "Styling/AppStyle.h"
#include "Styling/CoreStyle.h"
#include "Misc/FileHelper.h"
#include "DesktopPlatformModule.h"
#include "Framework/Application/SlateApplication.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "Engine/Blueprint.h"
#include "Editor.h"
#include "ScopedTransaction.h"
#include "Subsystems/AssetEditorSubsystem.h"
#include "Misc/MessageDialog.h"
#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Input/STextComboBox.h"
#include "Editor/TransBuffer.h"
#include "Kismet2/BlueprintEditorUtils.h"
#include "Kismet2/KismetEditorUtilities.h"
// Sprint 5 P0-1: NavigateToIssue now recurses AnimBP sub-graphs to land on SM-internal nodes.
#include "Animation/AnimBlueprint.h"
#include "AnimGraphNode_Base.h"
#include "UObject/LinkerLoad.h"
#include "HAL/PlatformApplicationMisc.h"
#include "Serialization/JsonSerializer.h"
#include "Misc/Paths.h"
#include "Interfaces/IPluginManager.h"
#include "HAL/PlatformProcess.h"

// Sprint 5 Phase D: notification toasts + right-click context menu support
#include "Framework/Notifications/NotificationManager.h"
#include "Widgets/Notifications/SNotificationList.h"
#include "Framework/MultiBox/MultiBoxBuilder.h"
#include "UObject/Package.h"

#define LOCTEXT_NAMESPACE "BPDoctor"

void SBPDoctorPanel::Construct(const FArguments& InArgs)
{
	Scanner = MakeShareable(new FBPDoctorScanner());
	Scanner->OnComplete.BindSP(this, &SBPDoctorPanel::OnScanComplete);

	ExperienceModeOptions.Add(MakeShareable(new FString(TEXT("Beginner"))));
	ExperienceModeOptions.Add(MakeShareable(new FString(TEXT("Intermediate"))));
	ExperienceModeOptions.Add(MakeShareable(new FString(TEXT("Expert"))));

	// Sprint 5 Phase D: dynamic profile labels with live tier counts.
	// Counts pulled from FBPDoctorChecks::GetAllChecks() so adding/removing checks
	// auto-updates the dropdown without re-touching strings. MakeProfileLabel calls
	// GetAllChecks() which has its own InitChecks() guard, safe before LoadSettings.
	ProfileOptions.Add(MakeShareable(new FString(MakeProfileLabel(EBPDoctorProfile::SilentFailuresOnly))));
	ProfileOptions.Add(MakeShareable(new FString(MakeProfileLabel(EBPDoctorProfile::Standard))));
	ProfileOptions.Add(MakeShareable(new FString(MakeProfileLabel(EBPDoctorProfile::Everything))));

	LoadSettings();

	ChildSlot
	[
		SNew(SVerticalBox)

		// ── Title Bar ──
		+ SVerticalBox::Slot()
		.AutoHeight()
		.Padding(8)
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot()
			.AutoWidth()
			[
				SNew(STextBlock)
				.Text(LOCTEXT("Title", "BP Doctor"))
				.Font(FCoreStyle::GetDefaultFontStyle("Bold", 18))
				.ColorAndOpacity(FLinearColor(0.f, 0.898f, 1.f))
			]
			+ SHorizontalBox::Slot()
			.AutoWidth()
			.Padding(12, 6, 0, 0)
			[
				SNew(STextBlock)
				.Text(LOCTEXT("Version", "v2.7.4 — Silent-Failure Scanner for AnimBP + Blueprint"))
				.Font(FCoreStyle::GetDefaultFontStyle("Regular", 10))
				.ColorAndOpacity(FLinearColor(0.533f, 0.533f, 0.667f))
			]
		]

		// ── Toolbar ──
		+ SVerticalBox::Slot()
		.AutoHeight()
		.Padding(8, 0, 8, 4)
		[
			SNew(SHorizontalBox)

			+ SHorizontalBox::Slot()
			.AutoWidth()
			.Padding(0, 0, 4, 0)
			[
				SNew(SButton)
				.Text(LOCTEXT("ScanProject", "Scan Project"))
				.ToolTipText(LOCTEXT("ScanTip", "Scan all Blueprints in /Game for issues"))
				.OnClicked(this, &SBPDoctorPanel::OnScanProject)
				.IsEnabled_Lambda([this]() { return !bScanRunning; })
			]

			+ SHorizontalBox::Slot()
			.AutoWidth()
			.Padding(0, 0, 4, 0)
			[
				SNew(SButton)
				.Text(LOCTEXT("FixAll", "Fix All"))
				.ToolTipText(LOCTEXT("FixAllTip", "Auto-fix all fixable issues"))
				.OnClicked(this, &SBPDoctorPanel::OnFixAll)
				.IsEnabled_Lambda([this]() { return TotalAutoFixable > 0; })
			]

			+ SHorizontalBox::Slot()
			.AutoWidth()
			.Padding(0, 0, 4, 0)
			[
				SNew(SButton)
				.Text(LOCTEXT("UndoFix", "Undo Fix"))
				.ToolTipText_Lambda([this]() -> FText {
					for (int32 i = FixHistory.Num() - 1; i >= 0; --i)
					{
						if (!FixHistory[i].bReverted)
						{
							return FText::FromString(FString::Printf(
								TEXT("Undo: %s in %s"), *FixHistory[i].CheckCode, *FixHistory[i].AssetName));
						}
					}
					return LOCTEXT("NoUndo", "No fixes to undo");
				})
				.OnClicked(this, &SBPDoctorPanel::OnUndoLastFix)
				.IsEnabled_Lambda([this]() {
					for (int32 i = FixHistory.Num() - 1; i >= 0; --i)
					{
						if (!FixHistory[i].bReverted) return true;
					}
					return false;
				})
			]

			+ SHorizontalBox::Slot()
			.AutoWidth()
			.Padding(0, 0, 4, 0)
			[
				SNew(SButton)
				.Text(LOCTEXT("Export", "Export Report"))
				.ToolTipText(LOCTEXT("ExportTip", "Export scan results to a text file"))
				.OnClicked(this, &SBPDoctorPanel::OnExportReport)
				.IsEnabled_Lambda([this]() { return FilteredIssues.Num() > 0; })
			]

			+ SHorizontalBox::Slot()
			.AutoWidth()
			.Padding(0, 0, 4, 0)
			[
				SNew(SButton)
				.Text(LOCTEXT("ExportHTML", "HTML"))
				.ToolTipText(LOCTEXT("ExportHTMLTip", "Export styled HTML report"))
				.OnClicked(this, &SBPDoctorPanel::OnExportHTMLReport)
				.IsEnabled_Lambda([this]() { return FilteredIssues.Num() > 0; })
			]

			+ SHorizontalBox::Slot()
			.AutoWidth()
			.Padding(0, 0, 4, 0)
			[
				SNew(SButton)
				.Text(LOCTEXT("Checks", "Checks"))
				.ToolTipText(LOCTEXT("ChecksTip", "View all checks — enable/disable individual checks"))
				.OnClicked_Lambda([this]() { ShowChecksDialog(); return FReply::Handled(); })
			]

			+ SHorizontalBox::Slot()
			.AutoWidth()
			.Padding(0, 0, 4, 0)
			[
				SNew(SButton)
				.Text(LOCTEXT("Settings", "Settings"))
				.ToolTipText(LOCTEXT("SettingsTip", "Configure BP Doctor preferences"))
				.OnClicked_Lambda([this]() { ShowSettingsDialog(); return FReply::Handled(); })
			]

			+ SHorizontalBox::Slot()
			.AutoWidth()
			.Padding(0, 0, 4, 0)
			[
				SNew(SButton)
				.Text(LOCTEXT("Help", "Help"))
				.ToolTipText(LOCTEXT("HelpTip", "Open the BP Doctor User Guide (bundled HTML)"))
				.OnClicked(this, &SBPDoctorPanel::OnOpenUserGuide)
			]

			+ SHorizontalBox::Slot()
			.AutoWidth()
			[
				SNew(SButton)
				.Text(LOCTEXT("Clear", "Clear"))
				.OnClicked(this, &SBPDoctorPanel::OnClear)
			]

			+ SHorizontalBox::Slot()
			.FillWidth(1.0f)
			[
				SNew(SSpacer)
			]

			// Search filter
			+ SHorizontalBox::Slot()
			.AutoWidth()
			.VAlign(VAlign_Center)
			.Padding(4, 0)
			[
				SNew(SBox)
				.WidthOverride(180)
				[
					SNew(SEditableTextBox)
					.HintText(LOCTEXT("SearchHint", "Filter checks/assets..."))
					.OnTextChanged_Lambda([this](const FText& NewText)
					{
						SearchFilter = NewText.ToString();
						RefreshFilteredList();
					})
				]
			]

			// Scan profile — which checks run. Default: Silent Failures Only.
			+ SHorizontalBox::Slot()
			.AutoWidth()
			.VAlign(VAlign_Center)
			.Padding(4, 0)
			[
				SNew(SBox)
				.WidthOverride(170)
				[
					SNew(STextComboBox)
					.OptionsSource(&ProfileOptions)
					// Clamp index — guards against a Settings.json from a future build that
					// persists an unrecognized profile enum value. Hard crash > silent default.
					.InitiallySelectedItem(ProfileOptions[FMath::Clamp(
						static_cast<int32>(ActiveProfile), 0, ProfileOptions.Num() - 1)])
					.ToolTipText(LOCTEXT("ProfileTip",
						"Profiles control which checks run. New users: start with Silent Failures Only.\n\n"
						"Silent Failures Only — silent T-pose bugs that ship to prod (default)\n"
						"Standard — silent failures + contextual smells (perf / architecture)\n"
						"Everything — all checks including stylistic heuristics"))
					.OnSelectionChanged_Lambda([this](TSharedPtr<FString> NewValue, ESelectInfo::Type)
					{
						// Sprint 5 Phase D: labels now include count suffix like "Standard (22)" — match by
						// distinguishing prefix substring instead of exact text. Order matters: "Everything"
						// is checked before "Standard" because "Standard" is a substring of nothing else but
						// the Everything case must win when both appear (it doesn't, but defensive).
						if (!NewValue.IsValid()) return;
						if (NewValue->StartsWith(TEXT("Everything")))    ActiveProfile = EBPDoctorProfile::Everything;
						else if (NewValue->StartsWith(TEXT("Standard"))) ActiveProfile = EBPDoctorProfile::Standard;
						else                                             ActiveProfile = EBPDoctorProfile::SilentFailuresOnly;
						FBPDoctorChecks::SetActiveProfile(ActiveProfile);
						SaveSettings();
					})
				]
			]

			// Experience mode
			+ SHorizontalBox::Slot()
			.AutoWidth()
			.VAlign(VAlign_Center)
			.Padding(4, 0)
			[
				SNew(SBox)
				.WidthOverride(130)
				[
					SNew(STextComboBox)
					.OptionsSource(&ExperienceModeOptions)
					// Pre-existing bug fix (v2.3 audit): was hardcoded to [1] (Intermediate) and
					// stomped the saved ExperienceMode when the dropdown reported its "initial" value.
					.InitiallySelectedItem(ExperienceModeOptions[FMath::Clamp(
						static_cast<int32>(ExperienceMode), 0, ExperienceModeOptions.Num() - 1)])
					.OnSelectionChanged_Lambda([this](TSharedPtr<FString> NewValue, ESelectInfo::Type)
					{
						if (NewValue.IsValid())
						{
							if (*NewValue == TEXT("Beginner")) ExperienceMode = EBPDoctorExperienceMode::Beginner;
							else if (*NewValue == TEXT("Expert")) ExperienceMode = EBPDoctorExperienceMode::Expert;
							else ExperienceMode = EBPDoctorExperienceMode::Intermediate;
							SaveSettings();
							if (SelectedIssue.IsValid())
								OnSelectionChanged(SelectedIssue, ESelectInfo::Direct);
						}
					})
				]
			]

			// Severity filters
			+ SHorizontalBox::Slot()
			.AutoWidth()
			.VAlign(VAlign_Center)
			.Padding(4, 0)
			[
				SNew(SCheckBox)
				.IsChecked_Lambda([this]() { return bShowErrors ? ECheckBoxState::Checked : ECheckBoxState::Unchecked; })
				.OnCheckStateChanged_Lambda([this](ECheckBoxState State)
				{
					bShowErrors = (State == ECheckBoxState::Checked);
					RefreshFilteredList();
				})
				[
					SNew(STextBlock)
					.Text(LOCTEXT("Errors", "Errors"))
					.Font(FCoreStyle::GetDefaultFontStyle("Bold", 10))
					.ColorAndOpacity(FLinearColor(1.0f, 0.09f, 0.27f))
				]
			]

			+ SHorizontalBox::Slot()
			.AutoWidth()
			.VAlign(VAlign_Center)
			.Padding(4, 0)
			[
				SNew(SCheckBox)
				.IsChecked_Lambda([this]() { return bShowWarnings ? ECheckBoxState::Checked : ECheckBoxState::Unchecked; })
				.OnCheckStateChanged_Lambda([this](ECheckBoxState State)
				{
					bShowWarnings = (State == ECheckBoxState::Checked);
					RefreshFilteredList();
				})
				[
					SNew(STextBlock)
					.Text(LOCTEXT("Warnings", "Warnings"))
					.Font(FCoreStyle::GetDefaultFontStyle("Bold", 10))
					.ColorAndOpacity(FLinearColor(1.0f, 0.843f, 0.251f))
				]
			]

			+ SHorizontalBox::Slot()
			.AutoWidth()
			.VAlign(VAlign_Center)
			.Padding(4, 0)
			[
				SNew(SCheckBox)
				.IsChecked_Lambda([this]() { return bShowInfo ? ECheckBoxState::Checked : ECheckBoxState::Unchecked; })
				.OnCheckStateChanged_Lambda([this](ECheckBoxState State)
				{
					bShowInfo = (State == ECheckBoxState::Checked);
					RefreshFilteredList();
				})
				[
					SNew(STextBlock)
					.Text(LOCTEXT("Info", "Info"))
					.Font(FCoreStyle::GetDefaultFontStyle("Bold", 10))
					.ColorAndOpacity(FLinearColor(0.f, 0.898f, 1.f))
				]
			]

			+ SHorizontalBox::Slot()
			.AutoWidth()
			.VAlign(VAlign_Center)
			.Padding(8, 0, 0, 0)
			[
				SNew(SCheckBox)
				.IsChecked_Lambda([this]() { return bShowSuppressed ? ECheckBoxState::Checked : ECheckBoxState::Unchecked; })
				.OnCheckStateChanged_Lambda([this](ECheckBoxState State)
				{
					bShowSuppressed = (State == ECheckBoxState::Checked);
					RefreshFilteredList();
				})
				[
					SNew(STextBlock)
					.Text_Lambda([this]() -> FText {
						if (SuppressedIssueKeys.Num() > 0)
							return FText::FromString(FString::Printf(TEXT("Suppressed (%d)"), SuppressedIssueKeys.Num()));
						return LOCTEXT("Suppressed", "Suppressed");
					})
					.Font(FCoreStyle::GetDefaultFontStyle("Regular", 9))
					.ColorAndOpacity(FLinearColor(0.533f, 0.533f, 0.667f))
				]
			]
		]

		// ── Stats Bar ──
		+ SVerticalBox::Slot()
		.AutoHeight()
		.Padding(8, 4)
		[
			SNew(SBorder)
			.BorderImage(FAppStyle::GetBrush("ToolPanel.DarkGroupBorder"))
			.Padding(8)
			[
				SNew(SHorizontalBox)

				// Health Grade
				+ SHorizontalBox::Slot()
				.AutoWidth()
				.Padding(0, 0, 20, 0)
				[
					SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight()
					[
						SNew(STextBlock)
						.Text(LOCTEXT("GradeLabel", "HEALTH"))
						.Font(FCoreStyle::GetDefaultFontStyle("Regular", 9))
						.ColorAndOpacity(FLinearColor(0.533f, 0.533f, 0.667f))
						.ToolTipText(LOCTEXT("HealthGradeTip",
							"Overall project health, graded from the scan results.\n\n"
							"A+ — 0 issues of any kind (perfectly clean)\n"
							"A — 0 errors, 0 warnings (info-only)\n"
							"B+ — 0 errors, 1-3 warnings\n"
							"B — 0 errors, 4+ warnings\n"
							"C — 1-2 errors\n"
							"D — 3-5 errors\n"
							"F — 6+ errors (silent failures shipping to prod)\n\n"
							"Errors are silent-failure bugs (T-pose, broken refs, etc.) that need fixing.\n"
							"Warnings are perf / architecture smells — context matters."))
					]
					+ SVerticalBox::Slot().AutoHeight()
					[
						SNew(STextBlock)
						.Text(this, &SBPDoctorPanel::GetHealthGradeText)
						.Font(FCoreStyle::GetDefaultFontStyle("Bold", 28))
						.ColorAndOpacity(this, &SBPDoctorPanel::GetHealthGradeColor)
						.ToolTipText(LOCTEXT("HealthGradeTip",
							"Overall project health, graded from the scan results.\n\n"
							"A+ — 0 issues of any kind (perfectly clean)\n"
							"A — 0 errors, 0 warnings (info-only)\n"
							"B+ — 0 errors, 1-3 warnings\n"
							"B — 0 errors, 4+ warnings\n"
							"C — 1-2 errors\n"
							"D — 3-5 errors\n"
							"F — 6+ errors (silent failures shipping to prod)\n\n"
							"Errors are silent-failure bugs (T-pose, broken refs, etc.) that need fixing.\n"
							"Warnings are perf / architecture smells — context matters."))
					]
				]

				// Stats text
				+ SHorizontalBox::Slot()
				.FillWidth(1.f)
				.VAlign(VAlign_Center)
				[
					SNew(STextBlock)
					.Text(this, &SBPDoctorPanel::GetStatsText)
					.Font(FCoreStyle::GetDefaultFontStyle("Regular", 11))
				]
			]
		]

		// ── Progress Bar ──
		+ SVerticalBox::Slot()
		.AutoHeight()
		.Padding(8, 0, 8, 4)
		[
			SNew(SProgressBar)
			.Percent(this, &SBPDoctorPanel::GetProgressPercent)
			.FillColorAndOpacity(FLinearColor(0.f, 0.898f, 1.f))
		]

		// ── Main Content: Results List + Detail Panel ──
		+ SVerticalBox::Slot()
		.FillHeight(1.0f)
		.Padding(8)
		[
			SNew(SSplitter)
			.Orientation(Orient_Horizontal)

			// Left: Results list with column headers
			+ SSplitter::Slot()
			.Value(0.6f)
			[
				SNew(SBorder)
				.BorderImage(FAppStyle::GetBrush("ToolPanel.GroupBorder"))
				[
					SAssignNew(IssueListView, SListView<TSharedPtr<FBPDoctorResult>>)
					.ListItemsSource(&FilteredIssues)
					.OnGenerateRow(this, &SBPDoctorPanel::OnGenerateRow)
					.OnSelectionChanged(this, &SBPDoctorPanel::OnSelectionChanged)
					.OnMouseButtonDoubleClick(this, &SBPDoctorPanel::OnRowDoubleClicked)
					.OnContextMenuOpening(this, &SBPDoctorPanel::OnRowContextMenuOpening)
					.SelectionMode(ESelectionMode::Single)
					.HeaderRow(
						SNew(SHeaderRow)
						+ SHeaderRow::Column("Severity")
							.DefaultLabel(LOCTEXT("ColSev", "Sev"))
							.FixedWidth(50)
							.SortMode_Lambda([this]() { return GetSortModeForColumn(FName("Severity")); })
							.OnSort(this, &SBPDoctorPanel::OnSortChanged)
						+ SHeaderRow::Column("Confidence")
							.DefaultLabel(LOCTEXT("ColConf", "Conf"))
							.FixedWidth(45)
							.SortMode_Lambda([this]() { return GetSortModeForColumn(FName("Confidence")); })
							.OnSort(this, &SBPDoctorPanel::OnSortChanged)
						+ SHeaderRow::Column("Code")
							.DefaultLabel(LOCTEXT("ColCode", "Check"))
							.FixedWidth(120)
							.SortMode_Lambda([this]() { return GetSortModeForColumn(FName("Code")); })
							.OnSort(this, &SBPDoctorPanel::OnSortChanged)
						+ SHeaderRow::Column("Type")
							.DefaultLabel(LOCTEXT("ColType", "Type"))
							.FixedWidth(45)
							.SortMode_Lambda([this]() { return GetSortModeForColumn(FName("Type")); })
							.OnSort(this, &SBPDoctorPanel::OnSortChanged)
						+ SHeaderRow::Column("Asset")
							.DefaultLabel(LOCTEXT("ColAsset", "Asset"))
							.FillWidth(0.3f)
							.SortMode_Lambda([this]() { return GetSortModeForColumn(FName("Asset")); })
							.OnSort(this, &SBPDoctorPanel::OnSortChanged)
						+ SHeaderRow::Column("Description")
							.DefaultLabel(LOCTEXT("ColDesc", "Description"))
							.FillWidth(0.5f)
							.SortMode_Lambda([this]() { return GetSortModeForColumn(FName("Description")); })
							.OnSort(this, &SBPDoctorPanel::OnSortChanged)
						+ SHeaderRow::Column("AutoFix")
							.DefaultLabel(LOCTEXT("ColFix", "Fix"))
							.FixedWidth(50)
							.SortMode_Lambda([this]() { return GetSortModeForColumn(FName("AutoFix")); })
							.OnSort(this, &SBPDoctorPanel::OnSortChanged)
					)
				]
			]

			// Right: Detail panel
			+ SSplitter::Slot()
			.Value(0.4f)
			[
				SNew(SBorder)
				.BorderImage(FAppStyle::GetBrush("ToolPanel.GroupBorder"))
				.Padding(10.0f)
				[
					SNew(SScrollBox)
					+ SScrollBox::Slot()
					[
						SNew(SVerticalBox)

						+ SVerticalBox::Slot()
						.AutoHeight()
						[
							SAssignNew(DetailText, STextBlock)
							.AutoWrapText(true)
							.Font(FCoreStyle::GetDefaultFontStyle("Regular", 11))
							.Text(LOCTEXT("SelectIssue", "Welcome to BP Doctor\n\nClick 'Scan Project' to find silent animation bugs that ship to prod — the ones UE's compiler won't tell you about.\n\nWHAT YOU GET (default scan, 20 checks):\n  Character T-poses silently (MotionMatching with no Database)\n  T-pose between every montage (Slot Source pin disconnected)\n  State machine freezes on entry (empty or broken Entry)\n  Retarget fails on wrong-skeleton references\n  Cached Pose mismatch (Save without Use, or vice versa)\n\nHOW TO USE:\n  1. Click Scan Project — the list fills with issues\n  2. Click any row — the detail panel on the right shows what's wrong and how to fix it\n  3. Click Navigate — jumps to the exact node in the editor\n  4. Click Fix This Issue — 7 checks auto-fix with preview + undo (Ctrl+Z works)\n  5. Right-click a row > Suppress — hides known issues you don't want to see again\n\nNEED MORE CHECKS? Change the Profile dropdown to Standard (adds perf + architecture) or Everything (adds stylistic heuristics — power-user audit mode).\n\nNEED LESS GUIDANCE? Change the Experience Mode dropdown to Intermediate or Expert for more compact output.\n\nAdvanced features (Export SARIF, Custom Rules, CI/CD commandlet) are documented in Documentation/BP_Doctor_User_Guide.html."))
						]

						+ SVerticalBox::Slot()
						.AutoHeight()
						.Padding(0, 16, 0, 0)
						[
							SAssignNew(FixButtonsRow, SHorizontalBox)
							.Visibility(EVisibility::Collapsed)
							+ SHorizontalBox::Slot()
							.AutoWidth()
							.Padding(0, 0, 4, 0)
							[
								SAssignNew(FixButton, SButton)
								.Text(LOCTEXT("FixThis", "Fix This Issue"))
								.ToolTipText(LOCTEXT("FixThisTip", "Preview and apply fix — shows what will change before applying"))
								.IsEnabled(false)
								.OnClicked(this, &SBPDoctorPanel::OnFixSelected)
							]
							+ SHorizontalBox::Slot()
							.AutoWidth()
							.Padding(0, 0, 8, 0)
							[
								SAssignNew(RevertButton, SButton)
								.Text(LOCTEXT("Revert", "Revert"))
								.ToolTipText(LOCTEXT("RevertTip", "Revert this fix — reload Blueprint from disk"))
								.IsEnabled(false)
								.OnClicked(this, &SBPDoctorPanel::OnRevertSelected)
							]
							+ SHorizontalBox::Slot()
							.AutoWidth()
							[
								SAssignNew(OpenEditorButton, SButton)
								.Text(LOCTEXT("Navigate", "Navigate"))
								.ToolTipText(LOCTEXT("NavigateTip", "Open Blueprint editor and zoom to the problematic node"))
								.IsEnabled(false)
								.OnClicked_Lambda([this]() {
									if (SelectedIssue.IsValid())
										NavigateToIssue(*SelectedIssue);
									return FReply::Handled();
								})
							]
							+ SHorizontalBox::Slot()
							.AutoWidth()
							.Padding(8, 0, 4, 0)
							[
								SAssignNew(CopyButton, SButton)
								.Text(LOCTEXT("Copy", "Copy"))
								.ToolTipText(LOCTEXT("CopyTip", "Copy issue details to clipboard"))
								.IsEnabled(false)
								.OnClicked(this, &SBPDoctorPanel::OnCopyDetails)
							]
							+ SHorizontalBox::Slot()
							.AutoWidth()
							[
								SAssignNew(SuppressButton, SButton)
								.Text_Lambda([this]() -> FText {
									if (SelectedIssue.IsValid() && SuppressedIssueKeys.Contains(
										SelectedIssue->CheckCode + TEXT("|") + SelectedIssue->AssetPath))
										return LOCTEXT("Unsuppress", "Unsuppress");
									return LOCTEXT("Suppress", "Suppress");
								})
								.ToolTipText_Lambda([this]() -> FText {
									if (SelectedIssue.IsValid() && SuppressedIssueKeys.Contains(
										SelectedIssue->CheckCode + TEXT("|") + SelectedIssue->AssetPath))
										return LOCTEXT("UnsuppressTip", "Restore this issue to normal results");
									return LOCTEXT("SuppressTip2", "Hide this issue — use Suppressed filter to view later");
								})
								.IsEnabled(false)
								.OnClicked(this, &SBPDoctorPanel::OnSuppressSelected)
							]
						]
					]
				]
			]
		]
	];
}

// ─────────────────────────────────────────────────────────────────
//  ACTIONS
// ─────────────────────────────────────────────────────────────────

FReply SBPDoctorPanel::OnScanProject()
{
	bScanRunning = true;
	CurrentProgress = 0.f;
	AllResults.Empty();
	FilteredIssues.Empty();
	SelectedIssue.Reset();

	Scanner->OnProgress.BindLambda([Weak = TWeakPtr<SBPDoctorPanel>(SharedThis(this))](int32 Current, int32 Total)
	{
		if (TSharedPtr<SBPDoctorPanel> Pin = Weak.Pin())
		{
			Pin->CurrentProgress = (Total > 0) ? static_cast<float>(Current) / static_cast<float>(Total) : 0.f;
		}
	});

	FBPDoctorChecks::SetDisabledChecks(DisabledChecks);
	Scanner->ScanProject();

	return FReply::Handled();
}

FReply SBPDoctorPanel::OnClear()
{
	AllResults.Empty();
	FilteredIssues.Empty();
	SelectedIssue.Reset();
	if (FixButton.IsValid()) FixButton->SetEnabled(false);
	if (RevertButton.IsValid()) RevertButton->SetEnabled(false);
	if (OpenEditorButton.IsValid()) OpenEditorButton->SetEnabled(false);
	if (CopyButton.IsValid()) CopyButton->SetEnabled(false);
	if (SuppressButton.IsValid()) SuppressButton->SetEnabled(false);
	if (FixButtonsRow.IsValid()) FixButtonsRow->SetVisibility(EVisibility::Collapsed);
	SuppressedIssueKeys.Empty();
	TotalScanned = 0;
	TotalErrors = 0;
	TotalWarnings = 0;
	TotalInfos = 0;
	TotalAutoFixable = 0;
	HealthGrade = TEXT("-");
	CurrentProgress = 0.f;
	if (IssueListView.IsValid()) IssueListView->RequestListRefresh();
	DetailText->SetText(LOCTEXT("Cleared", "Results cleared. Click Scan Project to begin."));
	return FReply::Handled();
}

FReply SBPDoctorPanel::OnFixSelected()
{
	if (!SelectedIssue.IsValid() || SelectedIssue->bFixed)
		return FReply::Handled();

	ShowFixConfirmDialog(SelectedIssue);
	return FReply::Handled();
}

FReply SBPDoctorPanel::OnFixAll()
{
	ShowFixAllDialog();
	return FReply::Handled();
}

FReply SBPDoctorPanel::OnExportReport()
{
	FString Report;
	Report += TEXT("BP Doctor Scan Report\n");
	Report += FString::Printf(TEXT("Generated: %s\n"), *FDateTime::Now().ToString());
	Report += TEXT("=============================================\n\n");

	Report += FString::Printf(TEXT("Scanned: %d assets | Health: %s\n"),
		TotalScanned, *HealthGrade);
	Report += FString::Printf(TEXT("Errors: %d | Warnings: %d | Info: %d\n\n"),
		TotalErrors, TotalWarnings, TotalInfos);

	for (const FBPDoctorAssetInfo& Info : AllResults)
	{
		if (Info.Issues.Num() == 0) continue;

		Report += FString::Printf(TEXT("--- %s [%s] ---\n"), *Info.Name, *Info.Grade);
		for (const FBPDoctorResult& Issue : Info.Issues)
		{
			FString SevStr = (Issue.Severity == EBPDoctorSeverity::Error) ? TEXT("ERROR") :
				(Issue.Severity == EBPDoctorSeverity::Warning) ? TEXT("WARN") : TEXT("INFO");
			FString FixStr = Issue.bFixed ? TEXT(" [FIXED]") : (Issue.bAutoFixable ? TEXT(" [fixable]") : TEXT(""));
			Report += FString::Printf(TEXT("  [%s] %s: %s%s\n"),
				*SevStr, *Issue.CheckCode, *Issue.Description, *FixStr);
			if (!Issue.NodeHint.IsEmpty())
			{
				Report += FString::Printf(TEXT("         > %s\n"), *Issue.NodeHint);
			}
		}
		Report += TEXT("\n");
	}

	TArray<FString> OutFiles;
	IDesktopPlatform* DesktopPlatform = FDesktopPlatformModule::Get();
	if (DesktopPlatform)
	{
		DesktopPlatform->SaveFileDialog(
			FSlateApplication::Get().FindBestParentWindowHandleForDialogs(nullptr),
			TEXT("Export BP Doctor Report"),
			FPaths::ProjectDir(),
			TEXT("BPDoctor_Report.txt"),
			TEXT("Text Files (*.txt)|*.txt"),
			0, OutFiles);

		if (OutFiles.Num() > 0)
		{
			FFileHelper::SaveStringToFile(Report, *OutFiles[0]);
		}
	}

	return FReply::Handled();
}

// ─────────────────────────────────────────────────────────────────
//  IN-EDITOR DOCUMENTATION (opens bundled HTML user guide)
// ─────────────────────────────────────────────────────────────────

FReply SBPDoctorPanel::OnOpenUserGuide()
{
	TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("BPDoctor"));
	if (!Plugin.IsValid())
	{
		UE_LOG(LogBPDoctor, Warning, TEXT("[BPDoctor] Help: plugin directory not found"));
		FMessageDialog::Open(EAppMsgType::Ok,
			LOCTEXT("HelpPluginMissing", "BP Doctor plugin directory not found."));
		return FReply::Handled();
	}

	const FString BaseDir = Plugin->GetBaseDir();
	// Prefer Documentation/ (Fab TRC convention), fall back to Resources/ for older installs.
	FString GuidePath = BaseDir / TEXT("Documentation/BP_Doctor_User_Guide.html");
	if (!FPaths::FileExists(GuidePath))
	{
		GuidePath = BaseDir / TEXT("Resources/BP_Doctor_User_Guide.html");
	}
	if (!FPaths::FileExists(GuidePath))
	{
		UE_LOG(LogBPDoctor, Warning, TEXT("[BPDoctor] Help: guide not found under %s"), *BaseDir);
		FMessageDialog::Open(EAppMsgType::Ok,
			FText::Format(LOCTEXT("HelpFileMissing", "User guide not found under:\n{0}"),
				FText::FromString(BaseDir)));
		return FReply::Handled();
	}

	const FString FullPath = FPaths::ConvertRelativePathToFull(GuidePath);
	UE_LOG(LogBPDoctor, Log, TEXT("[BPDoctor] Opening user guide: %s"), *FullPath);

	// Use LaunchFileInDefaultExternalApplication — the correct UE5 API for opening
	// a local file in its default associated program (browser for .html).
	FPlatformProcess::LaunchFileInDefaultExternalApplication(*FullPath, nullptr, ELaunchVerb::Open);
	return FReply::Handled();
}

// ─────────────────────────────────────────────────────────────────
//  SCANNER CALLBACK
// ─────────────────────────────────────────────────────────────────

void SBPDoctorPanel::OnScanComplete(const TArray<FBPDoctorAssetInfo>& Results)
{
	AllResults = Results;
	bScanRunning = false;
	CurrentProgress = 1.f;
	UpdateStats();
	RefreshFilteredList();
	// Only show fix buttons if there are actual issues
	if (FixButtonsRow.IsValid())
	{
		bool bHasIssues = FilteredIssues.Num() > 0;
		FixButtonsRow->SetVisibility(bHasIssues ? EVisibility::Visible : EVisibility::Collapsed);
	}
}

// ─────────────────────────────────────────────────────────────────
//  LIST VIEW
// ─────────────────────────────────────────────────────────────────

TSharedRef<ITableRow> SBPDoctorPanel::OnGenerateRow(TSharedPtr<FBPDoctorResult> Item,
	const TSharedRef<STableViewBase>& OwnerTable)
{
	// Severity
	FLinearColor SevColor;
	FString SevText;
	switch (Item->Severity)
	{
		case EBPDoctorSeverity::Error:
			SevColor = FLinearColor(1.f, 0.09f, 0.27f);
			SevText = TEXT("ERR");
			break;
		case EBPDoctorSeverity::Warning:
			SevColor = FLinearColor(1.f, 0.843f, 0.251f);
			SevText = TEXT("WRN");
			break;
		default:
			SevColor = FLinearColor(0.f, 0.898f, 1.f);
			SevText = TEXT("INF");
			break;
	}

	// Confidence from check definition
	const FBPDoctorCheckDef* CheckDef = FBPDoctorChecks::FindCheck(Item->CheckCode);
	FString ConfText = TEXT("MED");
	FLinearColor ConfColor(1.f, 0.843f, 0.251f);
	if (CheckDef)
	{
		switch (CheckDef->Confidence)
		{
			case EBPDoctorConfidence::High:
				ConfText = TEXT("HI");
				ConfColor = FLinearColor(0.f, 0.902f, 0.463f);
				break;
			case EBPDoctorConfidence::Medium:
				ConfText = TEXT("MED");
				ConfColor = FLinearColor(1.f, 0.843f, 0.251f);
				break;
			case EBPDoctorConfidence::Low:
				ConfText = TEXT("LO");
				ConfColor = FLinearColor(1.f, 0.549f, 0.f);
				break;
		}
	}

	// Type badge
	FString TypeText = (Item->AssetType == EBPDoctorAssetType::AnimBP) ? TEXT("Anim") : TEXT("BP");
	FLinearColor TypeColor = (Item->AssetType == EBPDoctorAssetType::AnimBP)
		? FLinearColor(0.f, 0.898f, 1.f) : FLinearColor(0.533f, 0.745f, 0.533f);

	// Fix indicator
	FString FixText = Item->bFixed ? TEXT("DONE") : (Item->bAutoFixable ? TEXT("YES") : TEXT("-"));
	FLinearColor FixColor = Item->bFixed ? FLinearColor(0.f, 0.902f, 0.463f)
		: (Item->bAutoFixable ? FLinearColor(1.f, 0.843f, 0.251f)
		: FLinearColor(0.533f, 0.533f, 0.667f));

	// Severity-tinted row background
	FLinearColor RowBg;
	if (Item->bFixed)
	{
		RowBg = FLinearColor(0.02f, 0.07f, 0.03f, 1.f);
	}
	else
	{
		switch (Item->Severity)
		{
			case EBPDoctorSeverity::Error:   RowBg = FLinearColor(0.12f, 0.015f, 0.03f, 1.f); break;
			case EBPDoctorSeverity::Warning: RowBg = FLinearColor(0.09f, 0.07f, 0.01f, 1.f); break;
			default:                          RowBg = FLinearColor(0.02f, 0.04f, 0.07f, 1.f); break;
		}
	}

	return SNew(STableRow<TSharedPtr<FBPDoctorResult>>, OwnerTable)
		[
			SNew(SBorder)
			.BorderImage(FAppStyle::GetBrush("NoBorder"))
			.BorderBackgroundColor(RowBg)
			.Padding(FMargin(0, 1))
			[
				SNew(SHorizontalBox)

			+ SHorizontalBox::Slot().AutoWidth().Padding(4, 2)
			[
				SNew(SBox).WidthOverride(50)
				[ SNew(STextBlock).Text(FText::FromString(SevText))
					.Font(FCoreStyle::GetDefaultFontStyle("Bold", 9)).ColorAndOpacity(SevColor) ]
			]

			+ SHorizontalBox::Slot().AutoWidth().Padding(2, 2)
			[
				SNew(SBox).WidthOverride(45)
				.ToolTipText(FText::FromString(CheckDef && !CheckDef->DetectionMethod.IsEmpty() ? CheckDef->DetectionMethod : TEXT("Hover for detection method")))
				[ SNew(STextBlock).Text(FText::FromString(ConfText))
					.Font(FCoreStyle::GetDefaultFontStyle("Bold", 8)).ColorAndOpacity(ConfColor) ]
			]

			+ SHorizontalBox::Slot().AutoWidth().Padding(4, 2)
			[
				SNew(SBox).WidthOverride(120)
				[ SNew(STextBlock).Text(FText::FromString(Item->CheckCode))
					.Font(FCoreStyle::GetDefaultFontStyle("Regular", 9)).ColorAndOpacity(SevColor) ]
			]

			+ SHorizontalBox::Slot().AutoWidth().Padding(2, 2)
			[
				SNew(SBox).WidthOverride(45)
				[ SNew(STextBlock).Text(FText::FromString(TypeText))
					.Font(FCoreStyle::GetDefaultFontStyle("Bold", 8)).ColorAndOpacity(TypeColor) ]
			]

			+ SHorizontalBox::Slot().FillWidth(0.3f).Padding(4, 2)
			[ SNew(STextBlock).Text(FText::FromString(Item->AssetName))
				.Font(FCoreStyle::GetDefaultFontStyle("Regular", 9)) ]

			+ SHorizontalBox::Slot().FillWidth(0.5f).Padding(4, 2)
			[ SNew(STextBlock).Text(FText::FromString(Item->Description))
				.Font(FCoreStyle::GetDefaultFontStyle("Regular", 9)) ]

			+ SHorizontalBox::Slot().AutoWidth().Padding(2, 2)
			[
				SNew(SBox).WidthOverride(50).HAlign(HAlign_Center)
				[ SNew(STextBlock).Text(FText::FromString(FixText))
					.Font(FCoreStyle::GetDefaultFontStyle("Bold", 9)).ColorAndOpacity(FixColor) ]
			]
			] // close SBorder
		];
}

void SBPDoctorPanel::OnSelectionChanged(TSharedPtr<FBPDoctorResult> SelectedItem, ESelectInfo::Type SelectInfo)
{
	SelectedIssue = SelectedItem;

	// Explicitly update button states
	bool bHasSelection = SelectedItem.IsValid();
	bool bCanFix = bHasSelection && !SelectedItem->bFixed;
	bool bCanRevert = bHasSelection && SelectedItem->bFixed;
	if (FixButton.IsValid()) FixButton->SetEnabled(bCanFix);
	if (RevertButton.IsValid()) RevertButton->SetEnabled(bCanRevert);
	if (OpenEditorButton.IsValid()) OpenEditorButton->SetEnabled(bHasSelection);
	if (CopyButton.IsValid()) CopyButton->SetEnabled(bHasSelection);
	if (SuppressButton.IsValid()) SuppressButton->SetEnabled(bHasSelection);

	if (!bHasSelection)
	{
		DetailText->SetText(LOCTEXT("NoSelection", "Select an issue from the list to see details."));
		return;
	}

	const FBPDoctorCheckDef* Check = FBPDoctorChecks::FindCheck(SelectedItem->CheckCode);

	// ── Expert mode: compact one-liner ──
	if (ExperienceMode == EBPDoctorExperienceMode::Expert)
	{
		FString SevStr = (SelectedItem->Severity == EBPDoctorSeverity::Error) ? TEXT("ERROR") :
			(SelectedItem->Severity == EBPDoctorSeverity::Warning) ? TEXT("WARN") : TEXT("INFO");
		FString FixStr = SelectedItem->bFixed ? TEXT(" [FIXED]") :
			(SelectedItem->bAutoFixable ? TEXT(" [fixable]") : TEXT(""));

		FString Detail = FString::Printf(TEXT("%s [%s] — %s\n%s%s"),
			*SelectedItem->CheckCode, *SevStr, *SelectedItem->AssetName,
			*SelectedItem->Description, *FixStr);

		if (!SelectedItem->NodeHint.IsEmpty())
			Detail += FString::Printf(TEXT("\n> %s"), *SelectedItem->NodeHint);

		DetailText->SetText(FText::FromString(Detail));
		return;
	}

	if (!Check)
	{
		DetailText->SetText(FText::FromString(SelectedItem->Description));
		return;
	}

	// ── Intermediate + Beginner modes ──
	FString SevStr = (Check->Severity == EBPDoctorSeverity::Error) ? TEXT("ERROR") :
		(Check->Severity == EBPDoctorSeverity::Warning) ? TEXT("WARNING") : TEXT("INFO");
	FString ConfStr = (Check->Confidence == EBPDoctorConfidence::High) ? TEXT("HIGH") :
		(Check->Confidence == EBPDoctorConfidence::Medium) ? TEXT("MEDIUM") : TEXT("LOW");
	FString TypeStr = (SelectedItem->AssetType == EBPDoctorAssetType::AnimBP) ? TEXT("AnimBP") : TEXT("Blueprint");

	FString Detail;
	Detail += FString::Printf(TEXT("%s  [%s]\n"), *Check->Name, *SevStr);
	Detail += FString::Printf(TEXT("Code: %s  |  Type: %s  |  Confidence: %s\n"), *Check->Code, *TypeStr, *ConfStr);
	Detail += FString::Printf(TEXT("Asset: %s\n"), *SelectedItem->AssetName);

	// Sprint 5 Phase B P3: show GraphPath when the check pinned a specific sub-graph node.
	// "AnimGraph > LocomotionSM > Idle" tells the dev exactly which sub-graph contains the
	// issue — eliminates the "which of three identically-named nodes?" ambiguity.
	if (!SelectedItem->GraphPath.IsEmpty())
	{
		Detail += FString::Printf(TEXT("Graph: %s\n"), *SelectedItem->GraphPath);
	}

	// Sprint 5 v2.7.1 audit fix: Detection Method describes the implementation heuristic in
	// C++ class names ("walks UAnimGraphNode_X..."). Beginner-mode reviewers flagged this as
	// jargon that confuses without educating. Now shown in Intermediate ONLY (transparency
	// for power users who want to know how the check works) and tooltip-only on the row's
	// Conf column for everyone else. Expert mode keeps Detection out of the detail panel
	// entirely — Expert wants compact one-liners.
	if (!Check->DetectionMethod.IsEmpty() && ExperienceMode == EBPDoctorExperienceMode::Intermediate)
	{
		Detail += FString::Printf(TEXT("Detection: %s\n"), *Check->DetectionMethod);
	}

	Detail += TEXT("\n----\n\n");
	Detail += FString::Printf(TEXT("%s\n"), *SelectedItem->Description);

	if (!SelectedItem->NodeHint.IsEmpty())
	{
		Detail += FString::Printf(TEXT("\n> %s\n"), *SelectedItem->NodeHint);
	}

	// HOW TO FIX — shown in both Intermediate and Beginner
	if (!Check->HowToFix.IsEmpty())
	{
		Detail += TEXT("\n----\n\n");
		Detail += FString::Printf(TEXT("HOW TO FIX:\n%s\n"), *Check->HowToFix);
	}

	// Beginner: WHY IT MATTERS + BEGINNER TIP. Detection is intentionally absent — it
	// describes the heuristic in C++ class names which beginners would Google rather
	// than learn from. Available via the Confidence column tooltip if they want it.
	if (ExperienceMode == EBPDoctorExperienceMode::Beginner)
	{
		if (!Check->WhyItMatters.IsEmpty())
		{
			Detail += TEXT("\n----\n\n");
			Detail += FString::Printf(TEXT("WHY IT MATTERS:\n%s\n"), *Check->WhyItMatters);
		}

		if (!Check->BeginnerTip.IsEmpty())
		{
			Detail += FString::Printf(TEXT("\nBEGINNER TIP:\n%s\n"), *Check->BeginnerTip);
		}
	}

	if (SelectedItem->bFixed)
	{
		Detail += TEXT("\n[FIXED] — Click Revert to undo this fix.");
	}
	else if (SelectedItem->bAutoFixable)
	{
		Detail += TEXT("\nAuto-fix available — click 'Fix This Issue' to preview and apply.");
	}
	else
	{
		Detail += TEXT("\nManual fix required — click 'Navigate' to jump to the issue in the editor.");
	}

	DetailText->SetText(FText::FromString(Detail));
}

void SBPDoctorPanel::RefreshFilteredList()
{
	FilteredIssues.Empty();
	SelectedIssue.Reset();
	if (FixButton.IsValid()) FixButton->SetEnabled(false);
	if (RevertButton.IsValid()) RevertButton->SetEnabled(false);
	if (OpenEditorButton.IsValid()) OpenEditorButton->SetEnabled(false);
	if (CopyButton.IsValid()) CopyButton->SetEnabled(false);
	if (SuppressButton.IsValid()) SuppressButton->SetEnabled(false);

	for (const FBPDoctorAssetInfo& Info : AllResults)
	{
		for (const FBPDoctorResult& Issue : Info.Issues)
		{
			// Severity filter
			bool bShow = false;
			switch (Issue.Severity)
			{
				case EBPDoctorSeverity::Error:   bShow = bShowErrors;   break;
				case EBPDoctorSeverity::Warning: bShow = bShowWarnings; break;
				case EBPDoctorSeverity::Info:    bShow = bShowInfo;     break;
			}

			// Suppression filter
			FString SuppKey = Issue.CheckCode + TEXT("|") + Issue.AssetPath;
			bool bIsSuppressed = SuppressedIssueKeys.Contains(SuppKey);
			if (bShowSuppressed)
			{
				// Suppressed view: ONLY show suppressed items
				bShow = bIsSuppressed;
			}
			else if (bIsSuppressed)
			{
				// Normal view: hide suppressed items
				bShow = false;
			}

			// Search filter
			if (bShow && !SearchFilter.IsEmpty())
			{
				bShow = Issue.CheckCode.Contains(SearchFilter, ESearchCase::IgnoreCase) ||
						Issue.AssetName.Contains(SearchFilter, ESearchCase::IgnoreCase) ||
						Issue.Description.Contains(SearchFilter, ESearchCase::IgnoreCase);
			}

			if (bShow)
			{
				FilteredIssues.Add(MakeShareable(new FBPDoctorResult(Issue)));
			}
		}
	}

	// Sprint 5 Phase D: column-aware sort. Default (no user click) preserves the
	// "Errors first, then Warnings, then Info" rule from earlier sprints. When a column
	// header is clicked, sort by that column in the requested direction. Sort applies
	// AFTER filtering so suppression/search changes don't lose the user's chosen order.
	if (CurrentSortColumn == NAME_None || CurrentSortMode == EColumnSortMode::None)
	{
		FilteredIssues.Sort([](const TSharedPtr<FBPDoctorResult>& A, const TSharedPtr<FBPDoctorResult>& B)
		{
			return static_cast<int32>(A->Severity) < static_cast<int32>(B->Severity);
		});
	}
	else
	{
		const bool bAsc = (CurrentSortMode == EColumnSortMode::Ascending);
		const FName Col = CurrentSortColumn;
		FilteredIssues.Sort([bAsc, Col](const TSharedPtr<FBPDoctorResult>& A, const TSharedPtr<FBPDoctorResult>& B)
		{
			int32 Cmp = 0;
			if (Col == FName("Severity"))
			{
				Cmp = static_cast<int32>(A->Severity) - static_cast<int32>(B->Severity);
			}
			else if (Col == FName("Confidence"))
			{
				const FBPDoctorCheckDef* DefA = FBPDoctorChecks::FindCheck(A->CheckCode);
				const FBPDoctorCheckDef* DefB = FBPDoctorChecks::FindCheck(B->CheckCode);
				const int32 ConfA = DefA ? static_cast<int32>(DefA->Confidence) : -1;
				const int32 ConfB = DefB ? static_cast<int32>(DefB->Confidence) : -1;
				Cmp = ConfA - ConfB;
			}
			else if (Col == FName("Code"))
			{
				Cmp = A->CheckCode.Compare(B->CheckCode);
			}
			else if (Col == FName("Type"))
			{
				Cmp = static_cast<int32>(A->AssetType) - static_cast<int32>(B->AssetType);
			}
			else if (Col == FName("Asset"))
			{
				Cmp = A->AssetName.Compare(B->AssetName);
			}
			else if (Col == FName("Description"))
			{
				Cmp = A->Description.Compare(B->Description);
			}
			else if (Col == FName("AutoFix"))
			{
				// Fixed first, then fixable, then non-fixable
				const int32 RankA = A->bFixed ? 0 : (A->bAutoFixable ? 1 : 2);
				const int32 RankB = B->bFixed ? 0 : (B->bAutoFixable ? 1 : 2);
				Cmp = RankA - RankB;
			}
			return bAsc ? (Cmp < 0) : (Cmp > 0);
		});
	}

	if (IssueListView.IsValid())
	{
		IssueListView->RequestListRefresh();
	}
}

void SBPDoctorPanel::UpdateStats()
{
	TotalScanned = AllResults.Num();
	TotalErrors = Scanner->GetErrorCount();
	TotalWarnings = Scanner->GetWarningCount();
	TotalInfos = Scanner->GetInfoCount();

	TotalAutoFixable = 0;
	for (const auto& Info : AllResults)
	{
		for (const auto& Issue : Info.Issues)
		{
			if (Issue.bAutoFixable && !Issue.bFixed) TotalAutoFixable++;
		}
	}

	// Calculate overall health grade
	if (TotalScanned == 0)
	{
		HealthGrade = TEXT("-");
	}
	else if (TotalErrors == 0 && TotalWarnings == 0 && TotalInfos == 0)
	{
		HealthGrade = TEXT("A+");
	}
	else if (TotalErrors == 0 && TotalWarnings == 0)
	{
		HealthGrade = TEXT("A");
	}
	else if (TotalErrors == 0 && TotalWarnings <= 3)
	{
		HealthGrade = TEXT("B+");
	}
	else if (TotalErrors == 0)
	{
		HealthGrade = TEXT("B");
	}
	else if (TotalErrors <= 2)
	{
		HealthGrade = TEXT("C");
	}
	else if (TotalErrors <= 5)
	{
		HealthGrade = TEXT("D");
	}
	else
	{
		HealthGrade = TEXT("F");
	}
}

// ─────────────────────────────────────────────────────────────────
//  ATTRIBUTE BINDINGS
// ─────────────────────────────────────────────────────────────────

TOptional<float> SBPDoctorPanel::GetProgressPercent() const
{
	if (!bScanRunning && CurrentProgress <= 0.f) return TOptional<float>();
	return CurrentProgress;
}

FText SBPDoctorPanel::GetHealthGradeText() const
{
	return FText::FromString(HealthGrade);
}

FSlateColor SBPDoctorPanel::GetHealthGradeColor() const
{
	if (HealthGrade == TEXT("A+") || HealthGrade == TEXT("A"))
		return FSlateColor(FLinearColor(0.f, 0.902f, 0.463f));
	if (HealthGrade == TEXT("B+") || HealthGrade == TEXT("B"))
		return FSlateColor(FLinearColor(1.f, 0.843f, 0.251f));
	if (HealthGrade == TEXT("C"))
		return FSlateColor(FLinearColor(1.f, 0.549f, 0.f));
	if (HealthGrade == TEXT("D") || HealthGrade == TEXT("F"))
		return FSlateColor(FLinearColor(1.f, 0.09f, 0.27f));
	return FSlateColor(FLinearColor(0.533f, 0.533f, 0.667f));
}

FText SBPDoctorPanel::GetStatsText() const
{
	if (TotalScanned == 0)
		return LOCTEXT("NoScan", "No scan results yet. Click Scan Project to begin.");

	FString StatsStr = FString::Printf(
		TEXT("Scanned: %d assets  |  %d AnimBPs + %d BPs\nErrors: %d  |  Warnings: %d  |  Info: %d  |  Auto-fixable: %d"),
		TotalScanned, Scanner->GetAnimBPCount(), Scanner->GetBlueprintCount(),
		TotalErrors, TotalWarnings, TotalInfos, TotalAutoFixable);
	if (SuppressedIssueKeys.Num() > 0)
	{
		StatsStr += FString::Printf(TEXT("  |  Suppressed: %d"), SuppressedIssueKeys.Num());
	}
	return FText::FromString(StatsStr);
}

// ─────────────────────────────────────────────────────────────────
//  HELPERS
// ─────────────────────────────────────────────────────────────────

UBlueprint* SBPDoctorPanel::LoadBlueprintFromResult(const FBPDoctorResult& Result)
{
	// Try loading via AssetRegistry first (most reliable)
	IAssetRegistry& AssetRegistry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();

	// AssetPath from GetPathName() is like "/Game/Path/BP.BP"
	// Try as-is first
	FAssetData AssetData = AssetRegistry.GetAssetByObjectPath(FSoftObjectPath(Result.AssetPath));
	if (AssetData.IsValid())
	{
		return Cast<UBlueprint>(AssetData.GetAsset());
	}

	// Fallback: try loading the object directly
	UObject* Obj = StaticLoadObject(UBlueprint::StaticClass(), nullptr, *Result.AssetPath);
	if (Obj)
	{
		return Cast<UBlueprint>(Obj);
	}

	// Final fallback: strip the object name suffix and try package path
	FString PackagePath = Result.AssetPath;
	int32 DotIndex;
	if (PackagePath.FindLastChar('.', DotIndex))
	{
		PackagePath = PackagePath.Left(DotIndex);
	}
	Obj = StaticLoadObject(UBlueprint::StaticClass(), nullptr, *PackagePath);
	return Cast<UBlueprint>(Obj);
}

// ─────────────────────────────────────────────────────────────────
//  FIX CONFIRMATION DIALOG
// ─────────────────────────────────────────────────────────────────

void SBPDoctorPanel::ShowFixConfirmDialog(TSharedPtr<FBPDoctorResult> Issue)
{
	UBlueprint* BP = LoadBlueprintFromResult(*Issue);
	if (!BP)
	{
		DetailText->SetText(FText::FromString(
			FString::Printf(TEXT("ERROR: Could not load Blueprint '%s'.\nIt may have been deleted or moved."),
				*Issue->AssetName)));
		return;
	}

	FBPDoctorFixAction Preview = FBPDoctorFixes::PreviewFix(*Issue, BP);

	TSharedPtr<int32> DialogResult = MakeShared<int32>(0);
	TSharedPtr<FString> CustomValue = MakeShared<FString>();

	// Fix type badge
	FString FixTypeStr;
	FLinearColor FixTypeColor;
	switch (Preview.FixType)
	{
		case EBPDoctorFixType::Programmatic:
			FixTypeStr = TEXT("AUTO-FIX AVAILABLE");
			FixTypeColor = FLinearColor(0.f, 0.902f, 0.463f);
			break;
		case EBPDoctorFixType::Script:
			FixTypeStr = TEXT("SCRIPT FIX");
			FixTypeColor = FLinearColor(1.f, 0.843f, 0.251f);
			break;
		default:
			FixTypeStr = TEXT("MANUAL FIX REQUIRED");
			FixTypeColor = FLinearColor(0.533f, 0.533f, 0.667f);
			break;
	}

	bool bCanAutoFix = (Preview.FixType == EBPDoctorFixType::Programmatic && Issue->bAutoFixable);

	// Manual input support — only for certain checks
	bool bHasCustomInput = bCanAutoFix &&
		(Issue->CheckCode == TEXT("BROKEN_BLEND_WT") || Issue->CheckCode == TEXT("DUP_SLOT"));
	FString InputLabel;
	FString InputDefault;
	if (Issue->CheckCode == TEXT("BROKEN_BLEND_WT"))
	{
		InputLabel = TEXT("CUSTOM VALUE (optional — leave empty for auto-clamp):");
		InputDefault = TEXT("");
	}
	else if (Issue->CheckCode == TEXT("DUP_SLOT"))
	{
		InputLabel = TEXT("CUSTOM SLOT NAME (optional — leave empty for auto-suffix):");
		InputDefault = TEXT("");
	}

	TSharedRef<SWindow> DialogWindow = SNew(SWindow)
		.Title(LOCTEXT("FixPreviewTitle", "BP Doctor — Fix Preview"))
		.ClientSize(FVector2D(540, 440))
		.SupportsMaximize(false)
		.SupportsMinimize(false)
		.IsTopmostWindow(true);

	TWeakPtr<SWindow> WeakWindow(DialogWindow);

	DialogWindow->SetContent(
		SNew(SBorder)
		.BorderImage(FAppStyle::GetBrush("ToolPanel.DarkGroupBorder"))
		.Padding(16)
		[
			SNew(SVerticalBox)

			// Header
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 4)
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().AutoWidth()
				[
					SNew(STextBlock)
					.Text(FText::FromString(Issue->CheckCode))
					.Font(FCoreStyle::GetDefaultFontStyle("Bold", 14))
					.ColorAndOpacity(FLinearColor(0.f, 0.898f, 1.f))
				]
				+ SHorizontalBox::Slot().AutoWidth().Padding(12, 3, 0, 0)
				[
					SNew(STextBlock)
					.Text(FText::FromString(FixTypeStr))
					.Font(FCoreStyle::GetDefaultFontStyle("Bold", 9))
					.ColorAndOpacity(FixTypeColor)
				]
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 8)
			[
				SNew(STextBlock)
				.Text(FText::FromString(FString::Printf(TEXT("Asset: %s"), *Issue->AssetName)))
				.Font(FCoreStyle::GetDefaultFontStyle("Regular", 10))
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 4)
			[ SNew(SSeparator) ]

			// Description
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 8, 0, 4)
			[
				SNew(STextBlock)
				.Text(LOCTEXT("WhatThisDoes2", "WHAT THIS FIX DOES:"))
				.Font(FCoreStyle::GetDefaultFontStyle("Bold", 10))
				.ColorAndOpacity(FLinearColor(0.533f, 0.533f, 0.667f))
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 8)
			[
				SNew(STextBlock)
				.Text(FText::FromString(Preview.Description))
				.Font(FCoreStyle::GetDefaultFontStyle("Regular", 11))
				.AutoWrapText(true)
			]

			// Changes
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 4)
			[
				SNew(STextBlock)
				.Text(LOCTEXT("Changes2", "CHANGES:"))
				.Font(FCoreStyle::GetDefaultFontStyle("Bold", 10))
				.ColorAndOpacity(FLinearColor(0.533f, 0.533f, 0.667f))
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 8)
			[
				SNew(STextBlock)
				.Text(FText::FromString(Preview.Preview.IsEmpty() ? TEXT("See description above.") : Preview.Preview))
				.Font(FCoreStyle::GetDefaultFontStyle("Regular", 11))
				.AutoWrapText(true)
			]

			// Manual input (only visible for supported checks)
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 4, 0, 4)
			[
				SNew(SVerticalBox)
				.Visibility(bHasCustomInput ? EVisibility::Visible : EVisibility::Collapsed)

				+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 4)
				[
					SNew(STextBlock)
					.Text(FText::FromString(InputLabel))
					.Font(FCoreStyle::GetDefaultFontStyle("Bold", 10))
					.ColorAndOpacity(FLinearColor(1.f, 0.843f, 0.251f))
				]
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(SEditableTextBox)
					.HintText(LOCTEXT("CustomHint", "Leave empty for default behavior"))
					.OnTextChanged_Lambda([CustomValue](const FText& Text) { *CustomValue = Text.ToString(); })
				]
			]

			// Revert note
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 8, 0, 12)
			[
				SNew(STextBlock)
				.Text(LOCTEXT("UndoNote2", "All fixes can be reverted with Ctrl+Z or the Undo Fix button."))
				.Font(FCoreStyle::GetDefaultFontStyle("Italic", 9))
				.ColorAndOpacity(FLinearColor(0.f, 0.902f, 0.463f))
			]

			+ SVerticalBox::Slot().FillHeight(1.f) [ SNew(SSpacer) ]

			// Buttons
			+ SVerticalBox::Slot().AutoHeight()
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 8, 0)
				[
					SNew(SButton)
					.Text(LOCTEXT("ApplyFixBtn2", "Apply Fix"))
					.ToolTipText(LOCTEXT("ApplyFixTip2", "Apply the fix now (undoable with Ctrl+Z)"))
					.IsEnabled(bCanAutoFix)
					.OnClicked_Lambda([DialogResult, WeakWindow]() {
						*DialogResult = 1;
						if (auto Pin = WeakWindow.Pin()) Pin->RequestDestroyWindow();
						return FReply::Handled();
					})
				]
				+ SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 8, 0)
				[
					SNew(SButton)
					.Text(LOCTEXT("OpenEditorBtn2", "Open in Editor"))
					.ToolTipText(LOCTEXT("OpenEditorTip2", "Open the Blueprint for manual editing"))
					.OnClicked_Lambda([DialogResult, WeakWindow]() {
						*DialogResult = 2;
						if (auto Pin = WeakWindow.Pin()) Pin->RequestDestroyWindow();
						return FReply::Handled();
					})
				]
				+ SHorizontalBox::Slot().FillWidth(1.f) [ SNew(SSpacer) ]
				+ SHorizontalBox::Slot().AutoWidth()
				[
					SNew(SButton)
					.Text(LOCTEXT("CancelBtn2", "Cancel"))
					.OnClicked_Lambda([WeakWindow]() {
						if (auto Pin = WeakWindow.Pin()) Pin->RequestDestroyWindow();
						return FReply::Handled();
					})
				]
			]
		]
	);

	FSlateApplication::Get().AddModalWindow(DialogWindow, TSharedPtr<const SWidget>());

	if (*DialogResult == 1)
	{
		// Backup .uasset BEFORE fixing — bulletproof revert
		FString BackupPath = BackupPackageFile(BP);

		// No outer FScopedTransaction / Modify here — ApplyFix owns its own.
		bool bSuccess = FBPDoctorFixes::ApplyFix(*Issue, BP, *CustomValue);

		if (bSuccess)
		{
			Issue->bFixed = true;
			for (FBPDoctorAssetInfo& Info : AllResults)
			{
				for (FBPDoctorResult& R : Info.Issues)
				{
					if (R.CheckCode == Issue->CheckCode && R.AssetPath == Issue->AssetPath)
						R.bFixed = true;
				}
			}

			FBPDoctorFixHistoryEntry Entry;
			Entry.CheckCode = Issue->CheckCode;
			Entry.AssetName = Issue->AssetName;
			Entry.AssetPath = Issue->AssetPath;
			Entry.FixDescription = Preview.Description;
			if (!BackupPath.IsEmpty())
			{
				FString PkgFile;
				FPackageName::DoesPackageExist(BP->GetPackage()->GetName(), &PkgFile);
				Entry.Backups.Add(PkgFile, BackupPath);
			}
			FixHistory.Add(Entry);

			UpdateStats();
			RefreshFilteredList();
			DetailText->SetText(FText::FromString(FString::Printf(
				TEXT("FIXED: %s in %s\n\nBlueprint modified. Save to persist, or Ctrl+Z / Undo Fix to revert."),
				*Issue->CheckCode, *Issue->AssetName)));

			// Sprint 5 Phase D: post-fix toast (visible feedback even if user has scrolled away
			// from the detail panel). 4s duration matches UE editor convention for non-blocking ops.
			ShowFixToast(true, Issue->CheckCode, Issue->AssetName);
		}
		else
		{
			DetailText->SetText(FText::FromString(
				TEXT("Fix could not be applied automatically.\nUse 'Open in Editor' for manual intervention.")));
			ShowFixToast(false, Issue->CheckCode, Issue->AssetName);
		}
	}
	else if (*DialogResult == 2)
	{
		OpenBlueprintInEditor(Issue->AssetPath);
	}
}

// ─────────────────────────────────────────────────────────────────
//  FIX ALL DIALOG — checklist UI
// ─────────────────────────────────────────────────────────────────

void SBPDoctorPanel::ShowFixAllDialog()
{
	// Collect all fixable issues with their asset paths
	TArray<FBPDoctorResult> FixableIssues;
	TArray<FString> AssetPaths;
	TArray<TSharedPtr<bool>> Selections;

	for (const FBPDoctorAssetInfo& Info : AllResults)
	{
		for (const FBPDoctorResult& Issue : Info.Issues)
		{
			if (Issue.bAutoFixable && !Issue.bFixed)
			{
				FixableIssues.Add(Issue);
				AssetPaths.Add(Info.AssetPath);
				Selections.Add(MakeShared<bool>(true));
			}
		}
	}

	if (FixableIssues.Num() == 0)
	{
		DetailText->SetText(LOCTEXT("NoFixable", "No auto-fixable issues found."));
		return;
	}

	TSharedPtr<bool> bApply = MakeShared<bool>(false);

	TSharedRef<SWindow> DialogWindow = SNew(SWindow)
		.Title(LOCTEXT("FixAllDlgTitle", "BP Doctor — Fix All Preview"))
		.ClientSize(FVector2D(700, 520))
		.SupportsMaximize(false)
		.SupportsMinimize(false)
		.IsTopmostWindow(true);

	TWeakPtr<SWindow> WeakWindow(DialogWindow);

	// Build the scrollable checklist
	TSharedRef<SScrollBox> CheckList = SNew(SScrollBox);

	for (int32 i = 0; i < FixableIssues.Num(); ++i)
	{
		TSharedPtr<bool> Sel = Selections[i];
		const FBPDoctorResult& Issue = FixableIssues[i];

		FLinearColor SevColor = (Issue.Severity == EBPDoctorSeverity::Error)
			? FLinearColor(1.f, 0.09f, 0.27f)
			: (Issue.Severity == EBPDoctorSeverity::Warning)
				? FLinearColor(1.f, 0.843f, 0.251f)
				: FLinearColor(0.f, 0.898f, 1.f);

		FString SevStr = (Issue.Severity == EBPDoctorSeverity::Error) ? TEXT("ERR")
			: (Issue.Severity == EBPDoctorSeverity::Warning) ? TEXT("WRN") : TEXT("INF");

		CheckList->AddSlot()
		.Padding(2, 2)
		[
			SNew(SCheckBox)
			.IsChecked_Lambda([Sel]() { return *Sel ? ECheckBoxState::Checked : ECheckBoxState::Unchecked; })
			.OnCheckStateChanged_Lambda([Sel](ECheckBoxState State) { *Sel = (State == ECheckBoxState::Checked); })
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().AutoWidth().Padding(4, 0)
				[
					SNew(SBox).WidthOverride(35)
					[
						SNew(STextBlock)
						.Text(FText::FromString(SevStr))
						.Font(FCoreStyle::GetDefaultFontStyle("Bold", 9))
						.ColorAndOpacity(SevColor)
					]
				]
				+ SHorizontalBox::Slot().AutoWidth().Padding(4, 0)
				[
					SNew(SBox).WidthOverride(130)
					[
						SNew(STextBlock)
						.Text(FText::FromString(Issue.CheckCode))
						.Font(FCoreStyle::GetDefaultFontStyle("Bold", 9))
						.ColorAndOpacity(SevColor)
					]
				]
				+ SHorizontalBox::Slot().AutoWidth().Padding(4, 0)
				[
					SNew(SBox).WidthOverride(140)
					[
						SNew(STextBlock)
						.Text(FText::FromString(Issue.AssetName))
						.Font(FCoreStyle::GetDefaultFontStyle("Regular", 9))
					]
				]
				+ SHorizontalBox::Slot().FillWidth(1.f).Padding(4, 0)
				[
					SNew(STextBlock)
					.Text(FText::FromString(Issue.Description))
					.Font(FCoreStyle::GetDefaultFontStyle("Regular", 9))
					.AutoWrapText(true)
				]
			]
		];
	}

	DialogWindow->SetContent(
		SNew(SBorder)
		.BorderImage(FAppStyle::GetBrush("ToolPanel.DarkGroupBorder"))
		.Padding(16)
		[
			SNew(SVerticalBox)

			+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 4)
			[
				SNew(STextBlock)
				.Text(FText::Format(LOCTEXT("FixAllItemCount", "{0} auto-fixable issues found"), FText::AsNumber(FixableIssues.Num())))
				.Font(FCoreStyle::GetDefaultFontStyle("Bold", 14))
				.ColorAndOpacity(FLinearColor(0.f, 0.898f, 1.f))
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 8)
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().FillWidth(1.f)
				[
					SNew(STextBlock)
					.Text(LOCTEXT("FixAllInstructions", "Uncheck issues to skip. All fixes are revertable via Undo Fix."))
					.Font(FCoreStyle::GetDefaultFontStyle("Regular", 10))
					.AutoWrapText(true)
				]
				+ SHorizontalBox::Slot().AutoWidth().Padding(8, 0, 4, 0)
				[
					SNew(SButton)
					.Text(LOCTEXT("SelectAllBtn", "Select All"))
					.OnClicked_Lambda([Selections]() {
						for (const auto& Sel : Selections) *Sel = true;
						return FReply::Handled();
					})
				]
				+ SHorizontalBox::Slot().AutoWidth()
				[
					SNew(SButton)
					.Text(LOCTEXT("DeselectAllBtn", "Deselect All"))
					.OnClicked_Lambda([Selections]() {
						for (const auto& Sel : Selections) *Sel = false;
						return FReply::Handled();
					})
				]
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 4)
			[ SNew(SSeparator) ]

			// Checklist
			+ SVerticalBox::Slot().FillHeight(1.f).Padding(0, 4)
			[ CheckList ]

			+ SVerticalBox::Slot().AutoHeight().Padding(0, 8, 0, 0)
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 8, 0)
				[
					SNew(SButton)
					.Text(LOCTEXT("ApplySelectedBtn", "Apply Selected Fixes"))
					.ToolTipText(LOCTEXT("ApplySelectedTip", "Apply all checked fixes (undoable with Ctrl+Z)"))
					.OnClicked_Lambda([bApply, WeakWindow]() {
						*bApply = true;
						if (auto Pin = WeakWindow.Pin()) Pin->RequestDestroyWindow();
						return FReply::Handled();
					})
				]
				+ SHorizontalBox::Slot().FillWidth(1.f) [ SNew(SSpacer) ]
				+ SHorizontalBox::Slot().AutoWidth()
				[
					SNew(SButton)
					.Text(LOCTEXT("CancelAllBtn", "Cancel"))
					.OnClicked_Lambda([WeakWindow]() {
						if (auto Pin = WeakWindow.Pin()) Pin->RequestDestroyWindow();
						return FReply::Handled();
					})
				]
			]
		]
	);

	FSlateApplication::Get().AddModalWindow(DialogWindow, TSharedPtr<const SWidget>());

	if (!*bApply) return;

	// Count selected
	int32 SelectedCount = 0;
	for (const auto& Sel : Selections)
	{
		if (*Sel) SelectedCount++;
	}
	if (SelectedCount == 0) return;

	// Backup all affected .uasset files BEFORE fixing
	TMap<FString, FString> BatchBackups; // OriginalPath -> BackupPath
	for (int32 i = 0; i < FixableIssues.Num(); ++i)
	{
		if (!*Selections[i]) continue;
		const FString& Path = AssetPaths[i];
		if (!BatchBackups.Contains(Path))
		{
			FBPDoctorResult TmpR;
			TmpR.AssetPath = Path;
			UBlueprint* TmpBP = LoadBlueprintFromResult(TmpR);
			FString BkPath = BackupPackageFile(TmpBP);
			if (!BkPath.IsEmpty())
			{
				FString PkgFile;
				FPackageName::DoesPackageExist(TmpBP->GetPackage()->GetName(), &PkgFile);
				BatchBackups.Add(PkgFile, BkPath);
			}
		}
	}

	// Per-fix undo granularity: each inner ApplyFix owns its own transaction.
	int32 TotalFixed = 0;
	TMap<FString, UBlueprint*> LoadedBPs;

	for (int32 i = 0; i < FixableIssues.Num(); ++i)
	{
		if (!*Selections[i]) continue;

		const FString& Path = AssetPaths[i];
		UBlueprint* BP = nullptr;

		if (UBlueprint** Found = LoadedBPs.Find(Path))
		{
			BP = *Found;
		}
		else
		{
			IAssetRegistry& AR = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();
			FAssetData AD = AR.GetAssetByObjectPath(FSoftObjectPath(Path));
			BP = AD.IsValid() ? Cast<UBlueprint>(AD.GetAsset()) : nullptr;
			if (BP)
			{
				BP->Modify();
				LoadedBPs.Add(Path, BP);
			}
		}

		if (BP && FBPDoctorFixes::ApplyFix(FixableIssues[i], BP))
		{
			TotalFixed++;
			for (FBPDoctorAssetInfo& Info : AllResults)
			{
				for (FBPDoctorResult& R : Info.Issues)
				{
					if (R.CheckCode == FixableIssues[i].CheckCode && R.AssetPath == FixableIssues[i].AssetPath)
						R.bFixed = true;
				}
			}
		}
	}

	FBPDoctorFixHistoryEntry Entry;
	Entry.CheckCode = TEXT("FIX_ALL");
	Entry.AssetName = FString::Printf(TEXT("%d of %d selected fixes applied"), TotalFixed, SelectedCount);
	Entry.FixDescription = TEXT("Batch fix (selected)");
	Entry.Backups = BatchBackups;
	FixHistory.Add(Entry);

	UpdateStats();
	RefreshFilteredList();
	DetailText->SetText(FText::FromString(FString::Printf(
		TEXT("Applied %d fixes.\n\nAll changes are undoable via Ctrl+Z or the Undo Fix button.\nRe-scan to verify."),
		TotalFixed)));

	// Sprint 5 Phase D: batch fix toast — green if any fix succeeded, otherwise neutral.
	// SelectedCount reflects what the user TRIED to fix; TotalFixed is what landed.
	{
		FNotificationInfo Info(FText::Format(
			LOCTEXT("FixAllToastFmt", "Fix All: {0} of {1} fixes applied"),
			FText::AsNumber(TotalFixed), FText::AsNumber(SelectedCount)));
		Info.ExpireDuration = 4.0f;
		Info.bUseSuccessFailIcons = true;
		TSharedPtr<SNotificationItem> Notif = FSlateNotificationManager::Get().AddNotification(Info);
		if (Notif.IsValid())
		{
			Notif->SetCompletionState(TotalFixed > 0
				? SNotificationItem::CS_Success
				: SNotificationItem::CS_Fail);
		}
	}
}

// ─────────────────────────────────────────────────────────────────
//  UNDO / REVERT
// ─────────────────────────────────────────────────────────────────

FReply SBPDoctorPanel::OnUndoLastFix()
{
	int32 LastIndex = -1;
	for (int32 i = FixHistory.Num() - 1; i >= 0; --i)
	{
		if (!FixHistory[i].bReverted)
		{
			LastIndex = i;
			break;
		}
	}

	if (LastIndex < 0)
	{
		DetailText->SetText(LOCTEXT("NoFixToUndo", "No fixes to undo."));
		return FReply::Handled();
	}

	// Try multiple undo methods — at least one will work
	bool bUndone = false;
	if (GEditor)
	{
		// Method 1: Transaction buffer direct undo (most reliable)
		// Use GEditor->UndoTransaction() (fires delegates) over Trans->Undo() — P2-01.
		if (GEditor->Trans && GEditor->Trans->CanUndo())
		{
			GEditor->UndoTransaction();
			bUndone = true;
		}
	}

	if (bUndone)
	{
		FixHistory[LastIndex].bReverted = true;
		DetailText->SetText(FText::FromString(FString::Printf(
			TEXT("REVERTED: %s in %s\n\nBlueprint restored. Re-scan to refresh results."),
			*FixHistory[LastIndex].CheckCode, *FixHistory[LastIndex].AssetName)));
	}
	else
	{
		// Fallback: reload from disk if transaction undo failed
		if (!FixHistory[LastIndex].AssetPath.IsEmpty())
		{
			RevertBlueprint(FixHistory[LastIndex].AssetPath);
			FixHistory[LastIndex].bReverted = true;
			DetailText->SetText(FText::FromString(FString::Printf(
				TEXT("REVERTED: %s in %s\n\nBlueprint reloaded from disk. Re-scan to refresh."),
				*FixHistory[LastIndex].CheckCode, *FixHistory[LastIndex].AssetName)));
		}
		else
		{
			DetailText->SetText(FText::FromString(
				TEXT("Could not undo automatically.\nRight-click the asset in Content Browser → Asset Actions → Reload to revert.")));
		}
	}

	return FReply::Handled();
}

FReply SBPDoctorPanel::OnRevertSelected()
{
	if (!SelectedIssue.IsValid() || !SelectedIssue->bFixed)
		return FReply::Handled();

	FString RevertedCheck = SelectedIssue->CheckCode;
	FString RevertedAsset = SelectedIssue->AssetName;
	FString RevertedPath = SelectedIssue->AssetPath;

	// Find the fix history entry with backup files
	FBPDoctorFixHistoryEntry* HistEntry = nullptr;
	for (int32 i = FixHistory.Num() - 1; i >= 0; --i)
	{
		if (!FixHistory[i].bReverted &&
			FixHistory[i].CheckCode == RevertedCheck &&
			FixHistory[i].AssetPath == RevertedPath)
		{
			HistEntry = &FixHistory[i];
			break;
		}
	}

	bool bReverted = false;

	if (HistEntry && HistEntry->Backups.Num() > 0)
	{
		// Bulletproof revert: restore from backup files
		UBlueprint* BP = LoadBlueprintFromResult(*SelectedIssue);
		if (BP && GEditor)
		{
			GEditor->GetEditorSubsystem<UAssetEditorSubsystem>()->CloseAllEditorsForAsset(BP);
		}

		for (const auto& Pair : HistEntry->Backups)
		{
			const FString& OriginalPath = Pair.Key;
			const FString& BackupPath = Pair.Value;

			// Copy backup back over the original .uasset
			IFileManager::Get().Copy(*OriginalPath, *BackupPath, true);

			// Force reload from restored file
			if (BP)
			{
				UPackage* Package = BP->GetPackage();
				if (Package)
				{
					ResetLoaders(Package);
					LoadPackage(Package, *OriginalPath, LOAD_None);
				}
			}

			// Clean up backup file
			IFileManager::Get().Delete(*BackupPath);
		}

		HistEntry->Backups.Empty();
		HistEntry->bReverted = true;
		bReverted = true;
	}
	else
	{
		// Fallback: try transaction undo
		// UndoTransaction fires notification delegates — P2-01.
		if (GEditor && GEditor->Trans && GEditor->Trans->CanUndo())
		{
			GEditor->UndoTransaction();
			bReverted = true;
			if (HistEntry) HistEntry->bReverted = true;
		}
	}

	if (bReverted)
	{
		for (FBPDoctorAssetInfo& Info : AllResults)
		{
			for (FBPDoctorResult& R : Info.Issues)
			{
				if (R.CheckCode == RevertedCheck && R.AssetPath == RevertedPath)
					R.bFixed = false;
			}
		}
		UpdateStats();
		RefreshFilteredList();
		DetailText->SetText(FText::FromString(FString::Printf(
			TEXT("REVERTED: %s in %s\n\nBlueprint restored to pre-fix state.\nRe-scan to verify."),
			*RevertedCheck, *RevertedAsset)));
	}

	return FReply::Handled();
}

void SBPDoctorPanel::RevertBlueprint(const FString& AssetPath)
{
	// Find history entry with backup for this asset
	for (int32 i = FixHistory.Num() - 1; i >= 0; --i)
	{
		if (!FixHistory[i].bReverted && FixHistory[i].AssetPath == AssetPath && FixHistory[i].Backups.Num() > 0)
		{
			FBPDoctorResult TempResult;
			TempResult.AssetPath = AssetPath;
			UBlueprint* BP = LoadBlueprintFromResult(TempResult);
			if (BP && GEditor)
			{
				GEditor->GetEditorSubsystem<UAssetEditorSubsystem>()->CloseAllEditorsForAsset(BP);
			}

			for (const auto& Pair : FixHistory[i].Backups)
			{
				IFileManager::Get().Copy(*Pair.Key, *Pair.Value, true);
				if (BP)
				{
					UPackage* Package = BP->GetPackage();
					if (Package)
					{
						ResetLoaders(Package);
						LoadPackage(Package, *Pair.Key, LOAD_None);
					}
				}
				IFileManager::Get().Delete(*Pair.Value);
			}
			FixHistory[i].Backups.Empty();
			FixHistory[i].bReverted = true;
			return;
		}
	}

	// Fallback if no backup exists: try reload from existing disk file
	FBPDoctorResult TempResult;
	TempResult.AssetPath = AssetPath;
	UBlueprint* BP = LoadBlueprintFromResult(TempResult);
	if (!BP) return;
	if (GEditor) GEditor->GetEditorSubsystem<UAssetEditorSubsystem>()->CloseAllEditorsForAsset(BP);
	UPackage* Package = BP->GetPackage();
	if (!Package) return;
	FString PkgFile;
	if (FPackageName::DoesPackageExist(Package->GetName(), &PkgFile))
	{
		ResetLoaders(Package);
		LoadPackage(Package, *PkgFile, LOAD_None);
	}
}

FString SBPDoctorPanel::BackupPackageFile(UBlueprint* BP)
{
	if (!BP) return FString();

	UPackage* Package = BP->GetPackage();
	if (!Package) return FString();

	FString PkgFilename;
	if (!FPackageName::DoesPackageExist(Package->GetName(), &PkgFilename))
		return FString();

	FString BackupDir = FPaths::ProjectSavedDir() / TEXT("BPDoctor") / TEXT("Backups");
	IFileManager::Get().MakeDirectory(*BackupDir, true);
	FString BackupPath = BackupDir / FString::Printf(TEXT("backup_%s.uasset"),
		*FGuid::NewGuid().ToString().Left(8));

	if (IFileManager::Get().Copy(*BackupPath, *PkgFilename) == COPY_OK)
	{
		return BackupPath;
	}
	return FString();
}

void SBPDoctorPanel::NavigateToIssue(const FBPDoctorResult& Result)
{
	UBlueprint* BP = LoadBlueprintFromResult(Result);
	if (!BP || !GEditor) return;

	// Open the Blueprint in the editor
	GEditor->GetEditorSubsystem<UAssetEditorSubsystem>()->OpenEditorForAsset(BP);

	// Sprint 5 Phase B P1 completion: if the result carries a stable Node ptr, jump
	// directly. This skips the title-matching fallback entirely — works for SM-internal
	// AnimBP nodes where titles are ambiguous (e.g. three "Layered blend per bone" nodes
	// in three states all have the same title and the string match would land on the
	// wrong one). Phase A's recursive sub-graph collection is still used as the fallback
	// for older results that pre-date this field.
	if (Result.Node.IsValid())
	{
		FKismetEditorUtilities::BringKismetToFocusAttentionOnObject(Result.Node.Get());
		return;
	}

	// Try to find and zoom to the specific node mentioned in NodeHint
	if (Result.NodeHint.IsEmpty()) return;

	// Collect every searchable graph. Top-level first (Ubergraph/Function/Macro), then
	// for AnimBPs recursively walk into AnimGraphNode_Base->GetSubGraphs() — state machine
	// state sub-graphs, layered linked layers, etc. Without this recursion, navigate
	// silently lands at the root for every AnimBP SilentFailure check whose node lives
	// inside an SM state — i.e. the headline product use case (Sprint 5 P0-1).
	TArray<UEdGraph*> AllGraphs;
	AllGraphs.Append(BP->UbergraphPages);
	AllGraphs.Append(BP->FunctionGraphs);
	AllGraphs.Append(BP->MacroGraphs);

	if (UAnimBlueprint* AnimBP = Cast<UAnimBlueprint>(BP))
	{
		TFunction<void(UEdGraph*)> CollectSubGraphs = [&](UEdGraph* Graph)
		{
			if (!Graph) return;
			for (UEdGraphNode* Node : Graph->Nodes)
			{
				if (UAnimGraphNode_Base* AnimNode = Cast<UAnimGraphNode_Base>(Node))
				{
					for (UEdGraph* Sub : AnimNode->GetSubGraphs())
					{
						if (Sub && !AllGraphs.Contains(Sub))
						{
							AllGraphs.Add(Sub);
							CollectSubGraphs(Sub);
						}
					}
				}
			}
		};
		// Snapshot the seed set so the recursive append doesn't disturb iteration.
		TArray<UEdGraph*> Seeds = AllGraphs;
		for (UEdGraph* Seed : Seeds)
		{
			CollectSubGraphs(Seed);
		}
	}

	for (UEdGraph* Graph : AllGraphs)
	{
		for (UEdGraphNode* Node : Graph->Nodes)
		{
			FString NodeTitle = Node->GetNodeTitle(ENodeTitleType::FullTitle).ToString();
			FString NodeName = Node->GetName();
			if (Result.NodeHint.Contains(NodeTitle) || NodeTitle.Contains(Result.NodeHint) ||
				Result.NodeHint.Contains(NodeName))
			{
				FKismetEditorUtilities::BringKismetToFocusAttentionOnObject(Node);
				return;
			}
		}
	}
}

// ─────────────────────────────────────────────────────────────────
//  COPY / SUPPRESS
// ─────────────────────────────────────────────────────────────────

FReply SBPDoctorPanel::OnCopyDetails()
{
	if (!SelectedIssue.IsValid()) return FReply::Handled();

	const FBPDoctorCheckDef* Check = FBPDoctorChecks::FindCheck(SelectedIssue->CheckCode);

	FString ClipText;
	ClipText += FString::Printf(TEXT("BP Doctor Issue: %s\n"), *SelectedIssue->CheckCode);
	ClipText += FString::Printf(TEXT("Asset: %s\n"), *SelectedIssue->AssetName);
	ClipText += FString::Printf(TEXT("Path: %s\n"), *SelectedIssue->AssetPath);
	FString SevStr = (SelectedIssue->Severity == EBPDoctorSeverity::Error) ? TEXT("ERROR") :
		(SelectedIssue->Severity == EBPDoctorSeverity::Warning) ? TEXT("WARNING") : TEXT("INFO");
	ClipText += FString::Printf(TEXT("Severity: %s\n"), *SevStr);
	if (Check)
	{
		FString ConfStr = (Check->Confidence == EBPDoctorConfidence::High) ? TEXT("HIGH") :
			(Check->Confidence == EBPDoctorConfidence::Medium) ? TEXT("MEDIUM") : TEXT("LOW");
		ClipText += FString::Printf(TEXT("Confidence: %s\n"), *ConfStr);
		ClipText += FString::Printf(TEXT("Name: %s\n"), *Check->Name);
	}
	ClipText += FString::Printf(TEXT("Description: %s\n"), *SelectedIssue->Description);
	if (!SelectedIssue->NodeHint.IsEmpty())
		ClipText += FString::Printf(TEXT("Node: %s\n"), *SelectedIssue->NodeHint);
	if (Check)
		ClipText += FString::Printf(TEXT("Why It Matters: %s\n"), *Check->WhyItMatters);
	ClipText += FString::Printf(TEXT("Auto-fixable: %s\n"), SelectedIssue->bAutoFixable ? TEXT("Yes") : TEXT("No"));
	if (SelectedIssue->bFixed)
		ClipText += TEXT("Status: FIXED\n");

	FPlatformApplicationMisc::ClipboardCopy(*ClipText);
	DetailText->SetText(FText::FromString(TEXT("Issue details copied to clipboard.")));
	return FReply::Handled();
}

FReply SBPDoctorPanel::OnSuppressSelected()
{
	if (!SelectedIssue.IsValid()) return FReply::Handled();

	FString Key = SelectedIssue->CheckCode + TEXT("|") + SelectedIssue->AssetPath;
	FString Code = SelectedIssue->CheckCode;
	FString Asset = SelectedIssue->AssetName;

	if (SuppressedIssueKeys.Contains(Key))
	{
		// Unsuppress
		SuppressedIssueKeys.Remove(Key);
		SaveSettings();
		RefreshFilteredList();
		DetailText->SetText(FText::FromString(FString::Printf(
			TEXT("UNSUPPRESSED: %s in %s\n\nThis issue will appear in normal scan results again."),
			*Code, *Asset)));
	}
	else
	{
		// Suppress
		SuppressedIssueKeys.Add(Key);
		SaveSettings();
		RefreshFilteredList();
		// v2.7.4 audit fix: surface that suppressions persist to a committable file with
		// full /Game/ asset paths. Studios on public/partner repos should review before
		// commit — the suppress file CAN leak WIP asset names. Inline message instead of
		// a modal so it doesn't gate the fast Suppress workflow.
		DetailText->SetText(FText::FromString(FString::Printf(
			TEXT("SUPPRESSED: %s in %s\n\nToggle the 'Suppressed' filter to view and unsuppress.\n\nNote: suppressions persist in Config/BPDoctor.suppress (one line per entry, format: CheckCode|AssetPath). The file is designed to be committed for team-wide policy — review it before pushing if asset names are sensitive."),
			*Code, *Asset)));
	}

	return FReply::Handled();
}

// ─────────────────────────────────────────────────────────────────
//  OPEN IN EDITOR
// ─────────────────────────────────────────────────────────────────

void SBPDoctorPanel::OpenBlueprintInEditor(const FString& AssetPath)
{
	IAssetRegistry& AssetRegistry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();
	FAssetData AssetData = AssetRegistry.GetAssetByObjectPath(FSoftObjectPath(AssetPath));

	UObject* Asset = AssetData.IsValid() ? AssetData.GetAsset() : nullptr;
	if (!Asset)
	{
		Asset = StaticLoadObject(UBlueprint::StaticClass(), nullptr, *AssetPath);
	}

	if (!Asset)
	{
		FString PackagePath = AssetPath;
		int32 DotIndex;
		if (PackagePath.FindLastChar('.', DotIndex))
		{
			PackagePath = PackagePath.Left(DotIndex);
		}
		Asset = StaticLoadObject(UBlueprint::StaticClass(), nullptr, *PackagePath);
	}

	if (Asset && GEditor)
	{
		GEditor->GetEditorSubsystem<UAssetEditorSubsystem>()->OpenEditorForAsset(Asset);
	}
}

// ─────────────────────────────────────────────────────────────────
//  CHECK LIBRARY + ENABLE/DISABLE
// ─────────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────────
//  SETTINGS DIALOG — interactive GUI
// ─────────────────────────────────────────────────────────────────

void SBPDoctorPanel::ShowSettingsDialog()
{
	TSharedRef<SWindow> DialogWindow = SNew(SWindow)
		.Title(LOCTEXT("SettingsWinTitle", "BP Doctor — Settings"))
		.ClientSize(FVector2D(550, 480))
		.SupportsMaximize(false)
		.SupportsMinimize(false)
		.IsTopmostWindow(true);

	TWeakPtr<SWindow> WeakWindow(DialogWindow);

	// Experience mode selection (copy current value for the dialog)
	TSharedPtr<int32> SelectedMode = MakeShared<int32>(static_cast<int32>(ExperienceMode));

	FString SettingsDir = FPaths::ProjectSavedDir() / TEXT("BPDoctor");
	FString CustomRulesPath = SettingsDir / TEXT("CustomRules.json");
	bool bHasCustomRules = FPaths::FileExists(CustomRulesPath);
	int32 NumCustomRules = 0;
	for (const auto& C : FBPDoctorChecks::GetAllChecks()) { if (C.Id >= 100) NumCustomRules++; }

	DialogWindow->SetContent(
		SNew(SBorder)
		.BorderImage(FAppStyle::GetBrush("ToolPanel.DarkGroupBorder"))
		.Padding(16)
		[
			SNew(SScrollBox)
			+ SScrollBox::Slot()
			[
				SNew(SVerticalBox)

				// ── EXPERIENCE MODE ──
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 4)
				[
					SNew(STextBlock)
					.Text(LOCTEXT("ExpModeLabel", "EXPERIENCE MODE"))
					.Font(FCoreStyle::GetDefaultFontStyle("Bold", 12))
					.ColorAndOpacity(FLinearColor(0.f, 0.898f, 1.f))
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 8)
				[
					SNew(STextBlock)
					.Text(LOCTEXT("ExpModeDesc", "Controls how much guidance and detail is shown in the detail panel."))
					.Font(FCoreStyle::GetDefaultFontStyle("Regular", 9))
					.AutoWrapText(true)
				]

				// Radio-style buttons for each mode
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 4)
				[
					SNew(SCheckBox)
					.Style(FCoreStyle::Get(), "RadioButton")
					.IsChecked_Lambda([SelectedMode]() { return *SelectedMode == 0 ? ECheckBoxState::Checked : ECheckBoxState::Unchecked; })
					.OnCheckStateChanged_Lambda([SelectedMode](ECheckBoxState) { *SelectedMode = 0; })
					[
						SNew(SVerticalBox)
						+ SVerticalBox::Slot().AutoHeight()
						[ SNew(STextBlock).Text(LOCTEXT("BegLabel", "Beginner")).Font(FCoreStyle::GetDefaultFontStyle("Bold", 10)) ]
						+ SVerticalBox::Slot().AutoHeight()
						[ SNew(STextBlock).Text(LOCTEXT("BegDesc", "Full guidance: step-by-step fix instructions, beginner tips, why-it-matters explanations, detection method details.")).Font(FCoreStyle::GetDefaultFontStyle("Regular", 9)).AutoWrapText(true) ]
					]
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 4)
				[
					SNew(SCheckBox)
					.Style(FCoreStyle::Get(), "RadioButton")
					.IsChecked_Lambda([SelectedMode]() { return *SelectedMode == 1 ? ECheckBoxState::Checked : ECheckBoxState::Unchecked; })
					.OnCheckStateChanged_Lambda([SelectedMode](ECheckBoxState) { *SelectedMode = 1; })
					[
						SNew(SVerticalBox)
						+ SVerticalBox::Slot().AutoHeight()
						[ SNew(STextBlock).Text(LOCTEXT("IntLabel", "Intermediate")).Font(FCoreStyle::GetDefaultFontStyle("Bold", 10)) ]
						+ SVerticalBox::Slot().AutoHeight()
						[ SNew(STextBlock).Text(LOCTEXT("IntDesc", "Standard: check details, fix instructions, confidence level. No beginner tips.")).Font(FCoreStyle::GetDefaultFontStyle("Regular", 9)).AutoWrapText(true) ]
					]
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 12)
				[
					SNew(SCheckBox)
					.Style(FCoreStyle::Get(), "RadioButton")
					.IsChecked_Lambda([SelectedMode]() { return *SelectedMode == 2 ? ECheckBoxState::Checked : ECheckBoxState::Unchecked; })
					.OnCheckStateChanged_Lambda([SelectedMode](ECheckBoxState) { *SelectedMode = 2; })
					[
						SNew(SVerticalBox)
						+ SVerticalBox::Slot().AutoHeight()
						[ SNew(STextBlock).Text(LOCTEXT("ExpLabel", "Expert")).Font(FCoreStyle::GetDefaultFontStyle("Bold", 10)) ]
						+ SVerticalBox::Slot().AutoHeight()
						[ SNew(STextBlock).Text(LOCTEXT("ExpDesc", "Minimal: one-line compact view. Code, severity, asset, description. No guidance.")).Font(FCoreStyle::GetDefaultFontStyle("Regular", 9)).AutoWrapText(true) ]
					]
				]

				+ SVerticalBox::Slot().AutoHeight().Padding(0, 4) [ SNew(SSeparator) ]

				// ── CHECKS ──
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 8, 0, 4)
				[
					SNew(STextBlock)
					.Text(LOCTEXT("ChecksLabel", "CHECKS"))
					.Font(FCoreStyle::GetDefaultFontStyle("Bold", 12))
					.ColorAndOpacity(FLinearColor(0.f, 0.898f, 1.f))
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 4)
				[
					SNew(STextBlock)
					.Text_Lambda([this, NumCustomRules]()
					{
						// Count checks that are active under the current profile (audit v2.3):
						// previously we showed total 34, which misled users on SilentFailuresOnly.
						const auto& All = FBPDoctorChecks::GetAllChecks();
						int32 Active = 0;
						for (const FBPDoctorCheckDef& C : All)
						{
							if (DisabledChecks.Contains(C.Code)) continue;
							if (C.CustomRule.Type == EBPDoctorRuleType::None
								&& !FBPDoctorChecks::IsTierInProfile(C.Tier, ActiveProfile)) continue;
							Active++;
						}
						return FText::FromString(FString::Printf(
							TEXT("%d active / %d total  |  %d disabled  |  %d custom rules loaded"),
							Active, All.Num(), DisabledChecks.Num(), NumCustomRules));
					})
					.Font(FCoreStyle::GetDefaultFontStyle("Regular", 10))
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 12)
				[
					SNew(SButton)
					.Text(LOCTEXT("ManageChecks", "Manage Checks..."))
					.ToolTipText(LOCTEXT("ManageChecksTip", "Open the Check Library to enable/disable individual checks"))
					.OnClicked_Lambda([this, WeakWindow]() {
						if (auto Pin = WeakWindow.Pin()) Pin->RequestDestroyWindow();
						ShowChecksDialog();
						return FReply::Handled();
					})
				]

				+ SVerticalBox::Slot().AutoHeight().Padding(0, 4) [ SNew(SSeparator) ]

				// ── SUPPRESSION ──
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 8, 0, 4)
				[
					SNew(STextBlock)
					.Text(LOCTEXT("SuppLabel", "SUPPRESSION"))
					.Font(FCoreStyle::GetDefaultFontStyle("Bold", 12))
					.ColorAndOpacity(FLinearColor(0.f, 0.898f, 1.f))
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 4)
				[
					SNew(STextBlock)
					.Text(FText::FromString(FString::Printf(TEXT("%d issues currently suppressed."), SuppressedIssueKeys.Num())))
					.Font(FCoreStyle::GetDefaultFontStyle("Regular", 10))
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 12)
				[
					SNew(SButton)
					.Text(LOCTEXT("ClearAllSupp", "Clear All Suppressions"))
					.IsEnabled(SuppressedIssueKeys.Num() > 0)
					.OnClicked_Lambda([this]() {
						SuppressedIssueKeys.Empty();
						SaveSettings();
						RefreshFilteredList();
						return FReply::Handled();
					})
				]

				+ SVerticalBox::Slot().AutoHeight().Padding(0, 4) [ SNew(SSeparator) ]

				// ── CUSTOM RULES ──
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 8, 0, 4)
				[
					SNew(STextBlock)
					.Text(LOCTEXT("CustomLabel", "CUSTOM RULES"))
					.Font(FCoreStyle::GetDefaultFontStyle("Bold", 12))
					.ColorAndOpacity(FLinearColor(0.f, 0.898f, 1.f))
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 8)
				[
					SNew(STextBlock)
					.Text(FText::FromString(FString::Printf(TEXT("%d custom rules loaded.  |  File: %s"),
						NumCustomRules, bHasCustomRules ? TEXT("Found") : TEXT("Not created yet"))))
					.Font(FCoreStyle::GetDefaultFontStyle("Regular", 10))
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 4)
				[
					SNew(SHorizontalBox)
					+ SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 4, 0)
					[
						SNew(SButton)
						.Text(LOCTEXT("EditRules", "Edit Rules..."))
						.ToolTipText(LOCTEXT("EditRulesTip", "Open the visual custom rules editor"))
						.OnClicked_Lambda([this, WeakWindow]() {
							if (auto Pin = WeakWindow.Pin()) Pin->RequestDestroyWindow();
							ShowCustomRulesEditor();
							return FReply::Handled();
						})
					]
					+ SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 4, 0)
					[
						SNew(SButton)
						.Text(LOCTEXT("ImportRulesBtn", "Import..."))
						.ToolTipText(LOCTEXT("ImportRulesTip", "Import a custom rules JSON file from disk"))
						.OnClicked_Lambda([this]() {
							ImportCustomRules();
							return FReply::Handled();
						})
					]
					+ SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 4, 0)
					[
						SNew(SButton)
						.Text(LOCTEXT("CreateExample", "Create Example"))
						.ToolTipText(LOCTEXT("CreateExampleTip", "Create a starter CustomRules.json with example rules"))
						.IsEnabled(!bHasCustomRules)
						.OnClicked_Lambda([this, CustomRulesPath]() {
							FString ExampleContent = TEXT("{\n  \"rules\": [\n    {\n      \"name\": \"Ban GetAllActorsOfClass\",\n      \"code\": \"CUSTOM_NO_GAA\",\n      \"severity\": \"WARNING\",\n      \"confidence\": \"HIGH\",\n      \"description\": \"GetAllActorsOfClass is expensive at scale.\",\n      \"why_it_matters\": \"Iterates the entire actor list every call.\",\n      \"beginner_tip\": \"Store the result in a variable instead.\",\n      \"type\": \"banned_function\",\n      \"function_name\": \"GetAllActorsOfClass\"\n    }\n  ]\n}");
							FString Dir = FPaths::GetPath(CustomRulesPath);
							IFileManager::Get().MakeDirectory(*Dir, true);
							FFileHelper::SaveStringToFile(ExampleContent, *CustomRulesPath, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
							FMessageDialog::Open(EAppMsgType::Ok, FText::FromString(FString::Printf(TEXT("Example rules created at:\n%s\n\nEdit the file to add your own rules, then re-scan."), *CustomRulesPath)));
							return FReply::Handled();
						})
					]
				]

				+ SVerticalBox::Slot().AutoHeight().Padding(0, 12) [ SNew(SSeparator) ]

				// ── IMPORT / EXPORT SETTINGS ──
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 8, 0, 4)
				[
					SNew(STextBlock)
					.Text(LOCTEXT("IOLabel", "CONFIGURATION"))
					.Font(FCoreStyle::GetDefaultFontStyle("Bold", 12))
					.ColorAndOpacity(FLinearColor(0.f, 0.898f, 1.f))
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 4)
				[
					SNew(STextBlock)
					.Text(LOCTEXT("IODesc", "Import or export your full BP Doctor configuration (experience mode, disabled checks, suppressions) to share across projects or team members."))
					.Font(FCoreStyle::GetDefaultFontStyle("Regular", 9))
					.AutoWrapText(true)
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 4)
				[
					SNew(SHorizontalBox)
					+ SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 4, 0)
					[
						SNew(SButton)
						.Text(LOCTEXT("ImportSettingsBtn", "Import Settings..."))
						.ToolTipText(LOCTEXT("ImportSettingsTip", "Load a Settings.json from another location"))
						.OnClicked_Lambda([this]() { ImportSettings(); return FReply::Handled(); })
					]
					+ SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 4, 0)
					[
						SNew(SButton)
						.Text(LOCTEXT("ExportSettingsBtn", "Export Settings..."))
						.ToolTipText(LOCTEXT("ExportSettingsTip", "Save your current settings to a file for sharing"))
						.OnClicked_Lambda([this]() { ExportSettings(); return FReply::Handled(); })
					]
				]

				+ SVerticalBox::Slot().AutoHeight().Padding(0, 12) [ SNew(SSeparator) ]

				// ── FILE PATHS ──
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 8, 0, 4)
				[
					SNew(STextBlock)
					.Text(LOCTEXT("PathsLabel", "FILE PATHS"))
					.Font(FCoreStyle::GetDefaultFontStyle("Bold", 12))
					.ColorAndOpacity(FLinearColor(0.f, 0.898f, 1.f))
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 12)
				[
					SNew(STextBlock)
					.Text(FText::FromString(FString::Printf(TEXT("Settings: %s/Settings.json\nCustom Rules: %s/CustomRules.json\nBackups: %s/Backups/"),
						*SettingsDir, *SettingsDir, *SettingsDir)))
					.Font(FCoreStyle::GetDefaultFontStyle("Regular", 9))
					.AutoWrapText(true)
				]

				// ── BUTTONS ──
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 8, 0, 0)
				[
					SNew(SHorizontalBox)
					+ SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 8, 0)
					[
						SNew(SButton)
						.Text(LOCTEXT("SaveSettings", "Save & Close"))
						.OnClicked_Lambda([this, SelectedMode, WeakWindow]() {
							ExperienceMode = static_cast<EBPDoctorExperienceMode>(*SelectedMode);
							SaveSettings();
							if (SelectedIssue.IsValid())
								OnSelectionChanged(SelectedIssue, ESelectInfo::Direct);
							if (auto Pin = WeakWindow.Pin()) Pin->RequestDestroyWindow();
							return FReply::Handled();
						})
					]
					+ SHorizontalBox::Slot().FillWidth(1.f) [ SNew(SSpacer) ]
					+ SHorizontalBox::Slot().AutoWidth()
					[
						SNew(SButton)
						.Text(LOCTEXT("CancelSettings", "Cancel"))
						.OnClicked_Lambda([WeakWindow]() {
							if (auto Pin = WeakWindow.Pin()) Pin->RequestDestroyWindow();
							return FReply::Handled();
						})
					]
				]
			]
		]
	);

	FSlateApplication::Get().AddModalWindow(DialogWindow, TSharedPtr<const SWidget>());
}

// ─────────────────────────────────────────────────────────────────
//  CUSTOM RULES EDITOR GUI
// ─────────────────────────────────────────────────────────────────

void SBPDoctorPanel::ShowCustomRulesEditor()
{
	FString RulesPath = FPaths::ProjectSavedDir() / TEXT("BPDoctor") / TEXT("CustomRules.json");

	// Load existing rules into editable structures
	struct FEditableRule
	{
		TSharedPtr<FString> Name, Code, Description, Type, MatchStr, Severity;
		TSharedPtr<int32> MaxCount;
		TSharedPtr<bool> bAnimBPOnly;
	};

	TArray<TSharedPtr<FEditableRule>> Rules;

	// Parse existing file
	FString JsonStr;
	if (FFileHelper::LoadFileToString(JsonStr, *RulesPath))
	{
		TSharedPtr<FJsonObject> Root;
		TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(JsonStr);
		if (FJsonSerializer::Deserialize(Reader, Root) && Root.IsValid())
		{
			const TArray<TSharedPtr<FJsonValue>>* Arr;
			if (Root->TryGetArrayField(TEXT("rules"), Arr))
			{
				for (const auto& V : *Arr)
				{
					const TSharedPtr<FJsonObject>* Obj;
					if (!V->TryGetObject(Obj)) continue;
					TSharedPtr<FEditableRule> R = MakeShared<FEditableRule>();
					// v2.7.4 audit fix: TryGetStringField (not GetStringField) so a malformed
					// CustomRules.json missing required keys silently produces a default-valued rule
					// in the editor instead of asserting/crashing the editor on the next dialog open.
					// Mirrors the LoadCustomRules robustness fix from v2.7.3 — this is the editor
					// dialog re-parsing the same file that was hardened in the runtime path.
					FString N, C, D, T, S, M;
					(*Obj)->TryGetStringField(TEXT("name"), N);          R->Name = MakeShared<FString>(N);
					(*Obj)->TryGetStringField(TEXT("code"), C);          R->Code = MakeShared<FString>(C);
					(*Obj)->TryGetStringField(TEXT("description"), D);   R->Description = MakeShared<FString>(D);
					(*Obj)->TryGetStringField(TEXT("type"), T);          R->Type = MakeShared<FString>(T);
					(*Obj)->TryGetStringField(TEXT("severity"), S);      R->Severity = MakeShared<FString>(S);
					if (!(*Obj)->TryGetStringField(TEXT("function_name"), M))
					{
						(*Obj)->TryGetStringField(TEXT("node_class_contains"), M);
					}
					R->MatchStr = MakeShared<FString>(M);
					int32 MaxCt = 3;
					(*Obj)->TryGetNumberField(TEXT("max_count"), MaxCt);
					R->MaxCount = MakeShared<int32>(MaxCt);
					bool bAnim = false; (*Obj)->TryGetBoolField(TEXT("animBP_only"), bAnim);
					R->bAnimBPOnly = MakeShared<bool>(bAnim);
					Rules.Add(R);
				}
			}
		}
	}

	TSharedPtr<bool> bSaved = MakeShared<bool>(false);

	TSharedRef<SWindow> Win = SNew(SWindow)
		.Title(LOCTEXT("RulesEdTitle", "BP Doctor — Custom Rules Editor"))
		.ClientSize(FVector2D(700, 520))
		.SupportsMaximize(false).SupportsMinimize(false).IsTopmostWindow(true);
	TWeakPtr<SWindow> WW(Win);

	TSharedRef<SScrollBox> RulesList = SNew(SScrollBox);

	// Use shared ptr so lambda captures are safe even if stack unwinds
	TSharedRef<TArray<TSharedPtr<FEditableRule>>> RulesRef = MakeShared<TArray<TSharedPtr<FEditableRule>>>(Rules);
	auto RebuildList = [RulesList, RulesRef]()
	{
		RulesList->ClearChildren();
		for (int32 i = 0; i < RulesRef->Num(); ++i)
		{
			TSharedPtr<FEditableRule> R = (*RulesRef)[i];
			RulesList->AddSlot().Padding(4, 4)
			[
				SNew(SBorder)
				.BorderImage(FAppStyle::GetBrush("ToolPanel.DarkGroupBorder"))
				.Padding(8)
				[
					SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight()
					[
						SNew(SHorizontalBox)
						+ SHorizontalBox::Slot().AutoWidth().Padding(0,0,8,0)
						[ SNew(STextBlock).Text(FText::FromString(*R->Code)).Font(FCoreStyle::GetDefaultFontStyle("Bold", 11)).ColorAndOpacity(FLinearColor(0.f, 0.898f, 1.f)) ]
						+ SHorizontalBox::Slot().FillWidth(1.f)
						[ SNew(STextBlock).Text(FText::FromString(*R->Name)).Font(FCoreStyle::GetDefaultFontStyle("Regular", 10)) ]
						+ SHorizontalBox::Slot().AutoWidth()
						[ SNew(STextBlock).Text(FText::FromString(*R->Severity)).Font(FCoreStyle::GetDefaultFontStyle("Bold", 9)) ]
					]
					+ SVerticalBox::Slot().AutoHeight().Padding(0,4,0,0)
					[ SNew(STextBlock).Text(FText::FromString(FString::Printf(TEXT("Type: %s  |  Match: %s"), **R->Type, **R->MatchStr)))
						.Font(FCoreStyle::GetDefaultFontStyle("Regular", 9)).ColorAndOpacity(FLinearColor(0.5f,0.5f,0.6f)) ]
				]
			];
		}
	};
	RebuildList();

	// Type options for dropdown
	TArray<TSharedPtr<FString>> TypeOptions;
	TypeOptions.Add(MakeShared<FString>(TEXT("banned_function")));
	TypeOptions.Add(MakeShared<FString>(TEXT("banned_node")));
	TypeOptions.Add(MakeShared<FString>(TEXT("required_node")));
	TypeOptions.Add(MakeShared<FString>(TEXT("node_limit")));

	TArray<TSharedPtr<FString>> SevOptions;
	SevOptions.Add(MakeShared<FString>(TEXT("ERROR")));
	SevOptions.Add(MakeShared<FString>(TEXT("WARNING")));
	SevOptions.Add(MakeShared<FString>(TEXT("INFO")));

	// New rule form fields
	TSharedPtr<FString> NewName = MakeShared<FString>(TEXT("My Custom Check"));
	TSharedPtr<FString> NewCode = MakeShared<FString>(TEXT("CUSTOM_NEW"));
	TSharedPtr<FString> NewDesc = MakeShared<FString>(TEXT("Description of what this check finds."));
	TSharedPtr<FString> NewType = MakeShared<FString>(TEXT("banned_function"));
	TSharedPtr<FString> NewSev = MakeShared<FString>(TEXT("WARNING"));
	TSharedPtr<FString> NewMatch = MakeShared<FString>(TEXT("FunctionName"));
	TSharedPtr<int32> NewMax = MakeShared<int32>(3);

	Win->SetContent(
		SNew(SBorder).BorderImage(FAppStyle::GetBrush("ToolPanel.DarkGroupBorder")).Padding(16)
		[
			SNew(SVerticalBox)

			+ SVerticalBox::Slot().AutoHeight().Padding(0,0,0,8)
			[ SNew(STextBlock).Text(FText::FromString(FString::Printf(TEXT("%d custom rules loaded. Edit below or add new ones."), RulesRef->Num())))
				.Font(FCoreStyle::GetDefaultFontStyle("Regular", 10)) ]

			// Current rules list
			+ SVerticalBox::Slot().FillHeight(0.4f).Padding(0,0,0,4)
			[ RulesList ]

			+ SVerticalBox::Slot().AutoHeight().Padding(0,4)
			[
				SNew(SButton).Text(LOCTEXT("DeleteLast", "Delete Last Rule"))
				.OnClicked_Lambda([RulesRef, RebuildList]() {
					if (RulesRef->Num() > 0) { RulesRef->RemoveAt(RulesRef->Num()-1); RebuildList(); }
					return FReply::Handled();
				})
			]

			+ SVerticalBox::Slot().AutoHeight().Padding(0,8) [ SNew(SSeparator) ]

			// ── ADD NEW RULE form ──
			+ SVerticalBox::Slot().AutoHeight().Padding(0,4,0,4)
			[ SNew(STextBlock).Text(LOCTEXT("AddNewLabel", "ADD NEW RULE")).Font(FCoreStyle::GetDefaultFontStyle("Bold", 11)).ColorAndOpacity(FLinearColor(0.f, 0.898f, 1.f)) ]

			+ SVerticalBox::Slot().AutoHeight().Padding(0,2)
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().FillWidth(0.5f).Padding(0,0,4,0)
				[ SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight() [ SNew(STextBlock).Text(LOCTEXT("RuleName","Name:")).Font(FCoreStyle::GetDefaultFontStyle("Regular",9)) ]
					+ SVerticalBox::Slot().AutoHeight() [ SNew(SEditableTextBox).Text(FText::FromString(*NewName)).OnTextChanged_Lambda([NewName](const FText& T){ *NewName = T.ToString(); }) ]
				]
				+ SHorizontalBox::Slot().FillWidth(0.5f)
				[ SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight() [ SNew(STextBlock).Text(LOCTEXT("RuleCode","Code:")).Font(FCoreStyle::GetDefaultFontStyle("Regular",9)) ]
					+ SVerticalBox::Slot().AutoHeight() [ SNew(SEditableTextBox).Text(FText::FromString(*NewCode)).OnTextChanged_Lambda([NewCode](const FText& T){ *NewCode = T.ToString(); }) ]
				]
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(0,2)
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().FillWidth(0.33f).Padding(0,0,4,0)
				[ SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight() [ SNew(STextBlock).Text(LOCTEXT("RuleType","Type:")).Font(FCoreStyle::GetDefaultFontStyle("Regular",9)) ]
					+ SVerticalBox::Slot().AutoHeight() [ SNew(STextComboBox).OptionsSource(&TypeOptions).InitiallySelectedItem(TypeOptions[0])
						.OnSelectionChanged_Lambda([NewType](TSharedPtr<FString> V, ESelectInfo::Type){ if(V.IsValid()) *NewType = *V; }) ]
				]
				+ SHorizontalBox::Slot().FillWidth(0.33f).Padding(0,0,4,0)
				[ SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight() [ SNew(STextBlock).Text(LOCTEXT("RuleSev","Severity:")).Font(FCoreStyle::GetDefaultFontStyle("Regular",9)) ]
					+ SVerticalBox::Slot().AutoHeight() [ SNew(STextComboBox).OptionsSource(&SevOptions).InitiallySelectedItem(SevOptions[1])
						.OnSelectionChanged_Lambda([NewSev](TSharedPtr<FString> V, ESelectInfo::Type){ if(V.IsValid()) *NewSev = *V; }) ]
				]
				+ SHorizontalBox::Slot().FillWidth(0.33f)
				[ SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight() [ SNew(STextBlock).Text(LOCTEXT("RuleMatch","Match (function/node name):")).Font(FCoreStyle::GetDefaultFontStyle("Regular",9)) ]
					+ SVerticalBox::Slot().AutoHeight() [ SNew(SEditableTextBox).Text(FText::FromString(*NewMatch)).OnTextChanged_Lambda([NewMatch](const FText& T){ *NewMatch = T.ToString(); }) ]
				]
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(0,2)
			[ SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight() [ SNew(STextBlock).Text(LOCTEXT("RuleDesc","Description:")).Font(FCoreStyle::GetDefaultFontStyle("Regular",9)) ]
				+ SVerticalBox::Slot().AutoHeight() [ SNew(SEditableTextBox).Text(FText::FromString(*NewDesc)).OnTextChanged_Lambda([NewDesc](const FText& T){ *NewDesc = T.ToString(); }) ]
			]

			+ SVerticalBox::Slot().AutoHeight().Padding(0,8,0,0)
			[
				SNew(SButton).Text(LOCTEXT("AddRuleBtn", "Add Rule"))
				.OnClicked_Lambda([RulesRef, RebuildList, NewName, NewCode, NewDesc, NewType, NewSev, NewMatch, NewMax]() {
					auto& Rules = *RulesRef; // Alias for readability
					TSharedPtr<FEditableRule> R = MakeShared<FEditableRule>();
					R->Name = MakeShared<FString>(*NewName);
					R->Code = MakeShared<FString>(*NewCode);
					R->Description = MakeShared<FString>(*NewDesc);
					R->Type = MakeShared<FString>(*NewType);
					R->Severity = MakeShared<FString>(*NewSev);
					R->MatchStr = MakeShared<FString>(*NewMatch);
					R->MaxCount = MakeShared<int32>(*NewMax);
					R->bAnimBPOnly = MakeShared<bool>(false);
					Rules.Add(R);
					RebuildList();
					return FReply::Handled();
				})
			]

			+ SVerticalBox::Slot().AutoHeight().Padding(0,12,0,0)
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().AutoWidth().Padding(0,0,8,0)
				[ SNew(SButton).Text(LOCTEXT("SaveRules", "Save & Close"))
					.OnClicked_Lambda([bSaved, WW]() { *bSaved = true; if(auto P=WW.Pin()) P->RequestDestroyWindow(); return FReply::Handled(); }) ]
				+ SHorizontalBox::Slot().FillWidth(1.f) [ SNew(SSpacer) ]
				+ SHorizontalBox::Slot().AutoWidth()
				[ SNew(SButton).Text(LOCTEXT("CancelRules", "Cancel"))
					.OnClicked_Lambda([WW]() { if(auto P=WW.Pin()) P->RequestDestroyWindow(); return FReply::Handled(); }) ]
			]
		]
	);

	FSlateApplication::Get().AddModalWindow(Win, TSharedPtr<const SWidget>());

	if (!*bSaved) return;

	// Serialize rules back to JSON
	TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
	TArray<TSharedPtr<FJsonValue>> Arr;
	for (const auto& R : *RulesRef)
	{
		TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
		Obj->SetStringField(TEXT("name"), *R->Name);
		Obj->SetStringField(TEXT("code"), *R->Code);
		Obj->SetStringField(TEXT("description"), *R->Description);
		Obj->SetStringField(TEXT("severity"), *R->Severity);
		Obj->SetStringField(TEXT("confidence"), TEXT("HIGH"));
		Obj->SetStringField(TEXT("why_it_matters"), TEXT(""));
		Obj->SetStringField(TEXT("beginner_tip"), TEXT(""));
		Obj->SetStringField(TEXT("type"), *R->Type);
		if (*R->Type == TEXT("banned_function"))
			Obj->SetStringField(TEXT("function_name"), *R->MatchStr);
		else
			Obj->SetStringField(TEXT("node_class_contains"), *R->MatchStr);
		if (*R->Type == TEXT("node_limit"))
			Obj->SetNumberField(TEXT("max_count"), *R->MaxCount);
		if (*R->bAnimBPOnly)
			Obj->SetBoolField(TEXT("animBP_only"), true);
		Arr.Add(MakeShared<FJsonValueObject>(Obj));
	}
	Root->SetArrayField(TEXT("rules"), Arr);

	FString Out;
	TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer =
		TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&Out);
	FJsonSerializer::Serialize(Root, Writer);

	FString Dir = FPaths::GetPath(RulesPath);
	IFileManager::Get().MakeDirectory(*Dir, true);
	FFileHelper::SaveStringToFile(Out, *RulesPath, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}

void SBPDoctorPanel::ImportCustomRules()
{
	TArray<FString> Files;
	IDesktopPlatform* DP = FDesktopPlatformModule::Get();
	if (!DP) return;
	DP->OpenFileDialog(
		FSlateApplication::Get().FindBestParentWindowHandleForDialogs(nullptr),
		TEXT("Import Custom Rules"), FPaths::ProjectDir(),
		TEXT(""), TEXT("JSON (*.json)|*.json"), 0, Files);
	if (Files.Num() == 0) return;

	FString DestPath = FPaths::ProjectSavedDir() / TEXT("BPDoctor") / TEXT("CustomRules.json");
	FString Dir = FPaths::GetPath(DestPath);
	IFileManager::Get().MakeDirectory(*Dir, true);
	IFileManager::Get().Copy(*DestPath, *Files[0], true);
	FMessageDialog::Open(EAppMsgType::Ok, FText::FromString(FString::Printf(
		TEXT("Custom rules imported to:\n%s\n\nRe-scan to apply new rules."), *DestPath)));
}

void SBPDoctorPanel::ExportSettings()
{
	// Save current settings first
	SaveSettings();

	TArray<FString> Files;
	IDesktopPlatform* DP = FDesktopPlatformModule::Get();
	if (!DP) return;
	DP->SaveFileDialog(
		FSlateApplication::Get().FindBestParentWindowHandleForDialogs(nullptr),
		TEXT("Export BP Doctor Settings"), FPaths::ProjectDir(),
		TEXT("BPDoctor_Settings.json"), TEXT("JSON (*.json)|*.json"), 0, Files);
	if (Files.Num() == 0) return;

	FString SourcePath = FPaths::ProjectSavedDir() / TEXT("BPDoctor") / TEXT("Settings.json");
	IFileManager::Get().Copy(*Files[0], *SourcePath, true);
}

void SBPDoctorPanel::ImportSettings()
{
	TArray<FString> Files;
	IDesktopPlatform* DP = FDesktopPlatformModule::Get();
	if (!DP) return;
	DP->OpenFileDialog(
		FSlateApplication::Get().FindBestParentWindowHandleForDialogs(nullptr),
		TEXT("Import BP Doctor Settings"), FPaths::ProjectDir(),
		TEXT(""), TEXT("JSON (*.json)|*.json"), 0, Files);
	if (Files.Num() == 0) return;

	FString DestPath = FPaths::ProjectSavedDir() / TEXT("BPDoctor") / TEXT("Settings.json");
	FString Dir = FPaths::GetPath(DestPath);
	IFileManager::Get().MakeDirectory(*Dir, true);
	IFileManager::Get().Copy(*DestPath, *Files[0], true);
	LoadSettings();
	FMessageDialog::Open(EAppMsgType::Ok, LOCTEXT("ImportedSettings", "Settings imported successfully. Changes applied."));
}

void SBPDoctorPanel::ShowChecksDialog()
{
	const TArray<FBPDoctorCheckDef>& AllDefs = FBPDoctorChecks::GetAllChecks();

	// Track enabled state per check (shared pointers for lambda capture)
	TArray<TSharedPtr<bool>> EnabledStates;
	for (const FBPDoctorCheckDef& Def : AllDefs)
	{
		EnabledStates.Add(MakeShared<bool>(!DisabledChecks.Contains(Def.Code)));
	}

	TSharedRef<SWindow> DialogWindow = SNew(SWindow)
		.Title(FText::Format(
			LOCTEXT("ChecksTitleFmt", "BP Doctor - Check Library ({0} Checks)"),
			FText::AsNumber(AllDefs.Num())))
		.ClientSize(FVector2D(750, 560))
		.SupportsMaximize(false)
		.SupportsMinimize(false)
		.IsTopmostWindow(true);

	TWeakPtr<SWindow> WeakWindow(DialogWindow);
	TSharedPtr<bool> bSaved = MakeShared<bool>(false);

	// Build scrollable check list
	TSharedRef<SScrollBox> CheckList = SNew(SScrollBox);

	for (int32 i = 0; i < AllDefs.Num(); ++i)
	{
		const FBPDoctorCheckDef& Def = AllDefs[i];
		TSharedPtr<bool> bEnabled = EnabledStates[i];

		FString SevStr = (Def.Severity == EBPDoctorSeverity::Error) ? TEXT("ERROR") :
			(Def.Severity == EBPDoctorSeverity::Warning) ? TEXT("WARN") : TEXT("INFO");
		FLinearColor SevColor = (Def.Severity == EBPDoctorSeverity::Error)
			? FLinearColor(1.f, 0.09f, 0.27f)
			: (Def.Severity == EBPDoctorSeverity::Warning)
				? FLinearColor(1.f, 0.843f, 0.251f) : FLinearColor(0.f, 0.898f, 1.f);
		FString ConfStr = (Def.Confidence == EBPDoctorConfidence::High) ? TEXT("HIGH") :
			(Def.Confidence == EBPDoctorConfidence::Medium) ? TEXT("MED") : TEXT("LOW");
		// Check-type column: 1-12 + 27-39 are AnimBP checks; 13-26 are general BP.
		// v2.7.4 audit fix: extended range to include Phase D checks (#35-#39); previously
		// they fell outside both ranges and were misclassified as "BP" in the toggle dialog.
		FString TypeStr = (Def.Id <= 12 || (Def.Id >= 27 && Def.Id <= 39)) ? TEXT("AnimBP") : TEXT("BP");
		FString FixStr = Def.bAutoFixable ? TEXT("Yes") : TEXT("No");

		CheckList->AddSlot()
		.Padding(4, 3)
		[
			SNew(SCheckBox)
			.IsChecked_Lambda([bEnabled]() { return *bEnabled ? ECheckBoxState::Checked : ECheckBoxState::Unchecked; })
			.OnCheckStateChanged_Lambda([bEnabled](ECheckBoxState S) { *bEnabled = (S == ECheckBoxState::Checked); })
			[
				SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(SHorizontalBox)
					+ SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 8, 0)
					[
						SNew(STextBlock)
						.Text(FText::FromString(FString::Printf(TEXT("#%d %s"), Def.Id, *Def.Code)))
						.Font(FCoreStyle::GetDefaultFontStyle("Bold", 10))
						.ColorAndOpacity(SevColor)
					]
					+ SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 8, 0)
					[
						SNew(STextBlock)
						.Text(FText::FromString(Def.Name))
						.Font(FCoreStyle::GetDefaultFontStyle("Regular", 10))
					]
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 2, 0, 0)
				[
					SNew(SHorizontalBox)
					+ SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 12, 0)
					[ SNew(STextBlock).Text(FText::FromString(SevStr))
						.Font(FCoreStyle::GetDefaultFontStyle("Bold", 8)).ColorAndOpacity(SevColor) ]
					+ SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 12, 0)
					[ SNew(STextBlock).Text(FText::FromString(FString::Printf(TEXT("Conf: %s"), *ConfStr)))
						.Font(FCoreStyle::GetDefaultFontStyle("Regular", 8)) ]
					+ SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 12, 0)
					[ SNew(STextBlock).Text(FText::FromString(TypeStr))
						.Font(FCoreStyle::GetDefaultFontStyle("Regular", 8)) ]
					+ SHorizontalBox::Slot().AutoWidth()
					[ SNew(STextBlock).Text(FText::FromString(FString::Printf(TEXT("Fix: %s"), *FixStr)))
						.Font(FCoreStyle::GetDefaultFontStyle("Regular", 8)) ]
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 2, 0, 0)
				[
					SNew(STextBlock)
					.Text(FText::FromString(Def.Description))
					.Font(FCoreStyle::GetDefaultFontStyle("Regular", 9))
					.ColorAndOpacity(FLinearColor(0.6f, 0.6f, 0.7f))
					.AutoWrapText(true)
				]
			]
		];
	}

	DialogWindow->SetContent(
		SNew(SBorder)
		.BorderImage(FAppStyle::GetBrush("ToolPanel.DarkGroupBorder"))
		.Padding(16)
		[
			SNew(SVerticalBox)

			+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 8)
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().FillWidth(1.f)
				[
					SNew(STextBlock)
					.Text(LOCTEXT("ChecksHeader", "Enable or disable checks. Disabled checks are skipped during scan."))
					.Font(FCoreStyle::GetDefaultFontStyle("Regular", 10))
					.AutoWrapText(true)
				]
				+ SHorizontalBox::Slot().AutoWidth().Padding(8, 0, 4, 0)
				[
					SNew(SButton).Text(LOCTEXT("EnableAll", "Enable All"))
					.OnClicked_Lambda([EnabledStates]() {
						for (auto& S : EnabledStates) *S = true;
						return FReply::Handled();
					})
				]
				+ SHorizontalBox::Slot().AutoWidth()
				[
					SNew(SButton).Text(LOCTEXT("DisableAll", "Disable All"))
					.OnClicked_Lambda([EnabledStates]() {
						for (auto& S : EnabledStates) *S = false;
						return FReply::Handled();
					})
				]
			]

			+ SVerticalBox::Slot().AutoHeight().Padding(0, 4)
			[ SNew(SSeparator) ]

			+ SVerticalBox::Slot().FillHeight(1.f).Padding(0, 4)
			[ CheckList ]

			+ SVerticalBox::Slot().AutoHeight().Padding(0, 8, 0, 0)
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 8, 0)
				[
					SNew(SButton).Text(LOCTEXT("SaveChecks", "Save"))
					.ToolTipText(LOCTEXT("SaveChecksTip", "Save check settings and close"))
					.OnClicked_Lambda([bSaved, WeakWindow]() {
						*bSaved = true;
						if (auto Pin = WeakWindow.Pin()) Pin->RequestDestroyWindow();
						return FReply::Handled();
					})
				]
				+ SHorizontalBox::Slot().FillWidth(1.f) [ SNew(SSpacer) ]
				+ SHorizontalBox::Slot().AutoWidth()
				[
					SNew(SButton).Text(LOCTEXT("CancelChecks", "Cancel"))
					.OnClicked_Lambda([WeakWindow]() {
						if (auto Pin = WeakWindow.Pin()) Pin->RequestDestroyWindow();
						return FReply::Handled();
					})
				]
			]
		]
	);

	FSlateApplication::Get().AddModalWindow(DialogWindow, TSharedPtr<const SWidget>());

	if (*bSaved)
	{
		DisabledChecks.Empty();
		for (int32 i = 0; i < AllDefs.Num(); ++i)
		{
			if (!*EnabledStates[i])
			{
				DisabledChecks.Add(AllDefs[i].Code);
			}
		}
		SaveSettings();
	}
}

// ─────────────────────────────────────────────────────────────────
//  HTML REPORT EXPORT
// ─────────────────────────────────────────────────────────────────

static FString HtmlEscape(const FString& In)
{
	FString Out = In;
	Out.ReplaceInline(TEXT("&"), TEXT("&amp;"));
	Out.ReplaceInline(TEXT("<"), TEXT("&lt;"));
	Out.ReplaceInline(TEXT(">"), TEXT("&gt;"));
	Out.ReplaceInline(TEXT("\""), TEXT("&quot;"));
	return Out;
}

FReply SBPDoctorPanel::OnExportHTMLReport()
{
	FString H;
	H += TEXT("<!DOCTYPE html>\n<html><head>\n<meta charset=\"utf-8\">\n");
	H += TEXT("<title>BP Doctor Scan Report</title>\n<style>\n");
	H += TEXT("body{background:#0d1117;color:#c9d1d9;font-family:'Segoe UI',sans-serif;margin:40px}\n");
	H += TEXT("h1{color:#00e5ff}h2{color:#88aacc;border-bottom:1px solid #333;padding-bottom:4px}\n");
	H += TEXT(".grade{font-size:48px;font-weight:bold}\n");
	H += TEXT(".ga{color:#00e676}.gb{color:#ffd740}.gc{color:#ff9100}.gd,.gf{color:#ff1744}\n");
	H += TEXT("table{width:100%;border-collapse:collapse;margin:16px 0}\n");
	H += TEXT("th{background:#161b22;padding:8px;text-align:left;border-bottom:2px solid #333}\n");
	H += TEXT("td{padding:6px 8px;border-bottom:1px solid #222}\n");
	H += TEXT(".err{color:#ff1744}.wrn{color:#ffd740}.inf{color:#00e5ff}\n");
	H += TEXT(".hi{color:#00e676}.med{color:#ffd740}.lo{color:#ff9100}\n");
	H += TEXT(".fx{color:#00e676;font-weight:bold}\n");
	H += TEXT("</style>\n</head><body>\n");

	H += TEXT("<h1>BP Doctor Scan Report</h1>\n");
	H += FString::Printf(TEXT("<p>Generated: %s</p>\n"), *FDateTime::Now().ToString());

	FString GC = HealthGrade.StartsWith(TEXT("A")) ? TEXT("ga") :
		HealthGrade.StartsWith(TEXT("B")) ? TEXT("gb") :
		HealthGrade == TEXT("C") ? TEXT("gc") : TEXT("gd");
	H += FString::Printf(TEXT("<div class=\"grade %s\">%s</div>\n"), *GC, *HealthGrade);
	H += FString::Printf(TEXT("<p>Scanned: %d | Errors: %d | Warnings: %d | Info: %d | Auto-fixable: %d</p>\n"),
		TotalScanned, TotalErrors, TotalWarnings, TotalInfos, TotalAutoFixable);

	H += TEXT("<table><tr><th>Sev</th><th>Conf</th><th>Check</th><th>Type</th><th>Asset</th><th>Description</th><th>Fix</th></tr>\n");

	for (const FBPDoctorAssetInfo& Info : AllResults)
	{
		for (const FBPDoctorResult& Issue : Info.Issues)
		{
			FString SC = (Issue.Severity == EBPDoctorSeverity::Error) ? TEXT("err") :
				(Issue.Severity == EBPDoctorSeverity::Warning) ? TEXT("wrn") : TEXT("inf");
			FString ST = (Issue.Severity == EBPDoctorSeverity::Error) ? TEXT("ERROR") :
				(Issue.Severity == EBPDoctorSeverity::Warning) ? TEXT("WARN") : TEXT("INFO");

			const FBPDoctorCheckDef* CD = FBPDoctorChecks::FindCheck(Issue.CheckCode);
			FString CC = TEXT("med"); FString CT = TEXT("MED");
			if (CD)
			{
				if (CD->Confidence == EBPDoctorConfidence::High) { CC = TEXT("hi"); CT = TEXT("HIGH"); }
				else if (CD->Confidence == EBPDoctorConfidence::Low) { CC = TEXT("lo"); CT = TEXT("LOW"); }
			}
			FString TT = (Issue.AssetType == EBPDoctorAssetType::AnimBP) ? TEXT("AnimBP") : TEXT("BP");
			FString FT = Issue.bFixed ? TEXT("<span class=\"fx\">FIXED</span>") :
				(Issue.bAutoFixable ? TEXT("Yes") : TEXT("-"));

			H += FString::Printf(TEXT("<tr><td class=\"%s\">%s</td><td class=\"%s\">%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>\n"),
				*SC, *ST, *CC, *CT, *HtmlEscape(Issue.CheckCode), *TT, *HtmlEscape(Issue.AssetName), *HtmlEscape(Issue.Description), *FT);
		}
	}
	H += TEXT("</table>\n");

	// Per-asset detail with why-it-matters
	for (const FBPDoctorAssetInfo& Info : AllResults)
	{
		if (Info.Issues.Num() == 0) continue;
		H += FString::Printf(TEXT("<h2>%s [%s]</h2>\n"), *Info.Name, *Info.Grade);
		for (const FBPDoctorResult& Issue : Info.Issues)
		{
			FString SC = (Issue.Severity == EBPDoctorSeverity::Error) ? TEXT("err") :
				(Issue.Severity == EBPDoctorSeverity::Warning) ? TEXT("wrn") : TEXT("inf");
			H += FString::Printf(TEXT("<p><span class=\"%s\"><b>%s</b></span> %s</p>\n"),
				*SC, *Issue.CheckCode, *Issue.Description);
			if (!Issue.NodeHint.IsEmpty())
				H += FString::Printf(TEXT("<p style=\"color:#666;margin-left:20px\">%s</p>\n"), *HtmlEscape(Issue.NodeHint));

			const FBPDoctorCheckDef* CD = FBPDoctorChecks::FindCheck(Issue.CheckCode);
			if (CD && !CD->WhyItMatters.IsEmpty())
				H += FString::Printf(TEXT("<p style=\"color:#88aacc;margin-left:20px\"><i>Why: %s</i></p>\n"), *HtmlEscape(CD->WhyItMatters));
		}
	}

	H += TEXT("<hr><p style=\"color:#555\">Generated by BP Doctor — Blueprint Diagnostics &amp; Auto-Fix</p>\n");
	H += TEXT("</body></html>\n");

	TArray<FString> OutFiles;
	IDesktopPlatform* DP = FDesktopPlatformModule::Get();
	if (DP)
	{
		DP->SaveFileDialog(
			FSlateApplication::Get().FindBestParentWindowHandleForDialogs(nullptr),
			TEXT("Export HTML Report"), FPaths::ProjectDir(),
			TEXT("BPDoctor_Report.html"), TEXT("HTML (*.html)|*.html"),
			0, OutFiles);
		if (OutFiles.Num() > 0)
			FFileHelper::SaveStringToFile(H, *OutFiles[0], FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
	}
	return FReply::Handled();
}

// ─────────────────────────────────────────────────────────────────
//  SETTINGS PERSISTENCE
// ─────────────────────────────────────────────────────────────────

// Sprint 5 Phase B P7: committable suppression file. The JSON in Saved/ is per-dev
// (gitignored by default UE projects), so a team of 5 can't share suppressions there.
// Config/BPDoctor.suppress is project-relative and committable — once a dev marks
// "BP_COMPLEXITY on BP_PlayerCharacter is intentional", every other dev gets the same
// suppression on next pull instead of re-marking it after fresh clone.
//
// Format: one `CheckCode|/Game/Path/Asset` per line. Lines starting with # are comments.
// Load merges into the live SuppressedIssueKeys set alongside the per-dev JSON entries
// — committed wins on conflict, but neither overrides the other. Save writes both files.

namespace
{
	FString BPDoctor_GetSuppressFilePath()
	{
		return FPaths::ProjectConfigDir() / TEXT("BPDoctor.suppress");
	}

	void BPDoctor_LoadSuppressFile(TSet<FString>& OutKeys)
	{
		const FString FilePath = BPDoctor_GetSuppressFilePath();
		if (!IFileManager::Get().FileExists(*FilePath)) return;

		TArray<FString> Lines;
		if (!FFileHelper::LoadFileToStringArray(Lines, *FilePath)) return;

		for (FString& Line : Lines)
		{
			Line.TrimStartAndEndInline();
			if (Line.IsEmpty() || Line.StartsWith(TEXT("#"))) continue;
			OutKeys.Add(Line);
		}
	}

	void BPDoctor_SaveSuppressFile(const TSet<FString>& Keys)
	{
		const FString FilePath = BPDoctor_GetSuppressFilePath();

		// Always write — even on empty set — so the file's presence signals
		// "team has decided to track suppressions here" rather than silently absent.
		TArray<FString> Lines;
		Lines.Add(TEXT("# BPDoctor suppression list"));
		Lines.Add(TEXT("# Commit this file to source control to share suppressions across the team."));
		Lines.Add(TEXT("# Format: CheckCode|/Game/Path/Asset    (one per line)"));
		Lines.Add(TEXT("# Lines starting with # are ignored. Edit by hand or via the BPDoctor panel."));
		Lines.Add(TEXT(""));

		TArray<FString> Sorted = Keys.Array();
		Sorted.Sort();
		Lines.Append(Sorted);

		FFileHelper::SaveStringArrayToFile(Lines, *FilePath,
			FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
	}
}

void SBPDoctorPanel::SaveSettings()
{
	TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();

	TArray<TSharedPtr<FJsonValue>> DisArr;
	for (const FString& Code : DisabledChecks)
		DisArr.Add(MakeShared<FJsonValueString>(Code));
	Root->SetArrayField(TEXT("disabled_checks"), DisArr);

	FString ModeStr = (ExperienceMode == EBPDoctorExperienceMode::Beginner) ? TEXT("beginner") :
		(ExperienceMode == EBPDoctorExperienceMode::Expert) ? TEXT("expert") : TEXT("intermediate");
	Root->SetStringField(TEXT("experience_mode"), ModeStr);

	FString ProfStr = (ActiveProfile == EBPDoctorProfile::Standard) ? TEXT("standard") :
		(ActiveProfile == EBPDoctorProfile::Everything) ? TEXT("everything") : TEXT("silent_failures_only");
	Root->SetStringField(TEXT("scan_profile"), ProfStr);

	TArray<TSharedPtr<FJsonValue>> SupArr;
	for (const FString& Key : SuppressedIssueKeys)
		SupArr.Add(MakeShared<FJsonValueString>(Key));
	Root->SetArrayField(TEXT("suppressed_issues"), SupArr);

	FString OutputString;
	TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&OutputString);
	FJsonSerializer::Serialize(Root, Writer);

	FString SettingsDir = FPaths::ProjectSavedDir() / TEXT("BPDoctor");
	IFileManager::Get().MakeDirectory(*SettingsDir, true);
	// v2.7.4 audit fix: atomic write via temp + rename. Without this, a mid-write
	// crash (Alt+F4, power loss, editor crash) truncates Settings.json to 0 bytes,
	// silently reverting all suppressions and disabled checks to defaults next launch.
	const FString FinalPath = SettingsDir / TEXT("Settings.json");
	const FString TempPath = FinalPath + TEXT(".tmp");
	if (FFileHelper::SaveStringToFile(OutputString, *TempPath,
			FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))
	{
		IFileManager::Get().Move(*FinalPath, *TempPath, /*bReplace=*/true);
	}
	else
	{
		UE_LOG(LogBPDoctor, Warning,
			TEXT("SaveSettings: could not write Settings.json (Saved/ read-only?). Settings not persisted."));
	}

	// Sprint 5 Phase B P7: also write Config/BPDoctor.suppress so suppressions are
	// committable and shareable across the team.
	// v2.7.4 audit note: BPDoctor.suppress contains full /Game/ asset paths. Teams on
	// public/partner repos should review the file before commit — paths can leak WIP
	// content names. Future enhancement: bPrivacyMode that hashes paths before write.
	BPDoctor_SaveSuppressFile(SuppressedIssueKeys);
}

void SBPDoctorPanel::LoadSettings()
{
	FString SettingsPath = FPaths::ProjectSavedDir() / TEXT("BPDoctor") / TEXT("Settings.json");
	FString JsonString;
	if (!FFileHelper::LoadFileToString(JsonString, *SettingsPath)) return;

	TSharedPtr<FJsonObject> Root;
	TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(JsonString);
	if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid()) return;

	DisabledChecks.Empty();
	const TArray<TSharedPtr<FJsonValue>>* DisArr;
	if (Root->TryGetArrayField(TEXT("disabled_checks"), DisArr))
	{
		for (const auto& V : *DisArr)
			DisabledChecks.Add(V->AsString());
	}

	FString ModeStr;
	if (Root->TryGetStringField(TEXT("experience_mode"), ModeStr))
	{
		if (ModeStr == TEXT("intermediate")) ExperienceMode = EBPDoctorExperienceMode::Intermediate;
		else if (ModeStr == TEXT("expert")) ExperienceMode = EBPDoctorExperienceMode::Expert;
		else ExperienceMode = EBPDoctorExperienceMode::Beginner;
	}

	FString ProfStr;
	if (Root->TryGetStringField(TEXT("scan_profile"), ProfStr))
	{
		if (ProfStr == TEXT("standard"))         ActiveProfile = EBPDoctorProfile::Standard;
		else if (ProfStr == TEXT("everything"))  ActiveProfile = EBPDoctorProfile::Everything;
		else                                     ActiveProfile = EBPDoctorProfile::SilentFailuresOnly;
	}
	FBPDoctorChecks::SetActiveProfile(ActiveProfile);

	SuppressedIssueKeys.Empty();
	const TArray<TSharedPtr<FJsonValue>>* SupArr;
	if (Root->TryGetArrayField(TEXT("suppressed_issues"), SupArr))
	{
		for (const auto& V : *SupArr)
			SuppressedIssueKeys.Add(V->AsString());
	}

	// Sprint 5 Phase B P7: also load committable suppressions from Config/BPDoctor.suppress.
	// Merged into the same set — committed entries take precedence by surviving the JSON's
	// per-dev wipe, but neither file silently overrides the other. New devs get team
	// suppressions on first scan after clone with zero manual config.
	BPDoctor_LoadSuppressFile(SuppressedIssueKeys);
}

// ─────────────────────────────────────────────────────────────────
//  Sprint 5 Phase D — UX polish member functions
// ─────────────────────────────────────────────────────────────────

void SBPDoctorPanel::OnRowDoubleClicked(TSharedPtr<FBPDoctorResult> Item)
{
	// Match the single-Navigate-button behavior: zoom the BP editor to the issue's node.
	// SListView's double-click event fires AFTER OnSelectionChanged, so SelectedIssue is
	// already current — but accept the Item directly for resilience to selection-mode quirks.
	if (Item.IsValid())
	{
		NavigateToIssue(*Item);
	}
}

TSharedPtr<SWidget> SBPDoctorPanel::OnRowContextMenuOpening()
{
	if (!SelectedIssue.IsValid())
	{
		return nullptr; // No selection -> no menu
	}

	// CloseSelfOnly = true: clicking outside the menu dismisses it cleanly.
	// CommandList = nullptr: BPDoctor doesn't ship a UICommandList; menu uses raw lambdas.
	FMenuBuilder MenuBuilder(/*bInShouldCloseWindowAfterMenuSelection=*/true, /*InCommandList=*/nullptr);

	MenuBuilder.BeginSection("BPDoctorIssue", LOCTEXT("CtxIssueSection", "Issue"));
	{
		MenuBuilder.AddMenuEntry(
			LOCTEXT("CtxNavigate", "Navigate to Node"),
			LOCTEXT("CtxNavigateTip", "Open the Blueprint editor and zoom to the offending node"),
			FSlateIcon(),
			FUIAction(FExecuteAction::CreateLambda([this]()
			{
				if (SelectedIssue.IsValid()) NavigateToIssue(*SelectedIssue);
			}))
		);

		// Only surface Fix if the issue is genuinely auto-fixable AND not already fixed.
		// Greying out is preferred to hiding so the user knows the option exists for OTHER rows.
		const bool bCanFix = SelectedIssue->bAutoFixable && !SelectedIssue->bFixed;
		MenuBuilder.AddMenuEntry(
			LOCTEXT("CtxFix", "Fix This Issue"),
			LOCTEXT("CtxFixTip", "Apply auto-fix with preview + undo (only available for fixable, unfixed issues)"),
			FSlateIcon(),
			FUIAction(
				FExecuteAction::CreateLambda([this]() { OnFixSelected(); }),
				FCanExecuteAction::CreateLambda([bCanFix]() { return bCanFix; })
			)
		);

		MenuBuilder.AddMenuEntry(
			LOCTEXT("CtxSuppress", "Suppress This Issue"),
			LOCTEXT("CtxSuppressTip", "Hide this CheckCode + Asset combination from future scans (write to Settings.json + Config/BPDoctor.suppress)"),
			FSlateIcon(),
			FUIAction(FExecuteAction::CreateLambda([this]() { OnSuppressSelected(); }))
		);

		MenuBuilder.AddMenuEntry(
			LOCTEXT("CtxCopy", "Copy Details to Clipboard"),
			LOCTEXT("CtxCopyTip", "Copy the issue's full detail-panel content (description + how-to-fix + detection method)"),
			FSlateIcon(),
			FUIAction(FExecuteAction::CreateLambda([this]() { OnCopyDetails(); }))
		);
	}
	MenuBuilder.EndSection();

	return MenuBuilder.MakeWidget();
}

void SBPDoctorPanel::OnSortChanged(EColumnSortPriority::Type /*SortPriority*/, const FName& ColumnName, EColumnSortMode::Type NewSortMode)
{
	CurrentSortColumn = ColumnName;
	CurrentSortMode = NewSortMode;
	RefreshFilteredList();
}

EColumnSortMode::Type SBPDoctorPanel::GetSortModeForColumn(FName ColumnName) const
{
	return (ColumnName == CurrentSortColumn) ? CurrentSortMode : EColumnSortMode::None;
}

void SBPDoctorPanel::ShowFixToast(bool bSuccess, const FString& CheckCode, const FString& AssetName)
{
	FNotificationInfo Info(FText::Format(
		bSuccess
			? LOCTEXT("FixToastSuccessFmt", "Fixed: {0} in {1}")
			: LOCTEXT("FixToastFailFmt", "Could not auto-fix: {0} in {1}"),
		FText::FromString(CheckCode), FText::FromString(AssetName)));
	Info.ExpireDuration = 4.0f;
	Info.bUseSuccessFailIcons = true;
	Info.bFireAndForget = true; // Auto-dismiss; no user click required to close

	TSharedPtr<SNotificationItem> Notif = FSlateNotificationManager::Get().AddNotification(Info);
	if (Notif.IsValid())
	{
		Notif->SetCompletionState(bSuccess
			? SNotificationItem::CS_Success
			: SNotificationItem::CS_Fail);
	}
}

FString SBPDoctorPanel::MakeProfileLabel(EBPDoctorProfile Profile)
{
	// Live tier-count helper — pulls from FBPDoctorChecks::GetAllChecks() (which has its own
	// InitChecks() guard so it's safe to call before LoadSettings). Counts checks whose tier
	// is included in the given profile via IsTierInProfile, NOT raw tier counts — so Standard
	// label correctly reflects "SilentFailure + Contextual" union.
	int32 Count = 0;
	const TArray<FBPDoctorCheckDef>& All = FBPDoctorChecks::GetAllChecks();
	for (const FBPDoctorCheckDef& Def : All)
	{
		if (FBPDoctorChecks::IsTierInProfile(Def.Tier, Profile))
		{
			Count++;
		}
	}

	switch (Profile)
	{
		case EBPDoctorProfile::SilentFailuresOnly:
			return FString::Printf(TEXT("Silent Failures Only (%d)"), Count);
		case EBPDoctorProfile::Standard:
			return FString::Printf(TEXT("Standard (%d)"), Count);
		case EBPDoctorProfile::Everything:
			return FString::Printf(TEXT("Everything (%d)"), Count);
		default:
			return FString::Printf(TEXT("Unknown (%d)"), Count);
	}
}

#undef LOCTEXT_NAMESPACE
