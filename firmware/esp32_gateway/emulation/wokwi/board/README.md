<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->

# CoreS3 SE custom board

This directory contains an original schematic-style board drawing and board
definition for Wokwi's website custom-board loader. `board.json`, `board.svg`
and the example `diagram.json` are original work under GPL-2.0-or-later. They
do not include the upstream CoreS3 artwork.

The pin map uses the CoreS3 SE wiring and the register/pin assignments in the
gateway's pinned M5GFX/M5Unified dependencies. Wokwi's
[CoreS3 board definition](https://github.com/wokwi/wokwi-boards/blob/962b19d/boards/m5stack-core-s3/board.json),
authored by Ariella Eliassaf, provided a reference for Wokwi's board/display
schema. Its published board bundle revision `962b19d` declares FT6336 but omits
the touch bus and interrupt wiring. No MIT license was found for that upstream
repository, so no license is inferred or assigned to its assets here.

1. Open Wokwi's [custom firmware template](https://wokwi.com/projects/305457271083631168)
   in the website editor. Click the code editor, press **F1**, choose
   **Load custom board file...**, and select this directory. This is the
   [official custom-board workflow](https://github.com/wokwi/wokwi-boards#testing-a-custom-board).
2. Add a **Custom Chip** named `cores3-power` using the diagram's **+** menu.
   Replace its generated C and JSON with the files in `../chips/`. The website
   compiles the C chip source; the firmware itself remains the locally compiled
   ESP32 binary. See the [custom chip instructions](https://docs.wokwi.com/chips-api/getting-started).
3. Replace the website's `diagram.json` with the example in this directory.
4. Press **F1** and select **Upload Firmware and Start Simulation...**. Choose
   the full merged ESP32-S3 image containing the project's bootloader,
   partition table and application. Wokwi recommends a merged image for
   [custom firmware](https://docs.wokwi.com/guides/esp32#custom-application-firmware).

The loader has not yet been verified with this board. VS Code 4.1.0's project
loader accepts custom WASM chips but exposes no custom board JSON/SVG loader;
adding `wokwi-custom-board` to a VS Code diagram alone does not install this
definition. Keep using the supplied full firmware image for comparisons.

| Board pin | Target | External connection |
| --- | --- | --- |
| G12 | GPIO12 and FT6336 SDA | Power chip SDA |
| G11 | GPIO11 and FT6336 SCL | Power chip SCL |
| AW_INTN | GPIO21 | Power chip AW_INTN |
| TOUCH_INT | FT6336 INT | Power chip TOUCH_INT |
| TOUCH_RESET | FT6336 RST | Power chip TOUCH_RESET |
| LCD_RESET | ILI9342C RST | Power chip LCD_RESET |
| BACKLIGHT | ILI9342C LED | Power chip BACKLIGHT |

The touch interrupt reaches the processor through the AW9523B model's P1_2
input and interrupt latch. It is not tied directly to GPIO21. The power chip's
BUS_POWER and USB_POWER outputs are available for instruments or additional
peripherals; they are logical enable signals, not modeled 5 V analog supplies.

SPI uses GPIO36 SCK, GPIO3 CS, GPIO35 D/C and GPIO37 data. The definition joins
the LCD model's MOSI and MISO terminals at GPIO37 for the firmware's half-duplex
`spi_3wire` reads. This electrical adaptation still needs a live check for the
built-in controller's output-enable behavior. It does not change the firmware
driver or substitute an ID response.

The memory attributes select 16 MB flash and 8 MB quad PSRAM. GPIO6 maps to
GPIO6; the upstream definition's GPIO36 alias is not used. Camera and IMU
devices are absent, as on the CoreS3 SE.

JSON, XML and connection targets can be checked locally. Successful loading,
SPI readback and the built-in FT6336 register behavior require a live Wokwi
run; these files are not evidence of a successful firmware boot.

The pinned driver requires:

- AXP2101 at `0x34`, identity register `0x03 = 0x4a`, and AW9523B at `0x58`,
  identity register `0x10 = 0x23`. The custom power model tests cover these.
- LCD command `0x04`, one dummy clock, then a 32-bit read whose low byte is
  `0xe3`. Later panel detection probes `0xdd`, `0xcb` and `0xd3`.
- FT6336 at `0x38`: writing work-mode register `0x00 = 0`, reading six bytes
  starting at `0xa3`, a nonzero vendor byte at `0xa8`, and writing `0xa4 = 0`.
- Press and release both reaching GPIO21 through the AW latch, with reads of
  AW input register `0x01` acknowledging the touch port interrupt.

Wokwi's built-in ILI9342C and FT6336 implementations are not supplied in the
public board repository. Their ID responses have not been verified here.
The [ILI9341 documentation](https://docs.wokwi.com/parts/wokwi-ili9341) also
lists reset and backlight as unimplemented for that related model. Exposing
those terminals here does not establish that ILI9342C implements their effects.
