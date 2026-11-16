<!--
SPDX-FileCopyrightText: 2026 Christopher Spitler
SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later
-->

# Packet-radio implementation and qualification

The revision-A CoreS3/NiceRF appliance is unassembled. Its RF2401F20 driver has
not been flashed onto that stack, captured over the air, or demonstrated with a
shade. SDR results establish separate protocol evidence; they do not qualify
this packet radio. The implementation has two explicit routes, with no automatic
fallback between them.

## Hardware ownership

`ArduinoIo` owns `SPIClass(HSPI)`, mode 0, on SCK6/MOSI5/MISO8 with CSN18,
CE17 and IRQ10. Startup and repeater transactions use 1 MHz. A finite native
train owns one 8 MHz SPI transaction and transfers each command plus data in one
hardware call. Registers and addresses are checked again at that faster clock
before CE. This avoids repeated transaction/per-byte overhead, but does not
establish signal integrity or actual timing on the carrier.

The network/display bus is separate. The application establishes USB power and
the carrier supply before `Radio::begin`; `Radio::shutdown` powers down the radio
and releases its GPIOs before supply removal. Revision A has no software
regulator-enable pin. The IRQ pin is not an ISR source; the owner polls STATUS
with a deadline. Module power defaults to 0 and setting 3 is rejected. Settings
are not bare-chip or measured module dBm claims.

## Repeater route: 2440 MHz / 250 kbps

This existing route uses three-byte address `e7 e7 e7`, CRC16, dynamic payloads,
pipe 0, RX width 0, FEATURE=4, DYNPD=1 and SETUP_RETR=0. Both address registers
and the profile are verified. Startup sets CONFIG=0x0e and waits 5 ms with CE low.

| Recipe | EN_AA | Purpose |
| --- | ---: | --- |
| `EsbNoRetry` | 1 | Request ACKs to retain ESB, with zero retries; count missing ACKs and flush MAX_RT payloads. |
| `OriginalRegisterExperiment` | 0 | Separate original-register experiment; may change the packet framing. |

Neither recipe has been RF-qualified on this module. The required repeater
reference has a nine-bit PCF; the radio generates its PCF/PID/CRC rather than
accepting a complete SDR frame as FIFO data.

Position, Sync and Jog require the global repeater enable/qualification flags
and the explicit shade grant. A transaction sends ten alternating 12-byte
command and nine-byte sequence payloads. Its ordinal is durably reserved before
submission, remains consumed after failure, and stops at exhaustion. Inventory
imports do not replace the independent sequence store.

The existing loop retains its 112.134 ms duration, nominal 130 µs CE-to-preamble
adjustment, 500 µs lateness guard and 3 ms completion deadline. These are software
parameters, not measured recipient tolerances. It cannot directly reproduce the
SDR's 54 µs carrier lead. There are no automatic retries.

## Native route: candidate 2 Mbps per-packet rotation

The native profile requests static five-byte payloads, three-byte address
`e7 e7 e7`, CRC16, EN_AA=0, ARC=0, DYNPD=0 and FEATURE=0 at 2 Mbps. Channels
rotate 33 → 52 → 71 before every packet, including phase boundaries.

| Operation | Command body after two-byte identity | Followup body after identity |
| --- | --- | --- |
| Primary feature 4 | `50 mask value` | `32 mask value` |
| Secondary feature 18 (hex `12`) | `6D mask value` | `32 mask value` |
| Jog feature 12 | Alternates `6A mask 01` and `20 mask 6A` | `32 mask 01` |

Jog follows the checked decrement-before-CE refresh behavior: initial alternate
blocks contain 19 or 99 packets, then 20/100. Primary and secondary position
retain their values and do not use Jog alternation. The constant-memory planner
requires explicit prior channel/alternate, both phase counts and a 401-half-µs
slot; it rejects plans longer than two seconds. It models idle entry in phase 2,
without the original active-timer prelude.

The current application profile is prior channel 71, prior alternate 0,
7,500 command plus 1,500 followup packets: 9,000 packets over a nominal 1.8045 s.
These explicit diagnostic assumptions match the selected SDR trials; they are
not measured universal counts or a complete original scheduler emulation.
Native Sync is rejected. Enrollment needs a distinct longer held/tail lifecycle,
cancellation and subsequent fresh-binding tests; it cannot inherit this short
control train. Features 7, 19 and 10 have no physical implementation.

### Framing is an open hardware question

The external `HD_Remote_Clone` project independently reports shade acceptance
with a commodity nRF24-style radio at the handheld settings. See the
[pinned source and evidence scope](../../../docs/rf-wake-experiments.md).
That is useful corroboration, not a measurement of this module's packet engine.

