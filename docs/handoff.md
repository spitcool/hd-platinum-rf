<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Laptop handoff — 2026-10-24

The objective is a replacement Platinum bridge covering RF control and
enrollment, the original mobile app, and LAN integration with Control4 and other
clients. Original-app discovery, inventory loading, and primary-position control
have been demonstrated with the original bridge off. An existing target also
jogged after an emulator Sync request and a manual receiver-button action,
without an app Jog request. Full enrollment under a new RF identity has not
been demonstrated. This is not yet a complete bridge.

The successful 250 kbps profile is implemented in
the public `bladerf-bridge` backend and `bridge-emulate` runtime. The earlier
`bridge-serve` position backend remains a separate 2 Mbps implementation.
Consult the private session journal for current wiring, bridge power, and
service state; the completed reference captures do not establish their present
state.

## Read these first

- This handoff describes the software, evidence limits, and restart order.
- The operator's **`hd-platinum-laptop-private-handoff.md` in the desktop's
  Downloads folder** contains the exact private paths, bridge address, allowed
  targets, artifact inventory, and transfer commands. It is not in Git.
- [Local bridge prototype](bridge-prototype.md) documents configuration and API
  behavior; [testing](testing.md) defines validation requirements.
- [RF protocol](rf-protocol.md), [LAN protocol](lan-protocol.md), and the
  [lab log](lab-log.md) separate captured facts from unverified hypotheses.

Cloning the repository supplies the source, tests, and sanitized documentation.
It does **not** supply the private configuration/token, raw recordings,
timestamp sidecars, exploratory analysis scripts, original inventory, FPGA
image, or operator constraints. Transfer those separately using the Downloads
document and preserve their relative directory layout. Do not copy `.venv`;
recreate it on the laptop. The Downloads document is an inventory and guide,
not a backup of the recordings.

## Implemented and verified

- Offline 88/97-bit frame parsing, CRC checks, SC16Q11 decoding, and finite
  handheld/position waveform generation are implemented.
- Captures support individual-position room identity, one-hot shade selection,
  and native values `0`, `128`, and `255` for the observed targets. Mapping
  validity does not establish physical delivery or actual position.
- The local HTTP dashboard/API supports authenticated commands, explicit target
  configuration, serialized transmission, idempotency, and dry-run operation.
  It does not contact the original bridge at runtime. `bridge-emulate` adds the
  observed TCP port 522 inventory, keepalive, primary-position staging/release
  subset and optional NetBIOS discovery. Original mobile-app discovery, inventory,
  and one-target primary-position control are demonstrated with the original
  bridge off. Explicitly enabled existing-target Sync has an operator-observed
  response under the same condition. New-identity enrollment, broader app setup,
  and Control4 integration remain unverified.
- A live TCP stage/release completed, produced ten matching transmitted packets
  and ten matching repeater-response packets, and closed the target according
  to the operator. Requested state and sequence allocation survived restart.
  The original app discovered the emulator, accepted the observed year-check
  reply, loaded the saved database, and moved the target roughly halfway.
- At the original-app position-control checkpoint, **192 tests** passed and both
  source distribution and wheel built. Later changes require the current full
  checks in [testing instructions](testing.md).
- Static analysis of the user-supplied Android app identified 25 product types
  and the room/shade create, edit, and delete command grammar. Mutable inventory
  support is being integrated from that evidence; original-app acceptance of
  those metadata flows remains pending. New records do not acquire RF access.
- The bladeRF backend provides bounded TX and RX with timestamp/overrun
  metadata. Conducted handheld checks recovered `993/1000`, `1000/1000`, and
  `1000/1000` expected packets on the three channels. This is not proof of
  motor control through that 2 Mbps backend. The 250 kbps encoder reproduces
  both working private artifacts byte for byte. Its public backend preserves
  concurrent RX, active TX readbacks, finite submission, and shutdown behavior.
- Software tests cover sanitized packet encoding, persistent sequence
  reservation, fake-radio failures, TCP/HTTP dispatch, and optional discovery.
  Tests use synthetic fixtures, fake hardware, and local loopback servers;
  they do not establish RF delivery or original-app interoperability. Run the
  current complete suite and build using [testing instructions](testing.md).
