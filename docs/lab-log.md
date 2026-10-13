<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Reference bench lab log

> **Environment-specific, not canonical.** This file records sanitized capability qualifications and results for Hunter Douglas Platinum protocol work. It does not define what every contributor must own or use. Canonical requirements are in [Testing and validation](testing.md) and the [Bill of materials](bom.md).

Last updated: 2026-10-13 (America/Chicago)

Private network addresses, MAC addresses, household labels, serial numbers, and local filesystem paths are intentionally excluded from this tracked log.

## Capability snapshot

| Capability | Public qualification status | Evidence still required |
| --- | --- | --- |
| USB 3 capture host and storage path | Not yet qualified | Record the selected physical port, negotiated USB speed, free storage at test time, and sustained IQ-capture result. |
| Original Platinum App Bridge read-only LAN reference | Read-only discovery partially qualified | Continue read-only discovery; retain unsanitized address and identifiers outside the repository. |
| Wideband SDR capture and transmit path | Not yet qualified | Record the exact hardware variant and revision, firmware, FPGA image, connector condition, and capture throughput during qualification. |
| SDR mechanical protection and cooling | Not yet qualified | Verify fit, connector clearance, and ventilation for the selected enclosure. |
| Nordic-compatible `2 Mbps` reference link | Not yet qualified | Record board revisions used for the test and validate a known reference link. |
| Six-channel digital logic capture | Not yet qualified | Record the software version used and validate digital capture before probing a spare remote. |
| Standard-SMA antenna path | Not yet qualified | Inspect center pins, label test antennas, and compare relative response at the Platinum frequencies. |
| RP-SMA antenna substitution path | Not yet qualified | Inspect center sockets and use only through the correct polarity adapter. |
| Conducted-loopback passive path | Not yet qualified | Identify parts matching the BOM, then complete connector, continuity, attenuation, and substitution checks. |

Qualification status in this table reflects public evidence, not acquisition or inventory state, and must not be copied into the canonical validation matrix as project-wide status.

## Qualification log

| Date | Item | Check | Result | Sanitized evidence |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |

## Experiment log

| Date | Activity | Result | Public evidence |
| --- | --- | --- | --- |
| 2026-10-13 | Offline Python unit suite | 11/11 passed | Test command and current result are recorded in [Testing and validation](testing.md#automated-software-tests). |
| 2026-10-13 | Read-only bridge discovery | Banner and sanitized `$dat` response observed; `$dmy` produced no device reply in the observation window | Sanitized findings are recorded in [LAN protocol](lan-protocol.md). |

## Planned bench work

1. Qualify the direct USB 3 and storage path at the intended SDR stream rate.
2. Inspect and identify every RF connector before mating components.
3. Characterize the nominal 40 dB loopback at `2433`, `2440`, `2452`, and `2471 MHz`.
4. Capture the paired handheld receive-only and retain immutable IQ plus metadata.
5. Establish an independent Nordic reference link.
6. Use a logic analyzer only after establishing a mechanically safe spare-remote probe plan.

## Logging rule

Record local details needed to reproduce an experiment, but sanitize them before committing. Unsanitized IQ, logic traces, serials, addresses, and household identifiers belong under ignored `captures/` or `tmp/` paths. A result affects canonical project status only after its sanitized evidence meets the gates in [Testing and validation](testing.md#validation-sequence).
