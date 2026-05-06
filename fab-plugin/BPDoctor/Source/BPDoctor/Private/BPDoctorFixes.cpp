// Copyright (C) 2025-2026 Jacob Ribbe. All rights reserved.

#include "BPDoctorFixes.h"
#include "BPDoctorLog.h"

#include "Animation/AnimBlueprint.h"
#include "AnimGraphNode_LayeredBoneBlend.h"
#include "AnimGraphNode_Slot.h"
#include "AnimGraphNode_Base.h"

#include "EdGraph/EdGraph.h"
#include "EdGraph/EdGraphNode.h"
#include "EdGraph/EdGraphPin.h"
#include "K2Node_CallFunction.h"
#include "K2Node_DynamicCast.h"
#include "EdGraphSchema_K2.h"

#include "Editor.h"
#include "Editor/TransBuffer.h"
#include "ScopedTransaction.h"
#include "Kismet2/BlueprintEditorUtils.h"
#include "Kismet2/KismetEditorUtilities.h"
#include "Engine/Blueprint.h"

#define LOCTEXT_NAMESPACE "BPDoctorFixes"

// ─────────────────────────────────────────────────────────────────
//  HELPERS — anonymous namespace, internal linkage only
// ─────────────────────────────────────────────────────────────────
namespace
{
	/**
	 * Collect anim graph nodes of a given type across an AnimBlueprint, INCLUDING nodes
	 * nested inside state machine sub-graphs. Mirrors the pattern in
	 * BPDoctorChecks::CollectAnimNodesOfType — duplicated here because that helper lives
	 * in an unnamed namespace inside BPDoctorChecks.cpp and isn't externally linkable.
	 *
	 * Use this in fixes that need to reach LayeredBoneBlend / Slot / etc. inside SM
	 * states. Without it, fixes silently no-op on AAA AnimBPs that put anim nodes inside
	 * state machines (Sprint 5 P0-3 batch; CollectAnimNodesOfType durable failure class
	 * documented in feedback_ue5_plugin_build.md).
	 */
	template <typename T>
	TArray<T*> CollectAnimNodesRecursive(UAnimBlueprint* AnimBP)
	{
		TArray<T*> Result;
		if (!AnimBP) return Result;

		TFunction<void(UEdGraph*)> Scan = [&](UEdGraph* Graph)
		{
			if (!Graph) return;
			for (UEdGraphNode* Node : Graph->Nodes)
			{
				if (UAnimGraphNode_Base* AnimNode = Cast<UAnimGraphNode_Base>(Node))
				{
					if (T* Typed = Cast<T>(AnimNode))
					{
						Result.Add(Typed);
					}
					for (UEdGraph* Sub : AnimNode->GetSubGraphs())
					{
						Scan(Sub);
					}
				}
			}
		};

		for (UEdGraph* Graph : AnimBP->FunctionGraphs)
		{
			Scan(Graph);
		}
		for (UEdGraph* Graph : AnimBP->UbergraphPages)
		{
			Scan(Graph);
		}
		return Result;
	}
}

// ─────────────────────────────────────────────────────────────────
//  PREVIEW
// ─────────────────────────────────────────────────────────────────

