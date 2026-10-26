<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# M5CoreS3 Platinum gateway

Independent C++17 firmware for the M5CoreS3 / CoreS3 SE ESP32-S3, with Wi-Fi
and W5500 builds and a native touchscreen interface. This is a buildable replacement implementation, **not yet a
qualified full stand-in for the original bridge**. No vendor firmware is
embedded, translated, or executed. The APK and original firmware supplied
protocol evidence only.

The default backend simulates commands. Separate native bench images permit
explicit, time-limited radio experiments; they do not claim hardware qualification.
The CoreS3/NiceRF appliance is unassembled, and no image has been flashed or
tested on that stack. Observed SDR shade responses are separate evidence.

## Implemented

- TCP 522: server-first banner, numbered LF-CR records, streaming request parser,
  keepalive, inventory, room/shade editing, scenes, schedules, position staging
  and release, Sync/Jog requests and bounded cancellation.
- UDP 137: both documented Platinum discovery names and node-status queries.
- HTTP 8077: bearer-authenticated JSON API, shade/room/scene lists, requested
  positions, operation status, and persistent service switches.
- Native 320×240 touchscreen: select a shade or room group and feature, adjust
  a raw value, or use explicitly mapped Open/Close endpoints. Paginated lists
  and status messages use the same grants and RF queue as network requests.
- Embedded responsive web interface: feature-specific raw controls, verified
  rail labels and endpoints, granted Sync/Jog controls, and service settings. The token stays
  in page memory; no CDN, cloud service or browser storage is needed.
- Independent TCP and HTTP switches. Turning off TCP also stops discovery;
  HTTP can remain available. Turning off HTTP closes the API and web interface;
  TCP can remain available. A separate web switch hides the page while retaining
  the API. All switches can be recovered over USB.
- Versioned CRC-protected database in NVS, explicit installation grants,
  persistent sequence allocation before transmission, and one finite RF owner
  shared by TCP, HTTP and scheduled actions.
- An experimental RF2401F20 driver with separate 250 kbps repeater and 2 Mbps
  native routes. The native planner covers primary position, secondary position
  and Jog with finite per-packet channel rotation. Neither route retries
  automatically or claims measured shade position.

The [command coverage matrix](docs/protocol-coverage.md) inventories all **57
original dollar-prefixed dispatcher commands** and identifies the 26 ordinary
app command prefixes implemented here. Remaining work includes repeater tests,
legacy maintenance/update/memory/solar commands, opaque original inventory
records, RF receive/feedback, NiceRF framing/timing qualification, new-identity
enrollment, and original-app qualification on real hardware. Native Sync is
rejected pending a distinct enrollment implementation; tilt and feature 10
remain simulation-only. Secondary position has watched SDR movement results and a native bench
candidate; its NiceRF implementation remains unqualified. LED brightness is
stored as metadata.

## Build and test

From the repository root, use Python 3.10+ for the build tooling:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install platformio==6.1.18
export PLATFORMIO_CORE_DIR="$PWD/tmp/esp32-platformio"
pio run -d firmware/esp32_gateway -e cores3 -e cores3_ethernet
# Optional unqualified native bench images; no upload is performed:
pio run -d firmware/esp32_gateway -e cores3_native_test -e cores3_ethernet_native_test
python firmware/esp32_gateway/tools/test_native.py --sanitizers
```

`cores3` uses Wi-Fi. `cores3_ethernet` uses the existing Base LAN W5500 wiring.
The matching `_native_test` environments select the native candidate, force all
qualification bits off, and boot with RF admission disarmed. Use the wired build
for RF qualification so co-located Wi-Fi is not another variable. The toolchain and libraries are pinned in
[platformio.ini](platformio.ini); exact installed versions and licenses are
recorded in [dependencies](docs/dependencies.md).

Native tests require CMake, CTest and a C++17 compiler. The wrapper probes the
compiler/linker first, selecting another installed macOS SDK if the default SDK
cannot link. It downloads nothing. The tests cover stream fragmentation,
Unicode lengths, state mutation and corruption, scenes/schedules, resource
limits, authentication/HTTP framing, discovery, radio register/timing failures,
and sequence commit/readback faults. ASan and UBSan apply to the portable code;
they do not exercise ESP32 peripherals or the Arduino adapter. Additional
screen tests cover tap/release gestures, stale selections, group validation,
renderer bounds, and repeated display/Ethernet ownership transitions.

The existing host checks remain separate:

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
python -m build
```

