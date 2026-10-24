<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Reference bench lab log

> **Environment-specific, not canonical.** This file records sanitized capability qualifications and results for Hunter Douglas Platinum protocol work. It does not define what every contributor must own or use. Canonical requirements are in [Testing and validation](testing.md) and the [Bill of materials](bom.md).

Last updated: 2026-10-23 (America/Chicago)

Private network addresses, MAC addresses, household labels, serial numbers, and local filesystem paths are intentionally excluded from this tracked log.

## Capability snapshot

| Capability | Public qualification status | Evidence still required |
| --- | --- | --- |
| USB 3 capture host and storage path | Short counter-stream check passed at `48 MS/s`; `61.44 MS/s` failed continuity | Identify the physical port and qualify longer capture continuity. USB reports SuperSpeed (`5 Gb/s`); five seconds of counter data at `48 MS/s` had no discontinuities. |
| Original Platinum App Bridge LAN/RF reference | Inventory, bounded primary-position transactions, and correlated position-payload comparisons observed | Physical position feedback, emitting component, and SDR-to-shade interoperability are not established; private address and identifiers remain outside the repository. |
| Wideband SDR capture and transmit path | Receive bring-up and limited protected 8 MS/s TX checks completed | bladeRF 2.0 micro xA4 initialized; firmware/FPGA versions recorded below. Independent receiver, calibrated RF response, and observed shade interoperability remain pending. |
| SDR mechanical protection and cooling | Not yet qualified | Verify fit, connector clearance, and ventilation for the selected enclosure. |
| Nordic-compatible `2 Mbps` reference link | Not yet qualified | Record board revisions used for the test and validate a known reference link. |
| Six-channel digital logic capture | Not yet qualified | Record the software version used and validate digital capture before probing a spare remote. |
| Standard-SMA antenna path | Not yet qualified | Inspect center pins, label test antennas, and compare relative response at the Platinum frequencies. |
| RP-SMA antenna substitution path | Not yet qualified | Inspect center sockets and use only through the correct polarity adapter. |
| Conducted-loopback passive path | Operator-confirmed nominal 40 dB path passes limited packet checks | Absolute attenuation and substitution checks remain unqualified. |

Qualification status in this table reflects public evidence, not acquisition or inventory state, and must not be copied into the canonical validation matrix as project-wide status.

## Qualification log

| Date | Item | Check | Result | Sanitized evidence |
| --- | --- | --- | --- | --- |
| 2026-10-23 | USB host and storage | USB enumeration and available local storage | SuperSpeed (`5 Gb/s`); approximately `179 GiB` free before captures | Apple Silicon macOS host; enumerated via a USB 3 hub in the host's USB tree. Physical socket/direct-path inspection remains pending. |
| 2026-10-23 | bladeRF 2.0 micro xA4 | Model, firmware, FPGA, host software | FPGA initialized successfully | `49 KLE`; FX3 `2.4.0-git-a3d5c55f`; FPGA `0.15.3`, temporarily loaded by host; Homebrew `libbladerf 2025.10`, library `2.6.0-git-fcf94233-dirty`, CLI `1.10.0-git-fcf94233-dirty`. No flash programming performed. |
| 2026-10-23 | RF power and routing | Explicitly disable all four bias tees; read state and RF routing | All bias tees off; both TX routes open; no TX stream started | RX1 alone used for receive tests; RX2 route open. User confirmed RX1 antenna and loads on TX1/TX2; component model and connector condition were not independently inspected. |
| 2026-10-23 | Maximum-rate receive stream | Five seconds of requested `61.44 MS/s` FPGA counter samples to local storage | **Failed continuity** despite no CLI stream error | `307,200,000` received words; `591,258` discontinuities. This setup must not use that rate for protocol timing evidence. |
| 2026-10-23 | Reduced-rate receive stream | Five seconds of `48 MS/s` FPGA counter samples to local storage | **Passed this short test** | `240,000,000` consecutive little-endian 32-bit words, from `0` through `239,999,999`, zero discontinuities; `960,000,000` bytes (`192 MB/s`). Does not prove continuity of subsequent raw-IQ recordings. |

