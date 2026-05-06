#!/usr/bin/env python3
"""AnimBP Doctor v2.0 — Feature Verification Test Suite"""

import importlib.util
import sys
import os
import tempfile
import json
import struct
import shutil

# Load the module without launching GUI
spec = importlib.util.spec_from_file_location("abpd", "AnimBPDoctor.pyw")
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

print("=" * 60)
print("TEST SUITE: AnimBP Doctor v2.0 Feature Verification")
print("=" * 60)

# ── TEST 1: BackupManager ──
print("\n[1] BackupManager")
tmpdir = tempfile.mkdtemp()
try:
    bm = mod.BackupManager(tmpdir)
    test("Init creates backup dir", bm.backup_dir.exists())
    test("Empty count = 0", bm.get_backup_count() == 0)

    # Create a test file and back it up
    test_file = os.path.join(tmpdir, "test.uasset")
    with open(test_file, "wb") as f:
        f.write(b"ORIGINAL_CONTENT_12345")

    backup_path = bm.backup_file(test_file, "Test backup")
    test("Backup file created", os.path.exists(backup_path))
    test("Backup count = 1", bm.get_backup_count() == 1)
    with open(backup_path, "rb") as f:
        test("Backup content matches", f.read() == b"ORIGINAL_CONTENT_12345")

    # Modify the original
    with open(test_file, "wb") as f:
        f.write(b"MODIFIED_CONTENT_99999")

    # Revert all
    reverted = bm.revert_all()
    test("Revert returns paths", len(reverted) == 1)
    with open(test_file, "rb") as f:
        test("Original restored", f.read() == b"ORIGINAL_CONTENT_12345")
    test("Backup removed after revert", not os.path.exists(backup_path))
    test("Count = 0 after revert", bm.get_backup_count() == 0)

    # Test single-file revert
    bm2 = mod.BackupManager(tmpdir)
    bm2.backup_file(test_file, "Test 2")
    with open(test_file, "wb") as f:
        f.write(b"CHANGED_AGAIN")
    ok = bm2.revert_file(test_file)
    with open(test_file, "rb") as f:
        test("Single file revert works", ok and f.read() == b"ORIGINAL_CONTENT_12345")
finally:
    shutil.rmtree(tmpdir, ignore_errors=True)

# ── TEST 2: ProjectConfig ──
print("\n[2] ProjectConfig")
tmpdir = tempfile.mkdtemp()
try:
    pc = mod.ProjectConfig(tmpdir)
    test("Has default directories", "skeletal_meshes" in pc.data["directories"])
    test("Has default variables", "speed" in pc.data["variable_mapping"])
    test("Has naming conventions", "animbp_prefix" in pc.data["naming_conventions"])

    pc.set_val(["directories", "skeletal_meshes"], ["Content/MyChars"])
    test("set_val works", pc.get("directories", "skeletal_meshes") == ["Content/MyChars"])

    pc.save()
    pc2 = mod.ProjectConfig(tmpdir)
    test("Config persists to disk", pc2.get("directories", "skeletal_meshes") == ["Content/MyChars"])
    test("Defaults preserved on reload", pc2.get("variable_mapping", "speed") == "Speed")
    test("Deep merge keeps auto_fix", pc2.get("auto_fix", "create_backups") == True)
finally:
    shutil.rmtree(tmpdir, ignore_errors=True)

# ── TEST 3: TemplateManager ──
print("\n[3] TemplateManager")
tm = mod.TemplateManager()
test("4 built-in templates", len(tm.templates) == 4)
test("Has montage_slot_wiring", tm.get("montage_slot_wiring") is not None)
test("Has skeletal_mesh_link", tm.get("skeletal_mesh_link") is not None)
test("Has blend_space_setup", tm.get("blend_space_setup") is not None)
test("Has state_machine_base", tm.get("state_machine_base") is not None)

# Render
script = tm.render("montage_slot_wiring", {
    "slot_name": "UpperBody",
    "animblueprint": "/Game/ABP_Hero",
})
test("Render replaces slot_name", "UpperBody" in script)
test("Render replaces animblueprint", "/Game/ABP_Hero" in script)
test("No unresolved {slot_name}", "{slot_name}" not in script)
test("No unresolved {animblueprint}", "{animblueprint}" not in script)

