<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Protocol conformance before shade testing

The selected live route is **2440 MHz bridge packets to a Platinum repeater**.
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
ELF layout review. It has not yet been loaded onto a DK. Actual reception needs
a known-good radio reference before judging the SDR signal. A second DK can
provide that later positive control. One fixed-channel receiver cannot establish
simultaneous three-channel reception, analogue signal quality or shade
acceptance. No original bridge firmware is included in this receiver.
