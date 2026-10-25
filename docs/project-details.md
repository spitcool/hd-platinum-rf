<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Project details and research tools

[← Project overview](../README.md) · [Build your ESP32 gateway](esp32-build.md)

This page collects the research tools, runtime commands, and implementation
notes behind the project. For the current RF findings and remaining validation,
see the [RF validation plan](rf-validation-plan.md).

Open-source tools and protocol documentation ensuring continued communication between discontinued Hunter Douglas Platinum bridges, blinds, and shades.

The project treats the LAN protocol and the two distinct RF paths as separate research surfaces:

| Interface | Project scope |
| --- | --- |
| Ethernet client ↔ Platinum App Bridge | Document the legacy LAN protocol, provide a research client, and emulate its observed command subset. |
| Legacy four-group handheld remote ↔ shades | Recover and validate the handheld remote's RF waveform. |
| Platinum App Bridge ↔ RF network | Encode the observed 250 kbps bridge/repeater commands and continue validating device interoperability. |
| Control4 | Integrate only after the underlying protocol work is validated; this is Phase 2. |

## Documentation

- [Next RF validation steps](rf-validation-plan.md) — three-channel receiver results and the staged plan for shade control, new enrollment, product features and clients.
- [Laptop handoff](handoff.md) — current implementation, unresolved RF findings, and setup for continuing on another computer.
- [LAN protocol](lan-protocol.md) — byte-level framing, records, commands, feature codes, compatibility differences, and sanitized live evidence.
- [RF protocol](rf-protocol.md) — device-generation boundary, handheld payloads, PHY/framing hypotheses, bridge bandwidth evidence, and the capture/validation procedure.
- [M5CoreS3 gateway firmware](../firmware/esp32_gateway/README.md) — independent ESP32-S3 firmware, TCP 522, bearer API, web controls, and experimental packet radio.
- [Local bridge prototype](bridge-prototype.md) — private configuration, browser controls, authenticated HTTP commands, waveform generation, and the experimental bladeRF backend.
- [Testing and validation](testing.md) — reference environment, safe RF interconnects, automated tests, evidence gates, and objective project status.
- [RF validation bench bill of materials](bom.md) — required quantities, reference parts, connector requirements, and optional bench expansions.
- [Reference bench lab log](lab-log.md) — sanitized capability qualifications and test history; useful project evidence, but not canonical requirements for other installations.
- [Licensing](../LICENSING.md) — component license boundaries, third-party treatment, and future firmware policy.
- [Contributing](../CONTRIBUTING.md) — contribution workflow, DCO sign-off, testing, and provenance requirements.
- [Credits and provenance](../CREDITS.md) — every upstream work consulted, version/hash where available, license treatment, and the independent-implementation boundary.

Claims in the protocol documents carry explicit evidence labels. In particular, a community implementation is not silently promoted to a fact observed on this installation.

## Research CLI

The Python package has no runtime dependencies and supports Python 3.9 or later.
Run the commands below from the repository root.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade "pip>=21.3"
python -m pip install -e .
```

Editable installs use the PEP 660 interface and therefore require pip 21.3 or
later.  If an editable checkout is unnecessary, `python -m pip install .`
also works with older pip releases.

Read the bridge inventory without changing it. Names, room RF identifiers, title bytes, and MAC are redacted by default:

```sh
hd-platinum inventory 192.0.2.10
```

`192.0.2.10` is a documentation-only address; replace it with the bridge's private-LAN address.

Decode a five-byte payload that has already been captured:

```sh
hd-platinum rf-decode 03c12001a1
```

Build an offline payload using a fictional identity:

```sh
hd-platinum rf-payload --remote-id aabb --groups 1 --action up
```

The optional `--candidate-frame` output constructs a 97-bit Enhanced ShockBurst comparison hypothesis. Initial local IQ instead supports an 88-bit frame without PCF for the captured remote; this alternative builder is not an SDR waveform and does not transmit:

```sh
hd-platinum rf-payload --remote-id aabb --groups all --action down --candidate-frame
```

Do not use another installation's two-byte identity. Capture the identity from the remote that is already paired with the shades.

### Decode a saved IQ recording

Install the optional analysis dependencies into the virtual environment:

```sh
python -m pip install -e '.[analysis]'
```

Decode little-endian signed 16-bit interleaved I/Q (SC16Q11), supplying the actual recorded sample rate and center frequency:

```sh
hd-platinum rf-iq-decode captures/remote.sc16q11 \
  --sample-rate 48000000 --center 2452000000 \
  --start 19 --duration 2 > captures/decoded.json
