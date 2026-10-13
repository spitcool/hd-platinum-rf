<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Hunter Douglas Platinum RF protocol

Status: working specification, evidence review dated 2026-10-13.

This document specifies the legacy Hunter Douglas **Platinum** four-group hand-remote signal, including the remote identified by part number `2984495100`. It also records what is known about the Platinum App Bridge, but FCC bandwidth measurements show that the bridge has a substantially narrower RF waveform and must not yet be treated as the same PHY. It does not describe the later PowerView/Pebble protocol. An original bridge is useful as a Phase 2 network reference, but its installation-specific address is not part of either RF protocol.

The practical result so far is that Platinum is not Wi-Fi or Bluetooth. It is a proprietary application payload carried by a Nordic-style 2.4 GHz GFSK packet radio. The known settings are sufficient to build an nRF24L01+ replay transmitter. A true SDR transmitter still needs raw-IQ validation of serialization, CRC byte order, and exact burst timing before this can be called a complete waveform specification.

## Evidence labels

Every technical claim below uses one of these labels:

- **[PRIMARY]** — a manufacturer data sheet or regulatory filing.
- **[CAPTURE]** — a community member reported a direct SPI, logic-analyzer, or RF capture. This is strong evidence, but has not yet been reproduced on this installation.
- **[REFERENCE]** — behavior of the local `HD-Platinum-Remote-Hack.ino` reference sketch, not necessarily behavior of an original remote.
- **[INFERENCE]** — a conclusion that follows from the sources but still needs a local capture.
- **[UNKNOWN]** — not established by the available evidence.

“Verified” in this document means verified by the cited source, not yet independently verified against the equipment at this site.

## Compatibility boundary: do not mix generations