FBPDoctorFixAction FBPDoctorFixes::PreviewFix(const FBPDoctorResult& Issue, UBlueprint* Blueprint)
{
	FBPDoctorFixAction Action;
	Action.CheckCode = Issue.CheckCode;
	Action.AssetName = Issue.AssetName;
	Action.AssetPath = Issue.AssetPath;

	if (Issue.CheckCode == TEXT("BROKEN_BLEND_WT"))
	{
		Action.FixType = EBPDoctorFixType::Programmatic;
		Action.Description = TEXT("Clamp all blend weight default values to the [0.0, 1.0] range.");
		Action.Preview = TEXT("BlendWeight pins with out-of-range defaults will be clamped.");
	}
	else if (Issue.CheckCode == TEXT("MISSING_SLOT"))
	{
		Action.FixType = EBPDoctorFixType::Programmatic;
		Action.Description = TEXT("Add a DefaultSlot node to the AnimGraph.");
		Action.Preview = TEXT("A new AnimGraphNode_Slot with SlotName='DefaultSlot' will be created. Wire it into your pose chain after fixing.");
	}
	else if (Issue.CheckCode == TEXT("TPOSE_FALLBACK"))
	{
		Action.FixType = EBPDoctorFixType::Manual;
		Action.Description = TEXT("Connect disconnected BasePose pins on LayeredBoneBlend nodes.");
		Action.Preview = TEXT("Open the AnimBP and connect the BasePose input pin to your main pose chain.");
	}
	else if (Issue.CheckCode == TEXT("DUP_SLOT"))
	{
		Action.FixType = EBPDoctorFixType::Programmatic;
		Action.Description = TEXT("Rename duplicate slot names to be unique (append _2, _3, etc.).");
		Action.Preview = TEXT("Duplicate SlotNames will get numeric suffixes.");
	}
	else if (Issue.CheckCode == TEXT("BP_SELF_CAST"))
	{
		Action.FixType = EBPDoctorFixType::Programmatic;
		Action.Description = TEXT("Remove self-cast nodes and reroute connections through Self reference.");
		Action.Preview = TEXT("Cast-to-Self nodes will be deleted; output pins rerouted to Self.");
	}
	else if (Issue.CheckCode == TEXT("BP_DEBUG_NODES"))
	{
		Action.FixType = EBPDoctorFixType::Programmatic;
		Action.Description = TEXT("Delete all PrintString and DrawDebug nodes.");
		Action.Preview = TEXT("Debug function call nodes will be removed from all graphs.");
	}
	else if (Issue.CheckCode == TEXT("BP_CONSTRUCT_HEAVY"))
	{
		Action.FixType = EBPDoctorFixType::Manual;
		Action.Description = TEXT("Move heavy operations from Construction Script to BeginPlay.");
		Action.Preview = TEXT("SpawnActor and query nodes should be moved manually to BeginPlay.");
	}
	else if (Issue.CheckCode == TEXT("ORPHANED_NODE"))
	{
		Action.FixType = EBPDoctorFixType::Programmatic;
		Action.Description = TEXT("Delete all AnimGraph nodes not reachable from the Output Pose root.");
		Action.Preview = TEXT("Orphaned nodes in the top-level AnimGraph will be removed. State machine contents are preserved.");
	}
	else
	{
		Action.FixType = EBPDoctorFixType::Manual;
		Action.Description = TEXT("This issue requires manual intervention in the Blueprint editor.");
		Action.Preview = Issue.NodeHint;
	}

	return Action;
}

// ─────────────────────────────────────────────────────────────────
//  APPLY
// ─────────────────────────────────────────────────────────────────

namespace
{
	/**
	 * A fix is "structural" if it adds or removes nodes, or otherwise changes the Blueprint's
	 * generated class skeleton. Non-structural fixes only edit pin defaults / properties.
	 * Structural fixes must call MarkBlueprintAsStructurallyModified so the skeleton class
	 * rebuilds correctly; non-structural fixes can use MarkBlueprintAsModified.
	 */
	bool IsStructuralFix(const FString& CheckCode)
	{
		return CheckCode == TEXT("MISSING_SLOT")
			|| CheckCode == TEXT("BP_SELF_CAST")
			|| CheckCode == TEXT("BP_DEBUG_NODES")
			|| CheckCode == TEXT("ORPHANED_NODE");
	}
}

