# Carrier electrical design evidence

Design date: 2026-10-24. Intended stack: **M5Stack CoreS3-SE K128-SE**, custom carrier in **M032**, and **Base LAN v1.2 K012-B-V12**. Radio: **NiceRF RF2401F20**, current V3.1 pin numbering. This document records the design inputs and engineering decisions; the released schematic/netlist and BOM define the actual assembled revision.

The existing project has demonstrated SDR transmissions to a shade. It has not yet demonstrated this packet-radio implementation or this assembled carrier. A matching 2.4 GHz frequency alone does not establish protocol compatibility. Hardware bring-up and over-the-air acceptance remain release conditions.

## 1. Signal allocation and host compatibility

The companion [pin-assignment.csv](pin-assignment.csv) uses **physical M5-Bus pin numbers**, not the older ESP32 Core GPIO labels printed in the LAN-base schematic. Numbers 1/2, 3/4, etc. are opposing positions in a two-row connector; do not renumber them as consecutive positions along one row.

| Carrier function | CoreS3-SE GPIO | Physical M5-Bus pin | RF2401F20 pin |
| --- | ---: | ---: | ---: |
| RF SCK | 6 | 21 | 5 |
| RF MOSI | 5 | 8 | 6 |
| RF MISO | 8 | 4 | 7 |
| RF CSN, active low | 18 | 15 | 4 |
| RF CE, active high | 17 | 16 | 3 |
| RF IRQ, active low | 10 | 2 | 8 |
| Radio regulator input | — | 28, regulated 5 V | — |
| Regulator enable reference | — | 12, host 3.3 V | — |
| Ground | — | 1, 3, 5 | 2, 9, 10 |

This allocation follows the manufacturer's [CoreS3-SE M5-Bus table](https://docs.m5stack.com/en/core/CoreS3-SE) and was cross-checked against sheets 3 and 6 of the [CoreS3-SE v1.0 schematic](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/498/Sch_M5_CoreS3_SE_v1.0.pdf). Those six GPIOs connect to the corresponding bus nets; GPIO8/17/18 also carry the documented Port B/C functions. Reserve Port B/C for this carrier and do not attach external accessories on those signals.

Use a dedicated ESP32-S3 general-purpose SPI controller for the radio. Reserve the other controller and the existing M5 bus for the LCD/Ethernet path. Flash/PSRAM SPI buses are not available for this purpose. The carrier must pass all 30 M5-Bus contacts through without remapping, while tapping only the documented carrier nets. Pins 25/27/29 are not ground: the LAN base identifies them as HPWR. Leave them electrically distinct from ground and 5 V.