```

The experimental decoder searches `2433`, `2452`, and `2471 MHz` at `2 Mbps`, tests both polarities and both frame layouts, and checks preamble, CRC, and RF power through the frame tail. `--channels` accepts a comma-separated list of frequencies in Hz for a narrower recording. Input rates must be integer multiples of `8 MS/s`, up to `256 MS/s`; `--start` and `--duration` select a bounded interval. It reads files only and never opens the SDR.

Output redacts the installation identity and identity-derived CRC by default. `--include-private` retains them for local research; keep that output under ignored `captures/` or `tmp/`. Ambiguous framing candidates receive additional redaction because misaligned fields can expose identity bits. Accepted-frame counts are not a packet-error-rate measurement, and raw files without timestamp/overrun metadata cannot establish lossless timing.

Initial local decoding recovered Group 1 Up, Down, and both release codes using **88-bit, no-PCF frames** with valid CRCs. See the [local RF findings](rf-protocol.md#initial-local-receive-result--2026-10-23) for the evidence scope and remaining validation gates.

## Bridge emulator

`bridge-emulate` serves the observed Platinum TCP protocol on port `522` and
the authenticated browser/HTTP API on port `8077`, using one serialized command
dispatcher. It loads a private configuration and a saved original-bridge
inventory; the original bridge is not contacted at runtime. Start locally with
the default dry-run backend:

```sh
hd-platinum bridge-emulate \
  --config tmp/bridge/config.private.json \
  --inventory tmp/bridge/inventory.private.json \
  --state-dir tmp/bridge/emulator-state \
  --backend dry-run
```

Open `http://127.0.0.1:8077/`. The [configuration guide](bridge-prototype.md)
describes private target mappings and the HTTP API. The live bridge backend
requires an empty `groups` map and individually enabled, validated shade
mappings. Its inventory must agree with the configured room identities and
shade masks.

For a live installation, install `.[analysis]` and libbladeRF, set the next
unused sequence from that installation's private records, and keep the same
state directory across restarts:

```sh
hd-platinum bridge-emulate \
  --config tmp/bridge/config.private.json \
  --inventory tmp/bridge/inventory.private.json \
  --state-dir tmp/bridge/emulator-state \
  --backend bladerf-bridge \
  --initial-sequence "$NEXT_SEQUENCE" \
  --tx-gain 50 --rx-gain 40
```

Omit `--initial-sequence` on subsequent starts. The store reserves and persists
each local ordinal before radio access, serializes commands across processes,
and burns a reserved value on failure. The low byte is the on-air transaction
counter, which wraps at 256; the separate command-count byte stays one. The
version-1 local store retains its 16-bit exhaustion limit and never resets or
retries automatically. Do not delete the state directory to reset it. Optional `--device` and
`--fpga` select the radio and a compatible FPGA image.

The fixed working profile sends ten packets over **112.134 ms** at `2440 MHz`,
`250 kbps`, and `8 MS/s`, with `1.5 MHz` bandwidth and concurrent three-second
RX. It preserves the flat carrier lead and packet timing used in the two
operator-observed responses on one shade. The backend checks active TX settings
and RX health before submission and retains bounded private recordings and
receipts. Gain is a device setting, not calibrated radiated power. The successful
bench setup used a direct TX1 antenna and a separate RX1 antenna through a
nominal 30 dB pad and DC block, with TX2 terminated.

To accept trusted LAN clients, append explicit source CIDRs. Discovery is
optional and advertises the emulator's own IPv4 address:

```sh
  --host 0.0.0.0 --allowed-client "$TRUSTED_CLIENT_CIDR" \
  --discovery --advertise-host "$EMULATOR_LAN_IP"
```

These are options to append to either command above. HTTP remains on loopback
unless `--http-host` is also supplied; wildcard HTTP binding additionally needs
`--allowed-host`. TCP 522 has no authentication, so LAN binding requires an
explicit local-client CIDR allowlist. Optional discovery uses UDP `137`, which
may already belong to macOS `netbiosd` or another service. Bind failure stops
startup; `--discovery-reuse-port` requests OS port sharing but does not guarantee
the app receives the emulator's answer. Use discovery only on the intended LAN.

The emulator implements inventory, keepalive, primary-position control,
release, the observed app startup exchange, and explicitly enabled shade Sync
and Jog. Jog requires `jog_enabled: true` for the exact configured target; it
defaults off, and database creation or a Sync-only grant does not enable it.
The original-app Jog request stages one shade and requires `$rls`; it cannot
be mixed with staged position requests. Jog never updates requested positions.
Room/shade creation, editing, and deletion use persistent private inventory;
the room's product code selects the app's controls. The catalog contains the
25 product codes found by static analysis of the supplied Android app.
Additional rail/vane features, scenes, schedules, and reset remain unsupported.
Returned positions are **requested state, not measured shade position**.
Original-app discovery, inventory loading, one-target position control, and
existing-target Sync have been exercised. The app created a persistent room and
a new shade, reaching its Sync/Jog screen. Entering the newly created room
required an app restart; that refresh issue remains unresolved. New-identity
enrollment and Control4 interoperability remain unverified.