bool FBPDoctorFixes::ApplyFix(const FBPDoctorResult& Issue, UBlueprint* Blueprint, const FString& CustomValue)
{
	if (!Issue.bAutoFixable || !Blueprint) return false;

	// Pre-condition gate (per 2026-04-23 auto-fix safety research):
	// refuse BPs already in error state so a failing post-fix compile can't be confused
	// with a pre-existing broken BP. User should fix the compile error first.
	if (Blueprint->Status == BS_Error)
	{
		UE_LOG(LogBPDoctor, Warning,
			TEXT("ApplyFix: '%s' is already in BS_Error; fix the compile error first before auto-fixing."),
			*Blueprint->GetName());
		return false;
	}

	const bool bStructural = IsStructuralFix(Issue.CheckCode);
	bool bSuccess = false;

	// Snapshot undo-queue length before our transaction. Rollback verifies
	// queue == snapshot + 1 to ensure CompileBlueprint's Slate pump didn't land
	// an unrelated user edit on top of our tx (2026-04-23 audit NEW-03 / P2-01).
	const int32 QueueSnapshot = (GEditor && GEditor->Trans)
		? GEditor->Trans->GetQueueLength() : -1;

	// ---- Transaction scope: everything inside is undoable as one atomic unit. ----
	{
		FScopedTransaction Transaction(
			FText::Format(LOCTEXT("AutoFixFmt", "BP Doctor: apply fix '{0}'"),
				FText::FromString(Issue.CheckCode)));

		Blueprint->Modify();

		// Dispatch to the right handler. Individual handlers call Modify() on their own targets.
		// v2.7.3 audit cleanup: removed TPOSE_FALLBACK + BP_CONSTRUCT_HEAVY dispatches — both
		// were stubs returning false, gated unreachable by bAutoFixable=false on the check
		// definitions. They survived as dead code until the second-pass audit caught them.
		if (Issue.CheckCode == TEXT("BROKEN_BLEND_WT"))        bSuccess = FixBrokenBlendWeight(Blueprint, CustomValue);
		else if (Issue.CheckCode == TEXT("MISSING_SLOT"))      bSuccess = FixMissingSlot(Blueprint);
		else if (Issue.CheckCode == TEXT("DUP_SLOT"))          bSuccess = FixDuplicateSlot(Blueprint, CustomValue);
		else if (Issue.CheckCode == TEXT("BP_SELF_CAST"))      bSuccess = FixSelfCast(Blueprint);
		else if (Issue.CheckCode == TEXT("BP_DEBUG_NODES"))    bSuccess = FixDebugNodes(Blueprint);
		else if (Issue.CheckCode == TEXT("ORPHANED_NODE"))     bSuccess = FixOrphanedNode(Blueprint);
		else if (Issue.CheckCode == TEXT("BLEND_WT_SUM"))      bSuccess = FixBlendWeightSum(Blueprint);

		if (bSuccess)
		{
			if (bStructural)
			{
				// Adds/removes nodes -> skeleton class must rebuild.
				FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
			}
			else
			{
				FBlueprintEditorUtils::MarkBlueprintAsModified(Blueprint);
			}
			Blueprint->MarkPackageDirty();
		}
		else
		{
			// Cancel the transaction so Ctrl+Z doesn't show an empty "apply fix" entry.
			Transaction.Cancel();
		}
	}
	// ---- End transaction scope. Compile AFTER scope closes (canonical pattern). ----

	if (bSuccess)
	{
		FKismetEditorUtilities::CompileBlueprint(Blueprint);

		if (Blueprint->Status == BS_Error)
		{
			UE_LOG(LogBPDoctor, Error,
				TEXT("ApplyFix: compile failed after applying '%s' to '%s' - rolling back via Undo."),
				*Issue.CheckCode, *Blueprint->GetName());

			if (GEditor && GEditor->Trans)
			{
				// Queue guard: verify our tx is still the top entry before undoing.
				// CompileBlueprint pumps Slate; deferred user actions can land here.
				const int32 QueueNow = GEditor->Trans->GetQueueLength();
				if (QueueSnapshot >= 0 && QueueNow == QueueSnapshot + 1)
				{
					GEditor->UndoTransaction();
					// Recompile post-undo so the BP isn't left in a half-reverted state.
					FKismetEditorUtilities::CompileBlueprint(Blueprint);
				}
				else
				{
					UE_LOG(LogBPDoctor, Error,
						TEXT("ApplyFix rollback skipped: queue length %d != snapshot+1 (%d); avoiding revert of unrelated edit."),
						QueueNow, QueueSnapshot + 1);
				}
			}
			return false;
		}

		UE_LOG(LogBPDoctor, Log,
			TEXT("ApplyFix: '%s' applied to '%s' (structural=%d)."),
			*Issue.CheckCode, *Blueprint->GetName(), bStructural ? 1 : 0);
	}

	return bSuccess;
}

