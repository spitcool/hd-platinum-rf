<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: MIT -->

The CoreS3 SE model and patch in this directory are MIT-licensed. The patch
applies to [esp32sim](https://github.com/mikroverk/esp32sim) commit
`964c26c1a6dac335e849195d2cabc15c713015a3` (v0.3.0). Retain the adjacent
upstream license notice when distributing the adapted emulator.

`cores3.rs` models the fitted ILI9342C, FT6336, AXP2101, AW9523B and RTC
interfaces. `cores3.patch` registers the board, routes three-wire SPI reads
back through MOSI, permits paced raw serial input, and adds loopback TCP
forwarding into the guest's real network stack. No guest functions are
stubbed and no graphics or gateway commands are intercepted.

The launcher downloads the pinned source into an ignored build directory,
applies the patch and installs the board model there. Upstream source and
Espressif ROM binaries are not vendored. See
[the environment notes](../../docs/device-simulator.md) for usage and limits.
