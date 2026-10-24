<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Reference bench lab log

> **Environment-specific, not canonical.** This file records sanitized capability qualifications and results for Hunter Douglas Platinum protocol work. It does not define what every contributor must own or use. Canonical requirements are in [Testing and validation](testing.md) and the [Bill of materials](bom.md).

Last updated: 2026-10-24 (America/Chicago)

Private network addresses, MAC addresses, household labels, serial numbers, and local filesystem paths are intentionally excluded from this tracked log.

## Capability snapshot

| Capability | Public qualification status | Evidence still required |
| --- | --- | --- |
| USB 3 capture host and storage path | Short counter-stream check passed at `48 MS/s`; `61.44 MS/s` failed continuity | Identify the physical port and qualify longer capture continuity. USB reports SuperSpeed (`5 Gb/s`); five seconds of counter data at `48 MS/s` had no discontinuities. |
| Original Platinum App Bridge LAN/RF reference | Inventory, bounded transactions, correlated payloads, and operator-observed reference movement | General position feedback and complete application semantics remain unresolved; private address and identifiers remain outside the repository. |
| Wideband SDR capture and transmit path | Protected packet checks and operator-observed 250 kbps position responses through private helpers and the public emulator | Independent receiver, calibrated RF response, repeatability, and broader shade coverage remain pending. The exercised public path is the 250 kbps backend, separate from the 2 Mbps position backend. |
| Original-app emulator compatibility | Discovery, inventory loading, primary-position control, and an existing-target Sync response demonstrated with the original bridge off | New-identity enrollment, room/shade editing acceptance, broader application behavior, and Control4 remain unverified. |
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

### Laptop reference captures and narrow candidate — 2026-10-24

Testing resumed on a laptop approximately six feet from the authorized target.
USB reported SuperSpeed, the verified FPGA was loaded temporarily, and all bias
tees were off. A five-second 48 MS/s receive check had zero timestamp gaps and
overruns. The package build and all **132 software tests** passed after fixing
recognition of NUL-padded LAN action records while preserving their raw bytes.

The operator observed the original bridge move the target, including a return
to closed with **all repeaters unplugged**. This establishes physical response
for those original-bridge commands, not SDR interoperability. Fresh 2 Mbps
references show roughly 600 µs same-channel spacing, compared with the earlier
roughly 702 µs recordings; these are capture-specific results.

Analysis of fresh and restored IQ recovered 2440 MHz packets at 250 kbps with
the public three-byte `E7 E7 E7` address, nine-bit PCF, 9- and 12-byte payloads,
and valid CRC-16/zero-residue checks. Independent demodulation supported the
packet bytes. Early and later groups support a repeater-forwarding hypothesis;
their complete application semantics and acknowledgment behavior remain open.

The bridge-only closed-position source yielded eight verified packets, four of
each payload length. Two expected slots in the ten-slot pattern were obscured
by interference; an emitted-packet denominator is not independently established.
A candidate copied those eight packets and their timing, leaving the two slots
silent. Its eight written-IQ frames decoded exactly in offline checks.

**One finite over-the-air trial** submitted the approximately 112 ms candidate
at 2440 MHz, 250 kbps, 8 MS/s, and TX system gain 35 dB. The original bridge was
off and one UXUPR was powered. The operator reported **no movement**. There was
no automatic retry. Missing signaling, application state, waveform assumptions,
and hardware delivery remain possible explanations; this single incomplete
trial does not establish a protocol failure or a need for more power.

After fresh operator confirmation of the protected nominal 40 dB cable path,
three finite copies of the same approximately 112 ms candidate were transmitted
at TX gains `-23`, `0`, and `35 dB`, with RX gain `40 dB`. Each one-second
recording used `8 MS/s`, center `2440 MHz`, and `1.5 MHz` bandwidth, and had zero
overruns, timestamp gaps, or clipped samples. The two lower gains were below
useful SNR. At `35 dB`, the baseline decoder recovered seven expected packets;
`300–350 kHz` filter refinements recovered the eighth. All eight complete bit
strings, CRCs, and zero residues matched the generated artifact.

Template correlation placed all eight received bursts at one common offset of
86 samples (`10.75 µs`) relative to the submitted waveform. Relative deviation
was approximately `±160 kHz`. These shared-oscillator measurements support
delivery of this eight-packet artifact through the conducted path; they do not
calibrate absolute frequency, RF power, attenuation, or antennas, and do not
establish shade acceptance. The two obscured source slots remain absent from
that candidate.

