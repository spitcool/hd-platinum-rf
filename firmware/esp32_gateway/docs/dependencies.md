<!--
SPDX-FileCopyrightText: 2026 Christopher Spitler
SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later
-->

# Dependency versions and provenance

This records the development dependencies inspected on 2026-10-24. Project
firmware is independently authored under `GPL-2.0-or-later`; dependency source
and binary components retain their own licenses. Dependencies are downloaded
into ignored build/cache directories. They are not vendored in the project
source tree, although their code and runtime libraries can become part of a
linked firmware image. This inventory is not a completed binary redistribution
or corresponding-source audit.

## Direct pins

The build inputs are declared in [platformio.ini](../platformio.ini). Both
network variants use the same platform and direct library pins.

| Input | Exact version/revision | Inspected license evidence |
| --- | --- | --- |
| [PlatformIO Core](https://github.com/platformio/platformio-core/tree/v6.1.18) | 6.1.18 | Installed Python distribution metadata identifies Apache licensing. Build tool, not firmware code. |
| [Espressif32 platform](https://github.com/platformio/platform-espressif32/tree/v6.12.0) | 6.12.0 | `platform.json`: Apache-2.0. Selects the `m5stack-cores3` board and Arduino framework. |
| [M5Unified](https://github.com/m5stack/M5Unified/tree/0.2.7) | 0.2.7 | Root `LICENSE`: MIT, copyright 2021 M5Stack. Its manifest requires M5GFX >=0.2.8; this project supplies the exact Git pin below. |
| [M5GFX](https://github.com/m5stack/M5GFX/tree/cc613d65f13a3a80021ef264a654e9e6a2419d8a) | Manifest version 0.2.8; commit `cc613d65f13a3a80021ef264a654e9e6a2419d8a` | Root `LICENSE`: MIT, copyright 2021 M5Stack. Embedded components have additional notices, discussed below. |
| [Arduino Ethernet](https://github.com/arduino-libraries/Ethernet/tree/2.0.2) | 2.0.2 | README declares LGPL-2.1-or-later; source files contain several different licenses, discussed below. |
| [ArduinoJson](https://github.com/bblanchon/ArduinoJson/tree/v7.4.2) | 7.4.2 | `LICENSE.txt`: MIT, copyright 2014–2025 Benoit Blanchon. |

The M5GFX Git revision is the pin, rather than a version-range resolution.
A package cache may also contain a newer registry copy left from an earlier
resolution; that does not change the declared Git dependency. Check the build's
dependency graph and the resolved checkout when reproducing an image.

## Resolved platform packages

The following are the actual installed `package.json` versions, not inferred
from the platform's allowed version ranges:

| Package | Installed package version | Role and license evidence |
| --- | --- | --- |
| `framework-arduinoespressif32` | `3.20017.241212+sha.dcc1105b` | Arduino-ESP32 2.0.17, confirmed by `cores/esp32/esp_arduino_version.h`; package metadata says LGPL-2.1-or-later. Individual files also carry Apache-2.0 and other terms. |
| Bundled ESP32-S3 SDK | ESP-IDF 4.4.7 version macros | Resolved inside the Arduino package, not a separately installed `framework-espidf` package. Exact source revision of every precompiled archive has not been independently mapped. |
| `toolchain-xtensa-esp32s3` | `8.4.0+2021r2-patch5` | ESP32-S3 GCC toolchain, macOS arm64 package. Package-level GPL-2.0-or-later metadata is not an exhaustive license description of the collection. |
| `toolchain-riscv32-esp` | `8.4.0+2021r2-patch5` | Platform-installed companion toolchain; the main application targets Xtensa, not RISC-V. Same package-level license caveat. |
| `tool-esptoolpy` | `2.40900.250804` | esptool 4.9.0 packaging; manifest says GPL-2.0-or-later. Build/upload tool, not application code. |
| `tool-scons` | `4.40801.0` | SCons 4.8.1 packaging; manifest says MIT. Build tool, not application code. |

The SDK version was read from
`tools/sdk/esp32s3/include/esp_common/include/esp_idf_version.h` within the
installed framework package. The toolchain supplies per-component notices in
`share/licenses/`, including Newlib's `COPYING.NEWLIB` and GCC's
`COPYING.RUNTIME` exception. Runtime libraries and headers incorporated in the
image need their own review; the compiler executable's package label does not
determine the firmware's license.

## File-level qualifications

M5GFX contains LovyanGFX code whose headers identify the FreeBSD/BSD license,
including `src/lgfx/v1/LGFXBase.hpp`. It also includes MIT notices for kikuchan's
PNG decoder, Richard Moore's QR code implementation, and Matthew Rodusek's
result type; an Unlicense statement in `lgfx_miniz.c`; and ChaN's JPEG decoder
terms in `lgfx_tjpgd.c`. Font material has its own notices: Adafruit BSD terms
in `Fonts/GFXFF/license.txt`, the IPA Font License Agreement, DejaVu references,
and efont copyright text. The root MIT license must not be substituted for all
of these. The native screen uses M5GFX Font2 and DejaVu12/DejaVu18; a headless build
still builds against M5GFX. Inspect the final
link map to determine which bundled code/assets enter a distributed image.

Ethernet's library-wide README declares LGPL-2.1-or-later, but its
`src/utility/w5100.{h,cpp}` explicitly offers GPL version 2 **or** LGPL version
2.1 without an "or later" clause in those file headers. Prefer the LGPL-2.1
option for those files when reviewing the combined image. Several main classes
and UDP files contain MIT notices; `Dns.{h,cpp}` identifies Apache-2.0 and MCQN
Ltd.; compatibility headers declare public-domain status. DHCP files attribute
Jordan Terrell without their own license grant, so retain and review the
library-wide notice and upstream provenance. Preserve `AUTHORS` and applicable
source notices rather than flattening this package into one SPDX identifier.

Espressif's [ESP-IDF 4.4.7 copyright inventory](https://docs.espressif.com/projects/esp-idf/en/v4.4.7/esp32s3/COPYRIGHT.html)
describes the original SDK source as Apache-2.0 and lists third-party exceptions,
including FreeRTOS, lwIP, Newlib, and Mbed TLS. Its file headers take precedence
over the summary. The installed Arduino package additionally contains
precompiled SDK archives, including Wi-Fi, PHY, and coexistence libraries.
Their source availability, exact provenance, notice requirements and
redistribution terms have not been fully audited here. Do not describe every
SDK binary as covered solely by the Arduino package's LGPL label.

## Linked-image release requirements

The project's `GPL-2.0-or-later` grant permits choosing GPLv3 for a combined
work that incorporates Apache-2.0 dependencies. Apache-2.0 is compatible with
GPLv3 but not GPLv2, as explained by the
[Apache Software Foundation](https://www.apache.org/licenses/GPL-compatibility.html).
That choice addresses this known compatibility issue; it does not by itself
resolve all bundled-binary, font, LGPL or corresponding-source requirements.
No dependency is relicensed by this document.

Before distributing an image, retain the exact sources, dependency versions,
build configuration and applicable license/NOTICE texts; identify linked
objects using the map file; resolve the precompiled SDK archive provenance and
terms; and provide corresponding source and relinking/installation materials
where the applicable licenses require them. Record any dependency modifications
and the final image's licensing decision. Local build success is not evidence
that this release review has been completed.

The project does not link RF24, copy manufacturer firmware, or incorporate the
unlicensed Arduino forum sketches. `gateway_radio` is a separate implementation
from documented register and packet facts.