# State machine template
sm = tm.render("state_machine_base", {
    "animblueprint": "/Game/ABP_Test",
    "speed_var": "MoveSpeed",
    "is_falling_var": "bInAir",
    "walk_threshold": "10.0",
})
test("SM: speed var replaced", "MoveSpeed" in sm)
test("SM: falling var replaced", "bInAir" in sm)
test("SM: threshold replaced", "10.0" in sm)
test("SM: has C++ code", "NativeUpdateAnimation" in sm)

# Export
tmpdir = tempfile.mkdtemp()
try:
    path = tm.export_script("montage_slot_wiring",
        {"slot_name": "DefaultSlot", "animblueprint": "/Game/ABP"},
        tmpdir)
    test("Export creates file", path is not None and os.path.exists(path))
    test("Export is .py", path.endswith(".py"))
    with open(path) as f:
        test("Export has rendered content", "DefaultSlot" in f.read())
finally:
    shutil.rmtree(tmpdir, ignore_errors=True)

# Skeletal mesh link template (C++ output)
cpp = tm.render("skeletal_mesh_link", {
    "actor_blueprint": "/Game/BP_Hero",
    "animblueprint": "/Game/ABP_Hero",
    "skeletal_mesh": "/Game/SK_Hero",
    "component_name": "CharMesh",
})
test("Skeletal link: has C++ code", "SetAnimInstanceClass" in cpp)
test("Skeletal link: actor replaced", "/Game/BP_Hero" in cpp)

# Categories
test("Has Animation Setup category", "Animation Setup" in tm.categories())

# ── TEST 4: ScriptImporter - JSON ──
print("\n[4] ScriptImporter - JSON Config")
si = mod.ScriptImporter(tm)

config = {
    "actions": [
        {"method": "AddSlotNode", "params": {
            "animblueprint_path": "/Game/ABP_Hero",
            "slot_name": "DefaultSlot",
        }},
        {"method": "SetAnimClass", "params": {
            "component_path": "/Game/BP_Hero",
            "animblueprint_path": "/Game/ABP_Hero",
        }},
    ]
}
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump(config, f)
    tmp = f.name
ok, actions, errors = si.parse_file(tmp)
os.unlink(tmp)
test("Valid JSON parses OK", ok)
test("2 actions parsed", len(actions) == 2)
test("No errors", len(errors) == 0)
test("First is AddSlotNode", actions[0]["method"] == "AddSlotNode")
test("Second is SetAnimClass", actions[1]["method"] == "SetAnimClass")

# Unknown method
bad = {"actions": [{"method": "FakeMethod", "params": {}}]}
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump(bad, f)
    tmp = f.name
ok2, _, err2 = si.parse_file(tmp)
os.unlink(tmp)
test("Unknown method fails", not ok2)
test("Error names the method", "FakeMethod" in err2[0])

# Missing params
bad2 = {"actions": [{"method": "AddSlotNode", "params": {"slot_name": "X"}}]}
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump(bad2, f)
    tmp = f.name
ok3, _, err3 = si.parse_file(tmp)
os.unlink(tmp)
test("Missing params fails", not ok3)
test("Error names missing param", "animblueprint_path" in err3[0])

# ── TEST 5: ScriptImporter - C++ ──
print("\n[5] ScriptImporter - C++ Macros")

cpp_content = (
    '// Setup script\n'
    'ANIMBP_DOCTOR_ACTION(AddSlotNode,\n'
    '    animblueprint_path="/Game/ABP_Warrior",\n'
    '    slot_name="DefaultSlot")\n'
    '\n'
    'ANIMBP_DOCTOR_ACTION(ConfigureStateMachine,\n'
    '    animblueprint_path="/Game/ABP_Warrior",\n'
    '    speed_var="Speed",\n'
    '    is_falling_var="bIsFalling")\n'
)
with tempfile.NamedTemporaryFile(mode="w", suffix=".cpp", delete=False) as f:
    f.write(cpp_content)
    tmp = f.name