A fresh bridge-only closed-position recording with all repeaters off recovered
one complete observed train of ten CRC-valid packets: five 12-byte and five
9-byte packets. Two independent demodulation methods agreed on their complete
bits, and the operator confirmed closure. A subsequent 2440 MHz midpoint
reference produced operator-confirmed halfway movement. A new candidate copied
all ten closed-source packets, including PID, `NO_ACK`, CRC, and relative timing,
with the same PHY as the conducted artifact. Independent written-IQ checks
recovered all ten exactly; every quiet interval was zero and no samples clipped.
The file lasts **112.134 ms**. This is a complete observed train, not proof of
the complete application exchange beyond the recorded band and time.

With the original bridge off, one UXUPR on, and the antenna on TX1, one finite
trial at TX system gain **35 dB** and one identical trial at **50 dB** each
produced **no movement and no observed repeater LED response**, as confirmed by
the operator. These were the first **three over-the-air trials**: the
earlier eight-packet trial and these two ten-packet trials. Gain is a device
setting, not measured RF power; disabled gain-stage readback is not an active
output-power measurement.

The fourth trial used the **unchanged ten-packet closed candidate** and its
original flat carrier lead, with TX gain `50 dB` and concurrent three-second RX
at gain `40 dB`, `8 MS/s`, `2440 MHz`, and `1.5 MHz` bandwidth. TX1 had a direct
antenna; RX1 had a second antenna through a nominal `30 dB` pad and DC block;
TX2 was terminated. The original bridge was off and one UXUPR was on. This was
a radiated observation, not the earlier nominal 40 dB conducted path. Before
IQ submission, enabled TX1 read back overall gain `50 dB`, DSA `-16 dB`, and
frequency `2439999998 Hz`.

The recording recovered **20 CRC-valid packets**: the ten submitted packets and
ten later packets consistent with repeater forwarding. The later 12-byte
payloads retained the closed command; the 9-byte packets retained their group
and countdown fields while byte 7 changed from `6` to `5`, with the corresponding
checksum change. The operator reported **shade movement**; exact full closure
and the repeater LED were not confirmed on this run.

At the operator's explicit request for native position `128`, the fifth trial
used the same successful schedule, PID/`NO_ACK`, and PHY. Its long payload came
from four fresh midpoint observations. Four short payloads matched captured
countdown values `3` through `0`; count `4` was constructed from the working
template, the freshly observed group field, and the validated application XOR
rule. All outer CRCs were recomputed, and independent written-IQ checks passed.
This is **capture-supported generation**, not an exact captured replay. The
operator confirmed **roughly halfway and a repeater LED response**.
The midpoint recording also recovered all ten transmitted packets and ten
forwarded packets with valid CRCs. The response preserved the midpoint payload
and group/countdown fields, again changing byte 7 from `6` to `5`; it began
about 29.9 ms after the final transmitted CRC. Neither recording had clipping,
timestamp gaps, or overruns.

The laptop session totals **five over-the-air trials**: three without observed
movement followed by two observed responses. A leading-zero waveform variant
was prepared but **not transmitted**; it did not cause the breakthrough. The
effects of concurrent RX, a second antenna, and connector reseating remain
unisolated. Neither an RX requirement nor universal protocol compatibility is
established. The working 250 kbps helpers remain private and are not integrated
into the public position backend.

Radio sessions are closed with no further hardware action planned. The shade
is roughly halfway, the two-antenna setup remains connected, the original
bridge is off, and one UXUPR is on.

### Remaining bench work

1. Extend the `48 MS/s` USB/storage continuity check and identify the physical USB port; investigate the `61.44 MS/s` counter failure before using that rate.
2. Inspect and identify every RF connector before mating components.
3. Characterize the nominal 40 dB loopback at `2433`, `2440`, `2452`, and `2471 MHz`.
4. Extend the initially decoded Group 1 result to the full receive-only action matrix, using timestamp/overrun metadata before making timing claims.
5. Establish an independent Nordic reference link.
6. Use a logic analyzer only after establishing a mechanically safe spare-remote probe plan.
7. Validate candidate position transmission and physical target response within the operator's current room scope; preserve the distinction between bridge-reported state and observed motor position.

