<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

Run this from the repository root on macOS:

```sh
python3 firmware/esp32_gateway/tools/device_simulator.py
```

The launcher builds the ESP32-S3 firmware and opens a native AppKit window.
The window shows the LCD controller's RGB565 framebuffer; mouse input reaches
the emulated FT6336 and AW9523 interrupt circuit. The firmware's M5GFX and
M5Unified drivers, FreeRTOS tasks, command engine and network stack execute
inside the ESP32 instruction emulator. There is no HTML screen renderer or
host implementation of gateway commands in this path.

Choose **Shades** or **Groups**, select a row, then **Open** or **Close**.
**Prev / Next** changes the list page. Six fictional shades in three rooms
are imported through the actual USB console after boot. The local state is
fresh on each process launch; the board's reset retains its current emulated
flash. RF is disabled in this dedicated build.

The same running firmware provides:

| Interface | Local address |
| --- | --- |
| Web interface and HTTP API | `http://127.0.0.1:18080/` |
| Legacy TCP 522 | `127.0.0.1:1523` |
| Framebuffer/input transport for the native window | `127.0.0.1:18079` |

The fictional API token is `wokwi-local-development-token-0001`. It is only
for this local environment. The emulator build never reads your private
`include/gateway_config.h`. Host forwarding passes TCP packets into the
firmware's sockets. API and TCP service switches continue to be handled and
persisted by the firmware.

```sh
curl -H 'Authorization: Bearer wokwi-local-development-token-0001' \
  http://127.0.0.1:18080/api/shades
```

The native window's USB console accepts the existing `status`, `export`,
`grant` and `services` commands. `services 1 1 1` restores both network
interfaces and the web page. Closing the native window or pressing Ctrl-C
in the launcher terminates its emulator process. `--no-build` reuses the
last build, `--build-only` prepares it without opening a window, and
`--no-seed` starts with an empty inventory. `--headless --seconds 10` runs
a bounded firmware boot without the macOS window.

The build uses Python 3.12+, PlatformIO 6.1.18, CMake, a C++17 compiler,
Rust/Cargo and Apple's Swift/AppKit toolchain. On this machine the dependencies
are installed in `.venv` and ignored `tmp` directories. The launcher selects
a working installed macOS SDK and downloads hash-checked emulator/ROM inputs
when needed. It keeps the downloaded source, patched builds, logs and native
application under `tmp/cores3-emulator/`. No physical serial device is opened
and nothing is flashed.

The emulator is pinned to esp32sim commit
`964c26c1a6dac335e849195d2cabc15c713015a3`. Its source archive SHA-256 is
`8fe8bb0ddb0b9c3e6f45ece5339773608f2c5dbb7e94ee24f2d398540aad704a`.
The Espressif ESP32-S3 ROM ELF SHA-256 is
`c0ce0f338d1de1bdc6efbef1591779a2a42c1ab7d759d3c6ae8ae63a7dd34cfd`.
The [retained board model and patch](../emulation/esp32sim/README.md) cover
16 MB flash, 8 MB PSRAM, ILI9342C SPI, FT6336 touch, AXP2101 power registers,
AW9523B GPIO/interrupt behavior, RTC register storage and virtual Wi-Fi.

Actual compiled-firmware checks on 2026-10-25 verified ROM/bootloader startup,
320×240 LCD output, shade and group Open/Close, second-page selection, and
CRC-checked state exports after touch actions. HTTP authentication, repeated
API requests, and fragmented TCP 522 requests on a persistent connection also
passed. The adaptation has board, SPI transport, networking and CLI tests;
the portable firmware has separate ASan/UBSan tests. Emulator timing is not
evidence of real bus timing, analog power behavior or successful RF delivery.

The RF transceiver, W5500 carrier, audio, analog rail dynamics and physical
radio environment are not modeled. This environment exercises the Wi-Fi
firmware and the peripherals used by its screen. Validate those other paths
on hardware. UDP discovery is implemented in the firmware but is not exposed
by the TCP forwarding rules above.

Wokwi remains available through `cores3_wokwi`, [wokwi.toml](../wokwi.toml)
and [diagram.json](../diagram.json). Install/activate the official VS Code
extension, build that environment, and compile the custom power chip:

```sh
env WASI_SDK_PATH="$PWD/tmp/wokwi-wasi-sdk" \
  ./tmp/esp32-tools/wokwi-cli chip compile \
  firmware/esp32_gateway/emulation/wokwi/chips/cores3-power.chip.c \
  -o firmware/esp32_gateway/emulation/wokwi/chips/cores3-power.chip.wasm
PLATFORMIO_CORE_DIR="$PWD/tmp/esp32-platformio" .venv/bin/pio run \
  -d firmware/esp32_gateway -e cores3_wokwi
```

Select that `wokwi.toml` using **Wokwi: Select Config File**, then run
**Wokwi: Start Simulator**. The complete image includes the custom partition
table and application at `0x80000`; loading only `firmware.bin` would use a
different flash layout. Wokwi uses HTTP port 18078, TCP port 1522 and RFC2217
port 4000. `tools/wokwi_serial.py` reads status or imports the native
`sample_inventory` executable's output.

The licensed Wokwi run verified actual firmware boot, Wi-Fi, NVS import and
HTTP API access. Its published CoreS3 board omits the touch I²C/interrupt
wiring and fails this firmware's touchscreen initialization. VS Code 4.1.0
does not expose a custom-board loader. An independently drawn
[experimental corrected board](../emulation/wokwi/board/README.md) is retained
for Wokwi's website loader; its runtime behavior has not been validated.
Use the native launcher above for the working touchscreen environment.
