<!--
SPDX-FileCopyrightText: 2026 Christopher Spitler
SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later
-->

# Carrier firmware contract

This is the interface and qualification contract for a future ESP32-S3 firmware
port. **This hardware package does not deliver ESP32 firmware, a programming
image, or a proven RF2401F20 implementation of the Platinum protocol.** The
existing Python bridge and bladeRF backend remain the behavioral reference.

## Pin ownership

Physical connector numbering and host GPIO numbering are different. See the
complete [pin assignment](pin-assignment.csv) and
[electrical evidence](electrical-evidence.md).

| Peripheral | Function | ESP32-S3 GPIO | Physical M-Bus pin |
| --- | --- | ---: | ---: |
| Dedicated radio SPI | SCK | 6 | 21 |
| Dedicated radio SPI | MOSI | 5 | 8 |
| Dedicated radio SPI | MISO | 8 | 4 |
| RF2401F20 | CSN, active low | 18 | 15 |
| RF2401F20 | CE, active high | 17 | 16 |
| RF2401F20 | IRQ, active low | 10 | 2 |
| W5500 / existing display bus | MOSI | 37 | 7 |
| W5500 / LCD D/C | MISO / D/C | 35 | 9 |
| W5500 / existing display bus | SCK | 36 | 11 |
| W5500 | CS, active low | 9 | 10 |
| W5500 | Reset | 7 | 22 |
| W5500 | IRQ | 14 | 26 |

The radio driver must use its own general-purpose SPI controller/instance,
explicitly initialized with the radio pins. Do not fall back to a library's
global/default SPI object after passing a different bus at initialization.
The ESP32-S3 flash/PSRAM interfaces are not spare peripheral buses.

Reserve M5Stack Port B/C pins for this design. Keep optional LAN-base RS232/RS485
adapters disconnected. During initial qualification, disable SD, speaker and
microphone drivers, leave the SD socket empty, and avoid automatic initialization
of accessories that claim these signals. GPIO14 belongs to W5500 IRQ here.

## Display and Ethernet

The CoreS3 SE connects **GPIO35 to both LCD D/C and the bus MISO signal**. An
Ethernet read needs it as an input while a display transaction normally drives
the D/C signal. Merely placing the radio on a separate bus does not resolve this
existing LCD/Ethernet interaction.

Start with a headless network/radio build that keeps LCD CS inactive and GPIO35
configured for W5500 reads. When adding screen updates, serialize LCD and W5500
transactions, deselect the other device and transfer GPIO35 direction/ownership
at the transaction boundary. Confirm with a logic analyzer that W5500 never
drives MISO while the ESP32 drives it as D/C. If a library cannot support that
sequence, adapt the driver or keep the display inactive in the released build.

M5Stack's [CoreS3/Base LAN example](https://docs.m5stack.com/en/arduino/projects/base/base_lan_v1.2)
is an integration reference. Freeze tested M5Unified and Ethernet-library
versions; the existence of the example is not a completed concurrency test of
this appliance.

## Power, startup and shutdown

Revision A uses M-Bus pin 28 `BUS_5V` through FB1 to U2, a TLV75533PDBVR.
M-Bus pin 12 `HOST_3V3` drives U2 EN and a 100 kΩ pull-down. The two 3.3 V
rails are electrically separate. There is no spare firmware GPIO controlling
U2's enable in this revision.

The selected appliance power path is the SC0218 supply into CoreS3 SE USB-C;
leave the Base LAN DC input unconnected. Configure the Core's power management
for that path and enable M-Bus 5 V using the supported M5Stack API. A base-powered
variant would need its own validated power configuration; never drive one 5 V
source into another because an example enables bus output unconditionally.

Startup order:

1. Keep radio control pins low or high impedance. In particular, leave CSN high
   impedance until the radio rail is present; R7 pulls it to **RF_3V3**, not the
   host supply. Avoid powering an unpowered radio through a GPIO.
2. Configure the host power path and enable BUS_5V. Allow U2 and the RF rail to
   settle; the first article must measure this interval. TP2 is BUS5V, TP3 is
   RF3V3 and TP7 is HOST3V3.
3. Drive CE low, CSN high and SCK low. Initialize the dedicated radio bus in
   SPI mode 0 at 1 MHz and verify register access before increasing speed.
4. Program and read back the complete intended radio configuration. Observe
   Nordic's power-up and TX/RX settling requirements; do not equate a successful
   SPI register read with a radio already ready to transmit.
5. Initialize the network and command dispatcher with transmission disabled
   until the installation configuration and persistent sequence state validate.

On normal shutdown or a bus-power change, stop accepting new radio work, wait
for the finite operation or abort it with a recorded failure, drive CE low and
put the driver into power-down. Return radio GPIOs to low/high impedance before
removing BUS_5V. R6/R8 hold CE/SCK low; R7 holds CSN high relative to the radio's
own rail. Test reset and interrupted-power behavior on the actual assembly.

## Radio settings and unresolved interoperability

The RF2401F20 V3.1 data sheet's page-5 note limits the power-level setting to
**2 or below**. Start at **RF_PWR=0**; do not expose level 3 as an ordinary
user option. The module contains a PA: the bare nRF24 chip's nominal dBm label
is not the module's conducted output power. Use the exact module and settings
qualified with the final antenna. The source and current limits are recorded
in [electrical evidence](electrical-evidence.md).

