<!--
SPDX-FileCopyrightText: 2026 Christopher Spitler
SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later
-->

# Unit build and acceptance traveler

Copy this template for a real unit. Empty fields mean not recorded; unchecked
items mean not completed. The template itself is not a completed test report.
Use [acceptance-test.md](acceptance-test.md) for procedures and limits.

| Identification | Recorded value |
| --- | --- |
| Unit serial | |
| PCB revision / source identifier | |
| Fabrication supplier / lot | |
| PCBA supplier / lot | |
| BOM and system BOM revisions | |
| Accepted stackup / impedance-report reference | |
| U1 manufacturer / markings / lot | |
| CoreS3 SE and Base LAN identifiers | |
| Radio pigtail / antenna MPNs | |
| Power supply MPN / region | |
| Application firmware version and hash | |
| Test firmware version and hash | |
| Build date / operator | |

## Manufacturing and mechanical checks

- [ ] Bare-board electrical test passed; supplier report retained.
- [ ] PCBA inspection passed, including U1 ground/ANT joints and J2.
- [ ] A089 on bottom with correct pin-1 orientation and mating depth.
- [ ] All 30 header contacts pass continuity and adjacent-short checks.
- [ ] Board retained in M032 with four original M2 × 5 mm self-tapping screws.
- [ ] Cases seat without forcing; no component, coax or fastener interference.
- [ ] Bulkhead fixed and coax strain-relieved; accepted assembly photos retained.

| Measured mechanical detail | Recorded value |
| --- | --- |
| Finished PCB thickness | |
| Header male protrusion / mating depth | |
| Stack screw lengths by position | |
| Minimum component and coax-plug clearance | |
| Bulkhead drawing revision / mounting location | |

## Electrical and functional results

| Test | Result / measurement | Equipment / evidence |
| --- | --- | --- |
| No unintended power-rail shorts | | |
| RF rail off with HOST3V3 low | | |
| Carrier 5 V input | | |
| RF rail enabled / idle voltage | | |
| Carrier-only idle current | | |
| CE low / CSN high / SCK low defaults | | |
| RF rail RX minimum / maximum | | |
| RF rail TX minimum / maximum | | |
| Radio SPI and IRQ | | |
| W5500 Ethernet while radio active | | |
| Complete stack startup / reset / reconnect | | |
| TCP and HTTP functional check | | |
| Shade command and independently observed movement | | |
| Configuration and sequence persistence after restart | | |
| Firmware/release qualification record reference | | |

## Disposition

| Release field | Recorded value |
| --- | --- |
| Disposition: accepted / rework / rejected / engineering hold | |
| Deviations or unperformed checks | |
| Rework record and retest reference | |
| Reviewer / date | |

For a first article, attach the additional waveform, RF-output, full appliance
and soak-test evidence required by the acceptance procedure. Do not mark a
unit accepted for distribution while those design-release gates remain open.
