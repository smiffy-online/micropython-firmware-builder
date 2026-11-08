# MicroPython Custom Firmware Build System (`mpy_build.py`)

## 1. Purpose

`mpy_build.py` builds custom MicroPython firmware images for multiple
microcontroller families. It handles ESP-IDF environment setup, frozen
module inclusion, and consistent firmware naming automatically.

```bash
python3 mpy_build.py list          # show registered boards
python3 mpy_build.py cyd           # build one board
python3 mpy_build.py all           # build all boards
```

Output lands in `~/mpy-build/firmware/`. A build log is kept at
`~/mpy-build/firmware/build.log`.

---

## 2. Directory Layout

Everything lives under `~/mpy-build/` — no scattered paths.

```
~/mpy-build/
├── mpy_build.py            # build script
├── boards.toml             # board registry
├── esp_idf_shell           # interactive ESP-IDF shell helper
├── micropython/            # MicroPython source (mainline)
├── esp-idf/                # ESP-IDF v5.5.2
├── tools/                  # ESP-IDF toolchains (IDF_TOOLS_PATH)
│   └── python_env/
│       └── idf5.5_py3.13_env/   # IDF-managed Python venv
├── addons/                 # .py modules frozen into ALL boards
├── addons_specific/        # .py modules frozen per-board (listed in boards.toml)
├── c_extensions/           # USER_C_MODULES directories
├── repos/                  # custom per-board MicroPython repos (if any)
└── firmware/               # build output
    └── build.log
```

The script anchors itself with:
```python
BUILD_ROOT = Path(__file__).resolve().parent
```
All paths are computed relative to this. Nothing touches `~/.espressif`
or `~/esp`.

---

## 3. ESP-IDF Version

**v5.5.2** — MicroPython's recommended version for v1.29.x.

The repo lives at `~/mpy-build/esp-idf/`. Toolchains are installed under
`~/mpy-build/tools/` (not `~/.espressif`) by running:

```bash
cd ~/mpy-build/esp-idf
IDF_TOOLS_PATH=~/mpy-build/tools ./install.sh esp32,esp32s3
```

`IDF_TOOLS_PATH` must be exported **before** sourcing `export.sh`.
The build script does this automatically:

```python
idf_env_prefix = f"export IDF_TOOLS_PATH={IDF_TOOLS_ROOT} && "
make_cmd_with_idf = f"bash -c '{idf_env_prefix}source {IDF_ROOT}/export.sh && {make_cmd}'"
```

---

## 4. `boards.toml` — Current Registry

```toml
[cyd]
port = "esp32"
ext = "bin"
make_args = "BOARD=ESP32_GENERIC"
addons = ["ili9341.py", "xpt2046.py", "ds3231.py", "bmp280.py",
          "ahtx0.py", "veml7700.py", "xglcd_font.py"]
c_extensions = ""

[microbit]
port = "nrf"
ext = "hex"
make_args = ""
addons = []
c_extensions = "microbit_ext"

[esp32s3_devkit]
port = "esp32"
ext = "bin"
make_args = "BOARD=ESP32_GENERIC_S3 BOARD_VARIANT=SPIRAM_OCT_N8R16"
addons = []
c_extensions = ""
```

**Notes:**
- `microbit` has `c_extensions = "microbit_ext"` which does not exist.
  This intentionally blocks accidental builds until the micro:bit
  implementation is complete. See section 8.
- `cyd` addons are all in `addons_specific/`. The `ili9341.py` and
  `xpt2046.py` are locally-modified versions (see section 6).

---

## 5. Frozen Modules (Addons)

Files listed in `addons` for a board are copied to
`micropython/ports/<port>/modules/` before the build. MicroPython
compiles them to bytecode and embeds them in the firmware as frozen
modules.

Frozen modules:
- Load faster than filesystem `.py` files (no compile step at import)
- Can be removed from the device filesystem to save space
- Are read-only (to edit, rebuild firmware)

