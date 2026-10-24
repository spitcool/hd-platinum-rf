<!--
SPDX-FileCopyrightText: 2026 Christopher Spitler
SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later
-->

# Acceptance and release procedure

This procedure separates manufacturing workmanship from complete-appliance
behavior. A bare-board test or successful radio register read is not a shade
control test. Record pass/fail, readings, equipment and operator against the
board serial and design revision. Unperformed tests remain **not tested**.

The numeric limits below are engineering targets for initial qualification.
Freeze final production limits after measuring first articles across the
intended operating conditions; do not silently widen a failing limit.

## 1. Design and mechanical qualification

Before approving a repeat lot, confirm all of the following on assembled first
articles from the intended supplier:

- Gerbers/drills, schematic, BOM and assembly drawings have matching revisions;
  the exact final CAD passes its configured ERC and DRC, with any exclusions
  reviewed and recorded.
- The supplier has accepted the actual stackup and RF geometry, module assembly
  method and stacking-connector operation.
- Board outline and hole locations match the mechanical drawing; the carrier
  seats in the M032 frame without board flex or interference.
- Header polarity, mating depth, case closure, screw engagement and coax bend
  radius are checked with the actual K128-SE and K012-B-V12 units.
- The enclosure exit, bulkhead clearance, strain relief and external antenna
  arrangement are photographed and captured in the released assembly drawing.

This qualification uses production-intent parts and is part of completing the
appliance design, not a separate debugging-hardware variant.

## 2. Every bare PCB / assembled carrier

| Test | Method | Acceptance |
| --- | --- | --- |
| Bare-board nets | Fabricator electrical test against submitted netlist | No opens or unintended shorts |
| PCBA visual inspection | Magnification of radio joints, regulator, passives, RF connector and header | Correct MPNs/orientation; no bridges, damaged contacts or loose parts |
| M-Bus pass-through | Unpowered continuity fixture for all 30 contacts | Each corresponding top/bottom contact connected; adjacent contacts not bridged |
| Supply isolation | Unpowered inspection/continuity test against schematic | RF 3.3 V is not directly tied to M-Bus 3.3 V; no short on 5 V or RF 3.3 V to GND |
| RF feed inspection | Inspect ANT-to-connector route and ground joints | No solder bridge to ground or open joint; geometry matches CAD |

Resistance-to-ground readings can be affected by capacitors and semiconductor
paths. Use them to detect shorts with a qualified fixture, not a universal
arbitrary resistance threshold. Do not apply a high-voltage insulation test
to an assembled board containing the radio and regulator.

## 3. Carrier-only power check

Keep the CoreS3 SE and Base LAN disconnected. The carrier uses **HOST_3V3 as
U2's enable signal**, so applying 5 V alone intentionally leaves the radio
supply disabled. For a carrier-only fixture, use a separately current-limited
3.3 V source on TP7 to simulate that host signal, with a common ground. Do not
connect TP7 to TP3 or to 5 V. This fixture connection is only for a disconnected
carrier; do not drive the installed Core's 3.3 V rail from an external source.

| Testpoint | Net | Purpose |
| --- | --- | --- |
| TP1 | GND | Common measurement/fixture return |
| TP2 | BUS_5V | Carrier 5 V power input |
| TP3 | RF_3V3 | U2 output and U1 supply |
| TP4 | RF_CE | Radio-side CE, after the series resistor |
| TP5 | RF_CSN | Radio-side chip select, after the series resistor |
| TP6 | RF_IRQ | Active-low radio interrupt |
| TP7 | HOST_3V3 | Host rail sense / U2 enable; not the radio supply |

Connect ground first, then the 5.0 V supply to TP2. Confirm the radio remains
off with TP7 low. Apply the fixture's 3.3 V enable to TP7 and measure TP3.
Follow the assembly drawing's labels and header orientation; never infer power
pins from an upside-down connector photograph.

Start with CE held low by R6 and no SPI activity. Set the 5 V input current
limit to **150 mA** for initial idle bring-up and the 3.3 V enable source to
**10 mA**. Once the idle checks pass, a **250 mA** limit on the carrier's 5 V
input supports finite TX testing. These are carrier-only fixture limits; they
do not budget the CoreS3 SE or LAN base. A current-limit trip is a failure
to investigate, not permission to raise the limit repeatedly.

| Measurement | Initial acceptance target |
| --- | --- |
| Supply at carrier 5 V input | 5.0 V nominal from test supply |
| Regulator output / radio VCC | 3.20–3.40 V steady state; never outside the radio's 1.9–3.6 V operating range |
| Enable defaults after TP7 is asserted | CE low through R6; CSN high through R7; SCK low through R8 |
| Unexpected heating | No rapid heating of regulator, radio or connector; compare measured input current with qualified first-article baseline |
| RF 3.3 V versus M-Bus 3.3 V | No hard connection or unintended power transfer through a board trace |

Remove the fixture enable and verify U2 disables the radio rail. Log quiescent
input current. Set a production current window from measured
known-good boards and the confirmed radio module revision; this document does
not invent a guaranteed module startup-current limit.

## 4. Digital and supply-load test

