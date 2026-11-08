# v1 - MicroPython Firmware Builder

Single-script build system for custom MicroPython firmware across four
boards: a CYD ESP32 with touch display, micro:bit V2, ESP32-S3 Zero, and an
ESP32-S3 DevKit (N8R16). One board registry (`boards.toml`), one entry
point (`mpy_build.py`), consistent output naming, frozen Python modules
baked into the image.

```bash
python3 mpy_build.py list          # show registered boards
python3 mpy_build.py cyd           # build one board
python3 mpy_build.py all           # build all boards (ESP32-family)
```

Output lands in `firmware/`, named `<artifact>-<board>-micropython-<mp-version>.bin|hex`.
A running build log is appended to `firmware/build.log`.

## Provenance and recovery status

Recovered verbatim from the dolly bootstrap drive (`/mnt/dolly/mpy-tooling/`,
files last modified 2026-07-25) after the machine rebuild, and committed
here as v1. Included:

- `mpy_build.py` - the build script (Python 3.11+, stdlib only)
- `mpy_build_spec.md` - the full build-system specification; the
  authoritative reference for every mechanism described below
- `boards.toml` - board registry
- `esp_idf_shell`, `mpy-build.code-workspace`
- `addons_specific/` - eight frozen-module drivers for the CYD build
- `firmware/` - ten built images plus eight build logs (evidence of working
  builds; artifacts are committed because the project itself is about
  reproducible builds)

Not recovered (too large to back up; must be re-created on a fresh
machine): the MicroPython source checkout, ESP-IDF v5.5.2 + toolchains,
and `repos/` (the micro:bit v2 port). Section 11 of `mpy_build_spec.md`
has the complete setup recipe.

## Boards

| Board | Target | Output | Frozen addons |
|---|---|---|---|
| `cyd` | ESP32, `ESP32_GENERIC` (4MB) | 3-flash-part components (`.bin`) | 8 drivers (see below) |
| `microbit` | micro:bit V2, nRF52833 (CODAL) | `firmware-microbit-*.hex` | none |
| `s3zero` | ESP32-S3, `ESP32_GENERIC_S3` | `firmware-s3zero-*.bin` | none |
| `esp32s3_devkit` | ESP32-S3-WROOM-1-N8R16, `SPIRAM_OCT_N8R16` (8MB flash, 8MB octal PSRAM) | merged `firmware-esp32s3_devkit-*.bin` | none |

`s3zero` and the `paj7620` cyd addon exist in `boards.toml` but not in
`mpy_build_spec.md` (Section 4); the registry is newer than the spec's
excerpt.

## Frozen modules

`addons/` is copied into every build; `addons_specific/` only into boards
that list the filename in `boards.toml`. The CYD addons in
`addons_specific/` include two locally-modified drivers whose stock
upstream differs - the source of truth was `~/embed/cyd/lib/` on the
build machine:

- `ili9341.py` - `_write_command` reuses a pre-allocated `bytearray`
  (SPI buffer optimisation)
- `xpt2046.py` - `sleep()` calls removed from the touch ISR; debounce is
  the caller's responsibility

Do not replace these with upstream versions.

## Reconstruction hazards (applied to the source tree, not to this repo)

Three changes lived inside the (unrecovered) MicroPython port tree and are
known only from `mpy_build_spec.md`. After re-setting up, re-apply them:

1. **S3 N8R16 variant** (Section 7): add
   `ports/esp32/boards/sdkconfig.flash_8MiB` and
   `ports/esp32/boards/ESP32_GENERIC_S3/mpconfigvariant_SPIRAM_OCT_N8R16.cmake`
   (full contents in the spec).
2. **micro:bit port** (Section 10): the CODAL port is cloned into
   `repos/microbit/`; its `lib/micropython` submodule must be replaced
   with a symlink to the shared mainline checkout, and
   `repos/microbit/src/codal_port/manifest.py` changed to
   `freeze("modules", opt=3)` so the addons mechanism works. `sync_addons()`
   copies files in but never removes stale ones - delete dropped addons by
   hand before rebuilding.
3. **esptool** comes from the IDF venv, not the system PATH:
   `tools/python_env/idf5.5_py3.13_env/bin/python3 -m esptool ...`

## Firmware inventory (committed output)

Built with MicroPython `v1.29.0-preview-289-gbb9b8fc69`:

| Artifact | Built | Source log |
|---|---|---|
| `firmware-s3zero-...-preview-289-...bin` | 2026-05-27 | `build-s3.log` |
| `firmware-esp32s3_devkit-...-preview-289-...bin` | 2026-05-27 | `build-s3-n8r16.log` |
| `firmware-cyd-...-preview-289-...bin` | 2026-05-27 | `build-cyd-v2.log` |
| `bootloader-` / `partition-table-s3zero-...-289-...bin` | 2026-05(-07) | per-board logs |
| `firmware-microbit-...-hex` + `micropython.hex` | 2026-07-25 | `build.log` |
| s3zero 626-preview set (2nd MicroPython preview) | 2026-07 | `build.log` |

## Flashing quick reference

Full commands in `mpy_build_spec.md` Section 8. Summary:

- **ESP32 (cyd)**: three-component flash at `0x1000` / `0x8000` / `0x10000`
  (bootloader, partition table, app). `firmware.bin` in the ESP32 build
  dir is the *bootloader* - do not flash it as firmware.
- **ESP32-S3 N8R16**: single merged image at `0x0`; device must be in
  bootloader mode first (hold BOOT, tap RESET).
- **micro:bit**: copy the hex to the `MICROBIT` USB drive, or use `uflash`.

## History

This generation descends from two earlier versions maintained on z50
(2025-09, 2025-11, on the bootstrap drive at `/mnt/z50/bin/`, not in this
repo). The dolly generation (May 2026 - July 2026) added the board
registry, the CODAL micro:bit path, and the S3 N8R16 variant.

v2 will hold the next iteration of the build system.