int32 FBPDoctorFixes::ApplyAllFixes(const TArray<FBPDoctorResult>& Issues, UBlueprint* Blueprint)
{
	// Per-fix undo granularity: each ApplyFix owns its own FScopedTransaction.
	// No outer batch tx — inner Cancel() can target the outer in some UE versions.
	//
	// v2.7.4 audit fix: stable-sort so non-structural fixes (property mutations) run
	// FIRST, structural fixes (add/remove nodes) run LAST. Structural fixes can
	// invalidate node-references embedded in subsequent results' NodeHint pointers;
	// running them last narrows the interference window. Edge case remains: two
	// structural fixes on the same BP can still cross-invalidate. Recommend a fresh
	// scan after Fix-All if the result-list shows multiple structural codes
	// (ORPHANED_NODE, MISSING_SLOT, BP_SELF_CAST, BP_DEBUG_NODES).
	TArray<FBPDoctorResult> Sorted = Issues;
	Sorted.StableSort([](const FBPDoctorResult& A, const FBPDoctorResult& B) {
		const bool bA = IsStructuralFix(A.CheckCode);
		const bool bB = IsStructuralFix(B.CheckCode);
		return !bA && bB; // non-structural before structural
	});

	int32 Count = 0;
	for (const FBPDoctorResult& Issue : Sorted)
	{
		if (Issue.bAutoFixable && ApplyFix(Issue, Blueprint, FString()))
		{
			Count++;
		}
	}
	return Count;
}

// ─────────────────────────────────────────────────────────────────
//  FIX IMPLEMENTATIONS
// ─────────────────────────────────────────────────────────────────

bool FBPDoctorFixes::FixBrokenBlendWeight(UBlueprint* BP, const FString& CustomValue)
{
	UAnimBlueprint* AnimBP = Cast<UAnimBlueprint>(BP);
	if (!AnimBP) return false;

	bool bFixed = false;
	const bool bUseCustom = !CustomValue.IsEmpty();
	const float CustomFloat = bUseCustom ? FMath::Clamp(FCString::Atof(*CustomValue), 0.0f, 1.0f) : 0.f;

	// Walk SM state sub-graphs too — CheckBrokenBlendWeight uses CollectAnimNodesOfType
	// which recurses, so the fix needs the same reach. Without this, the check fires on
	// a LayeredBoneBlend inside an SM state and the fix silently no-ops (Sprint 5 P0-3a).
	TArray<UAnimGraphNode_LayeredBoneBlend*> LBBs = CollectAnimNodesRecursive<UAnimGraphNode_LayeredBoneBlend>(AnimBP);
	for (UAnimGraphNode_LayeredBoneBlend* LBB : LBBs)
	{
		for (UEdGraphPin* Pin : LBB->Pins)
		{
			if (Pin->PinName.ToString().Contains(TEXT("BlendWeight")) && !Pin->LinkedTo.Num())
			{
				FString DefaultVal = Pin->GetDefaultAsString();
				if (!DefaultVal.IsEmpty())
				{
					float Val = FCString::Atof(*DefaultVal);
					if (Val < 0.0f || Val > 1.0f)
					{
						LBB->Modify();
						float NewVal = bUseCustom ? CustomFloat : FMath::Clamp(Val, 0.0f, 1.0f);
						Pin->DefaultValue = FString::Printf(TEXT("%.6f"), NewVal);
						bFixed = true;
					}
				}
			}
		}
	}
	return bFixed;
}