The LAN base occupies physical pins 7/9/11/10/22/26, which translate to **MOSI37, MISO35, SCK36, CS9, RST7, IRQ14** on this host. These assignments come from the [LAN-base physical bus table](https://docs.m5stack.com/en/base/Base_LAN_v1.2). Its GPIO23/19/18/26/13/34 table instead describes an older ESP32 host. Its linked 2018 schematic is similarly legacy-labelled; it is not a CoreS3 GPIO guide.

### Shared LCD/Ethernet signal qualification

**GPIO35 is both LCD D/C and SPI MISO.** This is explicit in the CoreS3-SE schematic and LCD/microSD table; it must not be treated as an ordinary permanently-input MISO when the screen is active. M5Stack's [CoreS3 + Base LAN example](https://docs.m5stack.com/en/arduino/projects/base/base_lan_v1.2) uses GPIO36/35/37/9 with M5Unified and its M5-Ethernet library. That example is useful integration evidence, not proof of contention-free concurrent display and Ethernet activity in our firmware.

Release firmware must serialize the display and LAN transactions, deselect the other SPI device, and switch GPIO35 direction/ownership correctly. Keep the SD socket empty and disable SD, speaker and microphone drivers during initial network/radio qualification; GPIO14 is reserved for LAN IRQ. A firmware/library combination must pass the simultaneous LAN + display acceptance test before enabling screen updates in a distributed build. A headless network mode may leave LCD CS inactive and GPIO35 as input. The separate radio SPI bus avoids adding another device to this issue.

Do not fit the LAN base's optional RS232/RS485 adapter modules for this product. Keep their selector switches disconnected from shared bus signals.

## 2. RF2401F20 pinout and footprint derivation

Primary reference: [NiceRF RF2401F20 V3.1, April 2022 revision, pages 4–6](https://www.nicerf.cn/uploads/20240130/RF2401F20%202.4GHz%20%E8%BF%87CE%20FCC%20IC%20TELEC%E8%AE%A4%E8%AF%81%20%E6%97%A0%E7%BA%BF%E6%94%B6%E5%8F%91%E6%A8%A1%E5%9D%97V3.1.pdf). The datasheet was retrieved and its dimensioned drawing visually checked on the design date. **Do not use older pin tables that call pin 9 ANT: current numbering is 11 ANT, 9/10 GND.**

Coordinates below use the component **top view, shield up**, origin at the upper-left module-body corner, positive x right and positive y down. The body is 20.00 × 13.02 mm, each dimension ±0.15 mm; overall height is 2.1 ±0.1 mm. The module PCB is nominally 1.0 mm thick. These are component dimensions, not enclosure clearances.

| Pin | Function | Module edge | y center, mm | Module land width × height, mm |
| ---: | --- | --- | ---: | --- |
| 1 | VCC | Left | 2.00 | 1.65 × 1.00 |
| 2 | GND | Left | 3.27 | 1.65 × 1.00 |
| 3 | CE | Left | 4.54 | 1.65 × 1.00 |
| 4 | CSN | Left | 5.81 | 1.65 × 1.00 |
| 5 | SCK | Left | 7.08 | 1.65 × 1.00 |
| 6 | MOSI | Left | 8.35 | 1.65 × 1.00 |
| 7 | MISO | Left | 9.62 | 1.65 × 1.00 |
| 8 | IRQ | Left | 10.89 | 1.65 × 1.00 |
| 9 | GND | Right | 10.68 | 1.59 × 1.36 |
| 10 | GND | Right | 3.53 | 1.59 × 1.36 |
| 11 | ANT | Right | 1.53 | 1.59 × 1.36 |

The left pitch is 1.27 mm. The drawing locates the left plated-hole centers at x=0.93 mm and the right centers at x=19.20 mm: 18.27 mm between hole-center columns. These are **holes in the radio module**, not a drilling requirement for the carrier.

Our carrier land pattern is an engineering derivation, not a manufacturer-issued recommended footprint: left rectangular SMD pad centers x=0.40 mm, width 2.50 mm, height 1.00 mm; right centers x=19.60 mm, width 2.50 mm, height 1.36 mm. Use the y coordinates above. Each land extends 0.85 mm outside its module edge for an inspectable solder fillet. Pin 1 must have an unmistakable assembly mark. Verify footprint polarity and dimensions against a purchased current-production module before board release; NiceRF has revised pin labels and dimensions in previous datasheet revisions.

Connect every radio ground terminal. Use a continuous ground plane below the radio and masked surface ground where practical. The module underside is not an exposed thermal pad: do not add a large paste aperture under it. Keep under-module vias tented or filled and solder-mask covered, and prohibit exposed unrelated copper or test pads under the module. These choices implement the grounding and underside-insulation cautions on datasheet page 5.

## 3. Dedicated radio power

The radio rail is separate from the host's 3.3 V supply. Design chain:

```text
M5-Bus 28 / 5 V -> input filter -> local input capacitors
                                  -> TLV75533PDBVR -> RF_3V3 -> RF2401F20 VCC
M5-Bus 12 / host 3.3 V -----------> regulator EN (logic input only)
M5-Bus 1,3,5 ---------------------> common ground
```

The suggested regulator is [TI TLV75533PDBVR](https://www.ti.com/product/TLV755P/part-details/TLV75533PDBVR), fixed 3.3 V, SOT-23-5. Pin 1=IN, 2=GND, 3=EN, 4=NC, 5=OUT. Its input range extends to 5.5 V and nominal current capability is 500 mA; actual dissipation/temperature still limits continuous current. Never apply the base's 9–24 V input directly to this regulator. Never connect its output to M5-Bus pin 12.

Recommended implementation: input [Murata BLM18AG601SN1D](https://www.murata.com/en-us/api/pdfdownloadapi?cate=cgsubChipFerriBead&partno=BLM18AG601SN1%23), 0603, 600 Ω at 100 MHz, 500 mA, maximum DCR 0.38 Ω. Put 10 µF and 100 nF immediately after it near IN/GND. Place 10 µF at OUT/GND, plus 47 µF bulk and 100 nF at the radio VCC/GND pair. Use X5R/X7R capacitors rated at least 10 V and check effective capacitance at 3.3/5 V. The input filter is before the LDO; do not separate the LDO output from all its local stabilizing capacitance with a ferrite.

The [TI datasheet](https://www.ti.com/lit/ds/symlink/tlv755p.pdf) requires effective output capacitance above 0.47 µF and recommends 1–200 µF nominal output capacitance, accounting for DC-bias derating. The proposed bulk values are design choices to be qualified by transient measurements. At a 150 mA radio load, the LDO dissipates approximately (5−3.3)×0.15=0.255 W. Provide useful ground copper and thermal vias near its GND pad; validate temperature in the closed enclosure. Its 500 mA headline is not permission to draw 500 mA continuously from this enclosed design.

Selected passive components were checked against current manufacturer product pages; board-spec.json and the assembly BOM contain the complete purchase list:

| References | Exact part | Manufacturer specification |
| --- | --- | --- |
| C1, C3 | Samsung CL21A106KAYNNNE | [10 µF, 25 V, ±10%, X5R, 0805; maximum height 1.45 mm](https://product.samsungsem.com/mlcc/CL21A106KAYNNN.do) |
| C2, C5 | Samsung CL10B104KB8NNNC | [100 nF, 50 V, ±10%, X7R, 0603; maximum height 0.90 mm](https://product.samsungsem.com/mlcc/CL10B104KB8NNN.do) |
| C4 | Samsung CL31A476MPHNNNE | [47 µF, 10 V, ±20%, X5R, 1206; maximum height 1.80 mm](https://product.samsungsem.com/mlcc/CL31A476MPHNNN.do) |
| R1–R5 | Yageo RC0603FR-0733RL | [33 Ω, ±1%, 0.1 W, 0603](https://yageogroup.com/component-documentation/download/specsheet/RC0603FR-0733RL) |
| R6–R9 | Yageo RC0603FR-07100KL | [100 kΩ, ±1%, 0.1 W, 0603](https://yageogroup.com/component-documentation/download/specsheet/RC0603FR-07100KL) |

Catalog references include JLC/LCSC C15850 (C1/C3), C1591 (C2/C5), and C96123 (C4). Their stock and assembly eligibility must be checked against the actual order; the presence of an LCSC listing does not reserve parts or establish JLC assembly availability. These SKUs preserve sensible MLCC voltage margin rather than treating nominal capacitance alone as the qualification criterion.

Pull EN down with 100 kΩ and drive it from the host 3.3 V reference so the radio is disabled when the host rail disappears. EN must never float. The selected appliance supply is the Raspberry Pi SC0218 USB-C 5.1 V/3 A supply into CoreS3-SE, with its M5-Bus 5 V output enabled; leave the LAN-base DC input unused. Configure the PMIC power-path state accordingly. Keep CSN high-impedance until RF_3V3 is stable; its radio-rail pull-up establishes the idle level. CE, SCK and MOSI remain low or high-impedance during power-up. Then enable the driven idle levels and SPI. Do not drive an unpowered radio through its GPIO protection structures. Do not enable a conflicting bus-output mode into an externally powered bus.

## 4. Logic defaults and firmware contract

Use 100 kΩ CE-to-ground and 100 kΩ CSN-to-RF_3V3 resistors, placed on the radio side of any series resistors. A 100 kΩ SCK pulldown is useful. Fit 33 Ω series damping resistors on SCK, MOSI, CSN and CE near the bus tap; fit the MISO series resistor near the radio. Values may change only after scope verification. IRQ is an active-low interrupt output; no 5 V pull-up is permitted. All signal levels are 3.3 V.

After power-up sequencing, initialize CE low, CSN high, SCK low. Start SPI at 1 MHz, mode 0; increase only after register/readback and waveform qualification. Radio initialization must preserve the project's nine-bit packet-control field and verified payload/waveform. Acknowledge/retry configuration needs an over-the-air experiment: blindly disabling EN_AA can select a legacy ShockBurst framing mode that omits that field. Establish a register configuration that produces exactly the required packets and no unwanted retries; do not rely on driver defaults. The driver must own the dedicated radio SPI instance and must not silently revert to the global Ethernet/display SPI bus.

The manufacturer's page-5 note states: “模块的功率等级要设到2或者2以下。” This means the module power-level setting must be **2 or below**. Default to **RF_PWR=0**; do not enable level 3 merely because the module advertises 20 dBm. The table associates level 0 with approximately 5 dBm module output. The Nordic bare-chip power setting is not the amplified module's final output power. Verify the selected setting and antenna with the completed assembly.

Datasheet reference consumption is RX 23.5 mA typical / 24 mA maximum and TX 135 mA typical / 150 mA maximum at the advertised 20 dBm point. Design the supply for that conservative peak even though the default permitted operating setting is lower. Actual output power/current must be measured; do not infer intermediate power levels by linear interpolation.

## 5. RF connector and controlled impedance

Connect module pin 11 to the specified genuine Hirose **U.FL-R-SMT-1(10)** receptacle using the [Hirose land-pattern drawing](https://www.hirose.com/product/download/?distributor=all&lang=en&series=U.FL&type=catalogue). The suffix identifies an ordering/packaging variant; acceptance of another suffix requires confirming the same land pattern and connector geometry. The connection must be U.FL/MHF-I size, not the smaller MHF4 family. Maintain the connector's own copper keepout and solder-paste dimensions.

The components face down into the M032 frame. Use a short, stub-free 50 Ω trace on **B.Cu / L4 over continuous In2.Cu / L3 ground**, with the connector close to module ANT. No RF vias, test pads, unpopulated matching stubs or branches are needed for this direct 50 Ω connection. Taper pad transitions smoothly. Stitch grounds close to the module RF ground and both connector shell lands, without interrupting the return plane.

The board specification selects the four-layer **JLC04161H-7628** stack, L4-to-L3 dielectric 0.2104 mm with nominal Dk 4.4, RF width 0.35 mm and adjacent surface-copper clearance 0.50 mm. These dimensions are the proposed fabrication geometry; they are **not** evidence of measured impedance. Obtain the fabricator's confirmation of 50 Ω ±10%, including the actual copper, solder mask and coplanar ground geometry, before releasing CAM. Do not retain the same trace width after changing the stackup. The controlled-impedance requirement and actual manufacturing drawing take precedence over a nominal calculator estimate.

The internal pigtail provides the transition to the enclosure bulkhead. Antenna and bulkhead must agree on **SMA versus RP-SMA** and center-contact sex. A Taoglas GW.11.A153 antenna, if used by the enclosure BOM, requires an RP-SMA mate. The external antenna choice and cable loss are system-level acceptance inputs.

## 6. Inspection and release evidence

Before fitting a radio, check the 5 V input and RF_3V3 for shorts and confirm that host 3.3 V is not shorted to RF_3V3. First power-up should verify RF_3V3 at 3.20–3.40 V with no unexpected regulator heating. Capture the rail during actual TX/RX bursts, check for resets and ringing, and keep the radio VCC within its 1.9–3.6 V operating range. Verify the radio pinout, antenna connection and CE/CSN startup behavior before transmission.

Record module supplier/lot, a pinout photograph, host/base revision, firmware/library versions, full-stack current, transient rail captures, RF output setting, Ethernet/display concurrency results, and real-shade acceptance results. Reference hashes are in [electrical-sources.json](../references/electrical-sources.json). Manufacturer documents were consulted from temporary downloads; third-party PDFs and vendor source code are not redistributed in this tree.
