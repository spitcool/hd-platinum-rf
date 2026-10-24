<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Original firmware execution

The supplied Android APK contains two Intel HEX firmware assets:
`assets/HiMemGateway.hex` and `assets/LoMemBridge.hex`. Their embedded labels
identify gateway 2.18 and bridge 1.18. These are update images, not a complete
copy of a particular bridge's bootloader and persistent configuration.

The project can extract and validate user-supplied images and execute an
isolated command-handler test using a separately installed 8051 simulator.
Complete Ethernet and RF operation using original firmware is not implemented.
The existing `bridge-emulate` command still runs the project-authored Python
implementation.

## CPU and board requirements

| Component | Evidence and modeling requirement |
| --- | --- |
| Instruction set | 8-bit 8051, consistent with Silicon Labs CIP-51. |
| MCU family | Register addresses strongly match C8051F34x. Exact suffix is unconfirmed. |
| Clock | Firmware enables the multiplier and selects nominal 48 MHz. Generic 8051 instruction execution does not establish CIP-51 timing accuracy. |
| Code | 64 KiB address space. Gateway image maps 47,205 bytes; its sparse binary spans 48,208 bytes. |
| Data memory | 256-byte internal RAM and a 4 KiB XRAM layout, plus external devices. Indirect upper RAM must remain distinct from SFRs. |
| External bus | Firmware sets EMI0CN to 0x20. MOVX through R0/R1 must use that page register. Ethernet accesses match CP2200/CP2201 registers. |
| SPI | Separate radio, serial SRAM and nonvolatile-storage chip selects. Correct transactions and stored contents are required. |
| Interrupts | Application vector stubs begin at offset 0x200; factory bootloader routing and timer behavior still need modeling. |

See the primary [C8051F34x datasheet](https://www.silabs.com/documents/public/data-sheets/C8051F34x.pdf)
and [CP2200/CP2201 datasheet](https://www.silabs.com/documents/public/data-sheets/CP2200.pdf).
The hardware identification above is inferred from the firmware, not a confirmed
reading of the original board's chip markings.

## Inspect and extract

```sh
hd-platinum firmware-inspect --apk tmp/platinum.apk
hd-platinum firmware-inspect --apk tmp/platinum.apk --image bridge
hd-platinum firmware-inspect --apk tmp/platinum.apk --output-dir tmp/extracted-gateway
```

Inspection validates Intel HEX record syntax, checksums, EOF, overlaps and the
64 KiB code-address bound. Extraction creates a new mode-0700 directory and
mode-0600 image/manifest files; existing directories are refused. Unmapped binary
bytes are filled with 0xff. The manifest records the mapped-byte count and fill
value; the preserved Intel HEX file retains the exact address mapping.
Neither inspection nor extraction executes code or accesses hardware.

## Execute the original keepalive handler

The observed gateway image has binary SHA-256
`f93843ff65dfb5fe91e9b3e5adf3a191bd09483d5b4ac03389ffb7c53fe5cf01`.
The handler probe accepts only this image because its entry points and memory
layout were established for that exact version.

Build [uCsim](https://github.com/danieldrotos/ucsim) separately. The reference
run used release 0.9.11, commit
`6f7cf7a4a67f5787a3a59847cfbd9f366a222e4b`, with the MCS-51 simulator enabled.
The executable is normally `src/sims/s51.src/ucsim_51` in that build tree.
The simulator and vendor firmware are not bundled with this package.

```sh
hd-platinum firmware-probe --apk tmp/platinum.apk \
  --simulator tmp/ucsim/src/sims/s51.src/ucsim_51 \
  --output-dir tmp/keepalive-probe
```

The probe runs genuine reset and code initialization, then explicitly supplies
one connection slot in RAM and invokes the original input ring and dispatcher.
The input is the internal record `S1$dmy`. Original code must consume it,
produce `$ack` inside its internal connection-routing envelope, and restore its
stack. The expected internal output is hex `1b53012461636b0a0d1b45`.
This envelope is not claimed to be final TCP wire data.

Execution has instruction, wall-clock and output limits. The simulator's guest
host-I/O interface is disabled; no Ethernet, UART or radio mapping is supplied.
The report distinguishes the connection fixture from real initialization and
records image and simulator hashes. No firmware bytes are patched.

## Remaining board work

A separate private reset-path experiment executes the unchanged firmware
through functional clock, SPI SRAM initialization and EEPROM control models.
It stops before executing the generic simulator's Timer2 vector at 0x002b;
the image's application vector stub is at 0x022b. Factory bootloader forwarding
and F34x timer semantics remain unmodeled. No persisted storage contents or
interrupt forwarding were invented to continue this run.

Clock readiness follows the observed reset/enable/delay/init sequence; lock
latency is not cycle accurate. This is partial startup, not a working bridge.

Full execution still needs storage contents, Ethernet register/buffer behavior,
radio transactions, timer/interrupt scheduling and bootloader vector routing.
Successful isolated keepalive execution does not establish pairing, RF delivery,
network discovery or mobile-app compatibility under original firmware.

Keep APKs, extracted images, simulator builds and execution artifacts in ignored
private directories. Project code and protocol observations do not relicense
vendor firmware; the distributable contains only authored tools and fictional
test fixtures.
