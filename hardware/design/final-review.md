<!--
SPDX-FileCopyrightText: 2026 Christopher Spitler
SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later
-->

# Revision A design-package review

Review date: 2026-10-24. Status: **engineering first article; not production
released**. This review reconciles the manufacturing instructions with the
checked native CAD and its recorded validation results. It is not evidence of
a fabricated board, physical assembly or executed ESP32 firmware.

## Recorded design checks

| Check | Recorded result | Evidence |
| --- | --- | --- |
| KiCad schematic ERC | 0 errors, 0 warnings | [schematic-erc.rpt](../reports/schematic-erc.rpt) |
| KiCad PCB DRC, including warnings and schematic parity | 0 violations, 0 unconnected items, 0 parity differences | [pcb-drc.json](../reports/pcb-drc.json) |
| DRC exclusion list | Empty | [project configuration](../kicad/hd-platinum-carrier-rev-a.kicad_pro) |
| Exported schematic versus board specification | 65 connected pins / 17 intended nets; 0 mismatches and 0 unexpected connected pins | [schematic-netlist-check.json](../reports/schematic-netlist-check.json) |
| Independent native-CAD mechanical/orientation checks | 95 of 95 passed | [mechanical-check.json](../reports/mechanical-check.json) |
| Firmware timing documentation | All 10 listed preamble timestamps match the current host source's sample offsets and lead | [firmware-contract.md](firmware-contract.md), [rf_bridge.py](../../src/hd_platinum/rf_bridge.py) |
| Copied footprint integrity | Eight local standard footprints match their recorded SHA-256 hashes | [footprint manifest](../references/kicad-footprints-sources.json) |
| Manufacturing export integrity | 41 checks passed: BOM, placements, drill counts, output coverage and hashes | [manufacturing-check.json](../reports/manufacturing-check.json) |
| System BOM structure | 10 unique line items; consistent CSV columns | [system-bom.csv](../manufacturing/system-bom.csv) |

The mechanical report records the reviewed PCB's SHA-256; comparison with the
native board file matched during this review. Any subsequent PCB change
requires rerunning the applicable checks and regenerating the manufacturing
outputs. The DRC result applies to the checked-in rule profile, rather than
establishing every possible electrical or physical property of the assembly.
The recorded environment is KiCad 9.0.8, `kicad-footprints` 9.0.7-1 and
`kicad-symbols` 9.0.7-1; see [tool-versions.txt](../reports/tool-versions.txt).
The schematic uses the project's original self-contained symbols.

## Manufacturing cross-check

The documentation calls for a 50 × 50 mm M032 replacement board with the
verified notches/chamfers, eight non-plated mechanical holes, all SMT parts on
the inward B.Cu side, and the A089 female housing on that same side. The
Core-facing surface receives the connector's male tails. The PCB passes the
native coordinate/orientation checks; actual plastic tolerances and mating
depth are still physical measurements.

The requested four-layer construction is JLC04161H-7628, nominal 1.6 mm. The
RF route is on B.Cu over In2.Cu through 0.2104 mm prepreg with reference Dk=4.4.
Its width is 0.35 mm and its same-layer clearance is 0.50 mm. The mechanical
checker finds a single 3.85 mm ANT trace with no RF vias. The supplier must
still verify the finished geometry for 50 ohms ±10%, including solder mask
and final copper thickness. The checked trace rule is not an impedance
measurement or field-solver result.

The native PCB explicitly sets 0.05 mm pad-to-mask expansion and 0.10 mm minimum
mask width. The fabrication notes request supplier review of those webs and
0.65 mm legend text. **J2 alone permits the original Hirose footprint's
intentional mask-opening bridge**, retaining its copper keepout and all pad
geometry; this is a documented per-footprint allowance, not a global mask-rule
relaxation or an excluded DRC violation. The supplier must accept those details
or return a source revision request. The assembled radio uses the V3.1 pinout: pin 11 ANT and
pins 2/9/10 GND. U2 EN senses HOST3V3; RF3V3 is separate from the host rail.
The carrier-only test therefore provides both 5 V power and a separate 3.3 V
enable signal with the Core disconnected.

The system BOM specifies the CoreS3 SE K128-SE, LAN base K012-B-V12, M032
frame, CAB.628 pigtail, GW.11.A153 antenna and SC0218 USB-C supply. Whole-stack
M3 screw lengths and the exact enclosure bulkhead/strain-relief arrangement
remain identified physical-fit holds, rather than invented manufacturing
dimensions. All required handoff categories appear in the
[supplier checklist](../manufacturing/order-checklist.md).

## Uncompleted release evidence

| Remaining item | Evidence needed to close it |
| --- | --- |
| Module land pattern and A089 terminals | Purchased-part dimensional comparison and assembled solder/contact inspection |
| Enclosure assembly | Measured PCB seat/thickness, header engagement, clearance, screw lengths and a dimensioned bulkhead modification |
| Power and temperature | Full-stack startup/current, RF rail transient captures and closed-enclosure thermal measurements |
| RF interconnect | Fabricator-approved impedance geometry and manufactured-board RF measurements |
| Native radio compatibility | Captured 250 kbps ESB waveform with required PCF/PID/CRC/length/timing and actual shade operation |
| Display and Ethernet | Demonstrated GPIO35 ownership without contention using the selected firmware/library versions |
| Deployable firmware | ESP32-S3 application, configuration/enrollment workflow, persistent sequence handling and networking acceptance |
| Repeat-build release | Completed unit traveler, qualified limits, frozen BOM/firmware and final product conformity review |

The RF2401F20 is half-duplex and its packet engine does not offer the same
arbitrary sample control as the successful bladeRF backend. An ACK-setting
recipe that drops the nine-bit PCF is incompatible with the reference frame.
These points are explicit firmware qualification conditions, not conclusions
settled by clean CAD checks. See the [firmware contract](firmware-contract.md)
and [acceptance procedure](../manufacturing/acceptance-test.md).

## Source and attribution

The package retains editable native source, local footprints, source manifests
and reproducible design tools. [LICENSE.md](../LICENSE.md) distinguishes
project CAD/tools, dual-licensed documentation, MIT-licensed M5Stack reference
attribution and the CC-BY-SA KiCad footprint collection with its library
exception. Vendor component PDFs have not been added to the distributed tree.