bool FBPDoctorFixes::FixMissingSlot(UBlueprint* BP)
{
	UAnimBlueprint* AnimBP = Cast<UAnimBlueprint>(BP);
	if (!AnimBP) return false;

	// Find the AnimGraph (the graph containing the Root output pose node)
	UEdGraph* AnimGraph = nullptr;
	for (UEdGraph* Graph : AnimBP->FunctionGraphs)
	{
		for (UEdGraphNode* Node : Graph->Nodes)
		{
			if (Node->GetClass()->GetName().Contains(TEXT("Root")))
			{
				AnimGraph = Graph;
				break;
			}
		}
		if (AnimGraph) break;
	}
	if (!AnimGraph) return false;

	// Verify no Slot node already exists in this graph
	for (UEdGraphNode* Node : AnimGraph->Nodes)
	{
		if (Cast<UAnimGraphNode_Slot>(Node))
		{
			return false;
		}
	}

	// Create a new DefaultSlot node
	AnimGraph->Modify();
	UAnimGraphNode_Slot* NewSlot = NewObject<UAnimGraphNode_Slot>(AnimGraph);
	NewSlot->CreateNewGuid();
	NewSlot->PostPlacedNewNode();
	NewSlot->AllocateDefaultPins();

	// Modify the new node BEFORE we write its user-visible properties so the undo
	// system records the property state for clean Ctrl+Z rollback (hellscape v2.4 #5).
	NewSlot->Modify();
	NewSlot->Node.SlotName = FName("DefaultSlot");

	// Position offset from origin so it's visible when the graph opens
	NewSlot->NodePosX = -200;
	NewSlot->NodePosY = 0;

	AnimGraph->AddNode(NewSlot, /*bFromUI=*/false, /*bSelectNewNode=*/false);

	return true;
}

bool FBPDoctorFixes::FixBlendWeightSum(UBlueprint* BP)
{
	UAnimBlueprint* AnimBP = Cast<UAnimBlueprint>(BP);
	if (!AnimBP) return false;

	bool bFixed = false;

	// Walk SM state sub-graphs too — CheckBlendWeightSum uses CollectAnimNodesOfType
	// which recurses. Previous flat walk silently failed to normalize LayeredBoneBlend
	// nodes inside SM states, so the check fired and the fix never reached the node
	// (Sprint 5 P0-3b).
	TArray<UAnimGraphNode_LayeredBoneBlend*> LBBs = CollectAnimNodesRecursive<UAnimGraphNode_LayeredBoneBlend>(AnimBP);
	for (UAnimGraphNode_LayeredBoneBlend* LBB : LBBs)
	{
		// First pass: collect all unlinked BlendWeight pins and sum their current defaults.
		TArray<UEdGraphPin*> WeightPins;
		float Sum = 0.0f;
		for (UEdGraphPin* Pin : LBB->Pins)
		{
			if (!Pin || !Pin->PinName.ToString().Contains(TEXT("BlendWeight"))) continue;
			if (Pin->LinkedTo.Num() > 0) continue; // variable-driven — skip
			const FString Default = Pin->GetDefaultAsString();
			if (Default.IsEmpty()) continue;
			WeightPins.Add(Pin);
			Sum += FCString::Atof(*Default);
		}

		const int32 NumWeights = WeightPins.Num();
		if (NumWeights == 0) continue;

		// Already inside tolerance — no-op for this node (don't pointlessly rewrite pins).
		if (Sum >= 0.95f && Sum <= 1.05f) continue;

		LBB->Modify();
		if (FMath::Abs(Sum) < KINDA_SMALL_NUMBER)
		{
			// All weights zero — split evenly so the node produces a meaningful output.
			const float EqualWeight = 1.0f / static_cast<float>(NumWeights);
			for (UEdGraphPin* Pin : WeightPins)
			{
				Pin->DefaultValue = FString::Printf(TEXT("%.6f"), EqualWeight);
			}
		}
		else
		{
			// Normalize: preserve ratios between layers, force total to 1.0.
			for (UEdGraphPin* Pin : WeightPins)
			{
				const float Old = FCString::Atof(*Pin->GetDefaultAsString());
				const float Normalized = Old / Sum;
				Pin->DefaultValue = FString::Printf(TEXT("%.6f"), Normalized);
			}
		}
		bFixed = true;
	}
	return bFixed;
}