**Two addon directories:**
- `addons/` — copied into every board's build
- `addons_specific/` — copied only for boards that list the filename

---

## 6. CYD-Specific Modified Drivers

The `addons_specific/` versions of these files differ from stock:

**`ili9341.py`** — SPI buffer optimisation: `_write_command` reuses a
pre-allocated `bytearray` instead of allocating on every call.

**`xpt2046.py`** — ISR fix: both `sleep(.1)` calls removed from
`int_press()`. The ISR now returns immediately; debounce is the caller's
responsibility. The `sleep(.05)` at line 86 is inside `raw_touch()`
(not the ISR) and was not changed.

The source of truth for these is `~/embed/cyd/lib/`. When updating, copy
from there — do not use the upstream versions.

---

## 7. ESP32-S3 N8R16 Variant (`SPIRAM_OCT_N8R16`)

The `esp32s3_devkit` board targets an **ESP32-S3-WROOM-1-N8R16** (8MB
flash, 8MB octal PSRAM). Two files were added to the MicroPython source
tree to support this:

**`micropython/ports/esp32/boards/sdkconfig.flash_8MiB`**
```
CONFIG_ESPTOOLPY_FLASHSIZE_8MB=y
CONFIG_ESPTOOLPY_FLASHSIZE="8MB"
CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions-4MiBplus.csv"
```
Uses the non-OTA single-factory partition layout. MicroPython does not
use OTA, and this gives the maximum filesystem space (~6MB on 8MB flash).

**`micropython/ports/esp32/boards/ESP32_GENERIC_S3/mpconfigvariant_SPIRAM_OCT_N8R16.cmake`**
```cmake
set(SDKCONFIG_DEFAULTS
    ${SDKCONFIG_DEFAULTS}
    boards/sdkconfig.240mhz
    boards/sdkconfig.spiram_oct
    boards/sdkconfig.flash_8MiB
)
list(APPEND MICROPY_DEF_BOARD
    MICROPY_HW_BOARD_NAME="ESP32-S3-WROOM-1 N8R16"
)
```

---

## 8. Flashing

### ESP32 (CYD, `ESP32_GENERIC`)

Produces separate binaries. Flash with three components:

```bash
esptool --chip esp32 -p /dev/ttyUSB0 -b 460800 \
  --before default_reset --after hard_reset write_flash \
  --flash_mode dio --flash_freq 40m --flash_size 4MB \
  0x1000  build-ESP32_GENERIC/bootloader/bootloader.bin \
  0x8000  build-ESP32_GENERIC/partition_table/partition-table.bin \
  0x10000 build-ESP32_GENERIC/micropython.bin
```

The saved `firmware-cyd-*.bin` is `micropython.bin` (app only, 0x10000).
The build dir is `micropython/ports/esp32/build-ESP32_GENERIC/`.

**Note:** `firmware.bin` also appears in the ESP32 build dir but is the
bootloader binary — do not use it as the firmware.

### ESP32-S3 N8R16 (`SPIRAM_OCT_N8R16`)

Produces a **merged image** (`firmware.bin`): bootloader + partition table
+ app concatenated at their flash addresses, starting at 0x0. Flash with:

```bash
esptool --chip esp32s3 -p /dev/ttyACM0 -b 460800 \
  --before default_reset --after hard_reset write_flash \
  --flash_mode dio --flash_size 8MB --flash_freq 80m \
  0x0 firmware.bin
```

The device must be in bootloader mode (hold BOOT, tap RESET, release
BOOT) before running esptool.

The `esptool` used should be from the IDF venv:
```bash
~/mpy-build/tools/python_env/idf5.5_py3.13_env/bin/python3 -m esptool ...
```

---

## 9. `mpy_build.py` Key Design Notes

**`_infer_board_token`** — extracts the build directory suffix from
`make_args`. Handles `BOARD_VARIANT=` to produce the `BOARD-VARIANT`
token (e.g. `ESP32_GENERIC_S3-SPIRAM_OCT_N8R16`).