ok, actions, errors = si.parse_file(tmp)
os.unlink(tmp)
test("C++ parses OK", ok)
test("2 actions from macros", len(actions) == 2)
test("First is AddSlotNode", actions[0]["method"] == "AddSlotNode")
test("slot_name extracted", actions[0]["params"].get("slot_name") == "DefaultSlot")
test("Second is ConfigureStateMachine", actions[1]["method"] == "ConfigureStateMachine")
test("speed_var extracted", actions[1]["params"].get("speed_var") == "Speed")

# No macros
with tempfile.NamedTemporaryFile(mode="w", suffix=".cpp", delete=False) as f:
    f.write("void Foo() {}")
    tmp = f.name
ok4, _, err4 = si.parse_file(tmp)
os.unlink(tmp)
test("No-macro file fails gracefully", not ok4)
test("Error mentions ANIMBP_DOCTOR_ACTION", "ANIMBP_DOCTOR_ACTION" in err4[0])

# ── TEST 6: ScriptImporter - Execute ──
print("\n[6] ScriptImporter - Execute Actions")
tmpdir = tempfile.mkdtemp()
try:
    test_actions = [
        {"method": "AddSlotNode",
         "params": {"slot_name": "DefaultSlot", "animblueprint": "/Game/ABP"},
         "template_id": "montage_slot_wiring",
         "description": "Add slot node"},
    ]
    results = si.execute_actions(test_actions, tmpdir)
    test("Execute returns results", len(results) == 1)
    desc, success, msg = results[0]
    test("Execution succeeded", success)
    test("Result message has file", "Saved" in msg)
    files = os.listdir(tmpdir)
    test("Output file on disk", len(files) == 1)
    test("Output is .py", files[0].endswith(".py"))
finally:
    shutil.rmtree(tmpdir, ignore_errors=True)

# ── TEST 7: FixEngine - Action Generation ──
print("\n[7] FixEngine - Action Generation")
se = mod.ScannerEngine()
fe = mod.FixEngine(se)

mock_results = [
    mod.ScanResult(
        check_code="BROKEN_BLEND_WT", severity="WARNING",
        animblueprint="ABP_Test", asset_path="/Game/ABP_Test",
        description="Blend weight outside range. Found weight: 1.500",
        auto_fixable=True),
    mod.ScanResult(
        check_code="MISSING_SLOT", severity="WARNING",
        animblueprint="ABP_Hero", asset_path="/Game/ABP_Hero",
        description="No Slot node found",
        auto_fixable=True),
    mod.ScanResult(
        check_code="NULL_ANIM_REF", severity="ERROR",
        animblueprint="ABP_Boss", asset_path="/Game/ABP_Boss",
        description="Sequence Player has no animation",
        auto_fixable=False),
]

actions = fe.generate_fix_actions(mock_results)
test("Generated 3 actions", len(actions) == 3)

bw = [a for a in actions if a.check_code == "BROKEN_BLEND_WT"][0]
test("BW is binary_patch", bw.fix_type == "binary_patch")
test("BW has patch_data", bw.patch_data is not None)
test("BW old = 1.5", abs(bw.patch_data["old_value"] - 1.5) < 0.01)
test("BW new = 1.0", abs(bw.patch_data["new_value"] - 1.0) < 0.01)

slot = [a for a in actions if a.check_code == "MISSING_SLOT"][0]
test("Slot is generated_script", slot.fix_type == "generated_script")
test("Slot script has unreal import", "import unreal" in slot.script_content)

manual = [a for a in actions if a.check_code == "NULL_ANIM_REF"][0]
test("NULL_ANIM_REF is manual", manual.fix_type == "manual")

