<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# hd-platinum-rf

Open-source tools and protocol documentation ensuring continued communication between discontinued Hunter Douglas Platinum bridges, blinds, and shades.

The project treats the LAN protocol and the two distinct RF paths as separate research surfaces:

| Interface | Project scope |
| --- | --- |
| Ethernet client ↔ Platinum App Bridge | Document the legacy LAN protocol and provide a conservative research client. |
| Legacy four-group handheld remote ↔ shades | Recover and validate the handheld remote's RF waveform. |
| Platinum App Bridge ↔ RF network | Characterize the bridge/repeater signaling independently from the handheld waveform. |
| Control4 | Integrate only after the underlying protocol work is validated; this is Phase 2. |

## Documentation

- [Laptop handoff](docs/handoff.md) — paused session status, current implementation, unresolved RF findings, and setup for continuing on another computer.
- [LAN protocol](docs/lan-protocol.md) — byte-level framing, records, commands, feature codes, compatibility differences, and sanitized live evidence.
- [RF protocol](docs/rf-protocol.md) — device-generation boundary, handheld payloads, PHY/framing hypotheses, bridge bandwidth evidence, and the capture/validation procedure.
- [Local bridge prototype](docs/bridge-prototype.md) — private configuration, browser controls, authenticated HTTP commands, waveform generation, and the experimental bladeRF backend.
- [Testing and validation](docs/testing.md) — reference environment, safe RF interconnects, automated tests, evidence gates, and objective project status.
- [Bill of materials](docs/bom.md) — required quantities, reference parts, connector requirements, and optional bench expansions.
- [Reference bench lab log](docs/lab-log.md) — sanitized capability qualifications and test history; useful project evidence, but not canonical requirements for other installations.
- [Licensing](LICENSING.md) — component license boundaries, third-party treatment, and future firmware policy.
- [Contributing](CONTRIBUTING.md) — contribution workflow, DCO sign-off, testing, and provenance requirements.
- [Credits and provenance](CREDITS.md) — every upstream work consulted, version/hash where available, license treatment, and the independent-implementation boundary.

Claims in the protocol documents carry explicit evidence labels. In particular, a community implementation is not silently promoted to a fact observed on this installation.

## Research CLI

The Python package has no runtime dependencies and supports Python 3.9 or later.

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

Initial local decoding recovered Group 1 Up, Down, and both release codes using **88-bit, no-PCF frames** with valid CRCs. See the [local RF findings](docs/rf-protocol.md#initial-local-receive-result--2026-10-23) for the evidence scope and remaining validation gates.

## Local bridge prototype

The prototype exposes configured handheld groups and individual primary-position
targets through a browser page and authenticated HTTP API at
`127.0.0.1:8077`. Start with the dry-run backend and a private configuration:

```sh
hd-platinum bridge-serve --config tmp/bridge/config.private.json --backend dry-run
```

The [setup guide](docs/bridge-prototype.md) covers private configuration, explicit
position controls, authenticated requests, offline waveform generation, and the
bladeRF backends. Captures establish room identity, one-hot shade selection, and
position values `0`, `128`, and `255`. Limited conducted packet checks have
passed on all three frequencies. **SDR-to-shade operation remains unverified.**
Position targets default to disabled until their mappings are validated; all
receipts leave actual delivery and position unconfirmed. The RF backend does
not call or depend on the original bridge at runtime.

## Testing environment

Development uses sanitized fixtures, mock hardware, and temporary loopback
servers. The complete RF validation program includes a USB 3 SDR host, an
independent 2.4 GHz reference receiver, and a protected 50-ohm SMA bench.
Transmission remains experimental pending observed over-the-air operation and
the remaining validation checks.

The canonical test method and evidence status are in [Testing and validation](docs/testing.md), and required equipment and quantities are in the [Bill of materials](docs/bom.md). The [reference bench lab log](docs/lab-log.md) records sanitized capability checks and progress without defining requirements for other contributors.

## Privacy and safety

- `$dat` exposes household labels and the bridge MAC. Published examples in this repository are sanitized.
- Raw IQ, packet captures, and downloaded research exhibits belong under ignored `captures/` or `tmp/` paths.
- TCP port 522 is cleartext and appears unauthenticated. Keep it on a trusted LAN and do not expose it to the internet.
- Treat the original bridge as irreplaceable. Avoid bootloader, pairing, database-edit, and firmware commands during discovery.
- Transmit only to equipment you own or are authorized to test, at lawful power and frequency settings.

## Project licensing

Project-authored software, tests, and configuration are licensed under the [GNU Affero General Public License v3.0 or later](LICENSE). Project-authored documentation is dual licensed under [CC BY-SA 4.0](LICENSES/CC-BY-SA-4.0.txt) or AGPL-3.0-or-later, at your option. These copyleft terms are intended to keep shared improvements open, including modified software offered as a network service.

See [LICENSING.md](LICENSING.md) for the exact component boundaries and [CONTRIBUTING.md](CONTRIBUTING.md) for the inbound-equals-outbound and DCO 1.1 contribution policy. Citations do not relicense third-party works, and unlicensed forum attachments remain reference evidence only; review [CREDITS.md](CREDITS.md) before incorporating any upstream material.

Hunter Douglas and its product names are trademarks of their respective owner. This project is independent and unofficial.
