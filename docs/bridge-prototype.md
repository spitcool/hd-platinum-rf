<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Local Platinum shade-control prototype

The prototype exposes an HTTP API and a browser control page for handheld
group Up/Down commands and experimental individual-shade position requests. It
can simulate requests or synthesize finite commands for a bladeRF. The service
uses private, explicitly configured RF identities and target mappings; it does
not contact the original App Bridge at runtime.

**Validation status:** locally captured bridge-command sequences establish the
position payload's room identity, one-hot shade mask, and native position byte
for observed values 0, 128, and 255 across two rooms. Same-target comparisons
isolate the position byte, and same-room comparisons support distinct shade
masks. This does not establish every target/value or SDR-to-shade operation.
Position mappings remain disabled by default until validated for that target.

Generated handheld packets decode in software across all three channels,
including release packets. Protected single-channel RF tests recovered
993/1,000, 1,000/1,000, and 1,000/1,000 expected handheld packets at 2433, 2452,
and 2471 MHz respectively, with continuous receive timestamps. These bench
results do not demonstrate shade acceptance. Gaussian shaping, repetition
counts, and the transmit envelope remain synthesis assumptions. See the
[RF protocol evidence](rf-protocol.md) and [validation plan](testing.md).

## Install and create a private configuration

From the repository root, activate the virtual environment described in the
[README](../README.md#research-cli), then install the analysis dependencies:

```sh
python -m pip install -e '.[analysis]'
```

Existing configurations with `remote_id`, `groups`, and `api_token` remain
compatible. An optional `shades` object adds individual targets. Group keys are
strings `"1"` through `"4"`; shade keys are canonical decimal strings `"0"`
through `"99"`. Configure only the groups and shades intended for control.
`groups` may be empty when at least one shade is present. A group mapping must
be verified independently; a room's shade mask is not a handheld group number.

This creates a disabled example shade and a fresh API token. Both RF identities
are fictional. The required `remote_id` is unused while `groups` is empty.

```sh
umask 077
mkdir -p tmp/bridge
export HD_PLATINUM_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python - <<'PY'
import json
import os
from pathlib import Path

config = {
    "remote_id": "aabb",
    "groups": {},
    "api_token": os.environ["HD_PLATINUM_TOKEN"],
    "shades": {
        "6": {
            "name": "Example shade",
            "room_id": 1,
            "room_rf_id": "ccdd",
            "mask": 4,
            "feature": 4,
            "position_enabled": False,
        }
    },
}
with Path("tmp/bridge/config.private.json").open("x", encoding="utf-8") as output:
    json.dump(config, output, indent=2)
    output.write("\n")
PY
```

The exclusive create preserves an existing configuration. Keep this file and
generated IQ under ignored `tmp/` or `captures/` paths; both contain private
installation information. The bearer token must contain 16–256 visible ASCII
characters without spaces.

Each shade requires `name`, `room_id`, `room_rf_id`, and `mask`. The room RF ID
must contain two bytes expressed as four hexadecimal digits. `mask` must be one
of 1, 2, 4, 8, 16, 32, 64, or 128. Only primary-position feature `4` is
implemented; it is the default when omitted. `position_enabled` defaults to
`false`. Duplicate room-RF-ID/mask pairs are rejected. Public API responses omit
RF identities and masks, while retaining display labels and room/shade numbers.

Populate a real private configuration from local evidence, keeping unvalidated
targets disabled and unrelated rooms absent. Enabling a mapping is an explicit
configuration change, not an automatic consequence of decoding a packet.

## Exercise the HTTP service without RF

```sh
hd-platinum bridge-serve \
  --config tmp/bridge/config.private.json \
  --backend dry-run
```

The default listener is `127.0.0.1:8077`. Open
`http://127.0.0.1:8077/` for the controls. Enter the configuration's API token to
submit commands. The dry-run backend reports `simulated` and never opens the
radio. Disabled mappings remain blocked in both backends. To exercise a
successful position simulation, use a separate fictional configuration with
its example target enabled and retain `--backend dry-run`.

The position slider shows a requested percentage and its corresponding native
integer, calculated as `round(percent * 255 / 100)`. Dragging it does not send a
command; press **Set requested position** to submit. The displayed value is not
a measured position. Disabled targets have disabled controls.

In another terminal, inspect the configured targets and request native position
128. With the disabled example configuration above, the POST intentionally
returns `409 validation_required` without calling a backend:

```sh
export HD_PLATINUM_TOKEN="$(python -c 'import json; print(json.load(open("tmp/bridge/config.private.json"))["api_token"])')"
curl --fail-with-body --silent --show-error http://127.0.0.1:8077/api/shades
curl --fail-with-body --silent --show-error \
  http://127.0.0.1:8077/api/positions \
  -H "Authorization: Bearer ${HD_PLATINUM_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data '{"shade":6,"position":128,"request_id":"manual-position-001"}'
```

For a separately configured group, POST to `/api/commands` with
`{"group":1,"action":"up","request_id":"manual-up-001"}`; `"down"` is the other
supported action. An empty `groups` configuration exposes no group commands.

Give each new request a new `request_id`; reuse it when retrying the same
request. Both endpoints share one transmission lock and one cache of up to
1,024 successful IDs. Reusing an ID for a different command, including across
endpoints, returns `409 idempotency_conflict`. Concurrent commands return
`409 busy`. Restarting the service or evicting an old ID ends duplicate
protection. Failed backend calls are not cached and can leave delivery unknown.

| Endpoint | Purpose |
| --- | --- |
| `GET /` | Browser group and individual-shade controls. |
| `GET /health` | Service/backend state and whether a transmission is busy. |
| `GET /api/groups` | Configured group numbers and labels. |
| `POST /api/commands` | Bearer-authenticated `group`, `action`, and optional `request_id`. |
| `GET /api/shades` | Shade labels, room numbers, enabled flags, and position-backend availability; no RF IDs or masks. |
| `POST /api/positions` | Bearer-authenticated `shade`, integer `position` in 0–255, and optional `request_id`. |

Command receipts always report `delivery: "unverified"` and
`position_confirmed: false`. Position receipts contain `requested_position`,
not an observed position. An enabled target with no position backend returns
`503 position_unavailable`. A successful submission does not confirm movement.
Keep the default local listener; the service is not intended for public-internet
exposure.

## Generate and inspect a waveform

The waveform commands create private SC16Q11 files without opening a radio.
Metadata redacts the two-byte identity and includes a SHA-256 hash, sample count,
and synthesis settings. The IQ itself contains the identity. Existing files are
preserved unless `--overwrite` is explicitly selected.

This small position example uses a fictional room identity and generates two
command cycles plus one followup cycle across all three frequencies:

```sh
hd-platinum rf-position-waveform tmp/bridge/position-example.sc16q11 \
  --room-rf-id ccdd --shade-mask 0x04 --position 128 \
  --command-repetitions 2 --followup-repetitions 1

hd-platinum rf-iq-decode tmp/bridge/position-example.sc16q11 \
  --sample-rate 48000000 --center 2452000000 \
  > tmp/bridge/position-example-decoded.json
```

The example contains nine frames, 101,088 complex samples, and 404,352 bytes
over 2.106 ms. Position synthesis uses 234 µs slots, a 49 µs lead-in, 44 µs
packet, 2 µs ramp-down, 320 kHz deviation, Gaussian BT 0.5, and amplitude 0.5.
The payload phases are room ID + `50` + mask + position, followed by room ID +
`32` + mask + position. “Command” and “followup” are descriptive labels; their
device-side semantics remain unresolved. Without repetition overrides, the
candidate profile uses 2,100 command and 425 followup cycles: 7,575 frames over
1.77255 seconds. These counts and timing are provisional.

For a handheld Group 1 Up waveform:

```sh
hd-platinum rf-waveform tmp/bridge/group1-up.sc16q11 \
  --remote-id aabb --groups 1 --action up

hd-platinum rf-iq-decode tmp/bridge/group1-up.sc16q11 \
  --sample-rate 48000000 --center 2452000000 \
  > tmp/bridge/group1-up-decoded.json
```

Both offline generators default to a 48 MS/s stream centered at 2452 MHz, with digital offsets
for 2433, 2452, and 2471 MHz. Sequential 195 µs slots avoid hardware retuning
between handheld packets. Each handheld pulse contains a 49 µs carrier lead-in,
44 µs packet, and 2 µs ramp-down. There are 500 action cycles followed by 500 release cycles:
3,000 packets over 0.585 seconds, producing 112,320,000 bytes. The waveform
planner limits any command to two seconds including gaps.

The packet has an `aa` preamble, `e7e7e7` address, five-byte payload, and CRC-16,
without a packet-control field. Both profiles use 2 Mbps; the handheld profile
uses 360 kHz deviation, Gaussian BT 0.5, and normalized amplitude 0.5. These waveform
parameters are explicit in the generation metadata. Software decoding checks
packet integrity; the remaining RF checks are described in
[Testing and validation](testing.md#validation-sequence).

## Connect the bladeRF backend

After completing the applicable RF validation setup, stop the dry-run service
and select the hardware backend:

```sh
hd-platinum bridge-serve \
  --config tmp/bridge/config.private.json \
  --backend bladerf \
  --cache-dir tmp/bridge/waveforms \
  --tx-gain 35 \
  --fpga tmp/firmware/hostedxA4.rbf
```

Use an FPGA image matching the board variant and its FX3 firmware. The image is
loaded into RAM when needed. The backend builds a finite waveform for each
command, submits it through TX1, disables TX afterward, and releases the device.
Both bladeRF command profiles use separately tuned 8 MS/s bursts with 6 MHz bandwidth,
one frequency at a time. They prepare all three private waveform files before
opening hardware and use a fresh device handle for each channel. This avoids a
locally observed libbladeRF 2.6 timestamp-epoch mismatch after sample-clock
reconfiguration. Each session disables and closes before the next starts. Handheld commands
contain 500 action and 500 release frames over 0.195 seconds per channel:
3,000 frames and 0.585 seconds total. Position requests contain 2,100 command
and 425 followup frames with 702 µs spacing on each frequency. This preserves
the observed same-channel cadence of the original's three-frequency cycle of
234 µs hop slots. Each position artifact lasts 1.77255 seconds, within the
two-second per-transmission bound; the three sequential artifacts total 7,575
frames and 5.31765 seconds including inter-packet silence. Their pulses occupy
about 0.720 seconds in total. These durations exclude device setup and hardware
tuning/settling gaps. The offline three-channel generator keeps 234 µs hop slots.
The sequential per-channel strategy differs from the observed rapid channel
cycling; shade interoperability remains unverified. This avoids the
failed simultaneous 48 MS/s TX/RX qualification; the standalone offline
generator retains its explicit 48 MS/s wideband mode.
The waveform cache is private. Gain is a device setting, not a calibrated output
power in dBm; retain the settings established by the bench validation.

For a standalone, already-generated artifact with a configured FPGA:

```sh
hd-platinum rf-transmit tmp/bridge/group1-up.sc16q11 \
  --sample-rate 48000000 --center 2452000000 \
  --bandwidth 46000000 --gain 35
```

This last command transmits RF. The example artifact still contains the
fictional identity, so it is suitable as a distinct identity control during
validation. Use the [protected bench topology](testing.md#safe-rf-interconnects)
and a locally captured identity for the corresponding positive control.

The hardware backend reports `submitted`; neither that receipt nor the
requested frame count establishes receiver acceptance or shade position.

## Integration boundary

An automation adapter can map groups to Up/Down requests and enabled shade
targets to native 0–255 position requests, retaining request IDs for retries.
Keep displayed state explicitly unconfirmed. The original App Bridge was a
reference for inventory and RF capture; this service's radio backends have no
LAN dependency on it. The service does not emulate its TCP protocol.

Feedback on actual shade position, secondary features such as vane/rail control,
stop commands, pairing, and a Control4 driver require further work. Captured
position bytes and software/backend tests establish a candidate implementation;
physical shade acceptance remains the next validation step.