# ── TEST 8: FixEngine - Binary Patch ──
print("\n[8] FixEngine - Binary Patch Execution")
tmpdir = tempfile.mkdtemp()
try:
    test_file = os.path.join(tmpdir, "ABP_Test.uasset")
    data = bytearray(b"\x00" * 100)
    marker = b"BlendWeight"
    data[20:20 + len(marker)] = marker
    bad_float = struct.pack("f", 1.5)
    data[20 + len(marker):20 + len(marker) + 4] = bad_float
    with open(test_file, "wb") as f:
        f.write(data)

    se2 = mod.ScannerEngine()
    se2.animblueprints = [mod.AnimBPInfo(
        name="ABP_Test", asset_path="/Game/ABP_Test",
        file_path=test_file, file_size=100)]

    fe2 = mod.FixEngine(se2)
    fe2.backup_mgr = mod.BackupManager(tmpdir)

    action = mod.FixAction(
        check_code="BROKEN_BLEND_WT", animblueprint="ABP_Test",
        asset_path="/Game/ABP_Test", file_path=test_file,
        fix_type="binary_patch", description="Clamp",
        preview="test",
        patch_data={
            "type": "float_replace",
            "search_marker": "BlendWeight",
            "old_value": 1.5,
            "new_value": 1.0,
        })

    ok, msg = fe2._execute_one(action, tmpdir)
    test("Patch succeeded", ok, msg)

    with open(test_file, "rb") as f:
        patched = f.read()
    offset = 20 + len(marker)
    val = struct.unpack("f", patched[offset:offset + 4])[0]
    test("Float patched to 1.0", abs(val - 1.0) < 0.001, f"got {val}")
    test("Backup created", fe2.backup_mgr.get_backup_count() == 1)

    # Revert
    fe2.backup_mgr.revert_all()
    with open(test_file, "rb") as f:
        rev = f.read()
    rev_val = struct.unpack("f", rev[offset:offset + 4])[0]
    test("Revert restored 1.5", abs(rev_val - 1.5) < 0.001, f"got {rev_val}")
finally:
    shutil.rmtree(tmpdir, ignore_errors=True)

# ── TEST 9: Script Generation to Disk ──
print("\n[9] FixEngine - Script Save")
tmpdir = tempfile.mkdtemp()
try:
    fe3 = mod.FixEngine(mod.ScannerEngine())
    action = mod.FixAction(
        check_code="MISSING_SLOT", animblueprint="ABP_Hero",
        asset_path="/Game/ABP_Hero", file_path="",
        fix_type="generated_script", description="Add slot",
        preview="test",
        script_content="import unreal\nunreal.log('hello')")
    ok, msg = fe3._exec_save_script(action, tmpdir)
    test("Script save succeeded", ok, msg)
    scripts_dir = os.path.join(tmpdir, ".animbpdoctor", "generated_scripts")
    files = os.listdir(scripts_dir)
    test("Script file exists", len(files) == 1)
    with open(os.path.join(scripts_dir, files[0])) as f:
        test("Script content correct", "import unreal" in f.read())
finally:
    shutil.rmtree(tmpdir, ignore_errors=True)

# ── TEST 10: User Template CRUD ──
print("\n[10] User Template Save/Load")
user_tmpl = {
    "id": "test_custom_tmpl_xyz",
    "name": "Test Custom",
    "description": "A test",
    "category": "Test",
    "variables": {"x": {"type": "string", "default": "hi", "description": "test"}},
    "script_template": "echo {x}",
}
tm2 = mod.TemplateManager()
path = tm2.save_user_template(user_tmpl)
test("User template saved to disk", os.path.exists(path))

tm3 = mod.TemplateManager()
custom = tm3.get("test_custom_tmpl_xyz")
test("User template loaded on init", custom is not None)
if custom:
    test("Has correct name", custom["name"] == "Test Custom")
    test("Marked user_created", custom.get("user_created") == True)

rendered = tm3.render("test_custom_tmpl_xyz", {"x": "world"})
test("User template renders", rendered == "echo world")

# Cleanup
os.unlink(path)

# ── SUMMARY ──
print("\n" + "=" * 60)
total = passed + failed
print(f"RESULTS: {passed}/{total} passed, {failed} failed")
if failed == 0:
    print("ALL TESTS PASSED")
else:
    print(f"WARNING: {failed} test(s) failed")
print("=" * 60)

sys.exit(0 if failed == 0 else 1)
