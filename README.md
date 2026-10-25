<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# hd-platinum-rf

An open-source replacement bridge for Hunter Douglas Platinum blinds and shades,
built around ESP32, with protocol documentation and tools for ongoing research.

## The problem

Hunter Douglas Platinum shades rely on discontinued bridges and remotes. When
that control hardware fails, otherwise working shades become harder to use and
integrate with home automation. The legacy LAN and RF protocols need to be
understood and documented so that replacement controllers can keep them useful.

## The solution

We're building an ESP32-S3 gateway that provides local shade control through a
touchscreen, web interface, and the legacy Platinum network protocol. The current
hardware design uses an M5Stack CoreS3 SE, an Ethernet base, and a custom radio
carrier. Python research tools and a bridge emulator help us capture, understand,
and validate the protocols as the device takes shape.

This project targets the **Platinum generation** of products. It is independent
and unofficial, and does not target the later PowerView system.

## Project status

**We're currently confirming the RF protocols and designing the hardware
implementation.** The project is experimental; the ESP32 gateway is not yet a
validated replacement for the original bridge.

- [x] Document observed LAN commands and initial RF packet formats.
- [x] Build research tools and a bridge emulator with limited observed shade-control results.
- [x] Implement an ESP32-S3 firmware prototype with local controls.
- [ ] Confirm all RF protocols, command timing, and product-specific behavior.
- [ ] Complete and qualify the ESP32 hardware design.
- [ ] Validate enrollment, repeatability, and broader shade compatibility.
- [ ] Validate integrations such as Control4.

See the [RF validation plan](docs/rf-validation-plan.md) for the evidence and
remaining work. Successful software builds and simulations do not establish
physical RF compatibility.

## Getting started

- **Build your own device:** [ESP32 build, flashing, and device BOM](docs/esp32-build.md).
- **Explore the implementation:** [Project details and research tools](docs/project-details.md), including CLI setup and bridge emulator commands.
- **Understand the protocols:** [LAN protocol](docs/lan-protocol.md) and [RF protocol](docs/rf-protocol.md).
- **Review the hardware:** [Carrier design and assembly](hardware/README.md).
- **Run tests or help with RF validation:** [Testing guide](docs/testing.md) and [bench equipment BOM](docs/bom.md).

## Contributing

Protocol validation, hardware review, firmware testing, and documentation
contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) for the
workflow, test requirements, and DCO sign-off. Remove private installation data
from shared captures and reports. Use the
[issue tracker](https://github.com/spitcool/hd-platinum-rf/issues) for bugs and
feature discussions.

## License

Host software is [AGPL-3.0-or-later](LICENSE); project firmware is
[GPL-2.0-or-later](LICENSES/GPL-2.0-or-later.txt). Documentation is available under
[CC BY-SA 4.0](LICENSES/CC-BY-SA-4.0.txt) or AGPL-3.0-or-later. See
[LICENSING.md](LICENSING.md) for component boundaries and
[CREDITS.md](CREDITS.md) for third-party attribution.

Hunter Douglas and its product names are trademarks of their respective owner.
