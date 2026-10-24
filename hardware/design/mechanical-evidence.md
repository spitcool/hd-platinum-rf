<!--
SPDX-FileCopyrightText: 2026 Christopher Spitler
SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later
-->

# M032 carrier mechanical evidence

Reference review: 2026-10-24. Units are millimetres. This document records source geometry and fit checks; the released PCB and fabrication drawing control manufacturing dimensions.

## Coordinate convention and source

The carrier replaces the perforated PCB inside the **M5Stack M032 Module13.2 Proto** ring. It is not a 54 mm PCB. The manufacturer publishes a nominal **50 × 50 mm PCB outline**, with 2 mm corner chamfers and two shallow notches on one edge, in [Module13.2_Proto_Board.PcbDoc](https://github.com/m5stack/M5_Hardware/blob/e29c139cbc7c80b5ccc5557e5ab8025a7a19a109/Common/Module13.2/Footprints/Module13.2_Proto_Board.PcbDoc).

The coordinates below use the manufacturer's PCB top view: the M5-Bus is on the **right**, the two edge notches are at the **top**, X increases right and Y increases down. The nominal upper-left board corner is (0, 0). This top side faces the CoreS3 SE when installed; the bottom side faces into the M032 ring toward Base LAN. A drawing of the underside must mirror X, rather than simply reuse this view.

The factual coordinate set is also available in [module132-mechanical.json](module132-mechanical.json). Coordinates were extracted from the Altium binary primitives, translated from its origin `(3705 mil, 2930 mil)` to the nominal board upper-left corner, and rounded to the precision of the nominal construction. No product photograph was scaled to infer hole coordinates.

## PCB outline

Use this closed polygon, traversed clockwise from the upper-left chamfer endpoint:

```text
(2,0), (8.5,0), (9.5,1), (12.5,1), (13.5,0),
(36.5,0), (37.5,1), (40.5,1), (41.5,0), (48,0),
(50,2), (50,48), (48,50), (2,50), (0,48), (0,2), (2,0)
```

These are the source's explicit mechanical outline track centres. Its automatically generated board-region polygon includes approximately 0.05 mm outward offsets and very short corner segments. Those numerical artefacts are not additional mounting clearance requirements. Do not use the 54 mm enclosure outline for Edge.Cuts.

The manufacturer's [M032 dimension drawing](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/982/module132proto.pdf) shows a nominal 54 × 54 × 13.2 mm housing, R5 exterior corners, 44 mm stack-hole pitch and a 3.1 mm housing through-hole. The [product specification](https://docs.m5stack.com/en/module/Module13.2_Proto) lists 54.2 × 54.2 × 13.2 mm. This 0.2 mm envelope difference is a source discrepancy; neither number specifies the internal PCB pocket tolerance.

## Hole centres and keepouts

| Feature | Centres in the defined top view | Manufacturer PCB hole diameter |
| --- | --- | --- |
| Stack screw passages | (3,3), (47,3), (3,47), (47,47) | 3.00 |
| M032 PCB retention | (7,3), (43,3), (7,47), (43,47) | 1.80 |

The source places paired stack/retention holes inside capsule-shaped keepout marks: the capsules span X=3..7 or X=43..47 and are centred at Y=3 or 47; nominal radius is 1.8 mm, except the top-right mark uses 1.75 mm. Reserve the larger 1.8 mm envelope for components. A wider copper/screw-head keepout in the carrier is an intentional design allowance, not a source dimension.

The source encodes these mechanical holes as pads with copper diameter equal to drill diameter. For the new board, use intentional **NPTH mechanical holes** with suitable copper clearance. Hole diameter changes, including enlarging stack passages to 3.2 mm, must be explicit on the fabrication drawing. The original PCB's nominal 3.0 mm passage and the housing drawing's 3.1 mm passage are distinct facts.

Retain the M032's four supplied **M2 × 5 mm self-tapping screws** for fastening the replacement PCB to the original plastic bosses. They are not M2 machine screws and are separate from the M3 screws that secure the complete stack. [M032 contents](https://docs.m5stack.com/en/module/Module13.2_Proto)

## M5-Bus geometry and orientation

The connector has 15 paired positions on 2.54 mm pitch. Its electrical row centres are X=**42.78** and **45.32**. Y is **7.22 + 2.54k**, where k=0..14. First-to-last position span is 35.56 mm; centre is (44.05,25.00).

In this top view:

- The **outer/right row, X=45.32, is odd-numbered**: pin 1 at Y=7.22, pin 29 at Y=42.78.
- The **inner/left row, X=42.78, is even-numbered**: pin 2 at Y=7.22, pin 30 at Y=42.78.
- Confirm pin 1 with GND continuity before mating. The old M032 CAD has GND on the outer row at its first three positions, +3.3 V on the inner sixth position and +5 V on the inner fourteenth position; these agree with the [CoreS3 SE M5-Bus pin assignment](https://docs.m5stack.com/en/core/CoreS3-SE).

Do not copy a generic two-row footprint's numbering without checking this orientation. Manufacturer pin tables drawn looking into a socket may place the odd row on the left. A view reversal does not alter electrical pin numbers.

### Specified connector

Use **M5Stack A089, Bus Socket DIP 13.2**, one connector per carrier; it is sold as a ten-piece pack. Manufacturer dimensions are 2×15 contacts, 2.54 mm pitch, 9.5 mm plastic body length, 6.6 mm tails and approximately 39 × 5 × 16 mm overall. [Manufacturer specification](https://docs.m5stack.com/en/accessory/Bus_Socket_DIP_13.2), [order page](https://shop.m5stack.com/products/2-15-pin-header-socket-for-13-2-module-10pcs).

Install its **female housing on the PCB bottom side toward Base LAN**. Tails pass through the PCB and project upward toward the CoreS3 SE socket. Do not trim the mating tails during soldering. This orientation follows the M032 assembly, where the PCB sits near the top of the ring and the long female housing occupies the ring interior.

The reference PCB's contact holes are 0.85 mm except the first and last paired positions, which are 0.75 mm; its copper lands are 1.3 mm. A uniform larger finished drill/land in the new design is a deliberate fabrication choice and needs an A089 sample or supplier drawing to verify the actual terminal section. The retail specification does not provide terminal cross-section tolerances, contact wipe or minimum insertion depth.

**A117 is a different SMD socket-and-pin set**, with a documented 9.2 mm female plastic body and separate 3.0 mm male header. It is not a drop-in BOM substitute for A089. [A117 specification](https://docs.m5stack.com/en/accessory/Bus_Socket_SMD_13.2)

## Component side, enclosure and cable

The volume intended for circuitry is below the M032 PCB, inside the 13.2 mm ring. Prefer radio, decoupling and coax connector on that inward face. A design that places them on the Core-facing surface must independently verify the CoreS3 SE underside cavity; the ring's external height does not provide 13.2 mm of clearance above the PCB.

The 9.5 mm connector body gives a useful relative height reference, but it is not a guaranteed free-height measurement over the entire board. Keep components and the mated coax plug below the connector body's inner extent where possible. Cable bend radius, insulation, solder fillets, the Core underside and Base LAN protrusions must be included in a sample fit check.

Use a bulkhead RF connector and flexible 50-ohm coax pigtail for the external antenna. The bulkhead must carry antenna torque; the tiny PCB RF connector must not carry it. Route the pigtail away from the screw passages and Ethernet assembly and provide strain relief. No M032 wall-hole diameter or location is released by this evidence: the ring has existing connector openings, internal ribs and split-line geometry that require inspection against the actual selected bulkhead body and nut. Do not blindly drill the centre of a ring wall or assume the older Base LAN antenna opening exists unchanged in K012-B-V12.

The specified pigtail is **Taoglas CAB.628**, a 95 mm, 1.13 mm diameter, 50-ohm cable with a right-angle I-PEX MHF I plug (U.FL compatible) and an RP-SMA female bulkhead. It mates with the selected **Taoglas GW.11.A153 RP-SMA male antenna**; do not substitute a standard SMA bulkhead. [CAB.628 product](https://www.taoglas.com/product/cab628-ipex-mhfiu-fl-to-95mm-1-13-cable-to-rp-smafbkst/)

The [CAB.628 drawing](https://www.taoglas.com/datasheets/CAB.628.pdf), revision SPE-12-8-152/E/WY, specifies a D-shaped mounting hole: 6.5 mm nominal circle diameter, truncated so the span from the opposite circular edge to the flat is **6.00 +0.08/−0.00 mm**. Its washer outside diameter is **10.2 ±0.6 mm**, its nut is **8 mm across flats**, and its connector thread is **1/4-36 UNS-2A**. Reserve the full washer and tool-access envelopes. These are connector interface dimensions; the **hole centre on the M032 housing remains a sample-fit decision**. Cable length is 95 ±2.5 mm between the manufacturer's illustrated datums, not the full end-to-end metal assembly length.

The [current GW.11.A153 datasheet](https://cdn.taoglas.com/datasheets/GW.11.A153.pdf), revision H dated 2026-08-31, gives an approximately **84.4 × 7.8 mm** antenna envelope and an adjustable 90-degree hinge. Allow the antenna to articulate without striking the Core or covering its screen. Its latest measured peak gain varies with orientation and ground-plane setup, reaching 3 dBi; do not carry the older 2.3 dBi value into an RF power budget without checking the actual antenna revision and installed measurement.

## Required mechanical acceptance before production release

1. Fit the unpopulated carrier to an actual M032 ring; confirm the notches, all eight holes and retention screws without forcing or bending the PCB.
2. Measure the supplied M032 board thickness and its seat position. The published Altium dielectric metadata is not a reliable specification for finished PCB thickness. Verify the new board's specified thickness preserves header engagement and ring closure.
3. Fit A089 and the complete CoreS3 SE / M032 / Base LAN v1.2 stack. Record male protrusion, socket insertion and gap at every seam. Confirm all 30 contacts, especially GND, 5 V and signal rows, before power.
4. Check the populated board, coax plug and pigtail for clearance and strain. Confirm access for snapping the coax connector on without loading the radio shield or other parts.
5. Select whole-stack M3 screw lengths from measured engagement. The [M5Stack screw guide](https://docs.m5stack.com/en/guide/basics/stack_screw_length) gives different CoreS3 lengths on opposite sides and states that tabulated values are reference values. Its Base15/Base26 tables are not a verified K012-B-V12 screw specification. Do not use longer screws to pull an unseated connector together.
6. Freeze a dimensioned enclosure modification drawing, bulkhead hardware and cable length after the sample closes without pinching. Photograph the accepted cable route and record the fastener selections in the build traveller.

The selected commercial enclosure parts are compatible by product family; a mechanically assembled sample has not yet been inspected for this carrier revision.
