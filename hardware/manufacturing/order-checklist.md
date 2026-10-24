<!--
SPDX-FileCopyrightText: 2026 Christopher Spitler
SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later
-->

# Supplier order and handoff checklist

Use this checklist to request a complete, repeatable carrier PCBA. The order
does not automatically include assembly of the purchased M5Stack products,
firmware programming, enclosure drilling or a functional shade-control test.
List those services separately if the same supplier is to perform them.

## Quote scope

- [ ] Identify board revision, quantity of bare boards, quantity assembled and
  number of first articles required before completing the remaining assembly.
- [ ] Include mixed SMT and M-Bus stacking-connector assembly in the quote.
  Confirm the connector supplier, pin length, body height and mating directions.
- [ ] Identify whether the NiceRF module is supplied by the assembler or
  consigned. Require the exact **RF2401F20** and traceable supplier/lot.
- [ ] Confirm module placement/reflow capability, moisture handling and
  inspection; do not assume a radio subassembly is an ordinary catalog IC.
- [ ] Include PCB finish, final thickness, stackup, RF impedance review and
  any coupon/report in the quoted board specification.
- [ ] Quote bare-board electrical test, PCBA inspection and carrier power test.
  Distinguish these from the complete firmware/RF acceptance procedure.
- [ ] State whether boards are delivered depanelized, fully cleaned and packed
  individually with the RF connector protected.
- [ ] State which assembly aids, tooling and surplus consigned parts are returned.

[PCBWay](https://www.pcbway.com/assembly-process.html) publishes a process for
PCB assembly using fabrication data, placement data and a BOM. It is a suitable
place to request a quote; only a reviewed quote establishes that it will source
and assemble this specific radio and stacking connector. Other assembly houses
can use the same package if they accept the defined components and process.

## Files supplied together

- [ ] Editable KiCad schematic and PCB, project configuration and any local
  symbols/footprints needed to open them without missing-library prompts.
- [ ] Generated Gerbers for every copper layer, both masks, relevant legends,
  paste layers and the board outline.
- [ ] Excellon plated and non-plated drill files and drill map.
- [ ] Fabrication drawing and [fabrication specification](fabrication.md),
  including the accepted layer stack and RF impedance target.
- [ ] Assembly BOM with reference designator, quantity, manufacturer, exact
  MPN, package, sourcing instruction and populate/do-not-populate status.
- [ ] Pick-and-place file with units, origin convention, side and rotation.
- [ ] Assembly drawings with pin-1 orientation, top/bottom views and connector
  mating directions; include radio and RF connector orientation.
- [ ] [Assembly instructions](assembly.md) and the agreed scope of the
  [acceptance procedure](acceptance-test.md).
- [ ] File checksums/release identifier, so the supplier can identify the exact
  files approved for manufacture.

This list follows the file categories in the manufacturer's
[submission guidance](https://www.pcbway.com/helpcenter/pcb_assembly_ordering/What_files_are_requested_for_assembly_production_.html).
Do not upload a screenshot or BOM alone and ask the factory to infer the circuit.

## No-substitution items

Require written engineering review before changing the radio module,
stacking connector, RF connector, antenna, coax assembly or regulator. For
passives, substitutions must retain the specified value, tolerance, voltage,
dielectric, package and relevant bias/temperature behavior; changing a nominal
capacitance to a smaller biased capacitance can affect the radio supply.

Never substitute a Core Basic/Core2 pin map for CoreS3 SE, or an earlier LAN
module for Base LAN v1.2. Preserve the separate radio supply and dedicated SPI
pins. Any approved change must be reflected in editable sources, BOM, outputs
and test records before it is used for another unit.

## First-article handoff

- [ ] Obtain DFM feedback and sourcing exceptions before manufacture.
- [ ] Review a module-placement drawing and header orientation before assembly.
- [ ] Receive photographs of both PCBA faces and the actual installed radio
  markings before approving the remainder of a lot.
- [ ] Fit the first assembled carrier in the purchased M032 frame with the
  intended CoreS3 SE and Base LAN; record clearance and screw lengths.
- [ ] Close the external antenna cable/connector and enclosure-drilling details
  in the system BOM and assembly drawing.
- [ ] Run the radio waveform and shade-operation qualification with the final
  firmware. Do not accept a generic radio test as proof of Platinum operation.
- [ ] Approve a repeatable release only after the acceptance record is complete.

## Repeat-build package

Freeze the approved PCBA BOM, appliance parts list, firmware image/source
identifier, programming method, serial-label format, test procedure and known-good
test limits. The supplier must report shortages or process changes before using
alternatives. Retain the editable project locally even if the supplier performs
layout corrections or manufacturing engineering; proprietary factory-only files
are not the sole source of this design.
