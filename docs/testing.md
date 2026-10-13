<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Testing and validation

Status review: 2026-10-13

This document defines the canonical repeatable test environment, safety rules, evidence gates, and project validation status. The [reference bench lab log](lab-log.md) records sanitized capability qualifications and test history, but it is explicitly non-canonical: another contributor may use different hardware that satisfies the requirements here and in the BOM. Private network addresses, serial numbers, local paths, shopping prices, and fulfillment details are not recorded in tracked documentation.

Related documents:

- [Bill of materials](bom.md) — quantities, electrical requirements, example parts, and connector compatibility.
- [Reference bench lab log](lab-log.md) — sanitized capability qualifications and results; not a project requirement.
- [LAN protocol](lan-protocol.md) — byte-level bridge protocol and sanitized read-only observations.
- [RF protocol](rf-protocol.md) — RF evidence, waveform hypotheses, capture matrix, and quantitative acceptance criteria.
- [Credits and provenance](../CREDITS.md) — sources and independent-development treatment.

## Reference test environment

| Capability | Requirement | Purpose |
| --- | --- | --- |
| Host | Direct USB 3 SuperSpeed connection and local storage capable of sustained IQ capture | Runs SDR control, capture, decode, and automated tests. |
| Wideband SDR | Coverage through 2.471 GHz and enough instantaneous bandwidth to observe the Platinum channels together | Preserves raw IQ and later generates a waveform only after receive-side validation. |
| Independent 2.4 GHz radios | Nordic proprietary `2 Mbps` support | Cross-checks packet-level behavior independently from the SDR decoder. |
| Logic analyzer | Six or more digital channels at `25 MS/s` minimum, preferably `50 MS/s` | Optionally correlates remote radio control/SPI activity with over-the-air timing. |
| Protected RF bench | 50-ohm standard-SMA interconnects, nominal 40 dB TX-to-RX attenuation, DC isolation, and terminated unused TX ports | Prevents receiver damage during conducted validation. |

At `61.44 MS/s` with signed 16-bit I/Q, one receive stream is approximately `245.76 MB/s`. Use direct USB connectivity, fast local storage, and short or triggered recordings. The exact reference parts and quantities are in the [BOM](bom.md).

## Connector conventions

Thread style does not determine RF contact by itself. Inspect the center conductor every time:

| Connector | Outer interface | Center contact |
| --- | --- | --- |
| Standard SMA male/plug | Internal coupling threads | Pin |
| Standard SMA female/jack | External threads | Socket |
| RP-SMA male/plug | Internal coupling threads | Socket |
| RP-SMA female/jack | External threads | Pin |

The bladeRF RF ports are standard SMA female. A standard-SMA antenna must provide a mating center pin. A common Wi-Fi RP-SMA-male antenna has a center socket; compatible-looking threads do not make it electrically compatible with a standard-SMA-female port.

## Safe RF interconnects

### Receive-only over the air

```text
paired remote / bridge  ~~ over the air ~~>  standard-SMA antenna -> SDR RX1

SDR TX1 -> 50-ohm load
SDR TX2 -> 50-ohm load
SDR RX2 -> disabled; it may remain open
```

Keep both transmit channels disabled in software as well as terminated. Begin with conservative manual RX gain and enough physical separation to prevent clipping.

### Conducted 40 dB loopback

```text
SDR TX1 (SMA female)
  -> 50-ohm SMA male-to-male cable
  -> 30 dB pad (female-to-male connector order)
  -> 10 dB pad (female-to-male connector order)
  -> DC block (female-to-male connector order)
  -> SDR RX1 (SMA female)

SDR TX2 -> 50-ohm load
SDR RX2 -> disabled/open or a spare 50-ohm load
```

One DC block in this single series path blocks DC in both directions. A second is needed only for a second simultaneous RF path. The block isolates the center conductor, not the grounded SMA shells, and therefore is not galvanic isolation.

The one-cable chain needs no barrel adapter. If flexible cable is required at both ends of the rigid component chain, add the female-to-female barrel and second cable listed as conditional items in the [BOM](bom.md). Support every rigid stack so it cannot lever an SDR bulkhead connector.

### Mandatory interlocks

1. Set every RX and TX bias tee **off** before connecting a passive network.
2. Never connect SDR TX directly to RX. Use the complete nominal 40 dB stack; never use the 10 dB pad alone.
3. Assemble and inspect the entire passive path before enabling a transmitter. Terminate every unused active TX channel.
4. Begin at minimum TX gain and conservative manual RX gain. Increase only while watching for clipping and unexpected spurs.
5. Disable TX before changing any cable, adapter, attenuator, DC block, or termination.
6. Strain-relieve cables and mechanically support rigid inline components.
7. Complete conducted validation into an independent receiver before attempting an experimental over-the-air waveform.
8. Transmit only on equipment, frequencies, and power levels the operator is authorized to test.

Nuand's [bladeRF accessory guidance](https://github.com/Nuand/bladeRF/wiki/bladeRF-Accessories) recommends at least 30 dB attenuation for conducted TX-to-RX loopback and warns against direct connection. This project uses nominal 40 dB attenuation for additional margin.

## Hardware qualification

Complete these checks before a component contributes to published evidence:

1. Record the manufacturer, model, revision, connector faces, and a non-sensitive component identifier. Keep serial numbers private unless publication is necessary and intentional.
2. Confirm every standard-SMA male part has a center pin and every standard-SMA female part has a center socket. Reject damaged, recessed, or loose contacts.
3. Check each cable for near-zero center-to-center and shell-to-shell resistance and an open circuit from center to shell. Flex the cable gently while checking for intermittence.
4. Check each dummy load for stable resistance near 50 ohms from center pin to shell.
5. For a DC block, verify shell-to-shell continuity and that center-to-center resistance settles open.
6. Do not infer an attenuator's RF performance from DC resistance. With a known-good 50-ohm load attached, a roughly 50-ohm input is only a gross fault check.
7. Enumerate the SDR, record hardware/firmware/FPGA and host-library versions, and verify the actual software path leaves every bias tee off.
8. Generate a low-level continuous wave through the complete conducted path. Confirm center frequency, stable reception, and absence of clipping at `2433`, `2440`, `2452`, and `2471 MHz`.
9. Without changing TX/RX settings, compare the 30 dB-only path with the 30+10 dB path. Retain the measured incremental change across all four frequencies rather than assuming the label is exact.
10. Substitute each cable, load, and inline block individually so one defective passive cannot masquerade as protocol behavior.

These checks identify gross faults and relative behavior. They do not establish traceable attenuation, insertion loss, return loss, or absolute received power. If calibrated equipment becomes available, retain the measurement setup, uncertainty, and Touchstone or tabular results.

## Automated software tests

Run the offline suite from the repository root:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The fixtures are synthetic and sanitized. They do not contact a bridge, move a shade, or transmit RF.

Result verified on 2026-10-13: **11 of 11 tests passed**.

## Public validation status

| Area | Public status | Evidence or remaining gate |
| --- | --- | --- |
| Offline LAN/RF unit tests | **VERIFIED** | Eleven tests pass against synthetic, sanitized fixtures. |
| LAN transport and inventory parsing | **LIVE-VERIFIED, READ-ONLY** | A sanitized bridge observation verifies TCP framing, banner handling, and `$dat`; see [LAN protocol](lan-protocol.md). |
| Legacy handheld frequencies, radio settings, and five-byte payloads | **SOURCE-SUPPORTED** | Multiple community captures, implementations, Nordic documentation, and FCC exhibits agree; see [RF protocol](rf-protocol.md). |
| Reference RF bench topology | **DOCUMENTED** | BOM, connector map, attenuation, DC isolation, termination, and interlocks are specified here. Component characterization evidence is not yet published. |
| Local handheld raw-IQ waveform | **PENDING EVIDENCE** | No sanitized capture set has yet established serialization, polarity, full framing, and CRC conventions. |
| App Bridge RF waveform | **UNDECODED** | FCC bandwidth evidence establishes that it must be captured independently from the handheld waveform. |
| SDR waveform transmission | **NOT IMPLEMENTED** | Remains gated on receive decoding and conducted validation. |
| Control4 integration | **DEFERRED** | Phase 2, after reliable underlying control is demonstrated. |

Public status describes reproducible technical evidence, not any contributor's private inventory or acquisition state.

## Validation sequence

1. **Software baseline** — the sanitized offline suite passes.
2. **Bench qualification** — connector inspection, bias-tee state, attenuation behavior, terminations, and sustained capture are documented.
3. **Receive-only capture** — raw IQ from the already-paired handheld is collected without enabling any SDR transmitter.
4. **Waveform validation** — symbol rate, deviation, polarity, serialization, frame length, CRC, channel sequence, repeats, and release timing validate across multiple actions and captures.
5. **Independent cross-check** — decoded payloads agree with a Nordic reference receiver and, where mechanically safe, a correlated logic-analyzer trace.
6. **Conducted transmission** — generated frames pass through the nominal 40 dB path and are accepted by an independent receiver without clipping or unexpected spectrum.
7. **Low-power over-the-air validation** — only after every prior gate passes, test the locally captured identity against authorized equipment with positive and negative controls.
8. **Integration** — expose stable commands to higher-level automation only after RF behavior and failure modes are understood.

The complete capture matrix, framing alternatives, timing schema, and quantitative acceptance thresholds are in the [RF protocol validation plan](rf-protocol.md#rigorous-local-capture-and-validation-plan).

## Next publishable milestone

Publish a sanitized, reproducible handheld capture set and decoder result that establish:

- signal parameters and sample metadata;
- frame boundaries and bit convention;
- CRC validity across all three handheld channels and multiple commands;
- channel order, repeat cadence, and release-tail timing; and
- agreement with an independent Nordic receiver.

Bridge RF remains a separate capture and decoding milestone.

## Evidence retention and publication

For every experiment retain:

- immutable original IQ or logic trace plus SHA-256 hash;
- UTC timestamp and timezone;
- source device and requested action;
- hardware model/revision and sanitized setup diagram;
- center frequency, sample rate, bandwidth, clock source, gain, attenuation, and bias-tee state;
- decoder/transmitter commit and dependency versions; and
- decoded output with a concise result or failure note.

Raw captures, local logs, and downloaded exhibits belong under ignored `captures/` or `tmp/` paths. Do not publish household labels, MAC addresses, private network addresses, serial numbers, or unrelated RF traffic. Promote a result to **VERIFIED** only when its retained, sanitized evidence can reproduce the claim.