bool FBPDoctorFixes::FixDuplicateSlot(UBlueprint* BP, const FString& CustomValue)
{
	UAnimBlueprint* AnimBP = Cast<UAnimBlueprint>(BP);
	if (!AnimBP) return false;

	bool bFixed = false;

	// Walk SM state sub-graphs too — CheckDuplicateSlot uses CollectAnimNodesOfType
	// which recurses. Without this, a duplicate Slot inside an SM state was renamed
	// only when the duplicate happened at the top level (Sprint 5 P0-3c).
	TArray<UAnimGraphNode_Slot*> AllSlots = CollectAnimNodesRecursive<UAnimGraphNode_Slot>(AnimBP);

	// Pass 1: collect EVERY existing slot name. A counter-based suffix (Foo_2, Foo_3)
	// silently collides with manually-named Foo_2 that the user already placed. The
	// only correct solution is to know the full set of taken names before picking a
	// suffix (hellscape v2.4 #7).
	TSet<FName> TakenNames;
	for (UAnimGraphNode_Slot* Slot : AllSlots)
	{
		TakenNames.Add(Slot->Node.SlotName);
	}

	// Pass 2: first occurrence of each name keeps it; every duplicate gets a suffix
	// that's probed until it doesn't collide with the taken set.
	TSet<FName> SeenNames;
	for (UAnimGraphNode_Slot* Slot : AllSlots)
	{
		FName SlotName = Slot->Node.SlotName;
		if (!SeenNames.Contains(SlotName))
		{
			SeenNames.Add(SlotName);
			continue;
		}

		Slot->Modify();
		const FString Base = !CustomValue.IsEmpty() ? CustomValue : SlotName.ToString();
		int32 Suffix = 2;
		FName NewName;
		do
		{
			NewName = FName(*FString::Printf(TEXT("%s_%d"), *Base, Suffix));
			Suffix++;
		}
		while (TakenNames.Contains(NewName) || SeenNames.Contains(NewName));

		Slot->Node.SlotName = NewName;
		TakenNames.Add(NewName);
		SeenNames.Add(NewName);
		bFixed = true;
	}
	return bFixed;
}

