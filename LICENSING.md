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

Project-authored firmware lives as a separate component and is licensed
`GPL-2.0-or-later`. The RAM-only receiver in `firmware/nrf52840_rx/` follows
that policy; the canonical GPL version 2 terms are in
[LICENSES/GPL-2.0-or-later.txt](LICENSES/GPL-2.0-or-later.txt).
This does not change the license of any library linked into a firmware image.

RF24 is currently treated conservatively as `GPL-2.0-only`. Before releasing a
linked firmware image, review the exact RF24 files and versions in the build,
confirm license compatibility at file level, retain required notices, and
provide corresponding source and build materials as required. Do not infer a
firmware release license from the host software's AGPL license.

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