- The laptop reports USB SuperSpeed. A five-second receive check at 48 MS/s
  completed with zero timestamp gaps or overruns. This qualifies that bounded
  check, not all future streams or simultaneous wideband TX/RX.

## Preserve these findings

The earlier 2 Mbps position backend uses a **fresh device handle for each channel**.
Reusing a handle after clock reconfiguration caused the second channel to fail
with `Requested timestamp is in the past` because the library retained a TX
timestamp cursor. Do not restore the earlier same-handle implementation.

The existing sequential 8 MS/s position artifacts use **702 µs same-channel spacing**
(`3 × 234 µs`), with 2,100 first-phase and 425 followup frames per channel.
Each lasts 1.77255 seconds; the three sequential files total 5.31765 seconds
including silence, plus device setup gaps. The offline simultaneous-channel
generator still uses 234 µs hop slots. Historical compressed single-channel
files are not the current profile. Neither sequential submission nor correct
offline decoding proves the shades accept this timing. Fresh laptop reference
captures instead show about **600 µs** same-channel spacing for their 2 Mbps
train. Preserve both capture-specific findings; neither is a universal cadence.

Earlier 2 Mbps attempts at transmit gains 35, 50, and 60 dB produced **no observed movement**.
The final 50/60 dB tests completed all three frequencies with corrected cadence.
Distance is a possible cause, not an established diagnosis. Gain is a device
setting, not a measurement of radiated power; another increase is not the next
step supported by the evidence.

The previously undecoded 2440 MHz signal now supports **250 kbps ESB framing**
with a three-byte `E7 E7 E7` address, nine-bit PCF, 9- or 12-byte payloads, and
CRC-16. Early and later packet groups support a repeater-forwarding interpretation,
but application roles and field semantics remain incomplete. Private analysis
and synthesis helpers retain the original evidence. `rf_bridge.py` now encodes
the supported position exchange for the new public `bladerf-bridge` backend;
the legacy 2 Mbps backend remains separate.

The first narrow candidate preserved eight recovered packets from a bridge-only
closed-position capture. Two expected packet slots were obscured by interference
and left silent. One approximately 112 ms trial at TX system gain 35 dB, with
the original bridge off and one UXUPR powered, produced no movement. It was an
incomplete exchange, so failure does not falsify the protocol or establish a
power problem. Subsequent nominal 40 dB conducted tests were continuous and
unclipped; at TX gain 35 dB and RX gain 40 dB, all eight frames matched the
artifact exactly, including CRC and timing. Lower TX gains were below useful
SNR. This shared-oscillator test does not qualify absolute frequency, radiated
power, antennas, or shade acceptance.

A fresh bridge-only closed reference recovered all ten packets in one observed
alternating train, and the operator confirmed closure. A subsequent 2440 MHz
midpoint reference produced observed halfway movement. The new candidate copied
all ten source packets and their relative timing, using the same PHY as the
conducted eight-packet artifact. Independent written-IQ checks passed for every
frame. One finite **112.134 ms** trial at gain **35 dB** and one identical trial
at **50 dB**, with the original bridge off and one UXUPR on, each produced **no
movement and no observed repeater LED response**. Together with the earlier
eight-packet trial, these were the first three over-the-air trials in this laptop session.
Completeness refers to the observed train, not the entire application exchange
outside the captured band and time. Gain remains a device setting; disabled
gain-stage readback is not an active output-power measurement.

The fourth trial submitted the **unchanged ten-packet closed candidate** at
gain 50 dB while recording three seconds through the second antenna at RX gain
40 dB. Active TX readback was 50 dB overall, -16 dB DSA, and `2439999998 Hz`.
The recording recovered the ten submitted packets plus ten later packets
consistent with repeater forwarding, and the operator reported **shade movement**.
The fifth trial kept the working schedule, PID/`NO_ACK`, and PHY, substituting
captured midpoint payloads and a capture-supported short-packet sequence. Four
short payloads matched fresh captures; the missing countdown value was derived
using the observed group field and validated XOR rule. All outer CRCs were
recomputed. The operator confirmed **roughly halfway and a repeater LED response**.

