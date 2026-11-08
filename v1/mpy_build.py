#!/usr/bin/env python3

# mpy_build.py - MicroPython Custom Firmware Build System

import os
import shutil
import subprocess
import sys
import tomllib  # Python 3.11+
from datetime import datetime
from pathlib import Path

# All paths are children of the directory containing this script.
BUILD_ROOT = Path(__file__).resolve().parent

BOARDS_TOML = BUILD_ROOT / "boards.toml"
ADDONS_DIR = BUILD_ROOT / "addons"
ADDONS_SPECIFIC_DIR = BUILD_ROOT / "addons_specific"
FIRMWARE_DIR = BUILD_ROOT / "firmware"
BUILD_LOG = FIRMWARE_DIR / "build.log"
C_EXTENSIONS_BASE = BUILD_ROOT / "c_extensions"

DEFAULT_MICROPY_PATH = BUILD_ROOT / "micropython"
REPOS_PATH = BUILD_ROOT / "repos"

# ESP-IDF locations — all under BUILD_ROOT.
IDF_ROOT = BUILD_ROOT / "esp-idf"
IDF_TOOLS_ROOT = BUILD_ROOT / "tools"
IDF_PYTHON = IDF_TOOLS_ROOT / "python_env" / "idf5.5_py3.13_env" / "bin" / "python3"
IDF_REQS = IDF_ROOT / "tools" / "requirements" / "requirements.core.txt"
IDF_CONSTRAINTS = IDF_TOOLS_ROOT / "espidf.constraints.v5.5.txt"

# -----------------------------
# Utility helpers
# -----------------------------

def sh(cmd: str, cwd: Path | None = None, capture: bool = False, env: dict | None = None):
    if capture:
        return subprocess.check_output(cmd, cwd=str(cwd) if cwd else None, shell=True, text=True, env=env).strip()
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, shell=True, check=True, env=env)
    return None

def run(cmd_list: list[str], cwd: Path | None = None, capture: bool = False, env: dict | None = None):
    if capture:
        return subprocess.check_output(cmd_list, cwd=str(cwd) if cwd else None, text=True, env=env).strip()
    subprocess.run(cmd_list, cwd=str(cwd) if cwd else None, check=True, env=env)
    return None

def safe_run(cmd: str, cwd: Path | None = None, env: dict | None = None) -> bool:
    """Run command with proper error handling."""
    try:
        subprocess.run(cmd, cwd=str(cwd) if cwd else None, shell=True, check=True, env=env)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[error] Command failed (exit {e.returncode}): {cmd}")
        if cwd:
            print(f"[error] Working directory: {cwd}")
        return False

def safe_run_list(cmd_list: list[str], cwd: Path | None = None, env: dict | None = None) -> bool:
    """Run command list with proper error handling."""
    try:
        subprocess.run(cmd_list, cwd=str(cwd) if cwd else None, check=True, env=env)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[error] Command failed (exit {e.returncode}): {' '.join(cmd_list)}")
        if cwd:
            print(f"[error] Working directory: {cwd}")
        return False

# -----------------------------
# Build environment validation
# -----------------------------