The working host implementation in
[rf_bridge.py](../../src/hd_platinum/rf_bridge.py) encodes these specific facts:

| Parameter | Existing reference behavior |
| --- | --- |
| Center frequency | 2440 MHz; nRF channel number 40 if using the documented 2400 MHz + RF_CH mapping |
| Air rate | 250 kbps |
| Modulation synthesis | GFSK, ±160 kHz deviation, BT=0.5 |
| Address | Three bytes `e7 e7 e7` |
| Frame | 8-bit preamble, 24-bit address, 9-bit PCF, payload, CRC16 |
| Payload lengths | Alternating 12-byte command and 9-byte count/transaction/countdown frames |
| PCF | Six-bit payload length, two-bit PID, one-bit NO_ACK; reference PID is frame index modulo 4 and NO_ACK is 0 |
| CRC | 16-bit polynomial 0x1021, initial 0xffff over address + PCF + payload, MSB first |
| Burst | Ten frames; reference waveform duration 112.134 ms |
| Host framing lead | 54 µs unmodulated carrier before each preamble, with explicit SDR ramps/tails |

These are a captured/exercised reference profile, not a claim that every shade
accepts every generated command. Payload identities and initial sequence values
are installation-specific and must not be baked into a publicly distributed
firmware image.

**Retain Enhanced ShockBurst's 9-bit PCF.** Do not blindly use the common
`EN_AA=0`, `ARC=0` recipe: Nordic's nRF24L01+ product specification §§7.9–7.9.1
describes those settings at 1 Mbps/250 kbps as legacy ShockBurst compatibility,
whose packet omits that field. Disabling retries is required for bounded
transmission, but disabling every ESB feature may change framing. Establish an
explicit register recipe by capturing the resulting waveform. The project has
not validated that recipe on this module.

The nRF24 packet engine constructs the preamble, PCF and CRC. Sending an SDR's
complete encoded frame as the TX FIFO payload would add another packet wrapper.
Likewise, driver padding, fixed RX widths, dynamic payload configuration,
automatic ACKs, auto-retries, FIFO reuse and PID advancement all need explicit
checks for the alternating lengths and sequence. Handle TX_DS/MAX_RT and FIFO
contents deliberately; do not turn an unacknowledged finite submission into an
automatic application retry.

The packet radio is **half-duplex**. It cannot reproduce the bladeRF backend's
simultaneous receive stream during its own transmission, nor does a packet API
automatically reproduce the SDR's arbitrary 54 µs carrier lead. Determine
whether the native packet waveform and TX/RX transitions satisfy the real
installation; the current SDR successes do not prove that they will.

For a timing comparison, use `BURST_START_SAMPLES` and `LEAD_SAMPLES` from the
reference code, rather than a rounded 10 ms timer. At 8 MS/s the reference
preamble timestamps are `10.054, 21.5965, 31.629, 41.59975, 51.62125, 61.603,
71.634, 81.6035, 91.635, 101.605` ms. Measure actual preamble times in RF captures;
SPI-write completion or a CE edge is a different event. No allowable timing
tolerance has yet been established for recipients' installations.

Nordic reference: [nRF24L01+ Product Specification v1.0](https://docs.nordicsemi.com/bundle/nRF24L01P_PS_v1.0/resource/nRF24L01P_PS_v1.0.pdf).
The project [RF findings](../../docs/rf-protocol.md#2440-mhz-bridge-and-repeater-observations--2026-10-24)
separate captured fields from incomplete application semantics.

## Application port requirements

The Python code uses libbladeRF, sample buffers, filesystem transactions and
host networking. It cannot be flashed onto an ESP32-S3 as-is. A firmware port
needs a packet-radio backend, bounded command queue, persistent state, W5500
networking, configuration storage and the intended TCP/HTTP protocol handlers.

Preserve these application behaviors from
[bladerf_bridge.py](../../src/hd_platinum/bladerf_bridge.py) and the
[emulator documentation](../../README.md#bridge-emulator):

- Reserve and durably commit each local ordinal before RF transmission;
  keep it consumed after an interruption or failure. Original firmware uses
  separate one-byte command count and wrapping transaction counter fields.
  For this single-command backend, emit count 1 and the low byte of the ordinal;
  never serialize the entire ordinal as a two-byte field. The current host's
  version-1 store retains its 16-bit exhaustion limit; do not silently reset it
  during routine firmware updates.
- Serialize commands from TCP and HTTP through one radio owner. Keep long
  operations out of interrupt handlers and prevent screen/network activity
  from corrupting radio timing.
- Report submission and requested state separately from independently observed
  shade position. A radio TX-complete flag is not proof of movement.
- Implement the observed Platinum TCP protocol on port 522; do not add Telnet
  IAC negotiation merely because telnet can connect to that port. The current
  HTTP reference uses port 8077 and authenticated control requests.
- Preserve explicitly enabled target mapping, bounded operations, failed-state
  handling and private installation data. The current TCP service is
  unauthenticated and its host implementation requires a client allowlist.
- Treat enrollment/Sync and feature support according to existing evidence;
  do not claim a complete enrollment workflow because a request frame can be
  generated. Users need a supported configuration path before distribution.

Release requires the hardware [acceptance procedure](../manufacturing/acceptance-test.md),
the exact tested firmware/library versions and a documented installation flow.
Firmware must follow the repository's separate
[firmware licensing policy](../../LICENSING.md#firmware).