The 2026-10-25 native planner/control update passed all 12 portable test
executables with ASan/UBSan. Radio tests compare 162,000 complete planner events
with the Python references and model SPI wire time, TX completion, cancellation,
clock wrap and missed deadlines. These checks do not exercise Arduino SPI, real
RF timing or the assembled appliance. The full host suite passed 364 tests,
including the supplied-source libbladeRF regression, and its wheel/sdist built.
The actual ESP32 instruction-emulator image passed seven read-only network
checks and seven control checks across eight fictional shades in four rooms.
Wi-Fi, Ethernet, both native test variants and the emulator image built.
Run the build and test commands above against the exact image being released.

## Configure and provision

Copy `include/gateway_config.example.h` to the ignored
`include/gateway_config.h`. Set the Wi-Fi credentials for the Wi-Fi build, an
explicit private IPv4 client subnet/mask for either build, and a random token
of at least 32 characters. A blank SSID leaves Wi-Fi unconfigured; a blank token disables authenticated
API access. An unset client subnet disables both network services. Do not commit the private header or firmware images containing
it. Use the board's IPv4 address in URLs; HTTP verifies the `Host` and, when
present, `Origin` headers against that address and port 8077.

Initial service defaults are `GATEWAY_TCP_ENABLED`, `GATEWAY_HTTP_ENABLED` and
`GATEWAY_WEB_ENABLED`. Saved settings override these defaults after a settings
change. The web interface is at `http://DEVICE_IP:8077/`.
[API documentation](docs/http-api.md) includes a Home Assistant REST example.
The legacy TCP service has no authentication; both network services enforce the
configured client subnet. HTTP bearer tokens here run over a trusted local
network, without TLS.

Populate rooms, shades, scenes and schedules through the legacy app or the
API's `/api/command` endpoint. All new shades start with **no operation grants**.
For an initial simulated setup, the following independent HTTP transactions
create a fictional room and shade (each needs its own `request_id`):

```text
$ar01-06-Lounge
$as0-04-East
```

The serial monitor at 115200 baud provides these newline-terminated commands:

| Command | Behavior |
| --- | --- |
| `status` | Storage/network/backend/busy state and inventory counts. |
| `services 0 1 1` | Disable TCP/discovery; keep HTTP and web enabled. Values are TCP, HTTP, web booleans. |
| `services 1 0 0` | TCP/discovery only. |
| `services 1 1 1` | Re-enable both interfaces and the web page. |
| `export` | Private database backup as a hexadecimal PGW1 binary envelope. |
| `import HEX` | Validate and atomically replace a backup from this firmware; refused during active work. Does not reset sequence or service settings. |
| `bind SHADE ROOM_HEX SLOT` | Replace that shade's room RF identity and its slot (1–8); revoke all grants in the affected room. Use only your installation's known binding. |
| `grant SHADE FEATURE_BITMASK` | Enable selected feature bits for an existing shade; zero revokes them. |
| `control SHADE FEATURE ROLE OPEN_VALUE` | Record verified physical mapping for feature 4 or 18; grants unchanged. Roles: 0 unknown, 1 lift, 2 top rail, 3 bottom rail. Open value: 0, 255, or 256 for unknown. |
| `command LAN_TRANSACTION` | Execute one complete legacy transaction through the shared engine; all grants and backend gates apply. |
| `rf-test FEATURE_BITMASK` | Native bench image only: arm supported feature bits for at most 60 seconds. Zero disarms and requests cancellation. No persisted grant is added. |
| `sequence NEXT_UNUSED` | Repeater route only: initialize the independent sequence store once, only when absent. Existing, corrupt or exhausted state is not reset. |

Example `grant 0 16` enables primary position (bit 4) for shade 0 in simulation
or, with separate backend permission, RF. Sync is bit 1; Jog is bit 12. `grant 0 4114` enables
all three for a backend that supports them. Secondary position is bit 18
(`262144`); native supported bits are 4, 12 and 18. A native bench image also
requires an explicit `rf-test` window, for example `rf-test 16` for primary only.
Rearming is refused while busy; expiry/disarm cancels remaining native packets.
A packet already started may finish. Granting or arming never establishes
physical interoperability.
Changing room product or shade binding revokes grants; stale staged commands
are invalidated by database generation changes. Numeric LAN IDs compact on
removal while surviving RF identities and slots remain attached to their targets.
Integrations must refresh IDs after inventory deletion.