Jog's packet encoding and software dispatch have passed offline and fake-radio
checks. A controlled original-bridge Jog produced the expected narrow and
native RF forms, but movement on the newly created binding was not observed.
The emulator Jog path has not yet been physically validated. The app's observed
15-second Sync countdown is separate from the backend's 18-second diagnostic
receive window; neither establishes successful enrollment.

A live TCP request through this runtime closed the observed shade with the
original bridge off. The original app then loaded the saved database and moved
the same shade to roughly halfway with a native position request of `126`, again
with the original bridge off. An app Sync request also made one existing target
jog when its manual button was pressed, with the original bridge off. That
demonstrates resynchronization; it does not yet demonstrate enrollment with a
new RF identity or support for every product's controls. Control4 uses the same
plaintext TCP port `522`; driver-specific testing is deferred.

For client compatibility work, `--protocol-log tmp/bridge/tcp.private.jsonl`
records raw TCP bytes before parsing, including unsupported requests. This
opt-in journal contains private inventory and client data. It uses mode `0600`
and retains a maximum of two `1 MiB` files by default; keep it out of Git.
Logging errors do not turn completed commands into automatic retries.

## Earlier HTTP and 2 Mbps prototype

The prototype exposes configured handheld groups and individual primary-position
targets through a browser page and authenticated HTTP API at
`127.0.0.1:8077`. Start with the dry-run backend and a private configuration:

```sh
hd-platinum bridge-serve --config tmp/bridge/config.private.json --backend dry-run
```

The [setup guide](bridge-prototype.md) covers private configuration, explicit
position controls, authenticated requests, offline waveform generation, and the
bladeRF backends. Captures establish room identity, one-hot shade selection, and
position values `0`, `128`, and `255`. Limited conducted packet checks have
passed on all three frequencies. **This public 2 Mbps backend has not yet
produced verified shade operation.** The 250 kbps implementation used by
`bridge-emulate` is based on two observed responses on one shade with the original bridge off;
see the [latest lab results](lab-log.md#laptop-reference-captures-and-narrow-candidate--2026-10-24).
Position targets default to disabled until their mappings are validated; all
receipts leave actual delivery and position unconfirmed. The RF backend does
not call or depend on the original bridge at runtime.

## Original firmware research

The Android APK's embedded gateway and bridge firmware can be inspected and
extracted with `firmware-inspect`. An offline `firmware-probe` executes the
original gateway keepalive handler using a separately built 8051 simulator.
It verifies an original-code response with an explicit connection fixture;
complete board startup, Ethernet and RF peripherals remain unfinished.
See [Original firmware execution](firmware-emulation.md) for CPU details,
commands and the exact boundary of the working probe.

`firmware-bridge-probe` and `firmware-native-probe` compare RF payloads against
the original firmware's executed builders. The
[protocol conformance report](protocol-conformance.md) records the corrected
command-count/transaction fields, independent capture checks, and the remaining
direct-to-shade timing limitations.

## Testing environment

Development uses sanitized fixtures, mock hardware, and temporary loopback
servers. The complete RF validation program includes a USB 3 SDR host, an
independent 2.4 GHz reference receiver, and a protected 50-ohm SMA bench.
Transmission remains experimental; broader interoperability, repeatability,
and the remaining validation checks are incomplete.

The canonical test method and evidence status are in [Testing and validation](testing.md), and required equipment and quantities are in the [Bill of materials](bom.md). The [reference bench lab log](lab-log.md) records sanitized capability checks and progress without defining requirements for other contributors.

## Privacy and safety

- `$dat` exposes household labels and the bridge MAC. Published examples in this repository are sanitized.
- Raw IQ, packet captures, and downloaded research exhibits belong under ignored `captures/` or `tmp/` paths.
- TCP port 522 is cleartext and appears unauthenticated. Keep it on a trusted LAN and do not expose it to the internet.
- Treat the original bridge as irreplaceable. Avoid bootloader, pairing, database-edit, and firmware commands during discovery.
- Transmit only to equipment you own or are authorized to test, at lawful power and frequency settings.

## Project licensing

Project-authored host software, tests, and configuration are licensed under the [GNU Affero General Public License v3.0 or later](../LICENSE). Project-authored documentation is dual licensed under [CC BY-SA 4.0](../LICENSES/CC-BY-SA-4.0.txt) or AGPL-3.0-or-later, at your option. These copyleft terms are intended to keep shared improvements open, including modified software offered as a network service.

See [LICENSING.md](../LICENSING.md) for the exact component boundaries and [CONTRIBUTING.md](../CONTRIBUTING.md) for the inbound-equals-outbound and DCO 1.1 contribution policy. Citations do not relicense third-party works, and unlicensed forum attachments remain reference evidence only; review [CREDITS.md](../CREDITS.md) before incorporating any upstream material.

Hunter Douglas and its product names are trademarks of their respective owner. This project is independent and unofficial.
