<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Protocol conformance before shade testing

The public live route is **2440 MHz bridge packets to a Platinum repeater**;
separate private tests exercise direct native per-packet hopping. One watched
native Jog succeeded. The first watched native primary raw-128 trial produced
no movement; an explicitly requested repeat produced full opening on a
top-down-only shade. Later raw-255 and raw-0 requests produced covered and
exposed endpoints, respectively, with no other shade moving. The bottom rail
is fixed; only the top rail is controllable. Direct-native intermediate-position
accuracy remains unestablished. Original-app primary requests produced observed
intermediate results at raw 134, 191 and 127. The earlier searches recovered no
source RF for raw 134 or 191; a later narrow raw-127 capture recovered 63 native
packets with bodies matching the primary-position planner. Its sparse reception
does not establish the complete phase timing or packet counts.
Original firmware execution and independently decoded recordings provide
separate references. Later matching 2440 MHz traffic is consistent with
forwarding; it does not by itself identify the emitter or establish native
shade output.
They establish transmitter behavior; they do not expose the shade receiver's
learning policy or prove that a particular shade accepts a request.

## Original firmware checks

The tools require the exact gateway image identified in
[Original firmware execution](firmware-emulation.md). They execute its unchanged
8051 instructions with fictional inputs and stop before hardware access.
Connection/database/CPU fixtures and every checked boundary are recorded in
private reports. No original firmware is bundled with the project.

```sh
hd-platinum firmware-bridge-probe --apk tmp/platinum.apk \
  --simulator tmp/ucsim/src/sims/s51.src/ucsim_51 \
  --output-dir tmp/bridge-conformance

hd-platinum firmware-native-probe --apk tmp/platinum.apk \
  --simulator tmp/ucsim/src/sims/s51.src/ucsim_51 \
  --output-dir tmp/native-conformance
```

| Layer | Result and scope |
| --- | --- |
| 250 kbps command bodies | Original builders agree with primary positions 0/128/255, Sync feature 1/value 0/flags 3 and Jog feature 12/value 1/flags 1. |
| 250 kbps short bodies | Original builders establish separate command-count and transaction bytes, countdown and the XOR checksum. Original release code wraps the transaction byte from 255 to 0. |
| Native five-byte bodies | Original full-body construction agrees with public position/up/down encoders and explicit Sync/Jog held/tail vectors, across fictional identities and masks. |
| Native channel rotation | Original code rotates 2433 → 2452 → 2471 MHz. This is per-packet rotation, not a complete train per channel. |
| Native phase durations | Original code initializes and decrements phase counters. Sync uses about 15 seconds plus a 0.3-second tail; these are nominal timer-derived durations, not a qualified wall-clock model. |

### Corrected transaction encoding

The old encoder incorrectly serialized a local ordinal as a 16-bit wire field.
It happened to agree for ordinals 256–511: the high byte was one, matching a
single-command count. It would have advertised two commands at ordinal 512.

The corrected short packet always encodes count **1**, followed by
`local_ordinal & 0xff`. The existing version-1 reservation file is unchanged.
Reservations still persist before TX and remain consumed after uncertain
failure. The local 16-bit exhaustion policy is separate from the firmware's
normal 8-bit wire-counter wrap. Reports expose `sequence` (local ordinal),
`command_count` and `transaction_counter` separately.

## Independent recording checks

Two original Jog recordings supplied 19 recovered source frames. Independently
implemented polynomial division verified every CRC and bit-for-bit comparison
verified the ESB preamble, address, PCF, payload and CRC with captured PIDs.
An unrecovered slot was left missing. A successful SDR recording separately
supplied ten exact transmitted frames and ten later matching/forwarded frames.

Captured starting PID phases vary. The finite SDR plan retains its exercised
starting phase zero and modulo-four progression; it does not reproduce all
prior payload loads inside the original radio. Packet comparisons use each
capture's actual PID. Receiver-side duplicate filtering remains a physical
interoperability consideration, not a reason to invent a persistent chip state.

The original first long-to-short gap varied from about 10.74 to 13.08 ms across
the two Jog references. The exercised 11.54 ms gap lies between them; the
remaining starts agree within about 7.3 µs after aligning the first short frame.
This supports retaining the exercised schedule, not replacing it with one
recording's first gap.

