# Electrical design review — Rev A

Review date: 2026-10-24. Scope: primary-source pin assignments, native schematic connectivity, component operating limits and the proposed radio carrier interface. This is a design review, not evidence of a manufactured board or successful packet-radio shade control.

## Checked against primary sources

- **RF2401F20 V3.1 page 5:** the original symbol has 1=VCC, 2=GND, 3=CE, 4=CSN, 5=SCK, 6=MOSI, 7=MISO, 8=IRQ, 9=GND, 10=GND, 11=ANT. All three grounds reach GND; pin 11 alone reaches the U.FL signal terminal. Older contradictory antenna-pin tables were rejected.
- **RF2401F20 V3.1 page 6:** module dimensions, left 1.27 mm pitch, right RF pad offsets, and shield-up top-view orientation were read from the dimensioned drawing. Carrier lands are an explicitly documented engineering derivation. Sample-to-land verification remains necessary.
- **TLV755P SBVS320D page 3, DBV column:** U2 pin 1=IN, 2=GND, 3=EN, 4=NC, 5=OUT. Schematic pins agree. Input connects only to filtered regulated BUS_5V; EN connects HOST_3V3; output connects the distinct RF_3V3 net. NC has an explicit no-connect marker.
- **CoreS3-SE schematic sheets 3/6:** GPIO6/5/8/18/17/10 map to radio SCK/MOSI/MISO/CSN/CE/IRQ respectively. Their M5-Bus positions are 21/8/4/15/16/2. No classic-ESP32 GPIO numbering was carried into the CoreS3-SE design.
- **LAN-base physical M5-Bus table:** Ethernet reserves positions 7/9/11/10/22/26. The radio uses none of these. CoreS3-SE's existing GPIO35 LCD D/C versus Ethernet MISO sharing remains a firmware qualification requirement. GPIO14 audio use is disabled because it is reserved for LAN IRQ.
- **Supply design:** a 150 mA radio peak at nominal 5 V gives approximately 0.255 W regulator dissipation. This requires closed-enclosure thermal verification. EN, CE and CSN have explicit power-up defaults. No direct connection exists between host and radio 3.3 V rails.
- **Power setting:** the module's page-5 note requires power level 2 or below. Default setting 0 is documented. A hardware bill of materials does not authorize or validate every firmware power setting.

Source URLs, document hashes and dimensional reasoning are recorded in [electrical-evidence.md](../design/electrical-evidence.md) and [electrical-sources.json](../references/electrical-sources.json). Vendor documents are not redistributed.

## Native CAD checks

The schematic is generated from [board-spec.json](../design/board-spec.json) by [generate_schematic.py](../tools/generate_schematic.py), and includes editable original symbols plus a local library. U1 has power-input, digital-input, tri-state-output and interrupt-output pin types; U2 has actual power input/output and enable types. Passive connectors model the interface to the external host. Explicit power flags document externally supplied power and the filtered input rail. ERC severities were not suppressed.

KiCad 9.0.8 electrical-rule checking finished with **zero errors and zero warnings**. An independently parsed KiCad XML export found **65 connected component pins on 17 intended nets**, with **zero mismatches and zero unexpected connected pins** against the board specification. Native global labels preserve the same bare net names as the PCB. Unused stack-through contacts are explicitly no-connected from the carrier circuit; the connector itself still passes them through the stack.

Artifacts:

- [schematic-erc.rpt](schematic-erc.rpt): zero-error, zero-warning ERC result with local libraries present.
- [schematic-netlist.xml](schematic-netlist.xml): exported native KiCad netlist for independent comparison.
- [schematic-netlist-check.json](schematic-netlist-check.json): reproducible result from [check_schematic_netlist.py](../tools/check_schematic_netlist.py).
- [schematic-preview.pdf](../manufacturing/schematic.pdf): A3 schematic rendering, visually inspected for references, pin numbers, wire labels and notes.

## Remaining first-article evidence

No physical measurements were performed. Required evidence includes actual module and M5 header fit, host/bus power-path behavior, RF supply transients, closed-enclosure temperature, scope verification of SPI/default states, controlled-impedance fabrication confirmation, and real-shade over-the-air operation with the required nine-bit PCF and repeat timing. Disabling acknowledgment features without checking the transmitted frame can select an incompatible legacy framing mode. A packet-register recipe has not been validated by this electrical review.

Production release also requires demonstrating Ethernet/display ownership of GPIO35 under the selected library versions. The existing SDR demonstration and a clean schematic ERC do not replace that test.
