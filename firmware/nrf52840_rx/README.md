<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->
# RAM-only native-frame receiver

This independent, project-authored firmware component is GPL-2.0-or-later.
It is a small receive-only experiment for an nRF52840 DK. It has no transmit,
ACK, flash-writing, USB, UART, SDK, heap, or manufacturer-firmware component.
Building it does not access a board. The register configuration is grounded in
Nordic documentation; reception on actual hardware is not yet qualified.

## Build

Use an external, verified Arm GNU `arm-none-eabi` toolchain. Do not add toolchain
binaries or Nordic SDK assets to this component.

```sh
make -C firmware/nrf52840_rx CROSS_COMPILE=/absolute/toolchain/bin/arm-none-eabi-
make -C firmware/nrf52840_rx check-host
make -C firmware/nrf52840_rx inspect CROSS_COMPILE=/absolute/toolchain/bin/arm-none-eabi-
```

The ELF, map, and symbols are under `build/`, which is ignored. All ELF load
addresses are in the 256 KiB RAM region at `0x20000000`; no flash image is
produced. The vector table is at that address, with a 4 KiB stack at RAM's top.
The link fails if code/data would overlap the stack. Portable log tests run on
the host; they do not simulate the RADIO peripheral or validate RF reception.

## Loading boundary and silicon profile

No loader is included here. A separately reviewed loader must **reset and halt
the target before uploading RAM**, preserving flash, and enter `reset_handler`
in privileged Thread mode. Merely halting a running application is insufficient:
inherited EasyDMA could overwrite uploaded RAM before this image begins. A
running watchdog is rejected, because RAM code cannot stop an enabled WDT.
This is not a replacement for arbitrary board or application `SystemInit`.

The entry point masks interrupts, disables all 32 PPI channels and powers RADIO
off before clearing BSS. It installs the RAM vector table, clears inherited
SysTick/NVIC state, PPI groups/forks, and initializes only the peripherals it owns.
It accepts one deliberately narrow silicon profile: PART `0x52840`, VARIANT
`0x41414630` (AAF0), factory words at `0x10000130/134` equal to `8/5`, and 256 KiB
RAM and 1024 KiB flash. Other revisions report `CAPTURE_ERROR_CHIP`, with observed facts retained.
They require a separate errata review; no speculative workaround is applied.

Crystal startup has a 500 ms timer bound and checks HFCLK source/state. CLOCK
calibration-event residue is cleared. RSSI is retained as raw, uncompensated
magnitude; its temperature-dependent error is not corrected. Whitening is off,
avoiding the documented whitening/address-CRC anomaly. Firmware remains inert
with respect to RF until the host supplies the command below.

## Capture ABI

[`capture.h`](capture.h) is the authoritative, versioned little-endian ABI.
`capture_control` is 256 bytes; `capture_records` holds 4096 records of 32 bytes.
Their addresses are exported ELF symbols; `records_address` also publishes the
record-array address. There are no fixed private target identifiers in the image.

After `state == READY`, the host writes `channel` (33, 52, or 71),
`duration_us` (1 through 3,000,000), and `expected_variant` equal to the reported
variant. It writes `command = 0x52585331` **last**. Any nonzero invalid command or
configuration produces ERROR. The image accepts only one run; it cannot be
rearmed after DONE or ERROR. No command starts automatically at boot.

The receiver stays on the one selected channel (2433, 2452, or 2471 MHz).
Every completed address-matched packet is retained, including hardware CRC
failures. The DMA buffer contains exactly five payload bytes. The hardware CRC,
CRC status, address match and RSSI are logged separately. This is an addressed
packet receiver, not an energy detector; silence does not prove absence of RF.

TIMER4 is 32-bit, 1 MHz. PPI channels 0/1 capture RADIO ADDRESS/END into CC0/CC1;
channel 2 captures READY into CC3; channel 3 connects deadline CC2 to RADIO
DISABLE. CC4 is reserved for software time reads. READY->START and END->DISABLE
shortcuts bound each receive attempt. The DISABLED interrupt copies its packet
before issuing another RXEN. Thus there is an observable blind interval between
each END and next READY; timestamps and aggregate gaps expose it. No continuous
or lossless reception claim is made. Gap aggregates include subsequent completed
records, excluding initial ramp-up and the final incomplete attempt.

At the deadline, hardware disables RADIO; a second software cutoff check closes
the RXEN/deadline race. A 10 ms independent shutdown guard powers RADIO off on
failure. END timestamps beyond the requested window are counted but not stored.
An in-progress ADDRESS without END is indicated by `partial_at_stop`. Filling
4096 entries stops reception without overwriting prior records; no wraparound or
automatic retry exists. DONE is published only after RADIO is disabled, DMA has
stopped, and the final complete record is copied. The final state is ERROR if a
guard fails. Read records after DONE/ERROR, using only `record_count` entries.

## Packet configuration and provenance

The receiver uses Nordic proprietary 2 Mbps, an eight-bit preamble, three-byte
`E7E7E7` address, five fixed payload bytes, no PCF, no whitening, and a two-byte
CRC over address plus payload. `PCNF0=0`, `PCNF1=0x01020505`,
`BASE0=0xE7E70000`, `PREFIX0=0xE7`, `CRCCNF=2`, `CRCPOLY=0x11021`, and
`CRCINIT=0xFFFF`. Address bits are always LSB-first; payload bits are MSB-first.
The repeated, bit-palindromic address makes those conventions agree here.

Register facts and state/timing behavior were checked against Nordic's
[nRF52840 RADIO specification](https://docs.nordicsemi.com/r/bundle/ps_nrf52840/page/radio.html),
[TIMER specification](https://docs.nordicsemi.com/r/bundle/ps_nrf52840/page/timer.html),
and [PPI specification](https://docs.nordicsemi.com/r/bundle/ps_nrf52840/page/ppi.html).
Revision identification was cross-checked against Nordic's
[pinned nrfx v3.0.0 errata definitions](https://github.com/NordicSemiconductor/nrfx/blob/v3.0.0/mdk/nrf52_erratas.h).
No source from those implementations is incorporated. The relevant
[revision 3 errata](https://docs.nordicsemi.com/r/bundle/errata_nrf52840_rev3)
must remain part of a later actual-board qualification.
