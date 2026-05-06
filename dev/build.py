#!/usr/bin/env python3
"""
AnimBP Doctor — Dual Build System (Cross-Platform)
====================================================
Produces two standalone executables per app (.exe on Windows, no suffix on Linux/macOS):

  build/dev/AnimBP_Doctor_DEV       — PyInstaller, fast build, debuggable
  build/release/AnimBP_Doctor       — Nuitka, compiled to native C (no Python bytecode)
  build/release/AnimBP_FixGuide     — Nuitka, compiled to native C
  build/dev/AnimBP_FixGuide_DEV     — PyInstaller, fast build

Usage:
  python build.py dev          Build dev versions only (fast, ~30s)
  python build.py release      Build release versions only (slow, ~5-10min)
  python build.py protected    Build protected release (encrypt + Nuitka, slowest)
  python build.py demo         Build free demo (scan only, no auto-fix)
  python build.py all          Build both dev + release
  python build.py icon         Regenerate icon only
"""

import subprocess
import sys
import os
import shutil
import time
import platform

IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"
EXE_SUFFIX = ".exe" if IS_WINDOWS else ""

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(ROOT)  # AnimBPDoctor/
BUILD_DIR = os.path.join(ROOT, "build")
DEV_DIR = os.path.join(BUILD_DIR, "dev")
RELEASE_DIR = os.path.join(BUILD_DIR, "release")
PROTECTED_DIR = os.path.join(BUILD_DIR, "_protected")
PROTECT_SCRIPT = os.path.join(PROJECT_ROOT, "build", "protect.py")
ICON_ICO = os.path.join(ROOT, "icon.ico")
ICON_PNG = os.path.join(ROOT, "icon.png")

APPS = [
    {"source": "AnimBPDoctor.pyw",   "dev_name": "AnimBP_Doctor_DEV",  "release_name": "AnimBP_Doctor"},
    {"source": "AnimBPFixGuide.pyw", "dev_name": "AnimBP_FixGuide_DEV", "release_name": "AnimBP_FixGuide"},
]

# ── Helpers ──────────────────────────────────────────────────────

def banner(msg):
    width = 60
    print()
    print(f"  {'=' * width}")
    print(f"  |  {msg:<{width - 5}}|")
    print(f"  {'=' * width}")
    print()


def ensure_dirs():
    os.makedirs(DEV_DIR, exist_ok=True)
    os.makedirs(RELEASE_DIR, exist_ok=True)


def ensure_icon():
    icon = ICON_ICO if IS_WINDOWS else ICON_PNG
    if not os.path.exists(icon):
        print("  [icon] Generating icons ...")
        subprocess.run([sys.executable, os.path.join(ROOT, "generate_icon.py")], check=True)
    else:
        print(f"  [icon] Using existing {icon}")


def clean_nuitka_artifacts(source_name):
    """Remove Nuitka build artifacts from root to keep it clean."""
    stem = os.path.splitext(source_name)[0]
    for pattern in [f"{stem}.build", f"{stem}.dist", f"{stem}.onefile-build"]:
        p = os.path.join(ROOT, pattern)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)


# ── Dev Build (PyInstaller) ─────────────────────────────────────

def build_dev(app):
    source = os.path.join(ROOT, app["source"])
    name = app["dev_name"]
    banner(f"DEV BUILD: {name}")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", name,
        "--distpath", DEV_DIR,
        "--workpath", os.path.join(BUILD_DIR, "_pyinstaller_work"),
        "--specpath", os.path.join(BUILD_DIR, "_pyinstaller_specs"),
        "--clean",
    ]

    # --icon: .ico on Windows, .png on macOS/Linux (PyInstaller accepts both)
    if IS_WINDOWS and os.path.exists(ICON_ICO):
        cmd.extend(["--icon", ICON_ICO])
    elif os.path.exists(ICON_PNG):
        cmd.extend(["--icon", ICON_PNG])

    cmd.append(source)

    print(f"  $ {' '.join(cmd[-4:])}")
    t0 = time.time()
    result = subprocess.run(cmd, cwd=ROOT)
    elapsed = time.time() - t0

    out_name = f"{name}{EXE_SUFFIX}"
    exe_path = os.path.join(DEV_DIR, out_name)
    if result.returncode == 0 and os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print(f"\n  [OK] {exe_path}")
        print(f"       Size: {size_mb:.1f} MB  |  Built in {elapsed:.0f}s")
        return True
    else:
        print(f"\n  [FAIL] Dev build failed for {name} (exit {result.returncode})")
        return False