[Nordic's nRF24L01+ Product Specification v1.0](https://www.sparkfun.com/datasheets/Wireless/Nordic/nRF24L01P_Product_Specification_1_0.pdf)
§7.9 documents no-PCF legacy interoperability with EN_AA=0 and ARC=0 at 1 Mbps
or 250 kbps. It does not guarantee the required 2 Mbps, 88-bit frame on this
module. This does not prove that the candidate is impossible either. Community
remote-register evidence and original/SDR RF captures do not identify the
NiceRF packet engine's behavior. Capture the actual output and distinguish
88-bit no-PCF from 97-bit ESB before marking any operation qualified. Disabling
CRC or packing a frame into the payload is not an established workaround for
inserted PCF/PID bits.

The same specification permits SPI up to 10 MHz (§8), a 130 µs standby-to-TX
interval and a minimum 10 µs CE pulse (table 16). The driver selects 8 MHz and
10 µs CE pulses. Each target is individually rounded from the absolute 200.5 µs
grid to whole microseconds, with at most 0.5 µs rounding and no accumulated
rounding drift. Targets are CE edges, not measured RF preambles.

A delay greater than 5 µs aborts before another CE; completion must be observed
within 190 µs of the pulse's software timestamp. No queued multi-packet burst
or FIFO reuse is used. Retuning follows completion and FIFO-empty checks.
The SPI/CPU margin is small, and preemption between checking a deadline and
asserting GPIO remains possible. Fake timing tests are not a hardware deadline
guarantee. Real CE/channel/status/RF timing must be checked under network load.

### Optional wake preparation

Primary-position bench trains can prepend the externally identified
`room-ID 01 00 80` RF wake or equal-length copies of the primary command as an
airtime control. This is separate from the original active-timer prelude and
does not implement IR. Both use whole three-channel cycles and continuous
200.5 µs slots. The unchanged command and followup follow without a new gap.

In the private `include/gateway_config.h`, set
`GATEWAY_RF_NATIVE_PREPARATION` to 0 (none, default), 1 (wake) or 2 (command
control), and `GATEWAY_RF_NATIVE_PREPARATION_FRAMES` to a multiple of three.
For example, mode 1 and 300 frames adds 60.15 ms. The fixed 9,000-packet
application train leaves room for at most 975 extra packets (1.9999875 s total).
Zero mode requires zero extra frames; active modes require positive counts.
Compile-time checks require enabled native bench RF and unqualified feature 4.
Build both native-test images; ordinary images cannot silently acquire the
experiment. Apply these settings only in a bench configuration.

The lower-level driver likewise rejects preparation outside primary position
or `NativeAccess::Bench`, including qualified access. Existing admission expiry
and cancellation apply from the first prefix packet. Prefixes count toward
the planner's combined two-second limit; secondary, Jog, Sync and the repeater
route do not acquire preparation. USB result lines and HTTP status report the
configured preparation mode and frame count; submitted frame totals include
the prefix. No automatic retries or new grants are introduced.

The [wake experiment procedure](../../../docs/rf-wake-experiments.md) requires
original-bridge captures, independent framing/timing checks, controlled idle
intervals and watched motion before interpreting a result. Hardware and
RF-only wake acceptance remain unqualified.

## Bench admission, cancellation and results

Ordinary images default to simulation. `cores3_native_test` and
`cores3_ethernet_native_test` explicitly select the candidate and force native
qualification bits to zero. They boot with no admitted RF features even if a
saved inventory contains grants. USB `rf-test FEATURE_BITMASK` opens an admission
window of at most 60 seconds for supported bits 4, 12 and 18; persisted shade
grants are independently required. `rf-test 0` disarms. Rearming while busy is
rejected, and expiry/disarm is checked during a train.

The driver separately represents `Disabled`, `Bench` and `Qualified` access
for each operation. Bench completion returns `bench_submitted_unqualified`;
qualification cannot be inferred from submission. Production qualification is
an explicit per-feature configuration, initially empty. Native transmission has
no repeater ordinal argument or sequence-store requirement.

Cancellation is latched when observed. No further packet is admitted after
that observation, although a packet already started may finish. Cancellation,
invalid status, timeout or missed deadline
clears the FIFO, powers down the source and requires reinitialization. A failed
operation is not retried. Success means submission only: neither TX_DS nor a
LAN completion record establishes motion, position or enrollment. There is no
handheld receiver/feedback implementation. The half-duplex module cannot capture
its own transmission simultaneously. The USB diagnostic line records shade,
feature, result, submitted frame count and maximum observed lateness in
microseconds. Keep it with the independent receiver trace; it is not an RF
measurement.

## Required physical evidence

Complete the [hardware acceptance procedure](../../../hardware/manufacturing/acceptance-test.md)
on the assembled module, carrier and final antenna. Start with protected,
independent reception of a bounded fictional-identity packet. Check profile
readback at both SPI speeds, emitted rate/address/framing/CRC, pulse timing,
absence of retries, output setting and rail transients. Then qualify a finite
three-channel train, cancellation, repeated jobs, faults and interrupted power.
A successful register read or build is insufficient.

Use the wired image initially to separate the CoreS3's co-located Wi-Fi source
from the radio experiment. Preserve original packet/receiver records and log
all missed deadlines. Only after those checks should watched shade operations
establish per-feature acceptance, including target isolation and physical rail
mapping. Follow the broader [RF validation plan](../../../docs/rf-validation-plan.md)
for enrollment and remaining product families.