The session totals five over-the-air trials: three without observed movement,
then these two observed responses. Both successful runs used the original flat
carrier lead. A leading-zero variant was prepared but never transmitted. The
effect of concurrent RX, the second antenna, and connector reseating has not
been isolated; RX is not established as a protocol requirement.
See the [RF notes](rf-protocol.md#2440-mhz-bridge-and-repeater-observations--2026-10-24)
and [lab log](lab-log.md#laptop-reference-captures-and-narrow-candidate--2026-10-24).

## Laptop software setup

From a fresh clone of the pushed branch, use a Python supported by the package
(`>=3.9`) and rebuild the environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade 'pip>=21.3'
python -m pip install -e '.[analysis]'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -q
```

The desktop's fully tested scientific environment was Python 3.9.6, NumPy
1.26.4, and SciPy 1.13.1. Private plotting scripts additionally use matplotlib;
it is not part of the package's `analysis` extra. Run the tests on the laptop
instead of assuming its Python/native-library combination has been qualified.

Hardware access requires the **libbladeRF 2.6 ABI**; the backend rejects other
major/minor versions. The desktop used Homebrew `libbladerf 2025.10`, CLI 1.10.0,
and library 2.6.0. Check the laptop's actual installed versions. The tested
board is a bladeRF 2.0 micro xA4 with existing FX3 firmware 2.4.0 and compatible
FPGA 0.15.3, loaded temporarily into RAM. Transfer the verified image identified
in the private guide; USB power loss may require reloading it. No firmware
flash update is part of the handoff.

After restoring the private configuration and original inventory, start a
**dry-run** emulator while testing software setup. Substitute the restored paths:

```sh
hd-platinum bridge-emulate \
  --config tmp/bridge/config.private.json \
  --inventory tmp/bridge/inventory.private.json \
  --state-dir tmp/bridge/emulator-state \
  --backend dry-run
```

Open `http://127.0.0.1:8077/`. A simulated receipt confirms software flow only.
Enabled position mappings in the saved configuration are capture-supported.
The live backend requires an empty `groups` map; room RF IDs and one-hot shade
masks must agree with the saved inventory. There is no installed autostart
service to migrate.

For live operation, change the backend to `bladerf-bridge` and supply
`--initial-sequence "$NEXT_SEQUENCE"` only when creating a new state store.
Obtain that installation-specific value from the private session journal; no
public example seed is safe to reuse. Preserve the state directory across
restarts and omit the seed afterward. Reservations are persisted before radio
access, serialized across processes, and consumed even after an uncertain
failure. There is no automatic retry or local ordinal reset. Firmware analysis
establishes that only the low eight bits are the wrapping on-air transaction
counter; the adjacent byte is command count and remains one. The existing
version-1 state file and its local exhaustion limit are preserved.

The default profile is ten packets in `112.134 ms`, `2440 MHz`, `250 kbps`,
`8 MS/s`, `1.5 MHz` bandwidth, and a flat carrier lead. Position commands retain
three seconds of concurrent RX; explicitly enabled Sync retains eighteen
seconds. Defaults are TX gain `50` and RX gain `40`; these are device
settings, not absolute power measurements. Each command opens a fresh device,
checks active TX gain/DSA/frequency and RX health before IQ submission, and
retains bounded private IQ, metadata, and receipts under `state-dir/rf/runs`.

Opt in to `--sync-rf-profile wide` to record the bridge link and covered native
channels during Sync. Position controls keep the default narrow profile. Wide
Sync uses reviewed factor-four interpolation at `32 MS/s` TX with the same
packet data, duration, center frequency, and `1.5 MHz` TX bandwidth. RX uses
`32 MS/s`, center `2446 MHz`, and `32 MHz` bandwidth: `2440`, `2433`, and
`2452 MHz` are covered; `2471 MHz` is outside the recording. RX gain remains
the explicit `--rx-gain` setting; the diagnostic reference used `30`.
Both backends share the durable sequence store and command serialization.
The combined `64 MS/s` rate stays below the library's recommended `80 MS/s`;
the earlier simultaneous `48+48 MS/s` experiment failed continuity.

Wide Sync requires a healthy receive window before IQ submission and at least
sixteen seconds of recorded samples after TX. It checks the active equal-rate
timestamp relationship and applies a conservative `25 ms` timing allowance;
this is a coarse diagnostic check, not calibrated synchronization. A later
capture failure still consumes the sequence and never triggers an automatic
RF retry. An eighteen-second wide recording is about `2.3 GB` before retention
pruning. Captured forwarding/native signaling does not confirm shade enrollment.
The default retains four runs. Bias tees are kept off and device ownership is
retained until receive shutdown completes.

Sync sends its TCP room-action event after finite TX submission, then waits for
the full diagnostic capture and cleanup before action-end. Private receipts
record UTC and monotonic elapsed times for waveform preparation, radio setup,
first RX block, TX submission, receive completion, and cleanup. These separate
transport activity from capture duration; they do not confirm enrollment.

TCP and HTTP share one dispatcher. Both bind to loopback by default. LAN TCP
binding requires `--allowed-client` with explicit trusted local CIDRs. Optional
`--discovery --advertise-host "$EMULATOR_LAN_IP"` enables UDP 137 NetBIOS
responses for the emulator's address. An existing `netbiosd` listener can block
startup; `--discovery-reuse-port` requests sharing but cannot establish discovery
compatibility. Wildcard HTTP binding also requires `--allowed-host`.

Inventory positions are saved requested values, never measured feedback.
Original-app discovery, inventory, and one-target position control are verified;
Control4 and full new-identity enrollment remain unverified. Sync requires an
explicit per-target `sync_enabled` grant and does not update position state.
The existing-target Sync observation is not proof of enrollment under a new
identity. Jog is now implemented with separate default-off `jog_enabled`
permission and an identity-bound `jog` grant for revoked/recreated targets.
The original-app feature-12 request stages one Jog and requires release; mixed
Jog/position batches are rejected, and position state is untouched. Offline
packet and fake-backend tests pass, but emulator Jog movement and full
new-identity enrollment remain unverified. Scene mutation and reset remain
unsupported. The original app's observed 15-second Sync countdown is distinct
from the backend's 18-second diagnostic RX window.
See the [runtime commands](../README.md#bridge-emulator).

The mutable inventory store preserves opaque source records, requested-position
overlays, and stable IDs in one atomic private state file. Known definitions are
served in ascending ID order. The Android app indexes lists by ID, so LAN
deletion rejects changes that would leave an ID hole; IDs are never silently
compacted. Deletes with recognized scene references are also rejected. Metadata
deletion does not claim RF unpairing, and newly created or rebound identities
remain disabled for RF. App acceptance of these editing flows is still pending.

Use optional `--protocol-log tmp/bridge/tcp.private.jsonl` when investigating
original-client compatibility. It records raw TCP request/response bytes,
including unsupported setup requests, in private mode-0600 JSONL with a `1 MiB`
file limit and one backup. Keep these identity-bearing records in ignored
storage. A wire trace establishes client messages and responses; it does not by
itself establish physical enrollment.

The ignored private `diagnose_radiated_path.py` helper accepts `--candidate closed`
or `--candidate midpoint`, plus a new `--stem`. It defaults to a dry run;
`--execute` selects one finite burst with concurrent RX after setup confirmation.
It checks an explicit artifact hash and active gain before IQ submission and
retains exclusive private receipts and captures. This helper is not installed
public runtime functionality, and no further invocation is currently planned.

## Remaining integration and physical validation

1. Read the private allowlist and current session journal, and reconfirm actual
   wiring before changing the RF setup.
2. Preserve the working artifacts and observations while testing the integrated
   emulator. Complete original-app metadata editing acceptance and deliberate
   new-identity enrollment validation. The cause of earlier failures,
   repeatability, broader target coverage, and Control4 behavior remain unresolved.
3. Choose any future bounded, observed test from that evidence. Maintain the
   configured room scope; the separately recorded one-target exception does not
   authorize its whole room. Preserve before/after journals, timing metadata,
   settings, and the operator's actual observation, including negative results.

Reliable observed control, the remaining protocol work, and eventual legacy
bridge/API compatibility are still required before calling this a replacement
device.