Use a versioned ESP32-S3 test firmware image. Keep the radio-facing GPIOs
low or high impedance until RF 3.3 V is present; in particular, leave CSN high
impedance so its pull-up follows the radio rail rather than driving an unpowered
module. Explicitly enable the CoreS3 SE's M-Bus 5 V output when powering from
its USB port, following its power-management API. After RF 3.3 V is stable,
drive CE low and CSN high before starting SPI. Keep radio transmission disabled
until a 50 ohm load or the approved antenna is attached.

1. Read the radio register set over the dedicated bus: SCK GPIO6, MOSI GPIO5,
   MISO GPIO8, CSN GPIO18. Verify repeatable read/write of a harmless
   configuration register and restore the expected configuration. Begin with
   SPI mode 0 at 1 MHz; qualify any faster clock separately.
2. Confirm CE on GPIO17 and active-low IRQ on GPIO10. Exercise receive and
   completion/interrupt behavior using a known-good radio peer. Reject a
   floating or permanently asserted IRQ.
3. Initialize W5500 Ethernet on its separate pins and verify its link and
   traffic while repeatedly exchanging radio data. No GPIO shared by the
   Ethernet control signals may be driven by the radio driver.
4. Scope RF 3.3 V at the radio during RX and permitted finite TX bursts while
   Ethernet and the display operate. Initial target is 3.20–3.40 V throughout
   normal activity, without reset, ringing above 3.6 V or regulator thermal
   limiting. Use a short probe ground connection.
5. Verify correct startup, shutdown and reset behavior for the selected system
   power path. In particular, hold CE low during host reset and ensure CSN does
   not float into an unintended command transaction.

## 5. RF first-article qualification

Use conducted RF measurement or a controlled known-good setup. Protect the
receiver/instrument with attenuation suitable for the RF2401F20's PA output;
do not connect its transmitter directly to an SDR receiver input. Use the
radio supplier's permitted power setting for this module revision. For the
reviewed RF2401F20 V3.1, set **RF_PWR=0 initially and never exceed 2**. The nRF24
chip's setting name is not the calibrated output power of the PA module.
The module datasheet lists 135 mA typical / 150 mA maximum TX current at
20 dBm and 23.5 mA typical / 24 mA maximum RX current; these are module ratings,
not promises that every permitted setting produces 20 dBm or that the complete
appliance draws only that current. Source details are in the
[electrical evidence](../design/electrical-evidence.md).

Capture the actual emitted waveform and check:

- 2440 MHz center frequency and the intended 250 kbps PHY;
- preamble/address order, 3-byte `e7 e7 e7` address, packet-control-field
  behavior, 9- and 12-byte payload handling and CRC;
- packet ordering, PID/sequence behavior, repeated-packet handling and the
  intended burst cadence against this repository's working reference;
- receive operation following TX, including the reply interval;
- stable radio behavior under simultaneous Ethernet and touchscreen activity.

Do not copy the SDR's sample-stream timing assumptions directly into the
hardware FIFO API. In particular, hardware auto-ACK, auto-retry and PID
generation can change the on-air packet sequence. Qualify the actual firmware
and RF waveform together. If the nRF24 packet engine cannot produce the
required behavior, the hardware/firmware combination fails this gate even if
register access and ordinary peer-to-peer radio tests pass.

Measure conducted output, occupied spectrum and the final antenna arrangement
at the intended settings before freezing the RF BOM. The first article must
also demonstrate reliable control at the placement and range intended for
users. Record the environment, antenna orientation and any repeater used.

## 6. Complete appliance qualification

Run the following with the intended release firmware and a real compatible
Platinum installation:

| Area | Required result |
| --- | --- |
| Ethernet | Link, address acquisition/configuration and reconnect recover without manual reset |
| TCP service | Expected commands on port 522 produce the documented responses; disconnects and malformed input do not corrupt command state |
| Web service | UI/API responds during radio traffic; configuration persists across reboot |
| Shade control | Qualified open, close, stop and supported position operations produce independently observed motion on the intended shades |
| Enrollment/configuration | A recipient can configure the supported installation without hidden developer files or an SDR |
| Sequence persistence | Restart and interrupted power do not reuse reserved command identities in an unsafe or incompatible way |
| Concurrency | Concurrent clients serialize radio actions without corrupting timing or replies |
| Reboot recovery | Repeated cold starts and network outages recover to a usable state |
| Soak | At least 24 hours of powered operation with a scheduled, bounded command set; no unexpected resets, lost configuration or excess heat |

The host Python implementation is a reference for these behaviors. These tests
cannot be marked passed merely because its test suite passes; the ESP32-S3
firmware and complete stack must be exercised.

## Release record

Keep the approved PCB revision, BOM revisions, supplier/lot, stackup, firmware
hash, test-firmware hash, photographs, measurements and signed test results
together. Record any failed or unsupported installation case explicitly.
Distribution release requires completed mechanical, radio, firmware and
appliance checks, plus the final product's applicable conformity review. A
module's test report or advertised approval is not a finished-product approval.

For repeat units, run sections 2–4 and the defined short appliance functional
test on every unit; the qualification record determines any justified sampling
for the more extensive RF and soak tests.
