<!--
SPDX-FileCopyrightText: 2026 Christopher Spitler
SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later
-->

# Carrier fabrication specification

This specification accompanies the matching KiCad PCB, Gerbers and Excellon
drill files. All dimensions are millimeters. Where a submitted fabrication
setting disagrees with the source design, stop and resolve the discrepancy;
do not silently choose the cheaper setting.

## Build definition

The board is a replacement for the PCB inside a M5Stack M032 Module13.2 frame.
The released `Edge.Cuts` defines the finished board, including all cutouts.
The manufacturer's plastic enclosure dimensions are not the PCB dimensions.
Use the drill outputs to distinguish plated component holes from non-plated
mounting holes. Do not plate a non-plated mounting hole or add copper to its
mechanical clearance.

The requested stack is **JLC04161H-7628**, nominal 1.6 mm, with four copper
layers. A different fabricator may supply an equivalent verified stack, but
must return its dielectric and copper specification before the RF route is
released for manufacture.

| Parameter | Requirement |
| --- | --- |
| Layer count | Four: F.Cu / In1.Cu / In2.Cu / B.Cu |
| Finished thickness | Nominal 1.60 mm; request ±0.10 mm, subject to supplier acceptance and first-article connector fit |
| Laminate | FR-4 suitable for the selected lead-free assembly process |
| Copper | 35 µm outside; 15.2 µm inside per reference stack. Fabricator must state starting/finished copper and account for plating in the impedance calculation. |
| Finish | ENIG preferred for the radio module and miniature RF connector pads |
| Solder mask | Both sides; no mask in component pads or RF connector contacts. General minimum retained mask web is 0.10 mm, with the intentional J2 aperture described below. Have the fabricator verify the supplied openings. |
| Legend | White; artwork includes 0.65 mm minimum text height and 0.10 mm minimum stroke/clearance. Supplier must confirm readability/process capability; do not print on exposed pads, contacts or fiducials. |
| Electrical test | 100% bare-board netlist test; retain test results with the lot |
| Board profile | Routed `Edge.Cuts`, including inside radii as drawn; no rectangular substitution |
| Drills | Separate plated and non-plated drill definitions from the CAD exports |
| Panelization | Fabricator may propose a panel; final board profile and functional copper must remain unchanged |
| Assembly quality | Request the assembler's normal IPC-A-610 Class 2 workmanship inspection and state exceptions in the quote |

The reference layer construction is:

| Layer/material, Core-facing top to LAN-facing bottom | Thickness | Relative permittivity used in reference |
| --- | ---: | ---: |
| L1 F.Cu | 0.0350 mm | — |
| 7628 prepreg | 0.2104 mm | 4.4 |
| L2 In1.Cu | 0.0152 mm | — |
| FR-4 core | 1.0650 mm | 4.6 |
| L3 In2.Cu | 0.0152 mm | — |
| 7628 prepreg | 0.2104 mm | 4.4 |
| L4 B.Cu | 0.0350 mm | — |

The sum is 1.5862 mm before the fabrication process's finished-thickness
definition. The supplier must quote the resulting finished thickness rather
than treating this arithmetic sum as a zero-tolerance specification. Values
come from JLCPCB's [published impedance stackup](https://jlcpcb.com/impedance).

All SMT parts and the RF route are on **B.Cu/L4**, facing into the M032 ring.
In2.Cu/L3 is their adjacent reference plane. The M-Bus connector is through-hole,
with its female body on the bottom and its male tails projecting from the top.

The source design's general electrical limits are 0.20 mm track/clearance,
0.50 mm copper-to-board-edge clearance, 0.60 mm via diameter with 0.30 mm drill,
0.15 mm minimum via annulus and 0.25 mm hole clearance. The ANT-net rule instead
requires a 0.35 mm trace and 0.50 mm clearance. These limits describe the checked
CAD; they do not replace a supplier's tolerances for its etching, drilling and
registration processes. If the supplier cannot retain the requested mask web
or legible 0.65 mm text, return a documented DFM change for source revision.
The native PCB specifies 0.05 mm general pad-to-mask expansion and a 0.10 mm
minimum mask web; preserve local footprint openings in the exported mask layers.

J2 has one intentional footprint-specific mask exception. The original Hirose
land pattern includes a rectangular mask opening beneath the connector close
to its signal pad. Its copper keepout prevents unrelated copper in that area.
The project enables **allow solder-mask bridges only within J2** to preserve
that opening; the general mask-bridge rule remains enabled elsewhere. The
local footprint changes only that allowance, not its pad or keepout geometry.
The assembler/fabricator must review this aperture against the Hirose drawing
and its paste process. Do not fill the copper keepout or extrapolate this
exception to other parts.

## RF section

The path from the RF2401F20 ANT pad to the external-coax connector is a
single-ended **50 ohm** RF path at 2.4 GHz. It depends on the copper geometry,
dielectric stack and ground return. A generic PCB thickness selection is not
an impedance specification.

Before fabrication, the supplier must confirm the final stackup and calculated
impedance of the actual RF geometry. Target 50 ohms ±10%. If the supplier's
standard stackup does not meet the design, return the required trace-width or
gap adjustment for a source-CAD revision. Do not modify only the Gerber files.
Record the accepted dielectric thickness and material assumptions in the lot
traveler. Quote an impedance coupon if the manufacturing process needs one.

Revision A starts with a **0.35 mm** RF trace on B.Cu and **0.50 mm** clearance
to coplanar ground, referenced to In2.Cu across 0.2104 mm prepreg. These are
layout inputs, not a measurement proving 50 ohms. Include solder mask, final
copper thickness, connector launch and the local ground geometry in the
supplier's review. The impedance target controls if a justified geometry
adjustment is needed.

Preserve the reference ground plane and stitching vias around this path. Do
not add plane splits, thermal isolation in the RF return, test stubs, text,
copper balancing features or panel tabs within the RF region. Keep the
module-to-connector RF route and its ground clearance as drawn. Do not replace
the RF connector with a visually similar alternative.

The NiceRF module already contains its radio and RF matching circuitry. The
carrier's RF feed is an interconnect to its 50 ohm antenna port, not a new
discrete nRF24 antenna-matching network.

## Manufacturing review

Review the complete stackup, drill chart, annular rings, solder-mask webs,
castellated module lands and connector pads before committing a panel. A DRC
report checks the designed rules; it does not replace the fabricator's process
review or a physical fit check.

For a panel, place breakaway features outside the completed board outline.
Keep tabs, tooling holes and fiducials clear of the RF connector, M-Bus mating
area and enclosure seating edges. Return a panel drawing for review. Supply
depanelized boards unless the assembly process explicitly calls for panel
delivery, and remove breakaway burrs without reducing the specified outline.

Tented vias may be used where specified by the solder-mask layers. Any via
filling, solder-mask change, stencil reduction, solder thief or footprint
adjustment proposed during DFM must be documented. Do not place exposed solder
features where they could short to the underside of the radio module.

## Required supplier outputs

Return the approved stackup, impedance calculation/report where ordered,
final panel drawing, bare-board electrical-test result, DFM deviations and lot
identification. If the supplier edits the design, return matching editable
KiCad sources and regenerated manufacturing outputs; a corrected Gerber set
alone is not sufficient for a repeatable release.

For the complete file list, see the [supplier checklist](order-checklist.md).
PCBWay's [assembly-file guidance](https://www.pcbway.com/helpcenter/pcb_assembly_ordering/What_files_are_requested_for_assembly_production_.html)
describes Gerber, BOM, placement and orientation requirements; it does not
constitute acceptance of this particular design or its components.