# ── Release Build (Nuitka — native C compilation) ───────────────

def build_release(app):
    source = os.path.join(ROOT, app["source"])
    name = app["release_name"]
    out_name = f"{name}{EXE_SUFFIX}"
    banner(f"RELEASE BUILD (Nuitka): {name}")

    cmd = [
        sys.executable, "-m", "nuitka",
        "--standalone",                       # Folder-based output (AV-safe, no self-extractor)
        f"--output-filename={out_name}",      # Output name
        f"--output-dir={RELEASE_DIR}",        # Output directory
        "--assume-yes-for-downloads",         # Auto-accept dependency downloads

        # ── IP Protection flags (max free-tier hardening) ──
        "--python-flag=no_docstrings",        # Strip all docstrings from binary
        "--python-flag=no_asserts",           # Strip assert statements
        "--python-flag=-OO",                  # Bytecode optimization level 2
        "--lto=yes",                          # Link-time optimization (harder decompilation)

        # ── Includes (standard lib modules used) ──
        "--enable-plugin=tk-inter",           # Tkinter support
    ]

    # ── Platform-specific flags ──
    if IS_WINDOWS:
        cmd.append("--windows-console-mode=disable")       # No console window
        if os.path.exists(ICON_ICO):
            cmd.append(f"--windows-icon-from-ico={ICON_ICO}")
        # Product metadata (PE resources, Windows-only)
        cmd.extend([
            "--product-name=AnimBPDoctor",
            "--product-version=2.5.0.0",
            "--file-description=Blueprint Diagnostic Tool for UE5",
            "--copyright=BP Doctor 2025-2026",
        ])
    elif IS_MACOS:
        cmd.append("--macos-disable-console")              # No console window
        if os.path.exists(ICON_PNG):
            cmd.append(f"--macos-app-icon={ICON_PNG}")
    else:
        if os.path.exists(ICON_PNG):
            cmd.append(f"--linux-icon={ICON_PNG}")

    cmd.append(source)

    print(f"  Compiling {app['source']} -> native C -> {out_name}")
    print(f"  This takes 3-10 minutes (one-time C compilation)...\n")

    t0 = time.time()
    result = subprocess.run(cmd, cwd=ROOT)
    elapsed = time.time() - t0

    # Clean up any leftover build dirs in root
    clean_nuitka_artifacts(app["source"])

    # Standalone mode outputs to a .dist folder
    stem = os.path.splitext(os.path.basename(app["source"]))[0]
    dist_dir = os.path.join(RELEASE_DIR, f"{stem}.dist")
    exe_path = os.path.join(dist_dir, out_name)

    if result.returncode == 0 and os.path.exists(exe_path):
        # Rename dist folder to product name
        final_dir = os.path.join(RELEASE_DIR, name)
        if os.path.exists(final_dir):
            shutil.rmtree(final_dir)
        os.rename(dist_dir, final_dir)
        exe_path = os.path.join(final_dir, out_name)

        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print(f"\n  [OK] {exe_path}")
        print(f"       Size: {size_mb:.1f} MB  |  Compiled in {elapsed:.0f}s")
        print(f"       Protection: Native C binary — NO Python bytecode exists")

        # Create zip for distribution
        import zipfile
        zip_path = os.path.join(RELEASE_DIR, f"{name}.zip")
        print(f"  [ZIP] Creating {zip_path}...")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for dirpath, dirnames, filenames in os.walk(final_dir):
                for fn in filenames:
                    fpath = os.path.join(dirpath, fn)
                    arcname = os.path.join(name, os.path.relpath(fpath, final_dir))
                    zf.write(fpath, arcname)
        zip_mb = os.path.getsize(zip_path) / (1024 * 1024)
        print(f"  [OK] {zip_path} ({zip_mb:.1f} MB)")
        return True
    else:
        print(f"\n  [FAIL] Release build failed for {name} (exit {result.returncode})")
        if IS_WINDOWS:
            print(f"         Make sure you have a C compiler installed (MSVC / MinGW)")
        elif IS_MACOS:
            print(f"         Make sure you have Xcode command-line tools installed")
        else:
            print(f"         Make sure you have gcc or clang installed")
        return False


# ── Protected Build (encrypt → Nuitka) ────────────────────────