## Integrated bridge emulator — 2026-10-24

The public `bridge-emulate` runtime now shares the authenticated HTTP dispatcher
with an original-protocol TCP 522 server. It imports the original raw inventory,
keeps requested positions separately, durably reserves RF sequences, and uses
the exercised 250 kbps profile with concurrent RX. Local software verification
passed 189 tests and built both distributions.

One live TCP stage/release requested the observed target's closed position.
The client observed the action-end marker; a new snapshot showed the requested
position. The operator confirmed closure while the original bridge was off.
Offline decoding recovered all ten generated packets exactly and ten matching
response packets, with valid CRCs and no capture gaps or clipping. The response
group began about 6.48 ms before the final source packet finished; it was not a
strictly subsequent non-overlapping group. This is the sixth laptop OTA burst
and third observed shade response, including the two earlier private-helper runs.

A graceful restart preserved requested state and the next sequence. The
optional discovery responder answered a LAN broadcast; the original mobile app
then found the emulator and updated its bridge address. The app's reconnect
loop exposed previously unsupported `$sdt`, `$stm`, and `$chksy` startup
commands in the private TCP journal. Discovery is demonstrated on this setup;
mobile control, enrollment, and a Control4 client remained separate checks at
this checkpoint. Subsequent app-control and Sync observations are recorded below.

### Original app control and pairing-reference capture — 2026-10-24

The original bridge returned `$chksy01-` for a current-year check. Replacing the
provisional `$done` reply made the original app send `$dat` and display the
existing rooms and shades. The app then sent a primary-position command with
native value `126`, without a final hyphen, followed by `$rls`. The public RF
backend submitted it, and the operator confirmed roughly-halfway movement with
the original bridge off. This was the seventh laptop OTA burst and fourth
observed response. The full software suite passed 192 tests and the package built.

For enrollment research, the emulator was stopped and a private transparent TCP
recorder connected the app to the original bridge. The original database was
saved before changes. A 60-second, receive-only 48 MS/s capture centered on
2452 MHz completed with zero timestamp gaps and overruns. Informational metadata
bits `0x30000` report mini-expansion pin states per the installed libbladeRF
header; they are preserved separately from errors. An earlier recording had
stopped before readiness because it treated those flags as errors.

The app issued two sync requests and several jog requests for the authorized
target. The operator reported an accidental Jog press, so observed movement is
not yet isolated evidence of enrollment. The first complete sync interval
precedes the first recorded Jog request; the later sync interval is partial and
mixed with Jog requests. The shade database entry was not deleted during this
reference; this capture alone does not demonstrate emulator enrollment.

### Existing-target Sync and mutable app inventory — 2026-10-24

Analysis isolated the first original-bridge Sync interval and its RF packets
before the first Jog request. The public emulator now accepts the observed
`$rscII-` request through a separate Sync dispatcher and an explicit per-target
allowlist. It reports action start and completion without treating Sync as a
position request. The RF backend submits the capture-supported 250 kbps Sync
profile and retains eighteen seconds of concurrent receive data.

In a subsequent isolated emulator test, the original bridge was off. The
operator used Sync and the receiver's manual button, sent no app Jog request,
and observed the existing authorized shade jog. This establishes an
existing-target Sync response in that setup. The record was not first recreated
under a new RF identity, so full new-identity enrollment remains unverified.

Static analysis of the user-supplied Android application recovered a catalog of
25 product types and exact room/shade create, edit, and delete request grammar.
The name field uses Java UTF-16 code-unit length and a 25-unit UI limit. The APK
was inspected as evidence; no application installation or execution was needed.
Its commands do not specify new record IDs, room RF identities, or shade slots.
The emulator's allocation and metadata cascade choices are implementation
policies, not established original-firmware behavior.

Mutable inventory support now uses that grammar. The store
atomically persists raw records, requested-position overlays, clock state, and
RF revocations; it migrates the earlier position-only state after checking the
original inventory hash. Known room and shade definitions are emitted in
ascending stable-ID order, while opaque records retain their bytes and relative
order. New and rebound records remain disabled for RF.

The Android parser indexes room and shade lists by numeric ID. LAN deletion
therefore rejects operations that would create ID holes, rather than silently
renumbering identities. Recognized scene dependencies also block deletion;
metadata deletion is not an RF unpairing operation. Offline store tests cover
restart, migration, ID reuse, ordering, atomic-write failures, and RF revocation.
The original app created a room and shade and reached the Sync/Jog screen.
Entering the new room required an app restart; immediate room refresh remains
unresolved.

