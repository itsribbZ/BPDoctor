#!/usr/bin/env python3
"""
BP Doctor v2.5 — Scanner Check Verification Suite
==================================================
Creates synthetic .uasset files with controlled name tables and binary
patterns to verify each check handler produces correct results.

Tests the FULL scan pipeline: file read -> parse -> check -> results.
"""

import importlib.util
import sys
import os
import struct
import tempfile
import shutil
import json

# Load module without GUI
spec = importlib.util.spec_from_file_location("bpd", "AnimBPDoctor.pyw")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

passed = 0
failed = 0

def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} -- {detail}")


# ── Synthetic .uasset builder ──

UASSET_MAGIC = 0x9E2A83C1

def build_uasset(names, extra_binary=b"", legacy_ver=-7, ue4_ver=522):
    """Build a minimal valid .uasset with a controlled name table.

    Args:
        names: list of strings to put in the name table
        extra_binary: additional bytes appended after the name table
        legacy_ver: UE version flag
        ue4_ver: UE4 version number
    Returns:
        bytes: the synthetic .uasset data
    """
    buf = bytearray()

    # Magic
    buf += struct.pack('<I', UASSET_MAGIC)
    # LegacyFileVersion
    buf += struct.pack('<i', legacy_ver)

    if legacy_ver != -4:
        buf += struct.pack('<i', 0)   # LegacyUE3Version

    buf += struct.pack('<i', ue4_ver)  # FileVersionUE4

    if legacy_ver <= -8:
        buf += struct.pack('<i', 0)    # FileVersionUE5

    buf += struct.pack('<i', 0)        # LicenseeVersion

    # Custom versions: count=0
    buf += struct.pack('<i', 0)

    # TotalHeaderSize (placeholder)
    buf += struct.pack('<i', 0)

    # FolderName (FString: length + bytes + null)
    folder = b"/Game"
    buf += struct.pack('<i', len(folder) + 1)
    buf += folder + b'\x00'

    # PackageFlags
    buf += struct.pack('<I', 0)

    # NameCount + NameOffset
    name_count = len(names)
    # NameOffset = current position + 8 (for NameCount + NameOffset themselves)
    # + 16 (ExportCount/Offset/ImportCount/Offset)
    header_remaining = 8 + 16
    name_offset = len(buf) + header_remaining
    buf += struct.pack('<i', name_count)
    buf += struct.pack('<i', name_offset)

    # ExportCount, ExportOffset, ImportCount, ImportOffset (minimal)
    export_count = max(1, name_count // 3)  # approximate
    buf += struct.pack('<i', export_count)
    buf += struct.pack('<i', 0)  # ExportOffset (0 = no export data)
    buf += struct.pack('<i', 0)  # ImportCount
    buf += struct.pack('<i', 0)  # ImportOffset

    # Pad to name_offset if needed
    while len(buf) < name_offset:
        buf += b'\x00'

    # Name table entries: FString + 2-byte hash (for legacy_ver <= -6)
    for name_str in names:
        encoded = name_str.encode('utf-8') + b'\x00'
        buf += struct.pack('<i', len(encoded))
        buf += encoded
        if legacy_ver <= -6 or ue4_ver >= 504:
            buf += struct.pack('<HH', 0, 0)  # case-preserve hash + hash

    # Append extra binary content (for binary-pattern checks)
    buf += extra_binary

    return bytes(buf)


def scan_synthetic(uasset_data, filename="Test_Synth.uasset"):
    """Run the full scanner pipeline on synthetic data and return results."""
    tmpdir = tempfile.mkdtemp()
    try:
        # Create a minimal Content directory structure
        content_dir = os.path.join(tmpdir, "Content")
        os.makedirs(content_dir)

        # Write the .uasset
        filepath = os.path.join(content_dir, filename)
        with open(filepath, "wb") as f:
            f.write(uasset_data)

        # Create a fake .uproject
        with open(os.path.join(tmpdir, "Test.uproject"), "w") as f:
            f.write('{"FileVersion": 3}')

        # Run scanner
        scanner = mod.ScannerEngine()
        results = scanner.scan_all(tmpdir)
        return scanner, results
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


print("=" * 60)
print("TEST SUITE: BP Doctor v2.5 Scanner Check Verification")
print("=" * 60)

# ── TEST: Name table parser ──
print("\n[1] Name Table Parser")
names = ["AnimBlueprintGeneratedClass", "AnimGraphNode_SequencePlayer",
         "AnimGraphNode_Root", "AnimInstance", "Skeleton", "TestPkg"]
data = build_uasset(names)
result = mod.parse_uasset_names(data)
test("Parser returns name set", result is not None)
test("Contains AnimBlueprintGeneratedClass", result and "AnimBlueprintGeneratedClass" in result)
test("Contains all names", result and len(result) >= 5)

# ── TEST: Export count parser ──
print("\n[2] Export Count Parser")
counts = mod.parse_uasset_export_counts(data)
test("Export counts parsed", counts is not None)
if counts:
    ec, ic = counts
    test("Export count > 0", ec > 0, f"got {ec}")

# ── TEST: NULL_ANIM_REF detection ──
print("\n[3] NULL_ANIM_REF Check")
# Should trigger: SequencePlayer present, no AnimSequence
names_null = ["AnimBlueprintGeneratedClass", "AnimGraphNode_SequencePlayer",
              "AnimGraphNode_Root", "AnimInstance"]
data_null = build_uasset(names_null)
scanner, results = scan_synthetic(data_null, "ABP_NullAnim.uasset")
null_results = [r for r in results if r.check_code == "NULL_ANIM_REF"]
test("NULL_ANIM_REF fires when no AnimSequence", len(null_results) > 0)

# Should NOT trigger: has AnimSequence
names_ok = ["AnimBlueprintGeneratedClass", "AnimGraphNode_SequencePlayer",
            "AnimGraphNode_Root", "AnimSequence", "AnimInstance"]
data_ok = build_uasset(names_ok)
scanner2, results2 = scan_synthetic(data_ok, "ABP_GoodAnim.uasset")
null_ok = [r for r in results2 if r.check_code == "NULL_ANIM_REF"]
test("NULL_ANIM_REF silent when AnimSequence present", len(null_ok) == 0)

# ── TEST: MISSING_SLOT detection ──
print("\n[4] MISSING_SLOT Check")
# Should trigger: has Montage but no Slot
names_noslot = ["AnimBlueprintGeneratedClass", "AnimGraphNode_Root", "AnimInstance"]
extra_noslot = b"PlayMontage" + b"\x00" * 50 + b"SlotAnimationTrack"
data_noslot = build_uasset(names_noslot, extra_binary=extra_noslot)
_, results_ns = scan_synthetic(data_noslot, "ABP_NoSlot.uasset")
slot_results = [r for r in results_ns if r.check_code == "MISSING_SLOT"]
test("MISSING_SLOT fires when no AnimGraphNode_Slot", len(slot_results) > 0)

# Should NOT trigger: has Slot
names_slot = ["AnimBlueprintGeneratedClass", "AnimGraphNode_Root",
              "AnimGraphNode_Slot", "AnimInstance"]
extra_slot = b"Montage" + b"\x00" * 50 + b"AnimGraphNode_Slot"
data_slot = build_uasset(names_slot, extra_binary=extra_slot)
_, results_s = scan_synthetic(data_slot, "ABP_HasSlot.uasset")
slot_ok = [r for r in results_s if r.check_code == "MISSING_SLOT"]
test("MISSING_SLOT silent when Slot present", len(slot_ok) == 0)

# ── TEST: BP_COMPLEXITY detection ──
print("\n[5] BP_COMPLEXITY Check")
# Build a BP with many K2Node_ occurrences
names_complex = ["BlueprintGeneratedClass", "EventGraph", "K2Node_CallFunction"]
extra_complex = b"K2Node_" * 120  # 120 node refs
data_complex = build_uasset(names_complex, extra_binary=extra_complex)
_, results_cx = scan_synthetic(data_complex, "BP_Complex.uasset")
cx_results = [r for r in results_cx if r.check_code == "BP_COMPLEXITY"]
test("BP_COMPLEXITY fires for 100+ nodes", len(cx_results) > 0)

# ── TEST: BP_EMPTY_GRAPH detection ──
print("\n[6] BP_EMPTY_GRAPH Check")
names_empty = ["BlueprintGeneratedClass", "EventGraph"]
data_empty = build_uasset(names_empty)  # no K2Node_ at all
_, results_eg = scan_synthetic(data_empty, "BP_Empty.uasset")
eg_results = [r for r in results_eg if r.check_code == "BP_EMPTY_GRAPH"]
test("BP_EMPTY_GRAPH fires for minimal nodes", len(eg_results) > 0)

# ── TEST: BP_DEBUG_NODES detection ──
print("\n[7] BP_DEBUG_NODES Check")
names_debug = ["BlueprintGeneratedClass", "EventGraph", "K2Node_CallFunction"]
extra_debug = b"K2Node_" * 5 + b"PrintString" + b"\x00" * 20 + b"DrawDebugLine"
data_debug = build_uasset(names_debug, extra_binary=extra_debug)
_, results_db = scan_synthetic(data_debug, "BP_Debug.uasset")
db_results = [r for r in results_db if r.check_code == "BP_DEBUG_NODES"]
test("BP_DEBUG_NODES fires for PrintString", len(db_results) > 0)

# ── TEST: BP_MASSIVE_ASSET detection ──
print("\n[8] BP_MASSIVE_ASSET Check")
names_big = ["BlueprintGeneratedClass", "EventGraph"]
extra_big = b"\x00" * (6 * 1024 * 1024)  # 6MB padding
data_big = build_uasset(names_big, extra_binary=extra_big)
_, results_big = scan_synthetic(data_big, "BP_Huge.uasset")
big_results = [r for r in results_big if r.check_code == "BP_MASSIVE_ASSET"]
test("BP_MASSIVE_ASSET fires for >5MB file", len(big_results) > 0)

# ── TEST: BP_CONSTRUCT_HEAVY detection ──
print("\n[9] BP_CONSTRUCT_HEAVY Check")
names_ch = ["BlueprintGeneratedClass", "EventGraph", "K2Node_CallFunction"]
extra_ch = b"K2Node_" * 5 + b"UserConstructionScript" + b"\x00" * 20 + b"SpawnActorFromClass"
data_ch = build_uasset(names_ch, extra_binary=extra_ch)
_, results_ch = scan_synthetic(data_ch, "BP_HeavyConstruct.uasset")
ch_results = [r for r in results_ch if r.check_code == "BP_CONSTRUCT_HEAVY"]
test("BP_CONSTRUCT_HEAVY fires for SpawnActor in ConstructionScript", len(ch_results) > 0)

# ── TEST: BP_TIMELINE_HEAVY detection ──
print("\n[10] BP_TIMELINE_HEAVY Check")
names_tl = ["BlueprintGeneratedClass", "EventGraph"]
extra_tl = b"K2Node_" * 5 + b"TimelineComponent" * 5
data_tl = build_uasset(names_tl, extra_binary=extra_tl)
_, results_tl = scan_synthetic(data_tl, "BP_ManyTimelines.uasset")
tl_results = [r for r in results_tl if r.check_code == "BP_TIMELINE_HEAVY"]
test("BP_TIMELINE_HEAVY fires for 5 Timeline components", len(tl_results) > 0)

# ── TEST: DEPRECATED_NODE detection ──
print("\n[11] DEPRECATED_NODE Check")
names_dep = ["AnimBlueprintGeneratedClass", "AnimGraphNode_Root",
             "AnimGraphNode_Deprecated_SequenceEvaluator", "AnimInstance"]
data_dep = build_uasset(names_dep)
_, results_dep = scan_synthetic(data_dep, "ABP_Deprecated.uasset")
dep_results = [r for r in results_dep if r.check_code == "DEPRECATED_NODE"]
test("DEPRECATED_NODE fires for deprecated class in name table", len(dep_results) > 0)

# ── TEST: Clean AnimBP produces no issues ──
print("\n[12] Clean AnimBP (no false positives)")
names_clean = ["AnimBlueprintGeneratedClass", "AnimGraphNode_Root",
               "AnimGraphNode_SequencePlayer", "AnimGraphNode_StateMachine",
               "AnimSequence", "AnimGraphNode_Slot", "AnimInstance",
               "Skeleton", "OutputPose", "BasePose"]
extra_clean = b"AnimGraphNode_Slot" + b"\x00" * 50 + b"AnimSequence" + b"\x00" * 50
data_clean = build_uasset(names_clean, extra_binary=extra_clean)
_, results_clean = scan_synthetic(data_clean, "ABP_Clean.uasset")
test("Clean AnimBP has zero issues", len(results_clean) == 0,
     f"got {len(results_clean)} issues: {[r.check_code for r in results_clean]}")

# ── TEST: MISSING_NOTIFY detection ──
print("\n[13] MISSING_NOTIFY Check")
names_notify = ["AnimBlueprintGeneratedClass", "AnimGraphNode_Root",
                "AnimNotifyEvent", "AnimInstance", "AnimSequence",
                "AnimGraphNode_SequencePlayer", "AnimGraphNode_Slot"]
extra_notify = b"AnimGraphNode_Slot" + b"\x00" * 20 + b"AnimSequence"
data_notify = build_uasset(names_notify, extra_binary=extra_notify)
_, results_notify = scan_synthetic(data_notify, "ABP_MissingNotify.uasset")
notify_results = [r for r in results_notify if r.check_code == "MISSING_NOTIFY"]
test("MISSING_NOTIFY fires when AnimNotifyEvent but no AnimNotify_ handler", len(notify_results) > 0)

# ── TEST: Confidence levels ──
print("\n[14] Confidence Level Verification")
for check in mod.CHECKS:
    test(f"{check.code} has confidence", check.confidence is not None)

low_checks = [c for c in mod.CHECKS if c.confidence == mod.Confidence.LOW]
test("Zero LOW confidence checks remain", len(low_checks) == 0,
     f"LOW: {[c.code for c in low_checks]}")

# ── TEST: Check handler registry completeness ──
print("\n[15] Handler Registry Completeness")
all_codes = {c.code for c in mod.CHECKS}
handler_codes = set(mod._CHECK_HANDLERS.keys())
# BP_BROKEN_REF and BP_CIRCULAR_DEP handled specially in _run_check
special = {"BP_BROKEN_REF", "BP_CIRCULAR_DEP"}
missing = all_codes - handler_codes - special
test("All checks have handlers", len(missing) == 0, f"missing: {missing}")

# ── TEST: APP_VERSION is set ──
print("\n[16] Version & CLI")
test("APP_VERSION defined", hasattr(mod, 'APP_VERSION') and mod.APP_VERSION)
test("Version is semantic", len(mod.APP_VERSION.split('.')) == 3)

# ── SUMMARY ──
print("\n" + "=" * 60)
total = passed + failed
print(f"RESULTS: {passed}/{total} passed, {failed} failed")
if failed == 0:
    print("ALL SCANNER CHECKS VERIFIED")
else:
    print(f"WARNING: {failed} test(s) failed")
print("=" * 60)

sys.exit(0 if failed == 0 else 1)