The original signal approaches a low-symbol frequency just before its AA
preamble. The successful SDR signal instead has a flat center-frequency lead.
Both recordings independently recover the complete AA/data frames. This is a
measured difference before the data-bearing frame, without evidence that it
invalidates reception. The exercised flat lead and ±160 kHz synthesis remain.
Relative carrier offsets from these recordings are not an absolute calibration.

## Controlled physical checks and route limits

The experimental direct 2 Mbps hardware backends currently send an entire train
on one channel before retuning. They do not reproduce the original per-packet
hopping scheduler, and do not provide dedicated native Sync/Jog plans. Keep
their shade interoperability status unqualified; passing native payload checks
does not validate those backends.

The controlled checks used one already paired shade and finite Jog commands,
with the original bridge off and one repeater on. New-identity enrollment
remains unresolved, including on the original bridge.

The first existing-binding Jog after this audit produced no observed
movement. Its recording recovered all ten transmitted packets exactly and a
complete ten-packet later group consistent with forwarding; the command body
matched a successful original-bridge Jog. The 3-second 2440 MHz recording was
continuous and unclipped.
That recording does not establish native output.

For that diagnostic, the Python backend now accepts opt-in
`profile="wide", rx_center_hz=2_461_500_000` with Jog. Both directions use
32 MS/s; TX remains the same finite 2440 MHz command. RX records for 3 seconds,
with at least 2.25 seconds required after TX. This nominal passband includes
2452/2471 MHz and excludes 2440/2433 MHz. Receipts record that coverage explicitly.
The default narrow profile and the existing 2446 MHz wide Sync profile remain
unchanged. This receive selection is a diagnostic API option, not a new direct
shade-transmission mode.

Two subsequent wide recordings also accompanied no observed movement. Neither
recovered expected native packets on its covered channels. The 2446 MHz
recording recovered all ten transmitted 2440 MHz packets exactly, but no later
decoded group. Intermittent interference limits that negative result: failure
to decode is not proof of no emission, and neither wide profile covers all
three native channels. All three recordings were continuous and unclipped.
Matched filtering and nominal receive-gain correction put clean local TX
packet power within 0.04 dB across the narrow and wide modes. This argues
against a large interpolation-related power loss at the monitoring antenna;
it is not a radiated-power calibration or a measurement at the repeater.

An original-bridge baseline then failed to produce observed movement; the
operator-requested repeat succeeded. Both recordings contain the same target,
mask and native Jog bodies, the expected held/alternate/tail sequence, and
matching 2440 MHz source/later groups. The successful recording yielded fewer
decoded native frames at the SDR. No recovered payload or timing difference
explains the different physical outcomes. These data do not identify the native
emitter.
The successful repeat confirms the shade still accepts its existing binding;
it does not validate the new identity or the SDR Jog path.

A separate bounded execution of the original native initializer and phase
selection rules found no mandatory cold-start prelude. Initialization clears
the active native timer and starts an ordinary command in held phase 2. The
short phase-1 prelude applies when a previous native timer is active. This
does not establish the receiver's interpretation of that phase and is not a
reason to prepend it to every synthesized command.

A bounded composition of the original scheduler, payload builder and channel
selector also checked 720 pulse triggers, stopping at radio-access boundaries.
The reviewed path maintains channel rotation across payload changes. Steady
Jog refreshes use 100 main packets and 20 alternate packets, but decrementing
the refresh counter before the first pulse gives an initial run of 99 or 19,
depending on the supplied alternation state. The APK reset path and reviewed
main initializer do not establish the physical power-on channel/alternation
state. The independent phase-timer epoch also prevents deriving an exact
whole-command packet count from this fixture. A planner must expose these
initial-state and timing assumptions rather than claim one proven startup
schedule.

## Offline native Jog plan

`hd_platinum.rf_native_jog` now supplies a separate finite packet-event planner
and chunked IQ writer. It preserves per-packet channel rotation across main,
alternate and tail body changes, including the shorter initial refresh run.
The original-firmware payload probe compares this module's bodies directly,
including both alternation states during the tail. The live radio backends
remain unchanged; this module neither opens hardware nor grants control.