### New-identity Sync delivery comparison — 2026-10-24

The operator reported no enrollment jog for the new identity. Four retained
consecutive app-requested Sync recordings each contain nine exact transmitted
packets. Two also contain matching later 2440 MHz response groups, with nine
and eight decoded packets respectively; the other two contain none under the
tested decoder settings. A subsequent existing-identity control contains a
complete ten-packet response group. All five recordings have continuous sample
timestamps and no clipping. The first of five app requests aged out of the
rolling artifact store before analysis and is excluded from these counts.

This demonstrates intermittent response to both identities, rather than a
general rejection of the newly allocated room identity. It does not establish
the repeater's native shade-facing transmission or successful enrollment. The
transmitted waveform was unchanged; a prepared preamble variant was not used.
Closed recordings and their plans were preserved outside rolling retention.

A subsequent native-only recording at 2452 MHz contained no decoded frames;
an original-reference excerpt resampled to the same 8 MS/s successfully decoded,
but the native-only file could not establish whether that request reached the
repeater. A proposed simultaneous 48 MS/s RX / 8 MS/s TX configuration was
refused before streaming because configuring RX changed the TX sample rate.
Its sequence reservation was retained, and no IQ was submitted.

A private simultaneous recording then used 32 MS/s in both directions, within
the existing aggregate streaming envelope. TX remained at 2440 MHz with
1.5 MHz bandwidth and gain 50; RX used 2446 MHz with 32 MHz bandwidth and gain
30. This covers 2440 MHz and the native 2433/2452 MHz channels, but excludes
2471 MHz. Fourfold interpolation preserved every original sample on its source
grid, all ten packet bit strings, and the 112.134 ms schedule. Independent
decoding verified the written IQ; interpolation was not treated as hardware
qualification by itself.

The completed, continuous recording contains eight decoded own packets and a
complete ten-packet matching downstream group at 2440 MHz. Native decoding at
2452 MHz recovers 2,181 held-code packets followed by 34 release-tail packets,
all carrying the newly allocated identity and mask. The detected native train
spans 15.267 seconds. Alternate filtering also recovers the same held/tail
bodies. The original bridge was off, and no manual shade-button press was
requested during this recording. This establishes native forwarding of the
new identity in that trial; physical enrollment remains unconfirmed.

### Captured Jog and public implementation — 2026-10-24

Controlled original-bridge Jog requests staged feature `12`, value `000`, and
received feature-12 status `001` followed by `$done`. After release, the narrow
RF command carried feature `0x0c`, value `1`, and flags `1`. One bounded excerpt
contains all ten source packets, with short countdowns `4` through `0`, the
standard PID cycle and no-ACK field; matching later packets were also recovered.
That source recording was interrupted outside the selected interval, so it is
not presented as a complete continuous capture.

Independent offline comparison matched all ten full source packet bitstrings
to the public Jog encoder and recovered them from the written IQ. The public
waveform keeps the previously exercised finite schedule rather than copying
this Jog's exact timing: its first long-to-short gap is `805 µs` longer; after
aligning the first short packet, the other nine starts differ by at most
`7.25 µs`. No hardware transmission of the new public Jog path was performed
during implementation.

The original Jog produced target-specific native traffic at `2452 MHz`, while
Sync for that same original-created identity had been decoded at `2471 MHz`.
This is a same-identity counterexample to a room-only channel assignment rule;
the selection mechanism and emitting device remain unisolated. Physical
movement on the new binding was not observed, including during the
original-system enrollment checks. Full enrollment remains unresolved.

Software now supports separately enabled Jog through TCP stage/release and
authenticated HTTP, using the shared narrow backend and persistent sequence
allocator. Default-off permissions, grant revocation, rejected mixed batches,
single-use release, no position-overlay writes, and failure cleanup have
fictional-fixture and fake-radio coverage. A Sync-only grant never enables Jog.

## Logging rule

Record local details needed to reproduce an experiment, but sanitize them before committing. Unsanitized IQ, logic traces, serials, addresses, and household identifiers belong under ignored `captures/` or `tmp/` paths. A result affects canonical project status only after its sanitized evidence meets the gates in [Testing and validation](testing.md#validation-sequence).
