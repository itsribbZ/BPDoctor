// Copyright (C) 2025-2026 Jacob Ribbe. All rights reserved.
// Native UE5 Blueprint / AnimBlueprint diagnostic checks.

#include "BPDoctorChecks.h"
#include "BPDoctorConstants.h"
#include "BPDoctorLog.h"
#include "BPDoctorVersionCompat.h"

#include "Animation/AnimBlueprint.h"
#include "Animation/AnimBlueprintGeneratedClass.h"
#include "Animation/AnimInstance.h"
#include "Animation/AnimSequence.h"
#include "Animation/AnimMontage.h"
#include "Animation/BlendSpace.h"
#include "Animation/Skeleton.h"
#include "EdGraphSchema_K2.h"

#include "AnimGraphNode_Base.h"
#include "AnimGraphNode_SequencePlayer.h"
#include "AnimGraphNode_BlendSpacePlayer.h"
#include "AnimGraphNode_LayeredBoneBlend.h"
#include "AnimGraphNode_Slot.h"
#include "AnimGraphNode_StateMachine.h"
#include "AnimGraphNode_StateResult.h"
#include "AnimGraphNode_TransitionResult.h"
// State-machine SM graph node types (fix for CheckBrokenTransition silent zero-fire bug).
// UAnimStateNode is the actual state node in a state machine sub-graph;
// UAnimStateTransitionNode is the transition edge between states.
// The older UAnimGraphNode_StateResult/TransitionResult are INNER result nodes, not the SM graph topology.
#include "AnimStateNode.h"
#include "AnimStateTransitionNode.h"
#include "AnimStateConduitNode.h"
// Phase 2C (2026-04-16) - includes for new AnimBP v2 checks (27-34)
#include "AnimGraphNode_SaveCachedPose.h"
#include "AnimGraphNode_UseCachedPose.h"
#include "AnimStateEntryNode.h"
// Full type for SM->EditorStateMachineGraph->Nodes access (TObjectPtr needs complete type).
#include "AnimationStateMachineGraph.h"

// Phase D (2026-04-24) - includes for new AnimBP v3 checks (35-39)
#include "AnimGraphNode_LinkedAnimLayer.h"
#include "Animation/AnimNode_LinkedAnimLayer.h"
#include "Animation/AnimNodeAlphaOptions.h"
#include "Animation/BlendSpace1D.h" // IsA<UBlendSpace1D> in #39 BLENDSPACE_ZERO_AXIS
// PlayMontage K2 call walk for #38 MONTAGE_SECTION_LOOP — find AnimMontage refs from AnimBP graphs
#include "K2Node_CallFunction.h"

#include "EdGraph/EdGraph.h"
#include "EdGraph/EdGraphNode.h"
#include "EdGraph/EdGraphPin.h"
#include "K2Node.h"
#include "K2Node_CallFunction.h"
#include "K2Node_DynamicCast.h"
#include "K2Node_Event.h"
#include "K2Node_Timeline.h"
#include "K2Node_MacroInstance.h"

#include "Engine/Blueprint.h"
#include "Kismet2/BlueprintEditorUtils.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "UObject/UObjectIterator.h"
#include "Misc/PackageName.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonSerializer.h"

TArray<FBPDoctorCheckDef> FBPDoctorChecks::AllChecks;
bool FBPDoctorChecks::bInitialized = false;
bool FBPDoctorChecks::bCustomRulesLoaded = false;
TSet<FString> FBPDoctorChecks::DisabledCheckCodes;
EBPDoctorProfile FBPDoctorChecks::ActiveProfile = EBPDoctorProfile::SilentFailuresOnly;

// ─────────────────────────────────────────────────────────────────
//  CHECK DEFINITIONS
// ─────────────────────────────────────────────────────────────────

