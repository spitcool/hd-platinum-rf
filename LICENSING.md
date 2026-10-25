<!--
SPDX-FileCopyrightText: 2026 Christopher Spitler
SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later
-->

# Licensing

This repository uses component-scoped licenses so that the software and its
documentation remain open while third-party material keeps its own terms.

## Project software

Project-authored host software, tests, configuration, and build metadata are
licensed under the GNU Affero General Public License, version 3 or later
(`AGPL-3.0-or-later`). The canonical terms are in [LICENSE](LICENSE) and
[LICENSES/AGPL-3.0-or-later.txt](LICENSES/AGPL-3.0-or-later.txt).

The separately scoped libbladeRF patch and offline regression component is an
exception: `tools/libbladerf_sc8/sc8-metadata.patch`, `check.py`, `probe.c`, and
`tests/test_libbladerf_sc8.py` use `LGPL-2.1-or-later`. The patch preserves
Nuand's copyright, and generated upstream source copies retain their original
notices. The unchanged upstream license text is in
[tools/libbladerf_sc8/LICENSE](tools/libbladerf_sc8/LICENSE); provenance and
modifications are recorded in that component's README and `CREDITS.md`.
Its README follows the project documentation license below.

If you modify the software and let users interact with it over a network, read
the AGPL's source-offer requirements, including section 13, before deployment.

## Project documentation

Project-authored documentation—including the README, files under `docs/`,
`CREDITS.md`, and the project-authored policy documents—is dual-licensed under
`CC-BY-SA-4.0 OR AGPL-3.0-or-later`. You may use either license. Their canonical
terms are in [LICENSES/CC-BY-SA-4.0.txt](LICENSES/CC-BY-SA-4.0.txt) and
[LICENSES/AGPL-3.0-or-later.txt](LICENSES/AGPL-3.0-or-later.txt).

The official Developer's Certificate of Origin in [DCO](DCO) is not
project-authored documentation. It retains The Linux Foundation's copyright
and verbatim-copy terms, recorded in
[LICENSES/LicenseRef-DCO-1.1-copying.txt](LICENSES/LicenseRef-DCO-1.1-copying.txt).

## Firmware

Project-authored firmware lives as separate components and is licensed
`GPL-2.0-or-later`. The RAM-only receiver in `firmware/nrf52840_rx/` and the
M5CoreS3 gateway in `firmware/esp32_gateway/`, including their project-authored
tests and build files, follow that policy; documentation retains the separate
documentation license above. The canonical GPL version 2 terms are in
[LICENSES/GPL-2.0-or-later.txt](LICENSES/GPL-2.0-or-later.txt).
This does not change the license of any library linked into a firmware image.

The separate desktop emulator adaptation in
`firmware/esp32_gateway/emulation/esp32sim/` is MIT-licensed, including its
CoreS3 board model and patch to the pinned upstream emulator. It executes the
firmware as a separate program. The upstream notice is retained in that
directory's `LICENSE`; the downloaded emulator, toolchain and Espressif ROM
files remain in ignored build directories under their own terms.

The ESP32 gateway links Arduino-ESP32, M5Unified/M5GFX, Ethernet and ArduinoJson;
their exact pins and file-level qualifications are recorded in its
[dependency inventory](firmware/esp32_gateway/docs/dependencies.md). Apache-2.0
components require using the project's later-version option for a GPLv3
combined work, rather than assuming GPLv2 compatibility. A binary release also
requires review of the actual linked SDK archives and runtime libraries,
applicable notices, source availability, and corresponding-source/relinking
materials. This repository has not completed that binary release audit.

RF24 is not linked by either firmware component. It is currently treated
conservatively as `GPL-2.0-only` for any future proposal to use it; review the
exact files and combined-work compatibility before adding it. Do not infer a
firmware release license from the host software's AGPL license or from a
dependency's package-level label.

## External and reference material

[CREDITS.md](CREDITS.md) records sources consulted and their known terms.
References, captures, vendor documents, and unlicensed example sketches are not
incorporated into or relicensed as part of this project merely because they are
listed, cited, or used to learn protocol facts. Do not add their expressive
content to the distributable tree without a compatible license or explicit
permission.

When adding a dependency or derived work, preserve its notices, identify the
source and exact version in `CREDITS.md`, and add a file-level SPDX identifier
where the component policy alone is not sufficient.