Initial state, phase packet counts and the nominal timing grid are mandatory
arguments. For example, this creates a fictional offline plan:

```python
from hd_platinum.rf_native_jog import build_native_jog_plan

plan = build_native_jog_plan(
    bytes.fromhex("1234"), 1,
    prior_channel=71, prior_alternate=0,
    held_frame_count=7500, tail_frame_count=1500,
    slot_us=200.5,
)
print(plan.as_dict())
```

These chosen counts yield 1.8045 seconds; they are diagnostic assumptions, not
measured universal counts. Output uses 48 MS/s centered at 2452 MHz, with one
packet at a time on the three channels. The complete waveform is capped at two
seconds. Gaussian shaping, deviation and envelope remain provisional. The
optional writer creates a new mode-0600 file and refuses an existing path;
generated IQ contains the supplied identity even when metadata redacts it.

Independent decoding recovered all 297 packets from two short fictional
written-IQ fixtures, with valid CRCs on all three channel offsets. The checks
also covered both initial alternation states, channel continuity across a
held/tail boundary, zero-filled gaps, amplitude bounds, and rejecting silent or
wrong-channel inputs. These are digital-file results, not RF reception results.

Digital frame decoding does not qualify the wide radio path. TX analog bandwidth
must pass both outer channels, and actual TX/RX rates must remain as requested.
The reference bench previously found that requesting 24 MS/s RX changed a
48 MS/s TX configuration to 24 MS/s, consistent with
[Nuand's shared-rate explanation](https://nuand.com/forums/viewtopic.php?t=12937).
Its supported combined streaming limit
also excludes simultaneous 48 MS/s TX and RX. Those checks must not be bypassed
to obtain a nominally complete capture. Independent RF verification remains
necessary before qualifying this plan as a live direct-Jog backend.

## Independent Nordic receiver preparation

The separate [RAM-only nRF52840 receiver](../firmware/nrf52840_rx/README.md)
provides a fixed-channel, receive-only packet check. It has no transmit or ACK
path, and waits for an explicit host token before receiving. A bounded RAM log
retains hardware CRC verdicts, received CRC values, payloads, RSSI, hardware
timestamps and receiver rearm gaps. The first image accepts only its reviewed
silicon revision; it does not silently apply settings to other revisions.

`hd_platinum.nrf52840_capture` reads stopped capture dumps without opening a
debugger or serial port. It cross-checks CRCs independently and reports schema,
timing, counter, overflow and shutdown failures. Readable failed captures are
retained for diagnosis. A zero-packet capture does not qualify reception, and
default metadata excludes payloads, CRC values and factory words.

The image builds and has passed host log tests, independent parser fixtures and
ELF layout review. It has also been loaded into an identified AAF0 DK's RAM.
Startup checks confirmed the expected chip profile, crystal clock, idle READY
state, disabled radio and PPI, and zero capture commands or receive attempts.
The processor was halted after that check.

A subsequent three-second recording of an original-system Sync received 2,945
address-matched packets on 2452 MHz. Of these, 2,905 matched the expected native
Sync body and passed both hardware and independent software CRC checks; 40 had
bad hardware CRCs. The live register snapshot confirmed RX state, the expected
packet configuration and the READY event. The hardware deadline completed,
the radio and PPI were disabled, and the processor was halted afterward.
The original bridge's room and shade definitions were unchanged. No manual
shade-button press or enrollment claim was part of this reference check.

An earlier 29.674 ms SDR fixture produced no packets at this receiver. That
fixture contained 148 native packets across all three channels, including 49
expected on 2452 MHz, addressed to a fictional identity absent from the saved
inventories. The SDR's active readbacks confirmed 48 MS/s, 46 MHz bandwidth
and the selected gain setting; the scheduled burst fell inside the receiver's
three-second window. Successful submission is not proof of radiated samples.
The original-system positive control establishes that this receiver accepts
native packets, but the single short negative result does not isolate a cause:
the wide SDR path remains unobserved, and transient interference is also possible.

One fixed-channel receiver cannot establish simultaneous three-channel
reception, analogue signal quality or shade acceptance. No original bridge
firmware is included in this receiver.

### Synthesized center-channel reception

A subsequent comparison used the same fictional identity and 16 MS/s TX/RX
at 2452 MHz. Ten short bursts alternated the existing flat lead with a variant
containing a half-microsecond low-symbol lead immediately before the preamble.
Each variant supplied 245 packets; payloads, CRCs, packet times, amplitude and
radio settings were otherwise identical.
The SDR monitor independently recovered all 490 transmitted packets with
exact payloads and valid CRCs, and distinguished the intended lead shapes.

The independent DK accepted 210 flat-lead packets and 226 modified-lead
packets, with agreement between hardware and independently calculated CRCs.
All 436 valid records matched the expected payloads and unique packet slots.
A clock alignment anchored before transmission distinguished the alternating
bursts; fitting relative clock drift gave a maximum timing residual below
0.6 microseconds. Nine additional bad-CRC records fell in burst windows, with
one outside them. Both receivers completed their bounded recordings and were
stopped afterward.

The first unchanged burst already delivered 43 of 49 packets, before any
modified burst. Its waveform was identical to an earlier short gain-matched
trial that delivered no packets. This establishes center-channel SDR-to-DK
interoperability, but does not explain the earlier intermittent failures.
Coherent signal power at the SDR monitor was about 3.6 dB lower in that first
successful burst, so increased power at that monitor does not explain recovery;
the propagation path at the DK was not measured separately.
The modest difference between variants in one run does not establish that
the added lead symbol is necessary or justify changing the public waveform.
The full 48 MS/s three-channel transmission and shade acceptance remain
separate checks.

### Full-rate streaming investigation

A 9,000-packet, 1.8045-second fictional native train was independently decoded
from its written 48 MS/s IQ: 3,000 valid packets per channel. The first physical
attempt stopped after four application chunks because the next chunk lacked
the required 25 ms of scheduling lead. The metadata-adjusted transmit ring
holds about 43 ms at this rate; after one application chunk, that lead
requirement leaves too little space for continued submission.

A second attempt passed the entire preloaded waveform to one library call,
removing the pauses between application chunks. Submission completed, but the
call returned about 321 ms after the scheduled waveform end. Both attempts
produced only three decoded packets in an early segment at the independent
receiver. Its configuration and observed rearm timing matched successful
controls. The radio was stopped and the DK halted after each capture.
These results do not qualify sustained full-rate transmission. They support
investigating sample delivery, without establishing a calibrated USB throughput
limit or explaining the earlier repeater-route failures.

An SC8_Q7 candidate halves sample transport from 192 to 96 MB/s at the same
48 MS/s rate. Independent decoding verified all 9,000 quantized packets and
their CRCs, with unchanged timing, channel rotation and zero-filled gaps.
Review of libbladeRF at `fcf9423325ae49f5fdd2e5b52ab68bfc2576ad47`
found two missing SC8 metadata predicates: burst parameter handling and
successful end-of-burst cleanup. Actual-source inert tests reproduce both
defects and validate the two-condition fix while preserving SC16 output.
The [patch and portable regression harness](../tools/libbladerf_sc8/README.md)
are retained separately under the upstream library's license.

A physical SC8 check using the private patched build received 63 valid and
19 bad-CRC records before a USB transfer timeout. Their measured same-channel
grid was approximately 603.873 microseconds, versus the intended 601.5;
activity covered only an early segment, with no verified tail. This repeatable
stretch is much larger than the relative clock drift in the successful
center-channel check. It motivates investigating legacy FPGA message-boundary
handling; it does not establish a complete transmission or isolate the cause
of the USB timeout. At this stage, the host serialization fix was independently
tested, but sustained SC8 RF output remained unqualified.

### Matched firmware comparison

The same private patched library and byte-identical SC8 waveform were then
tested with official FX3 firmware 2.6.0 and FPGA 0.16.0, replacing firmware
2.4.0 and FPGA 0.15.3. Complete flash and OTP backups were read twice before
the update. Independent readback confirmed the new firmware and unchanged
calibration, OTP and all flash outside the firmware region. The FPGA was loaded
into volatile RAM only.

Three separate finite transmissions retained the same 48 MS/s rate, gain,
bandwidth, buffering, scheduling lead and single-call submission. Only the DK's
receive channel changed between these three runs. Each channel had 3,000
expected packet slots:

| Receive frequency | Exact CRC-valid packets | Bad-CRC records | Fitted same-channel interval |
| --- | ---: | ---: | ---: |
| 2433 MHz | 2,391 | 32 | 601.49623 microseconds |
| 2452 MHz | 2,682 | 48 | 601.49625 microseconds |
| 2471 MHz | 2,768 | 15 | 601.49622 microseconds |

Every valid packet matched the expected body and independently calculated CRC.
Each recording included its first and last expected packet, with a unique
alignment to the channel schedule and coverage through the final phase.
The fitted intervals differ from the nominal 601.5 microseconds by about
minus 6.3 ppm; maximum timing residual was below 0.62 microseconds. The earlier
approximately 3,945 ppm stretch and early USB timeout did not recur. All three
submissions returned about 43 ms before their scheduled end, and transmission
was allowed to finish before shutdown. The radio handles closed and the DK
completed its deadline and halted without capture-buffer drops.

This establishes sustained native packet reception on each frequency in
separate runs, not lossless or simultaneous reception of all three channels.
The firmware and FPGA changed together, so this comparison does not isolate
which component fixed each symptom. It also does not establish shade acceptance
or explain the earlier 2440 MHz repeater-route failures. The normal installed
library and public radio backend remain unchanged.

### Watched existing-binding native Jog

On 2026-10-25, a private one-shot coordinator sent the native Jog waveform for
one existing paired shade, with the original bridge and all repeaters confirmed
off. Offline checks independently decoded all 9,000 written packets and matched
the three target bodies against successful original-system references. The
unchanged planner reproduced the earlier fictional waveform byte for byte;
the same shaping, 48 MS/s rate, RF settings and finite 1.8045-second schedule
were retained. Initial channel, alternation state and phase counts remain
explicit diagnostic assumptions.

The first attempt recovered 584 exact CRC-valid packets and 572 bad-CRC records
on 2452 MHz, leaving 1,844 of 3,000 expected slots absent from the recording.
The operator missed its movement observation, so physical acceptance for that
attempt is unknown. The operator explicitly requested one repeat. Each attempt
used a separate consumed permission receipt and fresh bounded receiver session;
there was no automatic retransmission.

The repeat recovered 2,662 exact CRC-valid packets, 177 bad-CRC records and
161 absent records. Every valid packet matched the expected payload and an
independently calculated CRC. All 2,839 recorded packets aligned uniquely with
the expected channel schedule. Valid reception covered the first and last
expected packets, including 2,204 held-phase and 458 tail-phase packets.
The fitted same-channel interval was 601.496209 microseconds, with maximum
timing residual 0.597 microseconds. These are fixed-channel measurements with
gaps; the difference in reception between attempts has no established cause.

The operator confirmed the intended shade jogged and no other shade moved.
This establishes **one watched direct-native Jog success on an existing
binding**. It does not establish repeatability, fresh enrollment, primary
position control or qualification across products.

Both attempts used the pinned private library and verified firmware 2.6.0 / FPGA
0.16.0. Each submitted one finite START|END call and waited through its scheduled
end. All SDR channels and bias tees were disabled, handles closed, and the DK
finished with no errors or buffer drops before being halted. Saved bindings,
permissions and the durable repeater-route sequence were preserved. The
temporary grant permitted only this target's Jog; the public live backends
and installed library remain unchanged. The full 348-test local suite,
including the pinned-source C regression, and the Python package build passed.

### Native primary-position scheduler

`hd_platinum.rf_native_position` provides an offline event planner and chunked
IQ writer for feature 04. It retains the verified `0x50` command and `0x32`
followup bodies, with the requested position byte in both. Channel rotation
continues for every packet and across the phase boundary. It does not select
the older live backend or create an operation grant.

A bounded composition of the original queue loader, payload builder, pulse
scheduler, phase selector and channel selector passed 18 cases: values 0, 128
and 255, all three prior channels, and both prior alternation states. All 1,374
resulting packet events matched the new planner. In the exercised native
context, feature 04 disables Jog alternation and bypasses periodic refresh;
the body stays fixed until the phase changes. This finding is scoped to the
tested native context with the queue-mode bit clear.

An idle start selects phase 2; a previously active timer can select a phase-1
prelude. The new planner explicitly assumes the idle case and omits that
prelude. The original duration suffix loads 150 command ticks and 30 followup
ticks, but the fixtures do not model the interrupt epoch or establish exact
packet totals. Callers must supply the initial channel, both phase packet
counts and the nominal 200.5-microsecond grid:

```python
from hd_platinum.rf_native_position import build_native_position_plan

plan = build_native_position_plan(
    bytes.fromhex("1234"), 8, 128,
    prior_channel=71,
    command_frame_count=7500,
    followup_frame_count=1500,
    slot_us=200.5,
)
```

These explicit diagnostic counts yield 9,000 packets in 1.8045 seconds. Output
retains the exercised 48 MS/s shaping and a two-second limit, with exclusive
private-file creation and bounded chunk memory. Independent decoding checked
all 9,000 packets in each of two full written SC8 waveforms, plus every
SC16-to-SC8 conversion, channel placement and silent gap. The full local suite
passed 356 tests with no skips, and the package build passed. Digital checks
do not establish shade acceptance, direction, rail meaning or measured position.

### Native primary-position trials

Five subsequent finite position trials retained the reviewed native shaping,
48 MS/s rate and matched firmware/library transport. Each waveform contained
9,000 packets in 1.8045 seconds, with 3,000 expected on the independent DK's
2452 MHz receive channel. Initial channel and the 7,500 command/1,500 followup
counts remained explicit assumptions; they were not newly measured timer totals.

| Trial | Exact CRC-valid packets | Bad-CRC records | Absent records | Physical observation |
| --- | ---: | ---: | ---: | --- |
| Fictional identity, raw 128 | 2,839 | 60 | 101 | No physical target claim |
| Existing binding, raw 128 | 2,753 | 9 | 238 | No movement; no other shade moved |
| Requested raw-128 repeat after moving closer | 2,703 | 60 aligned + 1 unassigned | 237 | Moving top rail lowered fully, exposing the window; no other shade moved |
| Existing binding, raw 255 | 2,916 | 17 aligned + 1 unassigned | 67 | Top rail rose fully, covering the window; no other shade moved |
| Existing binding, raw 0 | 2,666 | 71 aligned + 1 unassigned | 263 | Top rail lowered fully, exposing the window; no other shade moved |

The fictional trial recovered its first and last expected channel packets and
completed with zero capture-buffer drops. The first watched existing-binding
trial also recovered correct packets, but the operator reported no movement.
This is a retained negative physical result, not native position acceptance.
The operator then requested one repeat of the same raw value after moving closer.
That finite transmission completed and closed with saved state preserved. Its
2,703 valid packets covered the first and last expected channel slots, including
2,252 command and 451 followup packets. Another 60 bad-CRC records aligned with
the schedule; one additional bad-CRC record did not and is left unassigned.
The fitted interval was 601.496166 microseconds, with maximum aligned residual
0.586 microseconds. The DK had no buffer drops and ended disabled and halted;
all SDR channels and bias tees were off, handles closed, and saved state unchanged.
The operator clarified that the fabric initially covered
the window fully, the bottom rail is fixed, and only the top rail moves. The
top rail lowered fully, exposing the window fully; no other shade moved.
This establishes one observed native motion response, not a raw-128 midpoint
or repeatable position result.

The subsequent raw-255 trial raised the top rail fully and covered the window.
Its valid packets uniquely covered the first and last expected channel slots,
with fitted interval 601.496078 microseconds and maximum aligned residual
0.540 microseconds. Raw 0 then lowered that same rail fully and exposed the
window. Its fitted interval was 601.496063 microseconds, with maximum valid
residual 0.600 microseconds. Two absolute alignments remain possible for raw 0:
the first valid packet is channel index 0 or 1, and the last is 2998 or 2999.
Both give the same phase totals; unique endpoint coverage is not claimed.
Each endpoint capture also contains one separately unassigned bad-CRC record.
Both trials completed with zero drops, quiet/closed radio sessions, halted
receivers and unchanged saved state. Neither moved another shade. These are
two observed endpoint responses on a shade with one controllable top rail and
a fixed bottom rail; they do not qualify a dual-rail mechanism or establish
intermediate positioning. No automatic retransmission occurred.

Raw 128 represents about 50.2% of the byte range, not calibrated half travel.
The original Android app maps product 2's primary command to its bottom-rail
slider and decimal feature 18 to its middle/top-down slider. Increasing the
primary raw value moves its UI upward; increasing the secondary value moves its
UI downward. Those are static client mappings, not proof of the installed
mechanism: the operator identifies this shade as top-down-only, with a fixed
bottom rail. The dedicated top-down-only screen instead uses feature 4 and
inverts the downward slider fraction: its UI maps raw 255 to the upper,
window-covered endpoint and raw 0 to the lower, exposed endpoint. This source
finding informed the endpoint test without changing the imported product
metadata. Actual endpoint observations are recorded separately above.
The app truncates `255 * fraction`, so exactly half produces 127; other
clients can round to 128. Earlier roughly-halfway/closed physical observations
were on a different product and do not establish this target's intermediate
behavior. The operator confirms intermediate control with the original app's
slider and handheld/wall control. Subsequent original-app feature/value
measurements are recorded below. Actual rail identity, direction and
approximate final position remain separate from requested state.

### Original-app intermediate comparison

An attempted original-app comparison then recorded 30 seconds of continuous
48 MS/s SC16 IQ through the receive antenna's 30 dB pad and DC block, using
gain 30. The 1.44 billion samples had no timestamp gaps, overruns or digital
clipping; the native decoder found no supported CRC-valid packets on any of
the three channels. This does not establish that no RF was emitted.
The transparent TCP recorder captured the original bridge's complete inventory
and matching identity, but only app initialization/query commands. No position
or release request was captured, and no TCP bytes were recorded during the RF
window. The operator confirmed dragging and releasing the slider, with no shade
movement. Thus this attempt obtained no original intermediate transaction and
does not assess pairing or position acceptance. A full app restart with a fresh
connection followed; stale app/socket state remains an unproven explanation.

After a full app restart, two LAN transactions were captured: the app's
"middle rail" control sent decimal feature 18/value 126 with no reported
movement; its "bottom rail" control sent feature 4/value 134 and moved the
sole controllable top rail to roughly halfway, with no other shade moving.
Both received the original bridge's action lifecycle replies. The app labels
do not describe this shade's physical mechanism. Both requests arrived after
the 30-second RF capture had finished, so their native RF is not established
by that recording.

A subsequent recording captured one feature-4/value-191 request at
**17.258952 seconds** after RX readiness and its release at **17.291875
seconds**. The original bridge returned the matching requested-state echo,
request acknowledgement and action-phase lifecycle on the same TCP
connection. The operator observed the sole moving **top rail** rise from
roughly halfway to roughly three-quarters covered, with the bottom rail fixed
and no other shade moving. This establishes an original-app primary
intermediate result; the app's "bottom rail" label does not reclassify the
physical mechanism.

The 60-second, 48 MS/s recording contains **2.88 billion samples** in
**10,987 contiguous blocks**, with no timestamp gaps, overruns, error status
bits or digital clipping. Receive gain remained 30 through the nominal 30 dB
pad and DC block. The receiver closed with bias tees off and its shared lock
released; saved emulator bindings, permissions and sequence were unchanged.
Both TCP legs were established before recording. A later socket snapshot
listed neither leg, after the command and its lifecycle replies; it does not
negate that recorded transaction or identify why the connection ended.

Searches of seconds **16–22** recovered no CRC-valid native 2 Mbps packets on
2433, 2452 or 2471 MHz, including alternate low-pass settings. The 2440 MHz /
250 kbps phase-discriminator search over the same interval, additional filter
checks and a separate noncoherent search around the request also recovered no
CRC-valid packets. These searches used the known address without filtering
for the expected target or value. Only the stated windows were demodulated;
digital levels and the file hash were checked across all 60 seconds. Zero
decoded packets and zero digital clipping do not establish RF silence or
adequate source SNR.

Decoder controls distinguish two retained recordings. A genuine original
native capture at **8 MS/s** had 2,416 supported packets in its historical
full decode; a bounded recheck recovered 205, 222 and 6 packets with 1.0,
1.3 and 2.0 MHz low-pass settings. A different 48 MS/s position reference had
zero native 2 Mbps decodes and is not that positive control. A retained real
250 kbps Sync capture yielded 17 phase-discriminator and 16 independently
demodulated noncoherent packets, with matching packet times. These checks
validate decoding of retained signals, not sensitivity of the current receive
path.

The successful LAN/physical result therefore does not yet provide an original
native body or schedule for comparison. No value-encoding change, calibrated
travel mapping or explanation of the direct raw-128 endpoint response follows
from these results. Establish original-source reception before using a new
capture to compare native phases and timing.

### Narrow original-app capture

A subsequent receive-only test removed the nominal 30 dB pad from RX1 while
retaining its antenna and DC block. The operator reported six feet to the
original bridge without intervening walls or floors; the bridge remained on
and all repeaters off. The fixed receiver profile was 8 MS/s, 2452 MHz,
6 MHz bandwidth and gain 20. All 480 million samples in 1,832 blocks were
continuous, with no overruns or digital clipping. The receiver closed with
bias tees off, and saved emulator bindings, permissions and sequence remained
unchanged. These changes do not isolate which factor improved reception.

One original-app feature-4/value-127 request arrived 16.338889 seconds after
RX readiness, followed by release 48.287 milliseconds later. Both were inside
the recording. The operator observed the sole controllable top rail lower
from roughly three-quarters to roughly halfway covered, with the bottom rail
fixed and no other shade moving. The app again called this its "bottom rail"
control. A second TCP connection contained initialization and inventory
queries, without another movement request.

Initial blind native decoding recovered 18 unique packets: two command
`0x50` bodies and 16 followup `0x32` bodies, all carrying raw value 127.
Independent extraction from the original IQ verified their preamble,
address, payload and CRC. A bounded refinement using discriminator averaging
and additional decision thresholds recovered **63 unique packets**: three
command and 60 followup bodies, with no other recovered payload. Searches
used the known address and CRC without forcing the expected target or value.
Independent raw-IQ reslicing and CRC checks then verified all 63 packets.
The captured bodies match the primary-position planner's raw-127 output.

The recovered command packets span only about 94 milliseconds near the
observed transition; followup packets span about 286 milliseconds. These are
observation spans, not complete phase durations. Sparse, jittered reception
does not establish total packet counts, exact cadence, phase onset or the
three-channel rotation. An initial lattice fit was rejected as unreliable.
No byte-encoding discrepancy or timing correction follows from this capture,
and the direct raw-128 full-opening result remains unresolved.

### Source-only secondary-position contract

The secondary feature is **decimal 18, hexadecimal `0x12`**, not `0x18`.
Executing the original queue loader, classifiers and complete body builder
passed 48 rows across primary controls and secondary fixtures, two fictional
identity/mask pairs, values 0/128/255, phases 2/3 and both prior alternate states.
Secondary held bodies use code `0x6D`; followup bodies use `0x32`. Both retain
the requested value byte. The primary controls retain `0x50`/`0x32`.

A separate original-code composition passed 18 secondary scheduler scenarios
and 1,374 packet events. Comparison with the primary source fixture found the
same channel, phase, alternate and refresh-counter behavior; only the held
code changed from `0x50` to `0x6D`. The queue classifier disables alternation,
and the counter initialized to 100 remains unchanged across pulses. This
no-refresh result is restricted to the exercised native context (`C9A = 6`,
queue-mode bit clear). Channel selection precedes each pulse and continues
across the forced held-to-followup boundary.

With flags 1, the original duration suffix supplies 150/30 ticks. Fixtures
forced phase expiry after explicit artificial pulse counts, so they do not
establish timer epochs or exact whole-command packet totals. Independent review
checked all builder rows, events, source provenance and recorded pulse boundaries.
Execution stopped before peripheral access. This is source-only evidence: no
public secondary planner, waveform, transmitter, grant or physical rail result
has been added. Primary APIs and live feature-4-only gates remain unchanged.
