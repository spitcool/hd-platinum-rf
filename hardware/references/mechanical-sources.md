<!--
SPDX-FileCopyrightText: 2026 Christopher Spitler
SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later
-->

# Mechanical source manifest

Reviewed 2026-10-24. Vendor PDFs, product photographs and complete CAD sources were downloaded only to `/tmp/hd-platinum-hardware-references` for inspection; those copies are not distributed in this repository. Repository files record factual dimensions and original design notes.

| Source | Purpose | SHA-256 of inspected download |
| --- | --- | --- |
| [M032 nominal model drawing](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/982/module132proto.pdf) | External enclosure and hole-pitch cross-check | `97f21fbd88df3b129056228623cab233ad5e49b15f172b8a310364269cd7d24f` |
| [Module13.2 Proto Board source](https://github.com/m5stack/M5_Hardware/blob/e29c139cbc7c80b5ccc5557e5ab8025a7a19a109/Common/Module13.2/Footprints/Module13.2_Proto_Board.PcbDoc) | Nominal PCB outline, mounting positions, M5-Bus contact coordinates | `f9d079c80630767c75cbed6de96a8cbb345d2f3a48bff0c95e1697da0807c075` |
| [Official M032 assembly photograph](https://static-cdn.m5stack.com/resource/docs/products/module/proto13.2/proto13.2_01.webp) | Qualitative connector and PCB orientation; no scaled measurements | `306ac048a7ebaa6f0ac964d8f82b00c13dc25a9df62a75a1ec08be844cbfd014` |
| [A089 manufacturer specification](https://docs.m5stack.com/en/accessory/Bus_Socket_DIP_13.2) | 2×15 pitch, body and tail lengths | Live HTML; no archive distributed |
| [CoreS3 SE documentation](https://docs.m5stack.com/en/core/CoreS3-SE) | Electrical pin-number orientation cross-check | Live HTML; no archive distributed |
| [M5Stack screw guide](https://docs.m5stack.com/en/guide/basics/stack_screw_length) | Unequal CoreS3 screw engagement and reference-only length tables | Live HTML; no archive distributed |
| [Taoglas CAB.628 drawing](https://www.taoglas.com/datasheets/CAB.628.pdf) | Pigtail length, bulkhead cutout, nut and washer envelopes | Revision `SPE-12-8-152/E/WY`; vendor PDF not distributed |
| [Taoglas GW.11.A153 drawing](https://cdn.taoglas.com/datasheets/GW.11.A153.pdf) | External antenna envelope and matching RP-SMA connector | Revision H, 2026-08-31; vendor PDF not distributed |

The inspected public hardware repository revision is `e29c139cbc7c80b5ccc5557e5ab8025a7a19a109`. Its top-level [license](https://github.com/m5stack/M5_Hardware/blob/e29c139cbc7c80b5ccc5557e5ab8025a7a19a109/LICENSE) is MIT, copyright 2021 M5Stack; a local copy of that notice is [M5Stack-MIT-LICENSE.txt](M5Stack-MIT-LICENSE.txt). The 11.4 MB Altium source itself is not vendored. Factual coordinate extraction does not import the reference board's schematic, layout, logos or silkscreen into this design.

The extraction used the Altium `Board6`, `Pads6`, `Tracks6`, and `Nets6` records. Integer coordinates are in units of 0.0001 mil; record field layout was cross-checked against the [KiCad Altium reader](https://github.com/KiCad/kicad-source-mirror/blob/master/pcbnew/pcb_io/altium/altium_parser_pcb.cpp). Manufacturing coordinates are normalized to nominal millimetres, not the source file's incidental global placement.
