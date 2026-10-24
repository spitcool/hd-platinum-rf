<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Protocol conformance before shade testing

The selected live route is **2440 MHz bridge packets to a Platinum repeater**.
The repeater supplies the native shade transmissions. Original firmware
execution and independently decoded recordings provide separate references.
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

## Route limits and next physical check

The experimental direct 2 Mbps hardware backends currently send an entire train
on one channel before retuning. They do not reproduce the original per-packet
hopping scheduler, and do not provide dedicated native Sync/Jog plans. Keep
their shade interoperability status unqualified; passing native payload checks
does not validate those backends.

The next controlled check uses one already paired shade and one finite Jog via
the corrected 2440 MHz backend, with the original bridge off and a known
repeater on. Verify the recorded transmitted packets and obtain an operator's
movement observation. This separates ordinary control from enrollment before
another attempt to assign a new shade identity. New-identity enrollment remains
unresolved, including on the original bridge.
