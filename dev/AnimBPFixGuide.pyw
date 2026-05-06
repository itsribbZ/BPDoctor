#!/usr/bin/env python3
# ══════════════════════════════════════════════════════════════════
#  AnimBP Fix Guide v1.0 — BP Doctor
#  Step-by-step repair companion for AnimBP Doctor
#  Reads scan results and generates detailed, user-friendly
#  fix instructions for every issue found.
# ══════════════════════════════════════════════════════════════════

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import os
import html as html_module
import webbrowser
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional

# ─────────────────────────────────────────────────────────────────
#  THEME — Doctor Dark (shared with AnimBP Doctor)
# ─────────────────────────────────────────────────────────────────

class Theme:
    BG_DEEP      = "#0a0e1a"
    BG_SURFACE   = "#111827"
    BG_CARD      = "#1a2035"
    BG_HOVER     = "#1e2a45"
    BG_INPUT     = "#0f1629"
    BG_STEP      = "#0d1a2d"
    ACCENT       = "#00d4ff"
    ACCENT_DIM   = "#0088aa"
    MAGENTA      = "#e040fb"
    SUCCESS      = "#00e676"
    WARNING      = "#ffab00"
    ERROR        = "#ff1744"
    INFO         = "#448aff"
    TEXT         = "#e8eaed"
    TEXT_DIM     = "#9aa0a6"
    TEXT_MUTED   = "#5f6368"
    BORDER       = "#2a3150"
    STEP_NUM     = "#00d4ff"
    TIP_BG       = "#1a2a1a"
    TIP_BORDER   = "#2a5a2a"
    WARN_BG      = "#2a2a1a"
    WARN_BORDER  = "#5a5a2a"

    @staticmethod
    def severity_color(sev):
        return {"ERROR": Theme.ERROR, "WARNING": Theme.WARNING, "INFO": Theme.INFO
                }.get(sev, Theme.TEXT_DIM)

# ─────────────────────────────────────────────────────────────────
#  FIX GUIDE DATABASE — Detailed step-by-step for each check
# ─────────────────────────────────────────────────────────────────

@dataclass
class FixStep:
    number: int
    title: str
    instruction: str
    details: str = ""
    tip: str = ""
    warning: str = ""
    screenshot_hint: str = ""

@dataclass
class FixGuide:
    check_code: str
    check_name: str
    severity: str
    summary: str
    what_went_wrong: str
    why_it_happened: str
    time_saved: str
    steps: List[FixStep]
    prevention: str
    related_docs: List[str]

