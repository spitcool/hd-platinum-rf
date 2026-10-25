<!--
SPDX-FileCopyrightText: 2026 Christopher Spitler
SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later
-->

# Carrier and appliance assembly

The [final assembly drawing](final-assembly.pdf) shows the three enclosure
layers and the carrier's orientation inside M032. The
[illustrated guide](final-assembly.md) identifies the parts and assembly sequence.

Use the assembly BOM, placement file and drawings from the same board revision.
Reference designators and pin-1 markers in the CAD control component orientation.
Photographs of a different nRF24 module or another M5Stack carrier do not.

## PCBA order scope

The carrier needs surface-mount assembly and a separately controlled M-Bus
stacking-connector operation. The supplier must explicitly accept the exact
radio module and connector assembly in its quote. A listing in a component
distributor's catalog does not guarantee automated placement, reflow or
through-hole assembly availability.

Use the specified **NiceRF RF2401F20**. Do not substitute RF2401PRO, an
unbranded nRF24L01 board, a pin-compatible clone, a 2.4 GHz LoRa module or a
generic Wi-Fi/Bluetooth module. The footprint, external antenna arrangement,
power behavior and packet-engine capabilities form part of this design.

The RF2401F20 is a castellated subassembly. Confirm the manufacturer's
permitted assembly profile and storage/moisture handling with the module
supplier before reflow. An arbitrary profile suitable for the small passives
is not proof that the module can tolerate the same process. Inspect every
module ground joint and the antenna joint for wetting, bridging and alignment.

Use the exact miniature RF connector MPN in the BOM. Its mechanical mating
height and pad geometry matter. Apply its maker's soldering and mating
instructions. Keep flux residue, glue and conformal coating out of the
connector; do not use the coax cable as a handle to lift the PCBA.

## Orientation and stacking connector

**All SMT parts are on B.Cu, facing down into the M032 ring toward Base LAN.**
The Core-facing F.Cu surface carries the protruding M-Bus tails. U1's shield
faces outward from the PCB toward the LAN base. J2 is the specified Hirose
`U.FL-R-SMT-1(10)` connector, mounted on the same bottom face.

J1 is **M5Stack A089**, Bus Socket DIP 13.2, one connector from a ten-piece
retail pack. Its female housing is on the bottom; its tails pass through the
PCB toward CoreS3 SE. Nominal housing height is 9.5 mm and tail length 6.6 mm.
The M-Bus connector passes all 30 contacts through to the LAN base, including
contacts not used by the radio. Do not substitute A117, which is a different
socket-and-header system.

In the PCB top view with the two edge notches at the top, J1 is at the right
edge and pin 1 is in the outer row at X=45.32, Y=7.22 mm from the nominal
upper-left board corner. A bottom assembly view mirrors that layout. Verify
pin 1's GND connection before mating; see the
[mechanical evidence](../design/mechanical-evidence.md).

Fit the stacking connector squarely using a jig or an unpowered mating sample.
Do not leave the expensive CoreS3 SE or LAN base connected during soldering.
Check the finished connector for solder intrusion into receptacles, bent pins,
bridges and full insertion depth. Do not trim pins until the released mechanical
drawing specifies the retained length.

If a connector is salvaged from an M032 board for a first article, identify that
unit in the traveler and inspect the contacts after removal. A production lot
needs a repeatable connector source and validated mounting process; salvaged
connectors are not an automatic production substitute.

## Enclosure and coax assembly

1. Remove power from every part of the stack. Remove the M032 perfboard and
   retain its Module13.2 frame and four M2 × 5 mm self-tapping PCB retention
   screws. Those screws go into the original plastic bosses; they are separate
   from the complete stack's M3 fasteners. Do not stack the new PCB on top of
   the perfboard.
2. Dry-fit the empty carrier into the frame. Confirm that no board edge,
   solder joint or component touches a plastic rib, screw boss or adjacent
   board. Record the measured clearance around the radio and coax plug.
3. Fit the external antenna bulkhead to the approved enclosure wall or mounting
   bracket. Its exact hole position is an enclosure-specific dimension and
   must be frozen from the first article's fit drawing before batch drilling.
   Remove the electronics before drilling and clear all chips before reassembly.
4. Install the **Taoglas CAB.628** 95 mm, 1.13 mm coax pigtail. Its I-PEX MHF I
   plug mates with J2; its RP-SMA female end is the bulkhead. Seat its board-end
   plug vertically and route it without a sharp bend at the plug. Observe the cable maker's minimum
   bend radius. Keep the cable clear of board edges, screw paths and contacts.
5. Secure the cable near the bulkhead so antenna movement cannot pull on the
   miniature board connector. Keep adhesive and the strain relief away from
   the RF route, module pads and serviceable connectors. Do not crush the coax.
6. Assemble CoreS3 SE → Module13.2 carrier layer → Base LAN v1.2. Align the
   M-Bus pin-1 orientation before applying pressure. All case shoulders must
   seat naturally without flexing the boards or using screws to force them shut.
7. Fit the verified stack screws. Confirm that each screw clamps its intended
   stack before bottoming out and does not reach a PCB or component. Record
   screw lengths by location in the released system BOM.
8. Install the **Taoglas GW.11.A153** RP-SMA male antenna. Check both the threaded coupling and
   center contact: an SMA plug and an RP-SMA jack can appear to screw together
   while leaving the RF center contact unmatched.
9. Perform the powered acceptance test before fitting any tamper label or
   packaging the appliance.

For the selected US appliance power arrangement, connect the Raspberry Pi
SC0218 supply to the CoreS3 SE USB-C port and leave the LAN base DC input
unconnected. Firmware must enable the Core's M-Bus 5 V output for the LAN base
and carrier. The supply's 3 A rating does not itself prove the Core's power
path can deliver that current downstream; measure the complete stack's demand
and startup behavior during qualification.

M5Stack documents different CoreS3 screw-length contributions at different
positions. Its [stack screw reference](https://docs.m5stack.com/en/guide/basics/stack_screw_length)
is a starting point; the exact CoreS3 SE + custom carrier + LAN base combination
must be measured rather than inferred from a different base.

Use the vendor's [CAB.628 drawing](https://www.taoglas.com/datasheets/CAB.628.pdf)
for the bulkhead body and recommended mounting-hole shape. That drawing
specifies the connector hole, not a collision-free hole position in the M032
wall. The [antenna drawing](https://cdn.taoglas.com/datasheets/GW.11.A153.pdf)
specifies the selected mating part.

## Inspection and records

Retain an image of each face of the first assembled board and images of the
completed stack showing the header engagement and coax routing. Record the
PCB revision, radio module lot/markings, firmware identifier, antenna/pigtail
MPNs, power arrangement and acceptance-test result against each unit serial.
Do not claim the complete appliance inherits a module's certification solely
because that module appears in the BOM.
