<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Testing and validation

Status review: 2026-10-24

This document defines the canonical repeatable test environment, safety rules, evidence gates, and project validation status. The [reference bench lab log](lab-log.md) records sanitized capability qualifications and test history, but it is explicitly non-canonical: another contributor may use different hardware that satisfies the requirements here and in the BOM. Private network addresses, serial numbers, local paths, shopping prices, and fulfillment details are not recorded in tracked documentation.

Related documents:

- [Bill of materials](bom.md) — quantities, electrical requirements, example parts, and connector compatibility.
- [Reference bench lab log](lab-log.md) — sanitized capability qualifications and results; not a project requirement.
- [LAN protocol](lan-protocol.md) — byte-level bridge protocol, sanitized original-bridge observations, and scoped original-app emulator results.
- [RF protocol](rf-protocol.md) — RF evidence, waveform hypotheses, capture matrix, and quantitative acceptance criteria.
- [Credits and provenance](../CREDITS.md) — sources and independent-development treatment.

## Reference test environment

Original-firmware research now has an offline loader and a separately invoked
8051 keepalive probe; see [Original firmware execution](firmware-emulation.md).
Ordinary tests use fictional images and simulator fixtures. The private reference
execution ran the unmodified gateway image's reset initialization, input-ring
code and command dispatcher, producing the expected internal `$ack` response.
It supplies an explicit connection-state fixture and does not qualify full boot,
Ethernet, timer accuracy, storage persistence or RF operation.

The emulator's software checks include the 25-product catalog, UTF-16 name
lengths over fragmented UTF-8 requests, room/shade CRUD, private atomic state
migration and restart, and RF-grant revocation after rebinding or deletion.
Database edits share the RF dispatch lock; tests interleave edits with command
preparation and active fake transmissions. A post-transmission persistence
failure must preserve the completed receipt and prevent another transmission
if the database commit became uncertain. These checks use fictional inventory
and fake radio backends.

An original-app Sync request has separately been observed to make one existing
shade jog after its manual button was pressed, with the original bridge off.
That is an existing-target resync result. It does not establish enrollment with
a newly generated identity, all product features, or Control4 interoperability.
The Android APK was inspected statically for protocol facts; it was not run,
and the live app has now created a persistent room and a new shade. The new
shade reached Sync/Jog; the room required an app restart before it could be
entered. That immediate refresh issue and new-identity enrollment remain open.

Jog now has separate default-off configuration, identity-bound grants, typed
dispatch, and authenticated HTTP/original-app TCP paths. Tests use fictional
identities to check stage-before-release behavior, mixed-batch rejection,
idempotency, no position updates, narrow-profile selection, sequence consumption
on uncertain failure, and device cleanup. Independent offline comparison
matched all ten recovered original Jog packet bitstrings and CRCs. The current
waveform retains the existing 112.134 ms schedule: its first gap is 805 µs
longer than the compared original Jog gap; the remaining nine starts agree
within 7.25 µs after aligning the first short packet. This is packet validation,
not an exact captured-waveform replay or hardware Jog validation.

New-identity enrollment remains unresolved after original-bridge Sync with the
manual receiver button and a captured original Jog without observed movement.
The app's observed 15-second countdown and the emulator's 18-second Sync RX
window describe different timing intervals and do not establish shade acceptance.

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

The IQ receiver tests require the optional analysis dependencies. Install them into the Python environment used for testing, then rerun the suite:

```sh
python3 -m pip install -e '.[analysis]'
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Build the distribution after the complete suite:

```sh
python3 -m pip install build
python3 -m build
```

The fixtures are synthetic and sanitized. They do not contact an actual bridge,
move a shade, or transmit RF. HTTP and LAN tests use temporary loopback servers,
which require local socket-binding permission. The hardware backend uses a fake
library in tests. Optional DSP tests are skipped when NumPy/SciPy are unavailable.

Results verified on 2026-10-23:

| Environment | Result |
| --- | --- |
| Python `3.9.6`, NumPy `1.26.4`, SciPy `1.13.1` | **129 of 129 tests passed**, no skips |
| Python `3.15.0`, without the optional analysis dependencies | **108 passed; 21 optional DSP tests skipped** |

These are historical baselines. The current suite additionally covers the
250 kbps encoder, persistent sequence reservations, concurrent-RX backend
failure paths, original-protocol TCP emulation, shared HTTP dispatch, and
optional NetBIOS discovery. Run the complete current suite rather than using
the older counts as a release check. The earlier 2026-10-13 baseline contained
11 passing tests; it predates the frame and IQ decoder tests.

## Public validation status

| Area | Public status | Evidence or remaining gate |
| --- | --- | --- |
| Offline LAN/RF unit tests | **SOFTWARE VERIFIED** | Synthetic, sanitized fixtures cover LAN framing, packet encoding, state persistence, and fake-radio behavior. Historical counts above predate the emulator; run the complete current suite before release. |
| LAN transport, inventory, and primary position transaction | **COMMAND-LAYER VERIFIED** | Live queries verify framing/banner/`$dat`. One shade's midpoint and restore transactions returned acknowledgements and completion markers; those are not physical position feedback. |
| Legacy handheld frequencies, radio settings, and five-byte payloads | **SOURCE-SUPPORTED; INITIAL LOCAL DECODING** | Local Group 1 Up/Down and following release-tail payloads validate against CRC; register settings and other groups still rely on source evidence. See [RF protocol](rf-protocol.md#initial-local-receive-result--2026-10-23). |
| Reference RF bench topology | **DOCUMENTED** | BOM, connector map, attenuation, DC isolation, termination, and interlocks are specified here. Component characterization evidence is not yet published. |
| Local handheld raw-IQ waveform | **PARTIALLY VALIDATED, RECEIVE-ONLY** | Initial local frames support `2 Mbps`, 88 bits without PCF, MSB-first payload/CRC, and positive discriminator polarity. Private immutable IQ and decode evidence are retained; the full action matrix, qualified timing, public reproducibility package, and independent Nordic receiver cross-check remain pending. |
| App Bridge command-triggered RF | **POSITION FIELDS CAPTURE-SUPPORTED** | Wide 2 Mbps packets correlate with positions `0`, `128`, and `255` across two room identities. Same-shade position comparisons and four same-room shade masks support the field mapping. Emitting component (bridge or repeater) and SDR interoperability remain unproven. |
| Public 2 Mbps waveform transmission | **IMPLEMENTED; LIMITED CONDUCTED CHECKS** | Single-channel 8 MS/s tests recover 993/1,000, 1,000/1,000, and 1,000/1,000 expected packets across the three frequencies. Interoperability of this path and independent receiver validation remain pending. |
| Public 250 kbps bridge/repeater path | **IMPLEMENTED; INITIAL LOCAL OVER-THE-AIR RESPONSES** | Two isolated bladeRF commands produced observed movement on one shade with the original bridge off; the second reached roughly halfway with a repeater indication. Each recording recovered ten transmitted and ten forwarded packets. The public encoder exactly reproduces both working artifacts, and the backend integrates the successful concurrent-RX profile with persistent sequence reservation. Broader repeatability and the cause of earlier failures remain open. See the [lab log](lab-log.md#laptop-reference-captures-and-narrow-candidate--2026-10-24). |
| Local HTTP bridge prototype | **SOFTWARE VERIFIED** | Authenticated group/position commands, disabled-by-default target mappings, serialized dispatch, idempotency, and shutdown have loopback/fake-backend tests. See [prototype guide](bridge-prototype.md). |
| TCP/HTTP bridge emulator and optional discovery | **LOCAL ORIGINAL-APP CONTROL VERIFIED; PARTIAL COVERAGE** | The original app discovered the emulator, completed startup, loaded existing rooms/shades, and sent one primary-position/release transaction. With the original bridge off, the RF backend submitted the command and the operator confirmed roughly halfway movement. A separate TCP transaction produced confirmed closure. Pairing, configuration, scenes, schedules, other features, and broader client/platform compatibility remain unverified. |
| Control4 integration | **UNVALIDATED** | No end-to-end Control4 test has established compatibility with this emulator. |

Public status describes reproducible technical evidence, not any contributor's private inventory or acquisition state.

### Emulator validation scope

Use the [dry-run and live runtime commands](../README.md#bridge-emulator) to
exercise the integrated service. Dry-run must load the same private mappings
and inventory intended for live use, while generating no RF. Verify supported
`$dat`, `$dmy`, feature-04 `$pss`/`$psr`, `$rls`, and app startup date/time/year
flows, rejected unsupported writes, and shared HTTP/TCP serialization. Test both
position request endings, including the app's omitted final hyphen. TCP LAN binding requires explicit
trusted local source CIDRs; HTTP authentication remains separate.

Loopback tests verify `$dmy` replies with `$ack` both while idle and while a
finite Sync backend is blocked. Duplicate actions and other same-connection
commands received during Sync are rejected as busy rather than queued. Tests
also cover fragmented keepalives, serialized replies, disconnect ownership,
and shutdown waiting for the single non-daemon Sync worker without repeating RF.

The live profile is fixed at `2440 MHz`, `250 kbps`, `8 MS/s`, `1.5 MHz`
bandwidth, ten packets in `112.134 ms`, and three seconds of concurrent RX.
Generated IQ matches the two working private artifacts byte for byte. Fake
hardware tests verify that missing RX startup or incorrect active TX readback
prevents IQ submission, cleanup retains device ownership while RX is active,
and uncertain failures consume a sequence without automatic retransmission.
An initial sequence is installation-specific and comes from private records;
tests use fictional values. Keep the state directory across restarts.

Original-code RF probes now independently check bridge and native payload
construction, transaction-byte rollover, native channel rotation and phase
counters. A backend restart regression crosses local ordinals 511→512 and
requires wire command count 1 with transaction 255→0, retaining durable state.
See [Protocol conformance](protocol-conformance.md). These checks do not qualify
the direct backend's whole-train-per-channel schedule or new-identity pairing.

Optional discovery must be checked on the actual LAN with the original client.
UDP 137 may conflict with `netbiosd`; requesting `--discovery-reuse-port` does
not establish that both services receive or answer broadcasts correctly.
The original app discovered the emulator on the exercised LAN setup; this does
not establish UDP port-sharing behavior on other hosts. Initial connection,
inventory display, and one existing shade's primary-position control are now
demonstrated. Pairing, room/shade configuration, scenes, schedules, other feature
channels, and Control4 integration remain unvalidated. Reported positions are
requested state, never sensor feedback or proof of arrival. These limits prevent
calling the implementation a complete original-bridge replacement.

The retained 2026-10-24 app trace establishes this specific sequence:

1. The phone discovered the replacement endpoint and sent date, time, and
   `$chksyYYYY-` startup requests. Date/time replies use source-derived `$done`;
   `$chksy01-` matches a separately captured same-year original-bridge reply.
2. After `$chksy01-`, the app sent `$dat`, received a 759-byte snapshot, and
   displayed the existing rooms and shades. Snapshot size is an observation of
   that inventory, not a protocol requirement.
3. The app sent `$pss03-04-126` with no final hyphen, then `$rls` after the
   staging acknowledgement. Shade ID `03` here is fictional; the value and
   request framing match the capture.
4. The integrated RF backend submitted the finite command with the original
   bridge off. The operator confirmed the selected shade moved to roughly
   halfway. This physical observation is separate from the returned `$cp` and
   action-end records, and does not calibrate motor position.

See the [sanitized app exchange](lan-protocol.md#current-emulator-coverage--2026-10-24)
for the response order and the remaining year-check uncertainties. This is one
existing target's successful control case; repeatability and the unresolved
setup/enrollment paths require their own evidence.

Optional `--protocol-log` captures raw TCP exchanges before parsing so rejected
original-app setup requests can be investigated. Its default bound is two
`1 MiB` private files, each mode `0600`. Tests cover raw-byte preservation,
rotation, concurrent writers, and refusal of symlink/nonregular destinations.
Journal errors are separate from RF outcomes and must not trigger a retry.

### Scope of the initial local receive result

The 2026-10-23 session retained a 30-second background recording and a 60-second handheld recording at `48 MS/s`, with operator-confirmed Group 1 Up–Down twice. Both full files passed sample-range checks without clipping. Decoding recovered the direction commands and following release-tail codes with valid address-plus-payload CRCs. A second independently authored decoder and separate PHY measurements supported the initial interpretation. This is evidence for the captured remote; it does not complete the project-wide validation sequence.

A complete scan recovered `21,585` carrier-supported, CRC-valid 88-bit frames across all three handheld channels, including `11,980` Group 1 direction/release frames. Independent bytewise CRC and zero-residue checks passed for all no-PCF frames. A complete scan of the 30-second background recording found no accepted frames under the same decoder settings. These results support the distinction between command traffic and background RF; they do not establish a general decoder success rate. One retained longer interpretation is a coincident CRC-codeword extension, reported as ambiguous rather than counted as another RF packet; see [RF framing](rf-protocol.md#locally-observed-framing-88-bits-without-pcf).

The observed data frame is `44 µs` at `2 Mbps`, near the end of an approximately `93 µs` RF-energy burst. Roughly `49 µs` of earlier RF energy is not a second validated packet. The local estimated deviation is approximately `±359 kHz`; it is not a calibrated RF measurement. Sample-derived channel order agrees with `2433 → 2452 → 2471 MHz`, but cadence and release timing require further qualification.

The raw SC16Q11 recordings contain no per-block timestamp or overrun metadata. A separate five-second FPGA-counter test at `48 MS/s` had no discontinuities; the `61.44 MS/s` test did. Consequently, a complete byte count or successful CLI exit is insufficient to establish lossless capture, and the short passing counter test must not be generalized to every subsequent IQ file. Use timestamp/overrun-aware recording and longer continuity checks before publishing timing distributions.

No independent Nordic receiver or local SPI trace has yet cross-checked the decoded packets. The full Groups 1–4/All, tap/hold, and repeated-session matrix remains incomplete, and no general `≥99%` decode-success claim is made. The initial recordings were receive-only; subsequent protected transmissions are logged separately. Original IQ, SHA-256 hashes, settings, and private outputs remain under ignored storage; tracked documentation excludes recovered identities and their payload CRCs. See the [lab log](lab-log.md) for bench observations and [RF protocol](rf-protocol.md#initial-local-receive-result--2026-10-23) for the framing interpretation and limitations.

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

Bridge RF has initial local operation evidence, a public encoder/backend, and
one original-app control case. Its separate next milestone is repeatable
integrated operation, broader original-client coverage including enrollment,
and a sanitized reproducibility package for the 250 kbps path.

The initial local Group 1 decoding provides a starting point for this milestone. It does not replace the broader action coverage, evidence publication, capture-continuity checks, or independent receiver agreement listed above.

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