| Family | Reported RF behavior | Hardware evidence | Relevance |
| --- | --- | --- | --- |
| Legacy Platinum hand remote | `2433`, `2452`, and `2471 MHz`; GFSK; community capture reports `2 Mbps`, 3-byte address, and 5-byte payload | FCC IDs [`UXURC4U`](https://fccid.io/UXURC4U) and [`UXURC4U2`](https://fccid.io/UXURC4U2) occupy `2433–2471 MHz`. The [`UXURC4U2` test report](https://fcc.report/FCC-ID/UXURC4U2/1688109.pdf) measured a wide 99%-power bandwidth of `3.38`, `3.65`, and `4.08 MHz` at those centers. | **Primary target of this document** |
| Platinum wall switch | `2433`, `2452`, and `2471 MHz`; GFSK; measured 20 dB widths `1.80`, `1.98`, and `1.68 MHz` | FCC ID [`UXUWS4U`](https://fccid.io/UXUWS4U), model/part `2986340000`, [test report](https://fccid.io/UXUWS4U/Test-Report/test-report-1092829.pdf) | **Related and consistent with the wide remote family; payload not decoded here** |
| Platinum App Bridge | Three main channels plus a `2440 MHz` control channel; all measured much narrower than the handheld signal | Bridge FCC ID [`UXUPC`](https://fccid.io/UXUPC); its [Part 15.249 report](https://fccid.io/UXUPC/Test-Report/SC1206696B-FCC-Part-15-249-RSS210-Test-Report-1757162.pdf) reports about `0.12–0.14 MHz` 99%-power bandwidth and `0.08–0.11 MHz` 20 dB bandwidth. It calls `2440 MHz` a short Bridge↔Repeater “Shock Burst” handshake and says main RF transmits sequentially at `2433/2452/2471`. | **Related but undecoded; capture separately** |
| Platinum Repeater | Same four-channel narrowband architecture described for the Bridge | FCC ID [`UXUPR`](https://fccid.io/UXUPR). Its public [BOM](https://fccid.io/UXUPR/Parts-List-Tune-Up-Info/RXX9000X2611E01-rev6-Repeater-BOM-1759043.pdf) identifies Nordic `nRF24LU1P-F32Q32-R7`; its [RF report](https://fccid.io/UXUPR/Test-Report/SC1206696C-FCC-Part-15-249-RSS210-Test-Report-1759014.pdf) describes the four channels. | **Chip family established for the Repeater, not for the Bridge; packet format still unknown** |
| Later PowerView/Pebble | A separate community capture reported `2407 MHz`, `1 Mbps`, a 3-byte address, and roughly 25 bytes after the address; an opened Pebble used an nRF51422 | FCC [`UXURC4U3`](https://fccid.io/UXURC4U3) spans a wider `2407–2480 MHz` range; see gpduino’s posts in the [protocol-investigation thread](https://forum.arduino.cc/t/nrf24l01-hack-on-hunter-douglas-shades/676940/17) | **Not compatible; do not import its packet layout, rolling fields, or channel into Platinum** |

The long “Pebble” frames and the gpduino address-discovery sketch are useful methodological references only. They are not evidence that Platinum uses a 25-byte payload, `1 Mbps`, channel 7, rolling counters, or a non-Nordic checksum. Hunter Douglas also states that later PowerView remotes use a different communication method and cannot operate earlier PowerRise/Platinum shades in its [compatibility FAQ](https://www.hunterdouglas.com/faqs/can-i-use-my-new-powerview-pebble-remote-to-operate-my-older-powerrise-shades).

Likewise, a shared set of three frequencies does not prove that the App Bridge emits the hand remote’s Nordic frames. The more-than-an-order-of-magnitude bandwidth difference is primary evidence for a distinct bridge RF PHY or transmit mode. The Repeater BOM proves that device contains an nRF24LU1+—whose radio is in the nRF24L01+ family—but it does not establish the Bridge chip, register configuration, or on-air frame. Whether the repeater translates narrow bridge frames into the wide remote waveform, and whether shades receive either form directly, remain **[UNKNOWN]**.

## RF/PHY specification

### Established parameters

| Parameter | Value | Evidence and confidence |
| --- | --- | --- |
| Modulation | GFSK | **[PRIMARY]** The 2007 [`UXURC4U` test report](https://fccid.io/m/fa3a1a00dbbd2dcb57442c97e26e018682903603b417ae840101f0b276d08809.pdf) identifies GFSK. Nordic documents GFSK for the nRF24L01+. |
| Air data rate | `2 Mbps` | **[CAPTURE]** Direct register dump reported `RF_SETUP = 0x0c` and `2MBPS`; the working reference sketch also selects `RF24_2MBPS`. This must still be checked against local IQ. |
| Typical deviation at `2 Mbps` | `±320 kHz` | **[PRIMARY]** nRF24L01+ product specification. This is a chip characteristic, not a measured value for this remote. |
| Nominal nRF24L01+ width at `2 Mbps` | approximately `1.8 MHz` typical and `2.0 MHz` maximum at the 20 dB points | **[PRIMARY]** nRF24L01+ product specification. This is a chip-level specification, not a substitute for measuring the finished remote. |
| Finished Platinum remote width | `3.38`, `3.65`, `4.08 MHz` 99%-power bandwidth at `2433`, `2452`, `2471 MHz`, respectively, for `UXURC4U2`; the 2007 `UXURC4U` report shows an approximately `3.02 MHz` 20 dB delta on its low-channel plot | **[PRIMARY]** FCC test reports. Analyzer method, 99%-power width, and 20 dB width are different measurements and must not be compared as if interchangeable. These values corroborate a wide remote waveform, while local IQ must establish actual demodulator settings. |
| Finished App Bridge width | approximately `0.12–0.14 MHz` 99%-power bandwidth and `0.08–0.11 MHz` 20 dB bandwidth | **[PRIMARY]** `UXUPC` Part 15.249 test report. This sharply differs from the remote and is not compatible with assuming the bridge uses the captured `2 Mbps` nRF24 PHY. |
| Finished Platinum wall-switch width | `1.80`, `1.98`, and `1.68 MHz` 20 dB bandwidth at `2433`, `2452`, and `2471 MHz` | **[PRIMARY]** `UXUWS4U` test report. This independently supports a wide legacy direct-control link, without proving the five-byte payload. |
| RF channels | nRF `RF_CH` `33`, `52`, `71` (`0x21`, `0x34`, `0x47`) | **[CAPTURE]/[REFERENCE]** Community SPI/logic captures and the reference sketch. |
| Center frequencies | `2433`, `2452`, `2471 MHz` | **[PRIMARY]** Nordic uses `f_center = 2400 MHz + RF_CH`; FCC filings for the legacy remote, wall switch, and bridge identify `2433–2471 MHz`, and the remote reports name all three centers. Shared centers do not establish shared modulation, data rate, or framing. |
| Address width | 3 bytes | **[CAPTURE]** Direct register dump. |
| TX address | `e7 e7 e7` (three active bytes) | **[CAPTURE]/[REFERENCE]** The register display prints `e7e7e7e7e7`, but `SETUP_AW` was 3 bytes, so only three bytes are on air. The reference sketch uses `{0xe7,0xe7,0xe7}`. |
| Payload width | fixed 5 bytes | **[CAPTURE]** `RX_PW_P0 = 0x05`; logic-analyzer report says each payload load contains five bytes. Dynamic payload is off. |
| CRC | enabled, 16 bit | **[CAPTURE]** Register dump reports `CONFIG = 0x0c` and 16-bit CRC. |
| Auto acknowledgment | disabled (`EN_AA = 0`) | **[CAPTURE]** Direct register dump and logic-analyzer observation. |
| Automatic retries | disabled (`ARC = 0`) | **[CAPTURE]** Reported explicitly; the reference sketch also programs zero retries. |
| Dynamic payload / feature register | disabled (`DYNPD = 0`, `FEATURE = 0`) | **[CAPTURE]** Direct register dump. |
| Original remote power setting | `RF_SETUP = 0x0c`, which decodes to `RF_PWR = 10` (nominal `-6 dBm` on a genuine nRF24L01+) | **[CAPTURE]/[PRIMARY]** Register dump plus Nordic register definition. The reference sketch instead selects `RF24_PA_MAX`; that is a replay choice, not an original-remote fact. |

For the hand remote, `8–10 MS/s` complex sampling per center is a practical starting point and covers the FCC-measured 99%-power widths with margin. The three centers span 38 MHz, so a receiver needs roughly `42 MHz` of genuinely usable instantaneous bandwidth to include the widest reported remote signal at both outer centers. Otherwise use three synchronized receivers or repeat controlled button presses while tuning one channel at a time. The bridge’s narrow waveform can be recorded at a lower rate after discovery, but initially use the same higher-rate captures so an incorrect bandwidth assumption cannot hide structure.

### Channel use

**[CAPTURE]** The original remote was reported to send one packet on a channel, change channel, and repeat across all three channels. This is rapid sequential hopping, despite an FCC report’s informal wording that the remote transmits on three channels “simultaneously.” The likely sequence is `2433 → 2452 → 2471 MHz`, matching the reference implementation, but the starting channel and exact order are **[UNKNOWN]** until a synchronized local capture proves them.

The shades may listen on only one of the three channels, or may have another receive strategy. That is also **[UNKNOWN]**. The three-channel repetition is best understood as redundancy against interference, not as proof that separate shades are assigned separate frequencies.

## Radio configuration

The following is the closest known faithful nRF24 configuration for Platinum transmission:

```text
channel             33, 52, or 71 (changed between packets)
air rate            2 Mbps
address width       3 bytes
TX address          e7 e7 e7
payload width       5 bytes, static
CRC                  16 bit
auto ACK             off
automatic retries    0
dynamic payload      off
```

An nRF24L01+ handles preamble, address, and CRC in hardware. Code supplies only the five application bytes. A software-defined radio must generate the full over-the-air frame described later.

## Five-byte application payload

The byte offsets below are zero-based. `ID0` and `ID1` are installation-specific bytes learned by the shades.

| Offset | Name | Known values | Meaning and confidence |
| ---: | --- | --- | --- |
| 0 | `ID0` | Example capture: `0x03`; reference-sketch example: `0x9a` | **[CAPTURE]/[REFERENCE]** First byte of a two-byte remote/system identity. It is not part of the Nordic RF address. |
| 1 | `ID1` | Example capture: `0xc1`; reference-sketch example: `0x8d` | **[CAPTURE]/[REFERENCE]** Second identity byte. Shades reportedly reject an identity they have not learned. Uniqueness and enrollment semantics are **[UNKNOWN]**. |
| 2 | mode/state | `0x20` when a group is active; reference comments report `0x01` when no group is selected | `0x20` is **[CAPTURE]** for normal group commands. The `0x01` interpretation is **[REFERENCE]** only. |
| 3 | group mask | `0x01`, `0x02`, `0x04`, `0x08`, `0xff`; possibly `0x00` for none | **[CAPTURE]** One-hot values select Groups 1–4 and `0xff` selects All. `0x00` is **[REFERENCE]** for no active group. |
| 4 | action/state | `0xa1`, `0xa2`, `0x21`, `0x22`; reference comments also report `0x80` in the no-group state | **[CAPTURE]** `0xa1` Up pressed/held, `0xa2` Down pressed/held, `0x21` release tail after Up, `0x22` release tail after Down. `0x80` is **[REFERENCE]** and its semantic meaning is **[UNKNOWN]**. |

### Group values

| Selection | Byte 3 |
| --- | ---: |
| Group 1 | `0x01` |
| Group 2 | `0x02` |
| Group 3 | `0x04` |
| Group 4 | `0x08` |
| All groups | `0xff` |
| No selected group, reported by reference sketch | `0x00` |

The one-hot values strongly suggest a bit mask, and the reference sketch says combinations are accepted. That remains **[UNKNOWN]** for this installation until combinations such as `0x03` are captured or tested. `0xff` may be a special “All” code; it is not proof that bits 4–7 address Groups 5–8.

### Action values

| Event | Byte 4 | Confidence |
| --- | ---: | --- |
| Up button pressed/held | `0xa1` | **[CAPTURE]** |
| Down button pressed/held | `0xa2` | **[CAPTURE]** |
| Up button released | `0x21` | **[CAPTURE]** |
| Down button released | `0x22` | **[CAPTURE]** |
| No-group state reported in reference comments | `0x80` | **[REFERENCE]** |

The relation `0xa1 → 0x21` and `0xa2 → 0x22` suggests that bit 7 marks an asserted/held command while the low bits encode direction. That is an **[INFERENCE]**, not a confirmed bit-field definition. Do not name `0x21` or `0x22` “stop” until behavior is tested: the capture proves only that each follows release of the corresponding button.

### Command examples

For a captured example identity of `03 c1`:

```text
03 c1 20 01 a1    Group 1 Up, button held
03 c1 20 01 21    release tail after Group 1 Up
03 c1 20 01 a2    Group 1 Down, button held
03 c1 20 01 22    release tail after Group 1 Down
03 c1 20 ff a1    All Up, button held
03 c1 20 ff a2    All Down, button held
```

The `03 c1` values belong to the forum contributor’s remote, not this installation. The `9a 8d` values in the local sketch are likewise an example/configuration value, not evidence of the user’s actual identity. Capture the local remote ID rather than guessing it.

No rolling counter, encryption, or challenge/response appears in the legacy five-byte application payload. That means replay is plausible and has been reported to work. It is not proof that every Platinum revision is stateless, nor that the two identity bytes are globally unique.

## Timing and repetition

### Original-remote observations

The best available direct timing report came from a logic analyzer attached to the remote’s nRF24 SPI and control lines:

- **[CAPTURE]** CE was pulsed high for approximately `13 µs`, satisfying Nordic’s minimum `10 µs` transmit trigger.
- **[CAPTURE]** The contributor reported approximately `193 µs` to load the next five-byte payload, change channel, and reach the next transmit operation. The precise measurement endpoints were not published, so treat this as approximate.
- **[CAPTURE]** One payload was sent per channel in a repeating three-channel rotation, around 30 rotations in one observed operation.
- **[CAPTURE]** While Up or Down remained held, the corresponding `0xa1` or `0xa2` payload repeated.
- **[CAPTURE]** Releasing the button changed the action byte to `0x21` or `0x22` and produced a finite tail. One report estimated about 60 tail packets; a short-press capture on one monitored channel counted 21 held-command packets followed by 18 release-command packets. Counts therefore need local statistical measurement, not a single hard-coded constant.
- **[CAPTURE]** There was no ACK/error polling in the observed SPI sequence; the controller loaded a payload, changed channel, and pulsed CE blindly.

The 2007 FCC test report contains a regulatory duty-cycle calculation based on `92 µs × 14 × 5 = 6.4 ms` in a 100 ms window. **[PRIMARY]** This is useful corroboration that transmission is bursty, but the report does not define those factors as protocol fields and it does not establish channel order or application-frame counts.

The App Bridge report uses a different `0.108 ms` burst element and a `21.6 ms` on-time calculation per 100 ms. **[PRIMARY]** That number belongs to the narrow bridge test mode and must not be substituted for handheld-remote frame timing.

### Reference-sketch behavior is not the original protocol

The local sketch deliberately floods the receiver: four outer passes of 999 payload submissions, a nominal `75 µs` delay in the inner loop, and a channel change after every submission. That is **[REFERENCE]**, not a captured Platinum timing requirement. Its `RF24_PA_MAX` setting also differs from the captured original register value.

Do not reproduce the four-by-999 flood in a first SDR transmitter. Besides consuming unnecessary airtime, queued `writeFast()` calls and channel writes make the sketch’s source-level timing an unreliable description of what happened at the antenna. Start with the measured original pattern, then determine the minimum reliable repeat count experimentally.

## Full over-the-air framing for an SDR

### Datasheet-consistent expectation: Enhanced ShockBurst framing

The nRF24L01+ Product Specification v1.0 §7.9 says that ShockBurst compatibility requires all of the following: `EN_AA = 0`, automatic retry count `ARC = 0`, **and** an air rate of `1 Mbps` or `250 kbps`. Section 7.9.1 says that compatibility-mode ShockBurst omits the 9-bit Packet Control Field (PCF). Platinum has the first two reported settings, but the working capture/replay configuration is explicitly `2 Mbps`. It therefore does not meet Nordic’s documented no-PCF compatibility conditions.

The datasheet-consistent **[INFERENCE]** is consequently an Enhanced ShockBurst-format packet with automatic acknowledgment and retransmission features disabled:

```text
8-bit preamble | 24-bit address | 9-bit PCF | 40-bit payload | 16-bit CRC
```

That is 97 on-air bits, nominally `48.5 µs` at `2 Mbps`, excluding transmitter startup, ramp, and any inter-frame idle time. Per Nordic §7.3, the PCF contains six payload-length bits, a two-bit PID, and `NO_ACK`; CRC covers address, PCF, and payload and uses polynomial `x^16 + x^12 + x^5 + 1` (`0x1021`) with initial value `0xffff`. With static payload length, Nordic says the length field is not used, but the PCF remains part of an Enhanced ShockBurst frame. The exact on-air values of those unused length bits, the initial PID, and `NO_ACK` must be recovered from IQ rather than guessed.

If each repeated frame is loaded as a new TX payload, the two-bit PID should advance and wrap. Thus “identical” five-byte FIFO payloads can still produce a four-state PCF/CRC pattern on air. The community logs cannot reveal that because an nRF24 receiver removes PCF and CRC before returning the payload.

This is still not a locally verified waveform. The expected `48.5 µs` does not directly explain the FCC report’s `92 µs` duty-cycle element, and the reported register/configuration evidence is community-derived.

### Falsifiable alternative: legacy ShockBurst framing

Raw IQ could instead show the no-PCF form:

```text
8-bit preamble | 24-bit address | 40-bit payload | 16-bit CRC
```

That is 88 bits, nominally `44 µs` at `2 Mbps`; CRC would cover address and payload. This alternative conflicts with Nordic’s documented `1 Mbps`/`250 kbps` compatibility condition, so it is not the leading expectation. Retain it as a test because the exact original silicon, register sequence, and on-air framing have not been independently captured. Frame length and CRC—not assumptions in an nRF24 decoder—must decide the issue.

### What a hardware nRF24 receiver hides

The five bytes printed by Arduino code are only the FIFO payload. A configured nRF24 receiver strips the preamble, address, and CRC (and, if present, PCF). Therefore a payload log cannot prove:

- on-air address/byte order;
- bit order within each byte;
- GFSK mark/space polarity;
- whether PCF is absent;
- CRC serialization or final byte order;
- exact carrier-on duration and inter-frame gap.

`e7 e7 e7` is symmetric across bytes, and `0xe7` is also unchanged by bit reversal. That makes both address byte order and within-byte bit order impossible to infer from the configured value alone. Use the non-symmetric payload bytes and a known CRC to resolve serialization from IQ.

### SDR transmit requirements still marked unknown

- **[UNKNOWN]** Exact over-the-air bit order and byte order as observed by the selected SDR demodulator.
- **[UNKNOWN]** Which discriminator polarity maps to logical 1; FSK inversion produces an equally plausible first decode.
- **[UNKNOWN]** CRC byte order and any implementation-specific final presentation. The polynomial and seed are known, but the captured bitstream must validate the entire convention.
- **[UNKNOWN]** Whether local IQ confirms the datasheet-consistent 97-bit Enhanced ShockBurst frame or instead reveals the 88-bit no-PCF alternative.
- **[UNKNOWN]** Exact preamble representation in the SDR’s bit convention. Nordic chooses an alternating `0x55`/`0xaa` pattern based on the first address bit.
- **[UNKNOWN]** Whether the finished transmitter adds any coding or whitening not visible in the FIFO view. Nordic’s documented packet format does not specify either, so the working expectation is neither; only raw IQ can promote that expectation to verified fact.
- **[UNKNOWN]** Exact Gaussian pulse shaping/filter bandwidth, transmitter ramp behavior, and actual deviation of the finished remote. `±320 kHz` is the Nordic typical chip value, not a local measurement.
- **[UNKNOWN]** Exact channel order, retune settling gap, repeat count distribution, and release-tail duration for the hand remote.
- **[UNKNOWN]** Bridge modulation, symbol rate, frame format, addressing, CRC/checksum, and payload semantics. Its FCC bandwidth rules out assuming the hand-remote `2 Mbps` configuration.

## Rigorous local capture and validation plan

The reference bench, safe physical interconnects, and public validation status are maintained in [Testing and validation](testing.md); required quantities and example parts are in the [Bill of materials](bom.md). This section defines the protocol-specific capture and evidence requirements.

### Tool and receiver implications

- The primary capture/transmit platform is a Nuand bladeRF 2.0 micro; both the [xA4](https://www.nuand.com/product/bladerf-xa4/) and [xA5](https://www.nuand.com/product/bladerf-xa5/) provide the required RF-side capability. The platform provides `61.44 MS/s`, `56 MHz` usable instantaneous bandwidth, two receive and two transmit paths, full-duplex operation, and GNU Radio/SoapySDR support. A capture centered near `2452 MHz` can therefore preserve all three main channels and the `2440 MHz` control channel on one timebase. Host-side processing is sufficient; the FPGA-size differences do not affect this capture plan and the larger xA9 is not required.
- A [HackRF One](https://hackrf.readthedocs.io/en/stable/hackrf_one.html) is half-duplex and supports 2–20 MS/s. It can capture one Platinum channel well, but it cannot span the full 38 MHz from `2433` through `2471 MHz` in one recording. Repeat a controlled action at each center.
- A [USRP B210](https://www.ettus.com/all-products/ub210-kit/) is an equally capable `56 MHz`, `2×2`, full-duplex alternative with the mature UHD ecosystem. It is appropriate when one is already available or UHD/NI support is a requirement, but it is not necessary for this protocol.
- [gr-nrf24-sniffer](https://github.com/kittennbfive/gr-nrf24-sniffer) is a modern GNU Radio/HackRF receive path with options for 2 Mbps, fixed payloads, CRC-16, and 3–5-byte addresses. Its author marks non-five-byte addresses as untested, so validate it against synthetic frames before trusting results. It is AGPL-3.0-or-later and is not incorporated here.
- [Bastille Research's gr-nordic](https://github.com/BastilleResearch/gr-nordic) is a useful historical Enhanced ShockBurst reference, but the inspected 2016 revision targets GNU Radio 3.7/Python 2-era tooling and contains parsing/CRC offsets specialized around a five-byte address. Do not use it unmodified for this three-byte-address protocol.

For a correlated hardware trace, a standard [Saleae Logic 8](https://www.saleae.com/products/logic-8) can sample the six relevant remote lines—`SCK`, `MOSI`, `MISO`, `CSN`, `CE`, and `IRQ`—at `50 MS/s`. Only attach it to a spare remote that can tolerate soldered probe wires; do not endanger the last working controller. One or preferably two [Nordic nRF52840 DKs](https://www.nordicsemi.com/Products/Development-hardware/nrf52840-dk) provide programmable `2 Mbps` proprietary-radio reference endpoints that Nordic documents as on-air compatible with the nRF24L family. Actual legacy hardware remains the final interoperability oracle.

An nRF24L01+ receiver is still valuable beside an SDR: it can confirm the five FIFO bytes while the SDR preserves the PCF, CRC, modulation, and timing the chip hides. For conducted SDR loopback, Nuand recommends at least `30 dB` attenuation; use `40 dB` for margin, terminate every active transmitter port in `50 ohms`, and never connect TX directly to RX. At `61.44 MS/s` with signed 16-bit I/Q, one receive stream is about `245.76 MB/s`, so use a direct USB 3 connection, NVMe storage, and short or triggered recordings.

### 1. Identify and preserve the hardware baseline

Record photographs and labels for every remote, wall switch, shade motor/controller, repeater, and bridge. Include part number, FCC ID, manufacture date, and the shade group worksheet. Hash and retain any firmware/app packages obtained later. Do not classify a device as Platinum solely from enclosure shape.

Make a read-only network inventory of the bridge at its private-LAN address separately. Network requests and RF events should share timestamps during later experiments, but network behavior must not be allowed to redefine RF fields without an RF capture.

### 2. Capture RF before transmitting

For each of `2433`, `2452`, and `2471 MHz`:

1. Capture complex IQ at `8–10 MS/s` or more, with automatic gain disabled and enough attenuation to avoid front-end clipping.
2. Record at least two seconds before and after the event.
3. Perform at least ten repetitions of each event: Groups 1–4 and All, Up and Down, short tap and long hold.
4. Capture group-selection button presses separately, button release, power-up, battery insertion, and—only if operationally safe—no-group and multi-group states.
5. Trigger the same semantic actions from the hand remote and from the original App Bridge, retaining synchronized timestamps but labeling the source. Do not expect their symbol rates or frames to match.

If available, make a simultaneous wideband capture spanning approximately `2431–2473 MHz`. Otherwise repeat a scripted test matrix on each tuned center. Keep the transmitter several wavelengths away or add attenuation; a nearby remote can overload an SDR even when the waterfall looks clean.

Analyze bridge captures as an independent discovery problem: measure modulation, symbol rate, deviation, burst structure, and any repeater response before applying the nRF24 framing model. A time-correlated wide burst appearing after a narrow bridge burst at the repeater would be direct evidence of protocol translation. If a spare repeater is available, a high-impedance logic-analyzer capture of its proven nRF24LU1+ SPI/control activity is more decisive than guessing from RF alone; do not probe an irreplaceable board without a mechanically safe connection plan.

### 3. Correlate RF with the remote’s digital bus

An optional but decisive capture uses a high-impedance logic analyzer on `SCK`, `MOSI`, `MISO`, `CSN`, `CE`, and `IRQ` between the remote MCU and radio. Sample fast enough to decode the SPI clock with margin (for example, `≥25 MS/s`, preferably `50 MS/s`). Capture:

- all register writes after selecting a group;
- every `W_TX_PAYLOAD` byte sequence;
- every `RF_CH` write;
- CE rising/falling edges;
- status-register reads and any FIFO flush/reuse commands.

Do not probe a fragile or irreplaceable board unless the connection method is mechanically safe. A passive SDR capture plus a known-address nRF24 receiver is sufficient for the first phase.

### 4. Use an independent nRF24 payload capture

Configure a receiver for `2 Mbps`, 3-byte `e7 e7 e7`, fixed 5-byte payload, no auto-ACK, and each known channel. Record raw payloads and timestamps without filtering to only the two presumed ID bytes. This provides a second view that is easier to parse than IQ, while IQ retains the framing that the nRF24 hardware removes.

The “two-byte address” pseudo-promiscuous trick from Goodspeed/Pullens is useful when the RF address is unknown. Here the three-byte address is already strongly evidenced, so a correctly configured normal receive pipe is the cleaner primary method.

### 5. Decode and falsify the framing hypotheses

For each high-SNR burst:

1. Estimate carrier offset and the two GFSK deviation peaks; verify approximately `2 Msymbol/s` and `±320 kHz` before slicing bits.
2. Test both discriminator polarities and all plausible bit alignments against the alternating preamble and `e7 e7 e7` address.
3. Test the datasheet-consistent 97-bit Enhanced ShockBurst form, including the 9-bit PCF and CRC over address, PCF, and payload. For repeated identical FIFO payloads, test the expected two-bit PID progression rather than assuming every RF frame is bit-identical.
4. Also test the falsifiable 88-bit ShockBurst alternative, computing CRC-16 over address plus five payload bytes. Prefer neither merely because a demodulator happens to find a preamble; require consistent length and CRC evidence.
5. Accept a convention only when it validates CRC across all commands, all three channels, and multiple captures—not because one frame happens to match.
6. Compare decoded payloads with the independent nRF24 capture and the known user action.

A useful acceptance threshold is at least 99% CRC-valid decoding on clean, non-clipped bursts, with every invalid frame explainable by low SNR, collision, or capture truncation. Report both total and per-channel rates.

### 6. Measure timing as distributions

Export one row per RF frame with at least:

```text
capture_id, source_device, requested_action, channel_hz,
burst_start_ns, burst_end_ns, gap_from_previous_ns,
address_hex, payload_hex, crc_rx, crc_ok, rssi_or_power
```

Derive channel order, time between CE/RF bursts, rotations per short tap, frames per second while held, and release-tail length. Publish median, minimum, maximum, and percentile ranges. Avoid turning one forum observation into a fixed constant.

### 7. Validate transmission conservatively

Only after receive decoding passes CRC:

1. Generate one known frame at the lowest usable output power and verify it with a second receiver or a cabled/attenuated setup.
2. Confirm spectrum center, occupied bandwidth, frame length, and CRC before exposing a shade.
3. Try the locally captured identity and Group 1 with a small, original-like three-channel sequence.
4. Use an intentionally wrong identity as a negative control; the shade should not move.
5. Test every group and direction for at least 30 trials, recording success rate and unintended responses.
6. Determine the minimum reliable repetitions, then add a modest reliability margin rather than reproducing the reference sketch’s flood.
7. Test release-tail packets separately to determine whether they stop motion, change manual-control behavior, or are ignored once motion begins.

Transmit only to equipment you own or are authorized to test, at compliant power, and under the rules for the local jurisdiction. The FCC grants document the original products, not a home-built SDR transmitter.

### 8. Archive reproducible evidence

Store for every experiment:

- original IQ and logic-analyzer files, never edited in place;
- SHA-256 hashes;
- SDR model, serial, clock source, sample rate, center frequency, gain, antenna/attenuator, and physical distance;
- UTC timestamp plus local timezone;
- decoder/transmitter commit ID and dependency versions;
- decoded CSV/JSON and a short lab note describing the physical action;
- photographs of the tested device label and setup.

Promote an item from **[CAPTURE]** or **[INFERENCE]** to locally verified only when another person can reproduce it from the archived raw data.

## Open questions

1. What are this installation’s two hand-remote identity bytes?
2. Does local IQ confirm the expected 97-bit Enhanced ShockBurst frame and its PID progression, or reveal the 88-bit no-PCF alternative?
3. What exact bit order, GFSK polarity, and CRC byte order appear in SDR output?
4. What is the true channel order and inter-channel timing at the antenna?
5. How many rotations are necessary for reliable operation, and do shade models differ?
6. What do release codes `0x21`/`0x22` do beyond marking button release?
7. Are arbitrary group masks accepted, or is `0xff` a special broadcast code?
8. Does `0x01 00 80` represent a real no-group packet, and when is it emitted?
9. Are there legacy commands for stop, favorite/intermediate position, tilt, setup, enrollment, or scene recall?
10. What modulation, symbol rate, framing, and payload does the narrowband App Bridge signal use?
11. Does a Platinum repeater translate narrow bridge frames into the wide hand-remote waveform, and can a network request be correlated across both hops?
12. Are there meaningful hand-remote/wall-switch differences among `UXURC4U`, `UXUWS4U`, and `UXURC4U2`?

## Provenance, credits, and licensing

This specification is an independent factual summary. No third-party source code has been copied into the repository by this document.

| Contributor/source | Work used here | License/provenance treatment |
| --- | --- | --- |
| **dpinvidic (Dan)** — [Arduino forum protocol-investigation thread](https://forum.arduino.cc/t/nrf24l01-hack-on-hunter-douglas-shades/676940) | Original Platinum register dump, five-byte commands, release packets, SPI/CE timing, hopping, and repeat observations | Forum posts and attachments do not state an open-source license. Facts are summarized and attributed; code is not copied. |
| **zergraph** — [ESP8266/nRF24 Platinum post](https://forum.arduino.cc/t/esp8266-and-nrf24l01-hunter-douglas-platinum-remote/918887) and [attached sketch](https://forum.arduino.cc/uploads/short-url/akOJ1E1YxEtv4hm7H9ZNA28BVNk.ino) | Demonstrated replay of part `2984495100`, documented payload interpretation, and supplied the attached sketch used as a provenance reference | The sketch has no license header and the post does not grant a downstream software license. It is reference/provenance only. Do not copy, modify, redistribute, or incorporate it into project code unless the author supplies a compatible license or permission. Arduino’s [Terms](https://www.arduino.cc/en/terms-conditions) grant rights to Arduino; they are not a general open-source grant to downstream users. |
| **gpduino** — [PacketDissector/address-discovery post](https://forum.arduino.cc/t/nrf24l01-hack-on-hunter-douglas-shades/676940/33) | nRF24 pseudo-promiscuous capture method and the explicit warning that Pebble hardware/protocol differs | The inspected attachment has SHA-256 `1f802b311f289725f8f7142742035c777df8470b4e8e06ca67ea34896d9bcfbf` and no explicit license. Method and findings are credited; code is not copied. The zergraph sketch states that it is derived from gpduino’s work, so any future reuse needs both provenance and license review. |
| **Travis Goodspeed** — [“Building a Promiscuous nRF24L01+ Packet Sniffer”](https://archive.conference.hitb.org/hitbsecconf2011ams/index.html_page_id%3D1391.html) | Original short-address/disabled-CRC nRF24 sniffing technique credited by gpduino | Research method cited; no code copied here. |
| **Ivo Pullens / Yveaux** — [`NRF24_Sniffer`](https://github.com/Yveaux/NRF24_Sniffer) | Practical nRF24 sniffing workflow credited by gpduino | Repository is GPL-3.0. No code copied. Any future incorporation must preserve GPL-3.0 obligations. |
| **TMRh20 and nRF24/RF24 contributors** — [`RF24`](https://github.com/nRF24/RF24) and [address-width issue 303](https://github.com/nRF24/RF24/issues/303) | Radio API and discussion used by the forum sketches | RF24 is GPL-2.0-only. No library source is copied by this document. Any future firmware that links RF24 must be a separately licensed deliverable and satisfy RF24's GPL-2.0-only requirements; do not assume the host software license governs that combined work. |
| **Nick Gammon** — [`Regexp`](https://github.com/nickgammon/Regexp) | Regex library credited by gpduino’s PacketDissector sketch | Not used in this project document or copied. Retained in the credit chain because the upstream sketch explicitly acknowledges it; confirm its license before reuse. |
| **Johannes Pohl and Andreas Noack** — [Universal Radio Hacker](https://github.com/jopohl/urh) | Tool used by gpduino for the distinct Pebble capture and a possible tool for local IQ analysis | GPL-3.0; no code copied. Tool output is evidence only when raw capture and settings are retained. |
| **Nordic Semiconductor** — [nRF24L01+ Product Specification v1.0](https://docs-be.nordicsemi.com/bundle/nRF24L01P_PS_v1.0/raw/resource/enus/nRF24L01P_PS_v1.0.pdf) | GFSK PHY, channel formula, deviation/bandwidth, packet framing, timing minimum, and CRC definition | Manufacturer documentation is copyrighted. This document cites and paraphrases technical facts; it does not redistribute the data sheet. |
| **Nuand** — [bladeRF 2.0 micro xA4](https://www.nuand.com/product/bladerf-xa4/) and [bladeRF accessories guidance](https://github.com/Nuand/bladeRF/wiki/bladeRF-Accessories) | SDR bandwidth, channel/duplex capabilities, software compatibility, and conducted-loopback safety guidance | Manufacturer specifications and documentation are cited and paraphrased; no code is incorporated. |
| **Saleae** — [Logic 8](https://www.saleae.com/products/logic-8) and [channel/sample-rate guidance](https://www.saleae.com/support/logic-software/capturing-data/what-sample-rate-settings-are-available) | Logic-analyzer channel count and simultaneous digital sample rate used to plan the remote SPI/CE/IRQ trace | Manufacturer specifications are cited and paraphrased; no software or documentation is redistributed. |
| **Hunter Douglas, SMK, Nemko, TÜV SÜD, and the FCC filing record** — [`UXURC4U`](https://fccid.io/UXURC4U), [`UXUWS4U`](https://fccid.io/UXUWS4U), [`UXURC4U2`](https://fccid.io/UXURC4U2), [`UXUPC`](https://fccid.io/UXUPC), [`UXUPR`](https://fccid.io/UXUPR) | Product identity, certified frequency range, named channel centers, modulation, power, regulatory bandwidth, and the Repeater BOM that identifies its nRF24LU1+ | Regulatory exhibits are linked and factual findings are summarized. Bridge internal-photo markings are unreadable, so no exact Bridge RF chip is claimed. No exhibit is redistributed. |

When implementation begins, write new transmitter/decoder code independently from this factual specification and locally captured evidence, without copying the unlicensed Arduino attachments. If a third-party implementation is intentionally incorporated, record its exact commit, copyright notice, license, modifications, and required notices in the repository before merging it.

## Source index

- [Arduino: legacy Platinum register/payload/timing investigation](https://forum.arduino.cc/t/nrf24l01-hack-on-hunter-douglas-shades/676940)
- [Arduino: zergraph’s part `2984495100` replay project](https://forum.arduino.cc/t/esp8266-and-nrf24l01-hunter-douglas-platinum-remote/918887)
- [FCC: original Platinum remote `UXURC4U` test report](https://fccid.io/m/fa3a1a00dbbd2dcb57442c97e26e018682903603b417ae840101f0b276d08809.pdf)
- [FCC: Platinum App Bridge `UXUPC`](https://fccid.io/UXUPC)
- [FCC: Platinum wall switch `UXUWS4U`](https://fccid.io/UXUWS4U)
- [FCC: Platinum Repeater `UXUPR`](https://fccid.io/UXUPR)
- [FCC: Platinum remote revision `UXURC4U2`](https://fccid.io/UXURC4U2)
- [FCC: `UXURC4U2` RF test report](https://fcc.report/FCC-ID/UXURC4U2/1688109.pdf)
- [FCC: `UXUPC` Part 15.249 RF test report](https://fccid.io/UXUPC/Test-Report/SC1206696B-FCC-Part-15-249-RSS210-Test-Report-1757162)
- [FCC: later PowerView/Pebble remote `UXURC4U3`](https://fccid.io/UXURC4U3)
- [Nordic: nRF24L01+ Product Specification v1.0](https://docs-be.nordicsemi.com/bundle/nRF24L01P_PS_v1.0/raw/resource/enus/nRF24L01P_PS_v1.0.pdf)
- [Goodspeed: promiscuous nRF24L01+ sniffing talk](https://archive.conference.hitb.org/hitbsecconf2011ams/index.html_page_id%3D1391.html)
- [Pullens/Yveaux: `NRF24_Sniffer`](https://github.com/Yveaux/NRF24_Sniffer)
- [nRF24/RF24 library](https://github.com/nRF24/RF24)
