<!--
SPDX-FileCopyrightText: 2026 Christopher Spitler
SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later
-->

# Hardware source licensing and attribution

The repository's [component licensing policy](../LICENSING.md) remains in
effect. This file records the added hardware-source scopes and the licenses
of the small library collection distributed with this project. No third-party
part is relicensed by the project's general license.

## Project-authored files

Copyright 2026 Christopher Spitler.

- Original electronic-design sources, project configuration, original
  `HDPlatinum.pretty` footprints, design-generation/build tools and generated
  manufacturing design data are licensed **AGPL-3.0-or-later**. The canonical
  terms are [LICENSE](../LICENSE) and
  [AGPL-3.0-or-later.txt](../LICENSES/AGPL-3.0-or-later.txt).
- Original prose, tables, engineering evidence, supplier notes, system parts
  list and illustrative reference drawings are licensed
  **CC-BY-SA-4.0 OR AGPL-3.0-or-later**, following the repository's documentation
  policy. The alternative Creative Commons terms are
  [CC-BY-SA-4.0.txt](../LICENSES/CC-BY-SA-4.0.txt).
- Generated output includes the underlying design/library material under its
  applicable terms. Exporting a file as PDF, Gerber or SVG does not remove
  retained attribution or change the original component's license.

The KiCad exceptions below permit the use of their library data within this
project's own design; the separately distributed library collection retains
its upstream terms. License sidecars identify files whose syntax does not
provide a suitable place for a notice.

## KiCad library footprints

Copyright the KiCad library contributors. The following files are copies from
the installed `kicad-footprints` package, redistributed locally so
the project has its required land patterns without a global library search:

- `kicad/Capacitor_SMD.pretty/C_0603_1608Metric.kicad_mod`
- `kicad/Capacitor_SMD.pretty/C_0805_2012Metric.kicad_mod`
- `kicad/Capacitor_SMD.pretty/C_1206_3216Metric.kicad_mod`
- `kicad/Connector_Coaxial.pretty/U.FL_Hirose_U.FL-R-SMT-1_Vertical.kicad_mod`
- `kicad/Inductor_SMD.pretty/L_0603_1608Metric.kicad_mod`
- `kicad/Package_TO_SOT_SMD.pretty/SOT-23-5.kicad_mod`
- `kicad/Resistor_SMD.pretty/R_0603_1608Metric.kicad_mod`
- `kicad/TestPoint.pretty/TestPoint_Pad_D1.0mm.kicad_mod`

Seven files are unchanged. The Hirose U.FL footprint has one project change:
its `allow_soldermask_bridges` attribute is enabled so KiCad retains the
manufacturer-pattern mask opening under J2. Its pads, mask-opening drawing and
copper keepout geometry are unchanged. Copyright 2026 Christopher Spitler for
that modification; the modified file retains the upstream library license.

Upstream source: [KiCad footprints](https://gitlab.com/kicad/libraries/kicad-footprints).
The collection is **CC-BY-SA-4.0 with the KiCad libraries exception**. The
exception permits electronic designs and generated design files to use their
own licenses; it does not remove the share-alike/attribution requirements when
redistributing the library collection itself. Retain the full
[upstream notice](references/KiCad-Libraries-LICENSE.md) and the repository's
[CC-BY-SA-4.0 text](../LICENSES/CC-BY-SA-4.0.txt). The
[KiCad licensing explanation](https://www.kicad.org/libraries/license/)
describes this distinction.

The [footprint source manifest](references/kicad-footprints-sources.json)
records each copied file's hash; the
[installed-package copyright notice](references/kicad-footprints-debian-copyright.txt)
retains the upstream copyright and full license. Board
instances can be rotated, mirrored or have reference text relocated independently
of the checked-in library files. If a library file is modified later,
record that modification and retain its upstream license and attribution.

## M5Stack mechanical reference

The board outline and connector coordinates were derived from factual
measurements in M5Stack's public Module13.2 PCB source. Its repository is
MIT-licensed, copyright 2021 M5Stack. Retain the
[M5Stack MIT notice](references/M5Stack-MIT-LICENSE.txt) with this attribution.
The exact source revision and extraction details are in
[mechanical-sources.md](references/mechanical-sources.md). The vendor's Altium
project, logos and original circuit are not redistributed here.

## Component documents and firmware

NiceRF, M5Stack product documentation, Texas Instruments, Murata, Samsung,
Hirose, Taoglas and Raspberry Pi retain rights in their own documents and
trademarks. This project cites them and uses factual dimensions/specifications;
it does not distribute their PDF documents or confer a license to their
trademarks. A part number is not a claim that its maker endorses this carrier.

No ESP32 firmware or RF24 library is included by this hardware package.
Future firmware is a separate **GPL-2.0-or-later** component under the
repository policy; linked libraries retain their own terms, and the exact
RF24 source license must be reconciled before a binary release.
