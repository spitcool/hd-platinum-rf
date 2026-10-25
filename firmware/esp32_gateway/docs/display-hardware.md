<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# CoreS3 SE touchscreen and shared SPI ownership

The CoreS3 and CoreS3 SE LCD uses GPIO36/37 for clock/data and GPIO35 for D/C.
The Base LAN W5500 uses those same clock/data pins and **GPIO35 as MISO**.
GPIO35 must never be an ESP32 output while a selected W5500 drives MISO.
The radio remains on its independent HSPI controller and GPIO6/5/8.

`gateway_display/display_bus` implements an explicit main-task ownership
transition, using the pinned M5GFX 0.2.8 and Arduino-ESP32 2.0.17 APIs. Rendering
and Ethernet must remain in the same main task; no background task, interrupt,
callback or display timer may access either peripheral outside this boundary.
Touch sampling uses the CoreS3 I2C touch controller and does not require LCD
SPI ownership. Radio jobs run separately and do not share this SPI controller.

## Lifecycle

After `M5.begin()` initializes the physical panel, call `displayBus.begin(wired)`.
For Wi-Fi, LCD bus ownership stays with M5GFX. For wired networking, startup
releases the display bus and initializes Arduino's global SPI on GPIO36/35/37.
The panel retains its contents and power while its bus is released.

Each dirty display frame in wired mode does the following:

1. Deselect W5500 CS9, LCD CS3 and SD CS4; allow one microsecond for the selected
   peripheral's MISO to release. Stop Arduino SPI completely.
2. Initialize the existing M5GFX **bus object**, without reinitializing or
   resetting the panel. Restore GPIO35 to output after bus initialization.
3. Draw the frame while no Ethernet operation runs. Finish the display
   transaction and wait for DMA completion.
4. Deselect devices again. Release the M5GFX bus, including its IDF device/DMA
   allocation and Arduino SPI handle. Set GPIO35 to input.
5. Reinitialize Arduino SPI with the Ethernet pin map. Only then resume
   network calls.

Changing only chip selects or GPIO35 direction is insufficient: both libraries
program the same FSPI peripheral. Keeping both bus implementations initialized
can retain incompatible cached state and DMA resources. The handoff releases
one implementation before starting the other. Render only when the UI changes;
do not continually allocate and free the bus for identical frames.

The explicit GPIO35 output restore is necessary for repeated frames. M5GFX's
CoreS3 configuration uses `pin_miso=pin_dc=35`. SPI initialization configures it
as input, while a cached APB clock may skip M5GFX's later D/C mode restoration.
Releasing the bus and reattaching MISO restores the input role for Ethernet.

The adapter rejects other automatically detected board types. A failed display
bus initialization disables further rendering and attempts to restore Ethernet
ownership. An Ethernet initialization failure leaves the shared pin as input
and reports the bus unavailable. Callers must respect `networkReady()` before
network access. The pinned M5GFX lower-level SPI helper does not propagate every
IDF allocation error, so an API success is not a complete hardware health test.

All `M5.Display` calls—including brightness, wake/sleep, rotation, drawing and
sprite pushes—belong inside `acquireDisplay()` / `releaseDisplay()`. Use balanced
`startWrite()` / `endWrite()` calls if explicitly opening a drawing transaction.
Do not add a background screen refresh or call `SPI.begin()` independently
while the screen owns this bus. Keep the SD socket empty and SD CS inactive.

## Evidence and qualification

The implementation was checked against these exact upstream sources, installed
by the project's pinned dependencies:

- [M5GFX CoreS3/SE configuration](https://github.com/m5stack/M5GFX/blob/cc613d65f13a3a80021ef264a654e9e6a2419d8a/src/M5GFX.cpp):
  board detection, pin assignment, shared D/C/MISO and panel setup.
- [M5GFX SPI bus](https://github.com/m5stack/M5GFX/blob/cc613d65f13a3a80021ef264a654e9e6a2419d8a/src/lgfx/v1/platforms/esp32/Bus_SPI.cpp)
  and [platform SPI helpers](https://github.com/m5stack/M5GFX/blob/cc613d65f13a3a80021ef264a654e9e6a2419d8a/src/lgfx/v1/platforms/esp32/common.cpp):
  peripheral initialization, cached D/C handling and full release.
- [Arduino-ESP32 2.0.17 SPI](https://github.com/espressif/arduino-esp32/blob/2.0.17/libraries/SPI/src/SPI.cpp):
  `begin`, `end`, pin attachment and transaction behavior.

The native fake-peripheral test validates ordering, no simultaneous owners,
GPIO direction restoration, 1,000 repeated handoffs, Wi-Fi ownership, and failure
fallback. It does not validate electrical timing, DMA-resource stability on the
ESP32, touch calibration, panel appearance or network throughput.

Before calling the wired touchscreen build qualified, use the actual CoreS3 SE
and Base LAN assembly to verify:

- With a logic analyzer, W5500 CS is inactive before GPIO35 becomes an output,
  and GPIO35 is input before W5500 CS becomes active. Check reset and reconnect.
- Redraw repeatedly while serving TCP 522, HTTP page/inventory responses and UDP
  discovery. Confirm complete replies, no corrupted LCD frames and stable heap
  and DMA resources over an extended run.
- Check both portrait/landscape touch mapping as configured by the renderer,
  all touch target boundaries, held presses, and page transitions.
- Check that a slow network client, DHCP renewal and a running RF job do not
  result in repeated touch commands or loss of bus ownership.

These physical checks remain outstanding. The carrier's
[firmware contract](../../../hardware/design/firmware-contract.md) remains the
hardware qualification authority; the new software does not change its pin map.
