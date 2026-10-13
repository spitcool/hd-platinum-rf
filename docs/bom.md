<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# RF validation bench bill of materials

This bill of materials defines the reference bench for capture, decoding, conducted waveform validation, and eventual low-power over-the-air interoperability testing. Quantities support one active SDR transmit/receive path and an independent reference-radio pair.

Equivalent parts are acceptable when they meet the stated electrical and connector requirements. Product links identify known-compatible examples; they are not endorsements, availability statements, or calibration evidence. Marketplace RF passives must be inspected and characterized as described in [Testing and validation](testing.md).

## Core equipment

| Quantity | Requirement | Reference item | Minimum requirement | Purpose |
| ---: | --- | --- | --- | --- |
| 1 | Required | [Nuand bladeRF 2.0 micro xA4](https://www.nuand.com/product/bladerf-xa4/) or [xA5](https://www.nuand.com/product/bladerf-xa5/) | USB 3, two RX/two TX paths, at least 56 MHz usable instantaneous bandwidth, tuning through 2.471 GHz | Raw-IQ capture and, after validation gates pass, waveform generation. The FPGA-size difference does not affect the host-side capture plan. |
| 1 | Required | USB 3-capable host | Direct SuperSpeed connection and local storage capable of sustained capture | Runs `libbladeRF`, capture tools, decoders, and test automation. One `61.44 MS/s` signed-16-bit complex stream is approximately `245.76 MB/s`. |
| 1 | Required | USB 3 SuperSpeed data cable | Connector types matching the host and bladeRF; data-rated rather than charge-only | Direct host-to-SDR connection. Use the bladeRF-supplied cable when available. |
| 2 | Recommended for full validation | [Nordic nRF52840 DK](https://www.nordicsemi.com/Products/Development-hardware/nrf52840-dk) | Nordic proprietary `2 Mbps` radio mode | Independent known transmitter/receiver pair and nRF24-family interoperability checks. One board can cover sequential tests; two permit an independent reference link. |
| 1 | Recommended when a spare remote can be probed safely | [Saleae Logic 8](https://www.saleae.com/products/logic-8) | At least six digital inputs and at least `25 MS/s`; `50 MS/s` preferred | Correlates `SCK`, `MOSI`, `MISO`, `CSN`, `CE`, and `IRQ` with RF captures. Do not probe the last irreplaceable remote. |
| 1 | Required for receive-only work | Standard-SMA 2.4 GHz antenna | 50 ohms, standard SMA male with center pin; a `0.6–6 GHz` wideband antenna is acceptable | Initial handheld, bridge, and repeater survey. A second antenna is optional for simultaneous dual-RX experiments. |
| 1 | Recommended | [bladeRF 2.0 micro enclosure](https://www.nuand.com/product/micro-case/) | Purpose-designed enclosure with unobstructed RF connectors and ventilation | Mechanical and ESD protection. |

## Conducted-loopback passives

| Quantity | Requirement | Reference part | Required characteristics | Purpose and limits |
| ---: | --- | --- | --- | --- |
| 1 | Required | [AURSINC 30 dB SMA attenuator](https://www.aursinc.com/products/aursinc-sma-male-female-rf-coaxial-attenuator-30db-dc-6ghz-50-ohm-2w-reduce-transmit-power-for-antenna-calibration-network-diagnostics-sensitive-receiver-protection) ([ASIN B08ZHTWRDP](https://www.amazon.com/dp/B08ZHTWRDP)) | 30 dB nominal, 50 ohms, standard SMA male-to-female, rated through at least 2.471 GHz | Primary receiver-protection pad. The linked part claims DC–6 GHz and 2 W, but has no traceable attenuation data. |
| 1 | Required | [AURSINC 10 dB SMA attenuator](https://www.aursinc.com/products/aursinc-sma-male-female-rf-coaxial-attenuator-10db-dc-6ghz-50-ohm-2w-precision-rf-signal-level-control-for-network-diagnosis-antenna-matching-sensitive-device-protection) ([ASIN B08ZHGFRLV](https://www.amazon.com/dp/B08ZHGFRLV)) | 10 dB nominal, 50 ohms, standard SMA male-to-female, rated through at least 2.471 GHz | Stacks with the 30 dB pad for nominal 40 dB attenuation. Never use this part alone for direct bladeRF TX-to-RX loopback. |
| 1 pack containing 2 | Required | [MOOKEERF two-foot RG316 cables, ASIN B0FWXC6KXM](https://www.amazon.com/dp/B0FWXC6KXM) | 50 ohms, standard SMA male-to-male | One cable completes the basic loopback; the second supports substitution checks or a later second path. Characterize loss rather than assuming it. |
| 2 | Required | [Mcbazel/Surecom 0014-0103 loads, ASIN B072MF2LR2](https://www.amazon.com/dp/B072MF2LR2) | Nominal 50-ohm standard SMA male termination, rated through at least 2.471 GHz | Terminates both TX ports during receive-only capture. During one-channel loopback, one terminates unused TX2 and the other is a spare or optional RX2 termination. |
| 1 | Recommended safety interlock | [Nooelec SMA In-Line DC Block, SKU 100816](https://www.nooelec.com/store/sdr/dc-block.html) ([ASIN B07YYLHJKS](https://www.amazon.com/dp/B07YYLHJKS)) | 50 ohms, standard SMA male-to-female, frequency range covering 2.4 GHz, DC blocking above the bladeRF bias voltage | One block in the single TX1-to-RX1 path is sufficient. The manufacturer specifies 50 kHz–8 GHz, 50 V blocking, 2 W RF input, less than 0.3 dB insertion loss, and less than 1.2 VSWR below 6 GHz. It does not replace disabling every bias tee. |

The exact one-cable chain is:

```text
bladeRF TX1 (SMA female)
  -> RG316 cable (SMA male-to-male)
  -> 30 dB pad (female-to-male connector order)
  -> 10 dB pad (female-to-male connector order)
  -> DC block (female-to-male connector order)
  -> bladeRF RX1 (SMA female)

bladeRF TX2 -> 50-ohm load
bladeRF RX2 -> disabled/open or the second 50-ohm load
```

All inline RF blocks above are electrically reciprocal; the female-to-male wording describes the connector order needed by this physical chain.

## Conditional adapters

| Quantity | When needed | Reference part | Purpose |
| ---: | --- | --- | --- |
| 1 | Only when cables are required on both sides of the rigid attenuator/DC-block chain | [Mini-Circuits SF-SF50+](https://www.minicircuits.com/WebStore/dashboard.html?model=SF-SF50%2B) | Standard SMA female-to-female barrel. It is not needed for the basic one-cable topology. |
| 1 per RP-SMA antenna | Only when using an RP-SMA-male Wi-Fi antenna | [Amphenol RF 132171RP](https://www.amphenolrf.com/en-us/part/132171rp/7264/) | Standard-SMA plug to RP-SMA jack conversion. Inspect the antenna center socket before ordering. |
| 1 | Alternative to the Nooelec DC block when traceable published RF data is preferred | [Mini-Circuits BLK-89-S+](https://www.minicircuits.com/pdfs/BLK-89-S%2B.pdf) | 50-ohm SMA female-to-male DC block, 0.1 MHz–8 GHz, with published performance data and S-parameters. |

Do not add an LNA, power amplifier, filter, splitter, or directional coupler until a measured requirement justifies it. Any external power amplifier invalidates the power-handling assumptions in this BOM and requires a new attenuation/safety calculation.

## Test articles supplied by the installation

| Quantity | Article | Purpose |
| ---: | --- | --- |
| 1 | Original paired Platinum handheld remote | Primary known-good RF source and identity/timing reference. |
| 1 or more | Platinum shade receivers | Final interoperability targets after conducted validation. |
| 1 | Original Platinum App Bridge | Read-only LAN behavioral reference and independent bridge-waveform capture source. |
| 0 or 1 | Platinum repeater | Optional bridge/repeater timing and possible protocol-translation investigation. |
| 0 or 1 | Spare remote suitable for probing | Required only for logic-analyzer correlation; never solder to the last operational controller. |

## Not included as calibration equipment

The reference marketplace attenuators, cables, loads, and antennas are appropriate for protection and protocol discovery, not absolute RF metrology. A calibrated VNA, spectrum analyzer, frequency reference, or power meter can improve uncertainty, but none is required to begin capture and framing work. Retain measurement settings and S-parameters whenever calibrated equipment is introduced.