bool FBPDoctorFixes::FixSelfCast(UBlueprint* BP)
{
	bool bFixed = false;
	UClass* BPClass = BP->GeneratedClass;
	if (!BPClass) return false;

	TArray<UEdGraph*> AllGraphs;
	AllGraphs.Append(BP->UbergraphPages);
	AllGraphs.Append(BP->FunctionGraphs);
	AllGraphs.Append(BP->MacroGraphs);

	for (UEdGraph* Graph : AllGraphs)
	{
		TArray<UK2Node_DynamicCast*> CastsToRemove;
		for (UEdGraphNode* Node : Graph->Nodes)
		{
			if (UK2Node_DynamicCast* CastNode = Cast<UK2Node_DynamicCast>(Node))
			{
				if (CastNode->TargetType == BPClass)
				{
					CastsToRemove.Add(CastNode);
				}
			}
		}

		if (CastsToRemove.Num() > 0)
		{
			Graph->Modify();
		}
		for (UK2Node_DynamicCast* CastNode : CastsToRemove)
		{
			CastNode->Modify();

			// Reroute: connect input object source to all output "As X" targets
			UEdGraphPin* SourcePin = CastNode->GetCastSourcePin();
			UEdGraphPin* ResultPin = CastNode->GetCastResultPin();
			if (SourcePin && ResultPin)
			{
				TArray<UEdGraphPin*> SourceLinks = SourcePin->LinkedTo;
				TArray<UEdGraphPin*> ResultLinks = ResultPin->LinkedTo;
				for (UEdGraphPin* Origin : SourceLinks)
				{
					for (UEdGraphPin* Target : ResultLinks)
					{
						Origin->MakeLinkTo(Target);
					}
				}
			}

			// Reroute exec pins. A self-cast always succeeds — the CastFailed branch is
			// dead code — so fold any CastFailed-downstream into the success path instead
			// of silently dropping it via BreakAllNodeLinks (hellscape v2.4 #6).
			UEdGraphPin* ExecIn = CastNode->FindPin(UEdGraphSchema_K2::PN_Execute);
			UEdGraphPin* ExecOut = CastNode->FindPin(UEdGraphSchema_K2::PN_Then);
			UEdGraphPin* ExecFailed = CastNode->FindPin(UEdGraphSchema_K2::PN_CastFailed);
			if (ExecIn && ExecOut)
			{
				// Copy arrays first — MakeLinkTo below mutates LinkedTo mid-iteration.
				TArray<UEdGraphPin*> InLinks = ExecIn->LinkedTo;
				TArray<UEdGraphPin*> OutLinks = ExecOut->LinkedTo;
				if (ExecFailed)
				{
					OutLinks.Append(ExecFailed->LinkedTo);
				}
				for (UEdGraphPin* In : InLinks)
				{
					for (UEdGraphPin* Out : OutLinks)
					{
						In->MakeLinkTo(Out);
					}
				}
			}

			CastNode->BreakAllNodeLinks();
			Graph->RemoveNode(CastNode);
			bFixed = true;
		}
	}
	return bFixed;
}

bool FBPDoctorFixes::FixDebugNodes(UBlueprint* BP)
{
	bool bFixed = false;

	static const TArray<FName> DebugFunctions = {
		FName("PrintString"), FName("PrintText"), FName("PrintWarning"),
		FName("DrawDebugLine"), FName("DrawDebugBox"), FName("DrawDebugSphere"),
		FName("DrawDebugPoint"), FName("DrawDebugArrow"), FName("DrawDebugString"),
		FName("DrawDebugCapsule"), FName("DrawDebugCylinder"),
	};

	TArray<UEdGraph*> AllGraphs;
	AllGraphs.Append(BP->UbergraphPages);
	AllGraphs.Append(BP->FunctionGraphs);
	AllGraphs.Append(BP->MacroGraphs);

	for (UEdGraph* Graph : AllGraphs)
	{
		TArray<UEdGraphNode*> NodesToRemove;
		for (UEdGraphNode* Node : Graph->Nodes)
		{
			if (UK2Node_CallFunction* Call = Cast<UK2Node_CallFunction>(Node))
			{
				FName FuncName = Call->FunctionReference.GetMemberName();
				if (DebugFunctions.Contains(FuncName))
				{
					NodesToRemove.Add(Node);
				}
			}
		}

		if (NodesToRemove.Num() > 0)
		{
			Graph->Modify();
		}
		for (UEdGraphNode* Node : NodesToRemove)
		{
			Node->Modify();
			UEdGraphPin* ExecIn = Node->FindPin(UEdGraphSchema_K2::PN_Execute);
			UEdGraphPin* ExecOut = Node->FindPin(UEdGraphSchema_K2::PN_Then);
			if (ExecIn && ExecOut)
			{
				// Copy arrays before iterating — MakeLinkTo modifies LinkedTo
				TArray<UEdGraphPin*> InLinks = ExecIn->LinkedTo;
				TArray<UEdGraphPin*> OutLinks = ExecOut->LinkedTo;
				for (UEdGraphPin* InLink : InLinks)
				{
					for (UEdGraphPin* OutLink : OutLinks)
					{
						InLink->MakeLinkTo(OutLink);
					}
				}
			}

			Node->BreakAllNodeLinks();
			Graph->RemoveNode(Node);
			bFixed = true;
		}
	}
	return bFixed;
}