The binary backup format is for this firmware, not an original bridge EEPROM or
raw `$dat` dump. The PGW1 envelope now stores schema 3 with per-feature physical
control mappings and the latest requested feature separate from history.
Schema-1 and schema-2 backups migrate; ambiguous request order remains unknown,
and schema-1 physical mappings remain unknown. Roles and direction are never
inferred from product codes or grants. Identity changes revoke mappings, grants
and request history. Original opaque inventories cannot yet be
imported losslessly. Binding a new room identity is not proof of pairing.

## CoreS3 SE touchscreen

The screen is enabled by default in both builds. It works independently of the
TCP and HTTP switches and requires no browser, API token or working LAN link.
It uses the same persisted inventory and installation grants as the API.
An unplugged Ethernet cable does not block startup or trigger DHCP waits. With
a connected link, the Ethernet library still performs short synchronous DHCP
requests/renewals; those can briefly pause the main loop. Lease attempts are
skipped while a touch gesture or radio operation is active.

1. Choose **Shades** for individual blinds or **Groups** for rooms. A room group
   contains every shade currently assigned to that room; these are not the
   separate four groups on a handheld remote.
2. Tap a row. Use **Prev / Next** to browse more than three items.
3. Select the feature, adjust the raw 0–255 value with **− / +**, then apply it.
   Open/Close uses the saved endpoint mapping; unknown direction is labelled
   with raw endpoints instead. Feature 10 is a separate **Preset 7** action.
   **Back** returns to the list.

A group action requires that every member supports and grants the chosen feature
and that the backend admits it. Open/Close also requires every endpoint mapping;
individual shades can have different raw directions. Empty groups, faults and
active work disable controls. Repeater mode additionally requires a usable
sequence store; native mode has no repeater ordinal dependency.

Actions happen once, on a stationary single-finger release in the same button.
Dragging more than 15 pixels or using multiple fingers cancels the gesture.
Inventory edits cancel pending gestures and clear stale selections, preventing
renumbered IDs from redirecting a touch to another blind. Touch controls never
bypass the existing dispatcher or transmit directly.

The renderer uses a 153,600-byte RGB565 sprite in PSRAM and redraws changed views
at most ten times per second; touch is polled every ten milliseconds. A local
command paints its busy state before admission. LCD redraws pause during active
physical radio work. Other interfaces can still update inventory/status, which
appears when the view refreshes. Display allocation or bus initialization failure
leaves local controls unavailable and reports a USB diagnostic.

Set `GATEWAY_SCREEN_ENABLED false` in the private header to restore headless
operation. Wired mode transfers ownership of the shared LCD/W5500 SPI controller
only for dirty redraws and explicitly switches GPIO35 between LCD D/C output and
Ethernet MISO input. See the [display hardware notes](docs/display-hardware.md)
for the implementation and the required first-article logic-analyzer checks.
No physical screen or simultaneous Ethernet test has been claimed from builds.

Run the complete local firmware environment on macOS:

```sh
python3 firmware/esp32_gateway/tools/device_simulator.py
```

This opens a native macOS window backed by an ESP32-S3 instruction emulator.
The real ROM, bootloader and gateway image run with emulated flash, PSRAM,
SPI LCD, I²C touch/power chips, Wi-Fi and TCP networking. Click the screen to
select shades or groups and use Open/Close. The fictional sample inventory
is loaded through the firmware's USB console. See the
[setup and validation notes](docs/device-simulator.md) for dependencies,
the API endpoints, and peripheral limits. The optional Wokwi setup boots the
same firmware, but its stock CoreS3 board does not provide working touch wiring.

The older host UI preview remains available as a separate development tool:

```sh
python3 firmware/esp32_gateway/tools/simulator.py
```

Open `http://127.0.0.1:18077/`. Click the screen to select shades or groups and
open/close them. **Copy token** supplies the bearer token for **Web interface**;
both interfaces share the same sample inventory. **Reset** restores that inventory
and the service switches. Ctrl-C stops the server.

The preview runs the actual portable command engine, touch model and renderer.
Its host HTTP adapter serves the firmware's web page. Sample state lives in memory;
per-feature cards show requested raw values and jobs finish after 900 ms without
radio I/O. It does not emulate the ESP32 drivers, TCP socket, or hardware timing.
The server binds only to loopback. To check the host adapter after building:

