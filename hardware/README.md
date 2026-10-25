<!--
SPDX-FileCopyrightText: 2026 Christopher Spitler
SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later
-->

# Platinum M5Stack radio carrier

This hardware adds an enclosed 2.4 GHz radio to an M5Stack CoreS3 SE and Base
LAN v1.2 stack. The intended product is an Ethernet-connected Platinum shade
bridge with a local TCP service and a small web interface. The radio PCB is designed for
a Module13.2 frame; a coax cable connects it to an external antenna.

**Revision A is an engineering first article.** The CAD and manufacturing
outputs describe a board to build and qualify. They do not establish measured
enclosure fit, RF performance, or compatibility with every Platinum shade.
Complete the [acceptance procedure](manufacturing/acceptance-test.md) before
releasing a repeat build for other users.

The recorded KiCad checks pass with **zero ERC errors/warnings, zero PCB DRC
violations, zero unconnected items and zero schematic-parity differences**;
there are no DRC exclusions. Independent checks passed 95 mechanical/orientation
assertions and 41 manufacturing-package checks and matched 65 connected schematic pins on 17 intended nets.
These check the design files. Physical fit, RF measurements, native-radio
interoperability and the ESP32 firmware remain qualification work. See the
[design-package review](design/final-review.md) for the evidence and limits.

## Appliance architecture

The [final assembly drawing](manufacturing/final-assembly.pdf) shows the
exploded stack, assembled enclosure and a cutaway of the M032 radio layer.
See the [illustrated assembly guide](manufacturing/final-assembly.md) for the
part list and sequence, or open the [SVG](manufacturing/final-assembly.svg).

```text
M5Stack CoreS3 SE K128-SE
  ESP32-S3: application, touchscreen, TCP and HTTP services
                  │ M-Bus power and GPIO
M032 Module13.2 frame + this replacement carrier PCB
  5 V → separate 3.3 V regulator → NiceRF RF2401F20
  dedicated SPI and control GPIO → 2.4 GHz radio
  RF connector → internal coax → external antenna
                  │ all 30 M-Bus contacts pass through
M5Stack Base LAN v1.2 K012-B-V12
  W5500 wired Ethernet and appliance base
```

The custom PCB replaces the M032 prototyping PCB. It is not an adapter soldered
onto the M032 hole grid. The Base LAN and CoreS3 SE remain purchased products.
This carrier does not add Ethernet, PoE, a charger, or another processor.

The radio has a separate SPI bus from the W5500. It uses GPIO 6/5/8 for
SCK/MOSI/MISO and GPIO 18/17/10 for CSN/CE/IRQ. The carrier derives its radio
supply from M-Bus 5 V; its RF 3.3 V rail must not connect to the M5Stack's 3.3 V
rail. The [electrical evidence](design/electrical-evidence.md) and
[pin assignment](design/pin-assignment.csv) record the interface details.

## Files and reproducible build

The complete [hardware review archive](hd-platinum-carrier-rev-a-review.zip)
contains the native source, manufacturing outputs, evidence, tools and license
notices. The archive is for engineering review and first-article planning.
The [tool instructions](tools/README.md) explain how to validate the native CAD
or regenerate it from source. A complete source regeneration and export passed
on the recorded KiCad 9.0.8 toolchain.

## What to send to a manufacturer

Open [the editable KiCad PCB](kicad/hd-platinum-carrier-rev-a.kicad_pcb) and
[schematic](kicad/hd-platinum-carrier-rev-a.kicad_sch), or review the exported
[schematic PDF](manufacturing/schematic.pdf) and
[bottom assembly drawing](manufacturing/assembly-bottom.pdf). The PCB is
50 × 50 mm with all surface-mount parts on the inward-facing bottom side.

Send the [Gerber/drill ZIP](manufacturing/hd-platinum-carrier-rev-a-gerbers.zip),
[PCBA BOM](manufacturing/bom.csv), [placement file](manufacturing/positions.csv),
the [fabrication drawing](manufacturing/fabrication-drawing.pdf),
assembly drawings and these documents together. The [board-only STEP](manufacturing/carrier-board-only.step)
and [outline DXF](manufacturing/board-outline.dxf) support enclosure review;
the STEP does not include components or an enclosure. Keep every file in a handoff
at the same board revision. The editable project and generation tools remain
the source for future revisions.

