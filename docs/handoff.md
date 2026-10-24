<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Laptop handoff — 2026-10-23

The objective is a replacement Platinum bridge with individual-shade and
position control. **That objective is not complete: no SDR transmission has
produced observed shade movement.** RF testing and signal analysis were paused
at the operator's request. The hardware HTTP service was stopped after the last
finite transmission completed. Documentation, file transfer, and software
verification do not resume physical testing.

The bladeRF is currently attached to a stationary desktop. The next bench
session will use a laptop with the radio moved into the test room. Move the
radio and its accessories; the desktop can remain where it is.

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
  It does not contact the original bridge at runtime. Original TCP port 522
  bridge emulation and Control4 integration remain unimplemented.
- The bladeRF backend provides bounded TX and RX with timestamp/overrun
  metadata. Conducted handheld checks recovered `993/1000`, `1000/1000`, and
  `1000/1000` expected packets on the three channels. This is not proof of
  motor control.
- Final desktop verification: **129/129 software tests pass** with NumPy/SciPy;
  the base environment passes 108 with 21 optional DSP tests skipped. Tests use
  synthetic fixtures, fake hardware, and local loopback servers.

## Preserve these findings

The current position backend uses a **fresh device handle for each channel**.
Reusing a handle after clock reconfiguration caused the second channel to fail
with `Requested timestamp is in the past` because the library retained a TX
timestamp cursor. Do not restore the earlier same-handle implementation.

Sequential 8 MS/s position artifacts now use **702 µs same-channel spacing**
(`3 × 234 µs`), with 2,100 first-phase and 425 followup frames per channel.
Each lasts 1.77255 seconds; the three sequential files total 5.31765 seconds
including silence, plus device setup gaps. The offline simultaneous-channel
generator still uses 234 µs hop slots. Historical compressed single-channel
files are not the current profile. Neither sequential submission nor correct
offline decoding proves the shades accept this timing.

Attempts at transmit gains 35, 50, and 60 dB produced **no observed movement**.
The final 50/60 dB tests completed all three frequencies with corrected cadence.
Distance is a possible cause, not an established diagnosis. Gain is a device
setting, not a measurement of radiated power; another increase is not the next
step supported by the evidence.

An unfinished analysis found narrow bursts near 2440 MHz before the wide
position train in two continuous reference captures: approximately 125 kHz
wide and repeating around every 5 ms. This signal is absent from the generated
model. Its modulation, payload, emitting component, and role are unknown. It
could be relevant bridge/repeater signaling; do not label it a proven wake-up
or invent bytes. Analysis of the original carrier lead-in is also unfinished.
The private transfer guide locates both saved investigations.

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

After restoring the private configuration, start only a **dry-run** service
while testing software setup. Substitute the restored config path for this
example:

```sh
hd-platinum bridge-serve --config tmp/bridge/config.private.json --backend dry-run
```

Open `http://127.0.0.1:8077/`. A simulated receipt confirms software flow only.
Enabled position mappings in the saved configuration are capture-supported;
they do not represent successful SDR control. There is no installed autostart
service to migrate.

## Next physical session, after the operator resumes

1. Read the private allowlist and confirm the actual antenna/termination state
   after moving the radio. The last reported state was antenna on TX1, 50-ohm
   loads on RX1 and TX2, RX2 unused, and bias tees off. For receive work, with
   streams stopped, move the antenna to RX1 and terminate both TX ports. For
   conducted loopback, retain the 30 dB + 10 dB attenuators and DC block; never
   connect TX directly to RX.
2. Use the laptop near the selected target and the original bridge for a
   controlled reference comparison. Verify USB SuperSpeed and fresh stream
   continuity on that laptop. The desktop passed only a five-second 48 MS/s
   counter check; 61.44 MS/s failed. Those results do not qualify a new host.
   Simultaneous 48 MS/s TX plus 48 MS/s RX also failed, and RX/TX sample-rate
   setters are coupled. Do not use that combination as timing evidence.
3. Continue the saved narrow-signal and carrier-lead investigations using the
   existing recordings. For new reference captures, use the private known
   bridge address rather than relying on same-subnet discovery. Its reference
   capture script issues a real shade command and must stay within the
   operator's target scope; it is not a read-only setup probe.
4. Compare reference signaling with generated signaling before another bounded,
   observed test. Maintain the configured room scope; the separately recorded
   one-target exception does not authorize its whole room. Preserve before/
   after journals, timing metadata, settings, and the operator's actual
   observation, including negative results.

Reliable observed control, the remaining protocol work, and eventual legacy
bridge/API compatibility are still required before calling this a replacement
device.
