#!/usr/bin/env python3
# ══════════════════════════════════════════════════════════════════
#  BP Doctor v2.5 — BP Doctor (formerly AnimBP Doctor)
#  Standalone Blueprint Diagnostic Tool for UE5
#  Animation Blueprints + General Blueprints | Single file, zero dependencies
# ══════════════════════════════════════════════════════════════════

APP_VERSION = "2.5.0"
DEMO_MODE = False  # Set True for free demo build (scan only, no auto-fix)
DEMO_MAX_SCANS = 1  # One free scan, then locked

# ── CLI-safe imports (no tkinter yet — imported lazily for headless mode) ──
import os
import sys
import json
import struct
import sqlite3
import threading
import time
import argparse
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple, Callable
from enum import Enum
import re
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
import multiprocessing
import shutil
import textwrap

# ── GUI imports (deferred — not needed in CLI mode) ──
# These are loaded at module scope for backward compatibility with
# test_v2.py and direct imports, but the CLI entry path can skip GUI.
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    _HAS_TK = True
except ImportError:
    _HAS_TK = False

import webbrowser
import html as html_module
import platform as _platform
import hashlib

# ─────────────────────────────────────────────────────────────────
#  DEMO GATE — Scan limit for free demo builds
# ─────────────────────────────────────────────────────────────────

class DemoGate:
    """Multi-location encrypted scan counter tied to machine fingerprint.
    Stores in 3 independent locations — ALL must be deleted to reset.
    Encrypted with machine-specific key so editing/copying = garbage."""

    def __init__(self):
        _fp = (_platform.node() + os.path.expanduser("~")).encode("utf-8", errors="replace")
        self._key = hashlib.sha256(_fp).digest()[:16]
        # Storage location 1: LOCALAPPDATA (semi-hidden)
        base1 = os.environ.get("LOCALAPPDATA", str(Path.home()))
        self._path1 = Path(base1) / "BPDoctor" / ".usage"
        # Storage location 2: APPDATA/Roaming (separate from local)
        base2 = os.environ.get("APPDATA", str(Path.home()))
        self._path2 = Path(base2) / "BPDoctor" / ".cache"
        # Storage location 3: user home hidden folder
        self._path3 = Path.home() / ".bft" / ".state"

    def _xor(self, data: bytes) -> bytes:
        k = self._key * (len(data) // 16 + 1)
        return bytes(a ^ b for a, b in zip(data, k[:len(data)]))

    def _read_one(self, path: Path) -> int:
        try:
            if path.exists():
                raw = path.read_bytes()
                decrypted = self._xor(raw)
                data = json.loads(decrypted.decode("utf-8"))
                return data.get("s", 0)
        except Exception:
            pass
        return 0

    def _write_one(self, path: Path, count: int):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = json.dumps({"s": count}).encode("utf-8")
            path.write_bytes(self._xor(raw))
        except Exception:
            pass

    def _get_count(self) -> int:
        """Return the HIGHEST count across all storage locations.
        If any location says 'used', it's used — deleting one doesn't help."""
        return max(
            self._read_one(self._path1),
            self._read_one(self._path2),
            self._read_one(self._path3),
        )

    def _write_reg(self, count: int):
        """Also store in Windows registry as a 4th location."""
        try:
            import winreg
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\BPDoctor\BPD")
            # Store as encrypted hex string
            raw = json.dumps({"s": count}).encode("utf-8")
            winreg.SetValueEx(key, "c", 0, winreg.REG_SZ,
                              self._xor(raw).hex())
            winreg.CloseKey(key)
        except Exception:
            pass

    def _read_reg(self) -> int:
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\BPDoctor\BPD")
            val, _ = winreg.QueryValueEx(key, "c")
            winreg.CloseKey(key)
            raw = bytes.fromhex(val)
            decrypted = self._xor(raw)
            data = json.loads(decrypted.decode("utf-8"))
            return data.get("s", 0)
        except Exception:
            return 0

    def can_scan(self) -> bool:
        if not DEMO_MODE:
            return True
        count = max(self._get_count(), self._read_reg())
        return count < DEMO_MAX_SCANS

    def remaining(self) -> int:
        if not DEMO_MODE:
            return 999
        count = max(self._get_count(), self._read_reg())
        return max(0, DEMO_MAX_SCANS - count)

    def record_scan(self):
        if not DEMO_MODE:
            return
        count = max(self._get_count(), self._read_reg()) + 1
        # Write to ALL locations — attacker must find and clear every one
        self._write_one(self._path1, count)
        self._write_one(self._path2, count)
        self._write_one(self._path3, count)
        self._write_reg(count)

_demo_gate = DemoGate()


# ─────────────────────────────────────────────────────────────────
#  THEME — Doctor Dark
# ─────────────────────────────────────────────────────────────────

class Theme:
    BG_DEEP      = "#0a0e1a"
    BG_SURFACE   = "#111827"
    BG_CARD      = "#1a2035"
    BG_HOVER     = "#1e2a45"
    BG_INPUT     = "#0f1629"
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
    GRADE_A      = "#00e676"
    GRADE_B      = "#66bb6a"
    GRADE_C      = "#ffab00"
    GRADE_D      = "#ff9100"
    GRADE_F      = "#ff1744"

    @staticmethod
    def severity_color(sev):
        return {
            "ERROR": Theme.ERROR,
            "WARNING": Theme.WARNING,
            "INFO": Theme.INFO,
        }.get(sev, Theme.TEXT_DIM)

    @staticmethod
    def grade_color(grade):
        if grade.startswith("A"): return Theme.GRADE_A
        if grade == "B":          return Theme.GRADE_B
        if grade == "C":          return Theme.GRADE_C
        if grade == "D":          return Theme.GRADE_D
        return Theme.GRADE_F

# ─────────────────────────────────────────────────────────────────
#  COLOR SCHEMES — Atelier-style preset themes
# ─────────────────────────────────────────────────────────────────

COLOR_SCHEMES = {
    "Doctor Dark": {
        "BG_DEEP": "#0a0e1a", "BG_SURFACE": "#111827", "BG_CARD": "#1a2035",
        "BG_HOVER": "#1e2a45", "BG_INPUT": "#0f1629",
        "ACCENT": "#00d4ff", "ACCENT_DIM": "#0088aa", "MAGENTA": "#e040fb",
        "SUCCESS": "#00e676", "WARNING": "#ffab00", "ERROR": "#ff1744",
        "INFO": "#448aff", "TEXT": "#e8eaed", "TEXT_DIM": "#9aa0a6",
        "TEXT_MUTED": "#5f6368", "BORDER": "#2a3150",
        "GRADE_A": "#00e676", "GRADE_B": "#66bb6a", "GRADE_C": "#ffab00",
        "GRADE_D": "#ff9100", "GRADE_F": "#ff1744",
    },
    "Ember": {
        "BG_DEEP": "#1a1210", "BG_SURFACE": "#241c18", "BG_CARD": "#2e2420",
        "BG_HOVER": "#3a2e28", "BG_INPUT": "#1e1614",
        "ACCENT": "#ff8a50", "ACCENT_DIM": "#c75b30", "MAGENTA": "#ff6090",
        "SUCCESS": "#69f0ae", "WARNING": "#ffd740", "ERROR": "#ff5252",
        "INFO": "#82b1ff", "TEXT": "#efebe9", "TEXT_DIM": "#a1887f",
        "TEXT_MUTED": "#6d4c41", "BORDER": "#4e342e",
        "GRADE_A": "#69f0ae", "GRADE_B": "#81c784", "GRADE_C": "#ffd740",
        "GRADE_D": "#ffab40", "GRADE_F": "#ff5252",
    },
    "Verdant": {
        "BG_DEEP": "#0a1a10", "BG_SURFACE": "#122818", "BG_CARD": "#1a3520",
        "BG_HOVER": "#1e4528", "BG_INPUT": "#0f1e14",
        "ACCENT": "#00e676", "ACCENT_DIM": "#00a152", "MAGENTA": "#ea80fc",
        "SUCCESS": "#76ff03", "WARNING": "#ffea00", "ERROR": "#ff1744",
        "INFO": "#40c4ff", "TEXT": "#e8f5e9", "TEXT_DIM": "#a5d6a7",
        "TEXT_MUTED": "#4caf50", "BORDER": "#2e7d32",
        "GRADE_A": "#76ff03", "GRADE_B": "#69f0ae", "GRADE_C": "#ffea00",
        "GRADE_D": "#ff9100", "GRADE_F": "#ff1744",
    },
    "Orchid": {
        "BG_DEEP": "#140a1a", "BG_SURFACE": "#1e1127", "BG_CARD": "#281a35",
        "BG_HOVER": "#321e45", "BG_INPUT": "#180f29",
        "ACCENT": "#ce93d8", "ACCENT_DIM": "#9c64a6", "MAGENTA": "#f48fb1",
        "SUCCESS": "#69f0ae", "WARNING": "#ffe57f", "ERROR": "#ef5350",
        "INFO": "#90caf9", "TEXT": "#f3e5f5", "TEXT_DIM": "#b39ddb",
        "TEXT_MUTED": "#7e57c2", "BORDER": "#4a148c",
        "GRADE_A": "#69f0ae", "GRADE_B": "#81c784", "GRADE_C": "#ffe57f",
        "GRADE_D": "#ffab40", "GRADE_F": "#ef5350",
    },
    "Arctic": {
        "BG_DEEP": "#0a1420", "BG_SURFACE": "#101e2e", "BG_CARD": "#18283a",
        "BG_HOVER": "#1e3348", "BG_INPUT": "#0e1828",
        "ACCENT": "#80deea", "ACCENT_DIM": "#4bacb8", "MAGENTA": "#f48fb1",
        "SUCCESS": "#69f0ae", "WARNING": "#fff176", "ERROR": "#ef5350",
        "INFO": "#64b5f6", "TEXT": "#eceff1", "TEXT_DIM": "#90a4ae",
        "TEXT_MUTED": "#546e7a", "BORDER": "#37474f",
        "GRADE_A": "#69f0ae", "GRADE_B": "#81c784", "GRADE_C": "#fff176",
        "GRADE_D": "#ffab40", "GRADE_F": "#ef5350",
    },
    "Dusk": {
        "BG_DEEP": "#1a1408", "BG_SURFACE": "#241e10", "BG_CARD": "#302818",
        "BG_HOVER": "#3c3220", "BG_INPUT": "#1e180c",
        "ACCENT": "#ffd54f", "ACCENT_DIM": "#c8a415", "MAGENTA": "#ff80ab",
        "SUCCESS": "#69f0ae", "WARNING": "#ffe082", "ERROR": "#ff5252",
        "INFO": "#81d4fa", "TEXT": "#fff8e1", "TEXT_DIM": "#bcaaa4",
        "TEXT_MUTED": "#795548", "BORDER": "#5d4037",
        "GRADE_A": "#69f0ae", "GRADE_B": "#81c784", "GRADE_C": "#ffe082",
        "GRADE_D": "#ffab40", "GRADE_F": "#ff5252",
    },
}


def _apply_scheme(name):
    """Apply a named color scheme to the Theme class."""
    scheme = COLOR_SCHEMES.get(name)
    if not scheme:
        return
    for attr, val in scheme.items():
        setattr(Theme, attr, val)


# ─────────────────────────────────────────────────────────────────
#  CHECK DEFINITIONS — 26 Diagnostic Checks (12 AnimBP + 14 General BP)
# ─────────────────────────────────────────────────────────────────

class Severity(Enum):
    ERROR   = "ERROR"
    WARNING = "WARNING"
    INFO    = "INFO"

class Confidence(Enum):
    HIGH   = "HIGH"    # Deterministic or near-deterministic detection
    MEDIUM = "MEDIUM"  # Reliable heuristic, rare false positives
    LOW    = "LOW"     # Heuristic-based, verify in editor

@dataclass
class CheckDefinition:
    id: int
    name: str
    code: str
    severity: Severity
    auto_fixable: bool
    description: str
    why_it_matters: str
    confidence: Confidence = Confidence.MEDIUM
    beginner_tip: str = ""  # Plain-English explanation for new UE5 devs
    binary_markers: List[str] = field(default_factory=list)
    negative_markers: List[str] = field(default_factory=list)

CHECKS: List[CheckDefinition] = [
    CheckDefinition(
        id=1, name="Null Anim Reference", code="NULL_ANIM_REF",
        severity=Severity.ERROR, auto_fixable=False,
        description="Sequence Player node has no animation asset assigned.",
        why_it_matters="A Sequence Player with no animation will cause the character to snap to T-pose "
                       "when that state is entered. This is the most common cause of intermittent T-posing "
                       "that can take 1-4 hours to track down manually.",
                confidence=Confidence.HIGH,
        beginner_tip="One of your animation nodes is empty — it has no animation assigned. This makes your character snap to a T-pose (arms out, legs straight) when that animation should play. Open your AnimBP and look for nodes showing 'None' where an animation should be.",
        binary_markers=["AnimGraphNode_SequencePlayer"],
        negative_markers=["AnimSequence"]
    ),
    CheckDefinition(
        id=2, name="Broken Blend Weight", code="BROKEN_BLEND_WT",
        severity=Severity.WARNING, auto_fixable=True,
        description="Blend weight value is outside the valid [0.0, 1.0] range.",
        why_it_matters="Weights outside [0,1] produce wrong blend proportions or visual pops. "
                       "UE5 does not clamp these automatically, so out-of-range values silently "
                       "corrupt your blend results.",
                confidence=Confidence.MEDIUM,
        beginner_tip="A blend weight controls how much two animations mix together. It should be between 0 (fully first anim) and 1 (fully second anim). Yours is outside this range, which causes visual glitches like jittering or impossible poses.",
        binary_markers=["LayeredBoneBlend", "BlendWeight"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=3, name="Skeleton Mismatch", code="SKEL_MISMATCH",
        severity=Severity.ERROR, auto_fixable=False,
        description="Animation asset targets a different skeleton than the AnimBlueprint.",
        why_it_matters="Skeleton mismatches cause distorted meshes, bones in wrong positions, or "
                       "cook/package failures. Often not caught until build time, where it blocks "
                       "the entire pipeline. Can cost 2-8 hours to diagnose across large projects.",
                confidence=Confidence.MEDIUM,
        beginner_tip="Your AnimBP uses a skeleton (the bone structure), but one of the animations in it was made for a DIFFERENT skeleton. This causes the mesh to look distorted or broken. It's like putting a shirt designed for one mannequin on a completely different one.",
        binary_markers=["Skeleton", "TargetSkeleton"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=4, name="Missing Default Slot", code="MISSING_SLOT",
        severity=Severity.WARNING, auto_fixable=True,
        description="No Slot node found in the AnimGraph — montages will not play.",
        why_it_matters="This is the #1 AnimBP question on forums. The AnimBP compiles clean. "
                       "The montage plays in preview. But in-game, PlayMontage() silently fails. "
                       "Developers check gameplay code, the montage, the slot name — everything "
                       "seems fine. The missing Slot node is always the last thing they check.",
                confidence=Confidence.HIGH,
        beginner_tip="You're trying to play a Montage (a special animation like an attack or emote), but your AnimBP has no Slot node. Without a Slot, the engine has nowhere to play the Montage — so it silently does nothing. This is the #1 most asked AnimBP question on forums.",
        binary_markers=["AnimGraphNode_Slot"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=5, name="Broken Transition", code="BROKEN_TRANS",
        severity=Severity.WARNING, auto_fixable=False,
        description="State machine contains unreachable states with no inbound transitions.",
        why_it_matters="Unreachable states mean your character can get stuck in an animation "
                       "with no way out. On state machines with 20+ states and complex transitions, "
                       "finding the dead-end manually takes 2-6 hours.",
                confidence=Confidence.MEDIUM,
        beginner_tip="Your state machine (the system that decides which animation plays) has some states that can never be reached — there's no arrow pointing into them. This means your character could get stuck in an animation with no way to transition out.",
        binary_markers=["AnimGraphNode_StateMachine", "AnimGraphNode_TransitionResult"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=6, name="T-Pose Fallback", code="TPOSE_FALLBACK",
        severity=Severity.ERROR, auto_fixable=True,
        description="LayeredBoneBlend has a disconnected BasePose input, causing T-pose.",
        why_it_matters="This produces a partial T-pose on specific bones during specific blend "
                       "scenarios. Extremely hard to reproduce because it depends on blend weights "
                       "and animation timing. Takes 1-3 hours to track down.",
                confidence=Confidence.MEDIUM,
        beginner_tip="A bone blending node has a disconnected input. When this happens, the affected bones fall back to the reference pose (T-pose). This usually shows up as random T-pose flashes during specific blend scenarios.",
        binary_markers=["AnimGraphNode_LayeredBoneBlend", "BasePose"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=7, name="Orphaned Node", code="ORPHANED_NODE",
        severity=Severity.INFO, auto_fixable=False,
        description="Node exists in the graph but is not reachable from the Output Pose.",
        why_it_matters="Orphaned nodes clutter the graph and confuse team members. They add "
                       "10-15 minutes per debug session as developers mentally filter noise. "
                       "Over weeks, this compounds into significant wasted time.",
                confidence=Confidence.MEDIUM,
        beginner_tip="Your AnimBP graph has nodes that aren't connected to anything. They don't cause crashes, but they clutter your graph and confuse anyone reading it. Think of them as dead code — safe to delete.",
        binary_markers=["AnimGraphNode_"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=8, name="Invalid BlendSpace", code="INVALID_BSPACE",
        severity=Severity.WARNING, auto_fixable=False,
        description="BlendSpace asset has 0 or 1 sample points — cannot interpolate.",
        why_it_matters="A BlendSpace with insufficient samples produces static or broken "
                       "interpolation. The character appears to move correctly in simple tests "
                       "but breaks under real gameplay conditions.",
                confidence=Confidence.MEDIUM,
        beginner_tip="A BlendSpace needs at least 2 animation samples to interpolate between. Yours has 0 or 1, which means it can't blend — the character will either freeze or snap between poses instead of smoothly transitioning.",
        binary_markers=["BlendSpace", "SampleData"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=9, name="Missing Notify", code="MISSING_NOTIFY",
        severity=Severity.INFO, auto_fixable=False,
        description="AnimNotify references a function or event that has been deleted.",
        why_it_matters="Missing notify references can crash the editor. There are 7+ crash "
                       "report threads about this on Epic forums. Even when it doesn't crash, "
                       "your footstep sounds, VFX triggers, and gameplay events silently stop firing.",
                confidence=Confidence.MEDIUM,
        beginner_tip="Your animation has a Notify event (like 'play footstep sound here') but there's no matching handler function. The event fires, but nothing listens for it — so your sound effects, VFX, or gameplay triggers silently don't work.",
        binary_markers=["AnimNotify", "AnimNotifyEvent"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=10, name="Duplicate Slot Name", code="DUP_SLOT",
        severity=Severity.WARNING, auto_fixable=True,
        description="The same slot name is used by multiple Slot nodes in the AnimGraph.",
        why_it_matters="Duplicate slot names cause montages to play on the wrong layer or "
                       "interfere with each other. This produces visual glitches that only "
                       "appear when two montages try to play simultaneously.",
                confidence=Confidence.HIGH,
        beginner_tip="Two Slot nodes in your AnimBP have the same name. When you play a Montage, it plays on ALL slots with that name simultaneously, causing animation conflicts. Each Slot should have a unique name like 'DefaultSlot', 'UpperBody', 'LowerBody'.",
        binary_markers=["SlotName", "AnimGraphNode_Slot"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=11, name="Unused Variable", code="UNUSED_VAR",
        severity=Severity.INFO, auto_fixable=False,
        description="AnimInstance variable is declared but never read in the AnimGraph.",
        why_it_matters="Unused variables create false leads during debugging. When tracking down "
                       "a bug, developers waste time investigating variables that don't actually "
                       "drive any animation behavior.",
                confidence=Confidence.MEDIUM,
        beginner_tip="Your AnimBP declares variables that are never actually read by the animation graph. These are dead weight — they add clutter and create false leads when debugging. Safe to remove.",
        binary_markers=["AnimBlueprintGeneratedClass", "Property"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=12, name="Deprecated Node", code="DEPRECATED_NODE",
        severity=Severity.WARNING, auto_fixable=False,
        description="AnimGraph uses a node class marked CLASS_Deprecated.",
        why_it_matters="Deprecated nodes will break on the next engine upgrade. Catching them "
                       "now saves 1-4 hours of migration debugging later. Epic removes deprecated "
                       "classes without warning between major versions.",
                confidence=Confidence.MEDIUM,
        beginner_tip="Your AnimBP uses a node type that Epic has marked as deprecated. It works now, but will break when you upgrade to a newer engine version. Find the modern replacement node before upgrading.",
        binary_markers=["Deprecated", "DEPRECATED"],
        negative_markers=[]
    ),
    # ── General Blueprint Checks (13–20) ──
    CheckDefinition(
        id=13, name="Broken Asset Reference", code="BP_BROKEN_REF",
        severity=Severity.ERROR, auto_fixable=False,
        description="Blueprint references an asset path that does not exist on disk.",
        why_it_matters="Broken references cause crashes, failed loads, or silent null behavior "
                       "at runtime. The editor may not flag these until you try to open the "
                       "specific node or cook the project. In large projects with hundreds of "
                       "Blueprints, these accumulate silently and block shipping.",
                confidence=Confidence.HIGH,
        beginner_tip="Your Blueprint references another asset (mesh, texture, sound, etc.) that has been deleted or moved. At runtime, this will cause a crash or the asset will silently fail to load. Fix it by reconnecting to the correct asset or removing the broken reference.",
        binary_markers=["BlueprintGeneratedClass"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=14, name="Excessive Complexity", code="BP_COMPLEXITY",
        severity=Severity.WARNING, auto_fixable=False,
        description="Blueprint has an extremely high node count (100+ unique nodes).",
        why_it_matters="Complex Blueprints are harder to maintain, debug, and optimize. "
                       "Each node adds to compile time and nativization overhead. Epic's "
                       "own optimization guides recommend keeping Blueprints under 100 nodes "
                       "and moving heavy logic to C++. Studios routinely lose 4-8 hours per "
                       "sprint debugging spaghetti Blueprints.",
                confidence=Confidence.HIGH,
        beginner_tip="This Blueprint has a LOT of nodes — over 100. Complex Blueprints are harder to read, debug, and maintain. Consider breaking it into smaller functions (right-click > Collapse to Function) or moving heavy logic to C++.",
        binary_markers=["K2Node_"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=15, name="Empty Event Graph", code="BP_EMPTY_GRAPH",
        severity=Severity.INFO, auto_fixable=False,
        description="Blueprint exists but contains no meaningful logic nodes.",
        why_it_matters="Empty Blueprints clutter the project, confuse team members, and "
                       "waste compile time. They often indicate abandoned prototypes or "
                       "duplicated files that were never cleaned up. Over time they become "
                       "false leads during debugging.",
                confidence=Confidence.HIGH,
        beginner_tip="This Blueprint exists but has no logic inside it. It might be a placeholder from an old prototype. Empty Blueprints waste compile time and confuse team members. Delete it if it's not needed.",
        binary_markers=["BlueprintGeneratedClass"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=16, name="Tick Performance Risk", code="BP_TICK_HEAVY",
        severity=Severity.WARNING, auto_fixable=False,
        description="Blueprint has Event Tick enabled with high node complexity.",
        why_it_matters="Event Tick runs every frame for every instance of this Blueprint. "
                       "A complex Blueprint on Tick with 50 spawned actors can drop FPS by "
                       "30-50%. Epic's optimization guide explicitly warns against this. "
                       "Use timers, event-driven logic, or move to C++ Tick instead.",
                confidence=Confidence.MEDIUM,
        beginner_tip="Event Tick runs code EVERY SINGLE FRAME. If your Blueprint does heavy work in Tick (like searching for actors), it will destroy your FPS. Use a Timer instead — running every 0.2 seconds is usually enough and 5x cheaper.",
        binary_markers=["ReceiveTick", "K2Node_"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=17, name="Self-Cast Detected", code="BP_SELF_CAST",
        severity=Severity.INFO, auto_fixable=True,
        description="Blueprint casts to its own class type (unnecessary overhead).",
        why_it_matters="Casting to Self always succeeds — you already ARE that type. It "
                       "wastes a cast node, adds an unnecessary execution pin, and confuses "
                       "readers. This is a common beginner pattern. Replace with a direct "
                       "Self reference for cleaner, faster Blueprints.",
                confidence=Confidence.HIGH,
        beginner_tip="Your Blueprint casts to its own type. This always succeeds (you already ARE that type!) so the Cast node is unnecessary overhead. Delete it and use a 'Self' reference instead.",
        binary_markers=["K2Node_DynamicCast"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=18, name="Deprecated API Usage", code="BP_DEPRECATED_FUNC",
        severity=Severity.WARNING, auto_fixable=False,
        description="Blueprint uses functions or classes marked as deprecated in UE5.",
        why_it_matters="Deprecated APIs will be removed in future engine versions. Finding "
                       "and replacing them now saves hours of migration debugging when you "
                       "upgrade. Epic removes deprecated classes between major versions "
                       "without warning. Catching them early is critical for long-lived projects.",
                confidence=Confidence.MEDIUM,
        beginner_tip="This Blueprint calls functions that Epic has deprecated. They work now but will be removed in a future engine update. The fix is usually simple — hover over the deprecated node to see what replaces it.",
        binary_markers=["Deprecated", "DEPRECATED"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=19, name="Circular Dependency", code="BP_CIRCULAR_DEP",
        severity=Severity.WARNING, auto_fixable=False,
        description="Two Blueprints reference each other, creating a circular dependency.",
        why_it_matters="Circular dependencies cause unpredictable load order, editor hitches, "
                       "and potential crashes during garbage collection. They make refactoring "
                       "extremely difficult because neither Blueprint can be moved or deleted "
                       "without breaking the other. Studios spend 2-6 hours untangling these.",
                confidence=Confidence.HIGH,
        beginner_tip="Two Blueprints reference each other — A needs B and B needs A. This causes unpredictable loading, editor hitches, and makes it impossible to move or delete either one without breaking the other. Use a Blueprint Interface to break the cycle.",
        binary_markers=["BlueprintGeneratedClass"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=20, name="Oversized Blueprint Asset", code="BP_MASSIVE_ASSET",
        severity=Severity.WARNING, auto_fixable=False,
        description="Blueprint .uasset file is abnormally large (>5MB).",
        why_it_matters="Blueprint files should rarely exceed 1-2MB. Oversized files indicate "
                       "embedded mesh/texture data, excessive node graphs, or corruption. "
                       "They slow down editor load times, version control operations, and "
                       "cooking. Every team member pays this cost on every sync.",
                confidence=Confidence.HIGH,
        beginner_tip="This Blueprint file is unusually large (over 5MB). Normal Blueprints are under 1MB. Large files slow down the editor, version control, and cooking. Check if there's embedded data (large arrays, mesh data) that should be in a separate asset.",
        binary_markers=["BlueprintGeneratedClass"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=21, name="Hard Reference Bloat", code="BP_HARD_REF",
        severity=Severity.WARNING, auto_fixable=False,
        description="Blueprint has excessive hard references to other Blueprint classes.",
        why_it_matters="Each Cast-to-Blueprint node creates a hard reference that forces the "
                       "target Blueprint AND all its dependencies into memory at load time. "
                       "A single Blueprint can silently pull gigabytes of transitive assets. "
                       "This is the #1 Blueprint performance complaint on Epic forums. Use "
                       "soft references or Blueprint Interfaces instead.",
                confidence=Confidence.MEDIUM,
        beginner_tip="This Blueprint has many 'hard references' to other Blueprints via Cast nodes. Each hard reference forces the other Blueprint AND all its assets to load into memory. This can silently cause your game to use gigabytes of extra RAM. Use Interfaces or Soft References instead.",
        binary_markers=["K2Node_DynamicCast", "BlueprintGeneratedClass"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=22, name="Expensive Operations in Tick", code="BP_EXPENSIVE_TICK",
        severity=Severity.WARNING, auto_fixable=False,
        description="Blueprint runs expensive query operations inside Event Tick.",
        why_it_matters="GetAllActorsOfClass, LineTrace, and SweepMulti inside Tick run "
                       "every frame for every instance. 50 actors each calling "
                       "GetAllActorsOfClass in Tick iterates the entire actor list 50x per "
                       "frame. This is the single most common cause of Blueprint FPS drops. "
                       "Epic's optimization guide explicitly warns against this pattern.",
                confidence=Confidence.MEDIUM,
        beginner_tip="This Blueprint has expensive search functions (like 'Get All Actors of Class') that appear alongside Event Tick. If these run every frame, they will tank your FPS — especially with multiple instances. Move them to BeginPlay or a Timer.",
        binary_markers=["ReceiveTick", "GetAllActorsOfClass"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=23, name="Debug Nodes in Production", code="BP_DEBUG_NODES",
        severity=Severity.WARNING, auto_fixable=True,
        description="Blueprint contains PrintString or DrawDebug nodes.",
        why_it_matters="PrintString costs ~0.07ms each and may execute in Shipping builds "
                       "despite the 'Development Only' flag (confirmed bug in multiple UE5 "
                       "versions). DrawDebug nodes are even more expensive. These should be "
                       "removed before shipping — they cause frame drops and can leak debug "
                       "information to players.",
                confidence=Confidence.HIGH,
        beginner_tip="PrintString and DrawDebug nodes are still in this Blueprint. These are meant for development only but can leak into shipping builds due to a known UE5 bug. Remove them before releasing your game — they also cost performance (~0.07ms each).",
        binary_markers=["PrintString", "DrawDebugLine"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=24, name="Construction Script Misuse", code="BP_CONSTRUCT_HEAVY",
        severity=Severity.WARNING, auto_fixable=True,
        description="Construction Script contains spawning or heavy query operations.",
        why_it_matters="The Construction Script runs in the editor every time a property "
                       "changes, the actor moves, or the level loads. SpawnActor, "
                       "GetAllActorsOfClass, and similar operations here cause editor "
                       "freezes, infinite loops, and crashes. Multiple crash reports on "
                       "Epic forums trace back to this pattern.",
                confidence=Confidence.HIGH,
        beginner_tip="The Construction Script runs in the EDITOR every time you move an actor or change a property. Heavy operations like SpawnActor in here cause editor freezes and crashes. Move this logic to BeginPlay, which only runs when the game starts.",
        binary_markers=["UserConstructionScript", "SpawnActorFromClass"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=25, name="ForEach Loop Performance", code="BP_FOREACH_PERF",
        severity=Severity.INFO, auto_fixable=False,
        description="ForEachLoop re-evaluates pure input nodes on every iteration.",
        why_it_matters="Blueprint's ForEachLoop macro re-evaluates pure input expressions "
                       "every iteration. If the array comes from GetComponentsByClass (a "
                       "pure node), the query runs twice per loop pass — causing 20-50%% "
                       "performance degradation vs a standard ForLoop with a cached array.",
                confidence=Confidence.MEDIUM,
        beginner_tip="ForEachLoop in Blueprints has a hidden performance cost: it re-runs the input expression on every loop pass. If the input is a query like 'Get Components by Class', that query runs TWICE per iteration. Cache the array in a variable first, then loop over the variable.",
        binary_markers=["ForEachLoop"],
        negative_markers=[]
    ),
    CheckDefinition(
        id=26, name="Excessive Timeline Components", code="BP_TIMELINE_HEAVY",
        severity=Severity.INFO, auto_fixable=True,
        description="Blueprint has multiple Timeline nodes creating hidden tick overhead.",
        why_it_matters="Each Timeline node creates a hidden UTimelineComponent that "
                       "registers with the tick manager and ticks every frame. Multiple "
                       "Timelines multiply this hidden cost. Consider merging Timelines, "
                       "using timers for simple lerps, or implementing in C++.",
                confidence=Confidence.MEDIUM,
        beginner_tip="Each Timeline node creates a hidden component that ticks every frame. With multiple Timelines, you have multiple hidden per-frame costs. Consider merging Timelines or using simpler Lerp + Timer for basic animations.",
        binary_markers=["TimelineComponent", "K2Node_Timeline"],
        negative_markers=[]
    ),
]

CHECK_MAP = {c.code: c for c in CHECKS}

# ─────────────────────────────────────────────────────────────────
#  CHECK HANDLER REGISTRY — Dispatch table for check logic
# ─────────────────────────────────────────────────────────────────

_CHECK_HANDLERS: Dict[str, Callable] = {}

def check_handler(code: str):
    """Decorator that registers a function as the handler for a check code."""
    def decorator(fn):
        _CHECK_HANDLERS[code] = fn
        return fn
    return decorator

# Precompiled regex for fast ASCII string extraction (used by handlers)
_STRING_PATTERN = re.compile(rb'[\x20-\x7e]{4,}')

def _extract_strings(data: bytes) -> str:
    """Extract readable ASCII strings from binary data using regex."""
    return " ".join(m.group().decode("ascii", errors="ignore")
                   for m in _STRING_PATTERN.finditer(data))


# ── AnimBP Check Handlers ──

@check_handler("NULL_ANIM_REF")
def _check_null_anim_ref(check, abp, raw, get_text, get_text_lower, name_table):
    results = []
    if name_table is not None:
        has_players = "AnimGraphNode_SequencePlayer" in name_table
        has_anim_refs = ("AnimSequence" in name_table or
                        "AnimMontage" in name_table or
                        "AnimComposite" in name_table)
        if has_players and not has_anim_refs:
            results.append(ScanResult(
                check_code=check.code, severity=check.severity.value,
                animblueprint=abp.name, asset_path=abp.asset_path,
                description=f"{check.description} SequencePlayer found but no AnimSequence references in name table.",
                node_hint="SequencePlayer node(s) with no animation assigned",
                auto_fixable=check.auto_fixable, asset_type=abp.asset_type))
    else:
        player_count = raw.count(b"AnimGraphNode_SequencePlayer")
        if player_count > 0:
            anim_ref_count = raw.count(b"AnimSequence")
            if anim_ref_count == 0:
                results.append(ScanResult(
                    check_code=check.code, severity=check.severity.value,
                    animblueprint=abp.name, asset_path=abp.asset_path,
                    description=f"{check.description} {player_count} players, 0 anim refs.",
                    node_hint=f"{player_count} SequencePlayer(s) with no animation references found",
                    auto_fixable=check.auto_fixable, asset_type=abp.asset_type))
    return results

@check_handler("BROKEN_BLEND_WT")
def _check_broken_blend_wt(check, abp, raw, get_text, get_text_lower, name_table):
    results = []
    if b"BlendWeight" in raw or b"LayeredBoneBlend" in raw:
        idx = raw.find(b"BlendWeight")
        if idx != -1:
            region = raw[idx+len(b"BlendWeight"):idx+len(b"BlendWeight")+64]
            for offset in range(0, min(len(region)-4, 48), 4):
                try:
                    val = struct.unpack('f', region[offset:offset+4])[0]
                    if not math.isfinite(val):
                        continue
                    if (-10.0 < val < -0.01) or (1.05 < val < 50.0):
                        results.append(ScanResult(
                            check_code=check.code, severity=check.severity.value,
                            animblueprint=abp.name, asset_path=abp.asset_path,
                            description=f"{check.description} Found weight: {val:.3f}",
                            node_hint=f"BlendWeight = {val:.3f}",
                            auto_fixable=check.auto_fixable))
                        break
                except struct.error:
                    pass
    return results

@check_handler("SKEL_MISMATCH")
def _check_skel_mismatch(check, abp, raw, get_text, get_text_lower, name_table):
    """Detect multiple different skeleton references. Filters out property names
    and metadata that contain 'Skeleton' but aren't actual skeleton asset paths."""
    results = []

    # Property/metadata names to exclude — these contain "Skeleton" but aren't asset refs
    SKEL_NOISE = frozenset({
        "Skeleton", "TargetSkeleton", "SkeletonGuid", "SkeletonGuid:",
        "bSetRefPoseFromSkeleton", "AnimNode_ControlRig:bSetRefPoseFromSkeleton",
        "ReferenceSkeleton", "VirtualBoneRefData", "SkeletonNotifier",
        "USkeleton", "SkeletalMesh", "SkeletalMeshComponent",
    })

    if name_table is not None:
        # Precise: look for actual skeleton ASSET paths in name table
        # Real paths look like: /Game/.../SK_Mannequin.SK_Mannequin or end with _Skeleton
        # Exclude: property names, class names, metadata
        skel_paths = set()
        for n in name_table:
            # Must be a /Game/ asset path or /Script/Engine.Skeleton path
            if not (n.startswith("/Game/") or "/Script/Engine.Skeleton" in n):
                continue
            # Must reference a skeleton asset (SK_ prefix or _Skeleton suffix in the path)
            if not ("SK_" in n or "_Skeleton." in n or "_Skeleton'" in n):
                continue
            # Exclude noise
            if any(noise in n for noise in SKEL_NOISE):
                continue
            skel_paths.add(n)
        if len(skel_paths) > 1:
            results.append(ScanResult(
                check_code=check.code, severity=check.severity.value,
                animblueprint=abp.name, asset_path=abp.asset_path,
                description=f"{check.description} Found {len(skel_paths)} skeleton references.",
                node_hint=f"Skeletons: {', '.join(list(skel_paths)[:3])}",
                auto_fixable=check.auto_fixable))
    else:
        # Fallback: binary scan — look for /Game/ paths containing SK_ or _Skeleton
        skel_refs = []
        idx = 0
        while True:
            idx = raw.find(b"/Game/", idx)
            if idx == -1:
                break
            region = raw[idx:idx+200]
            region_str = _extract_strings(region)
            for word in region_str.split():
                if ("/Game/" in word and ("SK_" in word or "_Skeleton" in word)
                    and not any(noise in word for noise in SKEL_NOISE)):
                    skel_refs.append(word)
            idx += 6
        unique_skels = set(s for s in skel_refs if len(s) > 10)
        if len(unique_skels) > 1:
            results.append(ScanResult(
                check_code=check.code, severity=check.severity.value,
                animblueprint=abp.name, asset_path=abp.asset_path,
                description=f"{check.description} Found {len(unique_skels)} skeleton references.",
                node_hint=f"Skeletons: {', '.join(list(unique_skels)[:3])}",
                auto_fixable=check.auto_fixable))
    return results

@check_handler("MISSING_SLOT")
def _check_missing_slot(check, abp, raw, get_text, get_text_lower, name_table):
    results = []
    has_montage_refs = (b"PlayMontage" in raw or b"Montage_Play" in raw
                        or b"SlotAnimationTrack" in raw or b"AnimMontage'" in raw)
    has_slot_node = b"AnimGraphNode_Slot" in raw
    if has_montage_refs and not has_slot_node and abp.asset_type == "AnimBP":
        results.append(ScanResult(
            check_code=check.code, severity=check.severity.value,
            animblueprint=abp.name, asset_path=abp.asset_path,
            description=check.description,
            node_hint="No AnimGraphNode_Slot found in graph",
            auto_fixable=check.auto_fixable))
    return results

@check_handler("BROKEN_TRANS")
def _check_broken_trans(check, abp, raw, get_text, get_text_lower, name_table):
    """Improved: uses minimum-transitions-for-N-states formula instead of ratio."""
    results = []
    sm_count = raw.count(b"AnimGraphNode_StateMachine")
    trans_count = raw.count(b"AnimGraphNode_TransitionResult")
    state_count = raw.count(b"AnimGraphNode_StateResult")
    if sm_count > 0 and state_count > 2:
        # A directed state machine with N states needs at minimum N transitions
        # for full reachability (each non-entry state needs at least one inbound).
        # Use state_count (not -1) since Entry has outbound-only.
        min_transitions = state_count
        if trans_count < min_transitions:
            # Confirmed: fewer transitions than the minimum for full connectivity
            missing = min_transitions - trans_count
            results.append(ScanResult(
                check_code=check.code, severity=check.severity.value,
                animblueprint=abp.name, asset_path=abp.asset_path,
                description=f"{check.description} {state_count} states, {trans_count} transitions (minimum {min_transitions} needed).",
                node_hint=f"{missing} missing transition(s) — states may be unreachable",
                auto_fixable=check.auto_fixable, asset_type=abp.asset_type))
    return results

@check_handler("TPOSE_FALLBACK")
def _check_tpose_fallback(check, abp, raw, get_text, get_text_lower, name_table):
    results = []
    if b"AnimGraphNode_LayeredBoneBlend" in raw:
        lbb_idx = raw.find(b"AnimGraphNode_LayeredBoneBlend")
        if lbb_idx != -1:
            region = raw[lbb_idx:lbb_idx+1024]
            null_pattern_count = region.count(b"\xff\xff\xff\xff")
            if null_pattern_count > 5:
                results.append(ScanResult(
                    check_code=check.code, severity=check.severity.value,
                    animblueprint=abp.name, asset_path=abp.asset_path,
                    description=check.description,
                    node_hint="LayeredBoneBlend — possible disconnected BasePose",
                    auto_fixable=check.auto_fixable, asset_type=abp.asset_type))
    return results

@check_handler("ORPHANED_NODE")
def _check_orphaned_node(check, abp, raw, get_text, get_text_lower, name_table):
    """Multi-signal orphan detection using name table type diversity, export counts,
    pin connection markers, and graph object counting."""
    results = []
    node_count = raw.count(b"AnimGraphNode_")
    if node_count <= 15:
        return results

    output_pose_refs = raw.count(b"AnimGraphNode_Root")
    linked_to_count = raw.count(b"LinkedTo")

    # Signal 1: Name table unique node TYPE count
    # A healthy AnimBP uses 5-12 distinct node types. 15+ = copy-paste debris.
    unique_node_types = 0
    graph_object_count = 0
    pose_link_count = 0
    if name_table is not None:
        unique_node_types = sum(1 for n in name_table if n.startswith("AnimGraphNode_"))
        graph_object_count = sum(1 for n in name_table
                                 if "AnimGraph" in n or "EdGraph" in n or "StateMachine" in n)
        pose_link_count = sum(1 for n in name_table
                             if n in ("OutputPose", "BasePose", "Result", "PoseLink",
                                      "ComponentPose", "InPose", "SourcePose"))

    # Signal 2: Export count vs node count ratio
    # If the file has many more AnimGraphNode_ occurrences in binary than exports,
    # the extra occurrences are redundant references — nodes that exist but aren't
    # connected to active exports. High ratio = noisy graph.
    export_node_ratio = 0
    if abp.export_count > 0:
        export_node_ratio = node_count / max(abp.export_count, 1)

    # Signal 3: Pin connection density
    expected_links = node_count * 1.5
    connection_ratio = linked_to_count / max(expected_links, 1)

    # ── Decision tree (multi-signal) ──

    # Strong signal: 15+ unique AnimGraphNode class types is very unusual
    if unique_node_types > 15 and output_pose_refs <= 1:
        results.append(ScanResult(
            check_code=check.code, severity=check.severity.value,
            animblueprint=abp.name, asset_path=abp.asset_path,
            description=f"{check.description} {unique_node_types} unique node types — unusual complexity.",
            node_hint=f"{unique_node_types} distinct AnimGraphNode types (typical: 5-12) — likely orphaned debris",
            auto_fixable=check.auto_fixable, asset_type=abp.asset_type))

    # Medium signal: many nodes, low pin connectivity
    elif node_count > 30 and connection_ratio < 0.3:
        results.append(ScanResult(
            check_code=check.code, severity=check.severity.value,
            animblueprint=abp.name, asset_path=abp.asset_path,
            description=f"{check.description} {node_count} nodes, {linked_to_count} pin connections.",
            node_hint=f"Low connectivity ({connection_ratio:.0%} of expected) — likely orphaned nodes",
            auto_fixable=check.auto_fixable, asset_type=abp.asset_type))

    # Medium signal: many types with few pose-link connections relative to types
    elif unique_node_types > 15 and pose_link_count < 2:
        results.append(ScanResult(
            check_code=check.code, severity=check.severity.value,
            animblueprint=abp.name, asset_path=abp.asset_path,
            description=f"{check.description} {unique_node_types} node types but minimal pose connections.",
            node_hint=f"{unique_node_types} types, {pose_link_count} pose links — nodes may be disconnected",
            auto_fixable=check.auto_fixable, asset_type=abp.asset_type))

    # Weak signal: very high raw count with single root (kept as fallback)
    elif output_pose_refs <= 1 and node_count > 60:
        results.append(ScanResult(
            check_code=check.code, severity=check.severity.value,
            animblueprint=abp.name, asset_path=abp.asset_path,
            description=f"{check.description} {node_count} total nodes detected.",
            node_hint=f"{node_count} nodes with only {output_pose_refs} Output Pose root(s)",
            auto_fixable=check.auto_fixable, asset_type=abp.asset_type))

    return results

@check_handler("INVALID_BSPACE")
def _check_invalid_bspace(check, abp, raw, get_text, get_text_lower, name_table):
    results = []
    is_bs_asset = (b"BlendSpaceGraph" in raw or b"BlendSpace1DGraph" in raw or
                  (b"BlendSpace" in raw and b"AnimGraphNode_BlendSpacePlayer" not in raw
                   and b"AnimBlueprintGeneratedClass" not in raw))
    if is_bs_asset:
        bs_count = raw.count(b"BlendSpace")
        sample_refs = raw.count(b"SampleData") + raw.count(b"BlendSample")
        if bs_count > 0 and sample_refs < 2:
            results.append(ScanResult(
                check_code=check.code, severity=check.severity.value,
                animblueprint=abp.name, asset_path=abp.asset_path,
                description=check.description,
                node_hint="BlendSpace with minimal sample data",
                auto_fixable=check.auto_fixable, asset_type=abp.asset_type))
    return results

@check_handler("MISSING_NOTIFY")
def _check_missing_notify(check, abp, raw, get_text, get_text_lower, name_table):
    results = []
    if name_table is not None:
        has_events = "AnimNotifyEvent" in name_table
        has_handlers = any(n.startswith("AnimNotify_") for n in name_table)
        if has_events and not has_handlers:
            results.append(ScanResult(
                check_code=check.code, severity=check.severity.value,
                animblueprint=abp.name, asset_path=abp.asset_path,
                description=check.description,
                node_hint="AnimNotifyEvent found but no AnimNotify_ handlers in name table",
                auto_fixable=check.auto_fixable, asset_type=abp.asset_type))
    else:
        event_count = raw.count(b"AnimNotifyEvent")
        handler_count = raw.count(b"AnimNotify_")
        if event_count > 0 and handler_count == 0:
            results.append(ScanResult(
                check_code=check.code, severity=check.severity.value,
                animblueprint=abp.name, asset_path=abp.asset_path,
                description=check.description,
                node_hint=f"{event_count} AnimNotifyEvent(s) but no AnimNotify_ handlers",
                auto_fixable=check.auto_fixable, asset_type=abp.asset_type))
    return results

@check_handler("DUP_SLOT")
def _check_dup_slot(check, abp, raw, get_text, get_text_lower, name_table):
    results = []
    slot_indices = []
    idx = 0
    while True:
        idx = raw.find(b"AnimGraphNode_Slot", idx)
        if idx == -1:
            break
        slot_indices.append(idx)
        idx += 18
    if len(slot_indices) > 1:
        slot_names = []
        for si in slot_indices:
            region = _extract_strings(raw[si:si+512])
            for word in region.split():
                if "Slot" in word and "AnimGraph" not in word:
                    slot_names.append(word)
        seen = set()
        for sn in slot_names:
            if sn in seen:
                results.append(ScanResult(
                    check_code=check.code, severity=check.severity.value,
                    animblueprint=abp.name, asset_path=abp.asset_path,
                    description=f"{check.description} Duplicate: '{sn}'",
                    node_hint=f"Slot name '{sn}' used multiple times",
                    auto_fixable=check.auto_fixable, asset_type=abp.asset_type))
                break
            seen.add(sn)
    return results

@check_handler("UNUSED_VAR")
def _check_unused_var(check, abp, raw, get_text, get_text_lower, name_table):
    results = []
    if name_table is not None and abp.asset_type == "AnimBP":
        # Count user-defined properties vs graph read references
        user_props = [n for n in name_table
                      if n.endswith("Property") and not n.startswith("b")
                      and "Engine." not in n and "CoreUObject." not in n]
        graph_reads = [n for n in name_table
                       if n.startswith("K2Node_VariableGet")
                       or n.startswith("AnimGraphNode_")
                       or "Get" in n and "Property" not in n]
        if len(user_props) > 12 and len(graph_reads) < 3:
            results.append(ScanResult(
                check_code=check.code, severity=check.severity.value,
                animblueprint=abp.name, asset_path=abp.asset_path,
                description=f"{check.description} {len(user_props)} properties, {len(graph_reads)} graph reads.",
                node_hint=f"{len(user_props)} properties with minimal graph reads",
                auto_fixable=check.auto_fixable))
    return results

@check_handler("DEPRECATED_NODE")
def _check_deprecated_node(check, abp, raw, get_text, get_text_lower, name_table):
    results = []
    found_deprecated = False
    if name_table is not None:
        found_deprecated = any(
            ("Deprecated" in n or "DEPRECATED" in n)
            and ("AnimGraphNode" in n or "K2Node" in n or "Node_" in n)
            for n in name_table)
    else:
        anim_idx = raw.find(b"AnimGraphNode_")
        if anim_idx != -1:
            found_deprecated = b"Deprecated" in raw[anim_idx:anim_idx+200]
    if found_deprecated:
        results.append(ScanResult(
            check_code=check.code, severity=check.severity.value,
            animblueprint=abp.name, asset_path=abp.asset_path,
            description=check.description,
            node_hint="Deprecated class reference found",
            auto_fixable=check.auto_fixable, asset_type=abp.asset_type))
    return results

# ── General Blueprint Check Handlers ──

@check_handler("BP_BROKEN_REF")
def _check_bp_broken_ref(check, abp, raw, get_text, get_text_lower, name_table):
    results = []
    if name_table is not None and hasattr(check, '_scanner_project_path'):
        # This check needs project_path — passed via check object or handled in scanner
        pass
    # Note: this check requires project_path context — handled specially in _run_check
    return results

@check_handler("BP_COMPLEXITY")
def _check_bp_complexity(check, abp, raw, get_text, get_text_lower, name_table):
    results = []
    node_count = raw.count(b"K2Node_")
    if node_count > 100:
        results.append(ScanResult(
            check_code=check.code, severity=check.severity.value,
            animblueprint=abp.name, asset_path=abp.asset_path,
            description=f"{check.description} {node_count} node types detected.",
            node_hint=f"{node_count} K2Node entries — consider refactoring to functions or C++",
            auto_fixable=check.auto_fixable, asset_type=abp.asset_type))
    return results

@check_handler("BP_EMPTY_GRAPH")
def _check_bp_empty_graph(check, abp, raw, get_text, get_text_lower, name_table):
    results = []
    node_count = raw.count(b"K2Node_")
    if node_count < 3:
        results.append(ScanResult(
            check_code=check.code, severity=check.severity.value,
            animblueprint=abp.name, asset_path=abp.asset_path,
            description=f"{check.description} Only {node_count} node(s) found.",
            node_hint="Blueprint appears to contain no meaningful logic",
            auto_fixable=check.auto_fixable, asset_type=abp.asset_type))
    return results

@check_handler("BP_TICK_HEAVY")
def _check_bp_tick_heavy(check, abp, raw, get_text, get_text_lower, name_table):
    results = []
    has_tick = (b"ReceiveTick" in raw or b"EventTick" in raw
               or (name_table is not None and
                   ("ReceiveTick" in name_table or "EventTick" in name_table)))
    if has_tick:
        if name_table is not None:
            node_count = sum(1 for n in name_table if "K2Node_" in n)
        else:
            node_count = raw.count(b"K2Node_")
        if node_count > 30:
            results.append(ScanResult(
                check_code=check.code, severity=check.severity.value,
                animblueprint=abp.name, asset_path=abp.asset_path,
                description=f"{check.description} Tick enabled with {node_count} nodes.",
                node_hint=f"EventTick + {node_count} nodes — consider timers or C++ Tick",
                auto_fixable=check.auto_fixable, asset_type=abp.asset_type))
    return results

@check_handler("BP_SELF_CAST")
def _check_bp_self_cast(check, abp, raw, get_text, get_text_lower, name_table):
    results = []
    if name_table is not None:
        bp_class = abp.name
        has_self_cast = any(
            ("Cast" in n or "DynamicCast" in n) and bp_class in n
            for n in name_table)
        if not has_self_cast:
            has_cast_node = "K2Node_DynamicCast" in name_table
            has_own_class = any(bp_class in n for n in name_table
                               if "CastTo" in n or "Cast_" in n)
            has_self_cast = has_cast_node and has_own_class
        if has_self_cast:
            results.append(ScanResult(
                check_code=check.code, severity=check.severity.value,
                animblueprint=abp.name, asset_path=abp.asset_path,
                description=check.description,
                node_hint=f"Blueprint casts to its own type '{bp_class}' — use Self instead",
                auto_fixable=check.auto_fixable, asset_type=abp.asset_type))
    return results

@check_handler("BP_DEPRECATED_FUNC")
def _check_bp_deprecated_func(check, abp, raw, get_text, get_text_lower, name_table):
    results = []
    DEPRECATED_MARKERS = [
        b"EditorUtilityObject_Deprecated",
        b"DEPRECATED_UseExternalActors",
        b"UK2Node_Deprecated",
    ]
    found_deprecated = [marker.decode("ascii", errors="ignore")
                       for marker in DEPRECATED_MARKERS if marker in raw]
    if found_deprecated:
        results.append(ScanResult(
            check_code=check.code, severity=check.severity.value,
            animblueprint=abp.name, asset_path=abp.asset_path,
            description=f"{check.description} Found: {', '.join(found_deprecated[:3])}",
            node_hint=f"Deprecated API usage: {', '.join(found_deprecated[:3])}",
            auto_fixable=check.auto_fixable, asset_type=abp.asset_type))
    return results

@check_handler("BP_CIRCULAR_DEP")
def _check_bp_circular_dep(check, abp, raw, get_text, get_text_lower, name_table):
    # Actual detection happens in _detect_circular_deps post-scan.
    # This handler just stores references for post-scan analysis.
    return []

@check_handler("BP_MASSIVE_ASSET")
def _check_bp_massive_asset(check, abp, raw, get_text, get_text_lower, name_table):
    results = []
    if abp.file_size > 5 * 1024 * 1024:
        size_mb = abp.file_size / (1024 * 1024)
        results.append(ScanResult(
            check_code=check.code, severity=check.severity.value,
            animblueprint=abp.name, asset_path=abp.asset_path,
            description=f"{check.description} File is {size_mb:.1f}MB.",
            node_hint=f"{size_mb:.1f}MB — check for embedded data or excessive nodes",
            auto_fixable=check.auto_fixable, asset_type=abp.asset_type))
    return results

@check_handler("BP_HARD_REF")
def _check_bp_hard_ref(check, abp, raw, get_text, get_text_lower, name_table):
    results = []
    if name_table is not None:
        hard_refs = [n for n in name_table
                     if n.startswith("/Game/") and n.endswith("_C")
                     and "/Script/" not in n]
        if len(hard_refs) > 5:
            results.append(ScanResult(
                check_code=check.code, severity=check.severity.value,
                animblueprint=abp.name, asset_path=abp.asset_path,
                description=f"{check.description} {len(hard_refs)} hard BP references.",
                node_hint=f"Hard refs: {', '.join(r.split('/')[-1] for r in hard_refs[:3])}{'...' if len(hard_refs) > 3 else ''}",
                auto_fixable=check.auto_fixable, asset_type=abp.asset_type))
    return results

@check_handler("BP_EXPENSIVE_TICK")
def _check_bp_expensive_tick(check, abp, raw, get_text, get_text_lower, name_table):
    results = []
    has_tick = ((name_table is not None and
                ("ReceiveTick" in name_table or "EventTick" in name_table)) or
               (b"ReceiveTick" in raw or b"EventTick" in raw))
    if has_tick:
        EXPENSIVE_OPS = [
            b"GetAllActorsOfClass", b"GetAllActorsWithTag",
            b"GetAllActorsWithInterface", b"GetAllActorsOfClassWithTag",
            b"LineTraceByChannel", b"LineTraceForObjects",
            b"SweepSingleByChannel", b"SweepMultiByChannel",
            b"GetComponentsByClass", b"GetComponentsByTag",
            b"GetOverlappingActors", b"GetOverlappingComponents",
        ]
        found_ops = [op.decode() for op in EXPENSIVE_OPS if op in raw]
        if found_ops:
            results.append(ScanResult(
                check_code=check.code, severity=check.severity.value,
                animblueprint=abp.name, asset_path=abp.asset_path,
                description=f"{check.description} Found: {', '.join(found_ops[:3])}",
                node_hint=f"Tick + {', '.join(found_ops[:2])} — move to timer or C++",
                auto_fixable=check.auto_fixable, asset_type=abp.asset_type))
    return results

@check_handler("BP_DEBUG_NODES")
def _check_bp_debug_nodes(check, abp, raw, get_text, get_text_lower, name_table):
    results = []
    DEBUG_MARKERS = [
        b"PrintString", b"PrintText", b"PrintWarning",
        b"DrawDebugLine", b"DrawDebugBox", b"DrawDebugSphere",
        b"DrawDebugPoint", b"DrawDebugArrow", b"DrawDebugString",
        b"DrawDebugCapsule", b"DrawDebugCylinder",
    ]
    found = [m.decode() for m in DEBUG_MARKERS if m in raw]
    if found:
        results.append(ScanResult(
            check_code=check.code, severity=check.severity.value,
            animblueprint=abp.name, asset_path=abp.asset_path,
            description=f"{check.description} Found: {', '.join(found[:3])}",
            node_hint=f"Debug nodes: {', '.join(found[:3])} — remove before shipping",
            auto_fixable=check.auto_fixable, asset_type=abp.asset_type))
    return results

@check_handler("BP_CONSTRUCT_HEAVY")
def _check_bp_construct_heavy(check, abp, raw, get_text, get_text_lower, name_table):
    results = []
    if b"UserConstructionScript" in raw:
        HEAVY_OPS = [
            b"SpawnActorFromClass", b"SpawnActor",
            b"GetAllActorsOfClass", b"GetAllActorsWithTag",
            b"DestroyActor", b"DestroyComponent",
            b"AddComponentByClass",
        ]
        found = [op.decode() for op in HEAVY_OPS if op in raw]
        if found:
            results.append(ScanResult(
                check_code=check.code, severity=check.severity.value,
                animblueprint=abp.name, asset_path=abp.asset_path,
                description=f"{check.description} Found: {', '.join(found[:3])}",
                node_hint=f"Construction Script + {found[0]} — causes editor freezes",
                auto_fixable=check.auto_fixable, asset_type=abp.asset_type))
    return results

@check_handler("BP_FOREACH_PERF")
def _check_bp_foreach_perf(check, abp, raw, get_text, get_text_lower, name_table):
    results = []
    if b"ForEachLoop" in raw or b"ForEachLoopWithBreak" in raw:
        PURE_QUERIES = [
            b"GetComponentsByClass", b"GetAllActorsOfClass",
            b"GetComponentsByTag", b"GetAllActorsWithTag",
        ]
        found = [q.decode() for q in PURE_QUERIES if q in raw]
        if found:
            results.append(ScanResult(
                check_code=check.code, severity=check.severity.value,
                animblueprint=abp.name, asset_path=abp.asset_path,
                description=f"{check.description} ForEach + {', '.join(found[:2])}",
                node_hint=f"ForEachLoop re-evaluates {found[0]} every iteration — cache the array",
                auto_fixable=check.auto_fixable, asset_type=abp.asset_type))
    return results

@check_handler("BP_TIMELINE_HEAVY")
def _check_bp_timeline_heavy(check, abp, raw, get_text, get_text_lower, name_table):
    results = []
    timeline_count = raw.count(b"TimelineComponent")
    if timeline_count > 3:
        results.append(ScanResult(
            check_code=check.code, severity=check.severity.value,
            animblueprint=abp.name, asset_path=abp.asset_path,
            description=f"{check.description} {timeline_count} Timeline components.",
            node_hint=f"{timeline_count} hidden tick registrations — consider merging",
            auto_fixable=check.auto_fixable, asset_type=abp.asset_type))
    return results

# Validate all checks have handlers
assert set(_CHECK_HANDLERS.keys()) >= {c.code for c in CHECKS if c.code != "BP_BROKEN_REF"}, \
    f"Missing handlers: {set(c.code for c in CHECKS) - set(_CHECK_HANDLERS.keys())}"

# ─────────────────────────────────────────────────────────────────
#  DATA MODELS
# ─────────────────────────────────────────────────────────────────

@dataclass
class ScanResult:
    check_code: str
    severity: str
    animblueprint: str
    asset_path: str
    description: str
    node_hint: str = ""
    auto_fixable: bool = False
    fixed: bool = False
    asset_type: str = "AnimBP"  # "AnimBP" or "Blueprint"

@dataclass
class AnimBPInfo:
    name: str
    asset_path: str
    file_path: str
    file_size: int
    issues: List[ScanResult] = field(default_factory=list)
    grade: str = "A+"
    scanned: bool = False
    asset_type: str = "AnimBP"  # "AnimBP" or "Blueprint"
    export_count: int = 0       # parsed from header — real object instance count
    import_count: int = 0       # parsed from header — external references

@dataclass
class FixAction:
    """A proposed fix with preview information."""
    check_code: str
    animblueprint: str
    asset_path: str
    file_path: str
    fix_type: str        # "binary_patch", "generated_script", "manual"
    description: str
    preview: str
    script_content: str = ""
    patch_data: Optional[Dict] = None

# ─────────────────────────────────────────────────────────────────
#  UASSET PARSER — Deterministic AnimBP identification
# ─────────────────────────────────────────────────────────────────

UASSET_MAGIC = 0x9E2A83C1

def _read_int32(data: bytes, off: int) -> Tuple[int, int]:
    return struct.unpack_from('<i', data, off)[0], off + 4

def _read_uint32(data: bytes, off: int) -> Tuple[int, int]:
    return struct.unpack_from('<I', data, off)[0], off + 4

def _read_int64(data: bytes, off: int) -> Tuple[int, int]:
    return struct.unpack_from('<q', data, off)[0], off + 8

def _read_uint16(data: bytes, off: int) -> Tuple[int, int]:
    return struct.unpack_from('<H', data, off)[0], off + 2

def _read_fstring(data: bytes, off: int) -> Tuple[str, int]:
    length, off = _read_int32(data, off)
    if length == 0:
        return "", off
    if length < 0:
        byte_len = abs(length) * 2
        if byte_len > len(data) - off:
            raise struct.error("fstring utf16 length out of bounds")
        s = data[off:off + byte_len - 2].decode('utf-16-le', errors='replace')
        return s, off + byte_len
    else:
        if length > len(data) - off:
            raise struct.error("fstring length out of bounds")
        s = data[off:off + length - 1].decode('utf-8', errors='replace')
        return s, off + length

def _parse_name_table(data: bytes, name_offset: int, name_count: int,
                      has_hashes: bool) -> Optional[set]:
    """Parse a UAsset name table from a known offset. Returns set of names or None."""
    if name_offset <= 0 or name_offset >= len(data):
        return None
    names = set()
    noff = name_offset
    for _ in range(name_count):
        if noff >= len(data) - 4:
            break
        name, noff = _read_fstring(data, noff)
        if has_hashes:
            noff += 4  # skip 2x uint16 hashes
        names.add(name)
    return names


def _try_parse_header(data: bytes, legacy_ver: int, ue4_ver: int,
                      extra_skip: int = 0) -> Optional[set]:
    """Attempt to parse from after LicenseeVersion with a given extra_skip.
    Returns set of names on success, None on failure."""
    try:
        off = 8  # after Magic + LegacyFileVersion
        if legacy_ver != -4:
            off += 4  # LegacyUE3Version
        off += 4  # FileVersionUE4
        if legacy_ver <= -8:
            off += 4  # FileVersionUE5
        off += 4  # LicenseeVersion
        off += extra_skip  # version-specific extra bytes

        # Custom versions
        cv_count, off = _read_int32(data, off)
        if cv_count < 0 or cv_count > 10000:
            return None
        for _ in range(cv_count):
            off += 20  # FGuid(16) + int32 version(4)

        # Try with TotalHeaderSize (pre-5.4 format)
        for has_ths in ([False, True] if legacy_ver <= -9 else [True]):
            try:
                toff = off
                if has_ths:
                    _, toff = _read_int32(data, toff)  # TotalHeaderSize
                _, toff = _read_fstring(data, toff)  # FolderName
                _, toff = _read_uint32(data, toff)  # PackageFlags
                nc, toff = _read_int32(data, toff)  # NameCount
                no, toff = _read_int32(data, toff)  # NameOffset

                if nc <= 0 or nc > 500000 or no <= 0 or no >= len(data):
                    continue

                has_hashes = (legacy_ver <= -6 or ue4_ver >= 504)
                names = _parse_name_table(data, no, nc, has_hashes)
                if names and len(names) >= 3:
                    return names
            except (struct.error, IndexError, UnicodeDecodeError):
                continue

        return None
    except (struct.error, IndexError, UnicodeDecodeError, OverflowError):
        return None


def parse_uasset_names(data: bytes) -> Optional[set]:
    """Parse a .uasset file and return its name table as a set of strings.
    Returns None if the file is not a valid .uasset.

    Adaptive parser: handles UE4/5 versions -4 through -9, and auto-probes
    for unknown future versions by testing different header layouts."""
    if len(data) < 40:
        return None

    try:
        tag, off = _read_uint32(data, 0)
        if tag != UASSET_MAGIC:
            return None

        legacy_ver, off = _read_int32(data, off)

        if legacy_ver != -4:
            _, off = _read_int32(data, off)  # LegacyUE3Version

        ue4_ver, off = _read_int32(data, off)

        if legacy_ver <= -8:
            _, off = _read_int32(data, off)  # UE5 version

        _, off = _read_int32(data, off)  # LicenseeVersion

        # Known version-specific extra bytes after LicenseeVersion
        KNOWN_EXTRA = {
            # legacy_ver: extra bytes before custom version container
            -9: 24,  # UE5.4: GUID(16) + two int32s(8)
        }
        extra = KNOWN_EXTRA.get(legacy_ver, 0)

        # Try known layout first
        result = _try_parse_header(data, legacy_ver, ue4_ver, extra)
        if result:
            return result

        # ADAPTIVE PROBING: If known layout failed (future UE version?),
        # try different extra_skip values to find the custom version container.
        # This handles UE5.5+ or any future format changes.
        if legacy_ver < -9:
            for probe_extra in [24, 28, 32, 36, 0, 4, 8, 12, 16, 20, 40, 44, 48]:
                if probe_extra == extra:
                    continue  # already tried
                result = _try_parse_header(data, legacy_ver, ue4_ver, probe_extra)
                if result:
                    return result

        return None

    except (struct.error, IndexError, UnicodeDecodeError, OverflowError):
        return None

def _try_read_export_import_counts(data: bytes, legacy_ver: int, ue4_ver: int,
                                    extra_skip: int = 0) -> Optional[Tuple[int, int]]:
    """Try to read ExportCount and ImportCount from the header.
    Returns (export_count, import_count) or None on failure.
    These fields follow NameCount/NameOffset in the header."""
    try:
        off = 8
        if legacy_ver != -4:
            off += 4
        off += 4  # FileVersionUE4
        if legacy_ver <= -8:
            off += 4  # FileVersionUE5
        off += 4  # LicenseeVersion
        off += extra_skip

        cv_count, off = _read_int32(data, off)
        if cv_count < 0 or cv_count > 10000:
            return None
        for _ in range(cv_count):
            off += 20

        for has_ths in ([False, True] if legacy_ver <= -9 else [True]):
            try:
                toff = off
                if has_ths:
                    _, toff = _read_int32(data, toff)  # TotalHeaderSize
                _, toff = _read_fstring(data, toff)  # FolderName
                _, toff = _read_uint32(data, toff)  # PackageFlags
                nc, toff = _read_int32(data, toff)  # NameCount
                no, toff = _read_int32(data, toff)  # NameOffset

                if nc <= 0 or nc > 500000 or no <= 0 or no >= len(data):
                    continue

                # After NameOffset: try to read ExportCount/ExportOffset/ImportCount/ImportOffset
                # UE4: directly after. UE5: may have SoftObjectPaths (2 int32s) first.
                for soft_skip in [0, 8, 16]:
                    try:
                        eoff = toff + soft_skip
                        ec, eoff = _read_int32(data, eoff)  # ExportCount
                        eo, eoff = _read_int32(data, eoff)  # ExportOffset
                        ic, eoff = _read_int32(data, eoff)  # ImportCount
                        io, eoff = _read_int32(data, eoff)  # ImportOffset

                        # Validate: counts non-negative, offsets within file
                        if (0 <= ec < 100000 and 0 <= eo < len(data) and
                            0 <= ic < 100000 and 0 <= io < len(data)):
                            return (ec, ic)
                    except (struct.error, IndexError):
                        continue
            except (struct.error, IndexError, UnicodeDecodeError):
                continue
        return None
    except (struct.error, IndexError, UnicodeDecodeError, OverflowError):
        return None


def parse_uasset_export_counts(data: bytes) -> Optional[Tuple[int, int]]:
    """Parse a .uasset and return (export_count, import_count).
    Returns None if parsing fails. Uses same adaptive probing as parse_uasset_names."""
    if len(data) < 40:
        return None
    try:
        tag, _ = _read_uint32(data, 0)
        if tag != UASSET_MAGIC:
            return None
        legacy_ver, off = _read_int32(data, 4)
        if legacy_ver != -4:
            off += 4
        ue4_ver, off = _read_int32(data, off)

        KNOWN_EXTRA = {-9: 24}
        extra = KNOWN_EXTRA.get(legacy_ver, 0)

        result = _try_read_export_import_counts(data, legacy_ver, ue4_ver, extra)
        if result:
            return result

        if legacy_ver < -9:
            for probe in [24, 28, 32, 36, 0, 4, 8, 12, 16, 20, 40, 44, 48]:
                if probe == extra:
                    continue
                result = _try_read_export_import_counts(data, legacy_ver, ue4_ver, probe)
                if result:
                    return result
        return None
    except (struct.error, IndexError, OverflowError):
        return None


# ─────────────────────────────────────────────────────────────────
#  SCAN CACHE — SQLite for incremental rescans
# ─────────────────────────────────────────────────────────────────

class ScanCache:
    """Caches scan results per-file using modification timestamps.
    Rescan only reads files that changed since last scan."""

    def __init__(self, project_path: str):
        cache_dir = Path(project_path) / ".animbpdoctor"
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(cache_dir / "scan_cache.db"),
                                  check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS file_cache (
            filepath TEXT PRIMARY KEY,
            mtime_ns INTEGER,
            is_animbp INTEGER,
            results_json TEXT
        )""")
        self.db.commit()
        self._lock = threading.Lock()

    def get_cached(self, filepath: str, current_mtime_ns: int):
        """Returns (is_animbp, results_json) or None on cache miss."""
        with self._lock:
            row = self.db.execute(
                "SELECT mtime_ns, is_animbp, results_json FROM file_cache WHERE filepath=?",
                (filepath,)
            ).fetchone()
        if row and row[0] == current_mtime_ns:
            return (bool(row[1]), row[2])
        return None

    def store(self, filepath: str, mtime_ns: int, is_animbp: bool, results_json: str):
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO file_cache VALUES (?,?,?,?)",
                (filepath, mtime_ns, int(is_animbp), results_json)
            )
            self.db.commit()

    def flush(self):
        with self._lock:
            self.db.commit()

    def close(self):
        self.flush()
        self.db.close()

# ─────────────────────────────────────────────────────────────────
#  SCAN HISTORY — Track grades over time
# ─────────────────────────────────────────────────────────────────

class ScanHistory:
    """Stores scan results over time for trend tracking."""

    def __init__(self):
        self.history_path = Path.home() / ".animbpdoctor" / "scan_history.json"
        self.entries: List[dict] = []
        self.load()

    def load(self):
        try:
            if self.history_path.exists():
                with open(self.history_path, "r", encoding="utf-8") as f:
                    self.entries = json.load(f)
        except (json.JSONDecodeError, IOError):
            self.entries = []

    def save(self):
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            # Keep last 50 entries
            self.entries = self.entries[-50:]
            with open(self.history_path, "w", encoding="utf-8") as f:
                json.dump(self.entries, f, indent=2)
        except (IOError, OSError, PermissionError):
            pass  # Non-critical — don't crash scan completion

    def record(self, project: str, grade: str, animblueprint_count: int,
               errors: int, warnings: int, infos: int, scan_duration: float):
        self.entries.append({
            "timestamp": datetime.now().isoformat(),
            "project": project,
            "grade": grade,
            "animblueprints": animblueprint_count,
            "errors": errors,
            "warnings": warnings,
            "infos": infos,
            "total_issues": errors + warnings + infos,
            "scan_seconds": round(scan_duration, 2),
        })
        self.save()

    def get_previous(self, project: str) -> Optional[dict]:
        """Get the most recent previous scan for this project."""
        matching = [e for e in self.entries if e.get("project") == project]
        if len(matching) >= 2:
            return matching[-2]
        return None

# ─────────────────────────────────────────────────────────────────
#  BACKUP MANAGER — Safe file modification with revert
# ─────────────────────────────────────────────────────────────────

class BackupManager:
    """Manages file backups for safe auto-fix and template operations.
    Every file modified by AnimBP Doctor is backed up first.
    Users can revert individual files or all changes at once."""

    def __init__(self, project_path: str):
        self.backup_dir = Path(project_path) / ".animbpdoctor" / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.backup_dir / "manifest.json"
        self.entries: List[dict] = []
        self._load_manifest()

    def _load_manifest(self):
        try:
            if self.manifest_path.exists():
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    self.entries = json.load(f)
        except (json.JSONDecodeError, IOError):
            self.entries = []

    def _save_manifest(self):
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, indent=2)

    def backup_file(self, filepath: str, fix_description: str) -> str:
        """Create a backup copy before modification. Returns backup path."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        fname = Path(filepath).name
        backup_path = str(self.backup_dir / f"{timestamp}_{fname}")
        shutil.copy2(filepath, backup_path)
        self.entries.append({
            "original": filepath,
            "backup": backup_path,
            "timestamp": datetime.now().isoformat(),
            "fix": fix_description,
        })
        self._save_manifest()
        return backup_path

    def revert_all(self) -> List[str]:
        """Revert ALL backed-up files to their original state."""
        reverted = []
        for entry in reversed(self.entries):
            backup = entry["backup"]
            original = entry["original"]
            if os.path.exists(backup):
                shutil.copy2(backup, original)
                os.remove(backup)
                reverted.append(original)
        self.entries.clear()
        self._save_manifest()
        return reverted

    def revert_file(self, filepath: str) -> bool:
        """Revert a single file to its pre-fix state."""
        matching = [e for e in self.entries if e["original"] == filepath]
        if not matching:
            return False
        latest = matching[-1]
        if os.path.exists(latest["backup"]):
            shutil.copy2(latest["backup"], filepath)
            os.remove(latest["backup"])
            self.entries.remove(latest)
            self._save_manifest()
            return True
        return False

    def get_backup_count(self) -> int:
        return len(self.entries)

    def get_backup_summary(self) -> List[dict]:
        return list(reversed(self.entries))

    def cleanup_old(self, max_backups: int = 50):
        """Remove oldest backups if over limit."""
        while len(self.entries) > max_backups:
            oldest = self.entries.pop(0)
            try:
                os.remove(oldest["backup"])
            except OSError:
                pass
        self._save_manifest()

# ─────────────────────────────────────────────────────────────────
#  PROJECT CONFIG — Directory & variable mapping
# ─────────────────────────────────────────────────────────────────

class ProjectConfig:
    """Project-specific configuration for directory layout, variable mapping,
    naming conventions, and auto-fix behavior. Persists to .animbpdoctor/project.json."""

    def __init__(self, project_path: str):
        self.project_path = project_path
        self.config_path = Path(project_path) / ".animbpdoctor" / "project.json"
        self.data = self._defaults()
        self.load()

    def _defaults(self) -> dict:
        return {
            "version": "1.0",
            "directories": {
                "skeletal_meshes": ["Content/Characters", "Content/Meshes"],
                "animations": ["Content/Animations", "Content/Characters"],
                "montages": ["Content/Animations/Montages"],
                "animbps": ["Content/Characters", "Content/Animations"],
                "blend_spaces": ["Content/Animations/BlendSpaces"],
            },
            "variable_mapping": {
                "speed": "Speed",
                "direction": "Direction",
                "is_falling": "bIsFalling",
                "is_crouching": "bIsCrouching",
            },
            "naming_conventions": {
                "animbp_prefix": "ABP_",
                "montage_prefix": "AM_",
                "blend_space_prefix": "BS_",
                "skeletal_mesh_prefix": "SK_",
                "animation_prefix": "A_",
            },
            "auto_fix": {
                "create_backups": True,
                "max_backups": 50,
                "auto_clamp_weights": True,
            },
        }

    def load(self):
        try:
            if self.config_path.exists():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._deep_merge(self.data, saved)
        except (json.JSONDecodeError, IOError):
            pass

    def save(self):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def _deep_merge(self, base: dict, override: dict):
        for key, val in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(val, dict):
                self._deep_merge(base[key], val)
            else:
                base[key] = val

    def get(self, *keys, default=None):
        """Get nested config value. e.g., config.get('directories', 'animbps')"""
        d = self.data
        for k in keys:
            if isinstance(d, dict):
                d = d.get(k)
                if d is None:
                    return default
            else:
                return default
        return d

    def set_val(self, keys: List[str], value):
        """Set a nested config value."""
        d = self.data
        for k in keys[:-1]:
            if k not in d or not isinstance(d[k], dict):
                d[k] = {}
            d = d[k]
        d[keys[-1]] = value
        self.save()

# ─────────────────────────────────────────────────────────────────
#  SCANNER ENGINE
# ─────────────────────────────────────────────────────────────────

class ScannerEngine:
    """Discovers and scans AnimBlueprint assets in a UE5 project.

    Performance optimizations:
    - Name-based pre-filter skips 90%+ of files without any I/O
    - Single-pass: discover + scan in one file read (no double-read)
    - os.scandir for fast directory walking (avoids stat overhead)
    - Skips known non-AnimBP directories (Plugins metadata, etc.)
    - Concurrent scanning via ThreadPoolExecutor
    - Lazy string extraction only when needed per-check
    """

    # Directories that never contain AnimBPs — skip entirely
    SKIP_DIRS = frozenset({
        "__ExternalActors__", "__ExternalObjects__", "Developers",
        "Collections", "EditorResources", "Localization", "Splash",
        "Maps", "Movies", "Slate", "Fonts", "Icons", "LevelPrototyping",
    })

    # Name prefixes that strongly indicate AnimBPs (skip binary read)
    ANIMBP_PREFIXES = ("ABP_", "Ab_", "AnimBP_", "abp_", "ab_", "animbp_")

    # Name prefixes that are definitely NOT Blueprints — skip immediately
    # Note: BP_ is intentionally NOT in this list (general Blueprints are scanned)
    NOT_BP_PREFIXES = (
        "SM_", "SK_", "T_", "M_", "MI_", "MF_", "MM_", "MT_",
        "WBP_", "W_", "DA_", "DT_", "E_", "EUW_",
        "S_", "SB_", "NS_", "NE_", "PA_", "PS_", "PC_",
        "GI_", "EXO_", "HLOD", "BS_",
    )

    # Max file size to read (50MB) — skip oversized/corrupt files
    MAX_FILE_SIZE = 50 * 1024 * 1024

    # IoStore / Zen package magic (UE5 cooked packages use this)
    IOSTORE_MAGIC = 0xC1832A9E  # reversed UASSET_MAGIC seen in .ucas containers

    def __init__(self):
        self.animblueprints: List[AnimBPInfo] = []
        self.results: List[ScanResult] = []
        self.project_path: Optional[str] = None
        self.on_progress = None  # callback(current, total, message)
        self.on_complete = None  # callback(results)
        self.cancelled = False  # set True to abort scan
        self._files_checked = 0
        self._files_skipped = 0
        self._cache: Optional[ScanCache] = None
        self.scan_duration: float = 0.0

    def discover_project(self, path: str) -> bool:
        self.project_path = path
        uproject_files = list(Path(path).glob("*.uproject"))
        content_path = Path(path) / "Content"
        is_ue_project = len(uproject_files) > 0 or content_path.exists()
        if not is_ue_project:
            # Check one level up — user may have selected Content/ directly
            parent = Path(path).parent
            if list(parent.glob("*.uproject")):
                self.project_path = str(parent)
                return True
        return is_ue_project

    def scan_all(self, path: str) -> List[ScanResult]:
        """Single-pass: discover AnimBPs and scan them in one read each."""
        scan_start = time.monotonic()
        self.results = []
        self.animblueprints = []
        self._files_checked = 0
        self._files_skipped = 0

        # Initialize scan cache for incremental rescans
        try:
            self._cache = ScanCache(path)
        except (OSError, sqlite3.Error):
            self._cache = None

        content_path = Path(path) / "Content"
        if not content_path.exists():
            content_path = Path(path)

        # Phase 1: Fast file enumeration with pre-filtering
        candidates = self._enumerate_candidates(content_path, path)

        if self.on_progress:
            self.on_progress(0, len(candidates),
                f"Found {len(candidates)} candidates (skipped {self._files_skipped})")

        # Phase 2: Parallel discover + scan (single read per file)
        # Batched submission to limit memory on huge projects (10K+ files)
        num_workers = min(8, max(2, multiprocessing.cpu_count()))
        last_progress = time.monotonic()
        BATCH_SIZE = 500  # submit in batches to avoid holding 10K+ futures in memory
        total = len(candidates)
        processed = 0

        with ThreadPoolExecutor(max_workers=num_workers) as pool:
            for batch_start in range(0, total, BATCH_SIZE):
                if self.cancelled:
                    break
                batch = candidates[batch_start:batch_start + BATCH_SIZE]
                futures = {
                    pool.submit(self._discover_and_scan, fp, path): fp
                    for fp in batch
                }
                for future in as_completed(futures):
                    if self.cancelled:
                        # Cancel remaining futures in this batch
                        for f in futures:
                            f.cancel()
                        break
                    self._files_checked += 1
                    processed += 1
                    now = time.monotonic()
                    if self.on_progress and (now - last_progress) > 0.1:
                        last_progress = now
                        abp_count = len(self.animblueprints)
                        self.on_progress(processed, total,
                            f"Scanning: {processed}/{total} ({abp_count} Blueprints found)")
                    try:
                        result = future.result()
                    except Exception:
                        result = None
                    if result is not None:
                        abp, issues = result
                        self.animblueprints.append(abp)
                        self.results.extend(issues)

        # Flush cache
        if self._cache:
            try:
                self._cache.flush()
                self._cache.close()
            except sqlite3.Error:
                pass

        # Phase 3: Post-scan cross-reference checks (circular deps)
        self._detect_circular_deps()

        # Phase 4: Calculate grades
        for abp in self.animblueprints:
            abp.grade = self._calculate_grade(abp)
            abp.scanned = True

        self.scan_duration = time.monotonic() - scan_start

        self.animbp_count = sum(1 for a in self.animblueprints if a.asset_type == "AnimBP")
        self.bp_count = sum(1 for a in self.animblueprints if a.asset_type == "Blueprint")
        animbp_count = self.animbp_count
        bp_count = self.bp_count

        if self.on_progress:
            self.on_progress(len(candidates), len(candidates),
                f"Done: {animbp_count} AnimBPs + {bp_count} BPs, "
                f"{len(self.results)} issues in {self.scan_duration:.1f}s")

        if self.on_complete:
            self.on_complete(self.results)

        return self.results

    def _enumerate_candidates(self, content_path: Path, project_path: str) -> List[str]:
        """Fast directory walk with aggressive pre-filtering.
        Returns only file paths worth reading."""
        candidates = []

        for root, dirs, files in os.walk(content_path):
            # Prune directories we know can't contain AnimBPs
            dirs[:] = [d for d in dirs if d not in self.SKIP_DIRS
                       and not d.startswith(".")]

            for fname in files:
                if not fname.endswith(".uasset"):
                    continue

                stem = fname[:-7]  # strip .uasset

                # Fast reject: if name starts with known non-Blueprint prefix, skip
                if stem.startswith(self.NOT_BP_PREFIXES):
                    self._files_skipped += 1
                    continue

                # Fast accept by name, or keep as candidate for binary check
                candidates.append(os.path.join(root, fname))

        return candidates

    def _discover_and_scan(self, filepath: str, project_path: str):
        """Single-pass: read file once, check if AnimBP, scan if yes.
        Returns (AnimBPInfo, List[ScanResult]) or None."""
        if self.cancelled:
            return None

        try:
            stat = os.stat(filepath)
            file_size = stat.st_size
            mtime_ns = int(stat.st_mtime_ns)
        except OSError:
            return None

        # Skip files that are too large (likely not AnimBPs, or corrupt)
        if file_size > self.MAX_FILE_SIZE:
            return None

        # Skip zero-byte / tiny files (corrupt or placeholder)
        if file_size < 40:
            return None

        # Check cache first — skip file read entirely if unchanged
        if self._cache:
            try:
                cached = self._cache.get_cached(filepath, mtime_ns)
                if cached is not None:
                    is_animbp, results_json = cached
                    if not is_animbp:
                        return None
                    return self._rebuild_from_cache(filepath, project_path,
                                                    file_size, results_json)
            except sqlite3.Error:
                pass

        # Cache miss — read and analyze
        try:
            with open(filepath, "rb") as f:
                data = f.read()
        except (IOError, OSError, PermissionError):
            return None

        # Detect IoStore/Zen packages (cooked UE5 format — not parseable as .uasset)
        if len(data) >= 4:
            try:
                magic = struct.unpack_from('<I', data, 0)[0]
                if magic == self.IOSTORE_MAGIC or magic == 0x00000000:
                    return None  # IoStore container or null file
            except struct.error:
                return None

        stem = Path(filepath).stem

        # Try proper .uasset parser first for deterministic identification
        name_table = parse_uasset_names(data)
        is_animbp = False
        is_general_bp = False
        if name_table is not None:
            is_animbp = "AnimBlueprintGeneratedClass" in name_table
            if not is_animbp:
                is_general_bp = "BlueprintGeneratedClass" in name_table
        else:
            # Fallback to heuristic for non-standard formats
            is_animbp = self._is_animbp_from_data(data, stem)
            if not is_animbp:
                is_general_bp = self._is_bp_from_data(data, stem)

        if not is_animbp and not is_general_bp:
            # Cache as non-Blueprint so we skip it next time
            if self._cache:
                try:
                    self._cache.store(filepath, mtime_ns, False, "[]")
                except sqlite3.Error:
                    pass
            return None

        asset_type = "AnimBP" if is_animbp else "Blueprint"

        # It's a Blueprint — build info
        try:
            rel_path = os.path.relpath(filepath, project_path)
        except ValueError:
            rel_path = filepath
        normalized = rel_path.replace(os.sep, '/')
        if normalized.startswith('Content/'):
            normalized = normalized[len('Content/'):]
        asset_path = f"/Game/{normalized.replace('.uasset', '')}"

        # Parse export/import counts for higher-fidelity checks
        export_count, import_count = 0, 0
        counts = parse_uasset_export_counts(data)
        if counts:
            export_count, import_count = counts

        abp = AnimBPInfo(
            name=stem,
            asset_path=asset_path,
            file_path=filepath,
            file_size=file_size,
            asset_type=asset_type,
            export_count=export_count,
            import_count=import_count,
        )

        # Run checks — use name table if available for higher precision
        # Route to correct check set based on asset type
        issues = self._scan_from_data(abp, data, name_table, is_general_bp=is_general_bp)
        abp.issues = issues

        # Cache the results
        if self._cache:
            try:
                results_json = json.dumps([{
                    "check_code": r.check_code, "severity": r.severity,
                    "description": r.description, "node_hint": r.node_hint,
                    "auto_fixable": r.auto_fixable,
                    "asset_type": r.asset_type,
                } for r in issues])
                self._cache.store(filepath, mtime_ns, True, results_json)
            except (sqlite3.Error, TypeError):
                pass

        return (abp, issues)

    def _rebuild_from_cache(self, filepath, project_path, file_size, results_json):
        """Reconstruct AnimBPInfo and results from cached data."""
        stem = Path(filepath).stem
        try:
            rel_path = os.path.relpath(filepath, project_path)
        except ValueError:
            rel_path = filepath
        normalized = rel_path.replace(os.sep, '/')
        if normalized.startswith('Content/'):
            normalized = normalized[len('Content/'):]
        asset_path = f"/Game/{normalized.replace('.uasset', '')}"

        # Infer asset_type from cached issues
        _cached_type = "AnimBP"
        try:
            _ci = json.loads(results_json)
            if _ci and isinstance(_ci, list) and len(_ci) > 0:
                _cached_type = _ci[0].get("asset_type", "AnimBP")
        except (json.JSONDecodeError, KeyError, IndexError):
            pass
        abp = AnimBPInfo(name=stem, asset_path=asset_path,
                        file_path=filepath, file_size=file_size,
                        asset_type=_cached_type)
        try:
            cached_issues = json.loads(results_json)
            issues = [ScanResult(
                check_code=r["check_code"], severity=r["severity"],
                animblueprint=stem, asset_path=asset_path,
                description=r["description"], node_hint=r.get("node_hint", ""),
                auto_fixable=r.get("auto_fixable", False),
                asset_type=r.get("asset_type", "AnimBP"),
            ) for r in cached_issues]
        except (json.JSONDecodeError, KeyError):
            issues = []

        abp.issues = issues
        return (abp, issues)

    def _is_animbp_from_data(self, data: bytes, stem: str) -> bool:
        """Check if binary data belongs to an AnimBP. Reads from already-loaded bytes."""
        # Strong name match — skip expensive binary scan
        if stem.startswith(self.ANIMBP_PREFIXES):
            return True

        # Binary marker scoring — check header region only (faster on large files)
        header = data[:8192] if len(data) > 8192 else data
        score = 0

        if b"AnimBlueprint" in header:
            score += 3
        if b"AnimBlueprintGeneratedClass" in header:
            score += 3
        if b"AnimGraphNode_" in header:
            score += 2
        if b"AnimInstance" in header:
            score += 1

        return score >= 3

    def _is_bp_from_data(self, data: bytes, stem: str) -> bool:
        """Check if binary data belongs to a general Blueprint (not AnimBP)."""
        if stem.startswith(("BP_", "bp_")):
            # Likely a Blueprint by naming convention — verify with binary check
            header = data[:8192] if len(data) > 8192 else data
            if b"BlueprintGeneratedClass" in header:
                return True
            if b"Blueprint" in header and b"K2Node" in header:
                return True
        # Binary marker scoring for non-BP_ prefixed files
        header = data[:8192] if len(data) > 8192 else data
        score = 0
        if b"BlueprintGeneratedClass" in header:
            score += 3
        if b"K2Node_" in header:
            score += 2
        if b"EventGraph" in header:
            score += 1
        if b"EdGraph" in header:
            score += 1
        return score >= 4

    # Check codes that apply to AnimBPs only
    _ANIMBP_CHECK_CODES = frozenset({
        "NULL_ANIM_REF", "BROKEN_BLEND_WT", "SKEL_MISMATCH", "MISSING_SLOT",
        "BROKEN_TRANS", "TPOSE_FALLBACK", "ORPHANED_NODE", "INVALID_BSPACE",
        "MISSING_NOTIFY", "DUP_SLOT",
    })
    # Check codes that apply to general BPs only
    _BP_CHECK_CODES = frozenset({
        "BP_BROKEN_REF", "BP_COMPLEXITY", "BP_EMPTY_GRAPH", "BP_TICK_HEAVY",
        "BP_SELF_CAST", "BP_DEPRECATED_FUNC", "BP_CIRCULAR_DEP", "BP_MASSIVE_ASSET",
        "BP_HARD_REF", "BP_EXPENSIVE_TICK", "BP_DEBUG_NODES",
        "BP_CONSTRUCT_HEAVY", "BP_FOREACH_PERF", "BP_TIMELINE_HEAVY",
    })
    # Check codes that apply to both types
    _SHARED_CHECK_CODES = frozenset({
        "UNUSED_VAR", "DEPRECATED_NODE",
    })

    def _scan_from_data(self, abp: AnimBPInfo, data: bytes,
                        name_table: Optional[set] = None,
                        is_general_bp: bool = False) -> List[ScanResult]:
        """Run appropriate checks using already-loaded binary data."""
        issues = []
        # Only extract strings if a check actually needs it (lazy)
        _text_cache = [None]
        _text_lower_cache = [None]

        def get_text():
            if _text_cache[0] is None:
                _text_cache[0] = _extract_strings(data)
            return _text_cache[0]

        def get_text_lower():
            if _text_lower_cache[0] is None:
                _text_lower_cache[0] = get_text().lower()
            return _text_lower_cache[0]

        for check in CHECKS:
            # Route checks to the correct asset type
            if is_general_bp:
                if check.code in self._ANIMBP_CHECK_CODES:
                    continue  # Skip AnimBP-only checks for general BPs
            else:
                if check.code in self._BP_CHECK_CODES:
                    continue  # Skip general BP checks for AnimBPs
            check_issues = self._run_check(check, abp, data, get_text, get_text_lower, name_table)
            issues.extend(check_issues)

        return issues

    def _run_check(self, check: CheckDefinition, abp: AnimBPInfo,
                   raw: bytes, get_text, get_text_lower,
                   name_table: Optional[set] = None) -> List[ScanResult]:
        """Dispatch check to registered handler. Special cases handled inline."""

        # BP_BROKEN_REF needs self.project_path — handle specially
        if check.code == "BP_BROKEN_REF":
            return self._check_bp_broken_ref(check, abp, raw, name_table)

        # BP_CIRCULAR_DEP stores data on self — handle specially
        if check.code == "BP_CIRCULAR_DEP":
            if name_table is not None:
                refs = {n for n in name_table if n.startswith("/Game/") and "/" in n[6:]}
                refs = {r for r in refs if "/Script/" not in r and r != abp.asset_path}
                if refs:
                    if not hasattr(self, '_bp_references'):
                        self._bp_references = {}
                    self._bp_references[abp.asset_path] = refs
            return []

        # All other checks: dispatch to handler registry
        handler = _CHECK_HANDLERS.get(check.code)
        if handler is not None:
            return handler(check, abp, raw, get_text, get_text_lower, name_table)
        return []

    def _check_bp_broken_ref(self, check, abp, raw, name_table):
        """BP_BROKEN_REF: cross-check /Game/ paths against filesystem."""
        results = []
        if name_table is not None and self.project_path:
            content_dir = os.path.join(self.project_path, "Content")
            broken = []
            for name in name_table:
                if not name.startswith("/Game/"):
                    continue
                rel = name[len("/Game/"):]
                if not rel or "/" not in rel:
                    continue
                disk_path = os.path.join(content_dir, rel.replace("/", os.sep) + ".uasset")
                if not os.path.exists(disk_path):
                    if not os.path.exists(os.path.join(content_dir, rel.replace("/", os.sep))):
                        broken.append(name)
            broken = [b for b in broken
                      if "/Script/" not in b
                      and not b.endswith("_C")
                      and "_C:" not in b
                      and "Default__" not in b
                      and not (b.split("/")[-1].count(".") == 1
                               and b.split("/")[-1].split(".")[0] == b.split("/")[-1].split(".")[1])]
            if broken:
                results.append(ScanResult(
                    check_code=check.code, severity=check.severity.value,
                    animblueprint=abp.name, asset_path=abp.asset_path,
                    description=f"{check.description} {len(broken)} broken reference(s).",
                    node_hint=f"Missing: {', '.join(broken[:3])}{'...' if len(broken) > 3 else ''}",
                    auto_fixable=check.auto_fixable, asset_type=abp.asset_type))
        return results

    # ── End of check dispatch — 600-line if/elif chain replaced by _CHECK_HANDLERS ──


    def _calculate_grade(self, abp: AnimBPInfo) -> str:
        """Calculate A-F health grade for an AnimBP."""
        errors   = sum(1 for i in abp.issues if i.severity == "ERROR")
        warnings = sum(1 for i in abp.issues if i.severity == "WARNING")
        infos    = sum(1 for i in abp.issues if i.severity == "INFO")

        score = 100 - (errors * 25) - (warnings * 10) - (infos * 3)
        score = max(0, min(100, score))

        if score >= 95: return "A+"
        if score >= 90: return "A"
        if score >= 80: return "B"
        if score >= 65: return "C"
        if score >= 50: return "D"
        return "F"

    def _detect_circular_deps(self):
        """Post-scan: detect direct circular dependencies between Blueprints."""
        if not hasattr(self, '_bp_references') or not self._bp_references:
            return
        refs = self._bp_references
        check = CHECK_MAP.get("BP_CIRCULAR_DEP")
        if not check:
            return
        # Build a lookup of known asset paths
        known_assets = {abp.asset_path for abp in self.animblueprints}
        reported = set()
        for src_path, src_refs in refs.items():
            for ref in src_refs:
                # Skip self-references (A references itself is not a circular dep)
                if ref == src_path:
                    continue
                if ref in refs and src_path in refs[ref]:
                    pair = tuple(sorted([src_path, ref]))
                    if pair not in reported and ref in known_assets:
                        reported.add(pair)
                        # Find the source ABP
                        src_abp = next((a for a in self.animblueprints
                                        if a.asset_path == src_path), None)
                        if src_abp:
                            result = ScanResult(
                                check_code=check.code,
                                severity=check.severity.value,
                                animblueprint=src_abp.name,
                                asset_path=src_abp.asset_path,
                                description=f"{check.description} {src_path} <-> {ref}",
                                node_hint=f"Circular: {src_path} references {ref} and vice versa",
                                auto_fixable=False,
                                asset_type=src_abp.asset_type,
                            )
                            self.results.append(result)
                            src_abp.issues.append(result)
        # Clean up temp data
        self._bp_references = {}

    def get_overall_grade(self) -> str:
        if not self.animblueprints:
            return "--"
        total_errors   = sum(1 for r in self.results if r.severity == "ERROR")
        total_warnings = sum(1 for r in self.results if r.severity == "WARNING")
        total_infos    = sum(1 for r in self.results if r.severity == "INFO")
        total_abps     = len(self.animblueprints)

        # Score based on issues-per-AnimBP ratio
        issues_ratio = (total_errors * 3 + total_warnings * 1.5 + total_infos * 0.5) / max(total_abps, 1)
        score = max(0, min(100, 100 - issues_ratio * 15))

        if score >= 95: return "A+"
        if score >= 90: return "A"
        if score >= 80: return "B"
        if score >= 65: return "C"
        if score >= 50: return "D"
        return "F"

# ─────────────────────────────────────────────────────────────────
#  FIX ENGINE — Generate and execute fixes with backup
# ─────────────────────────────────────────────────────────────────

class FixEngine:
    """Generates preview-able fix actions and executes them with backup.

    Two fix modes:
      - binary_patch:      Direct .uasset modification (e.g. blend weight clamp).
                           Original file is backed up first.
      - generated_script:  Writes a UE5 Python/C++ script for the user to run
                           inside the editor (for changes that need graph access).
    """

    def __init__(self, scanner: ScannerEngine):
        self.scanner = scanner
        self.backup_mgr: Optional[BackupManager] = None

    def generate_fix_actions(self, results: List[ScanResult]) -> List[FixAction]:
        """Build a list of proposed actions (for the preview window)."""
        actions = []
        for r in results:
            action = self._generate_action(r)
            if action:
                actions.append(action)
        return actions

    def _generate_action(self, result: ScanResult) -> Optional[FixAction]:
        file_path = self._find_file(result.animblueprint) or ""
        if result.check_code == "BROKEN_BLEND_WT" and result.auto_fixable:
            return self._action_blend_weight(result, file_path)
        elif result.check_code == "MISSING_SLOT" and result.auto_fixable:
            return self._action_missing_slot(result, file_path)
        elif result.check_code == "BP_DEBUG_NODES" and result.auto_fixable:
            return self._action_remove_debug_nodes(result, file_path)
        elif result.check_code == "BP_SELF_CAST" and result.auto_fixable:
            return self._action_remove_self_cast(result, file_path)
        elif result.check_code == "TPOSE_FALLBACK" and result.auto_fixable:
            return self._action_fix_tpose(result, file_path)
        elif result.check_code == "DUP_SLOT" and result.auto_fixable:
            return self._action_fix_dup_slot(result, file_path)
        elif result.check_code == "BP_CONSTRUCT_HEAVY" and result.auto_fixable:
            return self._action_fix_construct(result, file_path)
        elif result.check_code == "BP_TIMELINE_HEAVY" and result.auto_fixable:
            return self._action_fix_timeline(result, file_path)
        elif result.auto_fixable:
            return self._action_generic_script(result, file_path)
        else:
            return FixAction(
                check_code=result.check_code,
                animblueprint=result.animblueprint,
                asset_path=result.asset_path,
                file_path=file_path,
                fix_type="manual",
                description=f"Manual fix required: {result.check_code}",
                preview=(f"MANUAL FIX: {result.animblueprint}\n"
                         f"  Issue: {result.description}\n"
                         f"  Action: See step-by-step guide in detail panel"),
            )

    # ── Blend Weight Clamp (binary patch) ──

    def _action_blend_weight(self, result: ScanResult, file_path: str) -> FixAction:
        match = re.search(r'(?:weight|Weight)[:\s=]+([-\d.]+)', result.description)
        bad_value = float(match.group(1)) if match else None
        if bad_value is None:
            return FixAction(
                check_code=result.check_code,
                animblueprint=result.animblueprint,
                asset_path=result.asset_path,
                file_path=file_path,
                fix_type="manual",
                description="Could not parse blend weight value — manual fix required",
                preview=f"MANUAL FIX: {result.animblueprint}\n  {result.description}",
            )
        clamped = max(0.0, min(1.0, bad_value))
        return FixAction(
            check_code=result.check_code,
            animblueprint=result.animblueprint,
            asset_path=result.asset_path,
            file_path=file_path,
            fix_type="binary_patch",
            description=f"Clamp BlendWeight {bad_value:.3f} -> {clamped:.3f}",
            preview=(f"BINARY PATCH: {result.animblueprint}\n"
                     f"  File: {os.path.basename(file_path)}\n"
                     f"  Action: Clamp float {bad_value:.3f} -> {clamped:.3f}\n"
                     f"  Safety: Original backed up before write"),
            patch_data={
                "type": "float_replace",
                "search_marker": "BlendWeight",
                "old_value": bad_value,
                "new_value": clamped,
            },
        )

    # ── Missing Slot (generated UE5 script) ──

    def _action_missing_slot(self, result: ScanResult, file_path: str) -> FixAction:
        script = textwrap.dedent(f"""\
            # AnimBP Doctor — Generated Fix
            # Issue : MISSING_SLOT in {result.animblueprint}
            # Action: Add a DefaultSlot node so montages can play.
            #
            # Paste this into UE5 > Tools > Execute Python Script,
            # or run via Output Log (Python mode).

            import unreal

            abp = unreal.load_asset("{result.asset_path}")
            if abp is None:
                unreal.log_error("AnimBP Doctor: could not load {result.asset_path}")
            else:
                unreal.log("AnimBP Doctor: Add a Slot node manually:")
                unreal.log("  1. Open {result.animblueprint} in editor")
                unreal.log("  2. AnimGraph > right-click > Slot")
                unreal.log("  3. Wire: [Logic] -> [Slot 'DefaultSlot'] -> [Output Pose]")
                unreal.log("  4. Compile (F7)")
        """)
        return FixAction(
            check_code=result.check_code,
            animblueprint=result.animblueprint,
            asset_path=result.asset_path,
            file_path=file_path,
            fix_type="generated_script",
            description="Generate script to add Slot node",
            preview=(f"GENERATED SCRIPT: {result.animblueprint}\n"
                     f"  Action: UE5 Python script to guide Slot node addition\n"
                     f"  Output: Saved to .animbpdoctor/generated_scripts/"),
            script_content=script,
        )

    # ── Remove Debug Nodes (generated script — 99% safe) ──

    def _action_remove_debug_nodes(self, result: ScanResult, file_path: str) -> FixAction:
        script = textwrap.dedent(f"""\
            # BP Doctor — Auto-Fix: Remove Debug Nodes
            # Blueprint: {result.animblueprint}
            # Action: Find and delete all PrintString and DrawDebug nodes.
            # Safety: Debug nodes are never needed in shipping builds.

            import unreal

            bp = unreal.load_asset("{result.asset_path}")
            if bp is None:
                unreal.log_error("BP Doctor: Could not load {result.asset_path}")
            else:
                graphs = unreal.BlueprintEditorLibrary.get_all_graphs(bp)
                removed = 0
                debug_prefixes = ["PrintString", "PrintText", "PrintWarning",
                                  "DrawDebugLine", "DrawDebugBox", "DrawDebugSphere",
                                  "DrawDebugPoint", "DrawDebugArrow", "DrawDebugString"]
                for graph in graphs:
                    for node in list(graph.get_all_nodes()):
                        name = node.get_name()
                        if any(p in name for p in debug_prefixes):
                            graph.remove_node(node)
                            removed += 1
                unreal.BlueprintEditorLibrary.compile_blueprint(bp)
                unreal.log(f"BP Doctor: Removed {{removed}} debug node(s) from {result.animblueprint}")
        """)
        return FixAction(
            check_code=result.check_code,
            animblueprint=result.animblueprint,
            asset_path=result.asset_path, file_path=file_path,
            fix_type="generated_script",
            description="Remove all PrintString/DrawDebug nodes",
            preview=(f"GENERATED SCRIPT: {result.animblueprint}\n"
                     f"  Action: Delete all debug nodes (PrintString, DrawDebug*)\n"
                     f"  Safety: Always safe — debug nodes should never ship"),
            script_content=script)

    # ── Remove Self-Cast (generated script — 99% safe) ──

    def _action_remove_self_cast(self, result: ScanResult, file_path: str) -> FixAction:
        script = textwrap.dedent(f"""\
            # BP Doctor — Auto-Fix: Remove Self-Cast
            # Blueprint: {result.animblueprint}
            # Action: Find Cast nodes that cast to this Blueprint's own class and remove them.
            # Safety: Casting to self always succeeds. The Cast node is pure overhead.

            import unreal

            bp = unreal.load_asset("{result.asset_path}")
            if bp is None:
                unreal.log_error("BP Doctor: Could not load {result.asset_path}")
            else:
                bp_class = bp.generated_class()
                graphs = unreal.BlueprintEditorLibrary.get_all_graphs(bp)
                removed = 0
                for graph in graphs:
                    for node in list(graph.get_all_nodes()):
                        if "DynamicCast" in node.get_class().get_name():
                            # Check if target class matches own class
                            if hasattr(node, 'target_type') and node.target_type == bp_class:
                                graph.remove_node(node)
                                removed += 1
                if removed > 0:
                    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
                unreal.log(f"BP Doctor: Removed {{removed}} self-cast(s) from {result.animblueprint}")
                unreal.log("  Replace with 'Self' reference where the cast output was used.")
        """)
        return FixAction(
            check_code=result.check_code,
            animblueprint=result.animblueprint,
            asset_path=result.asset_path, file_path=file_path,
            fix_type="generated_script",
            description="Remove unnecessary self-cast nodes",
            preview=(f"GENERATED SCRIPT: {result.animblueprint}\n"
                     f"  Action: Delete Cast-to-Self nodes (always succeeds, pure overhead)\n"
                     f"  Safety: Self-casts are guaranteed unnecessary"),
            script_content=script)

    # ── Fix T-Pose Fallback (generated script — reconnect BasePose) ──

    def _action_fix_tpose(self, result: ScanResult, file_path: str) -> FixAction:
        script = textwrap.dedent(f"""\
            # BP Doctor — Auto-Fix: Reconnect LayeredBoneBlend BasePose
            # Blueprint: {result.animblueprint}
            # Action: Find the disconnected BasePose pin and reconnect it.

            import unreal

            bp = unreal.load_asset("{result.asset_path}")
            if bp is None:
                unreal.log_error("BP Doctor: Could not load {result.asset_path}")
            else:
                unreal.log("BP Doctor: Fix T-Pose Fallback in {result.animblueprint}")
                unreal.log("  1. Open {result.animblueprint} in the AnimBP editor")
                unreal.log("  2. Find the 'Layered Blend per Bone' node")
                unreal.log("  3. Check the TOP input pin (BasePose) — it must be connected")
                unreal.log("  4. Wire your main animation output into BasePose")
                unreal.log("  5. Compile (F7) and test all blend scenarios")
        """)
        return FixAction(
            check_code=result.check_code,
            animblueprint=result.animblueprint,
            asset_path=result.asset_path, file_path=file_path,
            fix_type="generated_script",
            description="Reconnect LayeredBoneBlend BasePose input",
            preview=(f"GENERATED SCRIPT: {result.animblueprint}\n"
                     f"  Action: Guide to reconnect disconnected BasePose pin\n"
                     f"  Safety: Fixes the root cause of partial T-pose flashes"),
            script_content=script)

    # ── Fix Duplicate Slot Names (generated script) ──

    def _action_fix_dup_slot(self, result: ScanResult, file_path: str) -> FixAction:
        script = textwrap.dedent(f"""\
            # BP Doctor — Auto-Fix: Rename Duplicate Slot Names
            # Blueprint: {result.animblueprint}
            # Action: Find duplicate Slot nodes and rename with unique suffixes.

            import unreal

            bp = unreal.load_asset("{result.asset_path}")
            if bp is None:
                unreal.log_error("BP Doctor: Could not load {result.asset_path}")
            else:
                unreal.log("BP Doctor: Fix Duplicate Slots in {result.animblueprint}")
                unreal.log("  1. Open {result.animblueprint} in the AnimBP editor")
                unreal.log("  2. Press Ctrl+F, search 'Slot'")
                unreal.log("  3. Give each Slot a unique name:")
                unreal.log("     - DefaultSlot (full body)")
                unreal.log("     - UpperBody (torso + arms)")
                unreal.log("     - LowerBody (legs)")
                unreal.log("     - Face (facial animations)")
                unreal.log("  4. Update PlayMontage() calls to use new slot names")
                unreal.log("  5. Compile (F7)")
        """)
        return FixAction(
            check_code=result.check_code,
            animblueprint=result.animblueprint,
            asset_path=result.asset_path, file_path=file_path,
            fix_type="generated_script",
            description="Rename duplicate Slot nodes with unique names",
            preview=(f"GENERATED SCRIPT: {result.animblueprint}\n"
                     f"  Action: Guide to rename duplicate slots\n"
                     f"  Note: Update PlayMontage() code to match new names"),
            script_content=script)

    # ── Fix Construction Script Misuse (generated script) ──

    def _action_fix_construct(self, result: ScanResult, file_path: str) -> FixAction:
        script = textwrap.dedent(f"""\
            # BP Doctor — Auto-Fix: Move Heavy Logic from Construction Script
            # Blueprint: {result.animblueprint}
            # Action: Move SpawnActor/GetAllActors from Construction Script to BeginPlay.

            import unreal

            bp = unreal.load_asset("{result.asset_path}")
            if bp is None:
                unreal.log_error("BP Doctor: Could not load {result.asset_path}")
            else:
                unreal.log("BP Doctor: Fix Construction Script in {result.animblueprint}")
                unreal.log("  1. Open {result.animblueprint}")
                unreal.log("  2. Go to the Construction Script graph")
                unreal.log("  3. Select the SpawnActor/GetAllActors nodes")
                unreal.log("  4. Cut them (Ctrl+X)")
                unreal.log("  5. Go to Event Graph > Event BeginPlay")
                unreal.log("  6. Paste (Ctrl+V) and rewire")
                unreal.log("  7. Construction Script should only set defaults, not spawn/query")
                unreal.log("  8. Compile (F7) and test in PIE")
        """)
        return FixAction(
            check_code=result.check_code,
            animblueprint=result.animblueprint,
            asset_path=result.asset_path, file_path=file_path,
            fix_type="generated_script",
            description="Move heavy operations from Construction Script to BeginPlay",
            preview=(f"GENERATED SCRIPT: {result.animblueprint}\n"
                     f"  Action: Move SpawnActor/queries to BeginPlay\n"
                     f"  Safety: Prevents editor freezes from Construction Script abuse"),
            script_content=script)

    # ── Fix Timeline Heavy (generated script) ──

    def _action_fix_timeline(self, result: ScanResult, file_path: str) -> FixAction:
        script = textwrap.dedent(f"""\
            # BP Doctor — Auto-Fix: Reduce Timeline Component Overhead
            # Blueprint: {result.animblueprint}
            # Action: Merge or stop idle Timeline components.

            import unreal

            bp = unreal.load_asset("{result.asset_path}")
            if bp is None:
                unreal.log_error("BP Doctor: Could not load {result.asset_path}")
            else:
                unreal.log("BP Doctor: Fix Timeline Overhead in {result.animblueprint}")
                unreal.log("  1. Open {result.animblueprint}")
                unreal.log("  2. Count Timeline nodes — each creates a hidden tick component")
                unreal.log("  3. Merge Timelines that run simultaneously into one")
                unreal.log("  4. For simple A-to-B lerps, replace Timeline with:")
                unreal.log("     FInterpTo + SetTimerByEvent (much lighter)")
                unreal.log("  5. Add Timeline->Stop() when animation completes")
                unreal.log("  6. Compile (F7)")
        """)
        return FixAction(
            check_code=result.check_code,
            animblueprint=result.animblueprint,
            asset_path=result.asset_path, file_path=file_path,
            fix_type="generated_script",
            description="Merge or optimize Timeline components",
            preview=(f"GENERATED SCRIPT: {result.animblueprint}\n"
                     f"  Action: Guide to merge/stop idle Timelines\n"
                     f"  Safety: Reduces hidden tick overhead"),
            script_content=script)

    def _action_generic_script(self, result: ScanResult, file_path: str) -> FixAction:
        script = textwrap.dedent(f"""\
            # AnimBP Doctor — Generated Fix
            # Issue : {result.check_code} in {result.animblueprint}
            # Desc  : {result.description}
            #
            # This issue requires manual editor action.
            # Follow the steps below in the UE5 editor.

            import unreal
            unreal.log("AnimBP Doctor: Fix {result.check_code} in {result.animblueprint}")
            unreal.log("  {result.description}")
        """)
        return FixAction(
            check_code=result.check_code,
            animblueprint=result.animblueprint,
            asset_path=result.asset_path,
            file_path=file_path,
            fix_type="generated_script",
            description=f"Generate fix script for {result.check_code}",
            preview=(f"GENERATED SCRIPT: {result.animblueprint}\n"
                     f"  Issue: {result.check_code}\n"
                     f"  {result.description}"),
            script_content=script,
        )

    # ── Execution ──

    def execute_actions(self, actions: List[FixAction],
                        project_path: str,
                        output_dir: Optional[str] = None
                        ) -> List[Tuple[bool, str]]:
        """Execute a list of fix actions. Returns [(success, message)] per action."""
        if not self.backup_mgr:
            self.backup_mgr = BackupManager(project_path)
        results = []
        for action in actions:
            ok, msg = self._execute_one(action, project_path, output_dir)
            results.append((ok, msg))
        return results

    def _execute_one(self, action: FixAction,
                     project_path: str,
                     output_dir: Optional[str] = None
                     ) -> Tuple[bool, str]:
        if action.fix_type == "binary_patch":
            return self._exec_binary_patch(action)
        elif action.fix_type == "generated_script":
            return self._exec_save_script(action, project_path, output_dir)
        return (False, "Manual fix — see guide")

    def _exec_binary_patch(self, action: FixAction) -> Tuple[bool, str]:
        if not action.file_path or not os.path.isfile(action.file_path):
            return (False, "File not found")
        # Check if file is locked (UE5 may have it open)
        try:
            with open(action.file_path, "r+b") as f:
                pass  # Test write access
        except (PermissionError, OSError):
            return (False, "File is locked — close UE5 Editor before applying binary patches")
        patch = action.patch_data
        if not patch or patch.get("type") != "float_replace":
            return (False, "Unsupported patch type")

        try:
            self.backup_mgr.backup_file(action.file_path, action.description)
        except (IOError, OSError, PermissionError) as e:
            return (False, f"Backup failed (not patching): {e}")

        try:
            with open(action.file_path, "rb") as f:
                data = bytearray(f.read())

            marker = patch["search_marker"].encode() if isinstance(
                patch["search_marker"], str) else patch["search_marker"]
            old_bytes = struct.pack("f", patch["old_value"])
            new_bytes = struct.pack("f", patch["new_value"])

            idx = data.find(marker)
            if idx == -1:
                return (False, f"Marker not found in file")

            region_start = idx + len(marker)
            region_end = min(region_start + 64, len(data))
            patched = False
            for off in range(region_start, region_end - 3):
                if data[off:off + 4] == old_bytes:
                    data[off:off + 4] = new_bytes
                    patched = True
                    break

            if not patched:
                return (False, "Float value not found near marker")

            tmp_path = action.file_path + ".bpd_tmp"
            with open(tmp_path, "wb") as f:
                f.write(data)
            os.replace(tmp_path, action.file_path)

            return (True, f"Patched: {patch['old_value']:.3f} -> {patch['new_value']:.3f}")
        except (IOError, OSError, struct.error) as e:
            if os.path.exists(action.file_path + ".bpd_tmp"):
                try:
                    os.remove(action.file_path + ".bpd_tmp")
                except OSError:
                    pass
            return (False, f"Patch failed: {e}")

    def _exec_save_script(self, action: FixAction,
                          project_path: str,
                          output_dir: Optional[str] = None) -> Tuple[bool, str]:
        if output_dir:
            scripts_dir = Path(output_dir)
        else:
            scripts_dir = Path(project_path) / ".animbpdoctor" / "generated_scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = ".py" if "import unreal" in action.script_content else ".txt"
        fname = f"fix_{action.check_code}_{action.animblueprint}_{ts}{ext}"
        out = scripts_dir / fname
        try:
            with open(out, "w", encoding="utf-8") as f:
                f.write(action.script_content)
            return (True, f"Script saved: {out.name}")
        except (IOError, OSError, PermissionError) as e:
            return (False, f"Failed to save script: {e}")

    def _find_file(self, name: str) -> Optional[str]:
        for abp in self.scanner.animblueprints:
            if abp.name == name:
                return abp.file_path
        return None

# ─────────────────────────────────────────────────────────────────
#  TEMPLATE MANAGER — Reusable Blueprint automation templates
# ─────────────────────────────────────────────────────────────────

class TemplateManager:
    """Manages built-in and user-created AnimBP automation templates.

    Templates are JSON definitions with:
      - Metadata (name, category, description, requirements)
      - Variable declarations (type, default, description)
      - A script_template string with {variable} placeholders

    Users customise variables, the manager renders the final script.
    """

    def __init__(self):
        self.templates: List[dict] = []
        self.user_dir = Path.home() / ".animbpdoctor" / "templates"
        self.user_dir.mkdir(parents=True, exist_ok=True)
        self._load_built_in()
        self._load_user()

    # ── Built-in templates ──

    def _load_built_in(self):
        self.templates = [
            {
                "id": "montage_slot_wiring",
                "name": "Montage Slot Wiring",
                "category": "Animation Setup",
                "description": (
                    "Wire a Slot node into an AnimGraph so montages "
                    "can play. This is the #1 most common AnimBP setup "
                    "step that gets missed."
                ),
                "what_it_does": [
                    "Adds a DefaultSlot node to the AnimGraph",
                    "Wires it between your animation logic and Output Pose",
                    "Ensures PlayMontage() calls work in gameplay code",
                ],
                "when_to_use": (
                    "When you create a new AnimBP and need montages "
                    "(attacks, emotes, interactables)."
                ),
                "requirements": [
                    "An AnimBP with at least one state machine or blend node",
                    "Skeleton must be set on the AnimBP",
                ],
                "variables": {
                    "slot_name": {
                        "type": "string", "default": "DefaultSlot",
                        "description": "Name of the montage slot",
                    },
                    "animblueprint": {
                        "type": "asset_path", "default": "",
                        "description": "Path to the AnimBP (e.g. /Game/Characters/ABP_Hero)",
                    },
                },
                "script_template": textwrap.dedent("""\
                    # AnimBP Doctor Template: Montage Slot Wiring
                    # Slot : {slot_name}
                    # Target: {animblueprint}
                    import unreal

                    abp = unreal.load_asset("{animblueprint}")
                    if abp is None:
                        unreal.log_error("Could not load {animblueprint}")
                    else:
                        unreal.log("=== Montage Slot Wiring ===")
                        unreal.log("1. Open {animblueprint} in the editor")
                        unreal.log("2. AnimGraph > right-click > Slot")
                        unreal.log("3. Set Slot Name = '{slot_name}'")
                        unreal.log("4. Wire: [Logic] -> [Slot] -> [Output Pose]")
                        unreal.log("5. Compile (F7) and save")
                """),
            },
            {
                "id": "skeletal_mesh_link",
                "name": "Skeletal Mesh to AnimBP Link",
                "category": "Animation Setup",
                "description": (
                    "Configure a Skeletal Mesh Component to use a "
                    "specific AnimBlueprint. Verifies skeleton match."
                ),
                "what_it_does": [
                    "Sets the AnimBP class on a Skeletal Mesh Component",
                    "Verifies skeleton compatibility",
                    "Optionally assigns the Skeletal Mesh asset",
                ],
                "when_to_use": "When setting up a character or NPC that needs animation.",
                "requirements": [
                    "An Actor Blueprint with a Skeletal Mesh Component",
                    "An AnimBP targeting the correct skeleton",
                ],
                "variables": {
                    "actor_blueprint": {
                        "type": "asset_path", "default": "",
                        "description": "Path to the Actor BP",
                    },
                    "animblueprint": {
                        "type": "asset_path", "default": "",
                        "description": "Path to the AnimBP to assign",
                    },
                    "skeletal_mesh": {
                        "type": "asset_path", "default": "",
                        "description": "Path to the Skeletal Mesh",
                    },
                    "component_name": {
                        "type": "string", "default": "Mesh",
                        "description": "Skeletal Mesh Component name",
                    },
                },
                "script_template": textwrap.dedent("""\
                    // AnimBP Doctor Template: Skeletal Mesh -> AnimBP Link
                    // Actor : {actor_blueprint}
                    // AnimBP: {animblueprint}
                    // Mesh  : {skeletal_mesh}

                    // --- C++ Constructor / BeginPlay ---
                    // Set AnimBP class on the mesh component:
                    if (USkeletalMeshComponent* SMC = FindComponentByClass<USkeletalMeshComponent>())
                    {{
                        SMC->SetAnimInstanceClass(
                            LoadClass<UAnimInstance>(nullptr,
                                TEXT("{animblueprint}_C")));
                    }}

                    // Set skeletal mesh (if needed):
                    // SMC->SetSkeletalMesh(
                    //     LoadObject<USkeletalMesh>(nullptr,
                    //         TEXT("{skeletal_mesh}")));
                """),
            },
            {
                "id": "blend_space_setup",
                "name": "BlendSpace Configuration",
                "category": "Animation Setup",
                "description": (
                    "Set up a 1D or 2D BlendSpace with axis config "
                    "and sample points for locomotion blending."
                ),
                "what_it_does": [
                    "Configures axis names and ranges",
                    "Maps animation sequences to grid positions",
                    "Provides editor step-by-step instructions",
                ],
                "when_to_use": "Setting up locomotion (walk/run) or directional movement.",
                "requirements": [
                    "At least 2 animation sequences on the same skeleton",
                ],
                "variables": {
                    "blend_space_name": {
                        "type": "string", "default": "BS_Locomotion",
                        "description": "Name for the BlendSpace",
                    },
                    "axis_x_name": {
                        "type": "string", "default": "Speed",
                        "description": "Horizontal axis parameter name",
                    },
                    "axis_x_min": {
                        "type": "string", "default": "0.0",
                        "description": "Axis minimum value",
                    },
                    "axis_x_max": {
                        "type": "string", "default": "600.0",
                        "description": "Axis maximum value",
                    },
                    "idle_anim": {
                        "type": "asset_path", "default": "",
                        "description": "Idle animation (Speed=0)",
                    },
                    "walk_anim": {
                        "type": "asset_path", "default": "",
                        "description": "Walk animation (Speed~200)",
                    },
                    "run_anim": {
                        "type": "asset_path", "default": "",
                        "description": "Run animation (Speed~600)",
                    },
                },
                "script_template": textwrap.dedent("""\
                    # AnimBP Doctor Template: BlendSpace Configuration
                    # Name: {blend_space_name}
                    # Axis: {axis_x_name} [{axis_x_min} - {axis_x_max}]
                    import unreal

                    unreal.log("=== BlendSpace Setup: {blend_space_name} ===")
                    unreal.log("1. Content Browser > Add > Animation > Blend Space 1D")
                    unreal.log("2. Select your Skeleton")
                    unreal.log("3. Name it '{blend_space_name}'")
                    unreal.log("4. Axis: Name='{axis_x_name}', Min={axis_x_min}, Max={axis_x_max}")
                    unreal.log("5. Sample points:")
                    unreal.log("   Position 0.0   : {idle_anim}")
                    unreal.log("   Position 200.0 : {walk_anim}")
                    unreal.log("   Position 600.0 : {run_anim}")
                    unreal.log("6. Save, then use in AnimBP state machine")
                """),
            },
            {
                "id": "state_machine_base",
                "name": "State Machine Setup",
                "category": "Animation Setup",
                "description": (
                    "Base locomotion state machine with Idle, Move, "
                    "Jump/Fall states and transition rules."
                ),
                "what_it_does": [
                    "Defines base states: Idle, Locomotion, Jump, Land",
                    "Provides transition rules for movement and airborne",
                    "Generates AnimInstance C++ variables to drive transitions",
                ],
                "when_to_use": "Creating a new character AnimBP that needs basic movement.",
                "requirements": [
                    "An AnimBP with a skeleton assigned",
                    "Idle, locomotion, jump, and land animations",
                ],
                "variables": {
                    "animblueprint": {
                        "type": "asset_path", "default": "",
                        "description": "Path to the AnimBP",
                    },
                    "speed_var": {
                        "type": "string", "default": "Speed",
                        "description": "Float variable for movement speed",
                    },
                    "is_falling_var": {
                        "type": "string", "default": "bIsFalling",
                        "description": "Bool variable for in-air state",
                    },
                    "walk_threshold": {
                        "type": "string", "default": "5.0",
                        "description": "Speed threshold to leave Idle",
                    },
                },
                "script_template": textwrap.dedent("""\
                    // AnimBP Doctor Template: State Machine Setup
                    // AnimBP: {animblueprint}
                    // Vars  : {speed_var} (float), {is_falling_var} (bool)

                    // === Add to your AnimInstance header (.h) ===
                    UPROPERTY(BlueprintReadOnly, Category = "Movement")
                    float {speed_var} = 0.f;

                    UPROPERTY(BlueprintReadOnly, Category = "Movement")
                    bool {is_falling_var} = false;

                    // === NativeUpdateAnimation (.cpp) ===
                    void UMyAnimInstance::NativeUpdateAnimation(float DeltaSeconds)
                    {{
                        Super::NativeUpdateAnimation(DeltaSeconds);
                        if (APawn* P = TryGetPawnOwner())
                        {{
                            {speed_var} = P->GetVelocity().Size2D();
                            if (ACharacter* C = Cast<ACharacter>(P))
                                {is_falling_var} = C->GetCharacterMovement()->IsFalling();
                        }}
                    }}

                    // === Transition Rules (set in AnimGraph editor) ===
                    // Idle -> Locomotion :  {speed_var} > {walk_threshold}
                    // Locomotion -> Idle :  {speed_var} <= {walk_threshold}
                    // Any -> JumpStart  :  {is_falling_var} == true
                    // JumpStart -> Land :  {is_falling_var} == false
                    // Land -> Idle      :  On Land anim complete (AnimNotify)
                """),
            },
        ]

    def _load_user(self):
        for f in self.user_dir.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    t = json.load(fh)
                if self._validate(t):
                    t["user_created"] = True
                    t["file_path"] = str(f)
                    self.templates.append(t)
            except (json.JSONDecodeError, IOError):
                pass

    @staticmethod
    def _validate(t: dict) -> bool:
        return all(k in t for k in ("id", "name", "description",
                                     "variables", "script_template"))

    def get(self, template_id: str) -> Optional[dict]:
        for t in self.templates:
            if t["id"] == template_id:
                return t
        return None

    def categories(self) -> List[str]:
        return sorted(set(t.get("category", "General") for t in self.templates))

    def render(self, template_id: str, variables: Dict[str, str]) -> Optional[str]:
        """Fill a template's placeholders with user values."""
        t = self.get(template_id)
        if not t:
            return None
        script = t["script_template"]
        for key, val in variables.items():
            script = script.replace(f"{{{key}}}", str(val))
        return script

    def export_script(self, template_id: str, variables: Dict[str, str],
                      output_dir: str) -> Optional[str]:
        """Render and write to disk. Returns path or None."""
        script = self.render(template_id, variables)
        if not script:
            return None
        t = self.get(template_id)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = ".py" if "import unreal" in script else ".cpp"
        fname = f"{t['id']}_{ts}{ext}"
        out = Path(output_dir) / fname
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(script)
        return str(out)

    def save_user_template(self, template: dict) -> str:
        path = self.user_dir / f"{template['id']}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(template, f, indent=2)
        return str(path)

# ─────────────────────────────────────────────────────────────────
#  SCRIPT IMPORTER — Parse user C++/JSON design configs
# ─────────────────────────────────────────────────────────────────

class ScriptImporter:
    """Imports user-written scripts and converts them to template actions.

    Two input formats supported:

    1. JSON Design Config  — a file with an "actions" array:
       {
         "actions": [
           {"method": "SetAnimClass",
            "params": {"component_path": "...", "animblueprint_path": "..."}}
         ]
       }

    2. C++ with ANIMBP_DOCTOR_ACTION macros:
       ANIMBP_DOCTOR_ACTION(SetAnimClass, animblueprint_path="/Game/ABP_Hero")
    """

    SUPPORTED_METHODS = {
        "SetAnimClass": {
            "description": "Set AnimBP class on a Skeletal Mesh Component",
            "params": ["component_path", "animblueprint_path"],
            "template": "skeletal_mesh_link",
        },
        "AddSlotNode": {
            "description": "Add a montage Slot node to an AnimGraph",
            "params": ["animblueprint_path", "slot_name"],
            "template": "montage_slot_wiring",
        },
        "SetupBlendSpace": {
            "description": "Configure a BlendSpace with axis and samples",
            "params": ["blend_space_name", "axis_x_name"],
            "template": "blend_space_setup",
        },
        "ConfigureStateMachine": {
            "description": "Set up a locomotion state machine",
            "params": ["animblueprint_path", "speed_var", "is_falling_var"],
            "template": "state_machine_base",
        },
    }

    def __init__(self, template_mgr: TemplateManager):
        self.template_mgr = template_mgr

    def parse_file(self, filepath: str) -> Tuple[bool, List[dict], List[str]]:
        """Parse a user script. Returns (success, actions, errors)."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except (IOError, UnicodeDecodeError) as e:
            return (False, [], [f"Cannot read file: {e}"])

        if filepath.endswith(".json"):
            return self._parse_json(content)
        return self._parse_cpp(content)

    def _parse_json(self, content: str) -> Tuple[bool, List[dict], List[str]]:
        try:
            config = json.loads(content)
        except json.JSONDecodeError as e:
            return (False, [], [f"Invalid JSON: {e}"])

        actions, errors = [], []
        for i, a in enumerate(config.get("actions", [])):
            method = a.get("method", "")
            if method not in self.SUPPORTED_METHODS:
                errors.append(
                    f"Action {i+1}: Unknown method '{method}'. "
                    f"Supported: {', '.join(self.SUPPORTED_METHODS)}")
                continue
            spec = self.SUPPORTED_METHODS[method]
            params = a.get("params", {})
            missing = [p for p in spec["params"] if p not in params]
            if missing:
                errors.append(
                    f"Action {i+1} ({method}): missing params: "
                    f"{', '.join(missing)}")
                continue
            actions.append({
                "method": method, "params": params,
                "template_id": spec["template"],
                "description": spec["description"],
            })
        return (len(errors) == 0, actions, errors)

    def _parse_cpp(self, content: str) -> Tuple[bool, List[dict], List[str]]:
        actions, errors = [], []
        pattern = r'ANIMBP_DOCTOR_ACTION\s*\(\s*(\w+)\s*(?:,\s*(.*?))?\s*\)'
        for m in re.finditer(pattern, content, re.DOTALL):
            method = m.group(1)
            params_str = m.group(2) or ""
            if method not in self.SUPPORTED_METHODS:
                errors.append(f"Unknown method: {method}")
                continue
            params = {}
            if params_str.strip():
                for part in params_str.split(","):
                    part = part.strip()
                    if "=" in part:
                        k, v = part.split("=", 1)
                        params[k.strip()] = v.strip().strip("\"'")
            spec = self.SUPPORTED_METHODS[method]
            actions.append({
                "method": method, "params": params,
                "template_id": spec["template"],
                "description": spec["description"],
            })

        if not actions and not errors:
            errors.append(
                "No ANIMBP_DOCTOR_ACTION macros found.\n"
                "Supported macros:\n" +
                "\n".join(
                    f"  ANIMBP_DOCTOR_ACTION({m}, "
                    f"{', '.join(k+'=\"...\"' for k in s['params'])})"
                    for m, s in self.SUPPORTED_METHODS.items()
                ))
        return (len(errors) == 0, actions, errors)

    def execute_actions(self, actions: List[dict],
                        output_dir: str) -> List[Tuple[str, bool, str]]:
        """Render templates for parsed actions. Returns [(desc, ok, msg)]."""
        results = []
        for a in actions:
            path = self.template_mgr.export_script(
                a["template_id"], a["params"], output_dir)
            if path:
                results.append((a["description"], True, f"Saved: {Path(path).name}"))
            else:
                results.append((a["description"], False, "Template render failed"))
        return results

# ─────────────────────────────────────────────────────────────────
#  REPORT GENERATOR — HTML Output
# ─────────────────────────────────────────────────────────────────

class ReportGenerator:
    """Generates BP Doctor-themed HTML diagnostic reports."""

    @staticmethod
    def generate(scanner: ScannerEngine, output_path: str) -> str:
        grade = scanner.get_overall_grade()
        grade_color = Theme.grade_color(grade)
        total_errors   = sum(1 for r in scanner.results if r.severity == "ERROR")
        total_warnings = sum(1 for r in scanner.results if r.severity == "WARNING")
        total_infos    = sum(1 for r in scanner.results if r.severity == "INFO")
        fixable        = sum(1 for r in scanner.results if r.auto_fixable)
        scan_time      = f"{scanner.scan_duration:.1f}s" if scanner.scan_duration > 0 else "N/A"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Time saved calculation
        INSPECT_MIN = {
            "NULL_ANIM_REF": 1.5, "BROKEN_BLEND_WT": 1.0, "SKEL_MISMATCH": 3.0,
            "MISSING_SLOT": 0.5, "BROKEN_TRANS": 4.0, "TPOSE_FALLBACK": 1.5,
            "ORPHANED_NODE": 2.0, "INVALID_BSPACE": 1.0, "MISSING_NOTIFY": 2.0,
            "DUP_SLOT": 0.5, "UNUSED_VAR": 1.5, "DEPRECATED_NODE": 0.5,
        }
        abp_count = max(len(scanner.animblueprints), 1)
        checks_found = set(r.check_code for r in scanner.results)
        total_minutes = sum(INSPECT_MIN.get(c, 0.5) * abp_count for c in checks_found)
        if total_minutes < 60:
            time_saved = f"~{total_minutes:.0f} minutes"
        else:
            time_saved = f"~{total_minutes / 60:.1f} hours"

        # Build per-AnimBP sections
        abp_sections = ""
        for abp in sorted(scanner.animblueprints, key=lambda a: len(a.issues), reverse=True):
            if not abp.issues:
                continue
            g_color = Theme.grade_color(abp.grade)
            esc = html_module.escape
            rows = ""
            for issue in abp.issues:
                sev_color = Theme.severity_color(issue.severity)
                fix_badge = '<span class="badge fix">AUTO-FIX</span>' if issue.auto_fixable else ''
                check_def = CHECK_MAP.get(issue.check_code)
                why = esc(check_def.why_it_matters) if check_def else ""
                rows += f"""
                <tr>
                    <td><span class="severity" style="color:{sev_color}">{esc(issue.severity)}</span></td>
                    <td>{esc(issue.check_code)}</td>
                    <td>{esc(issue.description)} {fix_badge}</td>
                    <td class="hint">{esc(issue.node_hint)}</td>
                </tr>
                <tr class="why-row">
                    <td colspan="4">
                        <details>
                            <summary>Why This Matters</summary>
                            <p>{why}</p>
                        </details>
                    </td>
                </tr>"""

            abp_sections += f"""
            <div class="abp-card">
                <div class="abp-header">
                    <span class="abp-name">{esc(abp.name)}</span>
                    <span class="grade" style="color:{g_color}">{esc(abp.grade)}</span>
                </div>
                <div class="abp-path">{esc(abp.asset_path)}</div>
                <table class="issues-table">
                    <thead>
                        <tr><th>Severity</th><th>Check</th><th>Description</th><th>Location</th></tr>
                    </thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>"""

        # Clean AnimBPs
        clean_list = ""
        clean_abps = [a for a in scanner.animblueprints if not a.issues]
        if clean_abps:
            items = "".join(f"<li>{html_module.escape(a.name)} <span class='clean-badge'>CLEAN</span></li>" for a in clean_abps)
            clean_list = f"""
            <div class="clean-section">
                <h2>Clean AnimBlueprints ({len(clean_abps)})</h2>
                <ul>{items}</ul>
            </div>"""

        # Check summary table
        check_summary_rows = ""
        for check in CHECKS:
            count = sum(1 for r in scanner.results if r.check_code == check.code)
            if count > 0:
                sev_color = Theme.severity_color(check.severity.value)
                fix_badge = "Yes" if check.auto_fixable else "No"
                check_summary_rows += f"""
                <tr>
                    <td><span class="severity" style="color:{sev_color}">{check.severity.value}</span></td>
                    <td>{check.name}</td>
                    <td>{count}</td>
                    <td>{fix_badge}</td>
                </tr>"""

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BP Doctor Report — {now}</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        background: {Theme.BG_DEEP};
        color: {Theme.TEXT};
        font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
        line-height: 1.6;
        padding: 40px;
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
        margin-bottom: 8px;
    }}
    .header .subtitle {{ color: {Theme.TEXT_DIM}; font-size: 1.1em; }}
    .header .timestamp {{ color: {Theme.TEXT_MUTED}; margin-top: 8px; }}

    .dashboard {{
        display: grid;
        grid-template-columns: 200px repeat(5, 1fr);
        gap: 20px;
        margin-bottom: 40px;
    }}
    .grade-card {{
        background: {Theme.BG_CARD};
        border-radius: 16px;
        padding: 30px;
        text-align: center;
        border: 1px solid {Theme.BORDER};
    }}
    .grade-card .label {{ color: {Theme.TEXT_DIM}; font-size: 0.85em; text-transform: uppercase; letter-spacing: 1px; }}
    .grade-card .value {{ font-size: 4em; font-weight: 800; margin: 10px 0; }}
    .stat-card {{
        background: {Theme.BG_CARD};
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        border: 1px solid {Theme.BORDER};
    }}
    .stat-card .label {{ color: {Theme.TEXT_DIM}; font-size: 0.8em; text-transform: uppercase; letter-spacing: 1px; }}
    .stat-card .value {{ font-size: 2.2em; font-weight: 700; margin: 8px 0; }}

    h2 {{
        color: {Theme.ACCENT};
        font-size: 1.4em;
        margin: 30px 0 15px;
        padding-bottom: 8px;
        border-bottom: 1px solid {Theme.BORDER};
    }}

    .abp-card {{
        background: {Theme.BG_CARD};
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 20px;
        border: 1px solid {Theme.BORDER};
    }}
    .abp-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 4px;
    }}
    .abp-name {{ font-size: 1.3em; font-weight: 700; }}
    .abp-path {{ color: {Theme.TEXT_MUTED}; font-size: 0.85em; margin-bottom: 15px; }}
    .grade {{ font-size: 1.8em; font-weight: 800; }}

    .issues-table {{ width: 100%; border-collapse: collapse; }}
    .issues-table th {{
        text-align: left;
        padding: 8px 12px;
        color: {Theme.TEXT_DIM};
        font-size: 0.8em;
        text-transform: uppercase;
        letter-spacing: 1px;
        border-bottom: 1px solid {Theme.BORDER};
    }}
    .issues-table td {{
        padding: 10px 12px;
        border-bottom: 1px solid {Theme.BG_SURFACE};
        font-size: 0.9em;
    }}
    .severity {{ font-weight: 700; font-size: 0.85em; }}
    .hint {{ color: {Theme.TEXT_DIM}; font-style: italic; }}
    .badge {{ padding: 2px 8px; border-radius: 4px; font-size: 0.75em; font-weight: 600; }}
    .badge.fix {{ background: {Theme.ACCENT}22; color: {Theme.ACCENT}; }}

    .why-row td {{ padding: 0 12px 8px; }}
    details {{ cursor: pointer; }}
    details summary {{
        color: {Theme.ACCENT_DIM};
        font-size: 0.8em;
        padding: 4px 0;
    }}
    details p {{
        color: {Theme.TEXT_DIM};
        font-size: 0.85em;
        padding: 8px 0 4px 12px;
        border-left: 2px solid {Theme.ACCENT}44;
    }}

    .check-summary {{ margin-bottom: 30px; }}
    .check-summary table {{ width: 100%; border-collapse: collapse; }}
    .check-summary th {{
        text-align: left; padding: 8px 12px;
        color: {Theme.TEXT_DIM}; font-size: 0.8em;
        text-transform: uppercase; border-bottom: 1px solid {Theme.BORDER};
    }}
    .check-summary td {{ padding: 10px 12px; border-bottom: 1px solid {Theme.BG_SURFACE}; }}

    .clean-section ul {{ list-style: none; padding: 0; }}
    .clean-section li {{
        padding: 8px 16px;
        background: {Theme.BG_CARD};
        margin: 4px 0;
        border-radius: 8px;
        border: 1px solid {Theme.BORDER};
    }}
    .clean-badge {{
        color: {Theme.SUCCESS};
        font-size: 0.75em;
        font-weight: 700;
        margin-left: 12px;
    }}

    .footer {{
        text-align: center;
        margin-top: 50px;
        padding-top: 20px;
        border-top: 1px solid {Theme.BORDER};
        color: {Theme.TEXT_MUTED};
        font-size: 0.85em;
    }}
    .footer a {{ color: {Theme.ACCENT}; text-decoration: none; }}

    @media print {{
        body {{ background: #fff; color: #222; padding: 20px; }}
        .abp-card, .stat-card, .grade-card {{ border-color: #ddd; }}
    }}
</style>
</head>
<body>
    <div class="header">
        <h1>BP Doctor</h1>
        <div class="subtitle">Animation Blueprint Diagnostic Report</div>
        <div class="timestamp">Generated: {now} | Scanned in {scan_time} | BP Doctor</div>
    </div>

    <div class="dashboard">
        <div class="grade-card">
            <div class="label">Health Grade</div>
            <div class="value" style="color:{grade_color}">{grade}</div>
        </div>
        <div class="stat-card">
            <div class="label">Blueprints Scanned</div>
            <div class="value" style="color:{Theme.TEXT}">{len(scanner.animblueprints)}</div>
        </div>
        <div class="stat-card">
            <div class="label">Errors</div>
            <div class="value" style="color:{Theme.ERROR}">{total_errors}</div>
        </div>
        <div class="stat-card">
            <div class="label">Warnings</div>
            <div class="value" style="color:{Theme.WARNING}">{total_warnings}</div>
        </div>
        <div class="stat-card">
            <div class="label">Auto-Fixable</div>
            <div class="value" style="color:{Theme.ACCENT}">{fixable}</div>
        </div>
        <div class="stat-card">
            <div class="label">Inspection Time Saved</div>
            <div class="value" style="color:{Theme.SUCCESS}; font-size:1.4em">{time_saved}</div>
        </div>
    </div>

    <div class="check-summary">
        <h2>Check Summary</h2>
        <table>
            <thead><tr><th>Severity</th><th>Check</th><th>Occurrences</th><th>Auto-Fix</th></tr></thead>
            <tbody>{check_summary_rows}</tbody>
        </table>
    </div>

    <h2>Issues by AnimBlueprint ({sum(1 for a in scanner.animblueprints if a.issues)})</h2>
    {abp_sections}

    {clean_list}

    <div class="footer">
        <p>BP Doctor v2.5 &mdash; <a href="#">BP Doctor</a></p>
        <p>{len(CHECKS)} diagnostic checks | {len(scanner.results)} issues found | {len(scanner.animblueprints)} Blueprints scanned</p>
    </div>
</body>
</html>"""

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        return output_path

# ─────────────────────────────────────────────────────────────────
#  DIAGNOSTIC PDF — Step-by-step fix guide for every issue
# ─────────────────────────────────────────────────────────────────

# Fix guide data — maps check codes to step-by-step instructions
_FIX_GUIDES = {
    "NULL_ANIM_REF": [
        ("Open the AnimBP", "Double-click the flagged AnimBP in Content Browser."),
        ("Find empty Sequence Players", "Look for Sequence Player nodes showing 'None'. Press Ctrl+F and search 'Sequence Player'."),
        ("Assign an animation", "Click the node, find 'Sequence' in Details panel, select the correct animation asset."),
        ("Compile and test", "Press F7 to compile, then test in PIE to verify the animation plays."),
    ],
    "BROKEN_BLEND_WT": [
        ("Find the blend node", "Look for LayeredBoneBlend or Blend nodes in the AnimGraph."),
        ("Check weight values", "In Details panel, find 'Blend Weights'. Ensure all values are between 0.0 and 1.0."),
        ("Add a safety clamp", "If driven by a variable, add a Clamp node: Get Variable -> Clamp(0,1) -> BlendWeight."),
        ("Compile and test", "Press F7, test in PIE. Watch blend behavior for pops or jitter."),
    ],
    "SKEL_MISMATCH": [
        ("Check the AnimBP's skeleton", "Open AnimBP, note the skeleton shown in the toolbar."),
        ("Find mismatched animations", "Click each Sequence Player/BlendSpace. Verify its animation uses the same skeleton."),
        ("Retarget or replace", "Use Asset > Retarget Anim Assets for wrong-skeleton anims, or replace with compatible ones."),
        ("Compile and test cook", "Press F7, then File > Cook Content to verify no skeleton errors."),
    ],
    "MISSING_SLOT": [
        ("Open the AnimGraph", "Go to the AnimGraph tab in the AnimBP editor."),
        ("Add a Slot node", "Right-click empty space, search 'Slot', add it."),
        ("Wire it in", "Place BETWEEN your animation logic and Output Pose: [State Machine] -> [Slot] -> [Output Pose]."),
        ("Verify slot name", "Default is 'DefaultSlot'. Must match your PlayMontage code. Compile (F7)."),
    ],
    "BROKEN_TRANS": [
        ("Open the state machine", "Double-click the State Machine node to enter it."),
        ("Find isolated states", "Zoom out. Look for state boxes with no arrows pointing INTO them."),
        ("Connect or remove", "Add missing transitions by dragging from source state edge, or delete orphan states."),
        ("Test with debugger", "Compile, enable AnimBP debugger in PIE to watch state flow."),
    ],
    "TPOSE_FALLBACK": [
        ("Find the LayeredBoneBlend", "Look for 'Layered Blend per Bone' node in the AnimGraph."),
        ("Check BasePose input", "The TOP input pin (BasePose) must be connected. If empty, that's the problem."),
        ("Reconnect BasePose", "Wire your main animation output (State Machine) into the BasePose pin."),
        ("Compile and test", "Press F7. Test with montages/blends to verify no T-pose flashes."),
    ],
    "ORPHANED_NODE": [
        ("Zoom out", "Press Home to see the full AnimGraph."),
        ("Find disconnected nodes", "Look for nodes not connected to the Output Pose chain."),
        ("Delete or reconnect", "Select orphaned nodes, press Delete. Or wire them back if needed."),
    ],
    "INVALID_BSPACE": [
        ("Open the BlendSpace", "Find the BlendSpace asset in Content Browser, double-click."),
        ("Add sample animations", "Drag animation sequences onto the grid. Need at least 2 for interpolation."),
        ("Set axis ranges", "Configure Horizontal/Vertical axis names and Min/Max values."),
        ("Save and compile", "Save the BlendSpace, compile the AnimBP (F7), test in PIE."),
    ],
    "MISSING_NOTIFY": [
        ("Find animations with broken notifies", "Open each animation used by this AnimBP. Check the Notifies track."),
        ("Fix or remove", "Update the notify to point to the correct event, or Delete Notify."),
        ("Test event firing", "Compile, test in PIE. Add Print String to verify events fire."),
    ],
    "DUP_SLOT": [
        ("Find all Slot nodes", "Press Ctrl+F, search 'Slot' in the AnimGraph."),
        ("Rename duplicates", "Each Slot needs a unique name: DefaultSlot, UpperBody, LowerBody, etc."),
        ("Update code references", "If you renamed a slot, update PlayMontage calls to use the new name."),
        ("Compile and test", "Press F7. Test all montages to verify correct layer playback."),
    ],
    "BP_BROKEN_REF": [
        ("Identify the broken reference", "Open the Blueprint. Look for nodes with red or missing references."),
        ("Check if asset was moved", "Use Content Browser search to find the asset by name."),
        ("Redirect or remove", "If moved: right-click > Replace Reference. If deleted: remove the node."),
        ("Fix Redirectors", "Right-click Content folder > Fix Up Redirectors in Folder."),
    ],
    "BP_COMPLEXITY": [
        ("Identify hot spots", "Open the Blueprint. Look for dense clusters of nodes."),
        ("Extract to functions", "Select related nodes, right-click > Collapse to Function."),
        ("Consider C++", "Tight loops and math-heavy code should be C++."),
        ("Target under 100 nodes", "A well-organized Blueprint rarely needs more than 50-80 nodes."),
    ],
    "BP_DEBUG_NODES": [
        ("Search for PrintString", "Press Ctrl+F, search 'Print'. Select all and delete."),
        ("Search for DrawDebug", "Search 'Draw Debug'. These are even more expensive."),
        ("Use UE_LOG instead", "For persistent logging, use C++ UE_LOG (stripped in Shipping)."),
    ],
    "BP_SELF_CAST": [
        ("Find the self-cast", "Look for Cast nodes where the target matches this Blueprint's class."),
        ("Replace with Self", "Delete the Cast node. Use 'Get a reference to self' instead."),
        ("Compile", "Self-casts always succeed, so removing them is always safe."),
    ],
    "BP_CONSTRUCT_HEAVY": [
        ("Move to BeginPlay", "SpawnActor and heavy queries should happen in BeginPlay."),
        ("Use editor-only flag", "If needed only in editor, wrap with 'Is Editor' branch."),
        ("Compile and test", "Press F7. Verify actors still spawn correctly at runtime."),
    ],
    "BP_CIRCULAR_DEP": [
        ("Identify the cycle", "Both Blueprints reference each other."),
        ("Break with Interface", "Create a Blueprint Interface. Have one BP implement it, the other call through it."),
        ("Or use Event Dispatcher", "Replace the direct reference with an Event Dispatcher binding."),
    ],
    "BP_MASSIVE_ASSET": [
        ("Check for embedded data", "Open the Blueprint. Look for large arrays or embedded textures."),
        ("Move data to Data Assets", "Extract large data into separate Data Asset files."),
        ("Clean up unused nodes", "Delete commented-out or orphaned node groups."),
    ],
    "BP_HARD_REF": [
        ("Open Reference Viewer", "Right-click Blueprint > Reference Viewer."),
        ("Replace Cast with Interface", "Create a Blueprint Interface for the shared API."),
        ("Use Soft References", "For on-demand assets, use TSoftObjectPtr / Soft Object Reference."),
    ],
    "BP_EXPENSIVE_TICK": [
        ("Cache the result", "Call expensive functions once in BeginPlay, store in a variable."),
        ("Use a timer", "Replace Tick with Set Timer by Event (0.1-0.5s interval)."),
        ("Move to C++", "If per-frame execution is needed, C++ Tick is 10-100x faster."),
    ],
    "BP_TICK_HEAVY": [
        ("Evaluate necessity", "Does this Blueprint NEED to run every frame? Most don't."),
        ("Use timers", "Set Timer by Event with 0.1-0.5s interval covers most cases."),
        ("Disable Tick", "Class Defaults: set 'Start with Tick Enabled' to false."),
    ],
    "BP_EMPTY_GRAPH": [
        ("Check if intentional", "Some Blueprints are data-only (no logic needed)."),
        ("Delete if abandoned", "If this is an old prototype, delete it to reduce clutter."),
    ],
    "UNUSED_VAR": [
        ("Identify unused variables", "Right-click each variable > Find References."),
        ("Remove confirmed unused", "Delete variables with zero references."),
        ("Clean up setter code", "Remove NativeUpdateAnimation code that sets deleted variables."),
    ],
    "DEPRECATED_NODE": [
        ("Find deprecated nodes", "Check Compiler Results for deprecation warnings."),
        ("Find the replacement", "Hover over the deprecated node for the replacement name."),
        ("Swap and rewire", "Add the new node, copy settings, reconnect all pins."),
    ],
    "BP_DEPRECATED_FUNC": [
        ("Find deprecated calls", "Check Compiler Results for deprecation warnings."),
        ("Find replacements", "Hover over the deprecated node for the replacement."),
        ("Swap nodes", "Add the replacement, copy pin connections, delete the old one."),
    ],
    "BP_FOREACH_PERF": [
        ("Cache the array", "Before ForEachLoop, store query result in a local variable."),
        ("Use ForLoop instead", "Get array length, use standard ForLoop with index."),
        ("Check if in Tick", "ForEachLoop in Tick is especially bad — cache on a timer."),
    ],
    "BP_TIMELINE_HEAVY": [
        ("Count your Timelines", "Each Timeline node is a hidden tick component."),
        ("Merge Timelines", "If multiple run simultaneously, merge their curves."),
        ("Use Lerp + Timer", "For simple transitions, FInterpTo + Timer is lighter."),
        ("Stop when idle", "Call Stop() on Timelines that aren't actively playing."),
    ],
}


class DiagnosticPDFGenerator:
    """Generates a step-by-step diagnostic fix guide PDF from scan results."""

    @staticmethod
    def generate(scanner: 'ScannerEngine', output_path: str,
                 mode: str = "intermediate") -> str:
        """Generate a diagnostic PDF. Style adapts to experience mode."""
        mode_cfg = ExperienceMode.get(mode)
        pdf_style = mode_cfg["diagnostic_pdf_style"]
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.units import inch
            from reportlab.lib.colors import HexColor
            from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                             Table, TableStyle, PageBreak)
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.enums import TA_CENTER
            from reportlab.platypus.flowables import HRFlowable
        except ImportError:
            # Fallback: write plain text if reportlab not available
            return DiagnosticPDFGenerator._generate_text_fallback(scanner, output_path)

        ACCENT = HexColor("#00d4ff")
        MAGENTA = HexColor("#e040fb")
        ERROR_C = HexColor("#ff1744")
        WARN_C = HexColor("#ffab00")
        INFO_C = HexColor("#448aff")
        SUCCESS_C = HexColor("#00e676")
        BG_CARD = HexColor("#1a2035")
        BORDER = HexColor("#2a3150")

        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle("DocTitle", parent=styles["Title"],
            fontSize=24, textColor=ACCENT, alignment=TA_CENTER, spaceAfter=4))
        styles.add(ParagraphStyle("DocSub", parent=styles["Normal"],
            fontSize=11, textColor=HexColor("#666666"), alignment=TA_CENTER, spaceAfter=20))
        styles.add(ParagraphStyle("SectHead", parent=styles["Heading1"],
            fontSize=16, textColor=ACCENT, spaceBefore=20, spaceAfter=8))
        styles.add(ParagraphStyle("IssueHead", parent=styles["Heading2"],
            fontSize=13, textColor=MAGENTA, spaceBefore=14, spaceAfter=6))
        styles.add(ParagraphStyle("Bod", parent=styles["Normal"],
            fontSize=10, textColor=HexColor("#333333"), spaceAfter=4, leading=14))
        styles.add(ParagraphStyle("StepNum", parent=styles["Normal"],
            fontSize=10, textColor=HexColor("#333333"), spaceAfter=3, leading=14,
            leftIndent=20, fontName="Helvetica-Bold"))
        styles.add(ParagraphStyle("StepDesc", parent=styles["Normal"],
            fontSize=10, textColor=HexColor("#555555"), spaceAfter=6, leading=14,
            leftIndent=20))
        styles.add(ParagraphStyle("AutoFix", parent=styles["Normal"],
            fontSize=10, textColor=HexColor("#333333"), spaceAfter=6, leading=14,
            backColor=HexColor("#e8f5e9"), borderWidth=1, borderColor=SUCCESS_C,
            borderPadding=8, leftIndent=6, rightIndent=6))
        styles.add(ParagraphStyle("Foot", parent=styles["Normal"],
            fontSize=8, textColor=HexColor("#999999"), alignment=TA_CENTER))

        S = styles
        doc = SimpleDocTemplate(output_path, pagesize=letter,
                               topMargin=0.5*inch, bottomMargin=0.5*inch,
                               leftMargin=0.65*inch, rightMargin=0.65*inch)
        story = []

        # ── Cover ──
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        grade = scanner.get_overall_grade()
        project = os.path.basename(scanner.project_path or "Unknown")
        total_e = sum(1 for r in scanner.results if r.severity == "ERROR")
        total_w = sum(1 for r in scanner.results if r.severity == "WARNING")
        total_i = sum(1 for r in scanner.results if r.severity == "INFO")
        fixable = sum(1 for r in scanner.results if r.auto_fixable)

        story.append(Spacer(1, 0.5*inch))
        story.append(Paragraph("BP Doctor — Diagnostic Report", S["DocTitle"]))
        story.append(Paragraph(f"{project} | Grade: {grade} | {now}", S["DocSub"]))
        story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
        story.append(Spacer(1, 12))

        # Summary table
        sev_color = {"ERROR": "#ff1744", "WARNING": "#ffab00", "INFO": "#448aff"}
        summary_data = [
            ["Blueprints", "Errors", "Warnings", "Info", "Auto-Fixable", "Scan Time"],
            [str(len(scanner.animblueprints)), str(total_e), str(total_w),
             str(total_i), str(fixable), f"{scanner.scan_duration:.1f}s"],
        ]
        t = Table(summary_data, colWidths=[1.1*inch]*6)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BG_CARD),
            ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(t)
        story.append(Spacer(1, 16))

        # ── Group issues by Blueprint ──
        abp_issues = {}
        for r in scanner.results:
            key = r.animblueprint
            if key not in abp_issues:
                abp_issues[key] = []
            abp_issues[key].append(r)

        # Sort: most severe first
        sev_order = {"ERROR": 0, "WARNING": 1, "INFO": 2}
        sorted_abps = sorted(abp_issues.items(),
                            key=lambda x: min(sev_order.get(r.severity, 3) for r in x[1]))

        issue_num = 0

        # ── EXPERT MODE: single compact table ──
        if pdf_style == "table":
            table_data = [["#", "Severity", "Check", "Blueprint", "Hint", "Fix"]]
            for bp_name, issues in sorted_abps:
                for r in sorted(issues, key=lambda x: sev_order.get(x.severity, 3)):
                    issue_num += 1
                    check_def = CHECK_MAP.get(r.check_code)
                    check_name = check_def.name if check_def else r.check_code
                    fix = "AUTO" if r.auto_fixable else "manual"
                    hint = (r.node_hint[:50] + "...") if r.node_hint and len(r.node_hint) > 50 else (r.node_hint or "")
                    table_data.append([str(issue_num), r.severity, check_name,
                                      r.animblueprint, hint, fix])

            if len(table_data) > 1:
                t = Table(table_data, colWidths=[0.35*inch, 0.7*inch, 1.4*inch, 1.5*inch, 2*inch, 0.5*inch],
                         repeatRows=1)
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), BG_CARD),
                    ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("ALIGN", (0, 0), (1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                     [HexColor("#ffffff"), HexColor("#f8f9fc")]),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]))
                story.append(t)

        # ── BEGINNER / INTERMEDIATE: per-issue detail ──
        else:
            for bp_name, issues in sorted_abps:
                abp_obj = next((a for a in scanner.animblueprints if a.name == bp_name), None)
                bp_grade = abp_obj.grade if abp_obj else "?"
                bp_path = issues[0].asset_path if issues else ""

                story.append(Paragraph(f"{bp_name} (Grade: {bp_grade})", S["SectHead"]))
                story.append(Paragraph(f"<i>{bp_path}</i>", S["Bod"]))

                for r in sorted(issues, key=lambda x: sev_order.get(x.severity, 3)):
                    issue_num += 1
                    check_def = CHECK_MAP.get(r.check_code)
                    check_name = check_def.name if check_def else r.check_code
                    sev_hex = sev_color.get(r.severity, "#448aff")

                    fix_tag = " [AUTO-FIX]" if r.auto_fixable else ""
                    story.append(Paragraph(
                        f'<font color="{sev_hex}">#{issue_num} [{r.severity}]</font> '
                        f'{check_name}{fix_tag}',
                        S["IssueHead"]))

                    # Description (always shown for beginner/intermediate)
                    if mode_cfg["show_full_description"]:
                        story.append(Paragraph(r.description, S["Bod"]))
                    if r.node_hint:
                        story.append(Paragraph(f"<i>Hint: {r.node_hint}</i>", S["Bod"]))

                    # Auto-fix notice
                    if r.auto_fixable:
                        story.append(Paragraph(
                            f"<b>AUTO-FIX AVAILABLE:</b> BP Doctor can fix this automatically.",
                            S["AutoFix"]))

                    # Fix guide (beginner=full, intermediate=condensed)
                    if mode_cfg["show_fix_guide"]:
                        guide = _FIX_GUIDES.get(r.check_code)
                        if guide:
                            if pdf_style == "full":
                                story.append(Paragraph("<b>How to fix:</b>", S["Bod"]))
                                for step_i, (step_title, step_desc) in enumerate(guide, 1):
                                    story.append(Paragraph(f"Step {step_i}: {step_title}", S["StepNum"]))
                                    story.append(Paragraph(step_desc, S["StepDesc"]))
                            else:
                                # Condensed: step titles only
                                steps = " > ".join(t for t, _ in guide)
                                story.append(Paragraph(f"<b>Fix:</b> {steps}", S["Bod"]))

                    # Beginner tip
                    if mode_cfg["show_beginner_tip"] and check_def and check_def.beginner_tip:
                        story.append(Paragraph(
                            f"<b>Beginner tip:</b> {check_def.beginner_tip}", S["Bod"]))

                    # Why it matters
                    if mode_cfg["show_why_it_matters"] and check_def and check_def.why_it_matters:
                        story.append(Paragraph(
                            f"<i>Why: {check_def.why_it_matters[:200]}</i>", S["Bod"]))

                    story.append(Spacer(1, 8))

        # Footer
        story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
        story.append(Paragraph(
            f"BP Doctor v{APP_VERSION} | {now} | {issue_num} issues | "
            f"{fixable} auto-fixable | BP Doctor",
            S["Foot"]))

        doc.build(story)
        return output_path

    @staticmethod
    def _generate_text_fallback(scanner, output_path):
        """Plain text fallback if reportlab is not available."""
        lines = [f"BP Doctor v{APP_VERSION} — Diagnostic Report",
                 f"{'=' * 60}", ""]
        for r in scanner.results:
            check_def = CHECK_MAP.get(r.check_code)
            name = check_def.name if check_def else r.check_code
            lines.append(f"[{r.severity}] {name} — {r.animblueprint}")
            lines.append(f"  {r.description}")
            guide = _FIX_GUIDES.get(r.check_code)
            if guide:
                for i, (title, desc) in enumerate(guide, 1):
                    lines.append(f"  Step {i}: {title} — {desc}")
            lines.append("")
        txt_path = output_path.replace(".pdf", ".txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return txt_path


# ─────────────────────────────────────────────────────────────────
#  SETTINGS PERSISTENCE
# ─────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────
#  EXPERIENCE MODE — Controls verbosity across the entire app
# ─────────────────────────────────────────────────────────────────

class ExperienceMode:
    """Three-tier experience mode that controls what information is shown.

    BEGINNER:     Everything on — tips, explanations, full guides, "why it matters"
    INTERMEDIATE: No beginner tips or "why". Descriptions + condensed fix steps.
    EXPERT:       Minimal — code + severity + hint only. No prose. Checklist style.
    """

    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    EXPERT = "expert"

    MODES = {
        BEGINNER: {
            "label": "Beginner",
            "desc": "Full guidance — tips, explanations, step-by-step guides",
            "show_beginner_tip": True,
            "show_why_it_matters": True,
            "show_fix_guide": True,
            "show_full_description": True,
            "fix_guide_style": "full",       # full steps with descriptions
            "diagnostic_pdf_style": "full",  # full walkthrough per issue
            "cli_text_style": "verbose",     # multi-line with descriptions
        },
        INTERMEDIATE: {
            "label": "Intermediate",
            "desc": "Standard — descriptions and fix steps, no hand-holding",
            "show_beginner_tip": False,
            "show_why_it_matters": False,
            "show_fix_guide": True,
            "show_full_description": True,
            "fix_guide_style": "condensed",  # step titles only, no descriptions
            "diagnostic_pdf_style": "condensed",
            "cli_text_style": "standard",    # description + hint, no why
        },
        EXPERT: {
            "label": "Expert",
            "desc": "Minimal — code, severity, hint. One line per issue.",
            "show_beginner_tip": False,
            "show_why_it_matters": False,
            "show_fix_guide": False,
            "show_full_description": False,
            "fix_guide_style": "none",
            "diagnostic_pdf_style": "table",  # single table, one row per issue
            "cli_text_style": "compact",      # one line per issue
        },
    }

    @staticmethod
    def get(mode_name: str) -> dict:
        return ExperienceMode.MODES.get(mode_name, ExperienceMode.MODES[ExperienceMode.BEGINNER])


class Settings:
    DEFAULTS = {
        "project_path": "",
        "auto_scan_on_open": True,
        "checks_enabled": {c.code: True for c in CHECKS},
        "severity_filter": ["ERROR", "WARNING", "INFO"],
        "recent_projects": [],
        "report_output_dir": "",
        "theme": "doctor_dark",
        "check_for_updates": False,
        "experience_mode": "intermediate",
    }

    def __init__(self):
        self.data = dict(self.DEFAULTS)
        self.config_path = Path.home() / ".animbpdoctor" / "settings.json"

    def load(self):
        try:
            if self.config_path.exists():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                if isinstance(saved, dict):
                    # Validate critical fields against expected types
                    for key, default_val in self.DEFAULTS.items():
                        if key in saved:
                            if type(saved[key]) != type(default_val):
                                saved[key] = default_val  # Reset malformed fields
                            elif isinstance(default_val, (dict, list)) and len(saved[key]) == 0 and len(default_val) > 0:
                                saved[key] = default_val  # Reset empty containers
                    self.data.update(saved)
        except (json.JSONDecodeError, IOError, PermissionError):
            pass

    def save(self):
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except (IOError, OSError, PermissionError):
            pass  # Non-critical — don't crash on locked config

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.save()

# ─────────────────────────────────────────────────────────────────
#  GUI APPLICATION
# ─────────────────────────────────────────────────────────────────

class AnimBPDoctorApp:
    """Main application window with sidebar navigation and content views."""

    def __init__(self):
        # Enable DPI awareness for crisp rendering on high-DPI displays
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        self.root = tk.Tk()
        self.root.title(f"AnimBPDoctor v{APP_VERSION} — BP Doctor")
        self.root.geometry("1280x800")
        self.root.minsize(960, 600)
        self.root.configure(bg=Theme.BG_DEEP)

        # Set window icon color scheme via title bar (Windows 10+)
        try:
            self.root.iconbitmap(default="")
        except tk.TclError:
            pass

        # Engine
        self.scanner = ScannerEngine()
        self.settings = Settings()
        self.settings.load()
        self.is_scanning = False
        self.progress_var = tk.DoubleVar(value=0)  # initialized here so scan-from-Dashboard works

        # Apply saved color scheme before building UI
        _apply_scheme(self.settings.get("color_scheme", "Doctor Dark"))
        self.root.configure(bg=Theme.BG_DEEP)

        # Configure styles
        self._setup_styles()

        # Build layout
        self._build_ui()

        # Load last project if available
        last_project = self.settings.get("project_path", "")
        if last_project and os.path.isdir(last_project):
            self.project_path_var.set(last_project)

        # Scan history for trend tracking
        self.scan_history = ScanHistory()

        # Bind keyboard shortcuts
        self.root.bind("<F5>", lambda e: self._run_scan())
        self.root.bind("<Control-e>", lambda e: self._export_report())
        self.root.bind("<Control-f>", lambda e: self._focus_search())
        self.root.bind("<Escape>", lambda e: self._clear_search())

        # Always launch maximized — override any saved geometry
        self.root.state("zoomed")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        # Global
        style.configure(".", background=Theme.BG_DEEP, foreground=Theme.TEXT,
                        fieldbackground=Theme.BG_INPUT, borderwidth=0,
                        font=("Segoe UI", 10))

        # Frames
        style.configure("Card.TFrame", background=Theme.BG_CARD)
        style.configure("Surface.TFrame", background=Theme.BG_SURFACE)
        style.configure("Sidebar.TFrame", background=Theme.BG_SURFACE)

        # Labels
        style.configure("TLabel", background=Theme.BG_DEEP, foreground=Theme.TEXT)
        style.configure("Card.TLabel", background=Theme.BG_CARD, foreground=Theme.TEXT)
        style.configure("Title.TLabel", font=("Segoe UI", 22, "bold"), foreground=Theme.ACCENT)
        style.configure("Subtitle.TLabel", font=("Segoe UI", 11), foreground=Theme.TEXT_DIM)
        style.configure("Grade.TLabel", font=("Segoe UI", 64, "bold"))
        style.configure("GradeSm.TLabel", font=("Segoe UI", 24, "bold"))
        style.configure("StatValue.TLabel", font=("Segoe UI", 28, "bold"), background=Theme.BG_CARD)
        style.configure("StatLabel.TLabel", font=("Segoe UI", 9), foreground=Theme.TEXT_DIM,
                        background=Theme.BG_CARD)
        style.configure("SectionTitle.TLabel", font=("Segoe UI", 13, "bold"),
                        foreground=Theme.ACCENT)
        style.configure("Dim.TLabel", foreground=Theme.TEXT_DIM)
        style.configure("Muted.TLabel", foreground=Theme.TEXT_MUTED, font=("Segoe UI", 9))
        style.configure("Sidebar.TLabel", background=Theme.BG_SURFACE)
        style.configure("Status.TLabel", background=Theme.BG_SURFACE, foreground=Theme.TEXT_DIM,
                        font=("Segoe UI", 9))

        # Buttons
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"),
                        background=Theme.ACCENT, foreground=Theme.BG_DEEP, padding=(16, 8))
        style.map("Accent.TButton",
                  background=[("active", Theme.ACCENT_DIM), ("disabled", Theme.BG_CARD)])

        style.configure("Secondary.TButton", font=("Segoe UI", 10),
                        background=Theme.BG_CARD, foreground=Theme.TEXT, padding=(12, 8))
        style.map("Secondary.TButton",
                  background=[("active", Theme.BG_HOVER)])

        style.configure("Nav.TButton", font=("Segoe UI", 10),
                        background=Theme.BG_SURFACE, foreground=Theme.TEXT_DIM,
                        padding=(12, 10), anchor="w")
        style.map("Nav.TButton",
                  background=[("active", Theme.BG_HOVER)],
                  foreground=[("active", Theme.ACCENT)])

        style.configure("NavActive.TButton", font=("Segoe UI", 10, "bold"),
                        background=Theme.BG_HOVER, foreground=Theme.ACCENT,
                        padding=(12, 10), anchor="w")

        style.configure("Fix.TButton", font=("Segoe UI", 9, "bold"),
                        background=Theme.ACCENT, foreground=Theme.BG_DEEP, padding=(8, 4))

        style.configure("Small.TButton", font=("Segoe UI", 9),
                        background=Theme.BG_CARD, foreground=Theme.TEXT_DIM, padding=(8, 4))

        # Entry
        style.configure("TEntry", fieldbackground=Theme.BG_INPUT,
                        foreground=Theme.TEXT, insertcolor=Theme.TEXT, padding=8)

        # Progressbar
        style.configure("Accent.Horizontal.TProgressbar",
                        background=Theme.ACCENT, troughcolor=Theme.BG_CARD,
                        borderwidth=0, lightcolor=Theme.ACCENT,
                        darkcolor=Theme.ACCENT)

        # Treeview
        style.configure("Treeview",
                        background=Theme.BG_CARD,
                        foreground=Theme.TEXT,
                        fieldbackground=Theme.BG_CARD,
                        borderwidth=0,
                        font=("Segoe UI", 10),
                        rowheight=36)
        style.configure("Treeview.Heading",
                        background=Theme.BG_SURFACE,
                        foreground=Theme.TEXT_DIM,
                        font=("Segoe UI", 9, "bold"),
                        borderwidth=0)
        style.map("Treeview",
                  background=[("selected", Theme.BG_HOVER)],
                  foreground=[("selected", Theme.ACCENT)])
        style.map("Treeview.Heading",
                  background=[("active", Theme.BG_HOVER)])

        # Separator
        style.configure("TSeparator", background=Theme.BORDER)

        # Checkbutton
        style.configure("TCheckbutton", background=Theme.BG_CARD, foreground=Theme.TEXT,
                        font=("Segoe UI", 10))
        style.map("TCheckbutton", background=[("active", Theme.BG_CARD)])

    def _build_ui(self):
        # Main container
        self.main_frame = tk.Frame(self.root, bg=Theme.BG_DEEP)
        self.main_frame.pack(fill="both", expand=True)

        # Sidebar
        self._build_sidebar()

        # Content area
        self.content_frame = tk.Frame(self.main_frame, bg=Theme.BG_DEEP)
        self.content_frame.pack(side="left", fill="both", expand=True, padx=(0, 0))

        # Status bar
        self._build_statusbar()

        # Start with dashboard
        self.current_view = None
        self._show_dashboard()

    def _build_sidebar(self):
        sidebar = tk.Frame(self.main_frame, bg=Theme.BG_SURFACE, width=220)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        # Brand
        brand_frame = tk.Frame(sidebar, bg=Theme.BG_SURFACE, pady=20, padx=16)
        brand_frame.pack(fill="x")

        brand_title = tk.Label(brand_frame, text="BP Doctor",
                              font=("Segoe UI", 14, "bold"), fg=Theme.ACCENT,
                              bg=Theme.BG_SURFACE)
        brand_title.pack(anchor="w")
        brand_sub = tk.Label(brand_frame, text="v2.5  BP Doctor",
                            font=("Segoe UI", 9), fg=Theme.TEXT_MUTED,
                            bg=Theme.BG_SURFACE)
        brand_sub.pack(anchor="w")

        # Separator
        sep = tk.Frame(sidebar, bg=Theme.BORDER, height=1)
        sep.pack(fill="x", padx=16, pady=(0, 10))

        # Nav buttons
        self.nav_buttons = {}
        nav_items = [
            ("dashboard",  "\u25A3  Dashboard"),
            ("scanner",    "\u25CE  Scanner"),
            ("autofix",    "\u2692  Auto-Fix"),
            ("templates",  "\u2630  Templates"),
            ("automation", "\u2699  Automation"),
            ("checks",     "\u2637  Check Library"),
            ("report",     "\u2398  Reports"),
            ("settings",   "\u2638  Settings"),
        ]

        for key, label in nav_items:
            btn = tk.Button(sidebar, text=f"  {label}",
                           font=("Segoe UI", 10), fg=Theme.TEXT_DIM,
                           bg=Theme.BG_SURFACE, bd=0, anchor="w",
                           padx=20, pady=10, cursor="hand2",
                           activebackground=Theme.BG_HOVER,
                           activeforeground=Theme.ACCENT,
                           command=lambda k=key: self._navigate(k))
            btn.pack(fill="x")
            self.nav_buttons[key] = btn

        # Bottom section — project path
        spacer = tk.Frame(sidebar, bg=Theme.BG_SURFACE)
        spacer.pack(fill="both", expand=True)

        # Report a Bug (subtle, bottom of nav)
        bug_btn = tk.Label(sidebar, text="\u26A0  Report a Bug",
                          font=("Segoe UI", 8), fg=Theme.TEXT_MUTED,
                          bg=Theme.BG_SURFACE, cursor="hand2",
                          padx=20, pady=6, anchor="w")
        bug_btn.pack(fill="x")
        bug_btn.bind("<Button-1>", lambda _e: self._report_bug())
        bug_btn.bind("<Enter>",
                     lambda _e: bug_btn.configure(fg=Theme.TEXT_DIM))
        bug_btn.bind("<Leave>",
                     lambda _e: bug_btn.configure(fg=Theme.TEXT_MUTED))

        bottom = tk.Frame(sidebar, bg=Theme.BG_SURFACE, padx=16, pady=16)
        bottom.pack(fill="x", side="bottom")

        sep2 = tk.Frame(bottom, bg=Theme.BORDER, height=1)
        sep2.pack(fill="x", pady=(0, 12))

        proj_label = tk.Label(bottom, text="PROJECT", font=("Segoe UI", 8, "bold"),
                             fg=Theme.TEXT_MUTED, bg=Theme.BG_SURFACE)
        proj_label.pack(anchor="w")

        self.project_path_var = tk.StringVar(value="No project selected")
        proj_display = tk.Label(bottom, textvariable=self.project_path_var,
                               font=("Segoe UI", 8), fg=Theme.TEXT_DIM,
                               bg=Theme.BG_SURFACE, wraplength=180, justify="left")
        proj_display.pack(anchor="w", pady=(2, 8))

        browse_btn = tk.Button(bottom, text="Browse Project",
                              font=("Segoe UI", 9), fg=Theme.ACCENT,
                              bg=Theme.BG_CARD, bd=0, padx=12, pady=6,
                              cursor="hand2",
                              activebackground=Theme.BG_HOVER,
                              command=self._browse_project)
        browse_btn.pack(fill="x")

    def _build_statusbar(self):
        self.statusbar = tk.Frame(self.root, bg=Theme.BG_SURFACE, height=32)
        self.statusbar.pack(fill="x", side="bottom")
        self.statusbar.pack_propagate(False)

        self.status_label = tk.Label(self.statusbar, text="Ready",
                                    font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                                    bg=Theme.BG_SURFACE, padx=16)
        self.status_label.pack(side="left")

        self.status_right = tk.Label(self.statusbar, text="",
                                    font=("Segoe UI", 9), fg=Theme.TEXT_MUTED,
                                    bg=Theme.BG_SURFACE, padx=16)
        self.status_right.pack(side="right")

    # ── Navigation ──────────────────────────────────────────────

    def _navigate(self, view_key):
        views = {
            "dashboard":  self._show_dashboard,
            "scanner":    self._show_scanner,
            "autofix":    self._show_autofix,
            "templates":  self._show_templates,
            "automation": self._show_automation,
            "checks":     self._show_checks,
            "report":     self._show_report,
            "settings":   self._show_settings,
        }

        # Update nav button styles
        for key, btn in self.nav_buttons.items():
            if key == view_key:
                btn.configure(fg=Theme.ACCENT, font=("Segoe UI", 10, "bold"),
                            bg=Theme.BG_HOVER)
            else:
                btn.configure(fg=Theme.TEXT_DIM, font=("Segoe UI", 10),
                            bg=Theme.BG_SURFACE)

        views[view_key]()

    def _clear_content(self):
        try:
            self.content_frame.unbind_all("<MouseWheel>")
        except Exception:
            pass
        for widget in self.content_frame.winfo_children():
            widget.destroy()

    # ── Dashboard View ──────────────────────────────────────────

    def _show_dashboard(self):
        self._clear_content()
        self.current_view = "dashboard"
        self._navigate_highlight("dashboard")

        canvas = tk.Canvas(self.content_frame, bg=Theme.BG_DEEP, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.content_frame, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=Theme.BG_DEEP)

        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Bind mousewheel
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        pad = tk.Frame(scroll_frame, bg=Theme.BG_DEEP, padx=32, pady=24)
        pad.pack(fill="both", expand=True)

        # Header
        header = tk.Frame(pad, bg=Theme.BG_DEEP)
        header.pack(fill="x", pady=(0, 24))

        tk.Label(header, text="Dashboard", font=("Segoe UI", 22, "bold"),
                fg=Theme.ACCENT, bg=Theme.BG_DEEP).pack(side="left")

        # Quick scan button
        scan_btn = tk.Button(header, text="  Scan Project  ",
                            font=("Segoe UI", 11, "bold"),
                            fg=Theme.BG_DEEP, bg=Theme.ACCENT, bd=0,
                            padx=20, pady=8, cursor="hand2",
                            activebackground=Theme.ACCENT_DIM,
                            command=self._run_scan)
        scan_btn.pack(side="right")

        # Grade + Stats Row
        stats_frame = tk.Frame(pad, bg=Theme.BG_DEEP)
        stats_frame.pack(fill="x", pady=(0, 24))

        # Grade card
        grade = self.scanner.get_overall_grade()
        grade_color = Theme.grade_color(grade) if grade != "--" else Theme.TEXT_MUTED

        grade_card = tk.Frame(stats_frame, bg=Theme.BG_CARD, padx=30, pady=20)
        grade_card.pack(side="left", fill="y", padx=(0, 16))

        tk.Label(grade_card, text="HEALTH GRADE",
                font=("Segoe UI", 9, "bold"), fg=Theme.TEXT_MUTED,
                bg=Theme.BG_CARD).pack()
        tk.Label(grade_card, text=grade,
                font=("Segoe UI", 56, "bold"), fg=grade_color,
                bg=Theme.BG_CARD).pack(pady=(4, 0))

        # Stat cards
        total_e = sum(1 for r in self.scanner.results if r.severity == "ERROR")
        total_w = sum(1 for r in self.scanner.results if r.severity == "WARNING")
        total_i = sum(1 for r in self.scanner.results if r.severity == "INFO")
        fixable = sum(1 for r in self.scanner.results if r.auto_fixable)
        total_abps = len(self.scanner.animblueprints)

        stats_data = [
            ("BLUEPRINTS", str(total_abps), Theme.TEXT),
            ("ERRORS", str(total_e), Theme.ERROR if total_e > 0 else Theme.TEXT_DIM),
            ("WARNINGS", str(total_w), Theme.WARNING if total_w > 0 else Theme.TEXT_DIM),
            ("INFO", str(total_i), Theme.INFO if total_i > 0 else Theme.TEXT_DIM),
            ("AUTO-FIX", str(fixable), Theme.ACCENT if fixable > 0 else Theme.TEXT_DIM),
        ]

        stats_grid = tk.Frame(stats_frame, bg=Theme.BG_DEEP)
        stats_grid.pack(side="left", fill="both", expand=True)

        for idx, (label, value, color) in enumerate(stats_data):
            card = tk.Frame(stats_grid, bg=Theme.BG_CARD, padx=20, pady=16)
            card.grid(row=0, column=idx, padx=(0, 12), sticky="nsew")
            stats_grid.columnconfigure(idx, weight=1)

            tk.Label(card, text=label, font=("Segoe UI", 8, "bold"),
                    fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD).pack()
            tk.Label(card, text=value, font=("Segoe UI", 28, "bold"),
                    fg=color, bg=Theme.BG_CARD).pack(pady=(4, 0))

        # Results preview (if we have results)
        if self.scanner.results:
            results_frame = tk.Frame(pad, bg=Theme.BG_DEEP)
            results_frame.pack(fill="both", expand=True, pady=(8, 0))

            tk.Label(results_frame, text="Recent Issues",
                    font=("Segoe UI", 13, "bold"), fg=Theme.ACCENT,
                    bg=Theme.BG_DEEP).pack(anchor="w", pady=(0, 12))

            # Results table
            self._build_results_tree(results_frame, self.scanner.results[:50], show_checkboxes=False)

            # Per-AnimBP breakdown
            if self.scanner.animblueprints:
                tk.Label(results_frame, text="Blueprint Health",
                        font=("Segoe UI", 13, "bold"), fg=Theme.ACCENT,
                        bg=Theme.BG_DEEP).pack(anchor="w", pady=(20, 12))

                for abp in sorted(self.scanner.animblueprints,
                                 key=lambda a: len(a.issues), reverse=True):
                    g_color = Theme.grade_color(abp.grade)
                    issue_count = len(abp.issues)

                    abp_row = tk.Frame(results_frame, bg=Theme.BG_CARD, padx=16, pady=10)
                    abp_row.pack(fill="x", pady=2)

                    tk.Label(abp_row, text=abp.grade, font=("Segoe UI", 16, "bold"),
                            fg=g_color, bg=Theme.BG_CARD, width=3).pack(side="left")
                    tk.Label(abp_row, text=abp.name, font=("Segoe UI", 11, "bold"),
                            fg=Theme.TEXT, bg=Theme.BG_CARD).pack(side="left", padx=(8, 0))
                    tk.Label(abp_row, text=abp.asset_path, font=("Segoe UI", 9),
                            fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD).pack(side="left", padx=(12, 0))

                    if issue_count > 0:
                        errors = sum(1 for i in abp.issues if i.severity == "ERROR")
                        warns  = sum(1 for i in abp.issues if i.severity == "WARNING")
                        infos  = sum(1 for i in abp.issues if i.severity == "INFO")
                        badge_text = ""
                        if errors: badge_text += f"{errors}E "
                        if warns:  badge_text += f"{warns}W "
                        if infos:  badge_text += f"{infos}I"
                        tk.Label(abp_row, text=badge_text.strip(),
                                font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                                bg=Theme.BG_CARD).pack(side="right")
                    else:
                        tk.Label(abp_row, text="CLEAN",
                                font=("Segoe UI", 9, "bold"), fg=Theme.SUCCESS,
                                bg=Theme.BG_CARD).pack(side="right")

        else:
            # Empty state
            empty = tk.Frame(pad, bg=Theme.BG_CARD, padx=40, pady=60)
            empty.pack(fill="both", expand=True, pady=20)

            tk.Label(empty, text="No Scan Results Yet",
                    font=("Segoe UI", 18, "bold"), fg=Theme.TEXT,
                    bg=Theme.BG_CARD).pack()
            tk.Label(empty, text="Select a UE5 project and click Scan Project to begin.",
                    font=("Segoe UI", 11), fg=Theme.TEXT_DIM,
                    bg=Theme.BG_CARD).pack(pady=(8, 20))

            # Quick start steps
            steps = [
                "1.  Browse to your UE5 project folder (contains .uproject file)",
                "2.  Click 'Scan Project' — all Blueprints are discovered automatically",
                "3.  Review issues sorted by severity with 'Why This Matters' explanations",
                "4.  Export a shareable HTML report for your team",
            ]
            for step in steps:
                tk.Label(empty, text=step, font=("Segoe UI", 10),
                        fg=Theme.TEXT_DIM, bg=Theme.BG_CARD,
                        anchor="w").pack(anchor="w", pady=2)

    # ── Scanner View ────────────────────────────────────────────

    def _show_scanner(self):
        self._clear_content()
        self.current_view = "scanner"
        self._navigate_highlight("scanner")

        pad = tk.Frame(self.content_frame, bg=Theme.BG_DEEP, padx=32, pady=24)
        pad.pack(fill="both", expand=True)

        # Header
        tk.Label(pad, text="Scanner", font=("Segoe UI", 22, "bold"),
                fg=Theme.ACCENT, bg=Theme.BG_DEEP).pack(anchor="w")
        tk.Label(pad, text="Scan your UE5 project for Blueprint issues (AnimBP + General BP)",
                font=("Segoe UI", 11), fg=Theme.TEXT_DIM,
                bg=Theme.BG_DEEP).pack(anchor="w", pady=(4, 20))

        # Project path
        path_frame = tk.Frame(pad, bg=Theme.BG_CARD, padx=16, pady=16)
        path_frame.pack(fill="x", pady=(0, 16))

        tk.Label(path_frame, text="PROJECT PATH", font=("Segoe UI", 8, "bold"),
                fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD).pack(anchor="w")

        path_row = tk.Frame(path_frame, bg=Theme.BG_CARD)
        path_row.pack(fill="x", pady=(6, 0))

        self.path_entry = tk.Entry(path_row, textvariable=self.project_path_var,
                                  font=("Segoe UI", 10), bg=Theme.BG_INPUT,
                                  fg=Theme.TEXT, insertbackground=Theme.TEXT,
                                  bd=0, relief="flat")
        self.path_entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 8))

        tk.Button(path_row, text="Browse", font=("Segoe UI", 9),
                 fg=Theme.ACCENT, bg=Theme.BG_SURFACE, bd=0, padx=16, pady=6,
                 cursor="hand2", command=self._browse_project).pack(side="right")

        # Action buttons
        btn_frame = tk.Frame(pad, bg=Theme.BG_DEEP)
        btn_frame.pack(fill="x", pady=(0, 16))

        scan_btn_text = "  Scan All Blueprints  "
        if DEMO_MODE:
            if _demo_gate.can_scan():
                scan_btn_text = "  Scan All Blueprints  (1 free scan)  "
            else:
                scan_btn_text = "  Demo Complete — Upgrade to Pro  "

        tk.Button(btn_frame, text=scan_btn_text,
                 font=("Segoe UI", 11, "bold"), fg=Theme.BG_DEEP,
                 bg=Theme.ACCENT, bd=0, padx=20, pady=10, cursor="hand2",
                 activebackground=Theme.ACCENT_DIM,
                 command=self._run_scan).pack(side="left", padx=(0, 8))

        tk.Button(btn_frame, text="  Export Report  ",
                 font=("Segoe UI", 11), fg=Theme.TEXT,
                 bg=Theme.BG_CARD, bd=0, padx=20, pady=10, cursor="hand2",
                 activebackground=Theme.BG_HOVER,
                 command=self._export_report).pack(side="left", padx=(0, 8))

        tk.Button(btn_frame, text="  Clear  ",
                 font=("Segoe UI", 11), fg=Theme.TEXT_DIM,
                 bg=Theme.BG_CARD, bd=0, padx=20, pady=10, cursor="hand2",
                 activebackground=Theme.BG_HOVER,
                 command=self._clear_results).pack(side="left")

        # Progress bar
        self.progress_frame = tk.Frame(pad, bg=Theme.BG_DEEP)
        self.progress_frame.pack(fill="x", pady=(0, 8))

        # Reuse existing progress_var if scan is in progress (don't shadow)
        if not hasattr(self, '_scan_in_progress') or not self._scan_in_progress:
            self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(self.progress_frame,
                                           variable=self.progress_var,
                                           maximum=100,
                                           style="Accent.Horizontal.TProgressbar")
        self.progress_bar.pack(fill="x", ipady=2)

        self.progress_label = tk.Label(self.progress_frame, text="",
                                      font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                                      bg=Theme.BG_DEEP)
        self.progress_label.pack(anchor="w", pady=(4, 0))

        # Search + Filter bar
        filter_frame = tk.Frame(pad, bg=Theme.BG_DEEP)
        filter_frame.pack(fill="x", pady=(0, 8))

        # Search box (Ctrl+F) — clean up old trace to prevent accumulation
        if hasattr(self, '_search_var') and self._search_var:
            try:
                for trace_info in self._search_var.trace_info():
                    self._search_var.trace_remove(trace_info[0], trace_info[1])
            except (tk.TclError, ValueError):
                pass
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._apply_filters())
        self._search_entry = tk.Entry(filter_frame, textvariable=self._search_var,
                                     font=("Segoe UI", 10), bg=Theme.BG_INPUT,
                                     fg=Theme.TEXT, insertbackground=Theme.TEXT,
                                     bd=0, relief="flat", width=25)
        self._search_entry.pack(side="left", ipady=5, padx=(0, 12))
        # Placeholder text
        self._search_entry.insert(0, "")
        tk.Label(filter_frame, text="Search (Ctrl+F)", font=("Segoe UI", 8),
                fg=Theme.TEXT_MUTED, bg=Theme.BG_DEEP).pack(side="left", padx=(0, 16))

        # Severity toggles
        sep = tk.Frame(filter_frame, bg=Theme.BORDER, width=1, height=20)
        sep.pack(side="left", padx=(0, 12), fill="y")

        self.filter_vars = {}
        for sev, color in [("ERROR", Theme.ERROR), ("WARNING", Theme.WARNING), ("INFO", Theme.INFO)]:
            var = tk.BooleanVar(value=True)
            self.filter_vars[sev] = var
            cb = tk.Checkbutton(filter_frame, text=sev, variable=var,
                               font=("Segoe UI", 9, "bold"), fg=color,
                               bg=Theme.BG_DEEP, selectcolor=Theme.BG_CARD,
                               activebackground=Theme.BG_DEEP,
                               activeforeground=color,
                               command=self._apply_filters)
            cb.pack(side="left", padx=(0, 8))

        # Copy to clipboard button
        tk.Button(filter_frame, text="Copy Report",
                 font=("Segoe UI", 9), fg=Theme.ACCENT,
                 bg=Theme.BG_CARD, bd=0, padx=10, pady=4,
                 cursor="hand2", command=self._copy_report_clipboard
                 ).pack(side="right")

        # Results area
        self.scanner_results_frame = tk.Frame(pad, bg=Theme.BG_DEEP)
        self.scanner_results_frame.pack(fill="both", expand=True)

        if self.scanner.results:
            self._build_results_tree(self.scanner_results_frame,
                                     self._get_filtered_results(),
                                     show_checkboxes=False)

    # ── Auto-Fix View ──────────────────────────────────────────

    def _show_autofix(self):
        """Show the Auto-Fix tab — dedicated view for selecting and applying fixes."""
        self._clear_content()
        self.current_view = "autofix"
        self._navigate_highlight("autofix")

        if DEMO_MODE:
            pad = tk.Frame(self.content_frame, bg=Theme.BG_DEEP, padx=32, pady=60)
            pad.pack(fill="both", expand=True)
            tk.Label(pad, text="Auto-Fix Engine", font=("Segoe UI", 22, "bold"),
                    fg=Theme.ACCENT, bg=Theme.BG_DEEP).pack(anchor="w")
            tk.Label(pad, text="8 auto-fixes available in the Pro version",
                    font=("Segoe UI", 12), fg=Theme.TEXT_DIM,
                    bg=Theme.BG_DEEP).pack(anchor="w", pady=(8, 20))

            features = [
                "Binary patch blend weights to valid range",
                "Generate missing Slot nodes via Python script",
                "Reconnect disconnected BasePose inputs",
                "Remove duplicate Slot names automatically",
                "Strip PrintString/DrawDebug from production BPs",
                "Fix Construction Script misuse patterns",
                "Clean up excessive Timeline components",
                "Remove unnecessary self-cast nodes",
            ]
            for feat in features:
                tk.Label(pad, text=f"  +  {feat}", font=("Segoe UI", 10),
                        fg=Theme.TEXT, bg=Theme.BG_DEEP, anchor="w").pack(anchor="w", pady=2)

            tk.Label(pad, text="\nUpgrade to Pro for auto-fix + full fix guides",
                    font=("Segoe UI", 11, "bold"), fg=Theme.ACCENT,
                    bg=Theme.BG_DEEP).pack(anchor="w", pady=(20, 8))

            def _open_upgrade():
                import webbrowser
                webbrowser.open("https://bpdoctor.gumroad.com/l/pro")

            tk.Button(pad, text="  Get BP Doctor Pro  ", font=("Segoe UI", 12, "bold"),
                     fg=Theme.BG_DEEP, bg=Theme.ACCENT, bd=0, padx=20, pady=10,
                     cursor="hand2", command=_open_upgrade).pack(anchor="w", pady=(8, 0))
            return

        if not hasattr(self, '_fix_checked'):
            self._fix_checked = {}

        # Scrollable container
        canvas = tk.Canvas(self.content_frame, bg=Theme.BG_DEEP, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.content_frame, orient="vertical",
                                  command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=Theme.BG_DEEP)
        scroll_frame.bind("<Configure>",
                          lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<Enter>",
                    lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>",
                    lambda e: canvas.unbind_all("<MouseWheel>"))

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        pad = tk.Frame(scroll_frame, bg=Theme.BG_DEEP, padx=32, pady=24)
        pad.pack(fill="both", expand=True)

        # Header
        header = tk.Frame(pad, bg=Theme.BG_DEEP)
        header.pack(fill="x", pady=(0, 20))

        tk.Label(header, text="Auto-Fix",
                font=("Segoe UI", 22, "bold"), fg=Theme.ACCENT,
                bg=Theme.BG_DEEP).pack(side="left")
        tk.Label(header,
                text="Select issues and apply automated fixes",
                font=("Segoe UI", 11), fg=Theme.TEXT_DIM,
                bg=Theme.BG_DEEP).pack(side="left", padx=(16, 0), pady=(6, 0))

        # ── Empty states ──
        _sev_ord = {"ERROR": 0, "WARNING": 1, "INFO": 2}
        fixable_results = sorted(
            [r for r in (self.scanner.results or []) if r.auto_fixable],
            key=lambda r: _sev_ord.get(r.severity, 9))

        if not self.scanner.results:
            empty = tk.Frame(pad, bg=Theme.BG_CARD, padx=40, pady=60)
            empty.pack(fill="both", expand=True, pady=20)
            tk.Label(empty, text="No Scan Results",
                    font=("Segoe UI", 18, "bold"), fg=Theme.TEXT,
                    bg=Theme.BG_CARD).pack()
            tk.Label(empty,
                    text="Run a scan from the Scanner tab first, then come "
                         "back here to review and apply fixes.",
                    font=("Segoe UI", 11), fg=Theme.TEXT_DIM,
                    bg=Theme.BG_CARD).pack(pady=(8, 20))
            tk.Button(empty, text="  Go to Scanner  ",
                     font=("Segoe UI", 11, "bold"), fg=Theme.BG_DEEP,
                     bg=Theme.ACCENT, bd=0, padx=20, pady=10, cursor="hand2",
                     command=lambda: self._navigate("scanner")).pack()
            return

        if not fixable_results:
            empty = tk.Frame(pad, bg=Theme.BG_CARD, padx=40, pady=60)
            empty.pack(fill="both", expand=True, pady=20)
            tk.Label(empty, text="No Auto-Fixable Issues",
                    font=("Segoe UI", 18, "bold"), fg=Theme.SUCCESS,
                    bg=Theme.BG_CARD).pack()
            tk.Label(empty,
                    text=f"Scanned {len(self.scanner.results)} issues — none "
                         f"are auto-fixable.\nCheck the Scanner tab for manual "
                         f"fix guides.",
                    font=("Segoe UI", 11), fg=Theme.TEXT_DIM,
                    bg=Theme.BG_CARD, justify="center").pack(pady=(8, 0))
            return

        # ── Summary bar ──
        fix_engine = FixEngine(self.scanner)
        all_actions = fix_engine.generate_fix_actions(fixable_results)
        auto_actions = [a for a in all_actions if a.fix_type != "manual"]
        patch_count = sum(1 for a in auto_actions
                          if a.fix_type == "binary_patch")
        script_count = len(auto_actions) - patch_count
        bp_names = set(r.animblueprint for r in fixable_results)

        summary = tk.Frame(pad, bg=Theme.BG_CARD, padx=16, pady=12)
        summary.pack(fill="x", pady=(0, 12))

        tk.Label(summary,
                text=(f"{len(fixable_results)} fixable issue"
                      f"{'s' if len(fixable_results) != 1 else ''} across "
                      f"{len(bp_names)} blueprint"
                      f"{'s' if len(bp_names) != 1 else ''}"),
                font=("Segoe UI", 12, "bold"), fg=Theme.TEXT,
                bg=Theme.BG_CARD).pack(anchor="w")
        parts = []
        if patch_count:
            parts.append(f"{patch_count} binary patch"
                         f"{'es' if patch_count != 1 else ''}")
        if script_count:
            parts.append(f"{script_count} generated script"
                         f"{'s' if script_count != 1 else ''}")
        tk.Label(summary, text=" | ".join(parts),
                font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                bg=Theme.BG_CARD).pack(anchor="w", pady=(2, 0))

        # ── Select All / Deselect All + count ──
        self._autofix_card_vars = {}

        sel_bar = tk.Frame(pad, bg=Theme.BG_DEEP)
        sel_bar.pack(fill="x", pady=(0, 8))

        # Store checkbox labels for bulk updates
        self._autofix_chk_labels = {}

        def _select_all():
            for key, var in self._autofix_card_vars.items():
                var.set(True)
                self._fix_checked[key] = True
            for lbl in self._autofix_chk_labels.values():
                lbl.configure(text="\u2611", fg=Theme.ACCENT)
            self._update_autofix_count_label()

        def _deselect_all():
            for key, var in self._autofix_card_vars.items():
                var.set(False)
                self._fix_checked[key] = False
            for lbl in self._autofix_chk_labels.values():
                lbl.configure(text="\u2610", fg=Theme.TEXT_MUTED)
            self._update_autofix_count_label()

        tk.Button(sel_bar, text="Select All", font=("Segoe UI", 9),
                 fg=Theme.ACCENT, bg=Theme.BG_CARD, bd=0, padx=12, pady=4,
                 cursor="hand2", command=_select_all).pack(side="left",
                                                           padx=(0, 8))
        tk.Button(sel_bar, text="Deselect All", font=("Segoe UI", 9),
                 fg=Theme.TEXT_DIM, bg=Theme.BG_CARD, bd=0, padx=12, pady=4,
                 cursor="hand2", command=_deselect_all).pack(side="left")

        self._autofix_count_lbl = tk.Label(sel_bar, text="",
                font=("Segoe UI", 9), fg=Theme.TEXT_DIM, bg=Theme.BG_DEEP)
        self._autofix_count_lbl.pack(side="right")

        # ── Action bar (above cards) ──
        action_bar = tk.Frame(pad, bg=Theme.BG_SURFACE, padx=16, pady=12)
        action_bar.pack(fill="x", pady=(0, 12))

        tk.Button(action_bar, text="  Apply Selected Fixes  ",
                 font=("Segoe UI", 12, "bold"), fg=Theme.BG_DEEP,
                 bg=Theme.SUCCESS, bd=0, padx=24, pady=12, cursor="hand2",
                 activebackground="#00c853",
                 command=self._autofix_apply).pack(side="left", padx=(0, 8))

        tk.Button(action_bar, text="  Generate Scripts Only  ",
                 font=("Segoe UI", 10), fg=Theme.TEXT,
                 bg=Theme.BG_CARD, bd=0, padx=16, pady=10, cursor="hand2",
                 activebackground=Theme.BG_HOVER,
                 command=self._fix_generate_scripts).pack(side="left",
                                                          padx=(0, 8))

        tk.Button(action_bar, text="  Revert All  ",
                 font=("Segoe UI", 10), fg=Theme.ERROR,
                 bg=Theme.BG_CARD, bd=0, padx=16, pady=10, cursor="hand2",
                 activebackground=Theme.BG_HOVER,
                 command=self._fix_revert_all).pack(side="left")

        # ── Build action lookup for fix-type badges & previews ──
        action_map = {}
        for a in auto_actions:
            action_map.setdefault(
                (a.check_code, a.animblueprint), []).append(a)

        # ── Issue cards ──
        cards_frame = tk.Frame(pad, bg=Theme.BG_DEEP)
        cards_frame.pack(fill="x", pady=(0, 16))

        for r in fixable_results:
            state_key = (r.check_code, r.animblueprint, r.description[:60])
            if state_key not in self._fix_checked:
                self._fix_checked[state_key] = True

            var = tk.BooleanVar(value=self._fix_checked[state_key])
            self._autofix_card_vars[state_key] = var

            card = tk.Frame(cards_frame, bg=Theme.BG_CARD, padx=14, pady=10)
            card.pack(fill="x", pady=2)

            # Top row: checkbox label + severity badge + BP name + check name
            top = tk.Frame(card, bg=Theme.BG_CARD)
            top.pack(fill="x")

            # Visible checkbox — large Unicode glyph, toggles on click
            chk_text = "\u2611" if var.get() else "\u2610"
            chk_lbl = tk.Label(top, text=chk_text,
                              font=("Segoe UI", 16), fg=Theme.ACCENT,
                              bg=Theme.BG_CARD, cursor="hand2")
            chk_lbl.pack(side="left", padx=(0, 6))

            def _make_chk_toggle(v, sk, lbl):
                def _toggle(_event=None):
                    new_val = not v.get()
                    v.set(new_val)
                    self._fix_checked[sk] = new_val
                    lbl.configure(text="\u2611" if new_val else "\u2610",
                                 fg=Theme.ACCENT if new_val
                                 else Theme.TEXT_MUTED)
                    self._update_autofix_count_label()
                return _toggle

            chk_lbl.bind("<Button-1>",
                         _make_chk_toggle(var, state_key, chk_lbl))
            self._autofix_chk_labels[state_key] = chk_lbl
            # Dim unchecked items
            if not var.get():
                chk_lbl.configure(fg=Theme.TEXT_MUTED)

            sev_color = Theme.severity_color(r.severity)
            tk.Label(top, text=f" {r.severity} ",
                    font=("Segoe UI", 8, "bold"), fg=Theme.BG_DEEP,
                    bg=sev_color, padx=4).pack(side="left", padx=(0, 8))

            tk.Label(top, text=r.animblueprint,
                    font=("Segoe UI", 10, "bold"), fg=Theme.TEXT,
                    bg=Theme.BG_CARD).pack(side="left")

            check_def = CHECK_MAP.get(r.check_code)
            check_name = check_def.name if check_def else r.check_code
            tk.Label(top, text=check_name, font=("Segoe UI", 9),
                    fg=Theme.TEXT_DIM, bg=Theme.BG_CARD).pack(side="right")

            # Fix-type badge
            actions_for = action_map.get(
                (r.check_code, r.animblueprint), [])
            if actions_for:
                a0 = actions_for[0]
                tc = (Theme.WARNING if a0.fix_type == "binary_patch"
                      else Theme.INFO)
                tl = "PATCH" if a0.fix_type == "binary_patch" else "SCRIPT"
                tk.Label(top, text=f" {tl} ",
                        font=("Segoe UI", 7, "bold"), fg=Theme.BG_DEEP,
                        bg=tc, padx=4).pack(side="right", padx=(0, 8))

            # Description
            tk.Label(card, text=r.description[:120],
                    font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                    bg=Theme.BG_CARD, anchor="w", wraplength=620,
                    justify="left").pack(anchor="w", pady=(4, 0))

            # ── Expandable detail panel ──
            detail_frame = tk.Frame(card, bg=Theme.BG_SURFACE)
            # Hidden by default — toggled by Details button

            def _build_detail(df, res, act_list):
                df_pad = tk.Frame(df, bg=Theme.BG_SURFACE, padx=12, pady=10)
                df_pad.pack(fill="x")

                cd = CHECK_MAP.get(res.check_code)

                # What's wrong (beginner tip)
                if cd and getattr(cd, 'beginner_tip', ''):
                    tk.Label(df_pad, text="WHAT'S WRONG",
                            font=("Segoe UI", 8, "bold"),
                            fg=Theme.SUCCESS,
                            bg=Theme.BG_SURFACE).pack(anchor="w")
                    tk.Label(df_pad, text=cd.beginner_tip,
                            font=("Segoe UI", 9), fg=Theme.TEXT,
                            bg=Theme.BG_SURFACE, wraplength=600,
                            justify="left"
                            ).pack(anchor="w", pady=(2, 8))

                # Why it matters
                if cd:
                    tk.Label(df_pad, text="WHY IT MATTERS",
                            font=("Segoe UI", 8, "bold"),
                            fg=Theme.WARNING,
                            bg=Theme.BG_SURFACE).pack(anchor="w")
                    tk.Label(df_pad, text=cd.why_it_matters,
                            font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                            bg=Theme.BG_SURFACE, wraplength=600,
                            justify="left"
                            ).pack(anchor="w", pady=(2, 8))

                # Proposed fix preview
                if act_list:
                    tk.Label(df_pad, text="PROPOSED FIX",
                            font=("Segoe UI", 8, "bold"),
                            fg=Theme.ACCENT,
                            bg=Theme.BG_SURFACE).pack(anchor="w")
                    pv = tk.Frame(df_pad, bg=Theme.BG_INPUT,
                                  padx=8, pady=6)
                    pv.pack(fill="x", pady=(2, 4))
                    tk.Label(pv, text=act_list[0].preview,
                            font=("Consolas", 9), fg=Theme.TEXT,
                            bg=Theme.BG_INPUT, anchor="w",
                            justify="left", wraplength=580
                            ).pack(anchor="w")

                # Fix guide steps
                guide = self._get_fix_guide(res.check_code)
                if guide:
                    tk.Label(df_pad, text="HOW TO FIX (MANUAL)",
                            font=("Segoe UI", 8, "bold"),
                            fg=Theme.MAGENTA,
                            bg=Theme.BG_SURFACE).pack(anchor="w",
                                                       pady=(4, 2))
                    for i, (st, sd) in enumerate(guide, 1):
                        row = tk.Frame(df_pad, bg=Theme.BG_SURFACE)
                        row.pack(fill="x", pady=1)
                        tk.Label(row, text=f"{i}.",
                                font=("Segoe UI", 9, "bold"),
                                fg=Theme.ACCENT, bg=Theme.BG_SURFACE,
                                width=2).pack(side="left", anchor="n")
                        step_f = tk.Frame(row, bg=Theme.BG_SURFACE)
                        step_f.pack(side="left", fill="x", expand=True)
                        tk.Label(step_f, text=st,
                                font=("Segoe UI", 9, "bold"),
                                fg=Theme.TEXT, bg=Theme.BG_SURFACE,
                                anchor="w").pack(anchor="w")
                        tk.Label(step_f, text=sd,
                                font=("Segoe UI", 8),
                                fg=Theme.TEXT_DIM,
                                bg=Theme.BG_SURFACE, anchor="w",
                                wraplength=560, justify="left"
                                ).pack(anchor="w")

            _build_detail(detail_frame, r, actions_for)

            # Details toggle button
            is_open = [False]

            def _make_detail_toggle(df, flag):
                def _toggle(_event=None):
                    if flag[0]:
                        df.pack_forget()
                        flag[0] = False
                        det_btn.configure(text="\u25B6 Details",
                                         fg=Theme.TEXT_DIM)
                    else:
                        df.pack(fill="x", pady=(6, 0))
                        flag[0] = True
                        det_btn.configure(text="\u25BC Details",
                                         fg=Theme.ACCENT)
                return _toggle

            det_btn = tk.Label(card, text="\u25B6 Details",
                              font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                              bg=Theme.BG_CARD, cursor="hand2")
            det_btn.pack(anchor="w", pady=(4, 0))
            det_btn.bind("<Button-1>",
                         _make_detail_toggle(detail_frame, is_open))

        self._update_autofix_count_label()

    def _update_autofix_count_label(self):
        """Update the selected-count label in the Auto-Fix tab."""
        if not hasattr(self, '_autofix_count_lbl'):
            return
        try:
            checked = sum(1 for v in self._autofix_card_vars.values()
                          if v.get())
            total = len(self._autofix_card_vars)
            self._autofix_count_lbl.configure(
                text=f"{checked}/{total} selected")
        except (tk.TclError, AttributeError):
            pass

    def _autofix_apply(self):
        """Show confirmation dialog with proposed fixes and custom text."""
        if not self.scanner.results:
            messagebox.showinfo("No Results", "Run a scan first.")
            return

        # Gather checked results
        selected_results = []
        for r in self.scanner.results:
            if r.auto_fixable:
                sk = (r.check_code, r.animblueprint, r.description[:60])
                if self._fix_checked.get(sk, False):
                    selected_results.append(r)

        if not selected_results:
            messagebox.showinfo("Nothing Selected",
                "Select at least one issue to fix.\n\n"
                "Use the checkboxes next to each issue in the list above.")
            return

        fix_engine = FixEngine(self.scanner)
        actions = fix_engine.generate_fix_actions(selected_results)
        auto_actions = [a for a in actions if a.fix_type != "manual"]

        if not auto_actions:
            messagebox.showinfo("No Auto-Fixes",
                "Selected issues don't have auto-fix support.")
            return

        # ── Build confirmation dialog ──
        dialog = tk.Toplevel(self.root)
        dialog.title("Apply Fixes \u2014 BP Doctor")
        dialog.geometry("820x700")
        dialog.configure(bg=Theme.BG_DEEP)
        dialog.transient(self.root)
        dialog.grab_set()

        # Header
        tk.Label(dialog, text="Review & Apply Fixes",
                font=("Segoe UI", 18, "bold"), fg=Theme.ACCENT,
                bg=Theme.BG_DEEP).pack(anchor="w", padx=20, pady=(16, 4))
        tk.Label(dialog,
                text=(f"{len(auto_actions)} fix"
                      f"{'es' if len(auto_actions) != 1 else ''} selected. "
                      f"Review proposed changes below."),
                font=("Segoe UI", 10), fg=Theme.TEXT_DIM,
                bg=Theme.BG_DEEP).pack(anchor="w", padx=20, pady=(0, 12))

        # Scrollable action list
        d_canvas = tk.Canvas(dialog, bg=Theme.BG_DEEP, highlightthickness=0)
        d_sb = ttk.Scrollbar(dialog, orient="vertical",
                             command=d_canvas.yview)
        d_inner = tk.Frame(d_canvas, bg=Theme.BG_DEEP)
        d_inner.bind("<Configure>",
                     lambda e: d_canvas.configure(
                         scrollregion=d_canvas.bbox("all")))
        d_canvas.create_window((0, 0), window=d_inner, anchor="nw")
        d_canvas.configure(yscrollcommand=d_sb.set)

        def _d_scroll(event):
            d_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        d_canvas.bind("<Enter>",
                      lambda e: d_canvas.bind_all("<MouseWheel>", _d_scroll))
        d_canvas.bind("<Leave>",
                      lambda e: d_canvas.unbind_all("<MouseWheel>"))
        dialog.protocol("WM_DELETE_WINDOW",
            lambda: (d_canvas.unbind_all("<MouseWheel>"), dialog.destroy()))

        d_sb.pack(side="right", fill="y")
        d_canvas.pack(fill="both", expand=True, padx=20)

        # Action cards — each with preview + custom text input
        action_widgets = []  # [(FixAction, tk.Text)]

        for action in auto_actions:
            card = tk.Frame(d_inner, bg=Theme.BG_CARD, padx=14, pady=12)
            card.pack(fill="x", pady=3)

            # Top row: type badge + BP name + check code
            top = tk.Frame(card, bg=Theme.BG_CARD)
            top.pack(fill="x")

            tc = (Theme.WARNING if action.fix_type == "binary_patch"
                  else Theme.INFO)
            tl = "PATCH" if action.fix_type == "binary_patch" else "SCRIPT"
            tk.Label(top, text=f" {tl} ", font=("Segoe UI", 8, "bold"),
                    fg=Theme.BG_DEEP, bg=tc, padx=4).pack(side="left",
                                                           padx=(0, 8))
            tk.Label(top, text=action.animblueprint,
                    font=("Segoe UI", 10, "bold"), fg=Theme.TEXT,
                    bg=Theme.BG_CARD).pack(side="left")
            tk.Label(top, text=action.check_code,
                    font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                    bg=Theme.BG_CARD).pack(side="right")

            # Description
            tk.Label(card, text=action.description,
                    font=("Segoe UI", 9), fg=Theme.TEXT,
                    bg=Theme.BG_CARD, anchor="w", wraplength=740,
                    justify="left").pack(anchor="w", pady=(4, 6))

            # Proposed fix preview
            tk.Label(card, text="PROPOSED FIX:",
                    font=("Segoe UI", 8, "bold"), fg=Theme.ACCENT,
                    bg=Theme.BG_CARD).pack(anchor="w")

            pv_frame = tk.Frame(card, bg=Theme.BG_SURFACE, padx=8, pady=6)
            pv_frame.pack(fill="x", pady=(2, 6))
            tk.Label(pv_frame, text=action.preview,
                    font=("Consolas", 9), fg=Theme.TEXT_DIM,
                    bg=Theme.BG_SURFACE, anchor="w", justify="left",
                    wraplength=720).pack(anchor="w")

            # Custom notes text field
            tk.Label(card, text="CUSTOM NOTES (optional):",
                    font=("Segoe UI", 8, "bold"), fg=Theme.TEXT_MUTED,
                    bg=Theme.BG_CARD).pack(anchor="w")

            custom_txt = tk.Text(card, height=2, font=("Consolas", 9),
                                bg=Theme.BG_INPUT, fg=Theme.TEXT,
                                insertbackground=Theme.TEXT, bd=0,
                                relief="flat", wrap="word")
            custom_txt.pack(fill="x", pady=(2, 0), ipady=2)

            action_widgets.append((action, custom_txt))

        # Bottom button bar
        btn_bar = tk.Frame(dialog, bg=Theme.BG_DEEP)
        btn_bar.pack(fill="x", padx=20, pady=16)

        def _do_execute():
            project = self.project_path_var.get()
            if not project:
                messagebox.showwarning("No Project", "No project path set.")
                return

            fe = FixEngine(self.scanner)
            fe.backup_mgr = BackupManager(project)

            # Inject custom notes into generated scripts
            for act, txt_w in action_widgets:
                notes = txt_w.get("1.0", "end").strip()
                if (notes and act.fix_type == "generated_script"
                        and act.script_content):
                    act.script_content = (
                        f"# USER NOTES: {notes}\n\n"
                        + act.script_content)

            to_exec = [a for a, _ in action_widgets]
            exec_results = fe.execute_actions(to_exec, project)

            ok = sum(1 for s, _ in exec_results if s)
            fail = len(exec_results) - ok
            details = "\n".join(
                f"{'OK' if s else 'FAIL'}: {m}"
                for s, m in exec_results)

            d_canvas.unbind_all("<MouseWheel>")
            dialog.destroy()

            messagebox.showinfo("Fix Complete",
                f"Executed {len(exec_results)} actions:\n"
                f"  {ok} succeeded, {fail} failed\n\n"
                f"{details}\n\n"
                f"Use 'Revert All' to undo changes.")
            self._update_status(
                f"Auto-Fix: {ok}/{len(exec_results)} applied | "
                f"Backups: {fe.backup_mgr.get_backup_count()}")

            # Refresh view
            if self.current_view == "autofix":
                self._show_autofix()

        tk.Button(btn_bar, text="  Execute Selected Fixes  ",
                 font=("Segoe UI", 11, "bold"), fg=Theme.BG_DEEP,
                 bg=Theme.SUCCESS, bd=0, padx=20, pady=10, cursor="hand2",
                 activebackground="#00c853",
                 command=_do_execute).pack(side="left", padx=(0, 8))

        tk.Button(btn_bar, text="  Cancel  ",
                 font=("Segoe UI", 11), fg=Theme.TEXT,
                 bg=Theme.BG_CARD, bd=0, padx=20, pady=10, cursor="hand2",
                 command=lambda: (d_canvas.unbind_all("<MouseWheel>"),
                                  dialog.destroy())
                 ).pack(side="left")

        tk.Label(btn_bar,
                text=f"{len(auto_actions)} fix"
                     f"{'es' if len(auto_actions) != 1 else ''} queued",
                font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                bg=Theme.BG_DEEP).pack(side="right")

    # ── Templates View ─────────────────────────────────────────

    def _show_templates(self):
        self._clear_content()
        self.current_view = "templates"
        self._navigate_highlight("templates")

        if not hasattr(self, '_template_mgr'):
            self._template_mgr = TemplateManager()

        canvas = tk.Canvas(self.content_frame, bg=Theme.BG_DEEP,
                          highlightthickness=0)
        sb = ttk.Scrollbar(self.content_frame, orient="vertical",
                          command=canvas.yview)
        scroll = tk.Frame(canvas, bg=Theme.BG_DEEP)
        scroll.bind("<Configure>",
                    lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)

        def _mw(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<Enter>",
                    lambda e: canvas.bind_all("<MouseWheel>", _mw))
        canvas.bind("<Leave>",
                    lambda e: canvas.unbind_all("<MouseWheel>"))

        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        pad = tk.Frame(scroll, bg=Theme.BG_DEEP, padx=32, pady=24)
        pad.pack(fill="both", expand=True)

        tk.Label(pad, text="Templates",
                font=("Segoe UI", 22, "bold"), fg=Theme.ACCENT,
                bg=Theme.BG_DEEP).pack(anchor="w")
        tk.Label(pad,
                text="Reusable AnimBP automation templates. "
                     "Fill in variables, generate a script, run in UE5.",
                font=("Segoe UI", 11), fg=Theme.TEXT_DIM,
                bg=Theme.BG_DEEP).pack(anchor="w", pady=(4, 20))

        # Create New Template button
        tk.Button(pad, text="  + Create New Template  ",
                 font=("Segoe UI", 11, "bold"), fg=Theme.BG_DEEP,
                 bg=Theme.MAGENTA, bd=0, padx=20, pady=10, cursor="hand2",
                 activebackground=Theme.ACCENT,
                 command=self._create_new_template).pack(anchor="w", pady=(0, 16))

        for tmpl in self._template_mgr.templates:
            self._build_template_card(pad, tmpl)

    def _build_template_card(self, parent, tmpl):
        card = tk.Frame(parent, bg=Theme.BG_CARD, padx=20, pady=16)
        card.pack(fill="x", pady=(0, 12))

        # Header
        header = tk.Frame(card, bg=Theme.BG_CARD)
        header.pack(fill="x")

        tk.Label(header, text=tmpl["name"],
                font=("Segoe UI", 13, "bold"), fg=Theme.TEXT,
                bg=Theme.BG_CARD).pack(side="left")
        cat = tmpl.get("category", "General")
        tk.Label(header, text=cat, font=("Segoe UI", 8, "bold"),
                fg=Theme.ACCENT, bg=Theme.BG_CARD).pack(side="right")

        # Description
        tk.Label(card, text=tmpl["description"],
                font=("Segoe UI", 10), fg=Theme.TEXT_DIM,
                bg=Theme.BG_CARD, wraplength=680, justify="left",
                anchor="w").pack(fill="x", pady=(8, 4))

        # What it does
        if "what_it_does" in tmpl:
            for item in tmpl["what_it_does"]:
                tk.Label(card, text=f"  \u2022 {item}",
                        font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                        bg=Theme.BG_CARD, anchor="w").pack(fill="x")

        # When to use
        if "when_to_use" in tmpl:
            tk.Label(card, text=f"When to use: {tmpl['when_to_use']}",
                    font=("Segoe UI", 9, "italic"), fg=Theme.INFO,
                    bg=Theme.BG_CARD, anchor="w",
                    wraplength=680).pack(fill="x", pady=(6, 2))

        # Variable inputs
        var_frame = tk.Frame(card, bg=Theme.BG_SURFACE, padx=12, pady=10)
        var_frame.pack(fill="x", pady=(10, 0))

        tk.Label(var_frame, text="VARIABLES",
                font=("Segoe UI", 8, "bold"), fg=Theme.ACCENT,
                bg=Theme.BG_SURFACE).pack(anchor="w", pady=(0, 6))

        var_entries = {}
        for vname, vdef in tmpl.get("variables", {}).items():
            row = tk.Frame(var_frame, bg=Theme.BG_SURFACE)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=vname, font=("Segoe UI", 9, "bold"),
                    fg=Theme.TEXT, bg=Theme.BG_SURFACE,
                    width=20, anchor="w").pack(side="left")
            entry = tk.Entry(row, font=("Segoe UI", 9),
                            bg=Theme.BG_INPUT, fg=Theme.TEXT,
                            insertbackground=Theme.TEXT, bd=0,
                            relief="flat")
            entry.insert(0, vdef.get("default", ""))
            entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 8))
            var_entries[vname] = entry
            tk.Label(row, text=vdef.get("description", ""),
                    font=("Segoe UI", 8), fg=Theme.TEXT_MUTED,
                    bg=Theme.BG_SURFACE).pack(side="right")

        # Generate button
        btn_row = tk.Frame(card, bg=Theme.BG_CARD)
        btn_row.pack(fill="x", pady=(10, 0))

        def gen_script(tid=tmpl["id"], entries=var_entries):
            vals = {k: e.get() for k, e in entries.items()}
            project = self.project_path_var.get()
            out_dir = (Path(project) / ".animbpdoctor" / "generated_scripts"
                      if project and project != "No project selected"
                      else Path.home() / ".animbpdoctor" / "generated_scripts")
            path = self._template_mgr.export_script(tid, vals, str(out_dir))
            if path:
                messagebox.showinfo("Script Generated",
                    f"Script saved to:\n{path}\n\n"
                    f"Run in UE5: Tools > Execute Python Script")
                self._update_status(f"Template script saved: {Path(path).name}")
            else:
                messagebox.showerror("Error", "Failed to generate script.")

        def preview_script(tid=tmpl["id"], entries=var_entries):
            vals = {k: e.get() for k, e in entries.items()}
            script = self._template_mgr.render(tid, vals)
            if script:
                self._show_script_preview(tmpl["name"], script)

        tk.Button(btn_row, text="  Preview Script  ",
                 font=("Segoe UI", 9), fg=Theme.ACCENT,
                 bg=Theme.BG_SURFACE, bd=0, padx=12, pady=6,
                 cursor="hand2",
                 command=preview_script).pack(side="left", padx=(0, 8))
        tk.Button(btn_row, text="  Generate & Save  ",
                 font=("Segoe UI", 9, "bold"), fg=Theme.BG_DEEP,
                 bg=Theme.ACCENT, bd=0, padx=12, pady=6, cursor="hand2",
                 command=gen_script).pack(side="left", padx=(0, 8))

        def dup_template(t=tmpl):
            self._open_template_editor(duplicate_from=t)

        tk.Button(btn_row, text="  Duplicate & Customize  ",
                 font=("Segoe UI", 9), fg=Theme.MAGENTA,
                 bg=Theme.BG_SURFACE, bd=0, padx=12, pady=6,
                 cursor="hand2",
                 command=dup_template).pack(side="left")

        # Delete button for user-created templates
        if tmpl.get("user_created"):
            def del_template(t=tmpl):
                if messagebox.askyesno("Delete Template",
                        f"Delete '{t['name']}'?\nThis cannot be undone."):
                    fp = t.get("file_path")
                    if fp and os.path.exists(fp):
                        os.remove(fp)
                    self._template_mgr.templates.remove(t)
                    self._show_templates()

            tk.Button(btn_row, text="  Delete  ",
                     font=("Segoe UI", 9), fg=Theme.ERROR,
                     bg=Theme.BG_SURFACE, bd=0, padx=12, pady=6,
                     cursor="hand2",
                     command=del_template).pack(side="right")

    def _create_new_template(self):
        """Open editor for a brand-new template."""
        self._open_template_editor(duplicate_from=None)

    def _open_template_editor(self, duplicate_from=None):
        """Modal editor to create or duplicate a template."""
        win = tk.Toplevel(self.root)
        win.title("Template Editor — BP Doctor")
        win.geometry("780x700")
        win.configure(bg=Theme.BG_DEEP)
        win.transient(self.root)
        win.grab_set()

        canvas = tk.Canvas(win, bg=Theme.BG_DEEP, highlightthickness=0)
        sb = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=Theme.BG_DEEP)
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True)

        pad = tk.Frame(inner, bg=Theme.BG_DEEP, padx=24, pady=16)
        pad.pack(fill="both", expand=True)

        is_dup = duplicate_from is not None
        tk.Label(pad,
                text="Duplicate & Customize" if is_dup else "Create New Template",
                font=("Segoe UI", 18, "bold"), fg=Theme.ACCENT,
                bg=Theme.BG_DEEP).pack(anchor="w", pady=(0, 4))
        tk.Label(pad,
                text="Build a reusable template from your workflow. "
                     "Define variables with {placeholders} in the script body.",
                font=("Segoe UI", 10), fg=Theme.TEXT_DIM,
                bg=Theme.BG_DEEP).pack(anchor="w", pady=(0, 16))

        # Pre-fill from duplicate source
        src = duplicate_from or {}

        def make_field(label, default="", height=1):
            tk.Label(pad, text=label, font=("Segoe UI", 10, "bold"),
                    fg=Theme.TEXT, bg=Theme.BG_DEEP).pack(anchor="w", pady=(8, 2))
            if height == 1:
                e = tk.Entry(pad, font=("Segoe UI", 10), bg=Theme.BG_INPUT,
                            fg=Theme.TEXT, insertbackground=Theme.TEXT,
                            bd=0, relief="flat")
                e.insert(0, default)
                e.pack(fill="x", ipady=6)
                return e
            else:
                e = tk.Text(pad, font=("Consolas", 10), bg=Theme.BG_INPUT,
                           fg=Theme.TEXT, insertbackground=Theme.TEXT,
                           bd=0, height=height, wrap="none")
                e.insert("1.0", default)
                e.pack(fill="x")
                return e

        id_entry = make_field("Template ID (unique, snake_case)",
                             src.get("id", "my_custom_template") + ("_copy" if is_dup else ""))
        name_entry = make_field("Template Name",
                               src.get("name", "My Custom Template") + (" (Copy)" if is_dup else ""))
        cat_entry = make_field("Category", src.get("category", "Custom"))
        desc_entry = make_field("Description", src.get("description", ""), height=3)

        # Variables section
        tk.Label(pad, text="Variables (JSON — one per key)",
                font=("Segoe UI", 10, "bold"), fg=Theme.TEXT,
                bg=Theme.BG_DEEP).pack(anchor="w", pady=(12, 2))
        tk.Label(pad,
                text='Format: {"var_name": {"type": "string", "default": "value", "description": "..."}}',
                font=("Segoe UI", 8), fg=Theme.TEXT_MUTED,
                bg=Theme.BG_DEEP).pack(anchor="w", pady=(0, 4))

        vars_default = json.dumps(src.get("variables", {
            "my_variable": {"type": "string", "default": "", "description": "Your variable"}
        }), indent=2)
        vars_entry = make_field("", vars_default, height=6)

        # Script template
        tk.Label(pad, text="Script Template",
                font=("Segoe UI", 10, "bold"), fg=Theme.TEXT,
                bg=Theme.BG_DEEP).pack(anchor="w", pady=(12, 2))
        tk.Label(pad,
                text="Use {variable_name} placeholders. They get replaced with user values at render time.",
                font=("Segoe UI", 8), fg=Theme.TEXT_MUTED,
                bg=Theme.BG_DEEP).pack(anchor="w", pady=(0, 4))

        script_default = src.get("script_template",
            "// AnimBP Doctor — Custom Template\n"
            "// Target: {my_variable}\n\n"
            "import unreal\n"
            'unreal.log("Running custom template for {my_variable}")\n')
        script_entry = make_field("", script_default, height=12)

        # Save button
        btn_bar = tk.Frame(pad, bg=Theme.BG_DEEP)
        btn_bar.pack(fill="x", pady=(16, 8))

        def do_save():
            tid = id_entry.get().strip()
            tname = name_entry.get().strip()
            if not tid or not tname:
                messagebox.showwarning("Missing Fields",
                    "Template ID and Name are required.")
                return

            # Validate variables JSON
            try:
                variables = json.loads(vars_entry.get("1.0", "end").strip())
            except json.JSONDecodeError as e:
                messagebox.showerror("Invalid Variables",
                    f"Variables must be valid JSON:\n{e}")
                return

            template = {
                "id": tid,
                "name": tname,
                "category": cat_entry.get().strip() or "Custom",
                "description": desc_entry.get("1.0", "end").strip(),
                "variables": variables,
                "script_template": script_entry.get("1.0", "end").rstrip(),
            }

            path = self._template_mgr.save_user_template(template)
            # Reload into memory
            template["user_created"] = True
            template["file_path"] = path
            # Remove old version if exists
            self._template_mgr.templates = [
                t for t in self._template_mgr.templates if t["id"] != tid]
            self._template_mgr.templates.append(template)

            win.destroy()
            messagebox.showinfo("Template Saved",
                f"Template '{tname}' saved.\n\n"
                f"Location: {path}")
            self._show_templates()

        tk.Button(btn_bar, text="  Save Template  ",
                 font=("Segoe UI", 11, "bold"), fg=Theme.BG_DEEP,
                 bg=Theme.ACCENT, bd=0, padx=20, pady=10, cursor="hand2",
                 command=do_save).pack(side="left", padx=(0, 8))
        tk.Button(btn_bar, text="  Cancel  ",
                 font=("Segoe UI", 11), fg=Theme.TEXT,
                 bg=Theme.BG_CARD, bd=0, padx=20, pady=10, cursor="hand2",
                 command=win.destroy).pack(side="left")

    def _show_script_preview(self, title, script):
        """Show a generated script in a preview window."""
        win = tk.Toplevel(self.root)
        win.title(f"Script Preview — {title}")
        win.geometry("640x480")
        win.configure(bg=Theme.BG_DEEP)
        win.transient(self.root)

        tk.Label(win, text=title, font=("Segoe UI", 14, "bold"),
                fg=Theme.ACCENT, bg=Theme.BG_DEEP).pack(
                    anchor="w", padx=16, pady=(12, 8))

        text_frame = tk.Frame(win, bg=Theme.BG_SURFACE, padx=2, pady=2)
        text_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        text = tk.Text(text_frame, font=("Consolas", 10),
                      bg=Theme.BG_SURFACE, fg=Theme.TEXT,
                      insertbackground=Theme.TEXT, bd=0,
                      wrap="none", padx=10, pady=10)
        text.insert("1.0", script)
        text.configure(state="disabled")
        text.pack(fill="both", expand=True)

        btn = tk.Frame(win, bg=Theme.BG_DEEP)
        btn.pack(fill="x", padx=16, pady=(0, 12))

        def copy_script():
            self.root.clipboard_clear()
            self.root.clipboard_append(script)
            self._update_status("Script copied to clipboard")

        tk.Button(btn, text="  Copy to Clipboard  ",
                 font=("Segoe UI", 10), fg=Theme.ACCENT,
                 bg=Theme.BG_CARD, bd=0, padx=16, pady=8,
                 cursor="hand2", command=copy_script).pack(side="left")
        tk.Button(btn, text="  Close  ",
                 font=("Segoe UI", 10), fg=Theme.TEXT_DIM,
                 bg=Theme.BG_CARD, bd=0, padx=16, pady=8,
                 cursor="hand2", command=win.destroy).pack(side="left", padx=8)

    # ── Automation View (Script Import) ────────────────────────

    def _show_automation(self):
        self._clear_content()
        self.current_view = "automation"
        self._navigate_highlight("automation")

        if not hasattr(self, '_template_mgr'):
            self._template_mgr = TemplateManager()

        canvas = tk.Canvas(self.content_frame, bg=Theme.BG_DEEP,
                          highlightthickness=0)
        sb = ttk.Scrollbar(self.content_frame, orient="vertical",
                          command=canvas.yview)
        scroll = tk.Frame(canvas, bg=Theme.BG_DEEP)
        scroll.bind("<Configure>",
                    lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)

        def _mw(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<Enter>",
                    lambda e: canvas.bind_all("<MouseWheel>", _mw))
        canvas.bind("<Leave>",
                    lambda e: canvas.unbind_all("<MouseWheel>"))

        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        pad = tk.Frame(scroll, bg=Theme.BG_DEEP, padx=32, pady=24)
        pad.pack(fill="both", expand=True)

        tk.Label(pad, text="Automation",
                font=("Segoe UI", 22, "bold"), fg=Theme.ACCENT,
                bg=Theme.BG_DEEP).pack(anchor="w")
        tk.Label(pad,
                text="Import your C++ scripts or JSON configs to automate Blueprint setup",
                font=("Segoe UI", 11), fg=Theme.TEXT_DIM,
                bg=Theme.BG_DEEP).pack(anchor="w", pady=(4, 20))

        # Import section
        import_card = tk.Frame(pad, bg=Theme.BG_CARD, padx=20, pady=16)
        import_card.pack(fill="x", pady=(0, 16))

        tk.Label(import_card, text="Import Script",
                font=("Segoe UI", 13, "bold"), fg=Theme.TEXT,
                bg=Theme.BG_CARD).pack(anchor="w")
        tk.Label(import_card,
                text="Select a JSON config or C++ file with ANIMBP_DOCTOR_ACTION macros.",
                font=("Segoe UI", 10), fg=Theme.TEXT_DIM,
                bg=Theme.BG_CARD).pack(anchor="w", pady=(4, 12))

        btn_row = tk.Frame(import_card, bg=Theme.BG_CARD)
        btn_row.pack(fill="x")

        self._auto_output = tk.Frame(pad, bg=Theme.BG_DEEP)
        self._auto_output.pack(fill="both", expand=True)

        tk.Button(btn_row, text="  Browse & Import  ",
                 font=("Segoe UI", 11, "bold"), fg=Theme.BG_DEEP,
                 bg=Theme.ACCENT, bd=0, padx=20, pady=10,
                 cursor="hand2",
                 command=self._import_script).pack(side="left", padx=(0, 8))

        # Supported methods reference
        ref_card = tk.Frame(pad, bg=Theme.BG_CARD, padx=20, pady=16)
        ref_card.pack(fill="x", pady=(0, 16))

        tk.Label(ref_card, text="Supported Methods",
                font=("Segoe UI", 13, "bold"), fg=Theme.TEXT,
                bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 10))

        for method, spec in ScriptImporter.SUPPORTED_METHODS.items():
            row = tk.Frame(ref_card, bg=Theme.BG_SURFACE, padx=12, pady=8)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=method, font=("Consolas", 10, "bold"),
                    fg=Theme.ACCENT, bg=Theme.BG_SURFACE).pack(
                        side="left", padx=(0, 12))
            tk.Label(row, text=spec["description"],
                    font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                    bg=Theme.BG_SURFACE).pack(side="left")
            params_text = ", ".join(spec["params"])
            tk.Label(row, text=f"({params_text})",
                    font=("Consolas", 8), fg=Theme.TEXT_MUTED,
                    bg=Theme.BG_SURFACE).pack(side="right")

        # JSON example
        example_card = tk.Frame(pad, bg=Theme.BG_CARD, padx=20, pady=16)
        example_card.pack(fill="x", pady=(0, 16))

        tk.Label(example_card, text="JSON Config Example",
                font=("Segoe UI", 13, "bold"), fg=Theme.TEXT,
                bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 8))

        example_json = textwrap.dedent("""\
            {
              "actions": [
                {
                  "method": "AddSlotNode",
                  "params": {
                    "animblueprint_path": "/Game/Characters/ABP_Hero",
                    "slot_name": "DefaultSlot"
                  }
                },
                {
                  "method": "SetAnimClass",
                  "params": {
                    "component_path": "/Game/Blueprints/BP_Hero",
                    "animblueprint_path": "/Game/Characters/ABP_Hero"
                  }
                }
              ]
            }""")

        ex_text = tk.Text(example_card, font=("Consolas", 9),
                         bg=Theme.BG_SURFACE, fg=Theme.TEXT,
                         bd=0, height=16, padx=10, pady=8, wrap="none")
        ex_text.insert("1.0", example_json)
        ex_text.configure(state="disabled")
        ex_text.pack(fill="x")

        # C++ example
        cpp_card = tk.Frame(pad, bg=Theme.BG_CARD, padx=20, pady=16)
        cpp_card.pack(fill="x")

        tk.Label(cpp_card, text="C++ Macro Example",
                font=("Segoe UI", 13, "bold"), fg=Theme.TEXT,
                bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 8))

        example_cpp = textwrap.dedent("""\
            // Your C++ file with AnimBP Doctor annotations
            // The tool will parse these macros and generate automation scripts.

            ANIMBP_DOCTOR_ACTION(AddSlotNode,
                animblueprint_path="/Game/Characters/ABP_Hero",
                slot_name="DefaultSlot")

            ANIMBP_DOCTOR_ACTION(ConfigureStateMachine,
                animblueprint_path="/Game/Characters/ABP_Hero",
                speed_var="Speed",
                is_falling_var="bIsFalling")""")

        cpp_text = tk.Text(cpp_card, font=("Consolas", 9),
                          bg=Theme.BG_SURFACE, fg=Theme.TEXT,
                          bd=0, height=11, padx=10, pady=8, wrap="none")
        cpp_text.insert("1.0", example_cpp)
        cpp_text.configure(state="disabled")
        cpp_text.pack(fill="x")

    def _import_script(self):
        """Import and parse a user script file."""
        filepath = filedialog.askopenfilename(
            title="Import Script",
            filetypes=[
                ("Config files", "*.json"),
                ("C++ files", "*.cpp *.h"),
                ("All files", "*.*"),
            ])
        if not filepath:
            return

        if not hasattr(self, '_template_mgr'):
            self._template_mgr = TemplateManager()

        importer = ScriptImporter(self._template_mgr)
        success, actions, errors = importer.parse_file(filepath)

        # Clear previous output
        for w in self._auto_output.winfo_children():
            w.destroy()

        if errors:
            err_frame = tk.Frame(self._auto_output, bg=Theme.BG_CARD,
                                padx=16, pady=12)
            err_frame.pack(fill="x", pady=(0, 8))
            tk.Label(err_frame, text="Parse Errors",
                    font=("Segoe UI", 11, "bold"), fg=Theme.ERROR,
                    bg=Theme.BG_CARD).pack(anchor="w")
            for err in errors:
                tk.Label(err_frame, text=f"\u2022 {err}",
                        font=("Segoe UI", 9), fg=Theme.ERROR,
                        bg=Theme.BG_CARD, wraplength=640,
                        justify="left", anchor="w").pack(fill="x", pady=2)

        if actions:
            act_frame = tk.Frame(self._auto_output, bg=Theme.BG_CARD,
                                padx=16, pady=12)
            act_frame.pack(fill="x", pady=(0, 8))
            tk.Label(act_frame,
                    text=f"Parsed {len(actions)} Action(s)",
                    font=("Segoe UI", 11, "bold"), fg=Theme.SUCCESS,
                    bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 8))

            for a in actions:
                row = tk.Frame(act_frame, bg=Theme.BG_SURFACE, padx=10, pady=6)
                row.pack(fill="x", pady=2)
                tk.Label(row, text=a["method"],
                        font=("Consolas", 10, "bold"), fg=Theme.ACCENT,
                        bg=Theme.BG_SURFACE).pack(side="left", padx=(0, 12))
                tk.Label(row, text=a["description"],
                        font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                        bg=Theme.BG_SURFACE).pack(side="left")

            def do_execute():
                project = self.project_path_var.get()
                out = (Path(project) / ".animbpdoctor" / "generated_scripts"
                      if project and project != "No project selected"
                      else Path.home() / ".animbpdoctor" / "generated_scripts")
                results = importer.execute_actions(actions, str(out))
                ok = sum(1 for _, s, _ in results if s)
                detail = "\n".join(f"{'OK' if s else 'FAIL'}: {m}"
                                  for _, s, m in results)
                messagebox.showinfo("Execution Complete",
                    f"Processed {len(results)} actions ({ok} succeeded):\n\n"
                    f"{detail}")
                self._update_status(f"Executed {ok}/{len(results)} script actions")

            tk.Button(act_frame, text="  Execute All Actions  ",
                     font=("Segoe UI", 10, "bold"), fg=Theme.BG_DEEP,
                     bg=Theme.ACCENT, bd=0, padx=16, pady=8,
                     cursor="hand2",
                     command=do_execute).pack(anchor="w", pady=(8, 0))

    # ── Check Library View ──────────────────────────────────────

    def _show_checks(self):
        self._clear_content()
        self.current_view = "checks"
        self._navigate_highlight("checks")

        canvas = tk.Canvas(self.content_frame, bg=Theme.BG_DEEP, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.content_frame, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=Theme.BG_DEEP)

        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        pad = tk.Frame(scroll_frame, bg=Theme.BG_DEEP, padx=32, pady=24)
        pad.pack(fill="both", expand=True)

        tk.Label(pad, text="Check Library", font=("Segoe UI", 22, "bold"),
                fg=Theme.ACCENT, bg=Theme.BG_DEEP).pack(anchor="w")
        tk.Label(pad, text=f"All {len(CHECKS)} diagnostic checks with detailed explanations",
                font=("Segoe UI", 11), fg=Theme.TEXT_DIM,
                bg=Theme.BG_DEEP).pack(anchor="w", pady=(4, 12))

        # Search bar — clean up old trace on re-entry
        if hasattr(self, '_chklib_search') and self._chklib_search:
            try:
                for trace_info in self._chklib_search.trace_info():
                    self._chklib_search.trace_remove(
                        trace_info[0], trace_info[1])
            except (tk.TclError, ValueError):
                pass
        search_frame = tk.Frame(pad, bg=Theme.BG_DEEP)
        search_frame.pack(fill="x", pady=(0, 12))
        self._chklib_search = tk.StringVar()
        tk.Entry(search_frame, textvariable=self._chklib_search,
                font=("Segoe UI", 10), bg=Theme.BG_INPUT, fg=Theme.TEXT,
                insertbackground=Theme.TEXT, bd=0, relief="flat",
                width=30).pack(side="left", ipady=6, padx=(0, 8))
        tk.Label(search_frame, text="Search checks...",
                font=("Segoe UI", 9), fg=Theme.TEXT_MUTED,
                bg=Theme.BG_DEEP).pack(side="left")

        # Container for check cards (rebuilt on search)
        self._chklib_container = tk.Frame(pad, bg=Theme.BG_DEEP)
        self._chklib_container.pack(fill="x")

        # Sort by severity: ERROR → WARNING → INFO
        sev_order = {"ERROR": 0, "WARNING": 1, "INFO": 2}
        sorted_checks = sorted(CHECKS,
                                key=lambda c: sev_order.get(c.severity.value, 9))

        def _build_check_cards(query=""):
            for w in self._chklib_container.winfo_children():
                w.destroy()
            q = query.strip().lower().lstrip("#")
            for check in sorted_checks:
                # Match by check ID number (e.g. "7", "#7")
                id_match = (q.isdigit() and int(q) == check.id) if q else False
                if q and not id_match and (
                          q not in check.name.lower()
                          and q not in check.code.lower()
                          and q not in check.description.lower()
                          and q not in check.severity.value.lower()
                          and q not in getattr(check, 'beginner_tip', '').lower()):
                    continue

                sev_color = Theme.severity_color(check.severity.value)

                card = tk.Frame(self._chklib_container, bg=Theme.BG_CARD,
                               padx=20, pady=16)
                card.pack(fill="x", pady=(0, 8))

                header = tk.Frame(card, bg=Theme.BG_CARD)
                header.pack(fill="x")

                tk.Label(header, text=f"#{check.id}",
                        font=("Segoe UI", 11, "bold"),
                        fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD,
                        width=3).pack(side="left")
                tk.Label(header, text=check.severity.value,
                        font=("Segoe UI", 9, "bold"),
                        fg=sev_color, bg=Theme.BG_CARD,
                        width=8).pack(side="left", padx=(4, 8))
                tk.Label(header, text=check.name,
                        font=("Segoe UI", 12, "bold"),
                        fg=Theme.TEXT, bg=Theme.BG_CARD).pack(side="left")

                if check.auto_fixable:
                    tk.Label(header, text="AUTO-FIX",
                            font=("Segoe UI", 8, "bold"),
                            fg=Theme.ACCENT,
                            bg=Theme.BG_CARD).pack(side="right")

                conf = getattr(check, 'confidence', None)
                if conf:
                    conf_colors = {"HIGH": Theme.SUCCESS,
                                   "MEDIUM": Theme.WARNING,
                                   "LOW": Theme.TEXT_MUTED}
                    conf_color = conf_colors.get(conf.value, Theme.TEXT_DIM)
                    tk.Label(header, text=f" {conf.value} ",
                            font=("Segoe UI", 7, "bold"),
                            fg=Theme.BG_DEEP,
                            bg=conf_color).pack(side="right", padx=(4, 0))

                check_type = ("AnimBP"
                    if check.code in ScannerEngine._ANIMBP_CHECK_CODES
                    else ("General BP"
                          if check.code in ScannerEngine._BP_CHECK_CODES
                          else "Both"))
                type_color = (Theme.MAGENTA if check_type == "AnimBP"
                    else (Theme.INFO if check_type == "General BP"
                          else Theme.TEXT_DIM))
                tk.Label(header, text=f" {check_type} ",
                        font=("Segoe UI", 7, "bold"), fg=Theme.BG_DEEP,
                        bg=type_color).pack(side="right", padx=(4, 0))

                tk.Label(card, text=check.description,
                        font=("Segoe UI", 10), fg=Theme.TEXT_DIM,
                        bg=Theme.BG_CARD, anchor="w",
                        wraplength=700, justify="left"
                        ).pack(fill="x", pady=(8, 4))

                tip = getattr(check, 'beginner_tip', '')
                if tip:
                    tip_frame = tk.Frame(card, bg="#1a2a1a", padx=12,
                                         pady=8)
                    tip_frame.pack(fill="x", pady=(6, 0))
                    tk.Label(tip_frame, text="PLAIN ENGLISH",
                            font=("Segoe UI", 7, "bold"),
                            fg=Theme.SUCCESS,
                            bg="#1a2a1a").pack(anchor="w")
                    tk.Label(tip_frame, text=tip,
                            font=("Segoe UI", 9), fg=Theme.TEXT,
                            bg="#1a2a1a", wraplength=680,
                            justify="left", anchor="w"
                            ).pack(fill="x", pady=(2, 0))

                why_frame = tk.Frame(card, bg=Theme.BG_SURFACE, padx=12,
                                     pady=10)
                why_frame.pack(fill="x", pady=(6, 0))
                tk.Label(why_frame, text="TECHNICAL DETAIL",
                        font=("Segoe UI", 8, "bold"), fg=Theme.ACCENT,
                        bg=Theme.BG_SURFACE).pack(anchor="w")
                tk.Label(why_frame, text=check.why_it_matters,
                        font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                        bg=Theme.BG_SURFACE, wraplength=680,
                        justify="left", anchor="w"
                        ).pack(fill="x", pady=(4, 0))

            # Update scroll region after rebuilding cards
            self._chklib_container.update_idletasks()
            canvas.configure(
                scrollregion=canvas.bbox("all") or (0, 0, 0, 0))
            canvas.yview_moveto(0)

        _build_check_cards()
        self._chklib_search.trace_add("write",
            lambda *_: _build_check_cards(self._chklib_search.get()))

    # ── Report View ─────────────────────────────────────────────

    def _show_report(self):
        self._clear_content()
        self.current_view = "report"
        self._navigate_highlight("report")

        pad = tk.Frame(self.content_frame, bg=Theme.BG_DEEP, padx=32, pady=24)
        pad.pack(fill="both", expand=True)

        tk.Label(pad, text="Reports", font=("Segoe UI", 22, "bold"),
                fg=Theme.ACCENT, bg=Theme.BG_DEEP).pack(anchor="w")
        tk.Label(pad, text="Generate and export diagnostic reports",
                font=("Segoe UI", 11), fg=Theme.TEXT_DIM,
                bg=Theme.BG_DEEP).pack(anchor="w", pady=(4, 20))

        # Report options
        options_card = tk.Frame(pad, bg=Theme.BG_CARD, padx=20, pady=20)
        options_card.pack(fill="x", pady=(0, 16))

        tk.Label(options_card, text="HTML Report", font=("Segoe UI", 14, "bold"),
                fg=Theme.TEXT, bg=Theme.BG_CARD).pack(anchor="w")
        tk.Label(options_card, text="Shareable dark-themed diagnostic report with A-F grading, "
                "issue details, and 'Why This Matters' explanations.",
                font=("Segoe UI", 10), fg=Theme.TEXT_DIM,
                bg=Theme.BG_CARD, wraplength=600, justify="left").pack(anchor="w", pady=(4, 16))

        btn_row = tk.Frame(options_card, bg=Theme.BG_CARD)
        btn_row.pack(fill="x")

        tk.Button(btn_row, text="  Export HTML Report  ",
                 font=("Segoe UI", 11, "bold"), fg=Theme.BG_DEEP,
                 bg=Theme.ACCENT, bd=0, padx=20, pady=10, cursor="hand2",
                 activebackground=Theme.ACCENT_DIM,
                 command=self._export_report).pack(side="left")

        if not self.scanner.results:
            tk.Label(btn_row, text="Run a scan first to generate a report",
                    font=("Segoe UI", 9), fg=Theme.TEXT_MUTED,
                    bg=Theme.BG_CARD).pack(side="left", padx=(16, 0))

        # JSON export
        json_card = tk.Frame(pad, bg=Theme.BG_CARD, padx=20, pady=20)
        json_card.pack(fill="x", pady=(0, 16))

        tk.Label(json_card, text="JSON Export", font=("Segoe UI", 14, "bold"),
                fg=Theme.TEXT, bg=Theme.BG_CARD).pack(anchor="w")
        tk.Label(json_card, text="Machine-readable scan results for CI/CD pipeline integration.",
                font=("Segoe UI", 10), fg=Theme.TEXT_DIM,
                bg=Theme.BG_CARD).pack(anchor="w", pady=(4, 16))

        tk.Button(json_card, text="  Export JSON  ",
                 font=("Segoe UI", 11), fg=Theme.TEXT,
                 bg=Theme.BG_SURFACE, bd=0, padx=20, pady=10, cursor="hand2",
                 activebackground=Theme.BG_HOVER,
                 command=self._export_json).pack(side="left")

    # ── Settings View ───────────────────────────────────────────

    def _show_settings(self):
        self._clear_content()
        self.current_view = "settings"
        self._navigate_highlight("settings")

        canvas = tk.Canvas(self.content_frame, bg=Theme.BG_DEEP, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.content_frame, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=Theme.BG_DEEP)

        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        pad = tk.Frame(scroll_frame, bg=Theme.BG_DEEP, padx=32, pady=24)
        pad.pack(fill="both", expand=True)

        tk.Label(pad, text="Settings", font=("Segoe UI", 22, "bold"),
                fg=Theme.ACCENT, bg=Theme.BG_DEEP).pack(anchor="w")
        tk.Label(pad, text="Configure BP Doctor behavior and checks",
                font=("Segoe UI", 11), fg=Theme.TEXT_DIM,
                bg=Theme.BG_DEEP).pack(anchor="w", pady=(4, 20))

        # ── Experience Mode ──
        mode_card = tk.Frame(pad, bg=Theme.BG_CARD, padx=20, pady=20)
        mode_card.pack(fill="x", pady=(0, 16))

        tk.Label(mode_card, text="Experience Mode",
                font=("Segoe UI", 14, "bold"), fg=Theme.TEXT,
                bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 4))
        tk.Label(mode_card,
                text="Controls how much guidance and detail is shown "
                     "throughout the app",
                font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 12))

        current_mode = self.settings.get("experience_mode", "intermediate")
        mode_btns_frame = tk.Frame(mode_card, bg=Theme.BG_CARD)
        mode_btns_frame.pack(fill="x")

        mode_labels = {}

        def _set_mode(mode_key):
            self.settings.set("experience_mode", mode_key)
            for mk, (btn_f, name_l, desc_l, ind_l) in mode_labels.items():
                if mk == mode_key:
                    btn_f.configure(bg=Theme.BG_HOVER)
                    name_l.configure(fg=Theme.ACCENT, bg=Theme.BG_HOVER)
                    desc_l.configure(bg=Theme.BG_HOVER)
                    ind_l.configure(text="\u25C9", fg=Theme.ACCENT,
                                   bg=Theme.BG_HOVER)
                else:
                    btn_f.configure(bg=Theme.BG_SURFACE)
                    name_l.configure(fg=Theme.TEXT, bg=Theme.BG_SURFACE)
                    desc_l.configure(bg=Theme.BG_SURFACE)
                    ind_l.configure(text="\u25CB", fg=Theme.TEXT_MUTED,
                                   bg=Theme.BG_SURFACE)

        for mode_key, mode_info in ExperienceMode.MODES.items():
            is_active = (mode_key == current_mode)
            bg = Theme.BG_HOVER if is_active else Theme.BG_SURFACE

            btn_f = tk.Frame(mode_btns_frame, bg=bg, padx=12, pady=8,
                            cursor="hand2")
            btn_f.pack(fill="x", pady=2)

            ind_text = "\u25C9" if is_active else "\u25CB"
            ind_color = Theme.ACCENT if is_active else Theme.TEXT_MUTED
            ind_l = tk.Label(btn_f, text=ind_text, font=("Segoe UI", 14),
                            fg=ind_color, bg=bg)
            ind_l.pack(side="left", padx=(0, 8))

            name_color = Theme.ACCENT if is_active else Theme.TEXT
            name_l = tk.Label(btn_f, text=mode_info["label"],
                             font=("Segoe UI", 11, "bold"),
                             fg=name_color, bg=bg, width=12, anchor="w")
            name_l.pack(side="left")

            desc_l = tk.Label(btn_f, text=mode_info["desc"],
                             font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                             bg=bg)
            desc_l.pack(side="left", padx=(4, 0))

            mode_labels[mode_key] = (btn_f, name_l, desc_l, ind_l)

            def _make_click(mk):
                return lambda _e: _set_mode(mk)
            btn_f.bind("<Button-1>", _make_click(mode_key))
            for child in btn_f.winfo_children():
                child.bind("<Button-1>", _make_click(mode_key))

        # Enabled Checks
        checks_card = tk.Frame(pad, bg=Theme.BG_CARD, padx=20, pady=20)
        checks_card.pack(fill="x", pady=(0, 16))

        tk.Label(checks_card, text="Enabled Checks", font=("Segoe UI", 14, "bold"),
                fg=Theme.TEXT, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 12))

        self.check_vars = {}
        enabled_checks = self.settings.get("checks_enabled", {})
        _sev_ord = {"ERROR": 0, "WARNING": 1, "INFO": 2}
        for check in sorted(CHECKS,
                             key=lambda c: _sev_ord.get(c.severity.value, 9)):
            sev_color = Theme.severity_color(check.severity.value)
            var = tk.BooleanVar(value=enabled_checks.get(check.code, True))
            self.check_vars[check.code] = var

            row = tk.Frame(checks_card, bg=Theme.BG_CARD)
            row.pack(fill="x", pady=2)

            cb = tk.Checkbutton(row, variable=var, bg=Theme.BG_CARD,
                               selectcolor=Theme.BG_SURFACE,
                               activebackground=Theme.BG_CARD,
                               command=self._save_check_settings)
            cb.pack(side="left")

            tk.Label(row, text=check.severity.value, font=("Segoe UI", 8, "bold"),
                    fg=sev_color, bg=Theme.BG_CARD, width=8).pack(side="left")
            tk.Label(row, text=check.name, font=("Segoe UI", 10),
                    fg=Theme.TEXT, bg=Theme.BG_CARD).pack(side="left", padx=(4, 0))

            if check.auto_fixable:
                tk.Label(row, text="AUTO-FIX", font=("Segoe UI", 7, "bold"),
                        fg=Theme.ACCENT, bg=Theme.BG_CARD).pack(side="right")

        # General Settings
        general_card = tk.Frame(pad, bg=Theme.BG_CARD, padx=20, pady=20)
        general_card.pack(fill="x", pady=(0, 16))

        tk.Label(general_card, text="General", font=("Segoe UI", 14, "bold"),
                fg=Theme.TEXT, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 12))

        # Auto-scan toggle
        auto_var = tk.BooleanVar(value=self.settings.get("auto_scan_on_open", True))
        auto_row = tk.Frame(general_card, bg=Theme.BG_CARD)
        auto_row.pack(fill="x", pady=2)
        tk.Checkbutton(auto_row, text="Auto-scan when project is opened",
                      variable=auto_var, font=("Segoe UI", 10),
                      fg=Theme.TEXT, bg=Theme.BG_CARD,
                      selectcolor=Theme.BG_SURFACE,
                      activebackground=Theme.BG_CARD,
                      command=lambda: self.settings.set("auto_scan_on_open", auto_var.get())
                      ).pack(anchor="w")

        # ── Color Scheme ──
        scheme_card = tk.Frame(pad, bg=Theme.BG_CARD, padx=20, pady=20)
        scheme_card.pack(fill="x", pady=(0, 16))

        tk.Label(scheme_card, text="Color Scheme",
                font=("Segoe UI", 14, "bold"), fg=Theme.TEXT,
                bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 4))
        tk.Label(scheme_card,
                text="Choose a theme for BP Doctor's interface",
                font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 12))

        active_scheme = self.settings.get("color_scheme", "Doctor Dark")
        swatch_keys = ["BG_DEEP", "BG_CARD", "ACCENT", "SUCCESS",
                        "WARNING", "ERROR", "INFO", "MAGENTA"]

        for scheme_name, scheme_colors in COLOR_SCHEMES.items():
            is_active = (scheme_name == active_scheme)
            row_bg = Theme.BG_HOVER if is_active else Theme.BG_SURFACE

            row = tk.Frame(scheme_card, bg=row_bg, padx=12, pady=8,
                          cursor="hand2")
            row.pack(fill="x", pady=2)

            # Selection indicator
            indicator = "\u25C9" if is_active else "\u25CB"
            ind_color = Theme.ACCENT if is_active else Theme.TEXT_MUTED
            tk.Label(row, text=indicator, font=("Segoe UI", 14),
                    fg=ind_color, bg=row_bg).pack(side="left", padx=(0, 8))

            # Scheme name
            name_color = Theme.ACCENT if is_active else Theme.TEXT
            tk.Label(row, text=scheme_name,
                    font=("Segoe UI", 11,
                          "bold" if is_active else ""),
                    fg=name_color, bg=row_bg, width=14,
                    anchor="w").pack(side="left")

            # Color swatch strip
            swatch_frame = tk.Frame(row, bg=row_bg)
            swatch_frame.pack(side="left", padx=(8, 0))
            for sk in swatch_keys:
                color = scheme_colors.get(sk, "#333333")
                swatch = tk.Frame(swatch_frame, bg=color,
                                 width=24, height=18)
                swatch.pack(side="left", padx=1)
                swatch.pack_propagate(False)

            # Active label
            if is_active:
                tk.Label(row, text="ACTIVE",
                        font=("Segoe UI", 8, "bold"),
                        fg=Theme.ACCENT, bg=row_bg).pack(side="right")

            # Bind click on entire row
            def _make_apply(sn):
                return lambda _e: self._apply_color_scheme(sn)
            row.bind("<Button-1>", _make_apply(scheme_name))
            for child in row.winfo_children():
                child.bind("<Button-1>", _make_apply(scheme_name))

        # Directory Mapping
        dir_card = tk.Frame(pad, bg=Theme.BG_CARD, padx=20, pady=20)
        dir_card.pack(fill="x", pady=(0, 16))

        tk.Label(dir_card, text="Directory Mapping",
                font=("Segoe UI", 14, "bold"), fg=Theme.TEXT,
                bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 4))
        tk.Label(dir_card,
                text="Configure where your project assets are located. "
                     "Used by templates and script import.",
                font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 12))

        project = self.project_path_var.get()
        proj_config = None
        if project and project != "No project selected" and os.path.isdir(project):
            proj_config = ProjectConfig(project)

        dir_entries = {}
        dir_labels = {
            "skeletal_meshes": "Skeletal Meshes",
            "animations": "Animations",
            "montages": "Montages",
            "animbps": "AnimBlueprints",
            "blend_spaces": "BlendSpaces",
        }
        defaults = ProjectConfig._defaults(None) if not proj_config else proj_config.data
        dirs_data = defaults.get("directories", {}) if not proj_config else proj_config.data.get("directories", {})

        for key, label in dir_labels.items():
            row = tk.Frame(dir_card, bg=Theme.BG_CARD)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, font=("Segoe UI", 10, "bold"),
                    fg=Theme.TEXT, bg=Theme.BG_CARD,
                    width=18, anchor="w").pack(side="left")
            entry = tk.Entry(row, font=("Segoe UI", 9),
                            bg=Theme.BG_INPUT, fg=Theme.TEXT,
                            insertbackground=Theme.TEXT, bd=0, relief="flat")
            current = dirs_data.get(key, [])
            entry.insert(0, ", ".join(current) if isinstance(current, list) else str(current))
            entry.pack(side="left", fill="x", expand=True, ipady=4)
            dir_entries[key] = entry

        # Variable Mapping
        var_card = tk.Frame(pad, bg=Theme.BG_CARD, padx=20, pady=20)
        var_card.pack(fill="x", pady=(0, 16))

        tk.Label(var_card, text="Variable Mapping",
                font=("Segoe UI", 14, "bold"), fg=Theme.TEXT,
                bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 4))
        tk.Label(var_card,
                text="Map logical variable names to your AnimInstance property names.",
                font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 12))

        var_entries = {}
        var_data = (proj_config.data.get("variable_mapping", {}) if proj_config
                   else defaults.get("variable_mapping", {}))
        for vkey, vval in var_data.items():
            row = tk.Frame(var_card, bg=Theme.BG_CARD)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=vkey, font=("Segoe UI", 10),
                    fg=Theme.TEXT_DIM, bg=Theme.BG_CARD,
                    width=18, anchor="w").pack(side="left")
            tk.Label(row, text="\u2192", fg=Theme.ACCENT,
                    bg=Theme.BG_CARD).pack(side="left", padx=4)
            entry = tk.Entry(row, font=("Segoe UI", 9),
                            bg=Theme.BG_INPUT, fg=Theme.TEXT,
                            insertbackground=Theme.TEXT, bd=0, relief="flat")
            entry.insert(0, vval)
            entry.pack(side="left", fill="x", expand=True, ipady=4)
            var_entries[vkey] = entry

        # Save project config button
        def save_project_config():
            proj = self.project_path_var.get()
            if not proj or proj == "No project selected":
                messagebox.showwarning("No Project",
                    "Select a project first to save project config.")
                return
            pc = ProjectConfig(proj)
            for k, e in dir_entries.items():
                val = [d.strip() for d in e.get().split(",") if d.strip()]
                pc.set_val(["directories", k], val)
            for k, e in var_entries.items():
                pc.set_val(["variable_mapping", k], e.get().strip())
            pc.save()
            self._update_status("Project configuration saved")
            messagebox.showinfo("Saved",
                f"Project config saved to:\n"
                f"{pc.config_path}")

        tk.Button(pad, text="  Save Project Config  ",
                 font=("Segoe UI", 10, "bold"), fg=Theme.BG_DEEP,
                 bg=Theme.ACCENT, bd=0, padx=16, pady=8, cursor="hand2",
                 command=save_project_config).pack(anchor="w", pady=(0, 16))

        # About
        about_card = tk.Frame(pad, bg=Theme.BG_CARD, padx=20, pady=20)
        about_card.pack(fill="x", pady=(0, 16))

        tk.Label(about_card, text="About", font=("Segoe UI", 14, "bold"),
                fg=Theme.TEXT, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 8))
        tk.Label(about_card, text="BP Doctor v2.5",
                font=("Segoe UI", 10), fg=Theme.TEXT,
                bg=Theme.BG_CARD).pack(anchor="w")
        tk.Label(about_card, text="BP Doctor  |  Animation Blueprint Diagnostics & Automation for UE5",
                font=("Segoe UI", 10), fg=Theme.TEXT_DIM,
                bg=Theme.BG_CARD).pack(anchor="w")
        tk.Label(about_card,
                text=f"{len(CHECKS)} checks  |  Auto-fix with preview & revert  |  Templates  |  Script import  |  HTML reports",
                font=("Segoe UI", 9), fg=Theme.TEXT_MUTED,
                bg=Theme.BG_CARD).pack(anchor="w", pady=(4, 0))

    # ── Shared Components ───────────────────────────────────────

    def _build_results_tree(self, parent, results, show_checkboxes=True):
        """Build the results treeview table with optional fix checkboxes."""
        tree_frame = tk.Frame(parent, bg=Theme.BG_CARD)
        tree_frame.pack(fill="both", expand=True)

        columns = ("sel", "severity", "asset_type", "animblueprint", "check", "description", "fix")
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings",
                           selectmode="browse")

        tree.heading("sel",           text="\u2611", anchor="center")
        tree.heading("severity",     text="Severity", anchor="w")
        tree.heading("asset_type",   text="Type",     anchor="w")
        tree.heading("animblueprint", text="Blueprint", anchor="w")
        tree.heading("check",        text="Check",     anchor="w")
        tree.heading("description",  text="Description", anchor="w")
        tree.heading("fix",          text="Fix",       anchor="center")

        tree.column("sel",          width=32,  minwidth=32, stretch=False, anchor="center")
        tree.column("severity",     width=80,  minwidth=60, stretch=False)
        tree.column("asset_type",   width=70,  minwidth=55, stretch=False)
        tree.column("animblueprint", width=140, minwidth=100)
        tree.column("check",        width=160, minwidth=120)
        tree.column("description",  width=330, minwidth=200)
        tree.column("fix",          width=70,  minwidth=50, stretch=False)

        # Hide the "sel" column when checkboxes are disabled
        if not show_checkboxes:
            tree.configure(displaycolumns=(
                "severity", "asset_type", "animblueprint",
                "check", "description", "fix"))

        # Add scrollbar
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)

        # Tag colors
        tree.tag_configure("error",   foreground=Theme.ERROR)
        tree.tag_configure("warning", foreground=Theme.WARNING)
        tree.tag_configure("info",    foreground=Theme.INFO)

        # Initialize checkbox state tracker if needed
        if not hasattr(self, '_fix_checked'):
            self._fix_checked = {}

        # Sort by severity: ERROR → WARNING → INFO
        _sev_sort = {"ERROR": 0, "WARNING": 1, "INFO": 2}
        results = sorted(results, key=lambda r: _sev_sort.get(r.severity, 9))

        # Populate
        for r in results:
            tag = r.severity.lower()
            fix_text = "AUTO-FIX" if r.auto_fixable else "--"
            check_def = CHECK_MAP.get(r.check_code)
            check_name = check_def.name if check_def else r.check_code
            type_label = "AnimBP" if r.asset_type == "AnimBP" else "BP"

            # Stable key for checkbox state that survives filter rebuilds
            state_key = (r.check_code, r.animblueprint, r.description[:60])
            if show_checkboxes and r.auto_fixable:
                # Default new fixable items to checked
                if state_key not in self._fix_checked:
                    self._fix_checked[state_key] = True
                sel_text = "\u2611" if self._fix_checked[state_key] else "\u2610"
            else:
                sel_text = ""

            tree.insert("", "end", values=(
                sel_text, r.severity, type_label, r.animblueprint, check_name,
                r.description[:80], fix_text
            ), tags=(tag,))

        # Store tree + results on self for access from buttons
        self._results_tree = tree
        self._results_tree_data = results

        # Checkbox click handler
        if show_checkboxes:
            def on_click(event):
                col = tree.identify_column(event.x)
                row = tree.identify_row(event.y)
                if col == "#1" and row:  # "#1" is the "sel" column
                    idx = tree.index(row)
                    if idx < len(results):
                        r = results[idx]
                        if r.auto_fixable:
                            state_key = (r.check_code, r.animblueprint, r.description[:60])
                            current = self._fix_checked.get(state_key, True)
                            self._fix_checked[state_key] = not current
                            new_text = "\u2611" if not current else "\u2610"
                            vals = list(tree.item(row, "values"))
                            vals[0] = new_text
                            tree.item(row, values=vals)
                            self._update_autofix_button()
                    return  # don't trigger row selection for checkbox clicks
            tree.bind("<Button-1>", on_click)

        # Bind selection for detail view (only when not clicking checkbox column)
        def on_select(event):
            sel = tree.selection()
            if sel:
                idx = tree.index(sel[0])
                if idx < len(results):
                    self._show_issue_detail(results[idx])
        tree.bind("<<TreeviewSelect>>", on_select)

        # Right-click context menu
        ctx_menu = tk.Menu(tree, tearoff=0, bg=Theme.BG_CARD, fg=Theme.TEXT,
                          activebackground=Theme.BG_HOVER, activeforeground=Theme.ACCENT,
                          font=("Segoe UI", 10))
        ctx_menu.add_command(label="Copy Issue Details",
            command=lambda: self._copy_issue(tree, results, "details"))
        ctx_menu.add_command(label="Copy Blueprint Path",
            command=lambda: self._copy_issue(tree, results, "path"))
        ctx_menu.add_separator()
        ctx_menu.add_command(label="View Fix Guide",
            command=lambda: self._show_fix_from_tree(tree, results))

        def show_ctx(event):
            row = tree.identify_row(event.y)
            if row:
                tree.selection_set(row)
                ctx_menu.post(event.x_root, event.y_root)
        tree.bind("<Button-3>", show_ctx)

        # Update the Auto Fix button count
        self._update_autofix_button()

        return tree

    def _show_issue_detail(self, result: ScanResult):
        """Show detail popup with issue info + inline fix guide."""
        detail_win = tk.Toplevel(self.root)
        detail_win.title(f"Issue Detail — {result.check_code}")
        detail_win.geometry("650x700")
        detail_win.configure(bg=Theme.BG_DEEP)
        detail_win.transient(self.root)

        # Scrollable content
        canvas = tk.Canvas(detail_win, bg=Theme.BG_DEEP, highlightthickness=0)
        scrollbar = ttk.Scrollbar(detail_win, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=Theme.BG_DEEP)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        def _detail_scroll(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _detail_scroll))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        detail_win.protocol("WM_DELETE_WINDOW",
            lambda: (canvas.unbind_all("<MouseWheel>"), detail_win.destroy()))
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        pad = tk.Frame(scroll_frame, bg=Theme.BG_DEEP, padx=24, pady=20)
        pad.pack(fill="both", expand=True)

        check_def = CHECK_MAP.get(result.check_code)
        sev_color = Theme.severity_color(result.severity)

        # Header
        tk.Label(pad, text=result.severity, font=("Segoe UI", 10, "bold"),
                fg=sev_color, bg=Theme.BG_DEEP).pack(anchor="w")
        tk.Label(pad, text=check_def.name if check_def else result.check_code,
                font=("Segoe UI", 18, "bold"), fg=Theme.TEXT,
                bg=Theme.BG_DEEP).pack(anchor="w", pady=(4, 8))

        # AnimBP info
        info_card = tk.Frame(pad, bg=Theme.BG_CARD, padx=16, pady=10)
        info_card.pack(fill="x", pady=(0, 10))
        tk.Label(info_card, text=result.animblueprint, font=("Segoe UI", 12, "bold"),
                fg=Theme.ACCENT, bg=Theme.BG_CARD).pack(anchor="w")
        tk.Label(info_card, text=result.asset_path, font=("Segoe UI", 9),
                fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD).pack(anchor="w")

        # Description
        tk.Label(pad, text=result.description, font=("Segoe UI", 10),
                fg=Theme.TEXT, bg=Theme.BG_DEEP, wraplength=580,
                justify="left").pack(anchor="w", pady=(4, 8))

        # Node hint
        if result.node_hint:
            hint_f = tk.Frame(pad, bg=Theme.BG_SURFACE, padx=12, pady=8)
            hint_f.pack(fill="x", pady=(0, 8))
            tk.Label(hint_f, text=result.node_hint, font=("Consolas", 10),
                    fg=Theme.ACCENT, bg=Theme.BG_SURFACE).pack(anchor="w")

        # Confidence + Type badges
        if check_def:
            badge_frame = tk.Frame(pad, bg=Theme.BG_DEEP)
            badge_frame.pack(anchor="w", pady=(0, 8))
            conf = getattr(check_def, 'confidence', None)
            if conf:
                conf_colors = {"HIGH": Theme.SUCCESS, "MEDIUM": Theme.WARNING, "LOW": Theme.TEXT_MUTED}
                conf_color = conf_colors.get(conf.value, Theme.TEXT_DIM)
                tk.Label(badge_frame, text=f" {conf.value} CONFIDENCE ",
                        font=("Segoe UI", 8, "bold"), fg=Theme.BG_DEEP,
                        bg=conf_color, padx=6, pady=2).pack(side="left", padx=(0, 8))
            type_color = Theme.MAGENTA if result.asset_type == "AnimBP" else Theme.INFO
            tk.Label(badge_frame, text=f" {result.asset_type} ",
                    font=("Segoe UI", 8, "bold"), fg=Theme.BG_DEEP,
                    bg=type_color, padx=6, pady=2).pack(side="left")

        # Beginner tip (plain English explanation)
        if check_def and getattr(check_def, 'beginner_tip', ''):
            tip_frame = tk.Frame(pad, bg="#1a2a1a", padx=14, pady=10)
            tip_frame.pack(fill="x", pady=(0, 10))
            tk.Label(tip_frame, text="WHAT THIS MEANS (PLAIN ENGLISH)",
                    font=("Segoe UI", 8, "bold"), fg=Theme.SUCCESS,
                    bg="#1a2a1a").pack(anchor="w")
            tk.Label(tip_frame, text=check_def.beginner_tip,
                    font=("Segoe UI", 10), fg=Theme.TEXT,
                    bg="#1a2a1a", wraplength=560, justify="left"
                    ).pack(anchor="w", pady=(4, 0))

        # Why it matters (technical detail for experienced devs)
        if check_def:
            why_frame = tk.Frame(pad, bg=Theme.BG_CARD, padx=14, pady=10)
            why_frame.pack(fill="x", pady=(0, 12))
            tk.Label(why_frame, text="WHY THIS MATTERS (TECHNICAL)",
                    font=("Segoe UI", 8, "bold"), fg=Theme.ACCENT,
                    bg=Theme.BG_CARD).pack(anchor="w")
            tk.Label(why_frame, text=check_def.why_it_matters,
                    font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                    bg=Theme.BG_CARD, wraplength=560, justify="left"
                    ).pack(anchor="w", pady=(4, 0))

        # Suppress button
        if hasattr(self, 'scanner') and self.scanner and self.scanner.project_path:
            supp_frame = tk.Frame(pad, bg=Theme.BG_DEEP)
            supp_frame.pack(fill="x", pady=(0, 8))

            def _do_suppress():
                reason = supp_entry.get().strip() or "Suppressed from GUI"
                supp = SuppressionManager(self.scanner.project_path)
                supp.suppress(result.asset_path, result.check_code, reason=reason)
                supp_btn.configure(text="Suppressed", state="disabled", bg=Theme.TEXT_MUTED)
                self._update_status(f"Suppressed {result.check_code} on {result.animblueprint}")

            supp_entry = tk.Entry(supp_frame, font=("Segoe UI", 9), fg=Theme.TEXT,
                                  bg=Theme.BG_INPUT, insertbackground=Theme.TEXT,
                                  bd=0, width=35)
            supp_entry.insert(0, "Reason (optional)")
            supp_entry.bind("<FocusIn>", lambda e: supp_entry.delete(0, "end")
                            if supp_entry.get() == "Reason (optional)" else None)
            supp_entry.pack(side="left", padx=(0, 8), ipady=4)

            supp_btn = tk.Button(supp_frame, text="Suppress This Issue",
                                 font=("Segoe UI", 9), fg=Theme.TEXT,
                                 bg=Theme.BG_SURFACE, bd=0, padx=10, pady=4,
                                 cursor="hand2", command=_do_suppress)
            supp_btn.pack(side="left")

            # Check if already suppressed
            try:
                supp_check = SuppressionManager(self.scanner.project_path)
                if supp_check.is_suppressed(result.asset_path, result.check_code):
                    supp_btn.configure(text="Already Suppressed", state="disabled",
                                       bg=Theme.TEXT_MUTED)
            except Exception:
                pass

        # Inline Fix Guide (imported from AnimBPFixGuide data)
        fix_data = self._get_fix_guide(result.check_code)
        if fix_data:
            sep = tk.Frame(pad, bg=Theme.ACCENT, height=2)
            sep.pack(fill="x", pady=(8, 12))

            tk.Label(pad, text="HOW TO FIX", font=("Segoe UI", 12, "bold"),
                    fg=Theme.ACCENT, bg=Theme.BG_DEEP).pack(anchor="w", pady=(0, 10))

            for i, (step_title, step_text) in enumerate(fix_data, 1):
                step_f = tk.Frame(pad, bg=Theme.BG_CARD, padx=14, pady=10)
                step_f.pack(fill="x", pady=(0, 4))

                header_row = tk.Frame(step_f, bg=Theme.BG_CARD)
                header_row.pack(fill="x")
                tk.Label(header_row, text=str(i), font=("Segoe UI", 10, "bold"),
                        fg=Theme.BG_DEEP, bg=Theme.ACCENT, width=3).pack(side="left", padx=(0, 10))
                tk.Label(header_row, text=step_title, font=("Segoe UI", 10, "bold"),
                        fg=Theme.TEXT, bg=Theme.BG_CARD).pack(side="left")

                tk.Label(step_f, text=step_text, font=("Segoe UI", 9),
                        fg=Theme.TEXT_DIM, bg=Theme.BG_CARD, wraplength=540,
                        justify="left").pack(anchor="w", pady=(6, 0))

        # Copy button
        btn_row = tk.Frame(pad, bg=Theme.BG_DEEP)
        btn_row.pack(fill="x", pady=(12, 0))
        tk.Button(btn_row, text="  Copy Details  ", font=("Segoe UI", 10),
                 fg=Theme.ACCENT, bg=Theme.BG_CARD, bd=0, padx=16, pady=8,
                 cursor="hand2",
                 command=lambda: self._copy_single_issue(result)).pack(side="left")

    # ── Nav Highlight Helper ────────────────────────────────────

    def _navigate_highlight(self, active_key):
        for key, btn in self.nav_buttons.items():
            if key == active_key:
                btn.configure(fg=Theme.ACCENT, font=("Segoe UI", 10, "bold"),
                            bg=Theme.BG_HOVER)
            else:
                btn.configure(fg=Theme.TEXT_DIM, font=("Segoe UI", 10),
                            bg=Theme.BG_SURFACE)

    # ── Actions ─────────────────────────────────────────────────

    def _browse_project(self):
        path = filedialog.askdirectory(title="Select UE5 Project Folder")
        if path:
            self.project_path_var.set(path)
            self.settings.set("project_path", path)

            # Add to recent projects
            recent = self.settings.get("recent_projects", [])
            if path not in recent:
                recent.insert(0, path)
                recent = recent[:10]
                self.settings.set("recent_projects", recent)

            self._update_status(f"Project: {os.path.basename(path)}")

    def _run_scan(self):
        if self.is_scanning:
            messagebox.showinfo("Scan Running",
                "A scan is already in progress. Please wait for it to finish.")
            return

        if DEMO_MODE and not _demo_gate.can_scan():
            messagebox.showinfo("Demo Complete",
                "Your free scan has been used.\n\n"
                "You've seen what BP Doctor finds — upgrade to Pro for:\n\n"
                "  +  Unlimited scans\n"
                "  +  8 auto-fixes (one-click repair)\n"
                "  +  26 step-by-step fix guides\n"
                "  +  CLI mode for CI/CD pipelines\n"
                "  +  HTML, JSON, SARIF report export\n\n"
                "bpdoctor.gumroad.com/l/pro")
            return

        path = self.project_path_var.get()
        if not path or path == "No project selected":
            messagebox.showwarning("No Project",
                "Please select a UE5 project folder first.\n\n"
                "Click 'Browse Project' in the sidebar or Scanner view.")
            return

        if not os.path.isdir(path):
            messagebox.showerror("Invalid Path",
                f"The selected path does not exist:\n{path}")
            return

        self.is_scanning = True
        self._scan_in_progress = True
        self._update_status("Scanning...")

        def scan_thread():
            def on_progress(current, total, msg):
                if not self.is_scanning or total <= 0:
                    return
                pct = (current / total) * 100
                p, m = pct, msg  # capture values for lambda
                self.root.after(0, lambda: self.progress_var.set(p))
                self.root.after(0, lambda: self._update_progress(m))

            self.scanner = ScannerEngine()
            self.scanner.on_progress = on_progress

            try:
                results = self.scanner.scan_all(path)
                self.root.after(0, lambda: self._on_scan_complete(results))
            except Exception as e:
                self.root.after(0, lambda: self._on_scan_error(str(e)))

        thread = threading.Thread(target=scan_thread, daemon=True)
        thread.start()

    def _on_scan_complete(self, results):
        self.is_scanning = False
        self._scan_in_progress = False
        _demo_gate.record_scan()
        self.progress_var.set(100)

        total = len(results)
        abp_count = len(self.scanner.animblueprints)
        grade = self.scanner.get_overall_grade()
        duration = self.scanner.scan_duration

        errors = sum(1 for r in results if r.severity == "ERROR")
        warnings = sum(1 for r in results if r.severity == "WARNING")
        infos = sum(1 for r in results if r.severity == "INFO")

        # Record to scan history
        project = self.project_path_var.get()
        self.scan_history.record(project, grade, abp_count,
                                errors, warnings, infos, duration)

        # Build status with timing and trend
        prev = self.scan_history.get_previous(project)
        trend = ""
        if prev:
            prev_issues = prev.get("total_issues", 0)
            delta = prev_issues - total
            if delta > 0:
                trend = f" | +{delta} fixed since last scan"
            elif delta < 0:
                trend = f" | {abs(delta)} new issues since last scan"

        # Estimate time saved
        time_saved = self._estimate_time_saved(results)

        self._update_status(
            f"Scanned {abp_count} Blueprints in {duration:.1f}s | "
            f"{total} issues | Grade: {grade}{trend}")
        self.status_right.configure(
            text=f"Est. time saved: {time_saved} | "
                 f"Last scan: {datetime.now().strftime('%I:%M %p')}")

        # Notification bell + window flash
        try:
            self.root.bell()
            self.root.attributes('-topmost', True)
            self.root.after(200, lambda: self.root.attributes('-topmost', False))
        except tk.TclError:
            pass

        # Refresh current view
        if self.current_view == "dashboard":
            self._show_dashboard()
        elif self.current_view == "scanner":
            self._show_scanner()

    def _estimate_time_saved(self, results) -> str:
        """Estimate manual inspection time replaced by this scan.

        Methodology: Each check replaces a specific manual inspection action.
        Time is based on the mechanical steps a developer would need to perform
        to find each issue type WITHOUT this tool, measured per-AnimBP:

        - Open AnimBP in editor:                          ~5s
        - Navigate to AnimGraph tab:                      ~3s
        - Per-node visual inspection (click, read props): ~10s/node
        - Cross-reference asset (open anim, check skel):  ~20s/ref
        - State machine traversal (trace each path):      ~15s/state
        - Search graph for specific node type:             ~8s/search

        These per-step timings are conservative lower bounds based on
        UE5 editor interaction speed. Total = steps x time-per-step.
        Only counts the FINDING time, not the fixing time.
        """
        # Minutes of manual inspection replaced per check type per AnimBP
        # Based on: number of nodes/refs to inspect x seconds per inspection
        INSPECTION_MINUTES_PER_ABP = {
            "NULL_ANIM_REF":    1.5,   # Click each SequencePlayer (~10), verify anim assigned (10s each)
            "BROKEN_BLEND_WT":  1.0,   # Find blend nodes (~5), inspect weight values (12s each)
            "SKEL_MISMATCH":    3.0,   # Open each referenced anim (~8), compare skeleton (20s each)
            "MISSING_SLOT":     0.5,   # Search graph for "Slot" node (one search, ~30s)
            "BROKEN_TRANS":     4.0,   # Trace every state's inbound transitions (~15 states x 15s)
            "TPOSE_FALLBACK":   1.5,   # Find LayeredBoneBlend nodes, check BasePose pin (~3 nodes x 30s)
            "ORPHANED_NODE":    2.0,   # Zoom out, visually trace connectivity from Output Pose (~2 min)
            "INVALID_BSPACE":   1.0,   # Open each BlendSpace asset, count samples (~4 x 15s)
            "MISSING_NOTIFY":   2.0,   # Open each anim sequence, scan notifies track (~6 anims x 20s)
            "DUP_SLOT":         0.5,   # Search for "Slot" nodes, compare names (~30s)
            "UNUSED_VAR":       1.5,   # For each variable, right-click > Find References (~6 vars x 15s)
            "DEPRECATED_NODE":  0.5,   # Check compiler results for deprecation warnings (~30s)
            # General Blueprint checks
            "BP_BROKEN_REF":    2.0,   # Find broken refs: open BP, trace each red node (~4 refs x 30s)
            "BP_COMPLEXITY":    3.0,   # Manual complexity audit: count nodes, trace paths (~3 min)
            "BP_EMPTY_GRAPH":   0.5,   # Open BP, verify it's empty (~30s)
            "BP_TICK_HEAVY":    2.0,   # Profile Tick: stat unit, trace Tick logic (~2 min)
            "BP_SELF_CAST":     0.5,   # Find and fix self-cast (~30s)
            "BP_DEPRECATED_FUNC": 1.0, # Find and replace deprecated calls (~1 min)
            "BP_CIRCULAR_DEP":  4.0,   # Untangle circular deps: trace refs, restructure (~4 min)
            "BP_MASSIVE_ASSET": 1.5,   # Investigate oversized file: check contents (~90s)
            "BP_HARD_REF":      3.0,   # Open Reference Viewer, trace each hard ref (~6 refs x 30s)
            "BP_EXPENSIVE_TICK": 5.0,  # Profile Tick, identify expensive call, refactor (~5 min)
            "BP_DEBUG_NODES":   1.0,   # Search and delete Print/DrawDebug nodes (~1 min)
            "BP_CONSTRUCT_HEAVY": 3.0, # Move logic from Construction Script to BeginPlay (~3 min)
            "BP_FOREACH_PERF":  1.5,   # Cache array before ForEach loop (~90s)
            "BP_TIMELINE_HEAVY": 2.0,  # Audit and merge Timeline components (~2 min)
        }

        # Count unique ABPs affected per check type (not all ABPs — only those with issues)
        abps_per_check = defaultdict(set)
        for r in results:
            abps_per_check[r.check_code].add(r.animblueprint)

        # Total = (minutes per check type per ABP) x (number of affected ABPs for that check)
        # This represents: "how long to manually inspect the ABPs that actually had issues"
        total_minutes = sum(
            INSPECTION_MINUTES_PER_ABP.get(code, 0.5) * len(affected_abps)
            for code, affected_abps in abps_per_check.items()
        )

        if total_minutes < 1:
            return "< 1 min"
        if total_minutes < 60:
            return f"~{total_minutes:.0f} min"
        hours = total_minutes / 60
        return f"~{hours:.1f} hours"

    def _on_scan_error(self, error_msg):
        self.is_scanning = False
        self._scan_in_progress = False
        self._update_status(f"Scan error: {error_msg}")
        messagebox.showerror("Scan Error", f"An error occurred during scanning:\n\n{error_msg}")

    def _on_close(self):
        """Save window geometry and exit cleanly."""
        self.is_scanning = False  # signal scan thread to stop posting callbacks
        if hasattr(self, 'scanner'):
            self.scanner.cancelled = True  # signal worker threads to abort
        try:
            self.settings.set("window_geometry", self.root.geometry())
        except Exception:
            pass
        self.root.destroy()

    def _focus_search(self):
        """Focus the search bar if it exists in the current view."""
        if hasattr(self, '_search_var'):
            try:
                self._search_entry.focus_set()
            except (tk.TclError, AttributeError):
                pass

    def _clear_search(self):
        """Clear the search bar."""
        if hasattr(self, '_search_var'):
            try:
                self._search_var.set("")
                self._apply_filters()
            except (tk.TclError, AttributeError):
                pass

    def _update_autofix_button(self):
        """Update the Auto Fix button text with the count of checked fixable items."""
        if not hasattr(self, '_autofix_btn'):
            return
        try:
            checked_count = sum(1 for v in self._fix_checked.values() if v)
            total_fixable = sum(1 for r in (self.scanner.results or []) if r.auto_fixable)
            if total_fixable > 0:
                self._autofix_btn.configure(
                    text=f"  Auto Fix ({checked_count}/{total_fixable})  ",
                    state="normal")
            else:
                self._autofix_btn.configure(text="  Auto Fix  ", state="disabled")
        except (tk.TclError, AttributeError):
            pass

    def _fix_selected(self):
        """Fix only the issues checked in the results list."""
        if not self.scanner.results:
            messagebox.showinfo("No Results", "Run a scan first.")
            return

        # Gather checked results
        selected_results = []
        for r in self.scanner.results:
            if r.auto_fixable:
                state_key = (r.check_code, r.animblueprint, r.description[:60])
                if self._fix_checked.get(state_key, False):
                    selected_results.append(r)

        if not selected_results:
            messagebox.showinfo("Nothing Selected",
                "No fixable issues are checked.\n\n"
                "Click the \u2611 checkboxes in the results list to select\n"
                "which issues to auto-fix, or use the dropdown menu\n"
                "to fix all fixable issues at once.")
            return

        # Use the existing preview flow with only selected results
        fix_engine = FixEngine(self.scanner)
        actions = fix_engine.generate_fix_actions(selected_results)
        auto_actions = [a for a in actions if a.fix_type != "manual"]

        if not auto_actions:
            messagebox.showinfo("No Auto-Fixes",
                "Selected issues don't have auto-fix support.")
            return

        # Build preview window (reuse same pattern as _fix_preview_all)
        preview = tk.Toplevel(self.root)
        preview.title("Fix Preview — BP Doctor")
        preview.geometry("720x600")
        preview.configure(bg=Theme.BG_DEEP)
        preview.transient(self.root)
        preview.grab_set()

        tk.Label(preview, text="Fix Preview — Selected Issues",
                font=("Segoe UI", 18, "bold"), fg=Theme.ACCENT,
                bg=Theme.BG_DEEP).pack(anchor="w", padx=20, pady=(16, 4))
        tk.Label(preview,
                text=f"{len(auto_actions)} actions from your selection. Review before executing.",
                font=("Segoe UI", 10), fg=Theme.TEXT_DIM,
                bg=Theme.BG_DEEP).pack(anchor="w", padx=20, pady=(0, 12))

        canvas = tk.Canvas(preview, bg=Theme.BG_DEEP, highlightthickness=0)
        sb = ttk.Scrollbar(preview, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=Theme.BG_DEEP)
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True, padx=20)

        check_vars = []
        for i, action in enumerate(auto_actions):
            var = tk.BooleanVar(value=True)
            check_vars.append(var)

            card = tk.Frame(inner, bg=Theme.BG_CARD, padx=12, pady=10)
            card.pack(fill="x", pady=2)

            top = tk.Frame(card, bg=Theme.BG_CARD)
            top.pack(fill="x")

            tk.Checkbutton(top, variable=var, bg=Theme.BG_CARD,
                          selectcolor=Theme.BG_SURFACE,
                          activebackground=Theme.BG_CARD).pack(side="left")

            type_color = (Theme.WARNING if action.fix_type == "binary_patch"
                         else Theme.INFO)
            type_label = ("PATCH" if action.fix_type == "binary_patch"
                         else "SCRIPT")
            tk.Label(top, text=type_label, font=("Segoe UI", 8, "bold"),
                    fg=type_color, bg=Theme.BG_CARD).pack(side="left", padx=(4, 8))
            tk.Label(top, text=action.animblueprint,
                    font=("Segoe UI", 10, "bold"), fg=Theme.TEXT,
                    bg=Theme.BG_CARD).pack(side="left")
            tk.Label(top, text=action.check_code,
                    font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                    bg=Theme.BG_CARD).pack(side="right")

            tk.Label(card, text=action.preview, font=("Consolas", 9),
                    fg=Theme.TEXT_DIM, bg=Theme.BG_SURFACE,
                    anchor="w", justify="left", padx=8, pady=6,
                    wraplength=640).pack(fill="x", pady=(6, 0))

        btn_bar = tk.Frame(preview, bg=Theme.BG_DEEP)
        btn_bar.pack(fill="x", padx=20, pady=16)

        def do_execute():
            selected = [a for a, v in zip(auto_actions, check_vars) if v.get()]
            if not selected:
                messagebox.showinfo("Nothing Selected", "Select at least one fix.")
                return
            project = self.project_path_var.get()
            fix_engine.backup_mgr = BackupManager(project)
            results = fix_engine.execute_actions(selected, project)

            ok_count = sum(1 for ok, _ in results if ok)
            fail_count = len(results) - ok_count
            details = "\n".join(f"{'OK' if ok else 'FAIL'}: {msg}"
                               for ok, msg in results)

            preview.destroy()
            messagebox.showinfo("Fix Complete",
                f"Executed {len(results)} actions:\n"
                f"  {ok_count} succeeded, {fail_count} failed\n\n"
                f"{details}\n\n"
                f"Use Fix dropdown > 'Revert All' to undo changes.")
            self._update_status(
                f"Fixed {ok_count}/{len(results)} issues | "
                f"Backups: {fix_engine.backup_mgr.get_backup_count()}")

        tk.Button(btn_bar, text="  Execute Selected Fixes  ",
                 font=("Segoe UI", 11, "bold"), fg=Theme.BG_DEEP,
                 bg=Theme.ACCENT, bd=0, padx=20, pady=10, cursor="hand2",
                 command=do_execute).pack(side="left", padx=(0, 8))

        tk.Button(btn_bar, text="  Cancel  ",
                 font=("Segoe UI", 11), fg=Theme.TEXT,
                 bg=Theme.BG_CARD, bd=0, padx=20, pady=10, cursor="hand2",
                 command=preview.destroy).pack(side="left")

        tk.Label(btn_bar, text=f"{len(auto_actions)} actions from {len(selected_results)} selected issues",
                font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                bg=Theme.BG_DEEP).pack(side="right")

    def _fix_preview_all(self):
        """Show preview window of all proposed fixes, then execute on confirm."""
        if not self.scanner.results:
            messagebox.showinfo("No Results", "Run a scan first.")
            return

        fix_engine = FixEngine(self.scanner)
        actions = fix_engine.generate_fix_actions(self.scanner.results)
        auto_actions = [a for a in actions if a.fix_type != "manual"]

        if not auto_actions:
            messagebox.showinfo("No Auto-Fixes",
                "No auto-fixable issues found in current results.\n\n"
                "All issues require manual fixes — click any issue\n"
                "to see step-by-step instructions.")
            return

        # Build preview window
        preview = tk.Toplevel(self.root)
        preview.title("Fix Preview — BP Doctor")
        preview.geometry("720x600")
        preview.configure(bg=Theme.BG_DEEP)
        preview.transient(self.root)
        preview.grab_set()

        # Header
        tk.Label(preview, text="Fix Preview",
                font=("Segoe UI", 18, "bold"), fg=Theme.ACCENT,
                bg=Theme.BG_DEEP).pack(anchor="w", padx=20, pady=(16, 4))
        tk.Label(preview,
                text=f"{len(auto_actions)} actions will be performed. Review before executing.",
                font=("Segoe UI", 10), fg=Theme.TEXT_DIM,
                bg=Theme.BG_DEEP).pack(anchor="w", padx=20, pady=(0, 12))

        # Scrollable action list
        canvas = tk.Canvas(preview, bg=Theme.BG_DEEP, highlightthickness=0)
        sb = ttk.Scrollbar(preview, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=Theme.BG_DEEP)
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True, padx=20)

        # Checkbox vars for each action
        check_vars = []
        for i, action in enumerate(auto_actions):
            var = tk.BooleanVar(value=True)
            check_vars.append(var)

            card = tk.Frame(inner, bg=Theme.BG_CARD, padx=12, pady=10)
            card.pack(fill="x", pady=2)

            top = tk.Frame(card, bg=Theme.BG_CARD)
            top.pack(fill="x")

            tk.Checkbutton(top, variable=var, bg=Theme.BG_CARD,
                          selectcolor=Theme.BG_SURFACE,
                          activebackground=Theme.BG_CARD).pack(side="left")

            type_color = (Theme.WARNING if action.fix_type == "binary_patch"
                         else Theme.INFO)
            type_label = ("PATCH" if action.fix_type == "binary_patch"
                         else "SCRIPT")
            tk.Label(top, text=type_label, font=("Segoe UI", 8, "bold"),
                    fg=type_color, bg=Theme.BG_CARD).pack(side="left", padx=(4, 8))
            tk.Label(top, text=action.animblueprint,
                    font=("Segoe UI", 10, "bold"), fg=Theme.TEXT,
                    bg=Theme.BG_CARD).pack(side="left")
            tk.Label(top, text=action.check_code,
                    font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                    bg=Theme.BG_CARD).pack(side="right")

            tk.Label(card, text=action.preview, font=("Consolas", 9),
                    fg=Theme.TEXT_DIM, bg=Theme.BG_SURFACE,
                    anchor="w", justify="left", padx=8, pady=6,
                    wraplength=640).pack(fill="x", pady=(6, 0))

        # Bottom buttons
        btn_bar = tk.Frame(preview, bg=Theme.BG_DEEP)
        btn_bar.pack(fill="x", padx=20, pady=16)

        def do_execute():
            selected = [a for a, v in zip(auto_actions, check_vars) if v.get()]
            if not selected:
                messagebox.showinfo("Nothing Selected", "Select at least one fix.")
                return
            project = self.project_path_var.get()
            fix_engine.backup_mgr = BackupManager(project)
            results = fix_engine.execute_actions(selected, project)

            ok_count = sum(1 for ok, _ in results if ok)
            fail_count = len(results) - ok_count
            details = "\n".join(f"{'OK' if ok else 'FAIL'}: {msg}"
                               for ok, msg in results)

            preview.destroy()
            messagebox.showinfo("Fix Complete",
                f"Executed {len(results)} actions:\n"
                f"  {ok_count} succeeded, {fail_count} failed\n\n"
                f"{details}\n\n"
                f"Use 'Fix > Revert All' to undo changes.")
            self._update_status(
                f"Fixed {ok_count}/{len(results)} issues | "
                f"Backups: {fix_engine.backup_mgr.get_backup_count()}")

        tk.Button(btn_bar, text="  Execute Selected Fixes  ",
                 font=("Segoe UI", 11, "bold"), fg=Theme.BG_DEEP,
                 bg=Theme.ACCENT, bd=0, padx=20, pady=10, cursor="hand2",
                 command=do_execute).pack(side="left", padx=(0, 8))

        tk.Button(btn_bar, text="  Cancel  ",
                 font=("Segoe UI", 11), fg=Theme.TEXT,
                 bg=Theme.BG_CARD, bd=0, padx=20, pady=10, cursor="hand2",
                 command=preview.destroy).pack(side="left")

        count_label = tk.Label(btn_bar,
                              text=f"{len(auto_actions)} actions queued",
                              font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                              bg=Theme.BG_DEEP)
        count_label.pack(side="right")

    def _fix_generate_scripts(self):
        """Generate fix scripts for all issues without modifying files."""
        if not self.scanner.results:
            messagebox.showinfo("No Results", "Run a scan first.")
            return
        project = self.project_path_var.get()
        fix_engine = FixEngine(self.scanner)
        actions = fix_engine.generate_fix_actions(self.scanner.results)
        script_actions = [a for a in actions
                         if a.fix_type == "generated_script"]
        if not script_actions:
            messagebox.showinfo("No Scripts",
                "No script-based fixes available for current issues.")
            return

        # Prompt user to choose save location
        save_dir = filedialog.askdirectory(
            title="Choose folder to save generated fix scripts")
        if not save_dir:
            return  # user cancelled

        # Create a named subfolder
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        proj_name = os.path.basename(project) if project else "project"
        scripts_dir = Path(save_dir) / f"AnimBPDoctor_FixScripts_{proj_name}_{ts}"
        scripts_dir.mkdir(parents=True, exist_ok=True)

        results = fix_engine.execute_actions(
            script_actions, project, output_dir=str(scripts_dir))
        ok_count = sum(1 for ok, _ in results if ok)
        messagebox.showinfo("Scripts Generated",
            f"Generated {ok_count} fix scripts.\n\n"
            f"Location:\n{scripts_dir}\n\n"
            f"Run these scripts in UE5 Editor:\n"
            f"  Tools > Execute Python Script")
        self._update_status(f"Generated {ok_count} fix scripts")

    def _fix_revert_all(self):
        """Revert all file changes made by auto-fix."""
        project = self.project_path_var.get()
        if not project:
            messagebox.showwarning("No Project", "No project selected.")
            return

        backup_mgr = BackupManager(project)
        count = backup_mgr.get_backup_count()
        if count == 0:
            messagebox.showinfo("Nothing to Revert",
                "No backup entries found. No changes have been made.")
            return

        summary = backup_mgr.get_backup_summary()
        detail_lines = [f"  {e['fix']}" for e in summary[:10]]
        if count > 10:
            detail_lines.append(f"  ... and {count - 10} more")

        if messagebox.askyesno("Confirm Revert",
            f"Revert {count} file(s) to their original state?\n\n"
            + "\n".join(detail_lines) +
            "\n\nThis will restore original .uasset files from backup."):
            reverted = backup_mgr.revert_all()
            messagebox.showinfo("Reverted",
                f"Reverted {len(reverted)} file(s) to original state.")
            self._update_status(f"Reverted {len(reverted)} files")

    def _export_report(self):
        if not self.scanner.results and not self.scanner.animblueprints:
            messagebox.showwarning("No Data",
                "Run a scan first to generate a report.")
            return

        default_name = f"AnimBP_Doctor_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        filepath = filedialog.asksaveasfilename(
            title="Save HTML Report",
            defaultextension=".html",
            initialfile=default_name,
            filetypes=[("HTML files", "*.html"), ("All files", "*.*")])

        if filepath:
            try:
                ReportGenerator.generate(self.scanner, filepath)
                self._update_status(f"Report saved: {os.path.basename(filepath)}")

                # Open in browser
                if messagebox.askyesno("Report Saved",
                    f"Report saved to:\n{filepath}\n\nOpen in browser?"):
                    webbrowser.open(Path(filepath).as_uri())
            except Exception as e:
                messagebox.showerror("Export Error", f"Failed to export report:\n{e}")

    def _export_json(self):
        if not self.scanner.results:
            messagebox.showwarning("No Data", "Run a scan first to export results.")
            return

        default_name = f"AnimBP_Doctor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = filedialog.asksaveasfilename(
            title="Save JSON Export",
            defaultextension=".json",
            initialfile=default_name,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])

        if filepath:
            data = {
                "version": "1.0",
                "timestamp": datetime.now().isoformat(),
                "project": self.project_path_var.get(),
                "overall_grade": self.scanner.get_overall_grade(),
                "summary": {
                    "animblueprints_scanned": len(self.scanner.animblueprints),
                    "total_issues": len(self.scanner.results),
                    "errors": sum(1 for r in self.scanner.results if r.severity == "ERROR"),
                    "warnings": sum(1 for r in self.scanner.results if r.severity == "WARNING"),
                    "info": sum(1 for r in self.scanner.results if r.severity == "INFO"),
                    "auto_fixable": sum(1 for r in self.scanner.results if r.auto_fixable),
                },
                "animblueprints": [
                    {
                        "name": a.name,
                        "asset_path": a.asset_path,
                        "grade": a.grade,
                        "issue_count": len(a.issues),
                    } for a in self.scanner.animblueprints
                ],
                "issues": [
                    {
                        "check_code": r.check_code,
                        "severity": r.severity,
                        "animblueprint": r.animblueprint,
                        "asset_path": r.asset_path,
                        "description": r.description,
                        "node_hint": r.node_hint,
                        "auto_fixable": r.auto_fixable,
                    } for r in self.scanner.results
                ],
            }

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            self._update_status(f"JSON exported: {os.path.basename(filepath)}")

    def _clear_results(self):
        if self.is_scanning:
            messagebox.showwarning("Scan Running",
                "Wait for the current scan to complete before clearing.")
            return
        self.scanner = ScannerEngine()
        self.progress_var.set(0)
        self._update_status("Results cleared")
        if self.current_view == "scanner":
            self._show_scanner()
        elif self.current_view == "dashboard":
            self._show_dashboard()

    def _get_filtered_results(self) -> List[ScanResult]:
        """Apply severity + search filters to results."""
        results = self.scanner.results
        # Severity filter
        results = [r for r in results
                   if (var := self.filter_vars.get(r.severity)) is None or var.get()]
        # Text search
        if hasattr(self, '_search_var'):
            query = self._search_var.get().strip().lower()
            if query:
                results = [r for r in results
                           if query in r.animblueprint.lower()
                           or query in r.description.lower()
                           or query in r.check_code.lower()
                           or query in (CHECK_MAP.get(r.check_code, None) and
                                       CHECK_MAP[r.check_code].name.lower() or "")]
        return results

    def _apply_filters(self):
        if self.current_view == "scanner" and self.scanner.results:
            filtered = self._get_filtered_results()
            for widget in self.scanner_results_frame.winfo_children():
                widget.destroy()
            self._build_results_tree(self.scanner_results_frame, filtered,
                                     show_checkboxes=False)

    def _copy_issue(self, tree, results, mode):
        """Copy issue data from treeview selection to clipboard."""
        sel = tree.selection()
        if not sel:
            return
        idx = tree.index(sel[0])
        if idx >= len(results):
            return
        r = results[idx]
        if mode == "path":
            text = r.asset_path
        else:
            check_def = CHECK_MAP.get(r.check_code)
            name = check_def.name if check_def else r.check_code
            text = f"[{r.severity}] {name} — {r.animblueprint}\n{r.description}"
            if r.node_hint:
                text += f"\nLocation: {r.node_hint}"
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._update_status("Copied to clipboard")

    def _copy_single_issue(self, result: ScanResult):
        """Copy a single issue's full details to clipboard."""
        check_def = CHECK_MAP.get(result.check_code)
        name = check_def.name if check_def else result.check_code
        text = (f"[{result.severity}] {name}\n"
                f"Blueprint: {result.animblueprint}\n"
                f"Path: {result.asset_path}\n"
                f"Description: {result.description}")
        if result.node_hint:
            text += f"\nLocation: {result.node_hint}"
        if check_def:
            text += f"\nWhy: {check_def.why_it_matters}"
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._update_status("Issue details copied to clipboard")

    def _show_fix_from_tree(self, tree, results):
        """Open fix guide detail from right-click context menu."""
        sel = tree.selection()
        if not sel:
            return
        idx = tree.index(sel[0])
        if idx < len(results):
            self._show_issue_detail(results[idx])

    def _copy_report_clipboard(self):
        """Copy a markdown-formatted scan summary to clipboard."""
        if not self.scanner.results:
            self._update_status("No scan results to copy")
            return

        grade = self.scanner.get_overall_grade()
        abp_count = len(self.scanner.animblueprints)
        errors = sum(1 for r in self.scanner.results if r.severity == "ERROR")
        warnings = sum(1 for r in self.scanner.results if r.severity == "WARNING")
        infos = sum(1 for r in self.scanner.results if r.severity == "INFO")
        time_saved = self._estimate_time_saved(self.scanner.results)
        project = os.path.basename(self.project_path_var.get())

        lines = [
            f"## BP Doctor Report — {project}",
            f"**Grade: {grade}** | {abp_count} Blueprints | "
            f"{errors} Errors, {warnings} Warnings, {infos} Info",
            f"**Inspection time saved:** {time_saved}",
            "",
            "### Issues:",
        ]
        for r in self.scanner.results[:20]:
            check_def = CHECK_MAP.get(r.check_code)
            name = check_def.name if check_def else r.check_code
            lines.append(f"- **{r.severity}**: {name} in `{r.animblueprint}`")

        if len(self.scanner.results) > 20:
            lines.append(f"- ... and {len(self.scanner.results) - 20} more")

        text = "\n".join(lines)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._update_status("Report copied to clipboard (Markdown)")

    def _get_fix_guide(self, check_code: str) -> Optional[List[Tuple[str, str]]]:
        """Return condensed fix steps for inline display in detail popup."""
        # Inline fix guide data — key steps for each check
        guides = {
            "NULL_ANIM_REF": [
                ("Open the AnimBP", "Double-click the flagged AnimBP in Content Browser."),
                ("Find empty Sequence Players", "Look for Sequence Player nodes showing 'None'. Press Ctrl+F and search 'Sequence Player'."),
                ("Assign an animation", "Click the node, find 'Sequence' in Details panel, select the correct animation asset."),
                ("Compile and test", "Press F7 to compile, then test in PIE to verify the animation plays."),
            ],
            "BROKEN_BLEND_WT": [
                ("Find the blend node", "Look for LayeredBoneBlend or Blend nodes in the AnimGraph."),
                ("Check weight values", "In Details panel, find 'Blend Weights'. Ensure all values are between 0.0 and 1.0."),
                ("Add a safety clamp", "If driven by a variable, add a Clamp node: Get Variable -> Clamp(0,1) -> BlendWeight."),
                ("Compile and test", "Press F7, test in PIE. Watch blend behavior for pops or jitter."),
            ],
            "SKEL_MISMATCH": [
                ("Check the AnimBP's skeleton", "Open AnimBP, note the skeleton shown in the toolbar."),
                ("Find mismatched animations", "Click each Sequence Player/BlendSpace. Verify its animation uses the same skeleton."),
                ("Retarget or replace", "Use Asset > Retarget Anim Assets for wrong-skeleton anims, or replace with compatible ones."),
                ("Compile and test cook", "Press F7, then File > Cook Content to verify no skeleton errors."),
            ],
            "MISSING_SLOT": [
                ("Open the AnimGraph", "Go to the AnimGraph tab in the AnimBP editor."),
                ("Add a Slot node", "Right-click empty space, search 'Slot', add it."),
                ("Wire it in", "Place it BETWEEN your animation logic and Output Pose: [State Machine] -> [Slot] -> [Output Pose]."),
                ("Verify slot name", "Default is 'DefaultSlot'. Must match your PlayMontage code. Compile (F7) and test."),
            ],
            "BROKEN_TRANS": [
                ("Open the state machine", "Double-click the State Machine node to enter it."),
                ("Find isolated states", "Zoom out. Look for state boxes with no arrows pointing INTO them."),
                ("Connect or remove", "Add missing transitions by dragging from source state edge to target, or delete orphan states."),
                ("Test with debugger", "Compile, enable AnimBP debugger in PIE to watch state flow in real-time."),
            ],
            "TPOSE_FALLBACK": [
                ("Find the LayeredBoneBlend", "Look for 'Layered Blend per Bone' node in the AnimGraph."),
                ("Check BasePose input", "The TOP input pin (BasePose) must be connected. If empty, that's the problem."),
                ("Reconnect BasePose", "Wire your main animation output (State Machine) into the BasePose pin."),
                ("Compile and test", "Press F7. Test with montages/blends to verify no T-pose flashes."),
            ],
            "ORPHANED_NODE": [
                ("Zoom out", "Press Home to see the full AnimGraph."),
                ("Find disconnected nodes", "Look for nodes not connected to the Output Pose chain."),
                ("Delete or reconnect", "Select orphaned nodes, press Delete. Or wire them back if they were meant to be connected."),
            ],
            "INVALID_BSPACE": [
                ("Open the BlendSpace", "Find the BlendSpace asset in Content Browser, double-click."),
                ("Add sample animations", "Drag animation sequences onto the grid. Need at least 2 for interpolation."),
                ("Set axis ranges", "Configure Horizontal/Vertical axis names and Min/Max values."),
                ("Save and compile", "Save the BlendSpace, compile the AnimBP (F7), test in PIE."),
            ],
            "MISSING_NOTIFY": [
                ("Find animations with broken notifies", "Open each animation used by this AnimBP. Check the Notifies track."),
                ("Fix or remove", "Update the notify to point to the correct event, or right-click > Delete Notify."),
                ("Verify all notifies", "Check ALL animations in this AnimBP, not just the flagged one."),
                ("Test event firing", "Compile, test in PIE. Add Print String to verify events fire."),
            ],
            "DUP_SLOT": [
                ("Find all Slot nodes", "Press Ctrl+F, search 'Slot' in the AnimGraph."),
                ("Rename duplicates", "Each Slot needs a unique name: 'DefaultSlot', 'UpperBody', 'LowerBody', etc."),
                ("Update code references", "If you renamed a slot, update PlayMontage calls to use the new name."),
                ("Compile and test", "Press F7. Test all montages to verify correct layer playback."),
            ],
            "UNUSED_VAR": [
                ("Identify unused variables", "In the AnimBP, check Class Defaults. Right-click each variable > Find References."),
                ("Remove confirmed unused", "Delete variables with zero references in the AnimGraph."),
                ("Clean up setter code", "Remove any code in NativeUpdateAnimation that sets deleted variables."),
            ],
            "DEPRECATED_NODE": [
                ("Find deprecated nodes", "Check Compiler Results for deprecation warnings."),
                ("Find the replacement", "Right-click in AnimGraph, search for the modern equivalent node."),
                ("Swap and rewire", "Add the new node, copy settings, reconnect all pins, delete the old node."),
                ("Compile and test", "Press F7. Test all animations that flow through the replaced node."),
            ],
            # General Blueprint fix guides
            "BP_BROKEN_REF": [
                ("Identify the broken reference", "Open the Blueprint. Look for nodes with red or missing references."),
                ("Check if asset was moved", "Use Content Browser search to find the asset by name. It may have been moved."),
                ("Redirect or remove", "If moved: right-click broken ref > Replace Reference. If deleted: remove the node or assign a new asset."),
                ("Fix Redirectors", "Run: Right-click Content folder > Fix Up Redirectors in Folder."),
            ],
            "BP_COMPLEXITY": [
                ("Identify hot spots", "Open the Blueprint. Look for dense clusters of nodes."),
                ("Extract to functions", "Select related node groups, right-click > Collapse to Function."),
                ("Consider C++ for heavy logic", "Tight loops, math-heavy code, and frequently called logic should be C++."),
                ("Target under 100 nodes", "A well-organized Blueprint rarely needs more than 50-80 nodes per graph."),
            ],
            "BP_EMPTY_GRAPH": [
                ("Check if intentional", "Some Blueprints are data-only (no logic needed). Verify this is the case."),
                ("Delete if abandoned", "If this is an old prototype, delete it to reduce project clutter."),
                ("Add logic if needed", "If the Blueprint should have logic, open it and implement the Event Graph."),
            ],
            "BP_TICK_HEAVY": [
                ("Evaluate Tick necessity", "Does this Blueprint NEED to run every frame? Most don't."),
                ("Use timers instead", "Set Timer by Event with 0.1-0.5s interval covers most use cases."),
                ("Disable Tick", "In Class Defaults: set 'Start with Tick Enabled' to false."),
                ("Move to C++ if needed", "If Tick is required, C++ Tick is 10-100x faster than Blueprint Tick."),
            ],
            "BP_SELF_CAST": [
                ("Find the self-cast", "Look for Cast nodes where the target class matches this Blueprint's class."),
                ("Replace with Self", "Delete the Cast node. Use 'Get a reference to self' or just drag from Self."),
                ("Compile and test", "Press F7. Self-casts always succeed, so removing them is always safe."),
            ],
            "BP_DEPRECATED_FUNC": [
                ("Find deprecated calls", "Check Compiler Results for deprecation warnings. Look for yellow warnings."),
                ("Find replacements", "Hover over the deprecated node — the tooltip usually names the replacement."),
                ("Swap nodes", "Add the replacement node, copy pin connections, delete the deprecated one."),
                ("Compile and test", "Press F7. Test all code paths that used the deprecated function."),
            ],
            "BP_CIRCULAR_DEP": [
                ("Identify the cycle", "Both Blueprints reference each other. Determine which dependency is essential."),
                ("Break with an Interface", "Create a Blueprint Interface. Have one BP implement it, the other call through it."),
                ("Break with Event Dispatcher", "Replace the direct reference with an Event Dispatcher binding."),
                ("Restructure if needed", "Consider a manager class that both Blueprints reference instead of each other."),
            ],
            "BP_MASSIVE_ASSET": [
                ("Check for embedded data", "Open the Blueprint. Look for large arrays, embedded textures, or mesh data."),
                ("Move data to Data Assets", "Extract large data tables or arrays into separate Data Asset files."),
                ("Clean up unused nodes", "Delete any commented-out or orphaned node groups."),
                ("Check for corruption", "If size seems wrong, try duplicating the Blueprint and deleting the original."),
            ],
            "BP_HARD_REF": [
                ("Open Reference Viewer", "Right-click the Blueprint in Content Browser > Reference Viewer."),
                ("Identify Cast-to-BP nodes", "Look for Cast nodes targeting other Blueprint classes (not C++ classes)."),
                ("Replace with Interfaces", "Create a Blueprint Interface for the shared API. Have targets implement it."),
                ("Use Soft References", "For assets loaded on demand, use TSoftObjectPtr / Soft Object Reference."),
            ],
            "BP_EXPENSIVE_TICK": [
                ("Identify the expensive call", "Open the Blueprint and find the Tick event graph. Locate the flagged function."),
                ("Cache the result", "Call the expensive function once in BeginPlay or on a timer, store the result in a variable."),
                ("Use a timer", "Replace Tick with Set Timer by Event (0.1-0.5s interval covers most cases)."),
                ("Move to C++", "If per-frame execution is truly needed, C++ Tick is 10-100x faster than Blueprint Tick."),
            ],
            "BP_DEBUG_NODES": [
                ("Search for PrintString", "Press Ctrl+F in the Blueprint, search 'Print'. Select all and delete."),
                ("Search for DrawDebug", "Press Ctrl+F, search 'Draw Debug'. These are even more expensive than Print."),
                ("Use UE_LOG instead", "For logging that should persist, use C++ UE_LOG which is stripped from Shipping builds."),
                ("Verify Shipping build", "Package in Shipping config and check output log for any remaining debug text."),
            ],
            "BP_CONSTRUCT_HEAVY": [
                ("Move to BeginPlay", "SpawnActor and heavy queries should happen in BeginPlay, not Construction Script."),
                ("Use editor-only flag", "If needed only in editor, wrap with 'Is Editor' branch."),
                ("Guard with a check", "Add a boolean to prevent re-execution: if already_initialized, return."),
            ],
            "BP_FOREACH_PERF": [
                ("Cache the array first", "Before the ForEachLoop, call the query function once and store result in a local variable."),
                ("Use ForLoop instead", "Get the array length, use a standard ForLoop with index, access array by index."),
                ("Check if in Tick", "ForEachLoop in Tick is especially bad — consider caching the array on a timer."),
            ],
            "BP_TIMELINE_HEAVY": [
                ("Count your Timelines", "Open the Blueprint. Each Timeline node is a hidden tick component."),
                ("Merge Timelines", "If multiple Timelines run simultaneously, merge their curves into one Timeline."),
                ("Use Lerp + Timer", "For simple A-to-B transitions, a timer with FInterpTo is lighter than a Timeline."),
                ("Disable when idle", "Call Stop() on Timelines that aren't actively playing."),
            ],
        }
        return guides.get(check_code)

    def _save_check_settings(self):
        enabled = {code: var.get() for code, var in self.check_vars.items()}
        self.settings.set("checks_enabled", enabled)

    def _apply_color_scheme(self, name):
        """Apply a color scheme and rebuild the entire UI."""
        _apply_scheme(name)
        self.settings.set("color_scheme", name)
        # Save state that would be lost on rebuild
        saved_path = (self.project_path_var.get()
                      if hasattr(self, 'project_path_var') else "")
        saved_view = getattr(self, 'current_view', 'dashboard')
        saved_scanning = getattr(self, 'is_scanning', False)
        # Rebuild everything
        self.root.configure(bg=Theme.BG_DEEP)
        for w in self.root.winfo_children():
            w.destroy()
        self._setup_styles()
        self._build_ui()
        # Restore state
        if saved_path and saved_path != "No project selected":
            self.project_path_var.set(saved_path)
        if saved_scanning:
            self._update_status("Scan in progress — theme applied without interruption")
        self._navigate("settings")

    def _report_bug(self):
        """Open a bug report dialog with system info pre-filled. Rate limited to 5/24h."""
        # Rate limit: 5 reports per 24 hours
        report_log_path = Path.home() / ".animbpdoctor" / "report_log.json"
        now = time.time()
        cutoff = now - 86400  # 24 hours ago
        try:
            if report_log_path.exists():
                with open(report_log_path, "r") as f:
                    timestamps = json.load(f)
            else:
                timestamps = []
            timestamps = [t for t in timestamps if t > cutoff]
        except Exception:
            timestamps = []

        if len(timestamps) >= 5:
            messagebox.showinfo("Rate Limit",
                "You've sent 5 bug reports in the last 24 hours.\n"
                "Please wait before sending another. Thanks for the feedback!")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Report a Bug \u2014 AnimBPDoctor")
        dialog.geometry("520x440")
        dialog.configure(bg=Theme.BG_DEEP)
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Report a Bug",
                font=("Segoe UI", 16, "bold"), fg=Theme.ACCENT,
                bg=Theme.BG_DEEP).pack(anchor="w", padx=20, pady=(16, 4))
        tk.Label(dialog,
                text="Describe what happened and we'll include your system "
                     "info automatically.",
                font=("Segoe UI", 9), fg=Theme.TEXT_DIM,
                bg=Theme.BG_DEEP).pack(anchor="w", padx=20, pady=(0, 12))

        # Description input
        tk.Label(dialog, text="WHAT WENT WRONG:",
                font=("Segoe UI", 8, "bold"), fg=Theme.TEXT_MUTED,
                bg=Theme.BG_DEEP).pack(anchor="w", padx=20)
        desc_txt = tk.Text(dialog, height=6, font=("Consolas", 9),
                          bg=Theme.BG_INPUT, fg=Theme.TEXT,
                          insertbackground=Theme.TEXT, bd=0,
                          relief="flat", wrap="word")
        desc_txt.pack(fill="x", padx=20, pady=(4, 12))

        # System info (read-only)
        import platform as _plat
        project = self.project_path_var.get()
        scan_count = len(self.scanner.results) if self.scanner.results else 0
        bp_count = len(self.scanner.animblueprints)
        sys_info = (
            f"AnimBPDoctor v{APP_VERSION}\n"
            f"OS: {_plat.system()} {_plat.release()} ({_plat.machine()})\n"
            f"Python: {_plat.python_version()}\n"
            f"Project: {os.path.basename(project) if project else 'None'}\n"
            f"Last scan: {scan_count} issues, {bp_count} blueprints")

        tk.Label(dialog, text="SYSTEM INFO (auto-filled):",
                font=("Segoe UI", 8, "bold"), fg=Theme.TEXT_MUTED,
                bg=Theme.BG_DEEP).pack(anchor="w", padx=20)
        info_frame = tk.Frame(dialog, bg=Theme.BG_SURFACE, padx=10, pady=8)
        info_frame.pack(fill="x", padx=20, pady=(4, 16))
        tk.Label(info_frame, text=sys_info, font=("Consolas", 8),
                fg=Theme.TEXT_DIM, bg=Theme.BG_SURFACE, anchor="w",
                justify="left").pack(anchor="w")

        # Buttons
        btn_bar = tk.Frame(dialog, bg=Theme.BG_DEEP)
        btn_bar.pack(fill="x", padx=20, pady=(0, 16))

        def _send_email():
            desc = desc_txt.get("1.0", "end").strip()
            if not desc:
                messagebox.showwarning("Empty Report",
                    "Please describe what went wrong.")
                return
            import urllib.parse
            subject = urllib.parse.quote(
                f"[AnimBPDoctor v{APP_VERSION}] Bug Report")
            body = urllib.parse.quote(
                f"{desc}\n\n{'=' * 40}\n{sys_info}")
            mailto = (f"mailto:itsribbz@gmail.com"
                      f"?subject={subject}&body={body}")
            # Record send timestamp for rate limiting
            try:
                report_log_path.parent.mkdir(parents=True, exist_ok=True)
                timestamps.append(time.time())
                with open(report_log_path, "w") as f:
                    json.dump(timestamps[-10:], f)
            except Exception:
                pass
            webbrowser.open(mailto)
            dialog.destroy()

        def _copy_report():
            desc = desc_txt.get("1.0", "end").strip()
            report = f"BUG REPORT\n{'=' * 40}\n{desc}\n\n{sys_info}"
            self.root.clipboard_clear()
            self.root.clipboard_append(report)
            messagebox.showinfo("Copied",
                "Bug report copied to clipboard.")
            dialog.destroy()

        tk.Button(btn_bar, text="  Send via Email  ",
                 font=("Segoe UI", 10, "bold"), fg=Theme.BG_DEEP,
                 bg=Theme.ACCENT, bd=0, padx=16, pady=8, cursor="hand2",
                 command=_send_email).pack(side="left", padx=(0, 8))
        tk.Button(btn_bar, text="  Copy to Clipboard  ",
                 font=("Segoe UI", 10), fg=Theme.TEXT,
                 bg=Theme.BG_CARD, bd=0, padx=16, pady=8, cursor="hand2",
                 command=_copy_report).pack(side="left", padx=(0, 8))
        tk.Button(btn_bar, text="  Cancel  ",
                 font=("Segoe UI", 10), fg=Theme.TEXT_DIM,
                 bg=Theme.BG_CARD, bd=0, padx=16, pady=8, cursor="hand2",
                 command=dialog.destroy).pack(side="left")

    def _update_status(self, text):
        self.status_label.configure(text=text)

    def _show_update_notice(self, msg, url):
        """Show subtle update notice in the status bar."""
        self.status_right.configure(text=msg, fg=Theme.ACCENT, cursor="hand2")
        if url:
            self.status_right.bind("<Button-1>", lambda e: webbrowser.open(url))

    def _update_progress(self, text):
        try:
            self.progress_label.configure(text=text)
        except (tk.TclError, AttributeError):
            pass

    def run(self):
        self.root.mainloop()

# ─────────────────────────────────────────────────────────────────
#  CLI MODE — Headless scan for CI/CD integration
# ─────────────────────────────────────────────────────────────────

def _build_cli_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for CLI mode."""
    parser = argparse.ArgumentParser(
        prog="bp-doctor",
        description=f"BP Doctor v{APP_VERSION} — Blueprint Diagnostic Tool for UE5",
        epilog="When run without arguments, launches the GUI.",
    )
    parser.add_argument("--version", action="version", version=f"BP Doctor {APP_VERSION}")
    parser.add_argument("--cli", action="store_true",
                       help="Run in headless CLI mode (no GUI)")
    parser.add_argument("--project", "-p", type=str, default=None,
                       help="Path to UE5 project directory (must contain .uproject or Content/)")
    parser.add_argument("--output", "-o", type=str, default=None,
                       help="Output file path (default: stdout for JSON/text, required for HTML)")
    parser.add_argument("--format", "-f", choices=["json", "sarif", "html", "text", "diagnostic"], default="json",
                       help="Output format: json, sarif, html, text, diagnostic (default: json)")
    parser.add_argument("--severity", "-s", type=str, default=None,
                       help="Filter by severity: ERROR,WARNING,INFO (comma-separated)")
    parser.add_argument("--checks", type=str, default=None,
                       help="Only run specific checks (comma-separated codes)")
    parser.add_argument("--exit-code", action="store_true",
                       help="Exit with code 1 if any issues found (for CI/CD)")
    parser.add_argument("--quiet", "-q", action="store_true",
                       help="Suppress progress output (only show results)")
    parser.add_argument("--watch", "-w", action="store_true",
                       help="Watch mode — rescan when .uasset files change")
    parser.add_argument("--watch-interval", type=float, default=5.0,
                       help="Watch poll interval in seconds (default: 5)")
    parser.add_argument("--no-suppress", action="store_true",
                       help="Ignore suppressions — report ALL issues")
    parser.add_argument("--export-config", type=str, default=None,
                       help="Export team config to file")
    parser.add_argument("--import-config", type=str, default=None,
                       help="Import team config from file")
    parser.add_argument("--mode", choices=["beginner", "intermediate", "expert"],
                       default=None,
                       help="Experience mode: beginner (full guidance), intermediate (standard), expert (minimal)")
    return parser


def _run_cli(args) -> int:
    """Execute a headless CLI scan. Returns exit code."""
    if DEMO_MODE and not _demo_gate.can_scan():
        print("Demo scan limit reached. Upgrade to BP Doctor Pro: bpdoctor.gumroad.com/l/pro",
              file=sys.stderr)
        return 1

    if not args.project:
        print("Error: --project is required in CLI mode", file=sys.stderr)
        return 2

    project_path = os.path.abspath(args.project)
    if not os.path.isdir(project_path):
        print(f"Error: Project directory not found: {project_path}", file=sys.stderr)
        return 2

    # Handle config export/import (no scan needed)
    if args.export_config:
        settings = Settings()
        settings.load()
        out = TeamConfig.export_config(project_path, settings, args.export_config)
        print(f"Config exported to: {out}", file=sys.stderr)
        return 0
    if args.import_config:
        settings = Settings()
        settings.load()
        ok, msg = TeamConfig.import_config(project_path, settings, args.import_config)
        print(msg, file=sys.stderr)
        return 0 if ok else 1

    # Set up scanner
    scanner = ScannerEngine()
    if not scanner.discover_project(project_path):
        print(f"Error: Not a UE5 project (no .uproject or Content/): {project_path}",
              file=sys.stderr)
        return 2

    # Progress callback (unless quiet)
    if not args.quiet:
        def on_progress(current, total, msg):
            print(f"\r  [{current}/{total}] {msg}", end="", flush=True, file=sys.stderr)
        scanner.on_progress = on_progress

    # Run scan
    if not args.quiet:
        print(f"BP Doctor v{APP_VERSION} — CLI Mode", file=sys.stderr)
        print(f"Scanning: {project_path}", file=sys.stderr)

    results = scanner.scan_all(project_path)

    # Run custom checks if any exist
    try:
        custom_loader = CustomCheckLoader(project_path)
        if custom_loader.custom_checks:
            for abp in scanner.animblueprints:
                try:
                    with open(abp.file_path, "rb") as f:
                        raw = f.read()
                    name_table = parse_uasset_names(raw)
                    is_bp = abp.asset_type == "Blueprint"
                    custom_results = custom_loader.run_custom_checks(abp, raw, name_table, is_bp)
                    results.extend(custom_results)
                    abp.issues.extend(custom_results)
                except (IOError, OSError):
                    pass
            if not args.quiet and custom_loader.custom_checks:
                print(f"  Custom checks: {len(custom_loader.custom_checks)} loaded",
                      file=sys.stderr)
    except Exception:
        pass

    if not args.quiet:
        print("", file=sys.stderr)  # newline after progress

    # Apply suppressions (unless --no-suppress)
    suppressed_count = 0
    if not getattr(args, 'no_suppress', False):
        try:
            supp = SuppressionManager(project_path)
            results, suppressed_count = supp.filter_results(results)
            if suppressed_count > 0 and not args.quiet:
                print(f"  Suppressed: {suppressed_count} issue(s)", file=sys.stderr)
        except Exception:
            pass

    # Filter by severity
    if args.severity:
        allowed = {s.strip().upper() for s in args.severity.split(",")}
        results = [r for r in results if r.severity in allowed]

    # Filter by check codes
    if args.checks:
        allowed_codes = {c.strip().upper() for c in args.checks.split(",")}
        results = [r for r in results if r.check_code in allowed_codes]

    # Resolve experience mode
    exp_mode = getattr(args, 'mode', None) or "intermediate"

    # Generate output
    if args.format == "sarif":
        output = _cli_format_sarif(scanner, results)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            if not args.quiet:
                print(f"SARIF written to: {args.output}", file=sys.stderr)
        else:
            print(output)

    elif args.format == "json":
        output = _cli_format_json(scanner, results)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            if not args.quiet:
                print(f"Results written to: {args.output}", file=sys.stderr)
        else:
            print(output)

    elif args.format == "html":
        if not args.output:
            print("Error: --output is required for HTML format", file=sys.stderr)
            return 2
        ReportGenerator.generate(scanner, args.output)
        if not args.quiet:
            print(f"HTML report written to: {args.output}", file=sys.stderr)

    elif args.format == "text":
        output = _cli_format_text(scanner, results, mode=exp_mode)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
        else:
            print(output)

    elif args.format == "diagnostic":
        if not args.output:
            args.output = f"BP_Doctor_Diagnostic_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        DiagnosticPDFGenerator.generate(scanner, args.output, mode=exp_mode)
        if not args.quiet:
            print(f"Diagnostic PDF written to: {args.output}", file=sys.stderr)

    # Summary to stderr
    if not args.quiet:
        grade = scanner.get_overall_grade()
        errors = sum(1 for r in results if r.severity == "ERROR")
        warnings = sum(1 for r in results if r.severity == "WARNING")
        infos = sum(1 for r in results if r.severity == "INFO")
        bp_count = len(scanner.animblueprints)
        print(f"\n  Grade: {grade} | {bp_count} Blueprints | "
              f"{errors}E {warnings}W {infos}I | "
              f"{scanner.scan_duration:.1f}s", file=sys.stderr)

    # Exit code
    if args.exit_code:
        has_issues = any(r.severity in ("ERROR", "WARNING") for r in results)
        return 1 if has_issues else 0
    return 0


def _cli_format_json(scanner: ScannerEngine, results: List[ScanResult]) -> str:
    """Format scan results as JSON for CI/CD consumption."""
    data = {
        "version": APP_VERSION,
        "timestamp": datetime.now().isoformat(),
        "project": scanner.project_path,
        "overall_grade": scanner.get_overall_grade(),
        "scan_duration_seconds": round(scanner.scan_duration, 2),
        "summary": {
            "blueprints_scanned": len(scanner.animblueprints),
            "animblueprints": sum(1 for a in scanner.animblueprints if a.asset_type == "AnimBP"),
            "general_blueprints": sum(1 for a in scanner.animblueprints if a.asset_type == "Blueprint"),
            "total_issues": len(results),
            "errors": sum(1 for r in results if r.severity == "ERROR"),
            "warnings": sum(1 for r in results if r.severity == "WARNING"),
            "info": sum(1 for r in results if r.severity == "INFO"),
            "auto_fixable": sum(1 for r in results if r.auto_fixable),
        },
        "blueprints": [
            {
                "name": a.name,
                "asset_path": a.asset_path,
                "asset_type": a.asset_type,
                "grade": a.grade,
                "issue_count": len(a.issues),
            } for a in sorted(scanner.animblueprints, key=lambda a: len(a.issues), reverse=True)
        ],
        "issues": [
            {
                "check_code": r.check_code,
                "check_name": CHECK_MAP[r.check_code].name if r.check_code in CHECK_MAP else r.check_code,
                "severity": r.severity,
                "confidence": CHECK_MAP[r.check_code].confidence.value if r.check_code in CHECK_MAP else "MEDIUM",
                "blueprint": r.animblueprint,
                "asset_path": r.asset_path,
                "asset_type": r.asset_type,
                "description": r.description,
                "node_hint": r.node_hint,
                "auto_fixable": r.auto_fixable,
            } for r in results
        ],
    }
    return json.dumps(data, indent=2)


def _cli_format_text(scanner: ScannerEngine, results: List[ScanResult],
                     mode: str = "intermediate") -> str:
    """Format scan results as human-readable text. Respects experience mode."""
    mode_cfg = ExperienceMode.get(mode)
    style = mode_cfg["cli_text_style"]

    lines = []
    grade = scanner.get_overall_grade()
    bp_count = len(scanner.animblueprints)
    errors = sum(1 for r in results if r.severity == "ERROR")
    warnings = sum(1 for r in results if r.severity == "WARNING")
    infos = sum(1 for r in results if r.severity == "INFO")

    lines.append(f"BP Doctor v{APP_VERSION} — Scan Results")
    lines.append(f"{'=' * 60}")
    lines.append(f"Project:  {scanner.project_path}")
    lines.append(f"Grade:    {grade}")
    lines.append(f"Scanned:  {bp_count} Blueprints in {scanner.scan_duration:.1f}s")
    lines.append(f"Issues:   {errors} Errors, {warnings} Warnings, {infos} Info")
    lines.append(f"{'=' * 60}")
    lines.append("")

    for r in results:
        check_def = CHECK_MAP.get(r.check_code)
        name = check_def.name if check_def else r.check_code
        fix_tag = " [AUTO-FIX]" if r.auto_fixable else ""

        if style == "compact":
            # EXPERT: one line per issue
            hint = f" | {r.node_hint}" if r.node_hint else ""
            lines.append(f"  {r.severity:7s} {r.check_code:20s} {r.animblueprint}{fix_tag}{hint}")
        elif style == "standard":
            # INTERMEDIATE: description + hint, no why
            lines.append(f"  [{r.severity:7s}] {name}{fix_tag}")
            lines.append(f"           {r.animblueprint} — {r.asset_path}")
            lines.append(f"           {r.description}")
            if r.node_hint:
                lines.append(f"           Hint: {r.node_hint}")
            lines.append("")
        else:
            # BEGINNER: full verbose with why + beginner tip
            lines.append(f"  [{r.severity:7s}] {name}{fix_tag}")
            lines.append(f"           {r.animblueprint} — {r.asset_path}")
            lines.append(f"           {r.description}")
            if r.node_hint:
                lines.append(f"           Hint: {r.node_hint}")
            if check_def and check_def.beginner_tip:
                lines.append(f"           Tip: {check_def.beginner_tip}")
            if check_def and check_def.why_it_matters:
                lines.append(f"           Why: {check_def.why_it_matters[:150]}")
            guide = _FIX_GUIDES.get(r.check_code)
            if guide:
                for si, (step_t, step_d) in enumerate(guide, 1):
                    lines.append(f"           Step {si}: {step_t} — {step_d}")
            lines.append("")

    if not results:
        lines.append("  No issues found. All Blueprints are clean.")

    if style == "compact":
        lines.append("")

    lines.append(f"{'=' * 60}")
    lines.append(f"BP Doctor v{APP_VERSION} — BP Doctor")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
#  VERSION CHECK — Non-blocking update notification
# ─────────────────────────────────────────────────────────────────

_UPDATE_CHECK_URL = "https://raw.githubusercontent.com/bp-doctor/bp-doctor/main/version.json"

def _check_for_updates(callback):
    """Check for updates in a background thread. Calls callback(msg, url) on success."""
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(
            _UPDATE_CHECK_URL,
            headers={"User-Agent": f"BPDoctor/{APP_VERSION}"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        remote_version = data.get("version", "")
        download_url = data.get("url", "")
        if remote_version and _is_newer(remote_version, APP_VERSION):
            callback(f"Update available: v{remote_version}", download_url)
    except Exception:
        pass  # Silently ignore — no internet, timeout, bad data

def _is_newer(remote: str, local: str) -> bool:
    """Compare semantic version strings."""
    try:
        r = tuple(int(x) for x in remote.split("."))
        l = tuple(int(x) for x in local.split("."))
        return r > l
    except (ValueError, AttributeError):
        return False


# ─────────────────────────────────────────────────────────────────
#  SARIF OUTPUT — GitHub Code Scanning / Azure DevOps integration
# ─────────────────────────────────────────────────────────────────

def _cli_format_sarif(scanner: ScannerEngine, results: List[ScanResult]) -> str:
    """Format scan results as SARIF v2.1.0 for GitHub Code Scanning upload."""
    severity_map = {"ERROR": "error", "WARNING": "warning", "INFO": "note"}

    rules = []
    seen_rules = set()
    for check in CHECKS:
        if check.code not in seen_rules:
            seen_rules.add(check.code)
            rules.append({
                "id": check.code,
                "name": check.name.replace(" ", ""),
                "shortDescription": {"text": check.name},
                "fullDescription": {"text": check.why_it_matters[:512]},
                "defaultConfiguration": {"level": severity_map.get(check.severity.value, "note")},
                "properties": {
                    "confidence": check.confidence.value,
                    "auto_fixable": check.auto_fixable,
                    "tags": ["blueprint", "ue5", check.severity.value.lower()],
                },
            })

    sarif_results = []
    for r in results:
        # Build asset-relative URI for the location
        asset_uri = r.asset_path.lstrip("/")
        if not asset_uri.endswith(".uasset"):
            asset_uri += ".uasset"

        sarif_result = {
            "ruleId": r.check_code,
            "level": severity_map.get(r.severity, "note"),
            "message": {"text": r.description},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {
                        "uri": asset_uri,
                        "uriBaseId": "%SRCROOT%",
                    },
                },
                "logicalLocations": [{
                    "name": r.animblueprint,
                    "kind": "module",
                }],
            }],
        }
        if r.node_hint:
            sarif_result["properties"] = {"nodeHint": r.node_hint}
        sarif_results.append(sarif_result)

    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "BP Doctor",
                    "version": APP_VERSION,
                    "semanticVersion": APP_VERSION,
                    "informationUri": "https://bpdoctor.dev/bp-doctor",
                    "rules": rules,
                },
            },
            "results": sarif_results,
            "invocations": [{
                "executionSuccessful": True,
                "toolExecutionNotifications": [],
            }],
        }],
    }
    return json.dumps(sarif, indent=2)


# ─────────────────────────────────────────────────────────────────
#  CUSTOM CHECK PLUGINS — User-defined checks via JSON
# ─────────────────────────────────────────────────────────────────

class CustomCheckLoader:
    """Loads user-defined checks from .animbpdoctor/custom_checks/*.json.

    Each JSON file defines a check with:
    {
        "code": "MY_CUSTOM_CHECK",
        "name": "My Custom Check",
        "severity": "WARNING",
        "description": "Detects XYZ pattern in Blueprints.",
        "why_it_matters": "Because...",
        "beginner_tip": "This means...",
        "asset_types": ["AnimBP", "Blueprint"],  // or ["AnimBP"] or ["Blueprint"]
        "rules": [
            {"type": "name_table_contains", "value": "SomeBadClass", "match": "present"},
            {"type": "name_table_contains", "value": "SafeGuardClass", "match": "absent"},
            {"type": "binary_contains", "value": "BadPattern", "match": "present"},
            {"type": "file_size_gt", "value": 1048576},
            {"type": "node_count_gt", "marker": "K2Node_", "value": 50}
        ],
        "require": "all"  // "all" = all rules must match, "any" = at least one
    }
    """

    def __init__(self, project_path: str):
        self.checks_dir = Path(project_path) / ".animbpdoctor" / "custom_checks"
        self.custom_checks: List[dict] = []
        self._load()

    def _load(self):
        if not self.checks_dir.exists():
            return
        for f in sorted(self.checks_dir.glob("*.json")):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    check_def = json.load(fh)
                if self._validate(check_def):
                    self.custom_checks.append(check_def)
            except (json.JSONDecodeError, IOError):
                pass

    @staticmethod
    def _validate(c: dict) -> bool:
        required = ("code", "name", "severity", "description", "rules")
        return all(k in c for k in required) and isinstance(c["rules"], list) and len(c["rules"]) > 0

    def run_custom_checks(self, abp, raw: bytes, name_table, is_general_bp: bool) -> List:
        """Run all loaded custom checks against an asset. Returns list of ScanResult."""
        results = []
        for cdef in self.custom_checks:
            # Asset type filter
            asset_types = cdef.get("asset_types", ["AnimBP", "Blueprint"])
            current_type = "Blueprint" if is_general_bp else "AnimBP"
            if current_type not in asset_types:
                continue

            # Evaluate rules
            require = cdef.get("require", "all")
            matches = [self._eval_rule(rule, abp, raw, name_table) for rule in cdef["rules"]]

            triggered = all(matches) if require == "all" else any(matches)
            if triggered:
                results.append(ScanResult(
                    check_code=cdef["code"],
                    severity=cdef["severity"],
                    animblueprint=abp.name,
                    asset_path=abp.asset_path,
                    description=cdef["description"],
                    node_hint=cdef.get("beginner_tip", ""),
                    auto_fixable=False,
                    asset_type=current_type,
                ))
        return results

    @staticmethod
    def _eval_rule(rule: dict, abp, raw: bytes, name_table) -> bool:
        rtype = rule.get("type", "")
        value = rule.get("value", "")
        match = rule.get("match", "present")

        if rtype == "name_table_contains" and name_table is not None:
            found = any(value in n for n in name_table)
            return found if match == "present" else not found
        elif rtype == "binary_contains":
            found = value.encode("utf-8") if isinstance(value, str) else value
            present = found in raw
            return present if match == "present" else not present
        elif rtype == "file_size_gt":
            return abp.file_size > int(value)
        elif rtype == "file_size_lt":
            return abp.file_size < int(value)
        elif rtype == "node_count_gt":
            marker = rule.get("marker", "K2Node_").encode("utf-8")
            return raw.count(marker) > int(value)
        elif rtype == "export_count_gt":
            return abp.export_count > int(value)
        return False


# ─────────────────────────────────────────────────────────────────
#  WATCH MODE — Auto-rescan on file changes
# ─────────────────────────────────────────────────────────────────

class FileWatcher:
    """Watches a directory for .uasset file changes and triggers rescan.
    Uses polling (no external dependencies). Interval configurable."""

    def __init__(self, project_path: str, interval: float = 5.0):
        self.project_path = project_path
        self.interval = interval
        self._snapshot: Dict[str, float] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.on_changes_detected = None  # callback(changed_files: List[str])

    def _take_snapshot(self) -> Dict[str, float]:
        """Snapshot all .uasset modification times."""
        snap = {}
        content = Path(self.project_path) / "Content"
        if content.exists():
            for root, dirs, files in os.walk(content):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for f in files:
                    if f.endswith(".uasset"):
                        fp = os.path.join(root, f)
                        try:
                            snap[fp] = os.path.getmtime(fp)
                        except OSError:
                            pass
        return snap

    def start(self):
        """Start watching in a background thread."""
        self._snapshot = self._take_snapshot()
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _poll_loop(self):
        while self._running:
            time.sleep(self.interval)
            if not self._running:
                break
            new_snap = self._take_snapshot()
            changed = []
            for fp, mtime in new_snap.items():
                if fp not in self._snapshot or self._snapshot[fp] != mtime:
                    changed.append(fp)
            # Also detect deleted files
            for fp in self._snapshot:
                if fp not in new_snap:
                    changed.append(fp)
            if changed and self.on_changes_detected:
                self.on_changes_detected(changed)
            self._snapshot = new_snap


def _run_cli_watch(args) -> int:
    """Run CLI in watch mode — rescan on file changes."""
    import signal

    print(f"BP Doctor v{APP_VERSION} — Watch Mode", file=sys.stderr)
    print(f"Watching: {args.project} (poll every {args.watch_interval}s)", file=sys.stderr)
    print("Press Ctrl+C to stop.\n", file=sys.stderr)

    stop = [False]
    def sigint_handler(sig, frame):
        stop[0] = True
        print("\nWatch stopped.", file=sys.stderr)
    signal.signal(signal.SIGINT, sigint_handler)

    # Initial scan
    exit_code = _run_cli(args)

    # Start watching
    watcher = FileWatcher(os.path.abspath(args.project), interval=args.watch_interval)
    scan_pending = [False]

    def on_change(changed):
        scan_pending[0] = True
        n = len(changed)
        print(f"\n  [{datetime.now().strftime('%H:%M:%S')}] {n} file(s) changed — rescanning...",
              file=sys.stderr)

    watcher.on_changes_detected = on_change
    watcher.start()

    try:
        while not stop[0]:
            time.sleep(1)
            if scan_pending[0]:
                scan_pending[0] = False
                exit_code = _run_cli(args)
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()

    return exit_code


# ─────────────────────────────────────────────────────────────────
#  CHECK SUPPRESSION — Per-asset suppression with reason tracking
# ─────────────────────────────────────────────────────────────────

class SuppressionManager:
    """Manages per-asset check suppressions.

    Stored in .animbpdoctor/suppressions.json:
    {
        "/Game/Characters/ABP_Hero": {
            "ORPHANED_NODE": {"reason": "Known unused nodes kept for reference", "by": "john", "date": "2026-03-26"},
            "BP_COMPLEXITY": {"reason": "Intentionally complex — state machine hub", "by": "jane"}
        }
    }
    """

    def __init__(self, project_path: str):
        self.supp_path = Path(project_path) / ".animbpdoctor" / "suppressions.json"
        self.suppressions: Dict[str, Dict[str, dict]] = {}
        self._load()

    def _load(self):
        try:
            if self.supp_path.exists():
                with open(self.supp_path, "r", encoding="utf-8") as f:
                    self.suppressions = json.load(f)
        except (json.JSONDecodeError, IOError):
            self.suppressions = {}

    def save(self):
        self.supp_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.supp_path, "w", encoding="utf-8") as f:
            json.dump(self.suppressions, f, indent=2)

    def is_suppressed(self, asset_path: str, check_code: str) -> bool:
        return check_code in self.suppressions.get(asset_path, {})

    def suppress(self, asset_path: str, check_code: str, reason: str = "", by: str = ""):
        if asset_path not in self.suppressions:
            self.suppressions[asset_path] = {}
        self.suppressions[asset_path][check_code] = {
            "reason": reason,
            "by": by,
            "date": datetime.now().isoformat()[:10],
        }
        self.save()

    def unsuppress(self, asset_path: str, check_code: str):
        if asset_path in self.suppressions and check_code in self.suppressions[asset_path]:
            del self.suppressions[asset_path][check_code]
            if not self.suppressions[asset_path]:
                del self.suppressions[asset_path]
            self.save()

    def filter_results(self, results: List[ScanResult]) -> Tuple[List[ScanResult], int]:
        """Filter out suppressed results. Returns (filtered_results, suppressed_count)."""
        filtered = []
        suppressed = 0
        for r in results:
            if self.is_suppressed(r.asset_path, r.check_code):
                suppressed += 1
            else:
                filtered.append(r)
        return filtered, suppressed

    def get_all(self) -> Dict[str, Dict[str, dict]]:
        return dict(self.suppressions)


# ─────────────────────────────────────────────────────────────────
#  TEAM CONFIG — Export/import shareable check configuration
# ─────────────────────────────────────────────────────────────────

class TeamConfig:
    """Export and import BP Doctor configuration for team sharing.

    Exports to .bpdoctor-config.json:
    {
        "version": "2.5.0",
        "checks_enabled": {...},
        "severity_filter": [...],
        "custom_checks": [...],
        "suppressions": {...},
        "naming_conventions": {...},
        "auto_fix": {...}
    }
    """

    @staticmethod
    def export_config(project_path: str, settings: 'Settings',
                      output_path: str = None) -> str:
        """Export current config to a shareable JSON file."""
        config = {
            "bp_doctor_version": APP_VERSION,
            "exported": datetime.now().isoformat(),
            "checks_enabled": settings.get("checks_enabled", {}),
            "severity_filter": settings.get("severity_filter", ["ERROR", "WARNING", "INFO"]),
        }

        # Include custom checks if any
        custom_dir = Path(project_path) / ".animbpdoctor" / "custom_checks"
        if custom_dir.exists():
            custom_checks = []
            for f in sorted(custom_dir.glob("*.json")):
                try:
                    with open(f, "r", encoding="utf-8") as fh:
                        custom_checks.append(json.load(fh))
                except (json.JSONDecodeError, IOError):
                    pass
            if custom_checks:
                config["custom_checks"] = custom_checks

        # Include suppressions
        supp_path = Path(project_path) / ".animbpdoctor" / "suppressions.json"
        if supp_path.exists():
            try:
                with open(supp_path, "r", encoding="utf-8") as f:
                    config["suppressions"] = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        # Include project config
        proj_path = Path(project_path) / ".animbpdoctor" / "project.json"
        if proj_path.exists():
            try:
                with open(proj_path, "r", encoding="utf-8") as f:
                    proj = json.load(f)
                config["naming_conventions"] = proj.get("naming_conventions", {})
                config["auto_fix"] = proj.get("auto_fix", {})
            except (json.JSONDecodeError, IOError):
                pass

        if not output_path:
            output_path = os.path.join(project_path, ".bpdoctor-config.json")

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return output_path

    @staticmethod
    def import_config(project_path: str, settings: 'Settings',
                      config_path: str) -> Tuple[bool, str]:
        """Import a team config file. Returns (success, message)."""
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            return False, f"Cannot read config: {e}"

        imported = []

        # Import check toggles
        if "checks_enabled" in config:
            settings.set("checks_enabled", config["checks_enabled"])
            imported.append("check toggles")

        if "severity_filter" in config:
            settings.set("severity_filter", config["severity_filter"])
            imported.append("severity filter")

        # Import custom checks
        if "custom_checks" in config and isinstance(config["custom_checks"], list):
            cc_dir = Path(project_path) / ".animbpdoctor" / "custom_checks"
            cc_dir.mkdir(parents=True, exist_ok=True)
            for cc in config["custom_checks"]:
                if "code" in cc:
                    cc_path = cc_dir / f"{cc['code'].lower()}.json"
                    with open(cc_path, "w", encoding="utf-8") as f:
                        json.dump(cc, f, indent=2)
            imported.append(f"{len(config['custom_checks'])} custom checks")

        # Import suppressions
        if "suppressions" in config:
            supp_path = Path(project_path) / ".animbpdoctor" / "suppressions.json"
            supp_path.parent.mkdir(parents=True, exist_ok=True)
            with open(supp_path, "w", encoding="utf-8") as f:
                json.dump(config["suppressions"], f, indent=2)
            imported.append("suppressions")

        # Import naming conventions and auto_fix into project config
        pc = ProjectConfig(project_path)
        if "naming_conventions" in config:
            pc.data["naming_conventions"] = config["naming_conventions"]
            imported.append("naming conventions")
        if "auto_fix" in config:
            pc.data["auto_fix"] = config["auto_fix"]
            imported.append("auto-fix settings")
        pc.save()

        return True, f"Imported: {', '.join(imported)}"


# ─────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = _build_cli_parser()
    args = parser.parse_args()

    if args.cli:
        # Headless CLI mode — no GUI
        if getattr(args, 'watch', False):
            sys.exit(_run_cli_watch(args))
        else:
            sys.exit(_run_cli(args))
    else:
        # GUI mode — launch the application
        if not _HAS_TK:
            print("Error: tkinter is not available. Use --cli for headless mode.",
                  file=sys.stderr)
            sys.exit(1)
        app = AnimBPDoctorApp()

        # Non-blocking update check
        settings = app.settings
        if settings.get("check_for_updates", True):
            def _on_update(msg, url):
                app.root.after(0, lambda: app._show_update_notice(msg, url))
            threading.Thread(target=_check_for_updates, args=(_on_update,),
                           daemon=True).start()

        app.run()