bool FBPDoctorFixes::FixOrphanedNode(UBlueprint* BP)
{
	UAnimBlueprint* AnimBP = Cast<UAnimBlueprint>(BP);
	if (!AnimBP) return false;

	bool bFixed = false;

	// Check all graphs that may contain AnimGraph nodes
	TArray<UEdGraph*> GraphsToCheck;
	GraphsToCheck.Append(AnimBP->FunctionGraphs);
	GraphsToCheck.Append(AnimBP->UbergraphPages);

	for (UEdGraph* Graph : GraphsToCheck)
	{
		if (!Graph) continue;

		// Collect AnimGraphNode_Base nodes in THIS graph only (no subgraph recursion —
		// state machine contents are intentionally preserved)
		TArray<UAnimGraphNode_Base*> AnimNodes;
		for (UEdGraphNode* Node : Graph->Nodes)
		{
			if (UAnimGraphNode_Base* AnimNode = Cast<UAnimGraphNode_Base>(Node))
			{
				AnimNodes.Add(AnimNode);
			}
		}

		// Per-graph threshold guard removed (Sprint 5 P0-4): the check fires on the
		// global orphan count crossing ANIMBP_ORPHANED_NODE_THRESHOLD (15). The previous
		// per-graph `<= 3` guard meant the fix almost never ran even when the check did
		// — orphans spread across 5 graphs at 4 nodes each tripped the check (20 > 15)
		// but the fix skipped every graph (4 > 3 is false → 4 ≤ 3 is false → wait this
		// was AnimNodes.Num() ≤ 3 not orphan count, so any graph with ≤3 anim nodes
		// got skipped regardless). The BFS below already returns early via
		// `if (WorkQueue.Num() == 0) continue;` for graphs without a Root node, which
		// is the only legitimate reason to skip.

		// BFS from Root node through input pins to find all reachable nodes
		TSet<UEdGraphNode*> Reachable;
		TArray<UEdGraphNode*> WorkQueue;

		for (UAnimGraphNode_Base* Node : AnimNodes)
		{
			if (Node->GetClass()->GetName().Contains(TEXT("Root")))
			{
				WorkQueue.Add(Node);
				Reachable.Add(Node);
			}
		}

		if (WorkQueue.Num() == 0) continue;

		while (WorkQueue.Num() > 0)
		{
			UEdGraphNode* Current = WorkQueue.Pop();
			for (UEdGraphPin* Pin : Current->Pins)
			{
				if (Pin->Direction == EGPD_Input)
				{
					for (UEdGraphPin* LinkedPin : Pin->LinkedTo)
					{
						UEdGraphNode* LinkedNode = LinkedPin->GetOwningNode();
						if (!Reachable.Contains(LinkedNode))
						{
							Reachable.Add(LinkedNode);
							WorkQueue.Add(LinkedNode);
						}
					}
				}
			}
		}

		// Delete unreachable AnimGraph nodes
		TArray<UAnimGraphNode_Base*> NodesToDelete;
		for (UAnimGraphNode_Base* Node : AnimNodes)
		{
			if (!Reachable.Contains(Node))
			{
				NodesToDelete.Add(Node);
			}
		}

		if (NodesToDelete.Num() > 0)
		{
			Graph->Modify();
			for (UAnimGraphNode_Base* Node : NodesToDelete)
			{
				Node->Modify();
				Node->BreakAllNodeLinks();
				Graph->RemoveNode(Node);
			}
			bFixed = true;
		}
	}

	return bFixed;
}

#undef LOCTEXT_NAMESPACE