def build_protected(app):
    source = os.path.join(ROOT, app["source"])
    protected_src = os.path.join(BUILD_DIR, "_protected", app["source"])
    name = app["release_name"]
    banner(f"PROTECTED BUILD: {name}")

    # Step 1: Run source protection
    print("  Encrypting source...")
    protect_script = PROTECT_SCRIPT
    os.makedirs(os.path.dirname(protected_src), exist_ok=True)
    result = subprocess.run(
        [sys.executable, protect_script, source, protected_src], cwd=ROOT)
    if result.returncode != 0 or not os.path.exists(protected_src):
        print(f"\n  [FAIL] Protection pipeline failed for {name}")
        return False

    # Step 2: Compile protected source with Nuitka
    print(f"\n  Compiling protected source...")
    papp = dict(app)
    papp["source"] = os.path.relpath(protected_src, ROOT)
    ok = build_release(papp)

    # Step 3: Clean up (don't ship intermediate source)
    if os.path.exists(protected_src):
        os.remove(protected_src)
        print(f"  [CLEAN] Removed {protected_src}")
    pdir = os.path.dirname(protected_src)
    if os.path.isdir(pdir) and not os.listdir(pdir):
        os.rmdir(pdir)

    return ok


# ── Main ─────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args or args[0] not in ("dev", "release", "protected", "demo", "all", "icon"):
        print(__doc__)
        sys.exit(1)

    mode = args[0]
    ensure_dirs()

    if mode == "icon":
        subprocess.run([sys.executable, os.path.join(ROOT, "generate_icon.py")], check=True)
        return

    ensure_icon()
    results = []

    if mode in ("dev", "all"):
        for app in APPS:
            ok = build_dev(app)
            results.append(("DEV " + app["dev_name"], ok))

    if mode in ("release", "all"):
        for app in APPS:
            ok = build_release(app)
            results.append(("RELEASE " + app["release_name"], ok))

    if mode == "protected":
        for app in APPS:
            ok = build_protected(app)
            results.append(("PROTECTED " + app["release_name"], ok))

    if mode == "demo":
        # Build demo: main scanner only, DEMO_MODE=True, encrypted (same protection as Pro)
        demo_app = APPS[0]
        banner("DEMO BUILD: BP_Doctor_Demo (encrypted)")
        demo_src = os.path.join(BUILD_DIR, "_demo", demo_app["source"])
        os.makedirs(os.path.dirname(demo_src), exist_ok=True)

        # Set DEMO_MODE = True in source copy
        with open(os.path.join(ROOT, demo_app["source"]), "r", encoding="utf-8") as f:
            src = f.read()
        src = src.replace("DEMO_MODE = False", "DEMO_MODE = True", 1)
        with open(demo_src, "w", encoding="utf-8") as f:
            f.write(src)
        print(f"  [OK] DEMO_MODE = True set")

        # Run protect.py — encrypt check data + detection strings (AV-safe integer-array encoding)
        protect_script = PROTECT_SCRIPT
        protected_demo = os.path.join(BUILD_DIR, "_demo", "_protected_" + demo_app["source"])
        print(f"  [PROTECT] Encrypting demo source...")
        pres = subprocess.run(
            [sys.executable, protect_script, demo_src, protected_demo], cwd=ROOT)
        if pres.returncode != 0 or not os.path.exists(protected_demo):
            print(f"\n  [FAIL] Demo protection pipeline failed")
            results.append(("DEMO BP_Doctor_Demo", False))
        else:
            # Compile protected+demo source with Nuitka
            demo_build_app = dict(demo_app)
            demo_build_app["source"] = os.path.relpath(protected_demo, ROOT)
            demo_build_app["release_name"] = "BP_Doctor_Demo"
            ok = build_release(demo_build_app)
            results.append(("DEMO BP_Doctor_Demo", ok))

        # Clean up intermediate files
        for f in [demo_src, protected_demo]:
            if os.path.exists(f):
                os.remove(f)
        demo_dir = os.path.join(BUILD_DIR, "_demo")
        if os.path.isdir(demo_dir) and not os.listdir(demo_dir):
            os.rmdir(demo_dir)

    # ── Summary ──
    banner("BUILD SUMMARY")
    all_ok = True
    for label, ok in results:
        status = "OK" if ok else "FAILED"
        icon = "[+]" if ok else "[X]"
        print(f"  {icon} {label:.<45} {status}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print("  All builds succeeded!")
        if mode in ("release", "protected", "all"):
            print(f"\n  Release executables ready in: {RELEASE_DIR}")
            print("  These are native C binaries — source code CANNOT be recovered.")
        if mode == "protected":
            print("  Protection: encrypted checks + encrypted detection strings + anti-debug")
        if mode in ("dev", "all"):
            print(f"\n  Dev executables ready in: {DEV_DIR}")
    else:
        print("  Some builds failed. Check output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