def validate_build_environment():
    """Validate required tools and paths exist."""
    errors = []
    
    if not IDF_ROOT.exists():
        errors.append(f"ESP-IDF not found at {IDF_ROOT}")
    
    if not IDF_PYTHON.exists():
        errors.append(f"ESP-IDF Python not found at {IDF_PYTHON}")
        errors.append("Run: cd ~/esp/esp-idf && ./install.sh")
    
    # Check for basic build tools
    try:
        subprocess.run(["make", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        errors.append("make not found - install build-essential")
    
    try:
        subprocess.run(["cmake", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        errors.append("cmake not found")
    
    if errors:
        print("[error] Build environment validation failed:")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)
    
    print("[validation] Build environment OK")

# -----------------------------
# Controlled ESP32 build env
# -----------------------------

def assert_paths():
    if not IDF_ROOT.exists():
        print(f"[error] ESP-IDF not found at {IDF_ROOT}")
        sys.exit(1)
    if not IDF_PYTHON.exists():
        print(f"[error] ESP-IDF python not found at {IDF_PYTHON}")
        print("        Run: cd ~/esp/esp-idf && ./install.sh")
        sys.exit(1)

def discover_tool_bins() -> list[str]:
    """Scan ~/.espressif/tools/*/*/bin and include any existing bin dirs, prioritizing newer versions."""
    bins: list[str] = []
    tools = IDF_TOOLS_ROOT / "tools"
    if tools.exists():
        for t in tools.iterdir():
            if not t.is_dir():
                continue
            # For each tool, collect all versions then sort to prefer newer ones
            tool_bins = []
            for sub in t.iterdir():
                if sub.is_dir():
                    bin1 = sub / "bin"
                    if bin1.exists():
                        tool_bins.append(str(bin1))
                    # sometimes another nesting (e.g. xtensa-esp-elf/esp-*/xtensa-esp-elf/bin)
                    for sub2 in sub.iterdir():
                        if sub2.is_dir():
                            bin2 = sub2 / "bin"
                            if bin2.exists():
                                tool_bins.append(str(bin2))
            
            # Sort tool bins to prefer newer versions (reverse sort puts newer dates first)
            tool_bins.sort(reverse=True)
            bins.extend(tool_bins)
    
    # de-dup, preserve order (newer versions first)
    seen = set()
    dedup = []
    for p in bins:
        if p not in seen:
            seen.add(p)
            dedup.append(p)
    return dedup

def make_esp_env() -> dict:
    """Create an environment that mimics export.sh without sourcing it."""
    assert_paths()
    env = os.environ.copy()
    tool_bins = discover_tool_bins()
    # Prepend our tool bins
    env["PATH"] = ":".join(tool_bins + [env.get("PATH", "")])

    # Core vars used by MicroPython's Makefiles / CMake
    env["IDF_PATH"] = str(IDF_ROOT)
    env["IDF_TOOLS_PATH"] = str(IDF_TOOLS_ROOT)  # point to BUILD_ROOT/tools, not ~/.espressif
    # Force MicroPython/Make to use the managed interpreter
    env["PYTHON"] = str(IDF_PYTHON)
    # Some tools sniff this to locate venv
    env["IDF_PYTHON_ENV_PATH"] = str(IDF_PYTHON.parent.parent)
    # Disable specific compiler warning that causes false positives
    env["CFLAGS"] = env.get("CFLAGS", "") + " -Wno-error=maybe-uninitialized"
    return env

def enforce_idf_constraints() -> bool:
    """Install ESP-IDF requirement versions with error handling."""
    if not (IDF_REQS.exists() and IDF_CONSTRAINTS.exists()):
        print("[warn] Could not find requirements/constraints files; skipping enforcement.")
        return True

    print("[repair] Enforcing ESP-IDF python constraints…")

    if not safe_run_list([
        str(IDF_PYTHON), "-m", "pip", "install",
        "--force-reinstall", "--upgrade", "--upgrade-strategy", "eager",
        "-r", str(IDF_REQS), "-c", str(IDF_CONSTRAINTS)
    ]):
        return False

    # Verify critical packages
    try:
        out = subprocess.check_output([
            str(IDF_PYTHON), "-m", "pip", "show", "click", "setuptools"
        ], text=True)
        print("[repair] Using:\n" + out)
        print("[repair] Constraint versions installed.")
        return True
    except subprocess.CalledProcessError:
        print("[error] Failed to verify constraint packages")
        return False

def apply_micropython_lockfile(repo_path: Path, idf_target: str) -> bool:
    """Apply MicroPython's official dependency lockfile for the target."""
    lockfile_name = f"dependencies.lock.{idf_target}"
    lockfile_path = repo_path / "ports" / "esp32" / "lockfiles" / lockfile_name

    if not lockfile_path.exists():
        print(f"[lockfile] Warning: {lockfile_name} not found, using default component versions")
        return True

    print(f"[lockfile] Applying {lockfile_name} for consistent component versions...")

    # Read the lockfile to extract specific component versions
    try:
        with open(lockfile_path, 'r') as f:
            lockfile_content = f.read()

        # The lockfile is in YAML format, but we just need to ensure the build uses it
        # MicroPython's build system will automatically use this if we set the right environment
        return True
    except Exception as e:
        print(f"[lockfile] Warning: Failed to read lockfile {lockfile_path}: {e}")
        return True

# -----------------------------
# Build directory management
# -----------------------------

def _get_build_dir(port_dir: Path, port: str, board_token: str | None) -> Path:
    """Get consistent build directory path for all ports."""
    if board_token:
        return port_dir / f"build-{board_token}"
    else:
        return port_dir / "build"

def _clean_build_dirs(port_dir: Path, port: str, board_token: str | None):
    """Clean build directories consistently."""
    build_dir = _get_build_dir(port_dir, port, board_token)
    if build_dir.exists():
        sh(f"rm -rf '{build_dir}'")
        print(f"[clean] Removed {build_dir}")

def _find_firmware_path(port_dir: Path, ext: str, port: str, board_token: str | None) -> tuple[Path, bool] | tuple[None, bool]:
    """Find firmware file in correct build directory.
    Returns (path, is_merged) where is_merged=True means the binary is a merged
    flash image (bootloader+partition table+app) and must be flashed at offset 0x0.
    """
    build_dir = _get_build_dir(port_dir, port, board_token)
    if port == "esp32":
        # Non-SPIRAM builds produce micropython.bin (app only, flash at 0x10000).
        # SPIRAM builds produce firmware.bin which is a merged image (boot+pt+app,
        # flash at 0x0) — detected by checking for a valid app header at offset 0x10000.
        p = build_dir / f"micropython.{ext}"
        if p.exists():
            return p, False
        p = build_dir / f"firmware.{ext}"
        if p.exists():
            # Confirm it's actually a merged image by checking for app magic at 0x10000
            with open(p, "rb") as fh:
                fh.seek(0x10000)
                magic = fh.read(1)
            if magic == b"\xe9":
                return p, True
        return None, False
    else:
        p = build_dir / f"firmware.{ext}"
        return (p, False) if p.exists() else (None, False)

# -----------------------------
# Repo & addons
# -----------------------------

def ensure_repo(board_name, cfg) -> Path:
    if "repo" in cfg:
        repo_url = cfg["repo"]
        repo_dir = REPOS_PATH / board_name
        if not repo_dir.exists():
            print(f"[update] Cloning {board_name} repo from {repo_url}…")
            REPOS_PATH.mkdir(parents=True, exist_ok=True)
            sh(f"git clone {repo_url} {repo_dir}")
        else:
            print(f"[update] Updating repo for {board_name}…")
            # Check if on a branch or detached HEAD
            try:
                sh("git symbolic-ref -q HEAD", cwd=repo_dir, capture=True)
                # On a branch, safe to pull
                sh("git pull --ff-only", cwd=repo_dir)
            except:
                # Detached HEAD or error, just fetch
                print(f"[update] Detached HEAD state, fetching updates…")
                sh("git fetch --all", cwd=repo_dir)
            sh("git submodule update --init --recursive", cwd=repo_dir)
        return repo_dir
    else:
        if not DEFAULT_MICROPY_PATH.exists():
            print("[update] Cloning default MicroPython repo…")
            sh(f"git clone https://github.com/micropython/micropython.git {DEFAULT_MICROPY_PATH}")
            sh("git submodule update --init --recursive", cwd=DEFAULT_MICROPY_PATH)
        else:
            print("[update] Updating default MicroPython repo…")
            # Check if on a branch or detached HEAD
            try:
                sh("git symbolic-ref -q HEAD", cwd=DEFAULT_MICROPY_PATH, capture=True)
                # On a branch, safe to pull
                sh("git pull --ff-only", cwd=DEFAULT_MICROPY_PATH)
            except:
                # Detached HEAD (e.g., checked out tag), just fetch
                print(f"[update] Detached HEAD state, fetching updates…")
                sh("git fetch --all", cwd=DEFAULT_MICROPY_PATH)
            sh("git submodule update --init --recursive", cwd=DEFAULT_MICROPY_PATH)
        return DEFAULT_MICROPY_PATH

def get_micropython_version(path: Path) -> str:
    pyproj = path / "pyproject.toml"
    if pyproj.exists():
        with open(pyproj) as f:
            for line in f:
                if line.startswith("version"):
                    return line.split("=")[1].strip().strip('"')
    try:
        return sh("git describe --tags", cwd=path, capture=True)
    except Exception:
        return "unknown"

def sync_addons(modules_dir: Path, board_name: str, cfg: dict):
    modules_dir.mkdir(parents=True, exist_ok=True)
    if ADDONS_DIR.exists():
        for fname in os.listdir(ADDONS_DIR):
            if fname.endswith(".py"):
                src = ADDONS_DIR / fname
                dst = modules_dir / fname
                sh(f"cp '{src}' '{dst}'")
                print(f"[addons] Added {fname} (common)")

    for fname in cfg.get("addons", []):
        src = ADDONS_SPECIFIC_DIR / fname
        if src.exists():
            dst = modules_dir / fname
            sh(f"cp '{src}' '{dst}'")
            print(f"[addons] Added {fname} (specific)")
        else:
            print(f"[addons] Warning: {fname} listed for {board_name} but not found in addons_specific/")

def setup_codal_repo(name: str, cfg: dict) -> Path:
    """Set up a CODAL-based port repo (e.g. micropython-microbit-v2).

    Deliberately does NOT reuse ensure_repo(): that function runs
    `git submodule update --init --recursive` unconditionally, which would
    replace the lib/micropython symlink below with a real submodule checkout
    pinned to whatever (older) core commit the upstream project declares,
    undoing the rebase onto the shared mainline checkout on every rebuild.
    """
    repo_url = cfg["repo"]
    repo_dir = REPOS_PATH / name

    if not repo_dir.exists():
        print(f"[{name}] Cloning {repo_url}…")
        REPOS_PATH.mkdir(parents=True, exist_ok=True)
        sh(f"git clone {repo_url} {repo_dir}")

    codal_dir = repo_dir / "lib" / "codal"
    if not (codal_dir / ".git").exists():
        print(f"[{name}] Initialising lib/codal submodule…")
        sh("git submodule update --init lib/codal", cwd=repo_dir)

    mpy_link = repo_dir / "lib" / "micropython"
    if mpy_link.is_symlink():
        pass
    elif mpy_link.is_dir():
        print(f"[{name}] Removing empty lib/micropython submodule placeholder…")
        mpy_link.rmdir()
        mpy_link.symlink_to(DEFAULT_MICROPY_PATH)
    elif not mpy_link.exists():
        mpy_link.symlink_to(DEFAULT_MICROPY_PATH)

    print(f"[{name}] Building mpy-cross…")
    sh(f"make -C {DEFAULT_MICROPY_PATH}/mpy-cross")

    return repo_dir

def resolve_c_extensions(name: str, cfg: dict) -> str:
    """Resolve the c_extensions config key to a USER_C_MODULES= make argument."""
    c_ext = (cfg.get("c_extensions") or "").strip()
    if not c_ext:
        return ""
    c_ext_path = C_EXTENSIONS_BASE / c_ext
    if not c_ext_path.is_dir():
        raise FileNotFoundError(f"[{name}] C extension {c_ext_path} not found")
    print(f"[{name}] Using C extensions: {c_ext_path}")
    return f"USER_C_MODULES={c_ext_path}"

def build_codal_board(name: str, cfg: dict) -> bool:
    """Build a CODAL-based port (e.g. micro:bit V2 / micropython-microbit-v2)."""
    print(f"\n=== Building {name} (codal) ===")

    try:
        port_root = setup_codal_repo(name, cfg)
        version = get_micropython_version(DEFAULT_MICROPY_PATH)
        print(f"[{name}] MicroPython version: {version}")

        src_dir = port_root / "src"
        modules_dir = src_dir / "codal_port" / "modules"
        sync_addons(modules_dir, name, cfg)

        try:
            c_ext_arg = resolve_c_extensions(name, cfg)
        except FileNotFoundError as e:
            print(str(e))
            return False

        make_cmd = " ".join(x for x in ["make -j$(nproc)", c_ext_arg] if x).strip()
        print(f"[{name}] Running: {make_cmd}")
        if not safe_run(make_cmd, cwd=src_dir):
            print(f"[{name}] Build failed")
            return False

        orig = src_dir / f"MICROBIT.{cfg['ext']}"
        if not orig.exists():
            print(f"[{name}] Error: Firmware not found at {orig}")
            return False

        new_name = f"firmware-{name}-micropython-{version}.{cfg['ext']}"
        new_path = src_dir / new_name
        orig.rename(new_path)

        move_firmware(new_path, name, version)

        plain_copy = BUILD_ROOT / f"micropython.{cfg['ext']}"
        shutil.copy2(FIRMWARE_DIR / new_name, plain_copy)
        print(f"[{name}] Plain copy saved to {plain_copy}")

        print(f"[{name}] Build completed successfully")
        return True

    except Exception as e:
        print(f"[{name}] Unexpected error: {e}")
        return False

def log_build(board_name: str, filename: str, version: str):
    FIRMWARE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp:<20} {board_name:<20} {filename:<50} v{version}\n"
    with open(BUILD_LOG, "a") as f:
        f.write(line)

def move_firmware(src: Path, name: str, version: str, is_merged: bool = False,
                  bootloader_bin: Path | None = None, partition_bin: Path | None = None):
    FIRMWARE_DIR.mkdir(parents=True, exist_ok=True)
    dst = FIRMWARE_DIR / src.name
    if dst.exists():
        dst.unlink()
    src.rename(dst)
    print(f"[{name}] Firmware saved to {dst}")
    if is_merged:
        print(f"[{name}] Merged image — flash with: esptool write-flash 0x0 {dst.name}")
    elif bootloader_bin and partition_bin:
        bl_name = f"bootloader-{name}-micropython-{version}.bin"
        pt_name = f"partition-table-{name}-micropython-{version}.bin"
        bl_dst = FIRMWARE_DIR / bl_name
        pt_dst = FIRMWARE_DIR / pt_name
        shutil.copy2(bootloader_bin, bl_dst)
        shutil.copy2(partition_bin, pt_dst)
        print(f"[{name}] Bootloader saved to {bl_dst}")
        print(f"[{name}] Partition table saved to {pt_dst}")
        print(f"[{name}] Non-merged image — flash with:")
        print(f"[{name}]   esptool write-flash 0x0 {bl_name} 0x8000 {pt_name} 0x10000 {dst.name}")
    log_build(name, dst.name, version)

def _infer_board_token(make_args: str, fallback_variant: str | None = None) -> str | None:
    board = None
    variant = None
    if make_args:
        for t in make_args.split():
            if t.startswith("BOARD="):
                board = t.split("=", 1)[1]
            elif t.startswith("BOARD_VARIANT="):
                variant = t.split("=", 1)[1]
    token = board
    if token and variant:
        token = f"{token}-{variant}"
    if not token and fallback_variant:
        token = fallback_variant
    return token

# -----------------------------
# Build logic
# -----------------------------

def build_board(name: str, cfg: dict) -> bool:
    """Build a single board with comprehensive error handling."""
    if cfg.get("build_system") == "codal":
        return build_codal_board(name, cfg)

    print(f"\n=== Building {name} ===")

    try:
        # Repo & version
        repo_path = ensure_repo(name, cfg)
        version = get_micropython_version(repo_path)
        print(f"[{name}] MicroPython version: {version}")

        # Port & build folders
        port_dir = repo_path / f"ports/{cfg['port']}"
        if not port_dir.exists():
            print(f"[{name}] Error: Port directory {port_dir} not found")
            return False
        
        make_args = cfg.get("make_args", "").strip()
        board_token = _infer_board_token(make_args, None)

        # Clean build directories
        _clean_build_dirs(port_dir, cfg['port'], board_token)
        
        # Create build directory
        build_dir = _get_build_dir(port_dir, cfg['port'], board_token)
        build_dir.mkdir(parents=True, exist_ok=True)

        # Addons
        modules_dir = port_dir / "modules"
        sync_addons(modules_dir, name, cfg)

        # Optional C extensions
        try:
            c_ext_arg = resolve_c_extensions(name, cfg)
        except FileNotFoundError as e:
            print(str(e))
            return False

        # Build command
        make_cmd = " ".join(x for x in ["make -j$(nproc)", make_args, c_ext_arg] if x).strip()
        print(f"[{name}] Running: {make_cmd}")

        # Execute build
        if cfg["port"] == "esp32":
            # ESP32 specific handling - use standard MicroPython make system with ESP-IDF sourcing
            print(f"[{name}] Using standard MicroPython make system with ESP-IDF...")

            # IDF_TOOLS_PATH must be exported before sourcing export.sh so the
            # toolchains under BUILD_ROOT/tools are found rather than ~/.espressif.
            idf_env_prefix = f"export IDF_TOOLS_PATH={IDF_TOOLS_ROOT} && "
            full_make = make_cmd if not c_ext_arg else f"make -j$(nproc) {make_args} {c_ext_arg}"
            make_cmd_with_idf = f"bash -c '{idf_env_prefix}source {IDF_ROOT}/export.sh && {full_make}'"

            print(f"[{name}] Running: {make_cmd_with_idf}")
            if not safe_run(make_cmd_with_idf, cwd=port_dir):
                print(f"[{name}] ESP32 build failed")
                return False
        else:
            # Other ports use standard make
            if not safe_run(make_cmd, cwd=port_dir):
                print(f"[{name}] Build failed")
                return False

        # Find and move firmware
        orig, is_merged = _find_firmware_path(port_dir, cfg["ext"], cfg['port'], board_token)
        if not orig:
            print(f"[{name}] Error: Firmware not found in {_get_build_dir(port_dir, cfg['port'], board_token)}")
            return False

        new_name = f"firmware-{name}-micropython-{version}.{cfg['ext']}"
        new_path = port_dir / new_name
        orig.rename(new_path)

        bootloader_bin = None
        partition_bin = None
        if not is_merged and cfg['port'] == 'esp32':
            build_dir = _get_build_dir(port_dir, cfg['port'], board_token)
            bl = build_dir / "bootloader" / "bootloader.bin"
            pt = build_dir / "partition_table" / "partition-table.bin"
            if bl.exists() and pt.exists():
                bootloader_bin = bl
                partition_bin = pt

        move_firmware(new_path, name, version, is_merged=is_merged,
                      bootloader_bin=bootloader_bin, partition_bin=partition_bin)
        
        print(f"[{name}] Build completed successfully")
        return True
        
    except Exception as e:
        print(f"[{name}] Unexpected error: {e}")
        return False

def tail_log(n=5):
    if not BUILD_LOG.exists():
        return
    print("\n=== Recent builds ===")
    with open(BUILD_LOG, "r") as f:
        lines = f.readlines()
        for line in lines[-n:]:
            print(line.rstrip())

def main():
    if not BOARDS_TOML.exists():
        print(f"Error: {BOARDS_TOML} not found")
        sys.exit(1)

    # Validate build environment before proceeding
    validate_build_environment()

    with open(BOARDS_TOML, "rb") as f:
        boards = tomllib.load(f)

    print("=== MicroPython Custom Image Builder ===")

    choice = sys.argv[1].lower() if len(sys.argv) > 1 else None

    if choice == "list":
        print("Available boards:")
        for key in boards.keys():
            print(f" - {key}")
        sys.exit(0)

    if not choice:
        available = ', '.join(sorted(boards.keys()))
        while True:
            choice = input(f"Enter board name ({available}, or 'all'): ").strip().lower()
            if choice in boards or choice == 'all':
                break
            print(f"Invalid choice '{choice}'. Please try again.")

    if choice == "all":
        FIRMWARE_DIR.mkdir(parents=True, exist_ok=True)
        # keep build.log; remove other artifacts
        for f in FIRMWARE_DIR.iterdir():
            if f.name != "build.log":
                f.unlink()
        
        # Track build results
        success_count = 0
        total_count = len(boards)
        failed_boards = []
        
        for name, cfg in boards.items():
            if build_board(name, cfg):
                success_count += 1
            else:
                failed_boards.append(name)
        
        print(f"\n=== Build Summary ===")
        print(f"Successful: {success_count}/{total_count}")
        if failed_boards:
            print(f"Failed: {', '.join(failed_boards)}")
        
    elif choice in boards:
        if not build_board(choice, boards[choice]):
            print(f"\nBuild failed for {choice}")
            sys.exit(1)
    else:
        print(f"Unknown board: {choice}")
        sys.exit(1)

    print("\n=== Build process complete ===")
    tail_log(5)

if __name__ == "__main__":
    main()