void FBPDoctorChecks::InitChecks()
{
	if (bInitialized) return;
	bInitialized = true;

	auto MakeCheck = [](int32 Id, const FString& Name, const FString& Code,
		EBPDoctorSeverity Sev, EBPDoctorConfidence Conf, EBPDoctorTier T, bool bFixable,
		const FString& Desc, const FString& Why, const FString& Tip,
		const FString& Fix = FString(), const FString& Detection = FString()) -> FBPDoctorCheckDef
	{
		FBPDoctorCheckDef C;
		C.Id = Id;
		C.Name = Name;
		C.Code = Code;
		C.Severity = Sev;
		C.Confidence = Conf;
		C.Tier = T;
		C.bAutoFixable = bFixable;
		C.Description = Desc;
		C.WhyItMatters = Why;
		C.BeginnerTip = Tip;
		C.HowToFix = Fix;
		C.DetectionMethod = Detection;
		return C;
	};

	// AnimBP Checks (1-12)
	AllChecks.Add(MakeCheck(1, TEXT("Null Anim Reference"), TEXT("NULL_ANIM_REF"),
		EBPDoctorSeverity::Error, EBPDoctorConfidence::High, EBPDoctorTier::SilentFailure, false,
		TEXT("Sequence Player node has no animation asset assigned."),
		TEXT("A Sequence Player with no animation can cause the character to snap to T-pose when that state is entered."),
		TEXT("One of your animation nodes is empty -- it has no animation assigned. This can make your character snap to a T-pose."),
		TEXT("1. Click Navigate to open the AnimBP\n2. Find the Sequence Player node with no animation\n3. In its Details panel, set the Sequence property to a valid AnimSequence\n4. Compile and save the AnimBP"),
		TEXT("Scans all AnimGraphNode_SequencePlayer nodes. Flags any where the Sequence property is null.")));

	AllChecks.Add(MakeCheck(2, TEXT("Broken Blend Weight"), TEXT("BROKEN_BLEND_WT"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::Medium, EBPDoctorTier::SilentFailure, true,
		TEXT("Blend weight value is outside the valid [0.0, 1.0] range."),
		TEXT("Weights outside [0,1] produce wrong blend proportions or visual pops. Clamping behavior varies by engine version."),
		TEXT("A blend weight controls how much two animations mix together. Yours is outside the valid range."),
		TEXT("AUTO-FIX: Clamps the value to [0.0, 1.0]. Use the custom input field to set a specific value.\n\nMANUAL: Navigate to the LayeredBoneBlend node > find the BlendWeight pin > set a value between 0.0 and 1.0."),
		TEXT("Reads default pin values on LayeredBoneBlend nodes. Flags any BlendWeight pin with a value outside [0.0, 1.0].")));

	AllChecks.Add(MakeCheck(3, TEXT("Skeleton Mismatch"), TEXT("SKEL_MISMATCH"),
		EBPDoctorSeverity::Error, EBPDoctorConfidence::Medium, EBPDoctorTier::SilentFailure, false,
		TEXT("Animation asset targets a different skeleton than the AnimBlueprint."),
		TEXT("Skeleton mismatches cause distorted meshes, bones in wrong positions, or cook/package failures."),
		TEXT("Your AnimBP is set to one skeleton (e.g. UE5 Mannequin) but one of its animations was made for a different skeleton (e.g. Mixamo or an older UE4 rig). The animation won't play correctly — bones end up in wrong positions or the asset fails to cook."),
		TEXT("WHAT'S HAPPENING: Every AnimBP has a Target Skeleton. Every animation also belongs to a skeleton. If they don't match, UE can't map the bones — you get distorted meshes or T-pose.\n\nEASIEST FIX (swap the animation):\n1. Click Navigate to open the AnimBP\n2. Find the animation node with the yellow warning badge\n3. In the Details panel on the right, find the 'Sequence' or 'Anim Sequence' property\n4. Click the dropdown and pick an animation built for the SAME skeleton your AnimBP uses\n5. Hit Compile (top-left, big button)\n\nTO CHECK YOUR SKELETON: Open the AnimBP > top-right 'Class Defaults' tab > 'Target Skeleton' field shows the name.\n\nHARDER FIX (retarget the animation to your skeleton):\n1. Window menu > Retarget Manager\n2. Set Source Skeleton = the animation's original skeleton\n3. Set Target Skeleton = your AnimBP's skeleton\n4. Map the bones (UE auto-maps most common rigs)\n5. Click 'Retarget' — creates new animations on your skeleton\n6. Come back to the AnimBP and swap to the new retargeted animation\n\nWHY THIS HAPPENS: Common cause is importing Mixamo anims or FBX from another project without retargeting first."),
		TEXT("Compares the AnimBP's TargetSkeleton against each referenced animation's Skeleton. Flags mismatches.")));

	AllChecks.Add(MakeCheck(4, TEXT("Missing Default Slot"), TEXT("MISSING_SLOT"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::Medium, EBPDoctorTier::SilentFailure, true,
		TEXT("AnimBP references montages but has no Slot node in the AnimGraph -- montages will not play."),
		TEXT("This is the #1 AnimBP question on forums. PlayMontage() silently fails without a Slot node."),
		TEXT("Your AnimBP uses montages but has no Slot node. Without a Slot, the engine has nowhere to play them."),
		TEXT("AUTO-FIX: Adds a DefaultSlot node to the AnimGraph. After fixing, open the AnimBP and connect the Slot node into your pose chain.\n\nMANUAL:\n1. Open the AnimBP > AnimGraph\n2. Right-click > Add Slot node (search 'Slot')\n3. Set the Slot Name (usually 'DefaultSlot')\n4. Connect it between your pose chain and the Output Pose\n5. Make sure your Montages use the same Slot Name"),
		TEXT("Searches AnimGraph for AnimGraphNode_Slot. Detection confidence is MEDIUM because montages may be triggered from other BPs.")));

	AllChecks.Add(MakeCheck(5, TEXT("Broken Transition"), TEXT("BROKEN_TRANS"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::Medium, EBPDoctorTier::Contextual, false,
		TEXT("State machine contains unreachable states with no inbound transitions."),
		TEXT("Unreachable states mean your character can get stuck in an animation with no way out."),
		TEXT("Your state machine has states that can never be reached -- no arrow pointing into them."),
		TEXT("1. Open the State Machine graph\n2. Look for states with no arrows pointing INTO them (only outgoing arrows)\n3. Either add a transition from another state, or delete the unreachable state\n4. Verify every state has at least one inbound transition path from the Entry node"),
		TEXT("Skips state machines with fewer than 3 states. Counts states vs transitions; if states > transitions + 1, some states may be unreachable.")));

	AllChecks.Add(MakeCheck(6, TEXT("T-Pose Fallback"), TEXT("TPOSE_FALLBACK"),
		EBPDoctorSeverity::Error, EBPDoctorConfidence::Medium, EBPDoctorTier::SilentFailure, false,
		TEXT("LayeredBoneBlend has a disconnected BasePose input, causing T-pose."),
		TEXT("This produces a partial T-pose on specific bones during specific blend scenarios."),
		TEXT("Your character will T-pose (arms out like a scarecrow) the moment this blend node runs. It's one of the most common silent-failure bugs in shipped games."),
		TEXT("WHAT'S HAPPENING: A 'Layered Blend Per Bone' node mixes two poses together — a base pose (e.g. idle) and a layer pose (e.g. upper-body aim). If the BasePose input has no connection, the node has nothing to blend FROM, so it outputs the skeleton's rest pose — T-pose.\n\nVISUAL CLUE: The BasePose input is the FIRST input pin on the LayeredBoneBlend, usually at the top-left of the node. If it has no white wire going into it, that's the bug.\n\nFIX STEPS:\n1. Click Navigate to open the AnimGraph\n2. Find the flagged 'Layered Blend Per Bone' node (has a yellow or red badge on it)\n3. Look at the top-left input pin labeled 'Base Pose'\n4. If empty: find your main pose chain (usually coming from a State Machine or a Blend Space) and drag a wire from its Output Pose INTO the Base Pose pin\n5. Hit Compile\n6. Press Play — character should no longer T-pose\n\nIF THE NODE SHOULDN'T EXIST: If you added this node by accident, select it and press Delete. Reconnect the surrounding nodes so the pose chain is continuous from the State Machine down to Output Pose.\n\nWHY THIS IS SUBTLE: UE's compiler does NOT warn about disconnected BasePose inputs. The AnimBP compiles clean. You only see the bug at runtime, which is why this ships to prod constantly."),
		TEXT("Checks LayeredBoneBlend nodes for disconnected BasePose input pins.")));

	AllChecks.Add(MakeCheck(7, TEXT("Orphaned Node"), TEXT("ORPHANED_NODE"),
		EBPDoctorSeverity::Info, EBPDoctorConfidence::Medium, EBPDoctorTier::Stylistic, true,
		TEXT("Node exists in the graph but is not reachable from the Output Pose."),
		TEXT("Orphaned nodes clutter the graph and create noise during debugging. Consider deleting them."),
		TEXT("Your AnimBP graph has nodes that aren't connected to anything. Safe to delete."),
		TEXT("AUTO-FIX: Deletes all AnimGraph nodes not reachable from the Output Pose root. Only affects top-level graph nodes (state machine contents are preserved).\n\nMANUAL:\n1. Click Navigate to find the orphaned node\n2. Check if it was accidentally disconnected (reconnect if needed)\n3. If truly unused, select it and press Delete\n4. Clean up any connected but also-orphaned nodes"),
		TEXT("Skips AnimBPs with 15 or fewer anim nodes. Walks from Output Pose root via input pins. Flags if more than 3 nodes are unreachable.")));

	AllChecks.Add(MakeCheck(8, TEXT("Invalid BlendSpace"), TEXT("INVALID_BSPACE"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::Medium, EBPDoctorTier::Contextual, false,
		TEXT("BlendSpace asset has 0 or 1 sample points -- cannot interpolate."),
		TEXT("A BlendSpace with insufficient samples produces static or broken interpolation."),
		TEXT("A BlendSpace needs at least 2 animation samples to interpolate between."),
		TEXT("1. Open the BlendSpace asset (double-click in Content Browser)\n2. Add sample points by dragging animations onto the grid\n3. Place at least 2 samples at different axis positions\n4. Preview the interpolation by moving the green crosshair"),
		TEXT("Reads BlendSpace sample count. Flags assets with fewer than 2 samples.")));

	AllChecks.Add(MakeCheck(9, TEXT("Missing Notify"), TEXT("MISSING_NOTIFY"),
		EBPDoctorSeverity::Info, EBPDoctorConfidence::Medium, EBPDoctorTier::Stylistic, false,
		TEXT("AnimNotify references a function or event that has been deleted."),
		TEXT("Missing notify handlers cause footstep sounds, VFX triggers, and gameplay events to silently stop firing."),
		TEXT("Your animation has a Notify event but there's no matching handler function."),
		TEXT("1. Open the AnimBP > Event Graph\n2. Check if the notify handler function exists (AnimNotify_[NotifyName])\n3. If deleted: right-click > Add AnimNotify Event > select the notify\n4. Reconnect the event to its gameplay logic (sound, VFX, etc.)"),
		TEXT("Checks for AnimNotify references in the AnimBP that have no corresponding handler function in the event graph.")));

	AllChecks.Add(MakeCheck(10, TEXT("Duplicate Slot Name"), TEXT("DUP_SLOT"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::High, EBPDoctorTier::SilentFailure, true,
		TEXT("The same slot name is used by multiple Slot nodes in the AnimGraph."),
		TEXT("Duplicate slot names cause montages to play on ALL matching slots simultaneously, causing animation conflicts."),
		TEXT("Two Slot nodes have the same name. Montages will play on ALL matching slots simultaneously."),
		TEXT("AUTO-FIX: Renames duplicates with _2, _3 suffixes. Use custom input to set your own name.\n\nMANUAL: Open AnimGraph > find Slot nodes > give each a unique name (e.g., UpperBody, LowerBody, FullBody)."),
		TEXT("Compares SlotName on all AnimGraphNode_Slot nodes. Exact string match — HIGH confidence.")));

	AllChecks.Add(MakeCheck(11, TEXT("Unused Variable"), TEXT("UNUSED_VAR"),
		EBPDoctorSeverity::Info, EBPDoctorConfidence::Low, EBPDoctorTier::Stylistic, false,
		TEXT("AnimBP declares many variables but very few are read in the AnimGraph (heuristic)."),
		TEXT("Unused variables create false leads during debugging."),
		TEXT("Your AnimBP declares many variables but barely uses them in the animation graph."),
		TEXT("1. Open the AnimBP > Class Defaults or My Blueprint panel\n2. Find the flagged variable\n3. Search for it in the AnimGraph (Ctrl+F)\n4. If truly unused, delete it from My Blueprint\n\nNOTE: Verify in editor — this check uses heuristics and may have false positives."),
		TEXT("Heuristic: flags AnimBPs with 12+ properties and fewer than 3 VariableGet nodes. LOW confidence — may miss property access bindings and struct patterns. Always verify in editor.")));

	AllChecks.Add(MakeCheck(12, TEXT("Deprecated Node"), TEXT("DEPRECATED_NODE"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::Medium, EBPDoctorTier::Deprecated, false,
		TEXT("AnimGraph uses a node class marked CLASS_Deprecated."),
		TEXT("Deprecated nodes will break on the next engine upgrade."),
		TEXT("Your AnimBP uses a node type that Epic has marked as deprecated."),
		TEXT("1. Click Navigate to find the deprecated node\n2. Hover over it to see the deprecation warning\n3. Right-click > Find Replacement (if available)\n4. Replace with the modern equivalent node\n5. Reconnect all pins and verify behavior"),
		TEXT("Checks node class flags for CLASS_Deprecated. Reliable across engine versions.")));

	// General BP Checks (13-26)
	AllChecks.Add(MakeCheck(13, TEXT("Broken Asset Reference"), TEXT("BP_BROKEN_REF"),
		EBPDoctorSeverity::Error, EBPDoctorConfidence::High, EBPDoctorTier::SilentFailure, false,
		TEXT("Blueprint references an asset path that does not exist on disk."),
		TEXT("Broken references cause crashes, failed loads, or silent null behavior at runtime."),
		TEXT("Your Blueprint references another asset that has been deleted or moved."),
		TEXT("1. Click Navigate to open the Blueprint\n2. Look for nodes with red 'Missing' errors or yellow warning icons\n3. Right-click the broken reference > Browse to Asset (will fail)\n4. Replace with a valid asset reference, or delete the node\n5. Check Content Browser > Filters > Show Redirectors for moved assets"),
		TEXT("Scans all object references in the Blueprint package. Flags paths that don't resolve via AssetRegistry.")));

	AllChecks.Add(MakeCheck(14, TEXT("Excessive Complexity"), TEXT("BP_COMPLEXITY"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::Medium, EBPDoctorTier::Stylistic, false,
		TEXT("Blueprint has an extremely high node count (100+ unique nodes)."),
		TEXT("Complex Blueprints are harder to maintain, debug, and optimize."),
		TEXT("This Blueprint has over 100 nodes. Consider breaking it into smaller functions."),
		TEXT("1. Open the Blueprint and assess which logic can be grouped\n2. Select related nodes > right-click > Collapse to Function\n3. Consider moving heavy computation to C++ (better performance + debugging)\n4. Split responsibilities: one BP per concern, not one mega-BP"),
		TEXT("Counts unique graph nodes across all graphs. Threshold: 100+ nodes. MEDIUM confidence — node count alone doesn't determine complexity.")));

	AllChecks.Add(MakeCheck(15, TEXT("Empty Event Graph"), TEXT("BP_EMPTY_GRAPH"),
		EBPDoctorSeverity::Info, EBPDoctorConfidence::High, EBPDoctorTier::Stylistic, false,
		TEXT("Blueprint contains very few logic nodes (fewer than 3)."),
		TEXT("Empty Blueprints clutter the project, confuse team members, and waste compile time."),
		TEXT("This Blueprint has no logic inside it. Delete it if not needed."),
		TEXT("1. Verify this BP isn't used as a data-only Blueprint (check for variables/components)\n2. If truly empty: right-click in Content Browser > Delete\n3. Fix Up Redirectors after deleting to clean up references\n4. If it's a parent class: check if child BPs depend on it"),
		TEXT("Counts meaningful nodes (excludes default Event nodes). Flags BPs with 0-2 logic nodes.")));

	AllChecks.Add(MakeCheck(16, TEXT("Tick Performance Risk"), TEXT("BP_TICK_HEAVY"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::Medium, EBPDoctorTier::Contextual, false,
		TEXT("Blueprint has Event Tick enabled with high node complexity."),
		TEXT("Event Tick runs every frame for every instance. Complex Tick = major FPS drops."),
		TEXT("Event Tick runs code EVERY FRAME. Use a Timer instead for heavy work."),
		TEXT("1. Open the Blueprint > Event Graph > find Event Tick\n2. Move non-essential logic to: Set Timer by Event (0.1-0.5s intervals)\n3. For checks: use Event-driven patterns (overlap events, delegates)\n4. Class Defaults > uncheck 'Start with Tick Enabled' if Tick isn't needed\n5. For C++ actors: set TickInterval to reduce frequency"),
		TEXT("Detects Event Tick node alongside 30+ total nodes. MEDIUM confidence — doesn't verify the expensive nodes are in the Tick execution path.")));

	AllChecks.Add(MakeCheck(17, TEXT("Self-Cast Detected"), TEXT("BP_SELF_CAST"),
		EBPDoctorSeverity::Info, EBPDoctorConfidence::High, EBPDoctorTier::Stylistic, true,
		TEXT("Blueprint casts to its own class type (unnecessary overhead)."),
		TEXT("Casting to Self always succeeds and creates an unnecessary hard reference. Replace with a direct Self reference."),
		TEXT("Your Blueprint casts to its own type. Use 'Self' reference instead."),
		TEXT("AUTO-FIX: Removes the Cast node and reroutes connections through the source pin.\n\nMANUAL:\n1. Find the Cast-to-Self node\n2. Note what's connected to the 'As [ClassName]' output pin\n3. Delete the Cast node\n4. Drag from 'Self' reference and connect to where the cast output was used"),
		TEXT("Compares Cast node TargetType against the Blueprint's own GeneratedClass. Exact match — HIGH confidence.")));

	AllChecks.Add(MakeCheck(18, TEXT("Deprecated API Usage"), TEXT("BP_DEPRECATED_FUNC"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::Medium, EBPDoctorTier::Deprecated, false,
		TEXT("Blueprint uses functions or classes marked as deprecated."),
		TEXT("Deprecated APIs will be removed in future engine versions."),
		TEXT("This Blueprint calls deprecated functions. They work now but will be removed."),
		TEXT("1. Click Navigate to find the deprecated node\n2. Hover over it — the tooltip shows the deprecation message and suggested replacement\n3. Delete the deprecated node\n4. Add the replacement function (usually has a similar name)\n5. Reconnect pins and test"),
		TEXT("Checks function metadata for the 'DeprecatedFunction' tag.")));

	AllChecks.Add(MakeCheck(19, TEXT("Circular Dependency"), TEXT("BP_CIRCULAR_DEP"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::Medium, EBPDoctorTier::Contextual, false,
		TEXT("Two Blueprints reference each other, creating a circular dependency."),
		TEXT("Circular dependencies cause unpredictable load order, editor hitches, and potential crashes."),
		TEXT("Two Blueprints reference each other. Use a Blueprint Interface to break the cycle."),
		TEXT("1. Identify which BP should 'own' the relationship\n2. Create a Blueprint Interface (right-click > Blueprint > Blueprint Interface)\n3. Move the shared function signatures to the Interface\n4. Have the dependent BP implement the Interface instead of casting\n5. Replace Cast nodes with Interface calls (Message nodes)"),
		TEXT("Uses AssetRegistry dependency tracking to detect bidirectional package references. MEDIUM confidence — only detects package-level deps, not pin-level.")));

	AllChecks.Add(MakeCheck(20, TEXT("Oversized Blueprint Asset"), TEXT("BP_MASSIVE_ASSET"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::High, EBPDoctorTier::Contextual, false,
		TEXT("Blueprint .uasset file is abnormally large (>5MB)."),
		TEXT("Oversized files slow down editor load times, version control, and cooking."),
		TEXT("This Blueprint file is unusually large (over 5MB). Normal Blueprints are under 1MB."),
		TEXT("1. Check for embedded data: large arrays, mesh data, or texture references stored as defaults\n2. Move large data to separate Data Assets or Data Tables\n3. Check for excessive node graphs (see BP_COMPLEXITY check)\n4. Right-click > Size Map in Content Browser to see what's consuming space"),
		TEXT("Reads the .uasset file size from disk. Threshold: 5MB. Deterministic — HIGH confidence.")));

	AllChecks.Add(MakeCheck(21, TEXT("Hard Reference Bloat"), TEXT("BP_HARD_REF"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::Medium, EBPDoctorTier::Contextual, false,
		TEXT("Blueprint has excessive hard references to other Blueprint classes."),
		TEXT("Each Cast-to-Blueprint forces the target AND all dependencies into memory at load time."),
		TEXT("This Blueprint has many hard references via Cast nodes. Use Interfaces or Soft References."),
		TEXT("1. Open the Blueprint and identify Cast-to-Blueprint nodes\n2. Replace casts with Blueprint Interface calls where possible\n3. For asset loading: use Soft Object References (TSoftObjectPtr) + Async Load\n4. Use the Reference Viewer (right-click > Reference Viewer) to visualize the dependency chain"),
		TEXT("Counts Cast-to-Blueprint nodes. Each creates a hard reference. Threshold: 5+ casts. MEDIUM confidence — some casts are necessary.")));

	AllChecks.Add(MakeCheck(22, TEXT("Expensive Operations in Tick"), TEXT("BP_EXPENSIVE_TICK"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::Medium, EBPDoctorTier::Contextual, false,
		TEXT("Blueprint has expensive query operations alongside Event Tick."),
		TEXT("GetAllActorsOfClass and similar queries inside Tick run every frame for every instance."),
		TEXT("Expensive search functions alongside Event Tick will tank FPS. Move to Timer or BeginPlay."),
		TEXT("1. Find the expensive node (GetAllActorsOfClass, SweepMulti, etc.)\n2. Move it to BeginPlay and cache the result in a variable\n3. Or use Set Timer by Event to run it periodically (every 0.2-0.5s)\n4. For actor finding: use Actor Tags + GetAllActorsWithTag (faster)\n5. Single line traces in Tick are usually OK — bulk queries are the problem"),
		TEXT("Detects expensive function calls (GetAllActorsOfClass, etc.) coexisting with Event Tick. MEDIUM confidence — doesn't verify execution flow.")));

	AllChecks.Add(MakeCheck(23, TEXT("Debug Nodes in Production"), TEXT("BP_DEBUG_NODES"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::High, EBPDoctorTier::Stylistic, true,
		TEXT("Blueprint contains PrintString or DrawDebug nodes."),
		TEXT("PrintString executes in Shipping builds (logs to output). DrawDebug is compiled out but clutters the graph."),
		TEXT("Debug nodes should be removed before shipping. PrintString still runs in packaged builds."),
		TEXT("AUTO-FIX: Deletes all PrintString and DrawDebug nodes, rerouting execution pins.\n\nMANUAL:\n1. Search the BP for 'PrintString' and 'DrawDebug' (Ctrl+F)\n2. Delete each debug node\n3. Reconnect the execution (white) pins around the deleted nodes\n4. Consider using UE_LOG in C++ for persistent logging instead"),
		TEXT("Searches for K2Node_CallFunction nodes calling PrintString, DrawDebug*, etc. Exact function name match — HIGH confidence.")));

	AllChecks.Add(MakeCheck(24, TEXT("Construction Script Misuse"), TEXT("BP_CONSTRUCT_HEAVY"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::High, EBPDoctorTier::Contextual, false,
		TEXT("Construction Script contains spawning or heavy query operations."),
		TEXT("Construction Script runs in the editor every time a property changes. Heavy ops cause editor freezes."),
		TEXT("Heavy operations like SpawnActor in Construction Script cause editor freezes. Move to BeginPlay."),
		TEXT("1. Open the Blueprint > Construction Script graph\n2. Find SpawnActor, GetAllActorsOfClass, or similar heavy nodes\n3. Move them to the BeginPlay event in the Event Graph\n4. Construction Script should only set variables, configure components, or do lightweight setup\n5. If you need editor-visible spawning, use ChildActorComponents instead"),
		TEXT("Scans Construction Script graph for SpawnActor, query operations, and other heavy calls. HIGH confidence — these patterns reliably cause editor issues.")));

	AllChecks.Add(MakeCheck(25, TEXT("ForEach Loop Performance"), TEXT("BP_FOREACH_PERF"),
		EBPDoctorSeverity::Info, EBPDoctorConfidence::Medium, EBPDoctorTier::Stylistic, false,
		TEXT("ForEachLoop re-evaluates pure input nodes on every iteration."),
		TEXT("ForEachLoop re-evaluates pure input expressions every iteration, multiplying the cost of connected queries."),
		TEXT("ForEachLoop re-runs input expressions on every pass. Cache the array in a variable first."),
		TEXT("1. Find the ForEachLoop macro node\n2. Check what's connected to its Array input\n3. If it's a function call (GetComponentsByClass, etc.): cache it first\n4. Create a local variable, assign the query result to it BEFORE the loop\n5. Connect the variable to the ForEachLoop input instead"),
		TEXT("Detects ForEachLoop macro alongside expensive function calls in the same Blueprint. MEDIUM confidence — doesn't verify the expensive call is the loop's input.")));

	AllChecks.Add(MakeCheck(26, TEXT("Excessive Timeline Components"), TEXT("BP_TIMELINE_HEAVY"),
		EBPDoctorSeverity::Info, EBPDoctorConfidence::Medium, EBPDoctorTier::Stylistic, false,
		TEXT("Blueprint has multiple Timeline nodes creating hidden tick overhead."),
		TEXT("Each Timeline creates a hidden UTimelineComponent that ticks every frame."),
		TEXT("Each Timeline node creates a hidden per-frame cost. Consider merging Timelines."),
		TEXT("1. Identify which Timelines can be merged (similar curves/durations)\n2. Combine into one Timeline with multiple output tracks\n3. For simple lerps: use FInterpTo/FInterpConstantTo in Tick with a low tick rate\n4. For one-shot animations: consider using Set Timer instead of a Timeline"),
		TEXT("Counts K2Node_Timeline instances. Threshold: 3+ Timelines. MEDIUM confidence — multiple Timelines may be intentional.")));

	// ── AnimBP Checks v2 (27-34) — Phase 2C Bible-alignment audit (2026-04-16) ──

	AllChecks.Add(MakeCheck(27, TEXT("MotionMatching Node Missing Database"), TEXT("MM_NO_DATABASE"),
		EBPDoctorSeverity::Error, EBPDoctorConfidence::High, EBPDoctorTier::SilentFailure, false,
		TEXT("MotionMatching node has no Pose Search Database assigned — outputs T-pose silently."),
		TEXT("Without a Database, the MM node cannot select poses and the character falls back to T-pose. This is the #1 silent failure in Bible-aligned AAA locomotion."),
		TEXT("Your MotionMatching node is missing its Database. Assign a UPoseSearchDatabase asset to fix."),
		TEXT("1. Open the AnimBP > AnimGraph\n2. Find the MotionMatching node\n3. In its Details panel, set the Database property to a valid UPoseSearchDatabase\n4. Ensure the database has been built (has index data)\n5. Compile and save the AnimBP"),
		TEXT("Walks all AnimGraph nodes. Matches by class name 'AnimGraphNode_MotionMatching' (no PoseSearch link required). Uses FProperty reflection to read the Database property.")));

	AllChecks.Add(MakeCheck(28, TEXT("MotionMatching Missing Inertialization"), TEXT("MM_NO_INERTIALIZATION"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::Medium, EBPDoctorTier::SilentFailure, false,
		TEXT("MotionMatching node output chain has no Inertialization node downstream — pose pops visible on every database change."),
		TEXT("MM selects a new pose every query. Without Inertialization smoothing, every selection produces a visible pop. This is textbook AAA locomotion guidance."),
		TEXT("Your MotionMatching doesn't have Inertialization smoothing. You'll see jerky pops when the DB changes selections."),
		TEXT("1. Open AnimGraph, find the MotionMatching node\n2. Right-click > Add 'Inertialization' node after MM output\n3. Connect MM.Pose -> Inertialization.Source\n4. Connect Inertialization output to the next node in the chain\n5. Default blend time (0.2s) is usually fine"),
		TEXT("Walks nodes linked directly off MM's Pose output pin. Flags if no 'AnimGraphNode_Inertialization' appears before a Slot, LayeredBoneBlend, or Root node.")));

	AllChecks.Add(MakeCheck(29, TEXT("Slot Name Not Registered in Skeleton"), TEXT("SLOT_NAME_MISMATCH"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::Medium, EBPDoctorTier::SilentFailure, false,
		TEXT("Slot node uses a SlotName that isn't registered in the Skeleton's slot groups — montages targeting this slot will silently fail."),
		TEXT("Montages route by slot name. If the slot node's name isn't in the skeleton's registered slots, Play_Montage will not route events to this slot."),
		TEXT("One of your Slot nodes uses a name that isn't registered in the skeleton. Montages won't play on it."),
		TEXT("1. Open the Skeleton asset (the AnimBP's TargetSkeleton)\n2. Window > Anim Slot Manager\n3. Verify the slot name from the flagged Slot node exists (e.g., 'DefaultSlot', 'UpperBody')\n4. If missing: Add Slot with that name, assign to a Slot Group\n5. Save the skeleton"),
		TEXT("Reads SlotName on every AnimGraphNode_Slot, compares against USkeleton->GetSlotNames() (all registered slot names across slot groups). Flags names not found.")));

	// Sprint 5 Phase B P5: re-tagged Contextual → SilentFailure. The broken-link variant
	// (UseCachedPose with broken link to Save node OR UseCachedPose with no matching Save)
	// outputs T-pose at runtime — that's textbook SilentFailure (compiles clean, ships, costs
	// hours). The dead-Save-only variant is genuinely Contextual but the check fires on both;
	// upgrading the tier means the SilentFailures profile catches the T-pose case.
	AllChecks.Add(MakeCheck(30, TEXT("Dead Cached Pose"), TEXT("DEAD_CACHED_POSE"),
		EBPDoctorSeverity::Info, EBPDoctorConfidence::High, EBPDoctorTier::SilentFailure, false,
		TEXT("SaveCachedPose without matching UseCachedPose (or vice versa) — orphan node contributes no value."),
		TEXT("A SaveCachedPose with no UseCachedPose is dead weight that still evaluates. A UseCachedPose with no SaveCachedPose outputs T-pose."),
		TEXT("You have a Cached Pose mismatch — either a Save with no Use, or a Use with no Save of the same name."),
		TEXT("1. Open the AnimGraph\n2. Find all SaveCachedPose and UseCachedPose nodes\n3. For each SaveCachedPose without a matching Use: either delete it or connect a UseCachedPose\n4. For each UseCachedPose without a matching Save: fix the cache name OR delete it\n5. Cache names must match EXACTLY (case-sensitive)"),
		TEXT("Builds a map of SaveCachedPose.CacheName -> UseCachedPose.CacheName. Names appearing on only one side are orphans.")));

	AllChecks.Add(MakeCheck(31, TEXT("Empty State Machine"), TEXT("EMPTY_SM"),
		EBPDoctorSeverity::Error, EBPDoctorConfidence::High, EBPDoctorTier::SilentFailure, false,
		TEXT("State machine has zero states or the Entry node has no outbound linked transition — evaluation freezes on entry."),
		TEXT("An empty SM or an SM with no Entry connection causes the character to freeze the moment the SM is evaluated."),
		TEXT("Your state machine is missing states or the Entry node isn't connected to anything."),
		TEXT("1. Double-click the State Machine node to open its sub-graph\n2. If zero states: add at least one state (right-click > Add State)\n3. Drag from the Entry node (or the green dot at top) to your initial state\n4. If ambiguous: set a default state via right-click > Set as Default"),
		TEXT("For every AnimGraphNode_StateMachine: checks EditorStateMachineGraph->Nodes for AnimStateNode count, and verifies the AnimStateEntryNode has at least one outbound pin linked.")));

	AllChecks.Add(MakeCheck(32, TEXT("Blend Weights Don't Sum to 1"), TEXT("BLEND_WT_SUM"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::Medium, EBPDoctorTier::SilentFailure, true,
		TEXT("LayeredBoneBlend BlendWeights sum is outside [0.95, 1.05] — partial blending produces unexpected pose bias."),
		TEXT("When all BlendWeight defaults sum to less than 1.0, the base pose leaks through proportionally. Above 1.0, bones over-blend."),
		TEXT("Your LayeredBoneBlend has weights that don't sum to 1.0. Fixing will normalize the blend."),
		TEXT("AUTO-FIX: Normalizes all BlendWeight defaults to sum to 1.0 proportionally.\n\nMANUAL: Open the LayeredBoneBlend Details panel, set each BlendWeights_N to values that sum to 1.0 (e.g., 0.5 + 0.5, or 1.0 + 0.0)."),
		TEXT("Sums all BlendWeight pin defaults on each LayeredBoneBlend. Flags if the total is outside [0.95, 1.05].")));

	AllChecks.Add(MakeCheck(33, TEXT("LayeredBoneBlend Has Empty Bone Filter"), TEXT("EMPTY_BRANCH_FILTER"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::High, EBPDoctorTier::SilentFailure, false,
		TEXT("LayeredBoneBlend layer has no BranchFilters configured — blends the entire skeleton, defeating the purpose of the node."),
		TEXT("LayeredBoneBlend is meant to blend a SUBSET of bones (e.g., upper body only). An empty filter blends everything, making it a simple two-way blend with extra cost."),
		TEXT("Your LayeredBoneBlend has a layer with no bone filter. It's blending the whole skeleton — usually a mistake."),
		TEXT("1. Find the LayeredBoneBlend node\n2. In Details panel, expand Layer Setup > Branch Filters\n3. Add an FBranchFilter entry with a BoneName (e.g., 'spine_01') and BlendDepth (e.g., 1 for full subtree)\n4. Reconstruct the node (right-click > Reconstruct Node) to sync runtime arrays"),
		TEXT("Ported from AnimBPDoctor v1.1.0. Checks UAnimGraphNode_LayeredBoneBlend's Node.LayerSetup[].BranchFilters array length for each layer.")));

	// ── AnimBP Checks v3 (35-39) — Sprint 5 Phase D coverage expansion (2026-04-24) ──
	// Declaration-order note: #34 (DISCONNECTED_SLOT_SRC, declared below) was already in place
	// when these were added. Phase D appended 35-39 via prepend rather than reordering the
	// existing #34 entry — Sacred Rule #4 (only-asked) + Sacred Rule #3 (don't churn confirmed
	// fixes). The "Checks" admin dialog renders in declaration order, so #34 appears last;
	// functionally inconsequential — runtime dispatch is by CheckCode string match in RunCheck.
	AllChecks.Add(MakeCheck(35, TEXT("RootMotion Mode Mismatch"), TEXT("ROOTMOTION_MODE_MISMATCH"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::High, EBPDoctorTier::SilentFailure, false,
		TEXT("AnimBP RootMotionMode is RootMotionFromMontagesOnly or IgnoreRootMotion but referenced sequences have EnableRootMotion=true."),
		TEXT("RootMotionFromMontagesOnly silently drops root motion from non-montage SequencePlayers. IgnoreRootMotion extracts then discards it — character pivots in-place instead of moving."),
		TEXT("Your character won't move forward correctly — root motion from one or more animations is being silently dropped at runtime."),
		TEXT("WHAT'S HAPPENING: Two settings interact: the AnimBP's RootMotionMode (Class Defaults > Root Motion Mode) and each AnimSequence's EnableRootMotion flag. Mismatches cause silent drops.\n\n1. Click Navigate to open the AnimBP\n2. Open Class Defaults (top-right tab) > Root Motion Mode\n3. Either change to 'Root Motion From Everything' (consumes from sequences AND montages)\n4. OR open the flagged animation > disable EnableRootMotion (if motion shouldn't drive the character)\n5. Compile and test in-game\n\nMOST COMMON FIX: Set RootMotionMode = Root Motion From Everything. This is what AAA locomotion systems use."),
		TEXT("Reads RootMotionMode from AnimBP CDO. Walks SequencePlayer + BlendSpacePlayer nodes, checks UAnimSequence::bEnableRootMotion against the mode.")));

	AllChecks.Add(MakeCheck(36, TEXT("LinkedAnimLayer No Layer Selected"), TEXT("LINKED_LAYER_NO_LAYER"),
		EBPDoctorSeverity::Error, EBPDoctorConfidence::High, EBPDoctorTier::SilentFailure, false,
		TEXT("LinkedAnimLayer node has no Layer name selected — outputs T-pose silently."),
		TEXT("A LinkedAnimLayer with no Layer name has no pose chain to evaluate. The entire sub-graph it drives produces T-pose at runtime."),
		TEXT("Your LinkedAnimLayer node is missing a Layer selection. The character will T-pose in whatever part of the graph this node feeds."),
		TEXT("WHAT'S HAPPENING: Linked Anim Layers route a piece of the AnimGraph to an interface implementation (often used for modular rigs — upper body vs lower body, vehicles vs on-foot). The Layer field tells the node WHICH layer to play. Empty Layer = T-pose.\n\n1. Click Navigate to open the AnimGraph\n2. Find the flagged LinkedAnimLayer node (yellow/red badge)\n3. In the Details panel, find the 'Layer' dropdown\n4. Select the layer name from your AnimLayerInterface (e.g. 'Locomotion', 'UpperBody')\n5. If no layer interface exists yet, you may want a Linked Anim Graph node instead\n6. Hit Compile\n\nSELF-LAYER NOTE: Leaving the external Interface unset is fine — the node will route to THIS AnimBP's own implementation of the layer. But the Layer field MUST be set."),
		TEXT("Walks UAnimGraphNode_LinkedAnimLayer nodes (SM-recursive). Flags any where FAnimNode_LinkedAnimLayer::Layer.IsNone().")));

	AllChecks.Add(MakeCheck(37, TEXT("Curve-Alpha References Missing Skeleton Curve"), TEXT("CURVE_ALPHA_MISSING"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::High, EBPDoctorTier::SilentFailure, false,
		TEXT("Blend node uses AlphaInputType=Curve with a curve name not present in the skeleton — blend alpha is permanently 0."),
		TEXT("When AlphaCurveName doesn't exist in skeleton metadata, the runtime returns 0 every frame. The blend never activates regardless of input animation values."),
		TEXT("A blend node's curve-driven alpha references a curve that was deleted (or never added) on the skeleton. The blend is stuck at 0 — the layered animation never appears."),
		TEXT("WHAT'S HAPPENING: Some blend nodes (Apply Mesh Space Additive, Blend List By Bool, etc.) can be driven by a curve value via AlphaInputType=Curve. The node looks up AlphaCurveName on the skeleton's curve metadata each frame. If that curve doesn't exist, it reads 0 and the blend never triggers.\n\n1. Click Navigate to find the flagged blend node\n2. Note the curve name in the issue description (e.g. 'AimWeight')\n3. Either: open the Skeleton asset > Window > Curves > add the missing curve\n4. OR: change the node's AlphaInputType to Float and drive it from a variable instead\n5. Compile and test the blend triggers correctly\n\nWHY IT'S SUBTLE: The AnimBP compiles clean. The node runs. It just always reads 0. You'd only notice in-game when the blended animation never plays."),
		TEXT("Reflects over all anim graph nodes' inner Node structs. Finds AlphaInputType=Curve, reads AlphaCurveName, validates against USkeleton::GetCurveMetaData().")));

	AllChecks.Add(MakeCheck(38, TEXT("AnimMontage Section Loops With No Exit"), TEXT("MONTAGE_SECTION_LOOP"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::High, EBPDoctorTier::SilentFailure, false,
		TEXT("AnimMontage referenced by this AnimBP has a section whose NextSectionName points to itself or to a closed cycle with no terminal section."),
		TEXT("Self-looping or cycle-with-no-exit sections trap the montage in an infinite loop. The character locks into the montage and gameplay code can't recover without an explicit Stop call."),
		TEXT("A montage will play forever — it loops back to itself with no way out. Gameplay code expecting Montage_Ended won't receive the event."),
		TEXT("WHAT'S HAPPENING: AnimMontage Composite Sections form a chain: each section has a 'Next Section' field. NAME_None = end. If section A points to A (self-loop), or A->B->A (closed cycle), the montage never finishes.\n\n1. Click Navigate (opens the montage)\n2. Look at Sections panel (bottom of montage editor)\n3. Find the section with the loop\n4. In its Details panel, set 'Next Section Name' to None (terminal) OR to a real exit section\n5. Save the montage\n\nIF THE LOOP IS INTENTIONAL (e.g. ammo-loaded loop in a reload montage with explicit Stop): consider tagging the section name to make the intent obvious (e.g. 'Loop_NeedsStop'). The check still fires but the team knows it's intentional."),
		TEXT("Walks K2Node_CallFunction nodes calling Montage_Play / PlayMontage. Reads the literal Montage pin's DefaultObject, dedupes, then walks UAnimMontage::CompositeSections detecting self-loops and closed cycles via DFS.")));

	AllChecks.Add(MakeCheck(39, TEXT("BlendSpace Axis Has Zero Range"), TEXT("BLENDSPACE_ZERO_AXIS"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::High, EBPDoctorTier::SilentFailure, false,
		TEXT("BlendSpace asset has an axis where Min == Max — interpolation is impossible along that axis."),
		TEXT("A zero-range axis collapses the BlendSpace to a single point along that dimension. All input values in any direction map to the same output, defeating the purpose of blending."),
		TEXT("Your BlendSpace can't actually blend on one of its axes. The Min and Max values are the same — there's no range to interpolate across."),
		TEXT("WHAT'S HAPPENING: A BlendSpace 1D has 1 axis (e.g. Speed: 0..600). A BlendSpace 2D has 2 axes (e.g. Speed: 0..600, Direction: -180..180). Each axis must have Min < Max for interpolation. If Min == Max, that axis is broken.\n\n1. Click Navigate (opens the BlendSpace)\n2. In Details panel, expand 'Horizontal Axis' (and 'Vertical Axis' if 2D)\n3. Check Min and Max fields\n4. Set Min and Max to a sensible range (e.g. Speed: 0 to 600)\n5. Re-place sample points across the new range\n6. Save\n\nCOMMON CAUSE: Forgot to set Max after setting Min, or copy-pasted parameters between BlendSpaces and missed updating one axis."),
		TEXT("Walks BlendSpacePlayer nodes (existing pattern). Reads UBlendSpace::GetBlendParameter(0/1), flags axes where FMath::IsNearlyEqual(Min, Max).")));

	AllChecks.Add(MakeCheck(34, TEXT("Slot Node Source Pin Disconnected"), TEXT("DISCONNECTED_SLOT_SRC"),
		EBPDoctorSeverity::Warning, EBPDoctorConfidence::High, EBPDoctorTier::SilentFailure, false,
		TEXT("Slot node exists but its Source input pin has no connection — slot will output T-pose when no montage is active."),
		TEXT("A Slot node with disconnected Source plays montages over T-pose instead of over the base pose. Character snaps to T-pose between montages."),
		TEXT("Your character will T-pose between montages. Every time a montage (attack, reload, reaction) finishes, the character snaps into T-pose for a frame before returning to idle."),
		TEXT("WHAT'S HAPPENING: A Slot node is where montages 'play over' your base animation. The node has two inputs:\n  - Source (input): the base pose the slot mixes montages over\n  - (no label, output): the final result after the montage plays\n\nIf Source has no connection, the slot has no base pose to fall back to when no montage is active — so it outputs T-pose.\n\nVISUAL CLUE: The Slot node's left-side input pin (Source) has no white wire going into it. In the node's title you'll see the slot name, e.g. 'DefaultSlot'.\n\nFIX STEPS:\n1. Click Navigate to open the AnimGraph\n2. Find the flagged Slot node (yellow badge on it)\n3. Look at its left input pin labeled 'Source'\n4. Find your base pose (the node that was outputting the animation before the Slot was added — usually the State Machine output, or the main Blend Space)\n5. Drag a wire from the base pose's output pin INTO the Slot's Source pin\n6. Hit Compile\n7. Test in-game: play a montage, let it finish — character should return to idle, not T-pose\n\nTYPICAL POSE CHAIN:\n  State Machine -> Slot (DefaultSlot) -> Output Pose\nThe Slot's Source input comes FROM the State Machine. The Slot's output goes TO Output Pose.\n\nIF THE SLOT ISN'T USED: If no montage ever plays on this slot, you can delete the Slot node entirely — select it, press Delete, then reconnect the State Machine output directly to the next node in your chain."),
		TEXT("Ported from AnimBPDoctor v1.1.0. Checks each AnimGraphNode_Slot for a pin named 'Source' (or the first input pin) and verifies LinkedTo.Num() > 0.")));
}

const TArray<FBPDoctorCheckDef>& FBPDoctorChecks::GetAllChecks()
{
	InitChecks();
	if (!bCustomRulesLoaded)
	{
		LoadCustomRules();
		bCustomRulesLoaded = true;
	}
	return AllChecks;
}

void FBPDoctorChecks::SetDisabledChecks(const TSet<FString>& Codes)
{
	DisabledCheckCodes = Codes;
}

void FBPDoctorChecks::RefreshCustomRules()
{
	bCustomRulesLoaded = false;
}

EBPDoctorProfile FBPDoctorChecks::GetActiveProfile()
{
	return ActiveProfile;
}

void FBPDoctorChecks::SetActiveProfile(EBPDoctorProfile Profile)
{
	ActiveProfile = Profile;
}

bool FBPDoctorChecks::IsTierInProfile(EBPDoctorTier Tier, EBPDoctorProfile Profile)
{
	// Silent Failures Only: pure-value checks. Bug compiles, ships, costs hours.
	// Standard: adds real-world contextual smells (perf, architecture).
	// Everything: includes stylistic + UE-compiler-redundant "deprecated" checks.
	switch (Profile)
	{
		case EBPDoctorProfile::SilentFailuresOnly:
			return Tier == EBPDoctorTier::SilentFailure;
		case EBPDoctorProfile::Standard:
			return Tier == EBPDoctorTier::SilentFailure
				|| Tier == EBPDoctorTier::Contextual;
		case EBPDoctorProfile::Everything:
			return true;
		default:
			return true;
	}
}

const FBPDoctorCheckDef* FBPDoctorChecks::FindCheck(const FString& Code)
{
	InitChecks();
	for (const auto& Check : AllChecks)
	{
		if (Check.Code == Code) return &Check;
	}
	return nullptr;
}

// ─────────────────────────────────────────────────────────────────
//  CUSTOM RULES (user-defined via JSON)
// ─────────────────────────────────────────────────────────────────

void FBPDoctorChecks::LoadCustomRules()
{
	// Remove any previously loaded custom rules (IDs >= 100)
	AllChecks.RemoveAll([](const FBPDoctorCheckDef& C) { return C.Id >= 100; });

	FString RulesPath = FPaths::ProjectSavedDir() / TEXT("BPDoctor") / TEXT("CustomRules.json");
	FString JsonString;
	if (!FFileHelper::LoadFileToString(JsonString, *RulesPath)) return;

	TSharedPtr<FJsonObject> Root;
	TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(JsonString);
	if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid()) return;

	const TArray<TSharedPtr<FJsonValue>>* RulesArray;
	if (!Root->TryGetArrayField(TEXT("rules"), RulesArray)) return;

	int32 CustomId = 100;
	for (const auto& RuleVal : *RulesArray)
	{
		const TSharedPtr<FJsonObject>* RuleObj;
		if (!RuleVal->TryGetObject(RuleObj)) continue;

		FBPDoctorCheckDef Def;
		Def.Id = CustomId++;
		Def.bAutoFixable = false;

		// v2.7.3 audit fix: TryGetStringField (not GetStringField) so a malformed
		// CustomRules.json missing required keys skips the rule rather than crashing
		// the editor on a JSON-value-access assertion. Required: name + code + type.
		// All others fall back to safe defaults.
		FString TypeStr;
		if (!(*RuleObj)->TryGetStringField(TEXT("name"), Def.Name)) continue;
		if (!(*RuleObj)->TryGetStringField(TEXT("code"), Def.Code)) continue;
		if (!(*RuleObj)->TryGetStringField(TEXT("type"), TypeStr)) continue;
		TypeStr = TypeStr.ToLower();

		// v2.7.4 audit fix: collision detection — if a custom rule's code matches a
		// built-in (Id < 100), the user has accidentally shadowed it. Skip the custom
		// rule and warn rather than producing silent double-reports on every scan.
		bool bCollidesWithBuiltIn = false;
		for (const FBPDoctorCheckDef& Existing : AllChecks)
		{
			if (Existing.Id < 100 && Existing.Code.Equals(Def.Code, ESearchCase::IgnoreCase))
			{
				bCollidesWithBuiltIn = true;
				break;
			}
		}
		if (bCollidesWithBuiltIn)
		{
			UE_LOG(LogBPDoctor, Warning,
				TEXT("LoadCustomRules: custom rule code '%s' collides with a built-in check — skipping. Rename your rule code to avoid double-reports."),
				*Def.Code);
			continue;
		}

		(*RuleObj)->TryGetStringField(TEXT("description"), Def.Description);
		(*RuleObj)->TryGetStringField(TEXT("why_it_matters"), Def.WhyItMatters);
		(*RuleObj)->TryGetStringField(TEXT("beginner_tip"), Def.BeginnerTip);

		FString SevStr;
		(*RuleObj)->TryGetStringField(TEXT("severity"), SevStr);
		SevStr = SevStr.ToUpper();
		Def.Severity = (SevStr == TEXT("ERROR")) ? EBPDoctorSeverity::Error :
			(SevStr == TEXT("WARNING")) ? EBPDoctorSeverity::Warning : EBPDoctorSeverity::Info;

		FString ConfStr;
		(*RuleObj)->TryGetStringField(TEXT("confidence"), ConfStr);
		ConfStr = ConfStr.ToUpper();
		Def.Confidence = (ConfStr == TEXT("HIGH")) ? EBPDoctorConfidence::High :
			(ConfStr == TEXT("LOW")) ? EBPDoctorConfidence::Low : EBPDoctorConfidence::Medium;

		if (TypeStr == TEXT("banned_function"))
		{
			Def.CustomRule.Type = EBPDoctorRuleType::BannedFunction;
			if (!(*RuleObj)->TryGetStringField(TEXT("function_name"), Def.CustomRule.MatchString)) continue;
		}
		else if (TypeStr == TEXT("banned_node"))
		{
			Def.CustomRule.Type = EBPDoctorRuleType::BannedNode;
			if (!(*RuleObj)->TryGetStringField(TEXT("node_class_contains"), Def.CustomRule.MatchString)) continue;
		}
		else if (TypeStr == TEXT("required_node"))
		{
			Def.CustomRule.Type = EBPDoctorRuleType::RequiredNode;
			if (!(*RuleObj)->TryGetStringField(TEXT("node_class_contains"), Def.CustomRule.MatchString)) continue;
			(*RuleObj)->TryGetBoolField(TEXT("animBP_only"), Def.CustomRule.bAnimBPOnly);
		}
		else if (TypeStr == TEXT("node_limit"))
		{
			Def.CustomRule.Type = EBPDoctorRuleType::NodeLimit;
			if (!(*RuleObj)->TryGetStringField(TEXT("node_class_contains"), Def.CustomRule.MatchString)) continue;
			(*RuleObj)->TryGetNumberField(TEXT("max_count"), Def.CustomRule.MaxCount);
		}
		else
		{
			continue; // Unknown rule type, skip
		}

		AllChecks.Add(Def);
	}
}

TArray<FBPDoctorResult> FBPDoctorChecks::RunCustomRules(UBlueprint* Blueprint)
{
	TArray<FBPDoctorResult> Results;
	bool bIsAnimBP = Blueprint->IsA<UAnimBlueprint>();

	// Collect all graphs
	TArray<UEdGraph*> AllGraphs;
	AllGraphs.Append(Blueprint->UbergraphPages);
	AllGraphs.Append(Blueprint->FunctionGraphs);
	AllGraphs.Append(Blueprint->MacroGraphs);

	for (const FBPDoctorCheckDef& Def : AllChecks)
	{
		if (Def.CustomRule.Type == EBPDoctorRuleType::None) continue;
		if (Def.CustomRule.bAnimBPOnly && !bIsAnimBP) continue;

		switch (Def.CustomRule.Type)
		{
			case EBPDoctorRuleType::BannedFunction:
			{
				for (UEdGraph* Graph : AllGraphs)
				{
					for (UEdGraphNode* Node : Graph->Nodes)
					{
						if (UK2Node_CallFunction* Call = Cast<UK2Node_CallFunction>(Node))
						{
							if (Call->FunctionReference.GetMemberName() == FName(*Def.CustomRule.MatchString))
							{
								FBPDoctorResult R;
								R.CheckCode = Def.Code;
								R.Severity = Def.Severity;
								R.AssetName = Blueprint->GetName();
								R.AssetPath = Blueprint->GetPathName();
								R.Description = Def.Description;
								R.NodeHint = Node->GetNodeTitle(ENodeTitleType::ListView).ToString();
								R.bAutoFixable = false;
								R.AssetType = bIsAnimBP ? EBPDoctorAssetType::AnimBP : EBPDoctorAssetType::Blueprint;
								Results.Add(R);
							}
						}
					}
				}
				break;
			}
			case EBPDoctorRuleType::BannedNode:
			{
				for (UEdGraph* Graph : AllGraphs)
				{
					for (UEdGraphNode* Node : Graph->Nodes)
					{
						if (Node->GetClass()->GetName().Contains(Def.CustomRule.MatchString))
						{
							FBPDoctorResult R;
							R.CheckCode = Def.Code;
							R.Severity = Def.Severity;
							R.AssetName = Blueprint->GetName();
							R.AssetPath = Blueprint->GetPathName();
							R.Description = Def.Description;
							R.NodeHint = Node->GetNodeTitle(ENodeTitleType::ListView).ToString();
							R.bAutoFixable = false;
							R.AssetType = bIsAnimBP ? EBPDoctorAssetType::AnimBP : EBPDoctorAssetType::Blueprint;
							Results.Add(R);
						}
					}
				}
				break;
			}
			case EBPDoctorRuleType::RequiredNode:
			{
				bool bFound = false;
				for (UEdGraph* Graph : AllGraphs)
				{
					for (UEdGraphNode* Node : Graph->Nodes)
					{
						if (Node->GetClass()->GetName().Contains(Def.CustomRule.MatchString))
						{
							bFound = true;
							break;
						}
					}
					if (bFound) break;
				}
				if (!bFound)
				{
					FBPDoctorResult R;
					R.CheckCode = Def.Code;
					R.Severity = Def.Severity;
					R.AssetName = Blueprint->GetName();
					R.AssetPath = Blueprint->GetPathName();
					R.Description = Def.Description;
					R.bAutoFixable = false;
					R.AssetType = bIsAnimBP ? EBPDoctorAssetType::AnimBP : EBPDoctorAssetType::Blueprint;
					Results.Add(R);
				}
				break;
			}
			case EBPDoctorRuleType::NodeLimit:
			{
				int32 Count = 0;
				for (UEdGraph* Graph : AllGraphs)
				{
					for (UEdGraphNode* Node : Graph->Nodes)
					{
						if (Node->GetClass()->GetName().Contains(Def.CustomRule.MatchString))
							Count++;
					}
				}
				if (Count > Def.CustomRule.MaxCount)
				{
					FBPDoctorResult R;
					R.CheckCode = Def.Code;
					R.Severity = Def.Severity;
					R.AssetName = Blueprint->GetName();
					R.AssetPath = Blueprint->GetPathName();
					R.Description = FString::Printf(TEXT("%s Found %d (max: %d)."), *Def.Description, Count, Def.CustomRule.MaxCount);
					R.bAutoFixable = false;
					R.AssetType = bIsAnimBP ? EBPDoctorAssetType::AnimBP : EBPDoctorAssetType::Blueprint;
					Results.Add(R);
				}
				break;
			}
			default: break;
		}
	}

	return Results;
}

// ─────────────────────────────────────────────────────────────────
//  GRAPH UTILITY HELPERS
// ─────────────────────────────────────────────────────────────────

namespace BPDoctorUtil
{
	// ── Per-BP Scan Memoization ──────────────────────────────────
	// Caches expensive computations so each is done once per BP
	// instead of once per check (up to 22 redundant walks → 5).

	static UBlueprint* s_MemoBP = nullptr;
	static int32 s_MemoNodeCount = -1;
	static int8 s_MemoHasEventTick = -1;  // -1=unknown, 0=false, 1=true
	static TArray<UAnimGraphNode_Base*> s_MemoAnimNodes;
	static bool s_bMemoAnimNodesValid = false;
	static TArray<UK2Node_CallFunction*> s_MemoCallFunctions;
	static bool s_bMemoCallFunctionsValid = false;
	static TArray<UK2Node_DynamicCast*> s_MemoDynamicCasts;
	static bool s_bMemoDynamicCastsValid = false;

	void BeginMemo(UBlueprint* BP)
	{
		s_MemoBP = BP;
		s_MemoNodeCount = -1;
		s_MemoHasEventTick = -1;
		s_MemoAnimNodes.Reset();
		s_bMemoAnimNodesValid = false;
		s_MemoCallFunctions.Reset();
		s_bMemoCallFunctionsValid = false;
		s_MemoDynamicCasts.Reset();
		s_bMemoDynamicCastsValid = false;
	}

	void EndMemo()
	{
		s_MemoBP = nullptr;
		s_MemoNodeCount = -1;
		s_MemoHasEventTick = -1;
		s_MemoAnimNodes.Reset();
		s_bMemoAnimNodesValid = false;
		s_MemoCallFunctions.Reset();
		s_bMemoCallFunctionsValid = false;
		s_MemoDynamicCasts.Reset();
		s_bMemoDynamicCastsValid = false;
	}

	// ── Node Collection Utilities ────────────────────────────────

	/** Count all nodes of a given type across all graphs in a Blueprint. */
	template<typename T>
	int32 CountNodesOfType(UBlueprint* BP)
	{
		int32 Count = 0;
		for (UEdGraph* Graph : BP->UbergraphPages)
		{
			for (UEdGraphNode* Node : Graph->Nodes)
			{
				if (Cast<T>(Node)) Count++;
			}
		}
		for (UEdGraph* Graph : BP->FunctionGraphs)
		{
			for (UEdGraphNode* Node : Graph->Nodes)
			{
				if (Cast<T>(Node)) Count++;
			}
		}
		return Count;
	}

	/** Collect all nodes of a given type across all graphs. */
	template<typename T>
	TArray<T*> CollectNodesOfType(UBlueprint* BP)
	{
		TArray<T*> Result;
		for (UEdGraph* Graph : BP->UbergraphPages)
		{
			for (UEdGraphNode* Node : Graph->Nodes)
			{
				if (T* Typed = Cast<T>(Node)) Result.Add(Typed);
			}
		}
		for (UEdGraph* Graph : BP->FunctionGraphs)
		{
			for (UEdGraphNode* Node : Graph->Nodes)
			{
				if (T* Typed = Cast<T>(Node)) Result.Add(Typed);
			}
		}
		return Result;
	}

	/** Memoized: Collect all K2Node_CallFunction nodes (called by 5 checks). */
	const TArray<UK2Node_CallFunction*>& GetCallFunctionNodes(UBlueprint* BP)
	{
		if (BP == s_MemoBP && s_bMemoCallFunctionsValid)
			return s_MemoCallFunctions;

		TArray<UK2Node_CallFunction*> Result = CollectNodesOfType<UK2Node_CallFunction>(BP);

		if (BP == s_MemoBP)
		{
			s_MemoCallFunctions = MoveTemp(Result);
			s_bMemoCallFunctionsValid = true;
			return s_MemoCallFunctions;
		}
		// Fallback for uncached calls — store temporarily and return
		s_MemoCallFunctions = MoveTemp(Result);
		return s_MemoCallFunctions;
	}

	/** Memoized: Collect all K2Node_DynamicCast nodes (called by 3 checks). */
	const TArray<UK2Node_DynamicCast*>& GetDynamicCastNodes(UBlueprint* BP)
	{
		if (BP == s_MemoBP && s_bMemoDynamicCastsValid)
			return s_MemoDynamicCasts;

		TArray<UK2Node_DynamicCast*> Result = CollectNodesOfType<UK2Node_DynamicCast>(BP);

		if (BP == s_MemoBP)
		{
			s_MemoDynamicCasts = MoveTemp(Result);
			s_bMemoDynamicCastsValid = true;
			return s_MemoDynamicCasts;
		}
		s_MemoDynamicCasts = MoveTemp(Result);
		return s_MemoDynamicCasts;
	}

	/** Memoized: Count total nodes across all graphs. Called by 3 checks. */
	int32 CountTotalNodes(UBlueprint* BP)
	{
		if (BP == s_MemoBP && s_MemoNodeCount >= 0)
			return s_MemoNodeCount;

		int32 Count = 0;
		for (UEdGraph* Graph : BP->UbergraphPages)
		{
			Count += Graph->Nodes.Num();
		}
		for (UEdGraph* Graph : BP->FunctionGraphs)
		{
			Count += Graph->Nodes.Num();
		}

		if (BP == s_MemoBP)
			s_MemoNodeCount = Count;

		return Count;
	}

	/** Check if any graph has a node calling a specific function. */
	bool HasFunctionCall(UBlueprint* BP, const FName& FunctionName)
	{
		const auto& CallNodes = GetCallFunctionNodes(BP);
		for (UK2Node_CallFunction* Node : CallNodes)
		{
			if (Node->FunctionReference.GetMemberName() == FunctionName)
			{
				return true;
			}
		}
		return false;
	}

	/** Memoized: Check if Blueprint has Event Tick. Called by 2 checks. */
	bool HasEventTick(UBlueprint* BP)
	{
		if (BP == s_MemoBP && s_MemoHasEventTick >= 0)
			return s_MemoHasEventTick == 1;

		auto EventNodes = CollectNodesOfType<UK2Node_Event>(BP);
		for (UK2Node_Event* Event : EventNodes)
		{
			if (Event->EventReference.GetMemberName() == FName("ReceiveTick"))
			{
				if (BP == s_MemoBP) s_MemoHasEventTick = 1;
				return true;
			}
		}
		if (BP == s_MemoBP) s_MemoHasEventTick = 0;
		return false;
	}

	/** Memoized: Get AnimBP graph nodes from ALL graph sources. Called by 9 checks. */
	TArray<UAnimGraphNode_Base*> GetAnimGraphNodes(UAnimBlueprint* AnimBP)
	{
		if (static_cast<UBlueprint*>(AnimBP) == s_MemoBP && s_bMemoAnimNodesValid)
			return s_MemoAnimNodes;

		TArray<UAnimGraphNode_Base*> Result;

		// Helper lambda to scan a graph and its subgraphs recursively
		TFunction<void(UEdGraph*)> ScanGraph = [&](UEdGraph* Graph)
		{
			if (!Graph) return;
			for (UEdGraphNode* Node : Graph->Nodes)
			{
				if (UAnimGraphNode_Base* AnimNode = Cast<UAnimGraphNode_Base>(Node))
				{
					Result.Add(AnimNode);
					// Also scan subgraphs (state machines, etc.)
					TArray<UEdGraph*> SubGraphs = AnimNode->GetSubGraphs();
					for (UEdGraph* Sub : SubGraphs)
					{
						ScanGraph(Sub);
					}
				}
			}
		};

		// AnimBP animation graphs (the actual AnimGraph lives here)
		for (UEdGraph* Graph : AnimBP->FunctionGraphs)
		{
			ScanGraph(Graph);
		}
		// Also check UbergraphPages (some AnimBP setups put nodes here)
		for (UEdGraph* Graph : AnimBP->UbergraphPages)
		{
			ScanGraph(Graph);
		}

		if (static_cast<UBlueprint*>(AnimBP) == s_MemoBP)
		{
			s_MemoAnimNodes = Result;
			s_bMemoAnimNodesValid = true;
		}

		return Result;
	}

	/**
	 * Build a human-readable breadcrumb of the graph chain a node lives in.
	 * Walks UEdGraphNode -> Outer (UEdGraph) -> Outer (UEdGraph if nested SM state, else UBlueprint).
	 * Result examples: "AnimGraph", "AnimGraph > LocomotionSM > Idle", "" (empty if Node null).
	 *
	 * Sprint 5 Phase B P1: lets the panel render exactly which sub-graph an issue is in,
	 * eliminating the "which of three LayeredBoneBlend nodes?" ambiguity on AAA AnimBPs.
	 */
	FString GetGraphPath(const UEdGraphNode* Node)
	{
		if (!Node) return FString();
		TArray<FString> Parts;
		UObject* Cur = Node->GetOuter();
		while (Cur)
		{
			if (UEdGraph* G = Cast<UEdGraph>(Cur))
			{
				Parts.Insert(G->GetName(), 0);
				Cur = G->GetOuter();
			}
			else
			{
				break; // outer is no longer a graph (typically the owning Blueprint)
			}
		}
		return FString::Join(Parts, TEXT(" > "));
	}

	/**
	 * Build a result struct. Sprint 5 Phase B: optional Node param. When provided, GraphPath
	 * is auto-computed and the weak ptr is captured for direct navigation. Backward-compatible
	 * with existing call sites that don't pass Node — those still work, just without the
	 * specificity layer payload.
	 */
	FBPDoctorResult MakeResult(const FBPDoctorCheckDef& Check, const FString& AssetName,
		const FString& AssetPath, const FString& Desc, const FString& Hint,
		EBPDoctorAssetType Type = EBPDoctorAssetType::AnimBP,
		UEdGraphNode* Node = nullptr)
	{
		FBPDoctorResult R;
		R.CheckCode = Check.Code;
		R.Severity = Check.Severity;
		R.AssetName = AssetName;
		R.AssetPath = AssetPath;
		R.Description = Desc;
		R.NodeHint = Hint;
		R.bAutoFixable = Check.bAutoFixable;
		R.AssetType = Type;
		if (Node)
		{
			R.Node = Node;
			R.GraphPath = GetGraphPath(Node);
		}
		return R;
	}

	/**
	 * Collect all anim graph nodes of a given type across an AnimBlueprint, INCLUDING nodes nested
	 * inside state machine sub-graphs. Use this instead of CollectNodesOfType<T>(AnimBP) whenever
	 * the target type inherits UAnimGraphNode_Base (Slot, LayeredBoneBlend, BlendSpacePlayer, etc.).
	 *
	 * CollectNodesOfType only walks UbergraphPages + FunctionGraphs - it misses every node placed
	 * inside a state machine state. GetAnimGraphNodes recurses through all SM sub-graphs, so this
	 * helper catches the full topology used by real production AnimBPs.
	 */
	template<typename T>
	TArray<T*> CollectAnimNodesOfType(UAnimBlueprint* AnimBP)
	{
		TArray<UAnimGraphNode_Base*> AllNodes = GetAnimGraphNodes(AnimBP);
		TArray<T*> Result;
		Result.Reserve(AllNodes.Num());
		for (UAnimGraphNode_Base* N : AllNodes)
		{
			if (T* Typed = Cast<T>(N)) Result.Add(Typed);
		}
		return Result;
	}
}

// ─────────────────────────────────────────────────────────────────
//  CHECK DISPATCH
// ─────────────────────────────────────────────────────────────────

TArray<FBPDoctorResult> FBPDoctorChecks::RunChecks(UBlueprint* Blueprint)
{
	using namespace BPDoctorUtil;
	InitChecks();
	BeginMemo(Blueprint);

	TArray<FBPDoctorResult> AllResults;
	AllResults.Reserve(8); // Most BPs have few issues

	UAnimBlueprint* AnimBP = Cast<UAnimBlueprint>(Blueprint);
	bool bIsAnimBP = (AnimBP != nullptr);

	for (const FBPDoctorCheckDef& Check : AllChecks)
	{
		if (DisabledCheckCodes.Contains(Check.Code)) continue;
		// Custom rules bypass the tier gate — they're user-defined, always run.
		if (Check.CustomRule.Type == EBPDoctorRuleType::None
			&& !IsTierInProfile(Check.Tier, ActiveProfile))
		{
			continue;
		}
		TArray<FBPDoctorResult> Results = RunCheck(Check.Code, Blueprint);
		AllResults.Append(Results);
	}

	EndMemo();
	return AllResults;
}

TArray<FBPDoctorResult> FBPDoctorChecks::RunCheck(const FString& CheckCode, UBlueprint* Blueprint)
{
	InitChecks();
	const FBPDoctorCheckDef* Check = FindCheck(CheckCode);
	if (!Check)
	{
		// v2.7.4 audit fix: warn on unknown code instead of silent empty return.
		// CI -checks=NULL_ANIM_RFE (typo) would previously report clean and never trip
		// the gate. Now the typo surfaces at scan time so users notice.
		UE_LOG(LogBPDoctor, Warning,
			TEXT("RunCheck: unknown check code '%s' — typo? See Help > User Guide for the full code list."),
			*CheckCode);
		return {};
	}

	// v2.7.4 audit fix: ResetMemo before each direct RunCheck so per-BP memoized
	// node-walks from a previous BP can't leak into this run. RunChecks (the bulk
	// path) already wraps BeginMemo/EndMemo; this guards the commandlet's
	// -checks= filter path which calls RunCheck per code.
	BPDoctorUtil::BeginMemo(Blueprint);
	ON_SCOPE_EXIT { BPDoctorUtil::EndMemo(); };

	UAnimBlueprint* AnimBP = Cast<UAnimBlueprint>(Blueprint);

	// AnimBP-specific checks require an AnimBP.
	// All AnimBP check codes do NOT start with "BP_" (which is the General BP prefix),
	// so we can gate by prefix rather than hardcoded ID ranges. This keeps the gate
	// robust as new AnimBP checks are added (v2: IDs 27-34 added 2026-04-16).
	if (!CheckCode.StartsWith(TEXT("BP_")) && !AnimBP) return {};

	// Dispatch to handler
	if (CheckCode == TEXT("NULL_ANIM_REF"))       return CheckNullAnimRef(*Check, AnimBP);
	if (CheckCode == TEXT("BROKEN_BLEND_WT"))      return CheckBrokenBlendWeight(*Check, AnimBP);
	if (CheckCode == TEXT("SKEL_MISMATCH"))        return CheckSkeletonMismatch(*Check, AnimBP);
	if (CheckCode == TEXT("MISSING_SLOT"))          return CheckMissingSlot(*Check, AnimBP);
	if (CheckCode == TEXT("BROKEN_TRANS"))          return CheckBrokenTransition(*Check, AnimBP);
	if (CheckCode == TEXT("TPOSE_FALLBACK"))        return CheckTPoseFallback(*Check, AnimBP);
	if (CheckCode == TEXT("ORPHANED_NODE"))         return CheckOrphanedNode(*Check, AnimBP);
	if (CheckCode == TEXT("INVALID_BSPACE"))        return CheckInvalidBlendSpace(*Check, AnimBP);
	if (CheckCode == TEXT("MISSING_NOTIFY"))        return CheckMissingNotify(*Check, AnimBP);
	if (CheckCode == TEXT("DUP_SLOT"))              return CheckDuplicateSlot(*Check, AnimBP);
	if (CheckCode == TEXT("UNUSED_VAR"))            return CheckUnusedVariable(*Check, AnimBP);
	if (CheckCode == TEXT("DEPRECATED_NODE"))       return CheckDeprecatedNode(*Check, AnimBP);
	if (CheckCode == TEXT("BP_BROKEN_REF"))         return CheckBrokenAssetRef(*Check, Blueprint);
	if (CheckCode == TEXT("BP_COMPLEXITY"))          return CheckComplexity(*Check, Blueprint);
	if (CheckCode == TEXT("BP_EMPTY_GRAPH"))         return CheckEmptyGraph(*Check, Blueprint);
	if (CheckCode == TEXT("BP_TICK_HEAVY"))          return CheckTickHeavy(*Check, Blueprint);
	if (CheckCode == TEXT("BP_SELF_CAST"))           return CheckSelfCast(*Check, Blueprint);
	if (CheckCode == TEXT("BP_DEPRECATED_FUNC"))     return CheckDeprecatedFunc(*Check, Blueprint);
	if (CheckCode == TEXT("BP_CIRCULAR_DEP"))        return CheckCircularDep(*Check, Blueprint);
	if (CheckCode == TEXT("BP_MASSIVE_ASSET"))       return CheckMassiveAsset(*Check, Blueprint);
	if (CheckCode == TEXT("BP_HARD_REF"))            return CheckHardRef(*Check, Blueprint);
	if (CheckCode == TEXT("BP_EXPENSIVE_TICK"))      return CheckExpensiveTick(*Check, Blueprint);
	if (CheckCode == TEXT("BP_DEBUG_NODES"))         return CheckDebugNodes(*Check, Blueprint);
	if (CheckCode == TEXT("BP_CONSTRUCT_HEAVY"))     return CheckConstructHeavy(*Check, Blueprint);
	if (CheckCode == TEXT("BP_FOREACH_PERF"))        return CheckForEachPerf(*Check, Blueprint);
	if (CheckCode == TEXT("BP_TIMELINE_HEAVY"))      return CheckTimelineHeavy(*Check, Blueprint);

	// v2 AnimBP checks (27-34) — Phase 2C Bible-alignment additions
	if (CheckCode == TEXT("MM_NO_DATABASE"))          return CheckMMNoDatabase(*Check, AnimBP);
	if (CheckCode == TEXT("MM_NO_INERTIALIZATION"))   return CheckMMNoInertialization(*Check, AnimBP);
	if (CheckCode == TEXT("SLOT_NAME_MISMATCH"))      return CheckSlotNameMismatch(*Check, AnimBP);
	if (CheckCode == TEXT("DEAD_CACHED_POSE"))        return CheckDeadCachedPose(*Check, AnimBP);
	if (CheckCode == TEXT("EMPTY_SM"))                return CheckEmptyStateMachine(*Check, AnimBP);
	if (CheckCode == TEXT("BLEND_WT_SUM"))            return CheckBlendWeightSum(*Check, AnimBP);
	if (CheckCode == TEXT("EMPTY_BRANCH_FILTER"))     return CheckEmptyBranchFilter(*Check, AnimBP);
	if (CheckCode == TEXT("DISCONNECTED_SLOT_SRC"))   return CheckDisconnectedSlotSource(*Check, AnimBP);

	// v3 AnimBP checks (35-39) — Sprint 5 Phase D coverage expansion
	if (CheckCode == TEXT("ROOTMOTION_MODE_MISMATCH")) return CheckRootMotionModeMismatch(*Check, AnimBP);
	if (CheckCode == TEXT("LINKED_LAYER_NO_LAYER"))    return CheckLinkedAnimLayerNoLayer(*Check, AnimBP);
	if (CheckCode == TEXT("CURVE_ALPHA_MISSING"))      return CheckCurveAlphaMissing(*Check, AnimBP);
	if (CheckCode == TEXT("MONTAGE_SECTION_LOOP"))     return CheckMontageSectionLoop(*Check, AnimBP);
	if (CheckCode == TEXT("BLENDSPACE_ZERO_AXIS"))     return CheckBlendSpaceZeroAxis(*Check, AnimBP);

	return {};
}

// ─────────────────────────────────────────────────────────────────
//  ANIMBP CHECK IMPLEMENTATIONS (1-12)
// ─────────────────────────────────────────────────────────────────

TArray<FBPDoctorResult> FBPDoctorChecks::CheckNullAnimRef(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	// Use the sub-graph-recursive walker: SequencePlayers commonly live inside state
	// machine state sub-graphs on real locomotion AnimBPs (hellscape v2.4 audit #1 —
	// top-level-only walk silently returned empty on the #1 advertised check).
	auto SeqPlayers = CollectAnimNodesOfType<UAnimGraphNode_SequencePlayer>(AnimBP);
	for (UAnimGraphNode_SequencePlayer* Player : SeqPlayers)
	{
		// Check if the SequencePlayer has an animation asset assigned
		UAnimationAsset* Asset = Player->GetAnimationAsset();
		if (!Asset)
		{
			Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
				FString::Printf(TEXT("SequencePlayer '%s' has no animation assigned -- evaluates to T-pose."),
					*Player->GetNodeTitle(ENodeTitleType::ListView).ToString()),
				FString::Printf(TEXT("SequencePlayer '%s' has no animation assigned"),
					*Player->GetNodeTitle(ENodeTitleType::ListView).ToString()),
				EBPDoctorAssetType::AnimBP, Player));
		}
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckBrokenBlendWeight(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	auto LBBNodes = CollectAnimNodesOfType<UAnimGraphNode_LayeredBoneBlend>(AnimBP);
	for (UAnimGraphNode_LayeredBoneBlend* LBB : LBBNodes)
	{
		// Check blend weights on the node's pins
		for (UEdGraphPin* Pin : LBB->Pins)
		{
			if (Pin->PinName.ToString().Contains(TEXT("BlendWeight")) && !Pin->LinkedTo.Num())
			{
				// Check default value
				FString DefaultVal = Pin->GetDefaultAsString();
				if (!DefaultVal.IsEmpty())
				{
					float Val = FCString::Atof(*DefaultVal);
					if (Val < 0.0f || Val > 1.0f)
					{
						Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
							FString::Printf(TEXT("%s Found weight: %.3f on '%s'"),
								*Check.Description, Val,
								*LBB->GetNodeTitle(ENodeTitleType::ListView).ToString()),
							FString::Printf(TEXT("BlendWeight = %.3f"), Val),
							EBPDoctorAssetType::AnimBP, LBB));
					}
				}
			}
		}
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckSkeletonMismatch(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	USkeleton* TargetSkeleton = AnimBP->TargetSkeleton.Get();
	if (!TargetSkeleton) return Results;

	// Walk all anim graph nodes and check referenced animation assets
	auto AnimNodes = GetAnimGraphNodes(AnimBP);
	TSet<FString> MismatchedSkeletons;
	for (UAnimGraphNode_Base* Node : AnimNodes)
	{
		UAnimationAsset* AnimAsset = Node->GetAnimationAsset();
		if (AnimAsset)
		{
			USkeleton* AnimSkeleton = AnimAsset->GetSkeleton();
			if (AnimSkeleton && AnimSkeleton != TargetSkeleton)
			{
				MismatchedSkeletons.Add(AnimSkeleton->GetName());
			}
		}
	}

	if (MismatchedSkeletons.Num() > 0)
	{
		FString SkeletonList = FString::Join(MismatchedSkeletons.Array(), TEXT(", "));
		Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
			FString::Printf(TEXT("%s Target: %s, Mismatched: %s"),
				*Check.Description, *TargetSkeleton->GetName(), *SkeletonList),
			FString::Printf(TEXT("Skeletons: %s vs %s"),
				*TargetSkeleton->GetName(), *SkeletonList)));
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckMissingSlot(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	// Source of truth: the skeleton's registered slot groups. Modern AAA setups trigger
	// montages from C++ / GameplayAbilities — the AnimBP itself never holds a montage
	// reference and never calls PlayMontage as a K2 node. The previous gate (search the
	// AnimGraph for UAnimMontage refs OR look for PlayMontage K2 calls) silently passed
	// clean on every production AnimBP that actually had the bug. New gate: if the
	// skeleton has slot groups registered, the AnimGraph is expected to consume at least
	// one via an AnimGraphNode_Slot. CollectAnimNodesOfType walks SM state sub-graphs so
	// a Slot anywhere in the AnimBP satisfies the requirement (Sprint 5 P0-5).
	USkeleton* Skel = AnimBP->TargetSkeleton;
	if (!Skel) return Results;

	const TArray<FAnimSlotGroup>& SlotGroups = Skel->GetSlotGroups();
	if (SlotGroups.Num() == 0) return Results;

	const bool bHasSlot = CollectAnimNodesOfType<UAnimGraphNode_Slot>(AnimBP).Num() > 0;
	if (!bHasSlot)
	{
		Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
			Check.Description,
			FString::Printf(TEXT("Skeleton has %d slot group(s) registered but AnimGraph has no Slot node -- montages will silently fail"), SlotGroups.Num())));
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckBrokenTransition(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	// CollectAnimNodesOfType walks sub-graphs too, so nested state machines are caught
	// (2026-04-23 audit NEW-06). CollectNodesOfType only walks Ubergraph + Function graphs.
	auto StateMachines = CollectAnimNodesOfType<UAnimGraphNode_StateMachine>(AnimBP);
	for (UAnimGraphNode_StateMachine* SM : StateMachines)
	{
		// Get the state machine's sub-graphs
		TArray<UEdGraph*> SubGraphs = SM->GetSubGraphs();

		for (UEdGraph* SMGraph : SubGraphs)
		{
			if (!SMGraph) continue;

			int32 StateCount = 0;
			int32 TransCount = 0;

			for (UEdGraphNode* Node : SMGraph->Nodes)
			{
				// SM-graph topology: state nodes are UAnimStateNode, transitions are UAnimStateTransitionNode,
				// conduits are UAnimStateConduitNode. The previous implementation cast to
				// UAnimGraphNode_StateResult/TransitionResult, which are INNER nodes that live inside each
				// state's own sub-graph - they never appear in SMGraph->Nodes, so StateCount stayed at 0
				// and the check silently returned empty on every AnimBP.
				// Conduits count as states for reachability (LOW-1) — they route transitions and need
				// at least one inbound edge to participate.
				if (Cast<UAnimStateNode>(Node) || Cast<UAnimStateConduitNode>(Node))
				{
					StateCount++;
				}
				if (Cast<UAnimStateTransitionNode>(Node))
				{
					TransCount++;
				}
			}

			if (StateCount > BPDoctorConstants::ANIMBP_STATE_MACHINE_MIN_STATES)
			{
				// Minimum transitions for reachability: N-1 (tree-shaped)
				int32 MinTransitions = StateCount - 1;
				if (TransCount < MinTransitions)
				{
					int32 Missing = MinTransitions - TransCount;
					Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
						FString::Printf(TEXT("%s %d states, %d transitions (minimum %d needed)."),
							*Check.Description, StateCount, TransCount, MinTransitions),
						FString::Printf(TEXT("%d missing transition(s) -- states may be unreachable"), Missing)));
				}
			}
		}
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckTPoseFallback(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	auto LBBNodes = CollectAnimNodesOfType<UAnimGraphNode_LayeredBoneBlend>(AnimBP);
	for (UAnimGraphNode_LayeredBoneBlend* LBB : LBBNodes)
	{
		// Check if BasePose pin is disconnected
		for (UEdGraphPin* Pin : LBB->Pins)
		{
			if (Pin->PinName == TEXT("BasePose") && Pin->LinkedTo.Num() == 0)
			{
				Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
					FString::Printf(TEXT("LayeredBoneBlend '%s' has a disconnected BasePose input -- T-pose on affected bones."),
						*LBB->GetNodeTitle(ENodeTitleType::ListView).ToString()),
					FString::Printf(TEXT("LayeredBoneBlend '%s' -- disconnected BasePose"),
						*LBB->GetNodeTitle(ENodeTitleType::ListView).ToString()),
					EBPDoctorAssetType::AnimBP, LBB));
			}
		}
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckOrphanedNode(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	auto AllAnimNodes = GetAnimGraphNodes(AnimBP);
	if (AllAnimNodes.Num() <= BPDoctorConstants::ANIMBP_ORPHANED_GATE) return Results;

	// Walk from output pose root and mark reachable nodes
	TSet<UEdGraphNode*> Reachable;
	TArray<UEdGraphNode*> WorkQueue;

	for (UEdGraphNode* Node : AllAnimNodes)
	{
		// Find the root (output pose node)
		if (Node->GetClass()->GetName().Contains(TEXT("Root")))
		{
			WorkQueue.Add(Node);
			Reachable.Add(Node);
		}
	}

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

	int32 OrphanCount = AllAnimNodes.Num() - Reachable.Num();
	if (OrphanCount > BPDoctorConstants::ANIMBP_ORPHANED_NODE_THRESHOLD)
	{
		Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
			FString::Printf(TEXT("%s %d nodes not reachable from Output Pose."), *Check.Description, OrphanCount),
			FString::Printf(TEXT("%d orphaned nodes (of %d total) -- safe to delete"),
				OrphanCount, AllAnimNodes.Num())));
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckInvalidBlendSpace(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	// v2.7.2 audit fix: walk SM-state sub-graphs too. CollectNodesOfType only walked
	// Ubergraph + FunctionGraphs, missing BlendSpacePlayer nodes inside state machine
	// states — the dominant location in any locomotion AnimBP. Sister fix to #39 below.
	auto BSPlayers = CollectAnimNodesOfType<UAnimGraphNode_BlendSpacePlayer>(AnimBP);
	for (UAnimGraphNode_BlendSpacePlayer* BSPlayer : BSPlayers)
	{
		UAnimationAsset* Asset = BSPlayer->GetAnimationAsset();
		UBlendSpace* BS = Asset ? Cast<UBlendSpace>(Asset) : nullptr;
		if (BS)
		{
			int32 SampleCount = BS->GetBlendSamples().Num();
			if (SampleCount < 2)
			{
				Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
					FString::Printf(TEXT("%s BlendSpace '%s' has %d sample(s)."),
						*Check.Description, *BS->GetName(), SampleCount),
					FString::Printf(TEXT("BlendSpace '%s' needs 2+ samples, has %d"),
						*BS->GetName(), SampleCount)));
			}
		}
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckMissingNotify(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	// Check animation assets referenced by the AnimBP for notifies
	auto AnimNodes = GetAnimGraphNodes(AnimBP);
	for (UAnimGraphNode_Base* Node : AnimNodes)
	{
		UAnimationAsset* Asset = Node->GetAnimationAsset();
		UAnimSequenceBase* SeqBase = Asset ? Cast<UAnimSequenceBase>(Asset) : nullptr;
		if (!SeqBase) continue;

		for (const FAnimNotifyEvent& Notify : SeqBase->Notifies)
		{
			if (Notify.NotifyName != NAME_None && !Notify.Notify && !Notify.NotifyStateClass)
			{
				Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
					FString::Printf(TEXT("%s Notify '%s' in '%s' has no handler."),
						*Check.Description, *Notify.NotifyName.ToString(), *SeqBase->GetName()),
					FString::Printf(TEXT("Missing handler for notify '%s'"),
						*Notify.NotifyName.ToString())));
			}
		}
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckDuplicateSlot(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	auto SlotNodes = CollectAnimNodesOfType<UAnimGraphNode_Slot>(AnimBP);
	TMap<FName, int32> SlotNameCounts;

	for (UAnimGraphNode_Slot* Slot : SlotNodes)
	{
		FName SlotName = Slot->Node.SlotName;
		SlotNameCounts.FindOrAdd(SlotName)++;
	}

	for (const auto& Pair : SlotNameCounts)
	{
		if (Pair.Value > 1)
		{
			Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
				FString::Printf(TEXT("%s Duplicate: '%s' (%d times)"),
					*Check.Description, *Pair.Key.ToString(), Pair.Value),
				FString::Printf(TEXT("Slot name '%s' used %d times"),
					*Pair.Key.ToString(), Pair.Value)));
		}
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckUnusedVariable(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	// Use BPDoctorCompat::GetCompiledAnimBPClass so 5.5+ doesn't hand back the skeleton-generated
	// class for uncompiled BPs (that would iterate zero properties and produce a false-negative).
	UAnimBlueprintGeneratedClass* GenClass = BPDoctorCompat::GetCompiledAnimBPClass(AnimBP);
	if (!GenClass) return Results;

	// Get all user-defined properties, skipping ones that have legitimate external use
	// (v2.3 intent gate): BlueprintReadable/EditAnywhere/SaveGame properties are by
	// definition consumed outside the graph — counting them as "unused" was a major
	// false-positive source in the 2026-04-23 product review.
	TArray<FProperty*> UserProps;
	for (TFieldIterator<FProperty> PropIt(GenClass, EFieldIteratorFlags::ExcludeSuper); PropIt; ++PropIt)
	{
		FProperty* Prop = *PropIt;
		if (!Prop) continue;
		// CPF_BlueprintVisible covers BlueprintReadWrite. CPF_BlueprintReadOnly is a SEPARATE
		// flag (audit v2.3 follow-up) — ReadOnly props are still externally consumed and must
		// not be counted as unused. Missing this flag leaked false positives on every BP with
		// BlueprintReadOnly vars.
		const uint64 ExternalFlags = CPF_BlueprintVisible | CPF_BlueprintReadOnly
			| CPF_Edit | CPF_SaveGame | CPF_Net;
		if (Prop->HasAnyPropertyFlags(ExternalFlags)) continue;
		UserProps.Add(Prop);
	}

	// Count variable-get nodes in graphs
	int32 VarGetCount = 0;
	for (UEdGraph* Graph : AnimBP->FunctionGraphs)
	{
		for (UEdGraphNode* Node : Graph->Nodes)
		{
			if (Node->GetClass()->GetName().Contains(TEXT("VariableGet")))
			{
				VarGetCount++;
			}
		}
	}

	if (UserProps.Num() > BPDoctorConstants::ANIMBP_UNUSED_VAR_MAX_PROPS
		&& VarGetCount < BPDoctorConstants::ANIMBP_UNUSED_VAR_MIN_GETS)
	{
		Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
			FString::Printf(TEXT("%s %d properties, %d graph reads."),
				*Check.Description, UserProps.Num(), VarGetCount),
			FString::Printf(TEXT("%d properties with minimal graph reads"), UserProps.Num())));
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckDeprecatedNode(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	auto AnimNodes = GetAnimGraphNodes(AnimBP);
	for (UAnimGraphNode_Base* Node : AnimNodes)
	{
		if (Node->GetClass()->HasAnyClassFlags(CLASS_Deprecated))
		{
			Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
				FString::Printf(TEXT("%s Node: %s"), *Check.Description, *Node->GetClass()->GetName()),
				FString::Printf(TEXT("Deprecated: %s"), *Node->GetClass()->GetName())));
		}
	}

	return Results;
}

// ─────────────────────────────────────────────────────────────────
//  GENERAL BP CHECK IMPLEMENTATIONS (13-26)
// ─────────────────────────────────────────────────────────────────

TArray<FBPDoctorResult> FBPDoctorChecks::CheckBrokenAssetRef(const FBPDoctorCheckDef& Check, UBlueprint* BP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	// Walk all nodes and check for broken references via pins
	TArray<UEdGraph*> AllGraphs;
	AllGraphs.Append(BP->UbergraphPages);
	AllGraphs.Append(BP->FunctionGraphs);
	AllGraphs.Append(BP->MacroGraphs);
	for (UEdGraph* Graph : AllGraphs)
	{
		for (UEdGraphNode* Node : Graph->Nodes)
		{
			for (UEdGraphPin* Pin : Node->Pins)
			{
				if (Pin->PinType.PinCategory == UEdGraphSchema_K2::PC_Object ||
					Pin->PinType.PinCategory == UEdGraphSchema_K2::PC_SoftObject)
				{
					FString DefaultVal = Pin->GetDefaultAsString();
					if (!DefaultVal.IsEmpty() && DefaultVal != TEXT("None"))
					{
						FSoftObjectPath Path(DefaultVal);
						if (!Path.ResolveObject())
						{
							// Verify it's actually a /Game/ path (not a class path)
							if (DefaultVal.StartsWith(TEXT("/Game/")))
							{
								Results.Add(MakeResult(Check, BP->GetName(), BP->GetPathName(),
									FString::Printf(TEXT("%s Missing: %s"), *Check.Description, *DefaultVal),
									FString::Printf(TEXT("Broken ref: %s"), *DefaultVal),
									EBPDoctorAssetType::Blueprint));
							}
						}
					}
				}
			}
		}
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckComplexity(const FBPDoctorCheckDef& Check, UBlueprint* BP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	int32 NodeCount = CountTotalNodes(BP);

	// Parent-scaled threshold (v2.3 intent gate): UMG widgets legitimately wire many event
	// handlers; AnimInstance BPs should stay tight because AnimGraph evaluation is hot.
	// Firing on every BP at 100 nodes was the #3 false-positive source in the product review.
	int32 Threshold = BPDoctorConstants::BP_COMPLEXITY_NODE_THRESHOLD;
	if (UClass* Parent = BP->ParentClass)
	{
		for (UClass* Ancestor = Parent; Ancestor; Ancestor = Ancestor->GetSuperClass())
		{
			const FString Name = Ancestor->GetName();
			if (Name == TEXT("UserWidget"))         { Threshold = 150; break; }
			if (Name == TEXT("AnimInstance"))       { Threshold = 80;  break; }
			if (Name == TEXT("AnimationAsset"))     { Threshold = 80;  break; }
		}
	}

	if (NodeCount > Threshold)
	{
		Results.Add(MakeResult(Check, BP->GetName(), BP->GetPathName(),
			FString::Printf(TEXT("%s %d nodes (class threshold: %d)."), *Check.Description, NodeCount, Threshold),
			FString::Printf(TEXT("%d nodes -- consider refactoring to functions or C++"), NodeCount),
			EBPDoctorAssetType::Blueprint));
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckEmptyGraph(const FBPDoctorCheckDef& Check, UBlueprint* BP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	// v2.7.4 audit fix: skip BP types that legitimately have few/no graph nodes —
	// Interface BPs declare function signatures only, MacroLibrary/FunctionLibrary
	// are pure-utility containers, LevelScript holds level-specific event hooks.
	// Without these guards, BP_EMPTY_GRAPH false-fires on every BPI_/BPML_/BPFL_
	// asset in a typical project (refund-trigger noise). Widget BPs (UWidgetBlueprint
	// subclass) bind via property metadata, not graph nodes — same false-positive.
	if (BP->BlueprintType == BPTYPE_Interface
		|| BP->BlueprintType == BPTYPE_MacroLibrary
		|| BP->BlueprintType == BPTYPE_FunctionLibrary
		|| BP->BlueprintType == BPTYPE_LevelScript)
	{
		return Results;
	}
	if (UClass* Parent = BP->ParentClass)
	{
		for (UClass* A = Parent; A; A = A->GetSuperClass())
		{
			if (A->GetName() == TEXT("UserWidget"))
			{
				return Results; // Widget BPs use property-binding, not graph nodes
			}
		}
	}

	int32 NodeCount = CountTotalNodes(BP);
	if (NodeCount < 3)
	{
		Results.Add(MakeResult(Check, BP->GetName(), BP->GetPathName(),
			FString::Printf(TEXT("%s Only %d node(s) found."), *Check.Description, NodeCount),
			TEXT("Blueprint appears to contain no meaningful logic"),
			EBPDoctorAssetType::Blueprint));
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckTickHeavy(const FBPDoctorCheckDef& Check, UBlueprint* BP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	if (HasEventTick(BP))
	{
		int32 NodeCount = CountTotalNodes(BP);
		if (NodeCount > BPDoctorConstants::BP_TICK_HEAVY_NODE_THRESHOLD)
		{
			Results.Add(MakeResult(Check, BP->GetName(), BP->GetPathName(),
				FString::Printf(TEXT("%s Tick enabled with %d nodes."), *Check.Description, NodeCount),
				FString::Printf(TEXT("EventTick + %d nodes -- consider timers or C++ Tick"), NodeCount),
				EBPDoctorAssetType::Blueprint));
		}
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckSelfCast(const FBPDoctorCheckDef& Check, UBlueprint* BP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	const auto& CastNodes = GetDynamicCastNodes(BP);
	UClass* BPClass = BP->GeneratedClass;
	if (!BPClass) return Results;

	for (UK2Node_DynamicCast* CastNode : CastNodes)
	{
		if (CastNode->TargetType != BPClass) continue;

		// Intent gate (v2.3): casts inside a function/macro whose name starts with "Cast"
		// are almost always deliberate utility wrappers, not accidental self-casts.
		if (UEdGraph* OwnerGraph = CastNode->GetGraph())
		{
			const FString GraphName = OwnerGraph->GetName();
			if (GraphName.StartsWith(TEXT("Cast")) || GraphName.Contains(TEXT("CastTo"))) continue;
		}

		Results.Add(MakeResult(Check, BP->GetName(), BP->GetPathName(),
			Check.Description,
			FString::Printf(TEXT("Blueprint casts to its own type '%s' -- use Self instead"),
				*BPClass->GetName()),
			EBPDoctorAssetType::Blueprint));
		break; // One report is enough
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckDeprecatedFunc(const FBPDoctorCheckDef& Check, UBlueprint* BP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	const auto& CallNodes = GetCallFunctionNodes(BP);
	TArray<FString> DeprecatedFuncs;

	for (UK2Node_CallFunction* Call : CallNodes)
	{
		UFunction* Func = Call->GetTargetFunction();
		if (Func && Func->HasMetaData(TEXT("DeprecatedFunction")))
		{
			DeprecatedFuncs.AddUnique(Func->GetName());
		}
	}

	if (DeprecatedFuncs.Num() > 0)
	{
		FString FuncList = FString::Join(DeprecatedFuncs, TEXT(", "));
		Results.Add(MakeResult(Check, BP->GetName(), BP->GetPathName(),
			FString::Printf(TEXT("%s Found: %s"), *Check.Description, *FuncList),
			FString::Printf(TEXT("Deprecated functions: %s"), *FuncList),
			EBPDoctorAssetType::Blueprint));
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckCircularDep(const FBPDoctorCheckDef& Check, UBlueprint* BP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	// Get all hard-referenced Blueprint classes
	TSet<FString> ReferencedBPs;
	const auto& CastNodes = GetDynamicCastNodes(BP);
	for (UK2Node_DynamicCast* CastNode : CastNodes)
	{
		if (CastNode->TargetType && CastNode->TargetType->ClassGeneratedBy)
		{
			ReferencedBPs.Add(CastNode->TargetType->GetPathName());
		}
	}

	// For each referenced BP, check if IT references US back
	FString OurPath = BP->GeneratedClass ? BP->GeneratedClass->GetPathName() : BP->GetPathName();
	IAssetRegistry& AssetRegistry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();

	for (const FString& RefPath : ReferencedBPs)
	{
		TArray<FName> Referencers;
		AssetRegistry.GetReferencers(FName(*RefPath), Referencers);
		FName OurPackageName(*BP->GetOutermost()->GetName());
		for (const FName& Ref : Referencers)
		{
			if (Ref == OurPackageName)
			{
				Results.Add(MakeResult(Check, BP->GetName(), BP->GetPathName(),
					FString::Printf(TEXT("%s Circular: %s <-> %s"),
						*Check.Description, *BP->GetName(),
						*FPaths::GetBaseFilename(RefPath)),
					FString::Printf(TEXT("Circular dependency with %s"),
						*FPaths::GetBaseFilename(RefPath)),
					EBPDoctorAssetType::Blueprint));
				break;
			}
		}
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckMassiveAsset(const FBPDoctorCheckDef& Check, UBlueprint* BP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	// Get file size from the package
	FString PackagePath = BP->GetOutermost()->GetName();
	FString FilePath;
	if (FPackageName::DoesPackageExist(PackagePath, &FilePath))
	{
		int64 FileSize = IFileManager::Get().FileSize(*FilePath);
		if (FileSize > BPDoctorConstants::BP_MASSIVE_ASSET_BYTES)
		{
			float SizeMB = FileSize / (1024.0f * 1024.0f);
			Results.Add(MakeResult(Check, BP->GetName(), BP->GetPathName(),
				FString::Printf(TEXT("%s File is %.1fMB."), *Check.Description, SizeMB),
				FString::Printf(TEXT("%.1fMB -- check for embedded data or excessive nodes"), SizeMB),
				EBPDoctorAssetType::Blueprint));
		}
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckHardRef(const FBPDoctorCheckDef& Check, UBlueprint* BP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	const auto& CastNodes = GetDynamicCastNodes(BP);
	TSet<FString> HardRefs;

	for (UK2Node_DynamicCast* CastNode : CastNodes)
	{
		if (CastNode->TargetType && CastNode->TargetType->ClassGeneratedBy)
		{
			HardRefs.Add(CastNode->TargetType->GetName());
		}
	}

	if (HardRefs.Num() >= BPDoctorConstants::BP_HARD_REF_THRESHOLD)
	{
		TArray<FString> RefList = HardRefs.Array();
		FString DisplayList = FString::Join(
			TArrayView<FString>(RefList.GetData(), FMath::Min(3, RefList.Num())),
			TEXT(", "));
		if (RefList.Num() > 3) DisplayList += TEXT("...");

		Results.Add(MakeResult(Check, BP->GetName(), BP->GetPathName(),
			FString::Printf(TEXT("%s %d hard BP references."), *Check.Description, HardRefs.Num()),
			FString::Printf(TEXT("Hard refs: %s"), *DisplayList),
			EBPDoctorAssetType::Blueprint));
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckExpensiveTick(const FBPDoctorCheckDef& Check, UBlueprint* BP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	if (!HasEventTick(BP)) return Results;

	static const TArray<FName> ExpensiveOps = {
		FName("GetAllActorsOfClass"), FName("GetAllActorsWithTag"),
		FName("GetAllActorsWithInterface"),
		FName("LineTraceByChannel"), FName("LineTraceForObjects"),
		FName("SweepSingleByChannel"), FName("SweepMultiByChannel"),
		FName("GetComponentsByClass"), FName("GetComponentsByTag"),
		FName("GetOverlappingActors"), FName("GetOverlappingComponents"),
	};

	TArray<FString> FoundOps;
	const auto& CallNodes = GetCallFunctionNodes(BP);
	for (UK2Node_CallFunction* Call : CallNodes)
	{
		FName FuncName = Call->FunctionReference.GetMemberName();
		if (ExpensiveOps.Contains(FuncName))
		{
			FoundOps.AddUnique(FuncName.ToString());
		}
	}

	if (FoundOps.Num() > 0)
	{
		FString OpList = FString::Join(
			TArrayView<FString>(FoundOps.GetData(), FMath::Min(3, FoundOps.Num())),
			TEXT(", "));
		Results.Add(MakeResult(Check, BP->GetName(), BP->GetPathName(),
			FString::Printf(TEXT("%s Found: %s"), *Check.Description, *OpList),
			FString::Printf(TEXT("Tick + %s -- move to timer or C++"), *OpList),
			EBPDoctorAssetType::Blueprint));
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckDebugNodes(const FBPDoctorCheckDef& Check, UBlueprint* BP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	// Intent gate (v2.3 product review): debug nodes are legitimate inside dev/test/WIP BPs
	// and BPs the developer has explicitly named as debug artifacts. Firing on those eroded
	// trust in the tool — real-world reviewer's "not a problem" finding was exactly this.
	const FString BPName = BP->GetName();
	const FString BPPath = BP->GetPathName();
	if (BPPath.Contains(TEXT("/Debug/")) || BPPath.Contains(TEXT("/Test/"))
		|| BPPath.Contains(TEXT("/Tests/")) || BPPath.Contains(TEXT("/WIP/"))
		|| BPPath.Contains(TEXT("/Prototype/")) || BPPath.Contains(TEXT("/Dev/"))
		|| BPPath.Contains(TEXT("/Sandbox/")) || BPPath.Contains(TEXT("/Developers/")))
	{
		return Results;
	}
	if (BPName.EndsWith(TEXT("_Dev")) || BPName.EndsWith(TEXT("_Test"))
		|| BPName.EndsWith(TEXT("_Debug")) || BPName.EndsWith(TEXT("_Temp"))
		|| BPName.StartsWith(TEXT("TEST_")) || BPName.StartsWith(TEXT("DEBUG_")))
	{
		return Results;
	}

	static const TArray<FName> DebugFunctions = {
		FName("PrintString"), FName("PrintText"), FName("PrintWarning"),
		FName("DrawDebugLine"), FName("DrawDebugBox"), FName("DrawDebugSphere"),
		FName("DrawDebugPoint"), FName("DrawDebugArrow"), FName("DrawDebugString"),
		FName("DrawDebugCapsule"), FName("DrawDebugCylinder"),
	};

	TArray<FString> Found;
	const auto& CallNodes = GetCallFunctionNodes(BP);
	for (UK2Node_CallFunction* Call : CallNodes)
	{
		FName FuncName = Call->FunctionReference.GetMemberName();
		if (DebugFunctions.Contains(FuncName))
		{
			Found.AddUnique(FuncName.ToString());
		}
	}

	if (Found.Num() > 0)
	{
		FString FoundList = FString::Join(
			TArrayView<FString>(Found.GetData(), FMath::Min(3, Found.Num())),
			TEXT(", "));
		Results.Add(MakeResult(Check, BP->GetName(), BP->GetPathName(),
			FString::Printf(TEXT("%s Found: %s"), *Check.Description, *FoundList),
			FString::Printf(TEXT("Debug nodes: %s -- remove before shipping"), *FoundList),
			EBPDoctorAssetType::Blueprint));
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckConstructHeavy(const FBPDoctorCheckDef& Check, UBlueprint* BP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	// Find the Construction Script graph
	UEdGraph* ConstructGraph = nullptr;
	for (UEdGraph* Graph : BP->FunctionGraphs)
	{
		if (Graph->GetName() == TEXT("UserConstructionScript"))
		{
			ConstructGraph = Graph;
			break;
		}
	}

	if (!ConstructGraph) return Results;

	static const TArray<FName> HeavyOps = {
		FName("SpawnActorFromClass"), FName("SpawnActor"),
		FName("GetAllActorsOfClass"), FName("GetAllActorsWithTag"),
		FName("DestroyActor"), FName("DestroyComponent"),
		FName("AddComponentByClass"),
	};

	TArray<FString> Found;
	for (UEdGraphNode* Node : ConstructGraph->Nodes)
	{
		if (UK2Node_CallFunction* Call = Cast<UK2Node_CallFunction>(Node))
		{
			FName FuncName = Call->FunctionReference.GetMemberName();
			if (HeavyOps.Contains(FuncName))
			{
				Found.AddUnique(FuncName.ToString());
			}
		}
	}

	if (Found.Num() > 0)
	{
		FString FoundList = FString::Join(Found, TEXT(", "));
		Results.Add(MakeResult(Check, BP->GetName(), BP->GetPathName(),
			FString::Printf(TEXT("%s Found: %s"), *Check.Description, *FoundList),
			FString::Printf(TEXT("Construction Script + %s -- causes editor freezes"), *Found[0]),
			EBPDoctorAssetType::Blueprint));
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckForEachPerf(const FBPDoctorCheckDef& Check, UBlueprint* BP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	// Intent gate (v2.3): ForEach is only a perf concern when it's in the tick-driven
	// execution path. Firing on every ForEach in every function was the #2 false-positive
	// source in the 2026-04-23 product review. We now require: (a) EventTick exists, and
	// (b) the ForEach lives in an UbergraphPage (event-driven) not a one-shot function.
	if (!HasEventTick(BP)) return Results;

	auto MacroNodes = CollectNodesOfType<UK2Node_MacroInstance>(BP);
	bool bHasForEach = false;
	for (UK2Node_MacroInstance* Macro : MacroNodes)
	{
		FString MacroName = Macro->GetMacroGraph() ? Macro->GetMacroGraph()->GetName() : TEXT("");
		if (!MacroName.Contains(TEXT("ForEachLoop"))) continue;
		UEdGraph* Owner = Macro->GetGraph();
		if (Owner && BP->UbergraphPages.Contains(Owner))
		{
			bHasForEach = true;
			break;
		}
	}

	if (!bHasForEach) return Results;

	static const TArray<FName> PureQueries = {
		FName("GetComponentsByClass"), FName("GetAllActorsOfClass"),
		FName("GetComponentsByTag"), FName("GetAllActorsWithTag"),
	};

	TArray<FString> Found;
	const auto& CallNodes = GetCallFunctionNodes(BP);
	for (UK2Node_CallFunction* Call : CallNodes)
	{
		FName FuncName = Call->FunctionReference.GetMemberName();
		if (PureQueries.Contains(FuncName))
		{
			Found.AddUnique(FuncName.ToString());
		}
	}

	if (Found.Num() > 0)
	{
		Results.Add(MakeResult(Check, BP->GetName(), BP->GetPathName(),
			FString::Printf(TEXT("%s ForEach + %s"), *Check.Description, *FString::Join(Found, TEXT(", "))),
			FString::Printf(TEXT("ForEachLoop re-evaluates %s every iteration -- cache the array"), *Found[0]),
			EBPDoctorAssetType::Blueprint));
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckTimelineHeavy(const FBPDoctorCheckDef& Check, UBlueprint* BP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	int32 TimelineCount = CountNodesOfType<UK2Node_Timeline>(BP);
	if (TimelineCount >= BPDoctorConstants::BP_TIMELINE_HEAVY_THRESHOLD)
	{
		Results.Add(MakeResult(Check, BP->GetName(), BP->GetPathName(),
			FString::Printf(TEXT("%s %d Timeline components."), *Check.Description, TimelineCount),
			FString::Printf(TEXT("%d hidden tick registrations -- consider merging"), TimelineCount),
			EBPDoctorAssetType::Blueprint));
	}

	return Results;
}

// ─────────────────────────────────────────────────────────────────
//  AnimBP v2 Check Implementations (27-34) — Phase 2C (2026-04-16)
//  Catches Motion Matching, Linked Layer, slot-name, cached-pose,
//  empty-state-machine, and 3 ported AnimBPDoctor checks.
//  MM checks use class-name string matching so BPDoctor stays
//  compilable even when PoseSearch module isn't linked.
// ─────────────────────────────────────────────────────────────────

TArray<FBPDoctorResult> FBPDoctorChecks::CheckMMNoDatabase(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	TArray<UAnimGraphNode_Base*> AllNodes = GetAnimGraphNodes(AnimBP);
	for (UAnimGraphNode_Base* Node : AllNodes)
	{
		if (!Node) continue;
		if (Node->GetClass()->GetName() != TEXT("AnimGraphNode_MotionMatching")) continue;

		// Read Database property via reflection on the inner FAnimNode_MotionMatching struct
		FProperty* NodeProp = Node->GetClass()->FindPropertyByName(TEXT("Node"));
		bool bHasDb = false;
		if (FStructProperty* StructProp = CastField<FStructProperty>(NodeProp))
		{
			void* InnerPtr = StructProp->ContainerPtrToValuePtr<void>(Node);
			if (FProperty* DbProp = StructProp->Struct->FindPropertyByName(TEXT("Database")))
			{
				if (FObjectPropertyBase* ObjProp = CastField<FObjectPropertyBase>(DbProp))
				{
					UObject* Db = ObjProp->GetObjectPropertyValue(ObjProp->ContainerPtrToValuePtr<void>(InnerPtr));
					bHasDb = (Db != nullptr);
				}
			}
		}
		if (!bHasDb)
		{
			Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
				FString::Printf(TEXT("MotionMatching node '%s' has no Pose Search Database assigned -- outputs T-pose silently."),
					*Node->GetNodeTitle(ENodeTitleType::ListView).ToString()),
				FString::Printf(TEXT("MotionMatching node '%s' has no Database — outputs T-pose"),
					*Node->GetNodeTitle(ENodeTitleType::ListView).ToString()),
				EBPDoctorAssetType::AnimBP, Node));
		}
	}
	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckMMNoInertialization(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	TArray<UAnimGraphNode_Base*> AllNodes = GetAnimGraphNodes(AnimBP);
	for (UAnimGraphNode_Base* Node : AllNodes)
	{
		if (!Node) continue;
		if (Node->GetClass()->GetName() != TEXT("AnimGraphNode_MotionMatching")) continue;

		// Walk the MM node's output pin(s). If any direct downstream node is not an
		// Inertialization node, flag. Accept Inertialization appearing within 1-hop.
		bool bHasInert = false;
		for (UEdGraphPin* Pin : Node->Pins)
		{
			if (Pin->Direction != EGPD_Output) continue;
			for (UEdGraphPin* Linked : Pin->LinkedTo)
			{
				if (!Linked) continue;
				UEdGraphNode* Downstream = Linked->GetOwningNode();
				if (Downstream && Downstream->GetClass()->GetName() == TEXT("AnimGraphNode_Inertialization"))
				{
					bHasInert = true;
					break;
				}
			}
			if (bHasInert) break;
		}
		if (!bHasInert)
		{
			Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
				FString::Printf(TEXT("MotionMatching node '%s' has no Inertialization node downstream -- pose pops visible on every database change."),
					*Node->GetNodeTitle(ENodeTitleType::ListView).ToString()),
				FString::Printf(TEXT("MotionMatching node '%s' has no Inertialization downstream — visible pose pops on DB change"),
					*Node->GetNodeTitle(ENodeTitleType::ListView).ToString()),
				EBPDoctorAssetType::AnimBP, Node));
		}
	}
	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckSlotNameMismatch(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;
	if (!AnimBP->TargetSkeleton) return Results; // SKEL_MISMATCH catches this

	// Collect registered slot names from all slot groups on the skeleton
	TSet<FName> RegisteredSlots;
	for (const FAnimSlotGroup& Group : AnimBP->TargetSkeleton->GetSlotGroups())
	{
		for (const FName& SlotName : Group.SlotNames)
		{
			RegisteredSlots.Add(SlotName);
		}
	}

	// Walk SM state sub-graphs too — a mis-registered slot inside a state must still fire
	// (hellscape v2.4 #3). Without this, a real SHIP bug goes silent in prod.
	auto SlotNodes = CollectAnimNodesOfType<UAnimGraphNode_Slot>(AnimBP);
	for (UAnimGraphNode_Slot* SlotNode : SlotNodes)
	{
		FName SlotName = SlotNode->Node.SlotName;
		if (SlotName.IsNone()) continue;
		if (!RegisteredSlots.Contains(SlotName))
		{
			Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
				FString::Printf(TEXT("Slot node uses SlotName '%s' which is NOT registered in the skeleton's slot groups -- montages targeting this slot will silently fail."),
					*SlotName.ToString()),
				FString::Printf(TEXT("Slot node uses '%s' which is NOT registered in the skeleton — montages won't route here"),
					*SlotName.ToString()),
				EBPDoctorAssetType::AnimBP, SlotNode));
		}
	}
	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckDeadCachedPose(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	// Build sets of cache names on each side
	TSet<FName> SaveNames;
	TSet<FName> UseNames;

	// UE 5.7: UAnimGraphNode_SaveCachedPose::CacheName is FString, not FName.
	// Use CollectAnimNodesOfType — CollectNodesOfType only walks Ubergraph + FunctionGraphs
	// and would miss cached-pose nodes inside state machine sub-graphs, producing false
	// "Save without Use" positives on any AnimBP that caches inside SMs (audit v2.3).
	auto SaveNodes = CollectAnimNodesOfType<UAnimGraphNode_SaveCachedPose>(AnimBP);
	for (UAnimGraphNode_SaveCachedPose* N : SaveNodes)
	{
		if (!N || N->CacheName.IsEmpty()) continue;
		SaveNames.Add(FName(*N->CacheName));
	}

	auto UseNodes = CollectAnimNodesOfType<UAnimGraphNode_UseCachedPose>(AnimBP);
	for (UAnimGraphNode_UseCachedPose* N : UseNodes)
	{
		if (!N) continue;
		// A null/stale SaveCachedPoseNode IS the broken-link condition this check exists
		// to catch — previously the `continue` guard silently swallowed it (hellscape v2.4 #4).
		if (!N->SaveCachedPoseNode.IsValid())
		{
			const FString UseTitle = N->GetNodeTitle(ENodeTitleType::ListView).ToString();
			Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
				FString::Printf(TEXT("UseCachedPose '%s' has a broken link to its SaveCachedPose node -- outputs T-pose."),
					*UseTitle),
				FString::Printf(TEXT("UseCachedPose '%s' has a broken link to its Save node"),
					*UseTitle),
				EBPDoctorAssetType::AnimBP, N));
			continue;
		}
		if (N->SaveCachedPoseNode->CacheName.IsEmpty()) continue;
		UseNames.Add(FName(*N->SaveCachedPoseNode->CacheName));
	}

	// Orphans: Save without matching Use
	for (const FName& SaveName : SaveNames)
	{
		if (!UseNames.Contains(SaveName))
		{
			Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
				Check.Description,
				FString::Printf(TEXT("SaveCachedPose '%s' has no matching UseCachedPose"),
					*SaveName.ToString())));
		}
	}
	// Orphans: Use without matching Save
	for (const FName& UseName : UseNames)
	{
		if (!SaveNames.Contains(UseName))
		{
			Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
				FString::Printf(TEXT("UseCachedPose '%s' has no matching SaveCachedPose -- will output T-pose at runtime."),
					*UseName.ToString()),
				FString::Printf(TEXT("UseCachedPose '%s' has no SaveCachedPose — will output T-pose"),
					*UseName.ToString())));
		}
	}
	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckEmptyStateMachine(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	auto SMs = CollectNodesOfType<UAnimGraphNode_StateMachine>(AnimBP);
	for (UAnimGraphNode_StateMachine* SM : SMs)
	{
		if (!SM || !SM->EditorStateMachineGraph)
		{
			Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
				FString::Printf(TEXT("State machine '%s' has no editor graph -- malformed asset, evaluation will freeze."),
					*SM->GetNodeTitle(ENodeTitleType::ListView).ToString()),
				TEXT("State machine has no editor graph"),
				EBPDoctorAssetType::AnimBP, SM));
			continue;
		}
		int32 StateCount = 0;
		UAnimStateEntryNode* EntryNode = nullptr;
		for (UEdGraphNode* N : SM->EditorStateMachineGraph->Nodes)
		{
			if (Cast<UAnimStateNode>(N)) StateCount++;
			if (UAnimStateEntryNode* E = Cast<UAnimStateEntryNode>(N)) EntryNode = E;
		}
		if (StateCount == 0)
		{
			Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
				FString::Printf(TEXT("State machine '%s' has zero states -- evaluation freezes on entry."),
					*SM->GetNodeTitle(ENodeTitleType::ListView).ToString()),
				FString::Printf(TEXT("State machine '%s' has zero states"),
					*SM->GetNodeTitle(ENodeTitleType::ListView).ToString()),
				EBPDoctorAssetType::AnimBP, SM));
			continue;
		}
		if (EntryNode)
		{
			bool bHasOutbound = false;
			for (UEdGraphPin* Pin : EntryNode->Pins)
			{
				if (Pin && Pin->LinkedTo.Num() > 0) { bHasOutbound = true; break; }
			}
			if (!bHasOutbound)
			{
				Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
					FString::Printf(TEXT("State machine '%s' Entry node has no outbound transition -- evaluation freezes on entry."),
						*SM->GetNodeTitle(ENodeTitleType::ListView).ToString()),
					FString::Printf(TEXT("State machine '%s' Entry node has no outbound transition"),
						*SM->GetNodeTitle(ENodeTitleType::ListView).ToString()),
					EBPDoctorAssetType::AnimBP, SM));
			}
		}
	}
	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckBlendWeightSum(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	auto LBBs = CollectAnimNodesOfType<UAnimGraphNode_LayeredBoneBlend>(AnimBP);
	for (UAnimGraphNode_LayeredBoneBlend* LBB : LBBs)
	{
		float Sum = 0.0f;
		int32 WeightCount = 0;
		for (UEdGraphPin* Pin : LBB->Pins)
		{
			// Only consider BlendWeight pins with default values (not driven by variables)
			if (!Pin->PinName.ToString().Contains(TEXT("BlendWeight"))) continue;
			if (Pin->LinkedTo.Num() > 0) continue; // driven by var — skip
			FString Default = Pin->GetDefaultAsString();
			if (Default.IsEmpty()) continue;
			Sum += FCString::Atof(*Default);
			WeightCount++;
		}
		// Only flag if we actually had weights AND the sum is off
		if (WeightCount > 0 && (Sum < 0.95f || Sum > 1.05f))
		{
			Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
				FString::Printf(TEXT("LayeredBoneBlend '%s' BlendWeights sum to %.3f across %d weights -- partial blending produces unexpected pose bias."),
					*LBB->GetNodeTitle(ENodeTitleType::ListView).ToString(), Sum, WeightCount),
				FString::Printf(TEXT("LayeredBoneBlend '%s' weight sum = %.3f"),
					*LBB->GetNodeTitle(ENodeTitleType::ListView).ToString(), Sum),
				EBPDoctorAssetType::AnimBP, LBB));
		}
	}
	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckEmptyBranchFilter(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	auto LBBs = CollectAnimNodesOfType<UAnimGraphNode_LayeredBoneBlend>(AnimBP);
	for (UAnimGraphNode_LayeredBoneBlend* LBB : LBBs)
	{
		// Inspect Node.LayerSetup via direct access (public in UE5 anim graph node classes).
		// Each FInputBlendPose entry has a BranchFilters TArray<FBranchFilter>.
		for (int32 i = 0; i < LBB->Node.LayerSetup.Num(); ++i)
		{
			const FInputBlendPose& Layer = LBB->Node.LayerSetup[i];
			if (Layer.BranchFilters.Num() == 0)
			{
				Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
					FString::Printf(TEXT("LayeredBoneBlend '%s' layer %d has no BranchFilters configured -- blends the entire skeleton, defeating the purpose of the node."),
						*LBB->GetNodeTitle(ENodeTitleType::ListView).ToString(), i),
					FString::Printf(TEXT("LayeredBoneBlend '%s' layer %d has no bone filters (blends entire skeleton)"),
						*LBB->GetNodeTitle(ENodeTitleType::ListView).ToString(), i),
					EBPDoctorAssetType::AnimBP, LBB));
			}
		}
	}
	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckDisconnectedSlotSource(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	auto Slots = CollectAnimNodesOfType<UAnimGraphNode_Slot>(AnimBP);
	for (UAnimGraphNode_Slot* SlotNode : Slots)
	{
		for (UEdGraphPin* Pin : SlotNode->Pins)
		{
			if (Pin->Direction != EGPD_Input) continue;
			if (Pin->PinName != TEXT("Source")) continue;
			if (Pin->LinkedTo.Num() == 0)
			{
				Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
					FString::Printf(TEXT("Slot '%s' Source input pin has no connection -- slot will output T-pose when no montage is active."),
						*SlotNode->Node.SlotName.ToString()),
					FString::Printf(TEXT("Slot '%s' Source pin is disconnected — will output T-pose between montages"),
						*SlotNode->Node.SlotName.ToString()),
					EBPDoctorAssetType::AnimBP, SlotNode));
			}
			break;
		}
	}
	return Results;
}

// ─────────────────────────────────────────────────────────────────
//  ANIMBP CHECK IMPLEMENTATIONS v3 (35-39) — Sprint 5 Phase D
// ─────────────────────────────────────────────────────────────────

TArray<FBPDoctorResult> FBPDoctorChecks::CheckRootMotionModeMismatch(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	// Read the AnimBP's effective RootMotionMode from the CDO. GeneratedClass is the
	// UAnimBlueprintGeneratedClass; GetDefaultObject<UAnimInstance>() gives us the AnimInstance
	// CDO where RootMotionMode lives (Engine/Source/Runtime/Engine/Classes/Animation/AnimInstance.h:366).
	if (!AnimBP->GeneratedClass) return Results;
	UAnimInstance* CDO = AnimBP->GeneratedClass->GetDefaultObject<UAnimInstance>();
	if (!CDO) return Results;

	const ERootMotionMode::Type Mode = CDO->RootMotionMode.GetValue();

	// Only two modes produce silent failures when sequences have bEnableRootMotion=true:
	//   - RootMotionFromMontagesOnly: motion is silently dropped from non-montage SequencePlayers
	//   - IgnoreRootMotion: motion is extracted but discarded — character pivots in-place
	const bool bMontagesOnly = (Mode == ERootMotionMode::RootMotionFromMontagesOnly);
	const bool bIgnoreRM     = (Mode == ERootMotionMode::IgnoreRootMotion);
	if (!bMontagesOnly && !bIgnoreRM) return Results;

	const FString ModeStr = bMontagesOnly
		? TEXT("RootMotionFromMontagesOnly (motion from non-montage SequencePlayers is silently dropped)")
		: TEXT("IgnoreRootMotion (motion is extracted then discarded — character pivots in-place)");

	auto Flag = [&](UEdGraphNode* Node, const FString& AnimName, const FString& Context)
	{
		Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
			FString::Printf(TEXT("'%s' has EnableRootMotion=true but AnimBP RootMotionMode is %s. Found via: %s"),
				*AnimName, *ModeStr, *Context),
			FString::Printf(TEXT("RootMotion mismatch: '%s' has root motion, AnimBP discards it (%s)"),
				*AnimName, bMontagesOnly ? TEXT("non-montage path") : TEXT("ignore mode")),
			EBPDoctorAssetType::AnimBP, Node));
	};

	auto SeqPlayers = CollectAnimNodesOfType<UAnimGraphNode_SequencePlayer>(AnimBP);
	for (UAnimGraphNode_SequencePlayer* Player : SeqPlayers)
	{
		UAnimSequence* Seq = Cast<UAnimSequence>(Player->GetAnimationAsset());
		if (!Seq || !Seq->bEnableRootMotion) continue;
		Flag(Player, Seq->GetName(), TEXT("SequencePlayer node"));
	}

	auto BSPlayers = CollectAnimNodesOfType<UAnimGraphNode_BlendSpacePlayer>(AnimBP);
	for (UAnimGraphNode_BlendSpacePlayer* BSPlayer : BSPlayers)
	{
		UBlendSpace* BS = Cast<UBlendSpace>(BSPlayer->GetAnimationAsset());
		if (!BS) continue;
		for (const FBlendSample& Sample : BS->GetBlendSamples())
		{
			if (!Sample.Animation || !Sample.Animation->bEnableRootMotion) continue;
			Flag(BSPlayer, Sample.Animation->GetName(),
				FString::Printf(TEXT("BlendSpace '%s' sample"), *BS->GetName()));
		}
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckLinkedAnimLayerNoLayer(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	// Walk LinkedAnimLayer nodes including SM-state-internal ones (CollectAnimNodesOfType is
	// the SM-recursive walker). FAnimNode_LinkedAnimLayer::Layer is the FName of the layer
	// to evaluate. IsNone() = no layer chosen = T-pose at runtime regardless of Interface.
	auto LayerNodes = CollectAnimNodesOfType<UAnimGraphNode_LinkedAnimLayer>(AnimBP);
	for (UAnimGraphNode_LinkedAnimLayer* LayerNode : LayerNodes)
	{
		if (LayerNode->Node.Layer.IsNone())
		{
			const FString NodeTitle = LayerNode->GetNodeTitle(ENodeTitleType::ListView).ToString();
			Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
				FString::Printf(TEXT("LinkedAnimLayer node '%s' has no Layer selected — outputs T-pose silently. Set a Layer in the node's Details panel."),
					*NodeTitle),
				FString::Printf(TEXT("LinkedAnimLayer '%s' has no Layer set — T-pose"), *NodeTitle),
				EBPDoctorAssetType::AnimBP, LayerNode));
		}
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckCurveAlphaMissing(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	USkeleton* Skel = AnimBP->TargetSkeleton;
	if (!Skel) return Results;

	// Walk every anim graph node (SM-recursive). Look for nodes whose inner Node struct has
	// AlphaInputType + AlphaCurveName (the FAnimNodeAlphaOptions pattern). When AlphaInputType
	// == Curve and AlphaCurveName names a curve missing from skeleton metadata, the runtime
	// returns 0 every frame — blend stuck off.
	TArray<UAnimGraphNode_Base*> AllNodes = GetAnimGraphNodes(AnimBP);
	for (UAnimGraphNode_Base* GraphNode : AllNodes)
	{
		if (!GraphNode) continue;

		// Most editor nodes wrap their runtime struct in a property literally named "Node".
		FStructProperty* NodeProp = CastField<FStructProperty>(
			GraphNode->GetClass()->FindPropertyByName(TEXT("Node")));
		if (!NodeProp) continue;

		void* InnerPtr = NodeProp->ContainerPtrToValuePtr<void>(GraphNode);

		// AlphaInputType is TEnumAsByte<EAnimAlphaInputType> stored as FByteProperty.
		FProperty* AlphaTypeProp = NodeProp->Struct->FindPropertyByName(TEXT("AlphaInputType"));
		FByteProperty* ByteProp = CastField<FByteProperty>(AlphaTypeProp);
		if (!ByteProp) continue;

		const uint8 AlphaTypeVal = ByteProp->GetPropertyValue(
			ByteProp->ContainerPtrToValuePtr<void>(InnerPtr));

		// Compile-time enum value extraction — bulletproof against UE renumbering EAnimAlphaInputType.
		static const uint8 CurveAlphaType = static_cast<uint8>(EAnimAlphaInputType::Curve);
		if (AlphaTypeVal != CurveAlphaType) continue;

		FProperty* CurveNameProp = NodeProp->Struct->FindPropertyByName(TEXT("AlphaCurveName"));
		FNameProperty* NameProp = CastField<FNameProperty>(CurveNameProp);
		if (!NameProp) continue;

		const FName CurveName = NameProp->GetPropertyValue(
			NameProp->ContainerPtrToValuePtr<void>(InnerPtr));
		if (CurveName.IsNone()) continue;

		// USkeleton::GetCurveMetaData returns nullptr if the curve doesn't exist.
		// (Engine/Source/Runtime/Engine/Classes/Animation/Skeleton.h:387-388 — UE 5.7 stable.)
		if (Skel->GetCurveMetaData(CurveName) == nullptr)
		{
			const FString NodeTitle = GraphNode->GetNodeTitle(ENodeTitleType::ListView).ToString();
			Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
				FString::Printf(TEXT("Node '%s' uses AlphaInputType=Curve with curve name '%s', but '%s' does not exist in skeleton '%s' curve metadata — blend alpha is permanently 0."),
					*NodeTitle, *CurveName.ToString(), *CurveName.ToString(), *Skel->GetName()),
				FString::Printf(TEXT("'%s' alpha curve '%s' missing from skeleton — blend stuck at 0"),
					*NodeTitle, *CurveName.ToString()),
				EBPDoctorAssetType::AnimBP, GraphNode));
		}
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckMontageSectionLoop(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	// Find AnimMontage references via PlayMontage / Montage_Play K2 calls in the AnimBP graphs.
	// This is the most common authoring path that ties an AnimBP to specific montages. Indie
	// projects use it heavily; AAA projects often trigger from C++ instead, in which case this
	// check has narrow scope (acceptable v1 trade-off — AAA-style direct-asset scanning is a
	// future expansion via dedicated AnimMontage scanner pass).
	TSet<UAnimMontage*> Visited;
	TMap<UAnimMontage*, UEdGraphNode*> AttributedNode; // node to attribute the result to

	auto K2Calls = CollectNodesOfType<UK2Node_CallFunction>(AnimBP);
	for (UK2Node_CallFunction* Call : K2Calls)
	{
		const FName FnName = Call->FunctionReference.GetMemberName();
		const bool bIsMontagePlay = (FnName == TEXT("Montage_Play"))
			|| (FnName == TEXT("PlayAnimMontage"))
			|| (FnName == TEXT("PlayMontage"));
		if (!bIsMontagePlay) continue;

		for (UEdGraphPin* Pin : Call->Pins)
		{
			if (Pin->Direction != EGPD_Input) continue;
			// Pin name varies: "Montage", "AnimMontage", or "MontageToPlay" depending on which
			// flavor of the function the user picked. Match by object type via DefaultObject.
			if (UAnimMontage* Montage = Cast<UAnimMontage>(Pin->DefaultObject))
			{
				if (!Visited.Contains(Montage))
				{
					Visited.Add(Montage);
					AttributedNode.Add(Montage, Call);
				}
			}
		}
	}

	// For each unique montage, walk CompositeSections detecting cycles with no exit.
	for (UAnimMontage* Montage : Visited)
	{
		if (!Montage) continue;
		const TArray<FCompositeSection>& Sections = Montage->CompositeSections;
		if (Sections.Num() == 0) continue;

		// Build SectionName -> NextSectionName map
		TMap<FName, FName> NextOf;
		for (const FCompositeSection& Sec : Sections)
		{
			NextOf.Add(Sec.SectionName, Sec.NextSectionName);
		}

		// For each section, walk the chain via NextOf with a visited set.
		// If we revisit any section in the current chain BEFORE hitting NAME_None, it's a closed loop.
		for (const FCompositeSection& StartSec : Sections)
		{
			TSet<FName> SeenInChain;
			FName Current = StartSec.SectionName;
			SeenInChain.Add(Current);

			// Self-loop short-circuit (most common bug):
			if (NextOf.FindRef(Current) == Current)
			{
				UEdGraphNode** NodePtr = AttributedNode.Find(Montage);
				Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
					FString::Printf(TEXT("AnimMontage '%s' section '%s' has NextSectionName pointing to itself — self-loop with no exit. Montage_Ended will never fire."),
						*Montage->GetName(), *Current.ToString()),
					FString::Printf(TEXT("Montage '%s' section '%s' self-loops"),
						*Montage->GetName(), *Current.ToString()),
					EBPDoctorAssetType::AnimBP, NodePtr ? *NodePtr : nullptr));
				continue; // Don't double-report this section in the multi-step walk below
			}

			// Multi-step walk — detect closed cycles A->B->A or longer
			constexpr int32 MaxWalkDepth = 32; // guard against absurdly long chains
			for (int32 Step = 0; Step < MaxWalkDepth; ++Step)
			{
				const FName Next = NextOf.FindRef(Current);
				if (Next.IsNone()) break; // Terminal — montage ends here, no infinite loop
				if (SeenInChain.Contains(Next))
				{
					// Closed cycle detected. Report on the starting section.
					UEdGraphNode** NodePtr = AttributedNode.Find(Montage);
					Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
						FString::Printf(TEXT("AnimMontage '%s' section chain starting at '%s' forms a closed cycle (revisits '%s') with no terminal section. Montage_Ended will never fire."),
							*Montage->GetName(), *StartSec.SectionName.ToString(), *Next.ToString()),
						FString::Printf(TEXT("Montage '%s' section '%s' loops back via '%s' with no exit"),
							*Montage->GetName(), *StartSec.SectionName.ToString(), *Next.ToString()),
						EBPDoctorAssetType::AnimBP, NodePtr ? *NodePtr : nullptr));
					break;
				}
				SeenInChain.Add(Next);
				Current = Next;
			}
		}
	}

	return Results;
}

TArray<FBPDoctorResult> FBPDoctorChecks::CheckBlendSpaceZeroAxis(const FBPDoctorCheckDef& Check, UAnimBlueprint* AnimBP)
{
	using namespace BPDoctorUtil;
	TArray<FBPDoctorResult> Results;

	// Walk BlendSpacePlayer nodes (existing #8 INVALID_BSPACE pattern). For each referenced
	// BlendSpace, check axes for Min ~== Max — a collapsed range that defeats interpolation.
	// v2.7.2 audit fix: CollectAnimNodesOfType (not CollectNodesOfType) so SM-state-internal
	// nodes are walked. Locomotion AnimBPs put BlendSpacePlayer nodes inside states 99% of
	// the time — without recursion this check fired on zero real projects.
	auto BSPlayers = CollectAnimNodesOfType<UAnimGraphNode_BlendSpacePlayer>(AnimBP);
	TSet<UBlendSpace*> Seen; // Dedupe — same BS often referenced by multiple nodes

	for (UAnimGraphNode_BlendSpacePlayer* BSPlayer : BSPlayers)
	{
		UBlendSpace* BS = Cast<UBlendSpace>(BSPlayer->GetAnimationAsset());
		if (!BS) continue;
		if (Seen.Contains(BS)) continue;
		Seen.Add(BS);

		// UBlendSpace exposes 2 axes (BlendSpace 1D uses only axis 0). Reading both is safe —
		// for 1D, axis 1's parameter is unused (typically (0, 0)), but FMath::IsNearlyEqual
		// would also flag axis 1 of a 1D as zero-range. Guard: if axis 1 is the conventional
		// (0,0) AND DimensionSize is 1, skip axis 1.
		const int32 NumDimensions = BS->IsA<UBlendSpace1D>() ? 1 : 2;
		const TCHAR* AxisLabels[2] = { TEXT("Horizontal Axis"), TEXT("Vertical Axis") };

		for (int32 Axis = 0; Axis < NumDimensions; ++Axis)
		{
			const FBlendParameter& Param = BS->GetBlendParameter(Axis);
			if (FMath::IsNearlyEqual(Param.Min, Param.Max))
			{
				Results.Add(MakeResult(Check, AnimBP->GetName(), AnimBP->GetPathName(),
					FString::Printf(TEXT("BlendSpace '%s' %s '%s' has Min=%.3f Max=%.3f — zero range, interpolation impossible. Set Min < Max or this axis is dead."),
						*BS->GetName(), AxisLabels[Axis], *Param.DisplayName, Param.Min, Param.Max),
					FString::Printf(TEXT("BlendSpace '%s' %s zero range (%.3f..%.3f)"),
						*BS->GetName(), AxisLabels[Axis], Param.Min, Param.Max),
					EBPDoctorAssetType::AnimBP, BSPlayer));
			}
		}
	}

	return Results;
}