FPGA `0.15.3` was selected to match the installed FX3 `2.4.0`, using Nuand's [release compatibility table](https://github.com/Nuand/bladeRF/blob/2025.10/host/libraries/libbladeRF/src/board/bladerf2/compatibility.c). The xA4 image's SHA-256 matched the [manufacturer's archive](https://www.nuand.com/fpga_images/): `eaa415650b6b00e75f1e28c2a860d8f90577b1f4648b2f7b88a65745f464a6db`. The host warns that this firmware/FPGA pair uses legacy USB messages; no firmware upgrade was attempted.

Counter checks used RX1, binary output, `65,536` samples per buffer, `64` buffers, `32` transfers, and a `3,000 ms` transfer timeout. The FPGA `32BIT_COUNTER` input was restored to `BASEBAND` after each test. Counter words were checked for increments of one modulo `2^32` across the complete files, including buffer boundaries.

## Experiment log

| Date | Activity | Result | Public evidence |
| --- | --- | --- | --- |
| 2026-10-13 | Offline Python unit suite | 11/11 passed | Test command and current result are recorded in [Testing and validation](testing.md#automated-software-tests). |
| 2026-10-13 | Read-only bridge discovery | Banner and sanitized `$dat` response observed; `$dmy` produced no device reply in the observation window | Sanitized findings are recorded in [LAN protocol](lan-protocol.md). |
| 2026-10-23 | Offline Python unit suite | 11/11 passed | Ran `PYTHONPATH=src python3 -m unittest discover -s tests -v`; no bridge or RF activity. |
| 2026-10-23 | Initial receive-only background recording | Complete 30-second file; no clipped samples | `48 MS/s`, requested center `2452 MHz` (reported `2451999998 Hz`), `46 MHz` bandwidth, manual `15 dB` gain, onboard VCTCXO; `1,440,000,000` complex SC16Q11 samples. User missed the requested remote-action window, so no remote attribution is claimed. Peak absolute component `614` on a full-scale magnitude of `2048`; unrelated RF energy remains in the private recording. |
| 2026-10-23 | First operator-confirmed handheld recording | Complete 60-second file; user confirmed Group 1 Up/Down twice; no clipped samples | Same receive settings as the background recording; `2,880,000,000` complex samples (`11,520,000,000` bytes). Peak absolute component `1584`; zero out-of-range components. Original IQ, SHA-256, command log, metadata, and energy survey retained privately. Subsequent decode results are recorded below; continuity within this raw-IQ file remains unverified. |
| 2026-10-23 | Complete offline handheld decode | `21,585` CRC-valid, carrier-supported 88-bit frames; Group 1 Up → Down → Up → Down and both release codes recovered | Channel totals: `7,187` at `2433 MHz`, `7,207` at `2452 MHz`, `7,191` at `2471 MHz`. `11,980` frames carry Group 1 commands/releases; `9,605` carry the earlier `01 00 80` state whose trigger remains unverified. All no-PCF CRCs also pass independent bytewise CRC and zero-residue checks. |
| 2026-10-23 | Background negative control | Zero accepted frames in the complete 30-second file | Same three-channel decoder settings as the command recording. This result does not establish a general false-positive rate. |
| 2026-10-23 | Expanded offline software suite | `35/35` passed with analysis dependencies | Python `3.9.6`, NumPy `1.26.4`, SciPy `1.13.1`; Python `3.15.0` without analysis dependencies passes 26 and skips nine optional IQ tests. |

The two raw-IQ files are retained read-only with SHA-256 hashes. The energy survey checks every component for clipping and uses contiguous `4096`-point Hann-windowed FFTs, summarized in `10 ms` bins over `5 MHz` bands centered on each handheld channel. This is a signal-level survey, not a protocol decoder; unrelated traffic and the center DC component are included. The raw SC16Q11 captures contain no per-block timestamps or overrun flags, so the separate counter result must not be treated as proof of their continuity.

The operator-confirmed recording contains eight sustained energy clusters. Subsequent decoding identifies the first four as the `01 00 80` state and the last four as Group 1 Up, Down, Up, Down, each followed by its direction-specific release tail. The exact trigger and meaning of the earlier state remain unresolved. The background recording has no comparable sustained clusters under the same energy rule.

The full decoder also found `222` longer CRC-valid interpretations: `221` failed the RF-tail power check. One remaining interpretation coincides with a correct no-PCF frame and is exactly its valid codeword extended by nine zero bits. It is retained as an ambiguous parser result, not counted among the `21,585` no-PCF frames or interpreted as another command/identity. A raw decoder `frame_count` can therefore count hypotheses rather than unique RF packets. Private JSON/CSV, a timeline, source hashes, and an independently authored decoder's cross-check are retained with the capture.

## Transmitter and bridge prototype work

### Finite transmitter prototype — 2026-10-23

The operator confirmed the protected path `TX1 → SMA cable → 30 dB pad →
10 dB pad → DC block → RX1`, with TX2 terminated. All bias tees were disabled.
These results are protocol checks through the nominal 40 dB path, not a
calibration of its attenuation or absolute RF power.

- An internal digital loopback recovered all 200 generated Up/release packets.
- The external path at `8 MS/s`, TX system gain `50 dB`, RX system gain `40 dB`,
  and `6 MHz` analog bandwidth recovered all 200 generated Up/release packets
  at `2452 MHz`. Lower settings were too weak for complete decoding.
- Full single-channel Down/release bursts contained 500 packets of each type.
  The receiver recovered 993/1,000 expected 88-bit packets at `2433 MHz`,
  1,000/1,000 at `2452 MHz`, and 1,000/1,000 at `2471 MHz`. Every receive file
  had continuous metadata timestamps and no overrun flags or clipped samples.
  Longer CRC-valid zero-extension hypotheses are excluded from these counts.
- Simultaneous `48 MS/s` TX plus `48 MS/s` RX exceeded Nuand's recommended
  `80 MS/s` combined throughput and failed continuity: 13,734 RX overrun flags
  and 13,733 timestamp gaps in this experiment. It is not a valid timing or
  packet-error measurement. Changing RX to `24 MS/s` also changed TX to that
  rate; the backend detects this shared-clock behavior.

The initial bridge backend therefore uses separately tuned `8 MS/s` bursts on
the three frequencies, with tuning/settling gaps. This differs from the
handheld's rapid channel cycling and still requires observed shade operation.
The software decoder, generator, finite hardware backend, and authenticated
local HTTP service are implemented. Subsequent original-bridge transactions
produced decoded position payloads, as recorded below. An independent Nordic receiver, absolute RF measurements, and the
full action matrix remain outstanding; these limited tests do not complete
the canonical validation program.

The original App Bridge was reached on its actual network segment with a
read-only `$dat` query: two rooms, eleven shades, each exposing feature `04`.
Private inventory, raw IQ, metadata, command receipts, and decode artifacts are
retained under ignored local paths. No bridge actuation had been sent at the
time of this entry. Subsequent controlled transactions are recorded below.

### Original-bridge position captures — 2026-10-23

Two bounded primary-position transactions targeted one existing shade: raw
position `128`, followed by its previously reported `255`. Both stages returned
`$done`; releases returned `$act00-00-`; the final inventory again reported
`255`. These are protocol observations, not confirmation that the motor reached
either position. All bladeRF transmitters remained disabled and terminated.

Each recording contains six seconds at `48 MS/s`, center `2452 MHz`, `46 MHz`
bandwidth, and RX gain `15 dB`. Both retain timestamped metadata with two
discontinuities; affected intervals must be excluded from timing claims.
Recording was moved before staging for the second transaction, because an
`$act01-00-` record arrived during the first stage. This does not by itself
establish when RF starts.

The restore recording contains wide `2 Mbps`, 88-bit no-PCF packets. Combining
the baseline and two documented filter variants recovers `2,541` distinct
CRC-valid frames: `2,525` at `2452 MHz` and `16` at `2433 MHz`. Their two-byte
prefix matches the inventory's target room RF identifier. The observed payload
forms are `ROOM_ID | 50 | 08 | FF` followed by `ROOM_ID | 32 | 08 | FF`.
The final `FF` matches the requested position. The `08` mask is consistent with
the target's inventory group field `4`. At this point it was a single-target
mapping hypothesis; subsequent comparisons below isolate position and shade
mask changes. The device-side meanings of `50`/`32` and whether the emitter is
the bridge or a repeater remain open.

Measured pulses are approximately `95 µs` long. Matched low/middle-channel
packets imply roughly `234 µs` channel slots; this is distinct from the earlier
handheld timing. Recovered counts are lower bounds, not a packet-error-rate
denominator. Narrow 1 MS/s survey excerpts distort these wide packets and must
not supply their symbol-rate estimate.

The first raw-`128` recording yielded zero CRC candidates with the baseline
decoder and with `1.0`/`1.3 MHz` low-pass variants over all four candidate
channels. Its energy survey did not show a sustained train resembling the
restore recording. RX began about `17 ms` after the position call started, but
that short delay alone does not explain the missing multi-second train. Its
discontinuities were near the end of the recording; the result remains an
unexplained negative, not evidence that raw `128` is unsupported.

### Position and shade-mask comparisons in one authorized room — 2026-10-23

The operator limited further actuation to one authorized room. All subsequent
physical requests remained within that scope; other rooms were excluded.
Later, the operator explicitly added one individually identified target in
another room while observing it. This is a target-specific exception, not
authorization for that entire room; other targets there remain excluded.
Five additional six-second recordings covered one target's raw `128` request
and separately requested return to `0`, then three other targets' requests for
their already-reported raw `0`. Even a repeated-value request can cause activity;
it was treated as an authorized transaction, not assumed physically inert.

RX was armed before both `$pss` and `$rls`. Increasing stream configuration to
`64` buffers and `32` transfers, with `65,536` samples per buffer, yielded zero
overrun flags and zero timestamp gaps in all five recordings. This qualifies
these particular files, not all future captures. The stream remained
`48 MS/s`, center `2452 MHz`, bandwidth `46 MHz`, and gain `15 dB`; SDR
transmitters remained disabled during original-bridge actuation.

The target labels below are fictional. Room identifiers and payload CRCs are
withheld. Counts include only the repeated, expected target payloads:

| Target | Inventory group field | Requested raw position | Observed mask / final byte | Expected CRC-valid frames | Decoder coverage |
| --- | ---: | ---: | --- | ---: | --- |
| A | 3 | 128 | `04 / 80` | 2,537 | Union of `1.0`/`1.3 MHz` filters: 2,521 at 2452 MHz, 16 at 2433 MHz |
| A | 3 | 0 | `04 / 00` | 2,536 | Union of both filters: 2,517 at 2452 MHz, 19 at 2433 MHz |
| B | 1 | 0 | `01 / 00` | 2,521 | `1.3 MHz` filter; all at 2452 MHz |
| C | 7 | 0 | `40 / 00` | 2,523 | `1.3 MHz` filter; all at 2452 MHz |
| D | 2 | 0 | `02 / 00` | 2,540 | `1.3 MHz` filter; all at 2452 MHz |

Each request produced `ROOM_ID | 50 | MASK | POSITION`, followed by
`ROOM_ID | 32 | MASK | POSITION`. Independent CRC calculations and zero-residue
checks agree for every expected frame. The same target's `128 → 0` comparison
changes only the last byte `80 → 00`. The other three targets keep room ID and
position fixed while changing the mask, supporting
`MASK = 1 << (group_field - 1)` for observed fields `1`, `2`, `3`, and `7`.
Together with the earlier other-room `FF` capture, the evidence covers raw
positions `0`, `128`, and `255` and two room identifiers. It does not validate
every target, value, feature, or arbitrary multi-bit mask.

The `50` phase lasts about `1.49 s` and the following `32` phase about `0.30 s`
across these requests. The mode bytes are chronological labels; no universal
start/release/stop meaning is assigned. The observed position slot is about
`234 µs`, compared with the handheld's roughly `195 µs`. Exact repeat counts,
Gaussian shaping, and full channel timing remain provisional. No accepted
position frame was recovered on `2471 MHz`; known-address `2 Mbps` searches of
the candidate `2440 MHz` control channel also yielded none. Different control
framing or modulation remains possible.

One outer-channel midpoint detection had a different payload with a valid CRC
under only one filter variant. It is retained as an anomalous singleton,
excluded from the table, and not treated as another identity. Longer
CRC-valid 97-bit zero-extension interpretations are also retained or rejected
under the documented framing/envelope rules, rather than counted as additional
88-bit transmissions. Counts remain recovered-frame lower bounds, not packet
error rates.

Before/after inventory and `$done`/`$act00-00-` receipts establish bridge state
and command-layer completion. They do not independently verify motor movement
or physical position. The source clients' native `0–255` scaling was checked
against original upstream code; it is not a physical travel calibration.
Candidate position-payload and waveform generation is available offline.
No position waveform has established SDR-to-shade interoperability.

The emitting component remains unassigned. These wide command-correlated
frames therefore do not overturn the narrow Bridge/Repeater waveforms in the
FCC filings, nor establish whether a repeater translates between them.

### Transmit attempts and laptop handoff — 2026-10-23

The first individual-position attempt failed on the second frequency with a
timestamp-in-the-past error. Reopening the device for each frequency resolved
the library's retained timestamp cursor after clock reconfiguration. Later
attempts submitted all three frequencies. Sequential position artifacts were
also corrected from 234 µs to 702 µs same-channel spacing, preserving the
observed three-slot cadence. Both selected-position profiles then decoded to
2,525 expected frames per channel in software, 15,150 frames across six files.

The operator reported no movement during any SDR attempt, including the final
corrected-cadence trials at 50 and 60 dB transmit gain. Distance and unmodeled
signaling remain possible causes; neither is established. A saved preliminary
analysis found narrow bursts near 2440 MHz preceding the wide position train
in both continuous same-target recordings. Their modulation and role remain
unresolved and they are absent from the synthesized model.

At the operator's request, RF activity and analysis paused for the night, and
the hardware service stopped. The radio will move from the stationary desktop
to a laptop for the next session. The [laptop handoff](handoff.md) records the
restart order, current software corrections, and evidence limits. Exact paths,
configuration, targets, and transfer instructions are in a private Downloads
document on the desktop. The final offline suite passes 129/129 with analysis
dependencies; the base environment passes 108 with 21 optional DSP skips.

### Remaining bench work

1. Extend the `48 MS/s` USB/storage continuity check and identify the physical USB port; investigate the `61.44 MS/s` counter failure before using that rate.
2. Inspect and identify every RF connector before mating components.
3. Characterize the nominal 40 dB loopback at `2433`, `2440`, `2452`, and `2471 MHz`.
4. Extend the initially decoded Group 1 result to the full receive-only action matrix, using timestamp/overrun metadata before making timing claims.
5. Establish an independent Nordic reference link.
6. Use a logic analyzer only after establishing a mechanically safe spare-remote probe plan.
7. Validate candidate position transmission and physical target response within the operator's current room scope; preserve the distinction between bridge-reported state and observed motor position.

## Logging rule

Record local details needed to reproduce an experiment, but sanitize them before committing. Unsanitized IQ, logic traces, serials, addresses, and household identifiers belong under ignored `captures/` or `tmp/` paths. A result affects canonical project status only after its sanitized evidence meets the gates in [Testing and validation](testing.md#validation-sequence).
