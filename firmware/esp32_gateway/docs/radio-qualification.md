<!--
SPDX-FileCopyrightText: 2026 Christopher Spitler
SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later
-->

# Packet-radio implementation and qualification

The RF2401F20 driver is an experiment for the revision-A carrier. It has not
been run on the physical stack or demonstrated with a shade. Native tests
exercise its register transactions through a fake SPI interface; they do not
establish emitted framing, RF timing, enrollment, or receiver acceptance.
The independent implementation follows the factual interfaces recorded in the
[carrier contract](../../../hardware/design/firmware-contract.md) and the
[RF findings](../../../docs/rf-protocol.md).

## Hardware ownership

`ArduinoIo` owns an explicit `SPIClass(HSPI)` on SCK6/MOSI5/MISO8 with CSN18,
CE17 and IRQ10. Every transaction uses that instance, SPI mode 0 and 1 MHz.
The network/display bus is separate. The application must establish USB power
and the carrier supply before calling `Radio::begin`; `Radio::shutdown` powers
the transceiver down and releases its GPIOs before the application removes the
supply. There is no GPIO-controlled carrier regulator enable on revision A.

The driver does not use the IRQ pin to trigger ISR work. It polls STATUS with a
finite deadline in its owning worker task. `begin`, `transmit` and `shutdown`
must never run concurrently. RF power defaults to level 0, and level 3 is
rejected because the selected module permits at most level 2. These levels are
not claims about the PA module's conducted output power.

## Explicit register experiments

Common configuration is address width 3, channel 40, 250 kbps, address
`e7 e7 e7`, two-byte CRC, dynamic payloads on pipe 0, RX width 0, FEATURE=4,
DYNPD=1, and SETUP_RETR=0. Both receive and transmit address registers are
written and read back. Startup verifies the programmed registers and empty
FIFOs, sets CONFIG=0x0e, and waits 5 ms while keeping CE low.

| Recipe | EN_AA | Purpose |
| --- | ---: | --- |
| `EsbNoRetry` | 1 | Request ACKs to retain Enhanced ShockBurst framing, with zero retransmissions. Missing ACKs are counted; MAX_RT payloads are deliberately flushed. |
| `OriginalRegisterExperiment` | 0 | Compare the original gateway's observed auto-ACK setting. This is an alternative experiment, not an asserted reproduction of the entire original register profile. |

The second recipe can select legacy ShockBurst framing on Nordic hardware.
Neither recipe has an RF capture proving the required nine-bit PCF and NO_ACK=0.
The radio itself generates preamble, PCF, CRC and PID: the application cannot
explicitly assign each PID. Native PID continuation across jobs may differ from
the reference's per-burst PID sequence. Measure it, including after flushes,
timeouts, resets and repeated payloads. Consult the
[Nordic nRF24L01+ specification](https://docs.nordicsemi.com/bundle/nRF24L01P_PS_v1.0/resource/nRF24L01P_PS_v1.0.pdf)
for the packet-engine and compatibility modes.

## Finite command submission

Position, Sync and Jog have independent application grants. The driver also
requires the global enabled and qualified flags and the command's explicit
operation grant. A failed gate produces no CE pulse. Payload encoding has no
side effects and is usable while radio transmission is disabled.

A transaction sends ten alternating 12-byte command and nine-byte sequence
payloads. The local ordinal is reserved and durably verified before submission;
the sequence payload contains command count 1 and only the ordinal's low byte.
The 16-bit local allocation exhausts after 65535 rather than silently wrapping.
Gateway inventory imports do not contain or replace this sequence store.

CE targets use the reference's fractional preamble timestamps, rounded up to
microseconds with a nominal 130 µs transmit-settling adjustment. The native
radio does not reproduce the SDR's explicitly synthesized 54 µs carrier lead.
A deadline missed by more than 500 µs aborts the experiment; that threshold is
an implementation guard, not a measured recipient tolerance. A successful
submission retains the reference's 112134 µs total duration, including trailing
quiet time. Each packet gets one CE pulse and a 3 ms completion deadline. There
are no application retries. A timeout, invalid status or missed deadline
powers down the radio and requires reinitialization.

`submitted_unconfirmed` means a finite packet submission ended, including an
expected missing ACK under the ESB experiment. It does not mean a repeater or
shade accepted the message. This driver does not yet receive reply packets,
listen for handheld commands, implement native 2 Mbps channel hopping, or
complete enrollment. The half-duplex module cannot reproduce the SDR backend's
simultaneous receive capture during its own transmission.

## Required physical evidence

Complete the [hardware acceptance procedure](../../../hardware/manufacturing/acceptance-test.md)
with the exact firmware, module and antenna. Capture startup rails and GPIOs;
verify channel/rate/address/PCF/CRC, 9/12-byte lengths, PID, packet order,
CE-to-preamble delay, absence of retransmissions, and cadence over consecutive
jobs. Confirm behavior under network activity and interrupted power. Prefer
the wired configuration for first RF qualification: the CoreS3's co-located
Wi-Fi transmitter introduces another 2.4 GHz source and scheduling load.
Do not mark the qualified flag true merely because compilation or native tests
pass.