```sh
python3 firmware/esp32_gateway/tools/test_simulator.py --binary firmware/esp32_gateway/build/simulator/gateway_simulator
```

Static layout previews use the same renderer, with approximate font metrics:

```sh
python firmware/esp32_gateway/tools/test_native.py --sanitizers
firmware/esp32_gateway/.native-build/screen_preview shades > tmp/screen-shades.svg
firmware/esp32_gateway/.native-build/screen_preview detail > tmp/screen-group.svg
```

## State and operations

The portable engine owns inventory and scheduling. The main task owns networking,
USB and engine calls; a queue with one entry feeds a separate radio task. A
command's requested state is committed before admission. Repeater mode reserves
and verifies an RF ordinal before each burst; failures consume reservations.
Ordinals 0–65535 are local allocation values, and exhaustion stops that route.
Native packets contain no such sequence: their explicit diagnostic profile is
7,500 command plus 1,500 followup packets, prior channel 71, prior Jog alternate
0, nominal 200.5 µs slots and an assumed idle phase-2 start. This is a finite
1.8045-second plan, not a measured universal shade timing requirement. Neither
route retries failed work.

Schedules use the app-set local date/time and weekday mask (bit 7 enables;
bits 0–6 are Sunday–Saturday). Date/time must be supplied again after reboot;
there is no RTC, NTP, timezone, DST or solar engine yet. Daily execution markers
are durable, and moving the clock backward does not replay an already burned
day. Missed events are not replayed after their minute. An event due while
another operation is busy can run later in the same minute. Disabling a network
interface does not disable local schedules or abort work already submitted.

`$stps` cancels queued portions of an active Sync. It cannot retract transmitted
packets and does not interrupt a burst mid-packet; a current finite burst can
finish before cancellation is observed. Completion indicates submission or
simulation, never measured position or confirmed enrollment.

Ceilings: three TCP clients, one HTTP connection, 1,024 command bytes, 4 KiB each
for HTTP headers/body (8 KiB total), 32 rooms, 100 shades, eight shades per room,
32 scenes, 64 schedules and 100 commands per operation. A conservative 48 KiB
snapshot budget additionally limits aggregate database size. HTTP retry receipts
are limited to 16 entries and approximately 64 KiB per boot. Slow or oversized
clients are closed; incomplete TCP requests time out after ten seconds and idle
TCP sessions after 300 seconds.

## Hardware and release qualification

Follow the [carrier firmware contract](../../hardware/design/firmware-contract.md)
and [radio qualification procedure](docs/radio-qualification.md). Power via
CoreS3 USB-C, leaving the LAN-base DC input disconnected. The startup sequence
turns USB output off, requests M-Bus power, verifies its reported state, then
uses a provisional 50 ms rail delay. Measure this on the first article.

M5Unified initializes the display and touch controller. Touchscreen builds keep
LCD ownership in Wi-Fi mode and explicitly transfer it around each screen update
in wired mode. Headless builds sleep/release the display once. Keep the SD socket
empty and accessories disconnected. Radio uses HSPI GPIO6/5/8 with CSN18, CE17
and IRQ10; Ethernet uses SPI GPIO36/37/35 with CS9 and reset7. SD CS stays inactive.
No shutdown/power-switch UI is exposed; any future power path must call
`radio.shutdown()` before removing the carrier rail.

The native bench images require both persisted per-shade grants and the USB
`rf-test` admission window. Production native permission is separate, through
`GATEWAY_RF_NATIVE_QUALIFIED_FEATURES`, which defaults to zero. Repeater mode
retains its global enable/qualification flags and sequence requirement. Module
power starts at level 0; level 3 is rejected. The packet engine cannot directly
reproduce SDR pulse shaping. Its 2 Mbps no-PCF compatibility and tight hopping
budget remain unproved on the NiceRF module; see the radio qualification guide.
Native Sync/enrollment is deliberately unsupported: the source suggests a much
longer held/tail lifecycle that requires separate implementation and testing.

Firmware source is `GPL-2.0-or-later`; documentation follows the repository's
dual documentation license. Preserve dependency notices and review corresponding
source/build obligations before distributing linked binaries. This directory is
self-contained for a future repository split, apart from cited research and
license texts in the parent repository.