# All 26 fix guides (12 AnimBP + 14 General BP)
FIX_GUIDES: Dict[str, FixGuide] = {

    "NULL_ANIM_REF": FixGuide(
        check_code="NULL_ANIM_REF",
        check_name="Null Anim Reference",
        severity="ERROR",
        summary="A Sequence Player node in your AnimGraph has no animation assigned to it.",
        what_went_wrong=(
            "One or more AnimGraphNode_SequencePlayer nodes in your Animation Blueprint "
            "are pointing to nothing. When the state machine enters this state, the engine "
            "has no animation to play, so the character snaps to the reference pose (T-pose)."
        ),
        why_it_happened=(
            "This usually happens when:\n"
            "  - An animation asset was deleted or renamed after being assigned\n"
            "  - A new state was added to the state machine but never configured\n"
            "  - An AnimBP was duplicated and the references broke\n"
            "  - Content was migrated between projects with missing dependencies"
        ),
        time_saved="1-4 hours (intermittent T-pose debugging)",
        steps=[
            FixStep(1, "Open the Animation Blueprint",
                "Double-click the flagged AnimBP in the Content Browser to open it.",
                "The AnimBP will open in the Animation Blueprint Editor with the AnimGraph tab visible."),
            FixStep(2, "Find the Sequence Player nodes",
                "In the AnimGraph, look for Sequence Player nodes. These are the nodes "
                "that play individual animation sequences.",
                "Sequence Players appear as rectangular nodes with an animation name (or 'None') inside.",
                tip="Press Ctrl+F in the AnimGraph to search for 'Sequence Player' to find them quickly."),
            FixStep(3, "Identify the empty one(s)",
                "Look for any Sequence Player that shows 'None' or has no animation preview thumbnail.",
                "The problematic node will have an empty or red-highlighted animation slot."),
            FixStep(4, "Assign the correct animation",
                "Click on the empty Sequence Player node. In the Details panel on the right, "
                "find the 'Sequence' property and click the dropdown to select the correct animation.",
                "Make sure the animation you select uses the same Skeleton as this AnimBP.",
                tip="You can type in the search box to filter animations. Look for animations that match "
                    "the state name (e.g., if the state is 'Idle', search for idle animations)."),
            FixStep(5, "Compile and test",
                "Click the Compile button in the toolbar (or press F7). Then test in PIE (Play In Editor) "
                "to verify the character plays the correct animation in that state.",
                warning="If the animation uses a different skeleton, you'll get a separate Skeleton Mismatch error. "
                        "Make sure to use animations that target the correct skeleton."),
        ],
        prevention="Always assign an animation immediately when creating a new state. Never leave "
                   "Sequence Player nodes empty, even temporarily.",
        related_docs=[
            "UE5 Docs: Animation Blueprints Overview",
            "UE5 Docs: State Machines",
            "UE5 Docs: Using Sequence Player Nodes",
        ]
    ),

    "BROKEN_BLEND_WT": FixGuide(
        check_code="BROKEN_BLEND_WT",
        check_name="Broken Blend Weight",
        severity="WARNING",
        summary="A blend weight value is outside the valid [0.0, 1.0] range.",
        what_went_wrong=(
            "A LayeredBoneBlend or similar blend node has a weight value that is less than 0 "
            "or greater than 1. UE5 does NOT automatically clamp blend weights, so out-of-range "
            "values produce incorrect blend results — the character may jitter, pop, or show "
            "impossible poses."
        ),
        why_it_happened=(
            "This usually happens when:\n"
            "  - A weight was manually typed incorrectly (e.g., 1.5 instead of 0.5)\n"
            "  - A Blueprint variable driving the weight has no clamp/range limit\n"
            "  - An animation curve or procedural value exceeded expected bounds\n"
            "  - Copy-paste from another node brought incorrect default values"
        ),
        time_saved="30 min - 1 hour (subtle blend debugging with Pose Watch)",
        steps=[
            FixStep(1, "Open the Animation Blueprint",
                "Double-click the flagged AnimBP in the Content Browser."),
            FixStep(2, "Find the blend node",
                "Look for LayeredBoneBlend or Blend nodes in the AnimGraph. "
                "The issue is in a node that has a BlendWeight property.",
                tip="Check the node hint in the scan result — it may show the exact weight value found."),
            FixStep(3, "Select the blend node",
                "Click on the blend node to see its properties in the Details panel."),
            FixStep(4, "Fix the weight value",
                "In the Details panel, find 'Blend Weights' or 'Alpha' property. "
                "Ensure all values are between 0.0 and 1.0.",
                "0.0 = fully first pose, 1.0 = fully second pose, 0.5 = equal blend.",
                tip="If the weight is driven by a variable, add a Clamp node (FMath::Clamp) "
                    "in your AnimInstance Blueprint to ensure the value stays in range."),
            FixStep(5, "Add a safety clamp (recommended)",
                "If the weight comes from gameplay code, add a Clamp node between the variable "
                "and the blend weight input:\n\n"
                "  In AnimGraph: Get [YourVariable] -> Clamp (Min=0, Max=1) -> BlendWeight\n\n"
                "This prevents future out-of-range values from ever reaching the blend.",
                tip="In C++, use: FMath::Clamp(Weight, 0.0f, 1.0f)"),
            FixStep(6, "Compile and verify",
                "Compile (F7) and test in PIE. Watch the blend behavior during gameplay "
                "to confirm the character blends smoothly without pops."),
        ],
        prevention="Always clamp blend weight inputs. Add meta=(ClampMin=0, ClampMax=1) to any "
                   "UPROPERTY that drives a blend weight.",
        related_docs=[
            "UE5 Docs: Layered Bone Blend",
            "UE5 Docs: Animation Blend Nodes",
            "UE5 Docs: FMath::Clamp",
        ]
    ),

    "SKEL_MISMATCH": FixGuide(
        check_code="SKEL_MISMATCH",
        check_name="Skeleton Mismatch",
        severity="ERROR",
        summary="An animation asset in this AnimBP targets a different skeleton.",
        what_went_wrong=(
            "One or more animation assets (sequences, montages, or blendspaces) referenced "
            "by this AnimBP were created for a different skeleton. When UE5 tries to play these "
            "animations, bones don't map correctly — causing distorted meshes, bones in wrong "
            "positions, or outright cook/package failures."
        ),
        why_it_happened=(
            "This usually happens when:\n"
            "  - Animations from a marketplace pack use a different skeleton\n"
            "  - The project's skeleton was replaced/updated but old animations weren't retargeted\n"
            "  - An AnimBP was duplicated for a different character without updating animation refs\n"
            "  - Content migration brought animations from another project"
        ),
        time_saved="2-8 hours (often not caught until cook/package time)",
        steps=[
            FixStep(1, "Identify the mismatched skeleton",
                "Check the scan result's node hint — it shows which skeleton names were found. "
                "Compare these to determine which is the 'correct' skeleton for this AnimBP.",
                tip="Right-click the AnimBP in Content Browser > Asset Actions > Show References "
                    "to see all referenced assets."),
            FixStep(2, "Open the AnimBP and check its skeleton",
                "Open the AnimBP. In the toolbar, look at the Skeleton/Mesh info. "
                "This is the skeleton that ALL animations in this AnimBP must target.",
                "The AnimBP's skeleton is set when the AnimBP is created and cannot be changed."),
            FixStep(3, "Find the mismatched animation(s)",
                "In the AnimGraph, check each Sequence Player and BlendSpace node. "
                "Click each one and verify the animation's skeleton matches the AnimBP's skeleton.",
                "Mismatched animations may show a yellow warning icon.",
                tip="Use Window > Reference Viewer to see all animation assets used by this AnimBP."),
            FixStep(4, "Option A: Retarget the animation",
                "If the animation is from a different skeleton, use UE5's Retargeting system:\n\n"
                "  1. Open the animation asset\n"
                "  2. Go to Asset > Retarget Anim Assets > Duplicate and Retarget\n"
                "  3. Select your AnimBP's skeleton as the target\n"
                "  4. Replace the old animation reference with the retargeted version",
                tip="UE5.4+ has IK Retargeter which produces much better results than the legacy system."),
            FixStep(5, "Option B: Replace with a compatible animation",
                "If retargeting isn't viable, find or create an animation that was made for "
                "the correct skeleton and assign it to the Sequence Player.",
                warning="Do NOT just change the AnimBP's skeleton — this will break ALL other animations in it."),
            FixStep(6, "Compile, save, and test a cook",
                "After fixing all mismatches, compile (F7), save, and do a test cook "
                "(File > Cook Content for [Platform]) to verify no skeleton errors remain.",
                warning="Skeleton mismatches can cascade. Fix them all before testing, or you may "
                        "see new errors after fixing the first one."),
        ],
        prevention="Establish a naming convention (e.g., all anims for SK_Mannequin start with 'A_Mannequin_'). "
                   "Always verify skeleton compatibility when importing marketplace animations.",
        related_docs=[
            "UE5 Docs: Animation Retargeting",
            "UE5 Docs: IK Retargeter",
            "UE5 Docs: Skeleton Compatibility",
        ]
    ),

    "MISSING_SLOT": FixGuide(
        check_code="MISSING_SLOT",
        check_name="Missing Default Slot",
        severity="WARNING",
        summary="Your AnimBP references montages but has no Slot node — montages will silently fail.",
        what_went_wrong=(
            "Your AnimBP has montage-related references but no AnimGraphNode_Slot in the AnimGraph. "
            "Without a Slot node, calls to PlayMontage() from gameplay code will silently do nothing. "
            "The AnimBP compiles clean. The montage plays in preview. But in-game — nothing happens."
        ),
        why_it_happened=(
            "This is the #1 AnimBP question on forums. It happens because:\n"
            "  - The Slot node is not added by default when creating a new AnimBP\n"
            "  - UE5 gives ZERO warnings about this — it compiles and runs without errors\n"
            "  - Developers assume PlayMontage() will 'just work' without an AnimGraph slot\n"
            "  - The Slot node is often forgotten when rebuilding or simplifying an AnimGraph"
        ),
        time_saved="30 min - 2 hours (the most common 'why won't my montage play' problem)",
        steps=[
            FixStep(1, "Open the Animation Blueprint",
                "Double-click the flagged AnimBP in the Content Browser."),
            FixStep(2, "Go to the AnimGraph",
                "Click the 'AnimGraph' tab at the top of the editor. You should see your "
                "state machine or blend nodes connected to the Output Pose.",
                "The Output Pose node is the final output — everything must eventually connect to it."),
            FixStep(3, "Right-click to add a Slot node",
                "Right-click in an empty area of the AnimGraph. Search for 'Slot' in the context menu. "
                "Select 'Slot' to add a DefaultSlot node.",
                tip="The node will be named 'DefaultSlot' by default. You can change the slot name "
                    "in the Details panel if you use named slots (e.g., 'UpperBody', 'FullBody')."),
            FixStep(4, "Wire the Slot node into the chain",
                "The Slot node needs to be BETWEEN your animation logic and the Output Pose:\n\n"
                "  BEFORE:  [State Machine] -> [Output Pose]\n"
                "  AFTER:   [State Machine] -> [Slot 'DefaultSlot'] -> [Output Pose]\n\n"
                "Disconnect the wire going into Output Pose. Connect State Machine output "
                "to Slot input. Connect Slot output to Output Pose input.",
                warning="The Slot node must be AFTER your state machine/blend logic and BEFORE "
                        "the Output Pose. If it's in the wrong position, montages may override "
                        "all animations or not blend correctly."),
            FixStep(5, "Verify the slot name matches your code",
                "If your gameplay code uses a specific slot name in PlayMontage(), make sure "
                "the Slot node's SlotName matches.\n\n"
                "  In C++:   PlayAnimMontage(Montage, 1.0f, NAME_None);\n"
                "  Slot name: 'DefaultSlot' (matches NAME_None / default)\n\n"
                "  In C++:   PlaySlotAnimationAsDynamicMontage(Montage, 'UpperBody');\n"
                "  Slot name: 'UpperBody' (must match exactly)",
                tip="Most projects just use 'DefaultSlot' unless you need layered montages "
                    "(e.g., upper body attack while legs keep running)."),
            FixStep(6, "Compile and test montage playback",
                "Compile (F7). In PIE, trigger the action that plays a montage. "
                "You should now see the montage play on your character.",
                tip="If the montage still doesn't play, check: Is the montage using the correct skeleton? "
                    "Is the slot name matching? Is PlayMontage actually being called? (Add a log/breakpoint)"),
        ],
        prevention="ALWAYS add a Slot node when creating a new AnimBP. Make it part of your "
                   "AnimBP template. Even if you don't use montages yet, the Slot node has zero cost.",
        related_docs=[
            "UE5 Docs: Animation Montages",
            "UE5 Docs: Using Montage Slots",
            "UE5 Docs: PlayAnimMontage",
        ]
    ),

    "BROKEN_TRANS": FixGuide(
        check_code="BROKEN_TRANS",
        check_name="Broken Transition",
        severity="WARNING",
        summary="Your state machine has states with no inbound transitions — they can never be reached.",
        what_went_wrong=(
            "One or more states in your AnimBP's state machine have no transitions leading INTO them. "
            "These states exist in the graph but can never be entered during gameplay. If they were "
            "meant to be reachable, your character is missing animation states."
        ),
        why_it_happened=(
            "This usually happens when:\n"
            "  - A transition was accidentally deleted during graph cleanup\n"
            "  - A state was added but never connected\n"
            "  - Refactoring moved states around and left orphaned connections\n"
            "  - The state machine grew organically and nobody audited connectivity"
        ),
        time_saved="2-6 hours (character gets 'stuck' in an animation with no way out)",
        steps=[
            FixStep(1, "Open the state machine",
                "In the AnimGraph, double-click the State Machine node to enter it. "
                "You'll see all states as boxes with transition arrows between them."),
            FixStep(2, "Visually inspect for isolated states",
                "Look for any state box that has NO arrows pointing INTO it (only arrows going OUT, "
                "or no arrows at all). These are unreachable.",
                tip="Zoom out (scroll wheel) to see the full state machine. Isolated states are "
                    "often pushed to the edges of the graph."),
            FixStep(3, "Decide: connect or remove",
                "For each unreachable state, ask:\n"
                "  - Was this supposed to be reachable? -> Add transitions\n"
                "  - Is this leftover from old design? -> Delete it\n"
                "  - Is this a future state not yet connected? -> Leave it but add a comment"),
            FixStep(4, "To add a transition",
                "Hover over the edge of the SOURCE state (the state you want to transition FROM). "
                "A green '+' or arrow icon appears. Click and drag to the TARGET state.\n\n"
                "Then double-click the new transition arrow to set up the transition rule "
                "(the condition that triggers the state change).",
                tip="Common transition conditions: Bool variables (IsJumping, IsAttacking), "
                    "Time Remaining < 0.1 (for sequential animations), or Gameplay Tags."),
            FixStep(5, "To remove a dead state",
                "Right-click the unreachable state and select 'Delete'. This removes the state "
                "and any outgoing transitions.",
                warning="Before deleting, make sure the state isn't referenced elsewhere "
                        "(e.g., in Blueprint code via state name)."),
            FixStep(6, "Compile and trace the state machine",
                "Compile (F7). In PIE, enable the Animation Blueprint debugger "
                "(Debug menu > select your character). Watch the state machine execute and verify "
                "all states are reachable through normal gameplay.",
                tip="The debugger highlights the active state in green and shows transition values in real-time."),
        ],
        prevention="After adding any state, immediately create at least one inbound transition. "
                   "Periodically audit state machines with 10+ states for connectivity.",
        related_docs=[
            "UE5 Docs: State Machines Overview",
            "UE5 Docs: Transition Rules",
            "UE5 Docs: Animation Blueprint Debugging",
        ]
    ),

    "TPOSE_FALLBACK": FixGuide(
        check_code="TPOSE_FALLBACK",
        check_name="T-Pose Fallback",
        severity="ERROR",
        summary="A LayeredBoneBlend has a disconnected BasePose — causing partial T-pose.",
        what_went_wrong=(
            "A LayeredBoneBlend node in your AnimGraph has its BasePose input disconnected or "
            "pointing to nothing. When UE5 evaluates this node, it uses the reference pose "
            "(T-pose) for the base layer, causing the character to partially T-pose on the "
            "affected bones."
        ),
        why_it_happened=(
            "This usually happens when:\n"
            "  - The BasePose wire was accidentally disconnected during graph editing\n"
            "  - A node upstream was deleted without reconnecting the chain\n"
            "  - Copy-pasting nodes broke the pin connections\n"
            "  - The AnimGraph was partially rebuilt and this connection was missed"
        ),
        time_saved="1-3 hours (extremely hard to reproduce — depends on blend timing)",
        steps=[
            FixStep(1, "Open the AnimGraph",
                "Open the flagged AnimBP and go to the AnimGraph tab."),
            FixStep(2, "Find the LayeredBoneBlend node",
                "Look for a node labeled 'Layered Blend per Bone' or 'LayeredBoneBlend'. "
                "It has multiple inputs: BasePose and one or more BlendPose inputs.",
                tip="The scan result's node hint tells you which specific node was flagged."),
            FixStep(3, "Check the BasePose input",
                "The TOP input pin (labeled 'BasePose') must be connected. If it shows no wire "
                "or is connected to a grayed-out/deleted node, that's the problem.",
                "BasePose is what the character looks like when NO blend is applied. Without it, "
                "UE5 uses T-pose as the fallback."),
            FixStep(4, "Reconnect the BasePose",
                "Connect the BasePose input to your main animation chain. Usually this is:\n\n"
                "  [State Machine Output] -> [BasePose input of LayeredBoneBlend]\n\n"
                "The BasePose should be your character's full-body animation (idle, locomotion, etc.). "
                "The BlendPose inputs are the overlays (upper body attacks, etc.).",
                warning="Do NOT leave BasePose disconnected 'because it works sometimes.' "
                        "It will T-pose unpredictably based on blend weight timing."),
            FixStep(5, "Verify blend settings",
                "Select the LayeredBoneBlend node. In Details, check:\n"
                "  - Bone names in the blend mask are correct\n"
                "  - Blend weights are in [0, 1] range\n"
                "  - Blend depth is appropriate for your skeleton"),
            FixStep(6, "Compile and test with montages",
                "Compile (F7). Test in PIE by triggering actions that activate the blend "
                "(e.g., attack while running). Watch for any momentary T-pose flashes.",
                tip="If the T-pose was intermittent, test multiple times with different "
                    "animation timings to confirm it's fully fixed."),
        ],
        prevention="Never disconnect the BasePose input of a LayeredBoneBlend. If you need to "
                   "temporarily disable blending, set the blend weight to 0 instead.",
        related_docs=[
            "UE5 Docs: Layered Blend per Bone",
            "UE5 Docs: Animation Blending",
            "UE5 Docs: Bone-Based Blending",
        ]
    ),

    "ORPHANED_NODE": FixGuide(
        check_code="ORPHANED_NODE",
        check_name="Orphaned Node",
        severity="INFO",
        summary="Nodes exist in the AnimGraph that aren't connected to the Output Pose chain.",
        what_went_wrong=(
            "Your AnimGraph contains nodes that are floating — not connected to the final "
            "Output Pose through any chain of connections. These nodes do nothing at runtime "
            "but clutter the graph and confuse anyone reading it."
        ),
        why_it_happened=(
            "This happens when:\n"
            "  - Nodes were disconnected during refactoring but not deleted\n"
            "  - Old experiments or test setups were left in the graph\n"
            "  - The AnimGraph evolved organically without cleanup passes"
        ),
        time_saved="10-15 min per debug session (mental noise filtering adds up)",
        steps=[
            FixStep(1, "Open the AnimGraph",
                "Open the flagged AnimBP and go to the AnimGraph tab."),
            FixStep(2, "Zoom out to see the full graph",
                "Use the scroll wheel to zoom out. Orphaned nodes are usually visually "
                "separated from the main connected graph.",
                tip="Press Home to fit the entire graph in view."),
            FixStep(3, "Identify disconnected clusters",
                "Look for nodes or groups of nodes that have no wire path leading to the "
                "Output Pose node (the green node on the right)."),
            FixStep(4, "Decide: reconnect or delete",
                "For each orphaned node:\n"
                "  - If it was meant to be connected: wire it into the correct place\n"
                "  - If it's leftover from old work: select it and press Delete\n"
                "  - If unsure: add a comment node explaining what it's for",
                tip="Select multiple nodes by holding Shift+Click or drawing a box selection. "
                    "Delete all selected with the Delete key."),
            FixStep(5, "Clean up the layout",
                "After removing orphaned nodes, right-click > Straighten Connections to "
                "clean up the remaining graph layout.",
                tip="A clean graph is easier to debug. Future-you will thank present-you."),
        ],
        prevention="Delete unused nodes immediately when disconnecting them. Don't leave "
                   "'maybe I'll need this later' nodes floating — use source control to recover old versions.",
        related_docs=[
            "UE5 Docs: AnimGraph Best Practices",
            "UE5 Docs: Blueprint Graph Navigation",
        ]
    ),

    "INVALID_BSPACE": FixGuide(
        check_code="INVALID_BSPACE",
        check_name="Invalid BlendSpace",
        severity="WARNING",
        summary="A BlendSpace has 0 or 1 sample points — it cannot interpolate.",
        what_went_wrong=(
            "A BlendSpace (1D or 2D) referenced by this AnimBP has too few sample points. "
            "BlendSpaces need at least 2 sample points to interpolate between. With 0 or 1, "
            "the BlendSpace either produces no output or plays a static, non-blended animation."
        ),
        why_it_happened=(
            "This usually happens when:\n"
            "  - A BlendSpace was created but not fully configured\n"
            "  - Sample animations were removed but the BlendSpace wasn't updated\n"
            "  - The BlendSpace was set up as a placeholder and forgotten"
        ),
        time_saved="30 min - 1 hour (wrong movement blend debugging)",
        steps=[
            FixStep(1, "Find the BlendSpace asset",
                "In the Content Browser, locate the BlendSpace asset referenced by this AnimBP. "
                "Check the scan result for the asset path.",
                tip="BlendSpaces typically have names like 'BS_Locomotion' or 'BS_Strafe'."),
            FixStep(2, "Open the BlendSpace editor",
                "Double-click the BlendSpace to open its editor. You'll see a 2D grid "
                "(for BlendSpace) or a 1D line (for BlendSpace1D) with sample points."),
            FixStep(3, "Add sample animations",
                "Drag animation sequences from the Content Browser onto the BlendSpace grid.\n\n"
                "For a locomotion BlendSpace (2D), typical setup:\n"
                "  - (0, 0): Idle\n"
                "  - (0, 150): Walk Forward\n"
                "  - (0, 300): Run Forward\n"
                "  - (-150, 150): Walk Left\n"
                "  - (150, 150): Walk Right\n\n"
                "For a 1D BlendSpace (e.g., speed-based):\n"
                "  - 0: Idle\n"
                "  - 150: Walk\n"
                "  - 300: Run",
                tip="Each sample point must use an animation from the SAME skeleton as the AnimBP."),
            FixStep(4, "Set axis ranges",
                "In the BlendSpace settings, verify:\n"
                "  - Horizontal Axis: Name (e.g., 'Direction'), Min/Max range\n"
                "  - Vertical Axis: Name (e.g., 'Speed'), Min/Max range\n"
                "These ranges must match the values your AnimInstance sends."),
            FixStep(5, "Compile and test",
                "Save the BlendSpace. Open the AnimBP, compile (F7). Test in PIE and verify "
                "the blend transitions smoothly between animations.",
                tip="Use the BlendSpace preview in the editor — drag the green diamond around "
                    "the grid to preview the blend result in real-time."),
        ],
        prevention="Always add at least 3 sample points when creating a BlendSpace. "
                   "Use a naming convention (BS_) so empty BlendSpaces are easy to find.",
        related_docs=[
            "UE5 Docs: Blend Spaces",
            "UE5 Docs: Blend Space 1D",
            "UE5 Docs: Locomotion Blend Spaces",
        ]
    ),

    "MISSING_NOTIFY": FixGuide(
        check_code="MISSING_NOTIFY",
        check_name="Missing Notify",
        severity="INFO",
        summary="An AnimNotify references a function or event that no longer exists.",
        what_went_wrong=(
            "An animation sequence used by this AnimBP has an AnimNotify that points to a "
            "Blueprint event or C++ function that has been deleted or renamed. The notify "
            "fires during playback but has nothing to call — it either silently fails or "
            "can crash the editor."
        ),
        why_it_happened=(
            "This usually happens when:\n"
            "  - A Blueprint event was renamed or deleted but the notify wasn't updated\n"
            "  - C++ function signatures changed without updating notify references\n"
            "  - Animations were imported from another project with different event names"
        ),
        time_saved="1-3 hours (silent failures, potential editor crashes)",
        steps=[
            FixStep(1, "Find the animation with the broken notify",
                "Check which animation sequences are used by this AnimBP. Open each one "
                "and look at the Notifies track at the bottom of the timeline.",
                tip="Look for notifies with red/yellow warning icons or 'None' references."),
            FixStep(2, "Identify the broken notify",
                "In the animation timeline, notifies appear as markers on the Notifies track. "
                "Click each one and check its Details panel for the referenced event/function."),
            FixStep(3, "Fix or replace the notify",
                "Options:\n"
                "  - If the function was renamed: Update the notify to point to the new name\n"
                "  - If the function was deleted: Right-click the notify > Delete Notify\n"
                "  - If you need to recreate: Right-click the timeline > Add Notify > choose type",
                warning="Deleting a notify means the event won't fire. Make sure nothing depends on it "
                        "before removing (e.g., footstep sounds, VFX triggers, gameplay events)."),
            FixStep(4, "Verify all notifies in the AnimBP",
                "Check ALL animation sequences used by this AnimBP, not just the flagged one. "
                "Broken notifies tend to occur in batches.",
                tip="Use Window > Anim Notify Manager to see all notifies across all animations."),
            FixStep(5, "Compile and test event firing",
                "Compile the AnimBP. In PIE, verify that events fire correctly "
                "(footsteps make sounds, VFX spawn at the right time, etc.).",
                tip="Add temporary Print String nodes to your notify events to confirm they fire."),
        ],
        prevention="When renaming Blueprint events that notifies reference, use the Rename tool "
                   "(F2) which updates references automatically. Never just delete and recreate.",
        related_docs=[
            "UE5 Docs: Animation Notifies",
            "UE5 Docs: Anim Notify Events",
            "UE5 Docs: Custom Notifies in C++",
        ]
    ),

    "DUP_SLOT": FixGuide(
        check_code="DUP_SLOT",
        check_name="Duplicate Slot Name",
        severity="WARNING",
        summary="Multiple Slot nodes use the same name — montages will conflict.",
        what_went_wrong=(
            "Two or more AnimGraphNode_Slot nodes in your AnimGraph share the same slot name. "
            "When a montage plays, UE5 sends it to ALL slots with that name, causing the montage "
            "to play multiple times or produce unexpected blend results."
        ),
        why_it_happened=(
            "This usually happens when:\n"
            "  - A Slot node was copy-pasted without changing the name\n"
            "  - Multiple developers added slots independently\n"
            "  - The AnimGraph was restructured and old slots weren't cleaned up"
        ),
        time_saved="30 min - 1 hour (montage conflicts only appear under specific conditions)",
        steps=[
            FixStep(1, "Open the AnimGraph",
                "Open the flagged AnimBP and go to the AnimGraph tab."),
            FixStep(2, "Find all Slot nodes",
                "Press Ctrl+F and search for 'Slot'. All Slot nodes will be highlighted.",
                tip="Check the Details panel for each Slot node to see its SlotName property."),
            FixStep(3, "Rename or remove duplicates",
                "Each Slot node should have a UNIQUE name. Standard naming:\n"
                "  - 'DefaultSlot' — full body montages\n"
                "  - 'UpperBody' — upper body only (attacks while running)\n"
                "  - 'LowerBody' — lower body only\n"
                "  - 'Face' — facial animations\n\n"
                "Rename duplicate slots to unique names, or delete the extras if they're unused."),
            FixStep(4, "Update gameplay code",
                "If you renamed a slot, update any PlayMontage calls that reference it:\n\n"
                "  // C++\n"
                "  PlayAnimMontage(Montage, 1.0f, FName(\"UpperBody\"));\n\n"
                "  // Blueprint\n"
                "  Play Anim Montage > Slot Name: UpperBody",
                warning="Changing slot names will break any existing montage playback code "
                        "that references the old name."),
            FixStep(5, "Compile and test all montages",
                "Compile (F7). Test every montage in PIE to verify they play on the correct layer.",
                tip="Test edge cases: What happens when two montages play simultaneously? "
                    "Each should play on its own slot without interfering."),
        ],
        prevention="Establish a slot naming convention in your project documentation. "
                   "Keep a list of all slot names and their purposes.",
        related_docs=[
            "UE5 Docs: Animation Slots",
            "UE5 Docs: Animation Slot Groups",
        ]
    ),

    "UNUSED_VAR": FixGuide(
        check_code="UNUSED_VAR",
        check_name="Unused Variable",
        severity="INFO",
        summary="AnimInstance variables are declared but never read by the AnimGraph.",
        what_went_wrong=(
            "Your AnimInstance (the C++ or Blueprint class behind the AnimBP) has variables that "
            "are being set by gameplay code but never used by any AnimGraph node. These variables "
            "exist but do nothing — they add confusion during debugging because developers waste "
            "time investigating them."
        ),
        why_it_happened=(
            "This usually happens when:\n"
            "  - Variables were created for a feature that was later redesigned\n"
            "  - The AnimGraph was rebuilt but old variables weren't cleaned up\n"
            "  - Variables are set by code 'just in case' but never consumed"
        ),
        time_saved="5-10 min per debug session (reduces false leads)",
        steps=[
            FixStep(1, "Identify unused variables",
                "Open the AnimBP's Class Defaults or the parent AnimInstance Blueprint/C++ class. "
                "Review the variables listed.",
                tip="The scan result shows the approximate count of properties vs reads."),
            FixStep(2, "Check each variable",
                "For each variable, ask: Is this used in the AnimGraph? "
                "Right-click the variable > Find References to see if anything reads it.",
                tip="In C++, search for Get[VariableName] in the AnimGraph. "
                    "In Blueprint, check if any Get nodes reference it."),
            FixStep(3, "Remove confirmed unused variables",
                "For variables confirmed unused:\n"
                "  - In Blueprint: Right-click > Delete Variable\n"
                "  - In C++: Remove the UPROPERTY declaration\n\n"
                "Also remove any code that SETS these variables (in NativeUpdateAnimation, etc.).",
                warning="Before deleting, double-check that the variable isn't used in gameplay "
                        "Blueprint code outside the AnimGraph (e.g., for UI or AI decisions)."),
            FixStep(4, "Compile and verify",
                "Compile the AnimBP and any C++ code. Run the game to verify nothing breaks.",
                tip="If something breaks after removing a variable, undo with Ctrl+Z — "
                    "the variable was being used somewhere you didn't expect."),
        ],
        prevention="When removing a feature from the AnimGraph, also remove the variables "
                   "that drove it. Keep AnimInstance classes lean — every variable should have a clear consumer.",
        related_docs=[
            "UE5 Docs: Animation Instance",
            "UE5 Docs: AnimBP Class Variables",
        ]
    ),

    "DEPRECATED_NODE": FixGuide(
        check_code="DEPRECATED_NODE",
        check_name="Deprecated Node",
        severity="WARNING",
        summary="Your AnimGraph uses a node class marked as deprecated — it will break on engine upgrade.",
        what_went_wrong=(
            "One or more nodes in your AnimGraph use UE5 classes that are marked CLASS_Deprecated. "
            "These nodes still work in the current engine version but may be removed in the next "
            "major version without warning."
        ),
        why_it_happened=(
            "This usually happens when:\n"
            "  - The AnimBP was created in an older UE version and not updated\n"
            "  - Epic deprecated an old node type and introduced a replacement\n"
            "  - The AnimBP was migrated from UE4 to UE5"
        ),
        time_saved="1-4 hours (saved during next engine version migration)",
        steps=[
            FixStep(1, "Identify the deprecated node(s)",
                "Open the AnimBP. The compiler may show warnings about deprecated nodes. "
                "Also check the Compiler Results panel for deprecation messages.",
                tip="The AnimBP compiler often suggests the replacement node in the warning message."),
            FixStep(2, "Find the replacement node",
                "Right-click in the AnimGraph and search for the modern equivalent:\n\n"
                "Common replacements:\n"
                "  - 'Evaluate Sequence Player' -> 'Sequence Player' (simplified)\n"
                "  - Old 'Apply Additive' -> 'Apply Mesh Space Additive'\n"
                "  - Legacy 'Two Way Blend' -> 'Blend' node\n"
                "  - 'Copy Bone' -> 'Copy Bone' (new version with different settings)\n\n"
                "Check UE5 Migration Guide for your specific version.",
                tip="The UE5 release notes always list deprecated classes and their replacements."),
            FixStep(3, "Add the replacement node",
                "Right-click > Add the new node type. Configure it to match the settings "
                "of the deprecated node (copy pin connections, properties, etc.)."),
            FixStep(4, "Rewire connections",
                "Connect all input and output pins from the old node to the new node. "
                "Make sure the data flow is preserved.",
                warning="Some replacement nodes have different pin layouts. "
                        "You may need to adjust blend settings or add intermediate nodes."),
            FixStep(5, "Delete the old node",
                "Once the new node is fully wired and configured, delete the deprecated node."),
            FixStep(6, "Compile and test thoroughly",
                "Compile (F7). Test ALL animations that flow through this section of the graph. "
                "The replacement node should produce identical visual results.",
                tip="If the visual result is slightly different, check the new node's properties — "
                    "newer nodes often have additional options that need to be configured to match the legacy behavior."),
        ],
        prevention="When upgrading UE versions, always check the Migration Guide and run a full "
                   "project scan for deprecated classes before starting new feature work.",
        related_docs=[
            "UE5 Docs: Engine Version Migration",
            "UE5 Docs: Deprecated Classes",
            "UE5 Release Notes",
        ]
    ),

    # ── General Blueprint Checks (13-26) ──

    "BP_BROKEN_REF": FixGuide(
        check_code="BP_BROKEN_REF", check_name="Broken Asset Reference", severity="ERROR",
        summary="Blueprint references an asset path that no longer exists on disk.",
        what_went_wrong="An asset was moved, renamed, or deleted, but this Blueprint still holds a reference to its old path.",
        why_it_happened="Common after Content Browser reorganization, branch merges, or deleting unused assets without checking references.",
        time_saved="1-4 hours (runtime null crashes in packaged builds)",
        steps=[
            FixStep(1, "Open the Blueprint", "Double-click the flagged Blueprint in Content Browser."),
            FixStep(2, "Check for red nodes", "Look for nodes with red error indicators. These point to missing assets."),
            FixStep(3, "Use Reference Viewer", "Right-click the Blueprint in Content Browser > Reference Viewer to see all dependencies.",
                    tip="Broken refs show as grayed-out nodes in the Reference Viewer."),
            FixStep(4, "Reconnect or remove", "Either redirect the reference to the correct asset, or delete the node if it's no longer needed."),
            FixStep(5, "Compile and save", "Compile (F7) and save. Re-scan to verify the broken reference is resolved."),
        ],
        prevention="Use 'Fix Up Redirectors' after moving assets. Always check references before deleting.",
        related_docs=["UE5 Docs: Referencing Assets", "UE5 Docs: Redirectors"],
    ),
    "BP_COMPLEXITY": FixGuide(
        check_code="BP_COMPLEXITY", check_name="Excessive Complexity", severity="WARNING",
        summary="Blueprint has over 100 unique nodes — maintenance and performance risk.",
        what_went_wrong="The Blueprint has grown too large for efficient maintenance. Complex BPs are harder to debug and compile slower.",
        why_it_happened="Incremental feature additions without refactoring. Common in prototyping-heavy workflows.",
        time_saved="4-8 hours per sprint (spaghetti BP debugging)",
        steps=[
            FixStep(1, "Identify logical groups", "Look for clusters of nodes that perform a single task (movement, combat, UI, etc.)."),
            FixStep(2, "Collapse to functions", "Select a group of related nodes > right-click > Collapse to Function. Name it clearly."),
            FixStep(3, "Consider child Blueprints", "If the BP handles multiple unrelated systems, split into parent/child or component BPs."),
            FixStep(4, "Move heavy logic to C++", "For performance-critical sections (Tick, physics, AI), implement in C++ and call from BP.",
                    tip="Epic recommends keeping BPs under 100 nodes. C++ is 10-100x faster for heavy logic."),
        ],
        prevention="Refactor every sprint. Follow the 'one responsibility per Blueprint' principle.",
        related_docs=["UE5 Docs: Blueprint Best Practices", "UE5 Docs: Nativization"],
    ),
    "BP_EMPTY_GRAPH": FixGuide(
        check_code="BP_EMPTY_GRAPH", check_name="Empty Event Graph", severity="INFO",
        summary="Blueprint exists but contains no meaningful logic.",
        what_went_wrong="This Blueprint was likely created as a placeholder or prototype and never filled in.",
        why_it_happened="Common during prototyping — BPs get duplicated or created for testing and never cleaned up.",
        time_saved="10-15 min per debugging session (eliminating false leads)",
        steps=[
            FixStep(1, "Verify it's unused", "Right-click > Reference Viewer. Check if anything depends on this Blueprint."),
            FixStep(2, "Delete if unused", "If no references exist, delete the Blueprint to reduce project clutter."),
            FixStep(3, "Add logic if needed", "If this BP is supposed to have logic, open it and implement the intended behavior."),
        ],
        prevention="Delete prototype BPs immediately when done testing. Don't leave empty placeholders.",
        related_docs=["UE5 Docs: Content Browser Management"],
    ),
    "BP_TICK_HEAVY": FixGuide(
        check_code="BP_TICK_HEAVY", check_name="Tick Performance Risk", severity="WARNING",
        summary="Blueprint runs Event Tick with complex logic — FPS risk.",
        what_went_wrong="Event Tick runs every frame for every instance. Complex logic here multiplies cost by instance count.",
        why_it_happened="Logic was placed in Tick for convenience during prototyping and never optimized.",
        time_saved="2-8 hours (FPS profiling and optimization)",
        steps=[
            FixStep(1, "Open the Blueprint", "Double-click to open and find Event Tick in the Event Graph."),
            FixStep(2, "Evaluate necessity", "Does this logic truly need to run every frame? Most gameplay logic works at 5-10 Hz."),
            FixStep(3, "Use a timer", "Replace Tick with Set Timer by Event (0.1-0.5s interval covers most cases).",
                    tip="A 0.2s timer is 5x cheaper than Tick and covers most gameplay needs."),
            FixStep(4, "Move to C++", "If per-frame execution is truly needed, C++ Tick is 10-100x faster than Blueprint Tick."),
        ],
        prevention="Never use Event Tick in Blueprint as a first choice. Default to timers or event-driven logic.",
        related_docs=["UE5 Docs: Blueprint Performance", "UE5 Docs: Timers"],
    ),
    "BP_SELF_CAST": FixGuide(
        check_code="BP_SELF_CAST", check_name="Self-Cast Detected", severity="INFO",
        summary="Blueprint casts to its own class type — unnecessary overhead.",
        what_went_wrong="A Cast node is casting to the same class type as the Blueprint itself. This always succeeds.",
        why_it_happened="Common beginner pattern — casting to self from an event or interface call when a Self reference would work.",
        time_saved="5-10 min (code cleanup)",
        steps=[
            FixStep(1, "Find the Cast node", "Search for Cast nodes in the Event Graph (Ctrl+F > 'Cast')."),
            FixStep(2, "Check the target class", "If the Cast target is the same class as this Blueprint, it's unnecessary."),
            FixStep(3, "Replace with Self", "Delete the Cast node and use 'Get a reference to self' (Self node) instead."),
        ],
        prevention="Use Self references instead of casting to your own class. Casts are for accessing OTHER classes.",
        related_docs=["UE5 Docs: Casting in Blueprints"],
    ),
    "BP_DEPRECATED_FUNC": FixGuide(
        check_code="BP_DEPRECATED_FUNC", check_name="Deprecated API Usage", severity="WARNING",
        summary="Blueprint uses functions marked deprecated in UE5.",
        what_went_wrong="Some nodes call functions that Epic has deprecated. They work now but will break on engine upgrade.",
        why_it_happened="Blueprint was created on an older UE version, or nodes were copied from legacy projects.",
        time_saved="1-4 hours (migration debugging)",
        steps=[
            FixStep(1, "Find deprecated nodes", "Open the Blueprint and look for nodes with strikethrough text or yellow warnings."),
            FixStep(2, "Check the tooltip", "Hover over the deprecated node — the tooltip usually shows the replacement function."),
            FixStep(3, "Replace with modern equivalent", "Delete the deprecated node and use the recommended replacement.",
                    tip="Check UE5 Migration Guides for a full list of deprecated-to-replacement mappings."),
            FixStep(4, "Compile and test", "Compile and verify behavior is identical with the new nodes."),
        ],
        prevention="Check the UE5 Release Notes when upgrading. Run a full scan before starting new work on upgraded projects.",
        related_docs=["UE5 Docs: Engine Version Migration", "UE5 Release Notes"],
    ),
    "BP_CIRCULAR_DEP": FixGuide(
        check_code="BP_CIRCULAR_DEP", check_name="Circular Dependency", severity="WARNING",
        summary="Two Blueprints reference each other, creating a circular dependency.",
        what_went_wrong="Blueprint A references Blueprint B, and B references A. This causes unpredictable load order.",
        why_it_happened="Direct cross-references between systems (e.g., Player references Enemy and Enemy references Player).",
        time_saved="2-6 hours (untangling load order crashes)",
        steps=[
            FixStep(1, "Identify the cycle", "Use Reference Viewer on both BPs to see the circular reference chain."),
            FixStep(2, "Create an Interface", "Make a Blueprint Interface that defines the functions one BP needs from the other."),
            FixStep(3, "Implement the Interface", "Have one BP implement the Interface. The other BP calls Interface functions instead of casting directly."),
            FixStep(4, "Remove the direct reference", "Delete the Cast node that creates the circular dependency.",
                    tip="Interfaces break dependency chains because they don't require a hard reference to the implementing class."),
        ],
        prevention="Use Blueprint Interfaces for cross-system communication. Never have two BPs directly reference each other.",
        related_docs=["UE5 Docs: Blueprint Interfaces", "UE5 Docs: Dependency Management"],
    ),
    "BP_MASSIVE_ASSET": FixGuide(
        check_code="BP_MASSIVE_ASSET", check_name="Oversized Blueprint Asset", severity="WARNING",
        summary="Blueprint .uasset file is abnormally large (>5MB).",
        what_went_wrong="The Blueprint file is much larger than normal, which slows editor, version control, and cooking.",
        why_it_happened="Usually embedded data (large arrays, mesh data), excessive node graphs, or file corruption.",
        time_saved="Ongoing (every editor load, every VCS sync)",
        steps=[
            FixStep(1, "Check for embedded data", "Open the BP and look for large arrays, data tables, or mesh components with inline data."),
            FixStep(2, "Extract to separate assets", "Move large data (meshes, textures, data arrays) into separate .uasset files."),
            FixStep(3, "Check for corruption", "If size seems wrong, try duplicating the BP and deleting the original to get a clean copy."),
        ],
        prevention="Never embed large data directly in Blueprints. Use separate assets and soft references.",
        related_docs=["UE5 Docs: Asset Size Guidelines"],
    ),
    "BP_HARD_REF": FixGuide(
        check_code="BP_HARD_REF", check_name="Hard Reference Bloat", severity="WARNING",
        summary="Blueprint has excessive hard references loading unnecessary assets into memory.",
        what_went_wrong="Cast-to-Blueprint nodes force the target Blueprint AND all its dependencies into memory at load time.",
        why_it_happened="Using Cast nodes for cross-BP communication instead of Interfaces or Soft References.",
        time_saved="Significant memory savings in large projects",
        steps=[
            FixStep(1, "Open Reference Viewer", "Right-click the BP in Content Browser > Reference Viewer to see all hard references."),
            FixStep(2, "Replace Casts with Interfaces", "For gameplay logic, use Blueprint Interfaces instead of Cast nodes."),
            FixStep(3, "Use Soft References", "For asset loading, use Soft Object References and async loading instead of hard references.",
                    tip="Hard refs are the #1 Blueprint memory complaint on Epic forums."),
        ],
        prevention="Default to Interfaces and Soft References. Only use Cast when you truly need the concrete type.",
        related_docs=["UE5 Docs: Soft References", "UE5 Docs: Blueprint Interfaces"],
    ),
    "BP_EXPENSIVE_TICK": FixGuide(
        check_code="BP_EXPENSIVE_TICK", check_name="Expensive Operations in Tick", severity="WARNING",
        summary="Blueprint runs expensive queries (GetAllActorsOfClass, traces) inside Event Tick.",
        what_went_wrong="Expensive search operations run every frame for every instance, causing massive FPS drops.",
        why_it_happened="Quick prototyping that used Tick + GetAllActorsOfClass instead of proper event-driven architecture.",
        time_saved="2-8 hours (FPS profiling)",
        steps=[
            FixStep(1, "Find the expensive nodes", "Open Tick and look for GetAllActorsOfClass, LineTrace, SweepMulti nodes."),
            FixStep(2, "Cache results", "Move the query to BeginPlay or a Timer. Store results in a variable."),
            FixStep(3, "Use events instead", "Instead of polling every frame, use delegates/events to be notified of changes.",
                    tip="50 actors each calling GetAllActorsOfClass in Tick = 50x the cost per frame."),
        ],
        prevention="Never put GetAllActorsOfClass or SweepMulti in Event Tick. Use BeginPlay + cached references.",
        related_docs=["UE5 Docs: Blueprint Optimization", "UE5 Docs: Performance Guidelines"],
    ),
    "BP_DEBUG_NODES": FixGuide(
        check_code="BP_DEBUG_NODES", check_name="Debug Nodes in Production", severity="WARNING",
        summary="Blueprint contains PrintString or DrawDebug nodes that may leak into shipping builds.",
        what_went_wrong="Debug output nodes are still present. They cost performance and can leak debug info to players.",
        why_it_happened="Debug nodes added during development and never removed before shipping.",
        time_saved="30 min (cleanup before shipping)",
        steps=[
            FixStep(1, "Search for PrintString", "Press Ctrl+F in the Blueprint, search 'Print'. Select and delete all matches."),
            FixStep(2, "Search for DrawDebug", "Press Ctrl+F, search 'Draw Debug'. These are even more expensive than Print."),
            FixStep(3, "Use UE_LOG instead", "For logging that should persist, use C++ UE_LOG which is stripped from Shipping builds."),
            FixStep(4, "Verify Shipping build", "Package in Shipping config and check output log for any remaining debug text."),
        ],
        prevention="Remove all PrintString/DrawDebug nodes before merging to main branch.",
        related_docs=["UE5 Docs: Shipping Build Configuration", "UE5 Docs: Logging"],
    ),
    "BP_CONSTRUCT_HEAVY": FixGuide(
        check_code="BP_CONSTRUCT_HEAVY", check_name="Construction Script Misuse", severity="WARNING",
        summary="Construction Script contains heavy operations that run in the editor.",
        what_went_wrong="SpawnActor, GetAllActorsOfClass, or similar expensive operations run every time a property changes in the editor.",
        why_it_happened="Logic was placed in Construction Script instead of BeginPlay for editor-time visualization.",
        time_saved="Prevents editor freezes and crashes",
        steps=[
            FixStep(1, "Move to BeginPlay", "SpawnActor and heavy queries should happen in BeginPlay, not Construction Script."),
            FixStep(2, "Use editor-only flag", "If needed only in editor, wrap with 'Is Editor' branch."),
            FixStep(3, "Guard with a check", "Add a boolean to prevent re-execution: if already_initialized, return."),
        ],
        prevention="Construction Script should only set default values and simple visualizations. Never spawn actors.",
        related_docs=["UE5 Docs: Construction Script", "UE5 Docs: Actor Lifecycle"],
    ),
    "BP_FOREACH_PERF": FixGuide(
        check_code="BP_FOREACH_PERF", check_name="ForEach Loop Performance", severity="INFO",
        summary="ForEachLoop re-evaluates pure input nodes on every iteration.",
        what_went_wrong="A query function connected directly to ForEachLoop runs the query twice per loop iteration.",
        why_it_happened="Blueprint's ForEachLoop macro re-evaluates pure inputs every pass — a non-obvious performance trap.",
        time_saved="20-50% performance improvement on affected loops",
        steps=[
            FixStep(1, "Cache the array first", "Before the ForEachLoop, call the query function once and store result in a local variable."),
            FixStep(2, "Use ForLoop instead", "Get the array length, use a standard ForLoop with index, access array by index.",
                    tip="ForLoop doesn't re-evaluate inputs. It's always faster than ForEachLoop for array iteration."),
            FixStep(3, "Check if in Tick", "ForEachLoop in Tick is especially bad — consider caching the array on a timer."),
        ],
        prevention="Always cache query results in a variable before looping. Never connect a pure query directly to ForEachLoop.",
        related_docs=["UE5 Docs: Blueprint Loops", "UE5 Docs: Pure vs Impure Functions"],
    ),
    "BP_TIMELINE_HEAVY": FixGuide(
        check_code="BP_TIMELINE_HEAVY", check_name="Excessive Timeline Components", severity="INFO",
        summary="Multiple Timeline nodes create hidden tick overhead.",
        what_went_wrong="Each Timeline node creates a hidden UTimelineComponent that ticks every frame.",
        why_it_happened="Multiple Timelines added for separate animations/effects without considering the hidden cost.",
        time_saved="Performance improvement from reducing hidden tick registrations",
        steps=[
            FixStep(1, "Count your Timelines", "Open the BP and search for Timeline nodes. Count how many exist."),
            FixStep(2, "Merge where possible", "If multiple Timelines drive related animations, merge them into one with multiple tracks."),
            FixStep(3, "Use Lerp + Timer", "For simple A-to-B interpolation, a Timer + FMath::Lerp is much cheaper than a Timeline.",
                    tip="Each Timeline = one hidden component ticking every frame, even when inactive."),
        ],
        prevention="Use Timelines sparingly. Prefer Lerp + Timer for simple interpolations.",
        related_docs=["UE5 Docs: Timelines", "UE5 Docs: FInterpTo"],
    ),
}

