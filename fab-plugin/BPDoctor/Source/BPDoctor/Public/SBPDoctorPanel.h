// Copyright (C) 2025-2026 Jacob Ribbe. All rights reserved.

#pragma once

#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/Views/SListView.h"
#include "Widgets/Notifications/SProgressBar.h"
#include "BPDoctorTypes.h"
#include "BPDoctorScanner.h"

/**
 * Main Slate panel for BP Doctor.
 * Polished dockable tab with health grade, column headers, severity filtering,
 * detail panel, and auto-fix support.
 */
class SBPDoctorPanel : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SBPDoctorPanel) {}
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);

private:
	// ── Actions ──
	FReply OnScanProject();
	FReply OnClear();
	FReply OnFixSelected();
	FReply OnFixAll();
	FReply OnExportReport();
	FReply OnUndoLastFix();
	FReply OnRevertSelected();
	FReply OnCopyDetails();
	FReply OnSuppressSelected();
	void ShowFixConfirmDialog(TSharedPtr<FBPDoctorResult> Issue);
	void ShowFixAllDialog();
	void OpenBlueprintInEditor(const FString& AssetPath);
	void NavigateToIssue(const FBPDoctorResult& Result);
	void RevertBlueprint(const FString& AssetPath);
	FString BackupPackageFile(UBlueprint* BP);
	void ShowChecksDialog();
	void ShowSettingsDialog();
	void ShowCustomRulesEditor();
	void ImportCustomRules();
	void ExportSettings();
	void ImportSettings();
	FReply OnExportHTMLReport();
	FReply OnOpenUserGuide();
	void SaveSettings();
	void LoadSettings();

	// ── Scanner callbacks ──
	void OnScanComplete(const TArray<FBPDoctorAssetInfo>& Results);

	// ── List view ──
	TSharedRef<ITableRow> OnGenerateRow(TSharedPtr<FBPDoctorResult> Item,
		const TSharedRef<STableViewBase>& OwnerTable);
	void OnSelectionChanged(TSharedPtr<FBPDoctorResult> SelectedItem, ESelectInfo::Type SelectInfo);
	void OnRowDoubleClicked(TSharedPtr<FBPDoctorResult> Item);
	TSharedPtr<SWidget> OnRowContextMenuOpening();
	void OnSortChanged(EColumnSortPriority::Type SortPriority, const FName& ColumnName, EColumnSortMode::Type NewSortMode);
	EColumnSortMode::Type GetSortModeForColumn(FName ColumnName) const;
	void RefreshFilteredList();
	void UpdateStats();
	void ShowFixToast(bool bSuccess, const FString& CheckCode, const FString& AssetName);
	static FString MakeProfileLabel(EBPDoctorProfile Profile);

	// ── Attribute bindings ──
	TOptional<float> GetProgressPercent() const;
	FText GetHealthGradeText() const;
	FSlateColor GetHealthGradeColor() const;
	FText GetStatsText() const;

	// ── Helpers ──
	UBlueprint* LoadBlueprintFromResult(const FBPDoctorResult& Result);

	// ── State ──
	TSharedPtr<FBPDoctorScanner> Scanner;
	TArray<FBPDoctorAssetInfo> AllResults;
	TArray<TSharedPtr<FBPDoctorResult>> FilteredIssues;
	TSharedPtr<FBPDoctorResult> SelectedIssue;
	TSharedPtr<SListView<TSharedPtr<FBPDoctorResult>>> IssueListView;
	TSharedPtr<STextBlock> DetailText;
	TSharedPtr<SButton> FixButton;
	TSharedPtr<SButton> RevertButton;
	TSharedPtr<SButton> OpenEditorButton;
	TSharedPtr<SButton> CopyButton;
	TSharedPtr<SButton> SuppressButton;
	TSharedPtr<SHorizontalBox> FixButtonsRow;

	// ── Filter state ──
	bool bShowErrors = true;
	bool bShowWarnings = true;
	bool bShowInfo = true;
	bool bShowSuppressed = false;
	FString SearchFilter;

	// ── Experience mode ──
	// Sprint 5 Phase C: default flipped Intermediate -> Beginner so first-launch users
	// (no Settings.json yet) land on the verbose panel that surfaces WhyItMatters,
	// BeginnerTip, and DetectionMethod by default. LoadSettings preserves explicit user
	// choice via the persistence chain.
	EBPDoctorExperienceMode ExperienceMode = EBPDoctorExperienceMode::Beginner;
	TArray<TSharedPtr<FString>> ExperienceModeOptions;

	// ── Scan profile ──
	// Default for new installs is SilentFailuresOnly — first scan experience is max signal,
	// zero false-positives from stylistic heuristics. Real-world reviewers showed that noise
	// kills tool trust faster than missed findings (2026-04-23 product review).
	EBPDoctorProfile ActiveProfile = EBPDoctorProfile::SilentFailuresOnly;
	TArray<TSharedPtr<FString>> ProfileOptions;

	// ── Scan state ──
	bool bScanRunning = false;
	float CurrentProgress = 0.f;
	FString HealthGrade = TEXT("-");
	int32 TotalScanned = 0;
	int32 TotalErrors = 0;
	int32 TotalWarnings = 0;
	int32 TotalInfos = 0;
	int32 TotalAutoFixable = 0;

	// ── Fix history (for undo) ──
	TArray<FBPDoctorFixHistoryEntry> FixHistory;

	// ── Suppression ──
	TSet<FString> SuppressedIssueKeys; // "CheckCode|AssetPath"

	// ── Check management ──
	TSet<FString> DisabledChecks;

	// ── Sprint 5 Phase D: column sort state ──
	// CurrentSortColumn = NAME_None means "no sort applied" (preserve scan order).
	// Sort applies in RefreshFilteredList() AFTER filtering so suppression / search
	// changes don't lose the user's chosen order.
	FName CurrentSortColumn = NAME_None;
	EColumnSortMode::Type CurrentSortMode = EColumnSortMode::None;
};