**`_find_firmware_path`** — for the `esp32` port:
1. Tries `micropython.bin` first (non-SPIRAM app binary, not merged)
2. Falls back to `firmware.bin` only if offset 0x10000 contains `0xe9`
   (valid ESP image magic confirming it's a merged image)

**`make_esp_env`** — constructs the build environment without sourcing
`export.sh`. Sets `IDF_PATH`, `IDF_TOOLS_PATH`, `PATH` (with tool bins),
and `PYTHON`. Used for validation; the actual build sources `export.sh`
via bash subprocess.

---

## 10. Micro:Bit — Status: Working (V2, full hardware support)

Board confirmed V2 (nRF52833). Built successfully 2026-07-25 (state thread
#346), then integrated into `mpy_build.py`/`boards.toml` the same day so it
builds the same way as the other boards -- one script, no per-board
standalone scripts.

**Approach:** mainline MicroPython's own `ports/nrf/boards/MICROBIT/` only
targets v1 (nRF51822) and is missing button/accelerometer/compass/radio --
inadequate for V2. Instead of writing those drivers from scratch against
nrfx, `micropython-microbit-v2` (the CODAL-based port maintained by the
micro:bit Foundation) is vendored and rebased onto the current mainline
core:

- Port lives at `repos/microbit/` (cloned from
  `microbit-foundation/micropython-microbit-v2` -- directory named after the
  `boards.toml` key, same convention as other repo-based boards).
- Its `lib/codal` submodule is initialised normally (pinned commit as
  declared by the upstream project; CODAL's own build tool fetches
  `codal-microbit-v2` per `src/codal_app/codal.json`, independently
  versioned and actively maintained -- this is the actual hardware driver
  stack: display, buttons, accelerometer, compass, radio, speaker/audio,
  BLE).
- Its `lib/micropython` submodule directory is **replaced with a symlink**
  to the shared `~/mpy-build/micropython` checkout (the same one `cyd`,
  `esp32s3_devkit`, and `s3zero` build against), so the micro:bit build
  always tracks whatever mainline commit that checkout is on, rather than
  the upstream project's separately-pinned core version.
- `lib/sam` is not a submodule -- it's vendored SAM speech-synth source
  already present in the checkout, used by `modspeech.c`.
- `src/codal_port/manifest.py` was changed from
  `freeze("modules", "neopixel.py", opt=3)` (upstream, names one file) to
  `freeze("modules", opt=3)` (wildcards the whole directory) -- this matches
  mainline's own `ports/esp32/boards/manifest.py` convention
  (`freeze("$(PORT_DIR)/modules")`) and is what makes the `addons`/
  `addons_specific` mechanism below work identically to the ESP32 boards.

At the time of the initial build, upstream's pinned core was MicroPython
v1.23.0 (2024-05-31) vs. the shared checkout's `v1.29.0-preview-289-gbb9b8fc69`
-- about 14 months of drift, not the 5+ years originally assumed. The build
succeeded with **no source changes required** beyond the manifest.py wildcard
above: the object/type declaration API the port's hardware modules use
(`MP_DEFINE_CONST_OBJ_TYPE`) is unchanged across that gap. If a future
rebuild against a newer mainline commit does hit breakage, fix it in the
port's glue files (`repos/microbit/src/codal_port/mpconfigport.h`,
`mphalport.c/.h`, `main.c`, `qstrdefsport.h`, `manifest.py`, `microbitfs.c`)
-- not in the hardware-implementing files (`microbit_button.c`,
`microbit_accelerometer.c`, `microbit_compass.c`, `microbit_display.c`,
`modradio.c`, `microbit_speaker.c`, `modaudio.c`, `modmusic.c`,
`microbit_image.c`, etc.) unless an error specifically traces there.

**`boards.toml` entry:**
```toml
[microbit]
build_system = "codal"
repo = "https://github.com/microbit-foundation/micropython-microbit-v2.git"
ext = "hex"
addons = []
c_extensions = ""
```

**How `build_system = "codal"` works in `mpy_build.py`** (for whenever
another CODAL-based, or otherwise non-ESP-IDF, board shows up):
- `setup_codal_repo()` -- clones `repo` into `repos/<name>/` if missing,
  inits `lib/codal` (but deliberately **not** `git submodule update --init
  --recursive` on the whole repo -- that would replace the `lib/micropython`
  symlink with a real submodule checkout pinned to upstream's declared,
  older core, undoing the rebase on every build), manages the symlink, and
  builds `mpy-cross`.
- `resolve_c_extensions()` -- shared with the ESP32 path; resolves
  `c_extensions = "<name>"` to `USER_C_MODULES=c_extensions/<name>`. Works
  here because `codal_port/Makefile` includes mainline's own `py/py.mk` /
  `py/mkrules.mk` (the classic make-based module system, same as
  unix/stm32/samd), which natively scans
  `$(USER_C_MODULES)/*/micropython.mk` -- a **different** mechanism from
  ESP32/rp2's CMake-based `micropython.cmake`, so a C extension meant to
  work on both `cyd`-style and `microbit`-style boards needs both a
  `micropython.mk` and a `micropython.cmake` in its `c_extensions/<name>/`
  directory (the standard convention upstream MicroPython's own cmodule
  template uses for exactly this reason).
- `addons`/`addons_specific` -- reuses the existing `sync_addons()` unchanged,
  pointed at `repos/microbit/src/codal_port/modules/`. Verified end-to-end
  2026-07-25: a test addon dropped in via `addons_specific/` + `boards.toml`
  froze in correctly and was importable over the serial REPL.
- Firmware is always at `src/MICROBIT.hex` (fixed name, no board-token build
  directory -- baked into the upstream Makefile, not derived from the
  `boards.toml` board name).
- Note: `sync_addons()` only *copies* files in -- it doesn't remove addons
  that were later dropped from `boards.toml`/`addons_specific/`. If an addon
  is removed from config, also delete its stale copy from
  `repos/microbit/src/codal_port/modules/` before rebuilding (this is a
  pre-existing property of `sync_addons()`, not new here).

**Build:** `python mpy_build.py microbit` from `~/mpy-build/`. Output:
`firmware/firmware-microbit-micropython-<version>.hex` and a plain copy at
`micropython.hex`.

**Flash:** copy the hex onto the `MICROBIT` USB drive, or use `uflash`
(installed under `/workspaces/smiffy-venv`).

---

## 11. Setup — Fresh Machine

```bash
# System packages (Debian 12 / Ubuntu 24.04)
sudo apt install -y git build-essential cmake ninja-build flex bison \
  gperf libffi-dev libssl-dev dfu-util libusb-1.0-0 python3-venv \
  gcc-arm-none-eabi binutils-arm-none-eabi  # for nrf/micro:bit

# Create working directory
mkdir -p ~/mpy-build
cd ~/mpy-build

# Clone MicroPython
git clone https://github.com/micropython/micropython.git
cd micropython && git submodule update --init --recursive && cd ..

# Clone ESP-IDF at the correct version
git clone -b v5.5.2 --recursive https://github.com/espressif/esp-idf.git esp-idf
# Note: openthread nested submodule may fail — this is benign for ESP32/S3 targets

# Install toolchains under this directory (not ~/.espressif)
cd esp-idf
IDF_TOOLS_PATH=~/mpy-build/tools ./install.sh esp32,esp32s3
cd ..

# Create required directories
mkdir -p addons addons_specific c_extensions firmware repos
```

---

## 12. Future Extensions

- Micro:Bit v2 C module implementation (buttons, accelerometer, compass, radio)
- PAJ7620 gesture sensor integration for CYD (pending hardware validation)
- Additional board support as needed
