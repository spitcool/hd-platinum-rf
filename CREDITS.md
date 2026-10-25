<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Credits, provenance, and independent-development record

This project depends on years of community investigation. The goal of this file is to make that lineage explicit and to keep factual protocol research separate from software-license reuse.

## Reuse policy

- The repository's Python code was written from the protocol facts and live observations documented here. No third-party implementation was copied into it.
- Wire tokens, measured values, register settings, packet-field facts, and interoperability behavior are restated with attribution.
- The unlicensed Arduino forum attachments are reference evidence only. They must not be copied, modified, or redistributed without permission from their authors.
- GPL/AGPL protocol comparison implementations were inspected as research tools only. No source from them is copied into the project-authored implementations. Separately linked firmware dependencies are recorded below.
- The separately scoped libbladeRF patch below incorporates a small upstream source diff under LGPL-2.1-or-later. The offline regression extracts user-supplied upstream functions with their original notices; those function bodies are not bundled here.
- For any further code incorporation, add its exact version, copyright, license text, modifications, and required notices before merging it.

## LAN protocol work consulted

- **Aaron Taylor / ExPHAT — [node-hunterdouglas](https://github.com/exPHAT/node-hunterdouglas)**. Early JavaScript client establishing TCP port 522, bare writes, LF-CR responses, `$dat`, `$pss`, `$rls`, and the 0–255 scale. Inspected at commit `9bb23b79ef6beb75b26885d70b5e175c8628ba77`. MIT License, copyright 2016 Aaron Taylor.
- **Roland Schemers — [homebridge-hunterdouglas-platinum](https://github.com/schemers/homebridge-hunterdouglas-platinum)**. Banner handling, variable numeric prefixes, LF-CR record parsing, operation sequencing, and secondary feature behavior. Inspected at commit `1bdd2cba5ef293da08bb4b6608421a306c64e83c`. MIT License, copyright 2020 schemers.
- **James Wilkinson — [aio-powerrise-api 0.1.0.dev3](https://pypi.org/project/aio-powerrise-api/0.1.0.dev3/)**. Broad command/record inventory, discovery, scenes, product types, and asynchronous state modeling. Inspected from the source distribution with SHA-256 `2ba797c13e2106e9b963af64e2b6e11fb44ec3a2af7676bef07ed768926b1453`. MIT License, copyright 2026 James Wilkinson. Its own NOTICE credits Sander Teunissen and Schwark Satyavolu.
- **Gengen — [Platinum Shade Vera plug-in v1.8](https://community.ezlo.com/t/hunter-douglas-platinum-bridge-app/187439?page=3)**. Action lifecycle, room and schedule layouts, `$psr`, date/time commands, queueing, and composite multi-feature behavior. The inspected v1.8 archive has SHA-256 `8e5b294d21123a82eb1861823d30c8470363fe4e46b7a5f75a4f4c0971de523c`. Its Lua source declares GNU GPL v2.0, while the archive has no standalone license and its XML files have no headers, so the exact scope is mildly ambiguous. Findings are paraphrased; implementation code is not reused.
- **Schwark Satyavolu — [smartthings-hunterdouglasplatinum](https://github.com/schwark/smartthings-hunterdouglasplatinum)**. SmartThings integration and long-running practical command behavior. Inspected at commit `e9826f3bec648ac41c5e18422da127eca2ebbd29`. The repository's root license is MIT, copyright 2015 Schwark Satyavolu, but its three device-handler files explicitly say Apache-2.0 and credit **Allan Klein (`@allanak`)** and **Mike Maxwell** as the originating code. Treat licensing per file; this project copied none of it.
- **Sander Teunissen — [aio-powerview-api](https://github.com/sander76/aio-powerview-api)**. Architecture/API influence credited by `aio-powerrise-api`; it targets the later PowerView family rather than this Platinum wire protocol. BSD 3-Clause License, copyright 2017 Sander Teunissen.

## RF protocol work consulted

- **dpinvidic (Dan) — [NRF24L01+ hack on Hunter Douglas shades](https://forum.arduino.cc/t/nrf24l01-hack-on-hunter-douglas-shades/676940)**. Direct register dump, five-byte legacy Platinum commands, release-tail values, SPI/CE timing, channel rotation, and repeat behavior. The posts do not state a software license; facts are summarized and credited, and posted code is not copied.
- **zergraph — [ESP8266 and NRF24L01+ Hunter Douglas Platinum Remote](https://forum.arduino.cc/t/esp8266-and-nrf24l01-hunter-douglas-platinum-remote/918887)**. Working replay implementation for remote part `2984495100`, payload commentary, and the attached `HD-Platinum-Remote-Hack.ino`. The inspected attachment has SHA-256 `2e4a90a34a77b974d2b6b54b6b850a7e6a3f1d4e7204434ef5ea25dd8e8d8b37` and no license grant. It was not copied.
- **gpduino — [PacketDissector/address-discovery contribution](https://forum.arduino.cc/t/nrf24l01-hack-on-hunter-douglas-shades/676940/33)**. Pseudo-promiscuous nRF24 capture method and evidence that later Pebble hardware/protocol differs. The inspected `PacketDissector.ino` has SHA-256 `1f802b311f289725f8f7142742035c777df8470b4e8e06ca67ea34896d9bcfbf` and no explicit license; method and findings only. zergraph explicitly states that the attached replay sketch derives from gpduino's work.
- **Travis Goodspeed** and **Ivo Pullens (Yveaux)**. Their nRF24 promiscuous-sniffing work is credited in gpduino's contribution. Pullens's [NRF24_Sniffer](https://github.com/Yveaux/NRF24_Sniffer) is GPL-3.0; no code is incorporated.
- **TMRh20 and the [RF24](https://github.com/nRF24/RF24) contributors**. The Arduino implementations use this nRF24 driver. RF24 is GPL-2.0-only. This repository neither vendors nor links it. Any future firmware that links RF24 must be a separately licensed deliverable and satisfy RF24's GPL-2.0-only requirements; do not assume the host software license governs that combined work.
- **Nick Gammon**, **AgileWare**, **kroimon**, and **Steven Cogswell**. gpduino's PacketDissector credits Gammon's `Regexp`, AgileWare's `CircularBuffer`, and kroimon's version of Cogswell's `SerialCommand`. None of those libraries is used here; their credit is retained because the unlicensed derivative sketch is part of the evidence lineage.
- **Johannes Pohl and Andreas Noack — [Universal Radio Hacker](https://github.com/jopohl/urh)**. Tool used for gpduino's separate Pebble capture and a candidate local analysis tool. GPL-3.0; no code incorporated.

## SDR implementations evaluated, not incorporated

- **Marc Newlin / Bastille Research — [gr-nordic](https://github.com/BastilleResearch/gr-nordic)**. GNU Radio receiver/transmitter reference for Nordic Enhanced ShockBurst. Inspected at commit `5c468607118e2857d6920708618860ba1a9ea532`. Source headers state GPL-3.0-or-later; the root license is GPLv3. Its parser/transmitter has offsets specialized around a five-byte address in the inspected revision, so it should not be assumed to support this protocol's three-byte address without review and testing.
- **kittennbfive — [gr-nrf24-sniffer](https://github.com/kittennbfive/gr-nrf24-sniffer)**. Current GNU Radio/HackRF receiver and C decoder supporting 2 Mbps, fixed payload size, CRC-16, and configurable 3–5-byte addresses; its documentation says address sizes other than five are untested. AGPL-3.0-or-later, copyright 2022–2026 kittennbfive. It is a promising receive-side validation tool, not incorporated code.

## libbladeRF patch and offline regression

- **Nuand LLC — [bladeRF/libbladeRF](https://github.com/Nuand/bladeRF/tree/fcf9423325ae49f5fdd2e5b52ab68bfc2576ad47)**. The separately licensed [SC8 metadata patch and regression tool](tools/libbladerf_sc8/README.md) target revision `fcf9423325ae49f5fdd2e5b52ab68bfc2576ad47`. The patch derives from `host/libraries/libbladeRF/src/streaming/sync.c`, copyright 2014–2015 Nuand LLC, LGPL-2.1-or-later. It adds SC8 metadata format handling to TX parameter validation and successful end-of-burst state cleanup. The project-authored inert harness compiles selected, hash-verified functions and headers supplied by the user, retaining upstream notices; it does not vendor or link a device library. Patch additions and harness are copyright 2026 Christopher Spitler, also LGPL-2.1-or-later. The canonical upstream LGPL text is preserved in `tools/libbladerf_sc8/LICENSE`. Full provenance, exact hashes, tested behavior, and hardware-validation limits are recorded in the component README.

## Original firmware research tools

- **Daniel Drotos and contributors — [uCsim](https://github.com/danieldrotos/ucsim)**. A separately built MCS-51 simulator executes user-supplied firmware in the bounded offline probe. The reference build used release 0.9.11, commit `6f7cf7a4a67f5787a3a59847cfbd9f366a222e4b`; its source headers declare GPL-2.0-or-later. Neither its source nor executable is bundled. The project's subprocess adapter is independently authored.
- **Silicon Laboratories — [C8051F34x datasheet](https://www.silabs.com/documents/public/data-sheets/C8051F34x.pdf)**. Instruction-family, memory, clock, SPI and external-memory register facts support the inferred MCU model. The exact installed part remains unconfirmed.
- **Silicon Laboratories — [CP2200/CP2201 datasheet](https://www.silabs.com/documents/public/data-sheets/CP2200.pdf)**. Parallel Ethernet register and buffer semantics support board-model research. Documentation and implementation code are not copied into this project.
- **Hunter Douglas Platinum Android application and embedded update images**. User-supplied local APK assets are inspected for interface and hardware facts. Extracted vendor firmware remains private and is not distributed or relicensed with the project. Public tests use generated fictional images; the observed image's hash identifies the address-specific execution probe.

## Native receiver firmware and host tooling

- **Nordic Semiconductor — [nRF52840 product specification](https://docs.nordicsemi.com/r/bundle/ps_nrf52840)**. RADIO, TIMER, PPI, clock, memory and interrupt register facts support the independently authored RAM-only receiver. Silicon revision facts were cross-checked against [nrfx v3.0.0 errata definitions](https://github.com/NordicSemiconductor/nrfx/blob/v3.0.0/mdk/nrf52_erratas.h). No Nordic SDK, startup implementation or vendor firmware is included in the component.
- **Arm and GNU toolchain contributors — [Arm GNU Toolchain](https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads)**. The separate reference compiler is Arm GNU 14.3.Rel1 for macOS arm64, targeting `arm-none-eabi` (GCC 14.3.1). Its official archive SHA-256 is `30f4d08b219190a37cded6aa796f4549504902c53cfc3c7e044a8490b6eba1f7`. The freestanding receiver links no SDK or runtime library. Compiler binaries remain external and retain their own licenses.
- **OpenOCD and libjaylink contributors — [OpenOCD](https://openocd.org/)**. OpenOCD 0.12.0 with bundled libjaylink 0.3.1 was built separately to prepare a J-Link/SWD host path. No programmer or library source/binary is distributed with the Python package or receiver component. Preparing tools does not establish target access, radio reception or successful RAM loading.

## ESP32-S3 gateway firmware dependencies

The [M5CoreS3 gateway](firmware/esp32_gateway/README.md) is independently
authored C++ from the documented LAN and RF facts. It does not include the
manufacturer's firmware, unlicensed forum sketches, or RF24. Its packet-radio
driver uses an explicit SPI/register interface; its project-authored source,
tests and build files follow the firmware `GPL-2.0-or-later` policy.

- **M5Stack, lovyan03 and contributors — [M5Unified](https://github.com/m5stack/M5Unified/tree/0.2.7) 0.2.7 and [M5GFX](https://github.com/m5stack/M5GFX/tree/cc613d65f13a3a80021ef264a654e9e6a2419d8a) 0.2.8**, pinned to M5GFX commit `cc613d65f13a3a80021ef264a654e9e6a2419d8a`. Board/power initialization and display-bus release use their public APIs. Both have root MIT licenses; M5GFX also contains LovyanGFX, decoder and font notices with separate terms.
- **Arduino Ethernet contributors — [Ethernet](https://github.com/arduino-libraries/Ethernet/tree/2.0.2) 2.0.2**. W5500 TCP/UDP and DHCP networking. Its README declares LGPL-2.1-or-later, while individual files include MIT, Apache-2.0, public-domain notices, and a GPL-2.0/LGPL-2.1 choice. **Benoit Blanchon — [ArduinoJson](https://github.com/bblanchon/ArduinoJson/tree/v7.4.2) 7.4.2**, MIT, supplies HTTP JSON encoding/decoding.
- **PlatformIO and Espressif contributors**. PlatformIO Core 6.1.18, Espressif32 platform 6.12.0, and Arduino-ESP32 2.0.17 provide the build and runtime framework. The resolved Arduino package is `3.20017.241212+sha.dcc1105b`, with ESP-IDF 4.4.7 version macros and Espressif GCC 8.4.0 (`2021r2-patch5`). Framework sources, precompiled SDK archives, and runtime libraries retain their own terms; the package-level LGPL label is not a complete combined-image license.
- **Joakim Eriksson, Alice, Mattia Fiumara and contributors — [esp32sim](https://github.com/mikroverk/esp32sim/tree/964c26c1a6dac335e849195d2cabc15c713015a3)**. The MIT-licensed instruction emulator runs the ESP32-S3 image in the desktop environment. The local adaptation adds a CoreS3 SE board model, three-wire SPI read routing, paced serial input, and inbound TCP forwarding. Its patch and board model are retained in `firmware/esp32_gateway/emulation/esp32sim/`; the macOS window displays the emulated LCD framebuffer and injects touch contacts.
- **Wokwi / CodeMagic and contributors**. The optional Wokwi configuration uses the licensed VS Code simulator and a locally compiled AXP2101/AW9523 custom chip. The stock CoreS3 board's missing touch wiring remains a limitation; original custom-board artwork and an experimental corrected definition are included separately. Wokwi itself is not bundled.

Exact resolved packages, inspected file-level notices, and remaining binary
release-review work are recorded in the
[dependency inventory](firmware/esp32_gateway/docs/dependencies.md). Downloaded
dependencies remain outside tracked source; linked firmware includes dependency
code and requires the corresponding notices/source review before distribution.

## Optional IQ-analysis dependencies

- **[NumPy](https://numpy.org/)**, tested at `1.26.4`, and **[SciPy](https://scipy.org/)**, tested at `1.13.1`, provide array operations, FIR filter design, and polyphase resampling through their public APIs. Both projects use the BSD 3-Clause license; their installed distributions retain their own copyright notices and bundled-component licenses. They are declared as the optional `analysis` dependency group, not vendored into this repository. No NumPy, SciPy, or third-party demodulator source was copied into the independently authored receiver.

The receive decoder and its synthetic fixtures were developed from the documented framing hypotheses and the local 2026-10-23 IQ. Independent polynomial division and Python's `binascii.crc_hqx` cross-checked the CRC implementation. Synthetic test identities are fictional; captured identities and their CRCs are excluded from tracked fixtures.

## Primary technical and regulatory sources

- **Nordic Semiconductor — [nRF24L01+ Product Specification v1.0](https://docs-be.nordicsemi.com/bundle/nRF24L01P_PS_v1.0/raw/resource/enus/nRF24L01P_PS_v1.0.pdf)** and [nRF24LU1+ Product Specification v1.1](https://docs-be.nordicsemi.com/bundle/nRF24LU1P_PS_v1.1/raw/resource/enus/nRF24LU1P_PS_v1.1.pdf). GFSK PHY, channel mapping, packet control field, CRC, timing, ShockBurst compatibility, and the repeater radio's integrated USB/transceiver architecture. Technical facts are paraphrased; the documents are not redistributed.
- **Hunter Douglas Window Fashions**, **SMK**, **Nemko**, **TÜV SÜD America**, and the **FCC filing record**. Public exhibits for [`UXURC4U`](https://fccid.io/UXURC4U), [`UXUWS4U`](https://fccid.io/UXUWS4U), [`UXURC4U2`](https://fccid.io/UXURC4U2), [`UXUPC`](https://fccid.io/UXUPC), [`UXUPR`](https://fccid.io/UXUPR), and later [`UXURC4U3`](https://fccid.io/UXURC4U3) establish device identity, frequencies, modulation, power, components, and measured bandwidth. The repeater BOM identifies Nordic `nRF24LU1P-F32Q32-R7`; the App Bridge's public internal-photo markings are unreadable, so this project does not claim an exact Bridge radio chip. The App Bridge test report inspected locally had SHA-256 `ccc1fab0d1104864ff739559e25ac262534a93fa1cf3bda410664d1fc92067a8`; its internal-photos exhibit had SHA-256 `e2e6c287142fc6d6eedfb2c9fae9ae8aec1e580254dfea3d3b8b6491178bf1f4`.
- **Hunter Douglas support — [Operate PowerRise with the Platinum App](https://help.hunterdouglas.com/hc/en-us/articles/40440345796372-Operate-PowerRise-with-the-Platinum-App)** and [PowerView versus older PowerRise compatibility](https://www.hunterdouglas.com/faqs/can-i-use-my-new-powerview-pebble-remote-to-operate-my-older-powerrise-shades). Product-generation, Bridge/Gateway, and incompatibility context.

## Capture-bench documentation consulted

- **Nuand — [bladeRF 2.0 micro platform](https://www.nuand.com/bladerf-2-0-micro/), [xA4](https://www.nuand.com/product/bladerf-xa4/), [xA5](https://www.nuand.com/product/bladerf-xa5/), and [bladeRF accessories guidance](https://github.com/Nuand/bladeRF/wiki/bladeRF-Accessories)**. Device bandwidth, sample rate, MIMO/full-duplex capability, variant differences, CW output power, software compatibility, and the minimum attenuated-loopback precautions. Manufacturer documentation facts are paraphrased. The separate libbladeRF source patch is attributed above.
- **Ettus Research / National Instruments — [USRP B210](https://www.ettus.com/all-products/ub210-kit/)**. Bandwidth, sample rate, MIMO/full-duplex capability, UHD support, and kit contents used in the capture-platform comparison. Manufacturer facts are paraphrased; no Ettus code is incorporated.
- **Great Scott Gadgets — [HackRF One documentation](https://hackrf.readthedocs.io/en/stable/hackrf_one.html)**. Half-duplex operation, supported sample-rate range, sample resolution, and input-protection guidance used to delimit its role as a per-channel fallback. Documentation facts are paraphrased; no code is incorporated.
- **Saleae — [Logic 8](https://www.saleae.com/products/logic-8)** and [simultaneous-channel sample-rate guidance](https://www.saleae.com/support/logic-software/capturing-data/what-sample-rate-settings-are-available). Channel count and digital sampling capability used to plan a correlated SPI/CE/IRQ capture. Manufacturer facts are paraphrased; no software is incorporated.
- **Nordic Semiconductor — [nRF52840 DK](https://www.nordicsemi.com/Products/Development-hardware/nrf52840-dk)** and [nRF52840 radio specification](https://docs.nordicsemi.com/r/bundle/ps_nrf52840/page/radio.html). Programmable proprietary `2 Mbps` reference-radio capabilities and nRF24-family on-air compatibility. Documentation facts are paraphrased; no SDK code is incorporated.
- **Bitcraze — [Crazyradio 2.0](https://store.bitcraze.io/products/crazyradio-2-0)** and its [compatible USB/radio protocol](https://www.bitcraze.io/documentation/repository/crazyradio2-firmware/main/development/compatible-usb-protocol/). Evaluated as an optional USB reference endpoint; its stock Enhanced ShockBurst settings do not by themselves prove the Platinum static-payload/no-ACK framing. No firmware is incorporated.
- **AURSINC — [10 dB attenuator](https://www.aursinc.com/products/aursinc-sma-male-female-rf-coaxial-attenuator-10db-dc-6ghz-50-ohm-2w-precision-rf-signal-level-control-for-network-diagnosis-antenna-matching-sensitive-device-protection) and [30 dB attenuator](https://www.aursinc.com/products/aursinc-sma-male-female-rf-coaxial-attenuator-30db-dc-6ghz-50-ohm-2w-reduce-transmit-power-for-antenna-calibration-network-diagnostics-sensitive-receiver-protection)**. Manufacturer pages were used to corroborate the nominal connector, impedance, frequency, power, and VSWR claims for Amazon ASINs [`B08ZHGFRLV`](https://www.amazon.com/dp/B08ZHGFRLV) and [`B08ZHTWRDP`](https://www.amazon.com/dp/B08ZHTWRDP). No calibration data or attenuation tolerance was found, so these are vendor specifications rather than local RF characterization.
- **MOOKEERF — [two 2-foot RG316 SMA cables, Amazon ASIN B0FWXC6KXM](https://www.amazon.com/dp/B0FWXC6KXM)**. The exact marketplace listing was used for cable count, length, impedance, construction, and connector sex. It supplied no measured insertion-loss, return-loss, or frequency-response data; no such performance is treated as verified.
- **Mcbazel/Surecom — [0014-0103 RF dummy load, Amazon ASIN B072MF2LR2](https://www.amazon.com/dp/B072MF2LR2)**. The exact marketplace listing and imagery were used for nominal impedance, frequency range, power rating, and standard-SMA-male connector identification. Vendor match claims are not treated as traceable measurements.
- **Amphenol RF — [132171RP adapter](https://www.amphenolrf.com/en-us/part/132171rp/7264/)**. The manufacturer connector definition supports the optional standard-SMA-plug to RP-SMA-jack adapter recommendation for typical Wi-Fi antennas. Actual antenna center contacts still must be inspected locally.
- **Mini-Circuits — [SF-SF50+ adapter](https://www.minicircuits.com/WebStore/dashboard.html?model=SF-SF50%2B) and [BLK-89-S+ DC block](https://www.minicircuits.com/WebStore/dashboard.html?model=BLK-89-S%2B)**. Manufacturer pages support the optional strain-relief/two-cable topology and DC-block recommendation. Neither part is required for the basic one-cable loopback and neither substitutes for disabling SDR bias tees.
- **Nooelec — [SMA In-Line DC Block, SKU 100816](https://www.nooelec.com/store/sdr/dc-block.html) and [Amazon ASIN B07YYLHJKS](https://www.amazon.com/dp/B07YYLHJKS)**. The manufacturer specification and exact marketplace listing were used to evaluate this male-to-female DC block as a bench substitute: 50-ohm operation from 50 kHz to 8 GHz, 50 V blocking, 2 W RF input, and the published insertion-loss/VSWR limits. These are vendor specifications; local inspection and characterization remain required.

## Local observations

The finite SDR backend uses the public API and ABI declared by Nuand's
[libbladeRF 2025.10 header](https://github.com/Nuand/bladeRF/blob/2025.10/host/libraries/libbladeRF/include/libbladeRF.h),
its [bladeRF 2.0 stream implementation](https://github.com/Nuand/bladeRF/blob/2025.10/host/libraries/libbladeRF/src/board/bladerf2/common.c),
and Analog Devices' [AD9361 driver API](https://github.com/analogdevicesinc/no-OS/blob/main/drivers/rf-transceiver/ad9361/ad9361_api.c).
These establish metadata layouts, finite-burst flushing, shared sample clocks,
and stream limits. The ctypes wrapper and lifecycle tests are independently
authored; no driver source is copied. The installed ABI is libbladeRF 2.6.

A sanitized read-only bridge observation on 2026-10-13 established TCP port 522, captured the banner and an initial `$dat` response, performed a second read-only `$dat` query while validating the client, and checked `$dmy` without receiving a device reply in the observation window. The private network address, household names, and real MAC address are deliberately excluded from the repository.

The receive-only session on 2026-10-23 retained original, hashed IQ and recovered Group 1 Up, Down, and following release-tail packets. Local framing and PHY observations are documented with their limits in [RF protocol](docs/rf-protocol.md#initial-local-receive-result--2026-10-23) and [Testing and validation](docs/testing.md). The raw recordings and installation identity remain private.

Later protected transmissions and command-correlated bridge recordings support
the separately documented position payload layout. The phase values, room
identity comparison, one-hot selector mapping, and position-byte observations
come from retained local IQ and controlled LAN commands. Synthetic fixture
identities and CRCs are fictional. Observing command traffic does not establish
which bridge/repeater component emitted it or prove replacement-transmitter
interoperability with a shade.

All errors in this synthesis are this project's responsibility, not those of the credited authors.