| Document | Purpose |
| --- | --- |
| [Final assembly drawing and guide](manufacturing/final-assembly.md) | M5Stack stack order, carrier location inside M032, antenna and cable arrangement |
| [Fabrication specification](manufacturing/fabrication.md) | Board construction, RF geometry, drill and DFM requirements |
| [Assembly instructions](manufacturing/assembly.md) | Component handling, orientation, stack assembly and coax installation |
| [Supplier checklist](manufacturing/order-checklist.md) | Quote scope, sourcing, deliverables and release gates |
| [Acceptance procedure](manufacturing/acceptance-test.md) | Bare PCB, assembled carrier and complete appliance tests |
| [Unit traveler template](manufacturing/traveler-template.md) | Per-unit part, measurement and acceptance record |
| [Mechanical evidence](design/mechanical-evidence.md) | Source dimensions, connector and enclosure fit assumptions |
| [Electrical evidence](design/electrical-evidence.md) | Source pinouts, radio constraints and power design |
| [Firmware contract](design/firmware-contract.md) | Initialization, bus ownership, packet-engine limits and porting requirements |
| [Design-package review](design/final-review.md) | Recorded CAD checks, manufacturing cross-check and open physical qualification |

## Purchased system parts

The PCBA BOM covers parts fitted to the custom carrier. These are separate
appliance items; do not accidentally order them once per carrier component.
The machine-readable list is [system-bom.csv](manufacturing/system-bom.csv).

| Item | Manufacturer part / SKU | Quantity per appliance | Procurement note |
| --- | --- | ---: | --- |
| Controller | M5Stack **K128-SE**, CoreS3 SE | 1 | This design's M-Bus assignments target CoreS3 SE. Do not substitute a Core Basic or Core2. |
| Ethernet base | M5Stack **K012-B-V12**, Base LAN v1.2 | 1 | Use v1.2 and verify its switch configuration against the electrical notes. |
| Radio-layer enclosure | M5Stack **M032**, Module13.2 Proto | 1 | Retain the frame; replace the perfboard with this carrier. |
| Assembled carrier | This project, matching board revision | 1 | Includes the exact RF2401F20 module, regulator and RF connector listed in the PCBA BOM. |
| Internal coax pigtail | Taoglas **CAB.628** | 1 | 95 mm, 1.13 mm coax; I-PEX MHF I board plug to RP-SMA female bulkhead. Verify cable routing and enclosure wall fit. |
| External antenna | Taoglas **GW.11.A153** | 1 | 2.4 GHz hinged antenna, RP-SMA male; matches CAB.628. Actual installation/range requires qualification. |
| Stack fasteners | Sized to the measured final assembly | 1 set | CoreS3 stacks can need different lengths at different positions. Do not select from total case height alone. |
| Power supply with captive USB-C cable | Raspberry Pi **SC0218**, black US 15 W supply | 1 | Fixed 5.1 V / 3 A into CoreS3 SE USB-C; enable M-Bus 5 V in firmware. Leave the LAN base's separate DC input unconnected. Qualify whole-stack startup/current. |

Manufacturer product references: [CoreS3 SE](https://docs.m5stack.com/en/core/CoreS3-SE),
[Base LAN v1.2](https://docs.m5stack.com/en/base/Base_LAN_v1.2),
[Module13.2 Proto](https://shop.m5stack.com/products/proto-module-13-2).
The selected RF accessory specifications are
[CAB.628](https://www.taoglas.com/datasheets/CAB.628.pdf) and
[GW.11.A153](https://cdn.taoglas.com/datasheets/GW.11.A153.pdf).
The power supply SKU and output rating are documented in the
[Raspberry Pi product brief](https://datasheets.raspberrypi.org/power-supply/usb-c-power-supply-product-brief.pdf).

## Firmware boundary

This board does not execute the repository's Python service unchanged. It
needs ESP32-S3 firmware implementing the radio driver and the appliance
services. Current host software provides a behavioral reference; its observed
TCP port is 522 and its HTTP service defaults to port 8077.

The RF2401F20 is selected for its nRF24L01+ radio architecture, including the
250 kbps mode relevant to the working bladeRF path. SDR success does not itself
prove that this carrier's hardware packet engine will produce the required
packet-control fields, sequence behavior and burst timing. Capture and compare
the first article's actual transmission before claiming shade interoperability.
See the existing [RF protocol findings](../docs/rf-protocol.md) and
[bridge behavior](../docs/bridge-prototype.md).

Before distribution, freeze a tested firmware version with the PCBA and
system BOM. A populated board without that firmware is not a completed shade
bridge. New firmware belongs in its own component under the repository's
[firmware licensing policy](../LICENSING.md#firmware).

## Source and licensing

The [hardware licensing and attribution record](LICENSE.md) identifies the
original design and redistributed KiCad library scopes. Project-authored documentation in this directory follows the repository's
`CC-BY-SA-4.0 OR AGPL-3.0-or-later` documentation policy. CAD/generator licensing
is recorded in the relevant source files. Vendor reference documents remain
the vendors' material; citations and factual measurements do not transfer
their licenses. Do not include downloaded vendor PDFs in an outgoing source
package unless their redistribution terms permit it.