# ─────────────────────────────────────────────────────────────────
#  HTML FIX GUIDE GENERATOR
# ─────────────────────────────────────────────────────────────────

class FixGuideReportGenerator:
    """Generates a beautiful step-by-step HTML fix guide from scan results."""

    @staticmethod
    def generate(scan_results: list, output_path: str) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total_issues = len(scan_results)

        # Group results by check code
        grouped = {}
        for r in scan_results:
            code = r.get("check_code", "")
            if not code:
                continue
            if code not in grouped:
                grouped[code] = []
            grouped[code].append(r)

        guide_sections = ""
        guide_toc = ""
        esc = html_module.escape

        for idx, (code, issues) in enumerate(grouped.items(), 1):
            guide = FIX_GUIDES.get(code)
            if not guide:
                continue

            sev_color = Theme.severity_color(guide.severity)
            affected = html_module.escape(", ".join(set(i.get("animblueprint", "Unknown") for i in issues)))

            # TOC entry
            guide_toc += f'<li><a href="#guide-{esc(code)}">{esc(guide.check_name)}</a> <span class="toc-count">({len(issues)} issues)</span></li>\n'

            # Steps HTML
            steps_html = ""
            for step in guide.steps:
                tip_html = ""
                if step.tip:
                    tip_html = f'<div class="tip-box"><strong>TIP:</strong> {esc(step.tip)}</div>'
                warn_html = ""
                if step.warning:
                    warn_html = f'<div class="warn-box"><strong>WARNING:</strong> {esc(step.warning)}</div>'
                details_html = f'<p class="step-details">{esc(step.details)}</p>' if step.details else ""

                steps_html += f"""
                <div class="step">
                    <div class="step-number">{step.number}</div>
                    <div class="step-content">
                        <h4>{esc(step.title)}</h4>
                        <p>{esc(step.instruction)}</p>
                        {details_html}
                        {tip_html}
                        {warn_html}
                    </div>
                </div>"""

            # Prevention and docs
            docs_html = "".join(f'<li>{esc(doc)}</li>' for doc in guide.related_docs)

            guide_sections += f"""
            <div class="guide-card" id="guide-{esc(code)}">
                <div class="guide-header">
                    <span class="severity-badge" style="background:{sev_color}20; color:{sev_color}">{guide.severity}</span>
                    <h2>{esc(guide.check_name)}</h2>
                    <span class="issue-count">{len(issues)} issue(s)</span>
                </div>

                <div class="guide-summary">{esc(guide.summary)}</div>

                <div class="affected-abps">
                    <strong>Affected AnimBPs:</strong> {affected}
                </div>

                <div class="explanation-section">
                    <div class="explanation-card wrong">
                        <h3>What Went Wrong</h3>
                        <p>{esc(guide.what_went_wrong)}</p>
                    </div>
                    <div class="explanation-card why">
                        <h3>Why It Happened</h3>
                        <pre>{esc(guide.why_it_happened)}</pre>
                    </div>
                    <div class="time-saved">
                        <strong>Time this saves you:</strong> {esc(guide.time_saved)}
                    </div>
                </div>

                <h3 class="steps-title">Step-by-Step Fix</h3>
                <div class="steps-container">
                    {steps_html}
                </div>

                <div class="prevention-section">
                    <h3>Prevention</h3>
                    <p>{esc(guide.prevention)}</p>
                </div>

                <div class="docs-section">
                    <h3>Related Documentation</h3>
                    <ul>{docs_html}</ul>
                </div>
            </div>"""

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AnimBP Fix Guide — {now}</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        background: {Theme.BG_DEEP};
        color: {Theme.TEXT};
        font-family: 'Segoe UI', system-ui, sans-serif;
        line-height: 1.7;
        padding: 40px;
        max-width: 900px;
        margin: 0 auto;
    }}
    .header {{
        text-align: center;
        margin-bottom: 40px;
        padding-bottom: 30px;
        border-bottom: 2px solid {Theme.BORDER};
    }}
    .header h1 {{
        font-size: 2.5em;
        background: linear-gradient(135deg, {Theme.ACCENT}, {Theme.MAGENTA});
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }}
    .header .subtitle {{ color: {Theme.TEXT_DIM}; margin-top: 8px; }}
    .header .meta {{ color: {Theme.TEXT_MUTED}; font-size: 0.9em; margin-top: 12px; }}

    .toc {{
        background: {Theme.BG_CARD};
        border-radius: 12px;
        padding: 24px;
        margin-bottom: 40px;
        border: 1px solid {Theme.BORDER};
    }}
    .toc h2 {{ color: {Theme.ACCENT}; margin-bottom: 12px; font-size: 1.2em; }}
    .toc ul {{ list-style: none; }}
    .toc li {{ padding: 6px 0; }}
    .toc a {{ color: {Theme.ACCENT}; text-decoration: none; font-weight: 600; }}
    .toc a:hover {{ text-decoration: underline; }}
    .toc-count {{ color: {Theme.TEXT_MUTED}; font-size: 0.85em; }}

    .guide-card {{
        background: {Theme.BG_CARD};
        border-radius: 16px;
        padding: 32px;
        margin-bottom: 32px;
        border: 1px solid {Theme.BORDER};
    }}
    .guide-header {{
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 16px;
    }}
    .guide-header h2 {{ font-size: 1.5em; flex-grow: 1; }}
    .severity-badge {{
        padding: 4px 12px;
        border-radius: 6px;
        font-size: 0.8em;
        font-weight: 700;
    }}
    .issue-count {{ color: {Theme.TEXT_MUTED}; font-size: 0.9em; }}
    .guide-summary {{
        font-size: 1.1em;
        color: {Theme.TEXT_DIM};
        margin-bottom: 16px;
        padding-bottom: 16px;
        border-bottom: 1px solid {Theme.BORDER};
    }}
    .affected-abps {{
        background: {Theme.BG_SURFACE};
        padding: 12px 16px;
        border-radius: 8px;
        margin-bottom: 20px;
        font-size: 0.9em;
    }}
    .affected-abps strong {{ color: {Theme.ACCENT}; }}

    .explanation-section {{ margin-bottom: 24px; }}
    .explanation-card {{
        background: {Theme.BG_SURFACE};
        padding: 16px 20px;
        border-radius: 10px;
        margin-bottom: 12px;
        border-left: 3px solid {Theme.BORDER};
    }}
    .explanation-card.wrong {{ border-left-color: {Theme.ERROR}; }}
    .explanation-card.why {{ border-left-color: {Theme.WARNING}; }}
    .explanation-card h3 {{ color: {Theme.TEXT}; font-size: 1em; margin-bottom: 8px; }}
    .explanation-card p, .explanation-card pre {{
        color: {Theme.TEXT_DIM};
        font-size: 0.9em;
        white-space: pre-wrap;
        font-family: inherit;
    }}
    .time-saved {{
        background: {Theme.ACCENT}10;
        border: 1px solid {Theme.ACCENT}30;
        padding: 10px 16px;
        border-radius: 8px;
        color: {Theme.ACCENT};
        font-size: 0.9em;
    }}

    .steps-title {{
        color: {Theme.ACCENT};
        font-size: 1.2em;
        margin-bottom: 16px;
    }}
    .steps-container {{ margin-bottom: 24px; }}
    .step {{
        display: flex;
        gap: 16px;
        margin-bottom: 20px;
        padding: 16px;
        background: {Theme.BG_STEP};
        border-radius: 10px;
        border: 1px solid {Theme.BORDER};
    }}
    .step-number {{
        min-width: 40px;
        height: 40px;
        background: {Theme.ACCENT};
        color: {Theme.BG_DEEP};
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 800;
        font-size: 1.1em;
        flex-shrink: 0;
    }}
    .step-content {{ flex-grow: 1; }}
    .step-content h4 {{ color: {Theme.TEXT}; margin-bottom: 6px; font-size: 1.05em; }}
    .step-content p {{ color: {Theme.TEXT_DIM}; font-size: 0.9em; margin-bottom: 6px; }}
    .step-details {{ color: {Theme.TEXT_MUTED}; font-size: 0.85em; font-style: italic; }}

    .tip-box {{
        background: {Theme.TIP_BG};
        border: 1px solid {Theme.TIP_BORDER};
        border-radius: 6px;
        padding: 10px 14px;
        margin-top: 8px;
        font-size: 0.85em;
        color: {Theme.SUCCESS};
    }}
    .warn-box {{
        background: {Theme.WARN_BG};
        border: 1px solid {Theme.WARN_BORDER};
        border-radius: 6px;
        padding: 10px 14px;
        margin-top: 8px;
        font-size: 0.85em;
        color: {Theme.WARNING};
    }}

    .prevention-section, .docs-section {{
        margin-top: 20px;
        padding-top: 16px;
        border-top: 1px solid {Theme.BORDER};
    }}
    .prevention-section h3, .docs-section h3 {{
        color: {Theme.ACCENT};
        font-size: 1em;
        margin-bottom: 8px;
    }}
    .prevention-section p {{ color: {Theme.TEXT_DIM}; font-size: 0.9em; }}
    .docs-section ul {{ list-style: none; }}
    .docs-section li {{
        color: {Theme.TEXT_DIM};
        font-size: 0.85em;
        padding: 3px 0;
    }}
    .docs-section li::before {{ content: "-> "; color: {Theme.ACCENT}; }}

    .footer {{
        text-align: center;
        margin-top: 50px;
        padding-top: 20px;
        border-top: 1px solid {Theme.BORDER};
        color: {Theme.TEXT_MUTED};
    }}

    @media print {{
        body {{ background: #fff; color: #222; max-width: 100%; }}
        .guide-card {{ border-color: #ddd; break-inside: avoid; }}
        .step {{ background: #f8f8f8; }}
        .tip-box {{ background: #e8f5e9; border-color: #66bb6a; color: #2e7d32; }}
        .warn-box {{ background: #fff3e0; border-color: #ffa726; color: #e65100; }}
    }}
</style>
</head>
<body>
    <div class="header">
        <h1>AnimBP Fix Guide</h1>
        <div class="subtitle">Step-by-Step Repair Instructions</div>
        <div class="meta">
            Generated: {now} | {total_issues} issues | {len(grouped)} check types | BP Doctor
        </div>
    </div>

    <div class="toc">
        <h2>Issues Found</h2>
        <ul>
            {guide_toc}
        </ul>
    </div>

    {guide_sections}

    <div class="footer">
        <p>AnimBP Fix Guide v1.0 — BP Doctor</p>
        <p>Generated by AnimBP Doctor | Every step verified against UE5 documentation</p>
    </div>
</body>
</html>"""

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        return output_path

# ─────────────────────────────────────────────────────────────────
#  GUI APPLICATION — Fix Guide Viewer
# ─────────────────────────────────────────────────────────────────

class FixGuideApp:
    """Standalone GUI for viewing and exporting fix guides."""

    def __init__(self):
        # Enable DPI awareness for crisp rendering on high-DPI displays
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        self.root = tk.Tk()
        self.root.title("AnimBP Fix Guide v1.0 — BP Doctor")
        self.root.geometry("1100x800")
        self.root.minsize(800, 600)
        self.root.configure(bg=Theme.BG_DEEP)

        self.scan_data = None
        self._issue_map = {}  # tree item iid -> scan_data index
        self._setup_styles()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=Theme.BG_DEEP, foreground=Theme.TEXT,
                        font=("Segoe UI", 10))
        style.configure("Treeview", background=Theme.BG_CARD, foreground=Theme.TEXT,
                        fieldbackground=Theme.BG_CARD, borderwidth=0,
                        font=("Segoe UI", 10), rowheight=36)
        style.configure("Treeview.Heading", background=Theme.BG_SURFACE,
                        foreground=Theme.TEXT_DIM, font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", Theme.BG_HOVER)],
                  foreground=[("selected", Theme.ACCENT)])

    def _build_ui(self):
        # Top bar
        topbar = tk.Frame(self.root, bg=Theme.BG_SURFACE, height=60)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        tk.Label(topbar, text="AnimBP Fix Guide", font=("Segoe UI", 16, "bold"),
                fg=Theme.ACCENT, bg=Theme.BG_SURFACE).pack(side="left", padx=20)

        tk.Button(topbar, text="  Export HTML Guide  ", font=("Segoe UI", 10, "bold"),
                 fg=Theme.BG_DEEP, bg=Theme.ACCENT, bd=0, padx=16, pady=6,
                 cursor="hand2", command=self._export_guide).pack(side="right", padx=20, pady=12)

        tk.Button(topbar, text="  Load Scan Results (JSON)  ", font=("Segoe UI", 10),
                 fg=Theme.TEXT, bg=Theme.BG_CARD, bd=0, padx=16, pady=6,
                 cursor="hand2", command=self._load_scan).pack(side="right", padx=4, pady=12)

        # Main content — split pane
        paned = tk.PanedWindow(self.root, orient="horizontal", bg=Theme.BG_DEEP,
                              sashwidth=4, sashrelief="flat")
        paned.pack(fill="both", expand=True)

        # Left: issue list
        left = tk.Frame(paned, bg=Theme.BG_SURFACE, width=350)
        paned.add(left, minsize=300)

        tk.Label(left, text="ISSUES", font=("Segoe UI", 9, "bold"),
                fg=Theme.TEXT_MUTED, bg=Theme.BG_SURFACE).pack(anchor="w", padx=16, pady=(12, 6))

        self.issue_tree = ttk.Treeview(left, columns=("sev", "check", "abp"), show="headings")
        self.issue_tree.heading("sev", text="Sev", anchor="w")
        self.issue_tree.heading("check", text="Check", anchor="w")
        self.issue_tree.heading("abp", text="AnimBP", anchor="w")
        self.issue_tree.column("sev", width=60, minwidth=50, stretch=False)
        self.issue_tree.column("check", width=140, minwidth=100)
        self.issue_tree.column("abp", width=120, minwidth=80)

        self.issue_tree.tag_configure("ERROR", foreground=Theme.ERROR)
        self.issue_tree.tag_configure("WARNING", foreground=Theme.WARNING)
        self.issue_tree.tag_configure("INFO", foreground=Theme.INFO)

        scroll = ttk.Scrollbar(left, orient="vertical", command=self.issue_tree.yview)
        self.issue_tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.issue_tree.pack(fill="both", expand=True, padx=(8, 0))

        self.issue_tree.bind("<<TreeviewSelect>>", self._on_issue_select)

        # Right: fix guide detail
        right = tk.Frame(paned, bg=Theme.BG_DEEP)
        paned.add(right, minsize=400)

        self.detail_canvas = tk.Canvas(right, bg=Theme.BG_DEEP, highlightthickness=0)
        detail_scroll = ttk.Scrollbar(right, orient="vertical", command=self.detail_canvas.yview)
        self.detail_frame = tk.Frame(self.detail_canvas, bg=Theme.BG_DEEP)

        self.detail_frame.bind("<Configure>",
            lambda e: self.root.after_idle(
                lambda: self.detail_canvas.configure(
                    scrollregion=self.detail_canvas.bbox("all") or (0, 0, 0, 0))))
        self._detail_window = self.detail_canvas.create_window((0, 0), window=self.detail_frame, anchor="nw")
        self.detail_canvas.configure(yscrollcommand=detail_scroll.set)

        # Scoped mousewheel — only scroll when mouse is over the canvas
        def _on_mousewheel(event):
            self.detail_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        self.detail_canvas.bind("<Enter>",
            lambda e: self.detail_canvas.bind_all("<MouseWheel>", _on_mousewheel))
        self.detail_canvas.bind("<Leave>",
            lambda e: self.detail_canvas.unbind_all("<MouseWheel>"))

        # Track canvas width so detail_frame fills it
        def _on_canvas_resize(event):
            self.detail_canvas.itemconfig(self._detail_window, width=event.width)
        self.detail_canvas.bind("<Configure>", _on_canvas_resize)

        detail_scroll.pack(side="right", fill="y")
        self.detail_canvas.pack(side="left", fill="both", expand=True)

        # Show empty state
        self._show_empty_detail()

    def _show_empty_detail(self):
        for w in self.detail_frame.winfo_children():
            w.destroy()

        pad = tk.Frame(self.detail_frame, bg=Theme.BG_DEEP, padx=32, pady=60)
        pad.pack(fill="both", expand=True)

        tk.Label(pad, text="Select an issue to see the fix guide",
                font=("Segoe UI", 16, "bold"), fg=Theme.TEXT_DIM,
                bg=Theme.BG_DEEP).pack()
        tk.Label(pad, text="Load a JSON scan result from AnimBP Doctor,\n"
                "then click any issue to see step-by-step repair instructions.",
                font=("Segoe UI", 11), fg=Theme.TEXT_MUTED,
                bg=Theme.BG_DEEP, justify="center").pack(pady=(12, 0))

    def _load_scan(self):
        filepath = filedialog.askopenfilename(
            title="Load AnimBP Doctor Scan Results",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not filepath:
            return

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.scan_data = data.get("issues", [])
            self._populate_tree()
        except Exception as e:
            messagebox.showerror("Load Error", f"Failed to load scan results:\n{e}")

    def _populate_tree(self):
        self.issue_tree.delete(*self.issue_tree.get_children())
        self._issue_map.clear()
        self._show_empty_detail()
        if not self.scan_data:
            return

        for idx, issue in enumerate(self.scan_data):
            sev = issue.get("severity", "INFO")
            code = issue.get("check_code", "")
            guide = FIX_GUIDES.get(code)
            name = guide.check_name if guide else code
            abp = issue.get("animblueprint", "")
            iid = self.issue_tree.insert("", "end", values=(sev, name, abp), tags=(sev,))
            self._issue_map[iid] = idx

    def _on_issue_select(self, event):
        sel = self.issue_tree.selection()
        if not sel or not self.scan_data:
            return

        idx = self._issue_map.get(sel[0])
        if idx is None or idx >= len(self.scan_data):
            return

        issue = self.scan_data[idx]
        code = issue.get("check_code", "")
        guide = FIX_GUIDES.get(code)
        if not guide:
            return

        self._show_guide_detail(guide, issue)

    def _show_guide_detail(self, guide: FixGuide, issue: dict):
        for w in self.detail_frame.winfo_children():
            w.destroy()
        self.detail_canvas.yview_moveto(0)  # Reset scroll to top

        pad = tk.Frame(self.detail_frame, bg=Theme.BG_DEEP, padx=28, pady=20)
        pad.pack(fill="both", expand=True)

        sev_color = Theme.severity_color(guide.severity)

        # Header
        tk.Label(pad, text=guide.severity, font=("Segoe UI", 9, "bold"),
                fg=sev_color, bg=Theme.BG_DEEP).pack(anchor="w")
        tk.Label(pad, text=guide.check_name, font=("Segoe UI", 20, "bold"),
                fg=Theme.TEXT, bg=Theme.BG_DEEP).pack(anchor="w", pady=(2, 4))
        tk.Label(pad, text=guide.summary, font=("Segoe UI", 11),
                fg=Theme.TEXT_DIM, bg=Theme.BG_DEEP, wraplength=550,
                justify="left").pack(anchor="w", pady=(0, 16))

        # Affected AnimBP
        abp_frame = tk.Frame(pad, bg=Theme.BG_SURFACE, padx=14, pady=10)
        abp_frame.pack(fill="x", pady=(0, 12))
        tk.Label(abp_frame, text=f"Affected: {issue.get('animblueprint', 'Unknown')}",
                font=("Segoe UI", 10, "bold"), fg=Theme.ACCENT,
                bg=Theme.BG_SURFACE).pack(anchor="w")
        hint = issue.get("node_hint", "")
        if hint:
            tk.Label(abp_frame, text=hint, font=("Consolas", 9),
                    fg=Theme.TEXT_DIM, bg=Theme.BG_SURFACE).pack(anchor="w")

        # What went wrong
        wrong_frame = tk.Frame(pad, bg=Theme.BG_CARD, padx=16, pady=12)
        wrong_frame.pack(fill="x", pady=(0, 8))
        tk.Label(wrong_frame, text="WHAT WENT WRONG", font=("Segoe UI", 8, "bold"),
                fg=Theme.ERROR, bg=Theme.BG_CARD).pack(anchor="w")
        tk.Label(wrong_frame, text=guide.what_went_wrong, font=("Segoe UI", 9),
                fg=Theme.TEXT_DIM, bg=Theme.BG_CARD, wraplength=520,
                justify="left").pack(anchor="w", pady=(4, 0))

        # Why it happened
        why_frame = tk.Frame(pad, bg=Theme.BG_CARD, padx=16, pady=12)
        why_frame.pack(fill="x", pady=(0, 8))
        tk.Label(why_frame, text="WHY IT HAPPENED", font=("Segoe UI", 8, "bold"),
                fg=Theme.WARNING, bg=Theme.BG_CARD).pack(anchor="w")
        tk.Label(why_frame, text=guide.why_it_happened, font=("Segoe UI", 9),
                fg=Theme.TEXT_DIM, bg=Theme.BG_CARD, wraplength=520,
                justify="left").pack(anchor="w", pady=(4, 0))

        # Time saved
        time_frame = tk.Frame(pad, bg=Theme.BG_SURFACE, padx=14, pady=8)
        time_frame.pack(fill="x", pady=(0, 16))
        tk.Label(time_frame, text=f"Time this saves you: {guide.time_saved}",
                font=("Segoe UI", 10, "bold"), fg=Theme.ACCENT,
                bg=Theme.BG_SURFACE).pack(anchor="w")

        # Steps
        tk.Label(pad, text="STEP-BY-STEP FIX", font=("Segoe UI", 12, "bold"),
                fg=Theme.ACCENT, bg=Theme.BG_DEEP).pack(anchor="w", pady=(0, 12))

        for step in guide.steps:
            step_frame = tk.Frame(pad, bg=Theme.BG_CARD, padx=16, pady=12)
            step_frame.pack(fill="x", pady=(0, 6))

            header_row = tk.Frame(step_frame, bg=Theme.BG_CARD)
            header_row.pack(fill="x")

            num_label = tk.Label(header_row, text=str(step.number),
                               font=("Segoe UI", 12, "bold"), fg=Theme.BG_DEEP,
                               bg=Theme.ACCENT, width=3, height=1)
            num_label.pack(side="left", padx=(0, 10))
            tk.Label(header_row, text=step.title, font=("Segoe UI", 11, "bold"),
                    fg=Theme.TEXT, bg=Theme.BG_CARD).pack(side="left")

            tk.Label(step_frame, text=step.instruction, font=("Segoe UI", 9),
                    fg=Theme.TEXT_DIM, bg=Theme.BG_CARD, wraplength=500,
                    justify="left").pack(anchor="w", pady=(6, 0))

            if step.details:
                tk.Label(step_frame, text=step.details, font=("Segoe UI", 9),
                        fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD, wraplength=500,
                        justify="left").pack(anchor="w", pady=(4, 0))

            if step.tip:
                tip_f = tk.Frame(step_frame, bg="#1a2a1a", padx=10, pady=6)
                tip_f.pack(fill="x", pady=(6, 0))
                tk.Label(tip_f, text=f"TIP: {step.tip}", font=("Segoe UI", 8),
                        fg=Theme.SUCCESS, bg="#1a2a1a", wraplength=480,
                        justify="left").pack(anchor="w")

            if step.warning:
                warn_f = tk.Frame(step_frame, bg="#2a2a1a", padx=10, pady=6)
                warn_f.pack(fill="x", pady=(6, 0))
                tk.Label(warn_f, text=f"WARNING: {step.warning}", font=("Segoe UI", 8),
                        fg=Theme.WARNING, bg="#2a2a1a", wraplength=480,
                        justify="left").pack(anchor="w")

        # Prevention
        prev_frame = tk.Frame(pad, bg=Theme.BG_CARD, padx=16, pady=12)
        prev_frame.pack(fill="x", pady=(12, 8))
        tk.Label(prev_frame, text="PREVENTION", font=("Segoe UI", 8, "bold"),
                fg=Theme.SUCCESS, bg=Theme.BG_CARD).pack(anchor="w")
        tk.Label(prev_frame, text=guide.prevention, font=("Segoe UI", 9),
                fg=Theme.TEXT_DIM, bg=Theme.BG_CARD, wraplength=520,
                justify="left").pack(anchor="w", pady=(4, 0))

        # Related docs
        docs_frame = tk.Frame(pad, bg=Theme.BG_CARD, padx=16, pady=12)
        docs_frame.pack(fill="x", pady=(0, 20))
        tk.Label(docs_frame, text="RELATED DOCUMENTATION", font=("Segoe UI", 8, "bold"),
                fg=Theme.ACCENT, bg=Theme.BG_CARD).pack(anchor="w")
        for doc in guide.related_docs:
            tk.Label(docs_frame, text=f"  -> {doc}", font=("Segoe UI", 9),
                    fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD).pack(anchor="w")

    def _export_guide(self):
        if not self.scan_data:
            messagebox.showwarning("No Data", "Load scan results first.")
            return

        default_name = f"AnimBP_Fix_Guide_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        filepath = filedialog.asksaveasfilename(
            title="Save Fix Guide",
            defaultextension=".html",
            initialfile=default_name,
            filetypes=[("HTML files", "*.html")])

        if filepath:
            try:
                FixGuideReportGenerator.generate(self.scan_data, filepath)
                if messagebox.askyesno("Saved", f"Fix guide saved!\n\nOpen in browser?"):
                    webbrowser.open(Path(filepath).as_uri())
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export:\n{e}")

    def _on_close(self):
        self.detail_canvas.unbind_all("<MouseWheel>")
        self.root.destroy()

    def run(self):
        self.root.mainloop()

# ─────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = FixGuideApp()
    app.run()
