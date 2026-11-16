<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# RF wake and idle-time experiments

Status: 2026-11-16. Offline and ESP32 bench preparation are implemented;
RF-only wake acceptance has not been measured locally. Infrared transmission,
IR-assisted pairing and IR hardware are outside this implementation.

## Evidence and bridge implications

The source is **digamesystems/HD_Remote_Clone**, commit
[`c36fbbba46e3481698c8254f8b45db0781dbe07a`](https://github.com/digamesystems/HD_Remote_Clone/tree/c36fbbba46e3481698c8254f8b45db0781dbe07a).
Its [RF report](https://github.com/digamesystems/HD_Remote_Clone/blob/c36fbbba46e3481698c8254f8b45db0781dbe07a/docs/RF_PROTOCOL.md)
and [2026-11-15 timing log](https://github.com/digamesystems/HD_Remote_Clone/blob/c36fbbba46e3481698c8254f8b45db0781dbe07a/captures/shade_timing_20261115.log)
supply external evidence, not a local reproduction.

| Finding | Scope and implication |
| --- | --- |
| Red-mode arrows send `ID0 ID1 01 00 80`, without direction | Sniffed on two remotes, channel 33. Identifies a plausible purpose for our locally captured `01 00 80` state. |
| Synthesized IR produced 0 responses in 20 trials; RF plus IR moved the shade | Establishes an RF enable for IR on their shade, not an RF-only bridge prerequisite. |
| After approximately 4–14 s idle, a 0.32 s interleaved RF/IR sequence worked 8/18; 1.94 s worked 9/9 | Small manual trials on one DC-converted battery shade. Suggests duty cycling; internal sleep behavior is inferred. The 1.94 s includes IR, not continuous RF wake. |
| RF-only group commands send held direction then release, without a distinct wake | `prepareWake()` configures the radio; `sendGroup()` replaces its payload before transmitting. A separate wake is not established for every RF operation. |
| Two unpaired IDs enabled IR; group commands checked pairing | Do not generalize to native positioning or enrollment. Our experiment uses the target's existing room RF identity. |

Later interleaved tests supersede the older impression that a 450 ms wake
followed by IR was reliable. Neither that duration nor their 50 ms per-channel
interleaving becomes a bridge constant. Their commodity nRF24-style module
results do not qualify this project's NiceRF module or its exact 2 Mbps framing.

Our original-firmware probes found no mandatory cold-start phase-1 prelude.
That result remains valid within its scope. The new experimental wake is a
different payload, distinct from that scheduler phase, the RF preamble, PLL
settling or carrier lead-in.

## Implemented RF-only preparation

`build_wake_payload(identity)` produces the five-byte candidate. Decoding labels
`01 00 80` as `wake` and `01 00 00` as `release-wake` only with mode 01 and
group 00. Other 80-valued packets retain their interpretation. No wake release
tail is emitted: external remotes differ on it, and no RF-only bridge need for
it is established.

`NativePositionPlan` supports three explicit preparations:

| Preparation | Prefix | Remaining train |
| --- | --- | --- |
| `none` (default) | No prefix; count must be zero | Existing command and followup |
| `wake` | `room-ID 01 00 80` | Same command and followup |
| `command-control` | Extra `room-ID 50 mask position` packets | Same command and followup |

Positive preparation counts must be multiples of three. Rotation continues
33 → 52 → 71 through every phase boundary, preserving the first command's
channel relative to a baseline with the same prior channel. The nominal
200.5 µs slot, command/followup counts, bodies and shaping remain unchanged.
Preparation counts toward the **combined two-second limit**, silent slot parts
included. Defaults add no prefix. HTTP/TCP permissions, enrollment, secondary
position and Jog are unchanged; there are no automatic retries.

The standard 7,500-command / 1,500-followup train lasts 1.8045 s. At most **975
preparation packets (195.4875 ms)** fit, giving 1.9999875 s overall; 978 are
rejected. This cannot reproduce a 1–2 s wake before the unchanged train. Do not
silently shorten baseline or split a combined experiment across sends to evade
the limit. A longer experiment needs a reviewed lifecycle and airtime budget.

The CLI creates only a new, mode-0600 offline SC16Q11 file:

```sh
PYTHONPATH=src .venv/bin/python -m hd_platinum rf-native-position-waveform \
  tmp/fictional-wake.sc16q11 --room-rf-id 1234 --shade-mask 0x08 \
  --position 128 --prior-channel 71 --command-frames 7500 \
  --followup-frames 1500 --slot-us 200.5 \
  --preparation wake --preparation-frames 300
```

The identity is fictional. This example adds 60.15 ms and creates about 358 MB
of IQ. Use a different output path and `--preparation command-control` with the
same count for the airtime control. Use `--preparation none` and
`--preparation-frames 0` for baseline. IQ contains the identity despite redacted
metadata. Existing files/symlinks are refused. Metadata records mode, count,
seconds, payload and unqualified status. Creating an artifact does not open a
radio, create a grant or authorize a physical trial.

The ESP32 uses `NativePreparation::{None,Wake,CommandControl}` and
`NativeSchedule::preparation_frames`. Preparation is admitted only for primary
position with `NativeAccess::Bench`; qualified access rejects it before CE.
Cancellation, admission expiry, timeout and shutdown also apply during the
prefix. See [configuration and telemetry](../firmware/esp32_gateway/docs/radio-qualification.md#optional-wake-preparation).

The **2440 MHz / 250 kbps bridge/repeater route is unchanged**. Combining it
with a native wake requires measured cross-profile timing and explicit retuning
and lifecycle work. A repeater could already supply the shade-facing acquisition
interval; capture this rather than assuming it.

## Required evidence collection

Pre-push software checks on 2026-11-16: all 369 host tests passed, including the
hash-pinned actual-upstream-source libbladeRF regression with sanitizers.
Source distribution and wheel built. All 12 portable firmware test programs
passed with address/undefined-behavior sanitizers, along with seven simulator
adapter tests and 14 instruction-emulator network/control checks. Ordinary and
native-test Wi-Fi/Ethernet images and the emulator image built. These checks
used synthetic identities, fake radios and offline IQ, with no hardware trial.

1. **Capture original behavior first.** Record original-bridge primary
   positioning after approximately 1, 5, 15 and 60 s idle on the paired target.
   Cover 2440 MHz and all three native channels, documenting any missing
   coverage. Look for `01 00 80`, emitter, lead time, duration, phase boundaries,
   channel order and cadence. Compare first attempts and successful repeats.
   Missing decoded frames do not prove absence of a signal.
2. **Qualify written and emitted waveforms.** Independently decode offline IQ,
   then use protected independent RF reception with a fictional identity.
   Verify bodies, address, 88-bit framing, CRC, all channels, prefix count,
   boundary spacing, complete tail and total duration. On ESP32, collect CE,
   SPI/status and cancellation/lateness traces under network/display load.
3. **Control starting conditions.** Use a fixed starting rail mark and a
   distinct requested mark. Wait for setup movement to stop before timing idle.
   Measure idle from the last relevant RF transmission, including remote,
   repeater and position-restoration traffic. Log intervening activity and
   original bridge/repeater power state. Keep target, antenna, gain and placement
   fixed. Record shade/product and battery/DC power arrangement.
4. **Randomize baseline, wake and command-control trials.** Start with 10 first
   attempts per condition/idle interval. Wake and control use identical positive
   counts with no extra gap; retain the original command/followup waveform.
   Record motion onset: the control prefix can itself command the position.
   Count warm repeats separately; a rescued attempt is not first-attempt success.
   Preserve failures and stop for unexpected target movement.
5. **Interpret before qualifying.** Improvement with both active prefixes may
   indicate acquisition time rather than a special opcode. Wake-only improvement
   supports a more specific effect. Failure of a short prefix does not exclude
   a longer acquisition requirement. Report counts and uncertainty by idle
   interval, then expand to other products; one success does not qualify a path.

Retain for each trial: UTC time and monotonic RF/motion offsets; source commit,
firmware/module versions; private target/grant reference; starting, requested
and observed rail marks; actual idle interval; preparation mode/count/duration;
command/followup counts and first channel; requested/active radio readbacks;
IQ hash, receiver settings and continuity/overrun records; valid/invalid CRC
counts by phase/channel; observed movement, latency and target isolation;
software result/lateness/cancellation; and first-attempt versus warm-repeat
classification. Identity-bearing artifacts stay private; publish sanitized
results with failures and coverage limits. Watched movement and wiring changes
need current operator readiness under the existing validation plan. No new
physical acceptance is claimed by this implementation.
