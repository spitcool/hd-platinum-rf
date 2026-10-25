<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Gateway compatibility contract

Evidence reviewed 2026-10-24. This is an inventory of the compatibility target,
including operations that remain unsupported. An implemented command handler,
a passing native test, and successful operation with a real shade are separate
claims. The new ESP32 implementation is independently authored; it does not
embed, translate, or execute the vendor firmware.

The implementation status and build instructions are in the component
[README](../README.md). A full replacement requires every relevant behavior
below to be implemented and qualified. The legacy maintenance protocol and
unresolved RF features prevent a claim of complete original-firmware equivalence.

## Evidence

- **LIVE:** Captured original-bridge traffic documented in
  [LAN protocol](../../../docs/lan-protocol.md). The original mobile app has also
  exercised the Python replacement; that is not an ESP32 interoperability test.
- **APP:** Static interface facts from the user-supplied Android Platinum 1.1
  build 14 APK, SHA-256
  `19a2992ee20fbbbc57e98e1ca5e83f2ce96a6728b69d97fcb5b4771b2723852f`.
  The local analysis is `tmp/laptop-2026-10-24/apk-analysis/command-contract.private.json`.
  `Commands.java`, `Parser.java`, `TimedEvent.java`, and `SocketHelper.java`
  establish the request builders, expected records, schedule bits, and transport.
  No APK or decompiled source is distributed with this component.
- **FW:** Reviewed original gateway dispatcher and selected handlers from
  `HiMemGateway.hex`; extracted binary SHA-256
  `f93843ff65dfb5fe91e9b3e5adf3a191bd09483d5b4ac03389ffb7c53fe5cf01`.
  Private evidence is `apk-firmware.private/command-enrollment-assessment-002.private.json`
  beneath the same dated directory. This establishes 57 distinct dollar-prefixed
  command matchers and three additional internal connection-handshake matchers.
  It does not establish every command's complete network grammar or semantics.
- **HOST:** Independently authored reference implementations in
  [lan_server.py](../../../src/hd_platinum/lan_server.py),
  [inventory_store.py](../../../src/hd_platinum/inventory_store.py), and
  [lan_discovery.py](../../../src/hd_platinum/lan_discovery.py).

Private evidence paths are reproducibility pointers, not prerequisites for
building or testing the public firmware. Public fixtures use fictional records.

## Current implementation boundary

| Area | Implemented in this component | Remaining qualification or missing behavior |
| --- | --- | --- |
| Core command families | 26 of the 27 ordinary-app prefixes below: startup, inventory, room/shade/scene/schedule management, staging/release, room/scene actions, Sync cancellation, and LED setting storage | `$RepTst` is rejected. Metadata and simulated operation tests do not establish physical compatibility. |
| Local touchscreen | Shade/room-group selection, paginated lists, Open/Close through the shared dispatcher, grant/busy/fault gates | Physical CoreS3 SE touch/display and shared LCD/W5500 bus qualification; groups currently mean rooms. |
| LAN adapter | TCP 522 banner/prefix/LF-CR, three simultaneous clients, bounded queues/timeouts, explicit client subnet; UDP 137 discovery | Physical Wi-Fi/W5500 original-app discovery and multi-client tests. |
| Radio commands | Separate bounded radio owner; primary position, Sync and Jog packet construction; durable sequence reservation; RF disabled by default | RF2401F20 packet framing, timing, PID, first-article electrical checks, receiver movement, and new-identity enrollment. |
| Other feature channels | Product validation, requested state, scenes and simulation for `07`, `10`, `18`, `19` | Hardware adapter rejects these while real RF is enabled. |
| Persistence | Versioned CRC-protected state encoding, reference validation, NVS commit/readback before mutation acknowledgement, grants separate from creation | Physical power-loss qualification and future schema migration. |
| Schedules | Running app-set local clock, weekly day mask, durable execution marker, finite scene dispatch | No RTC/NTP/DST/solar service; date/time must be set after reboot. |
| LED setting | Persisted and included in inventory | No physical CoreS3 LED/backlight mapping. |
| Provisioning | USB serial status/export/import, explicit feature grants, one-time sequence seed | USB import takes this component's binary state, not an original raw inventory or EEPROM image. |
| Original metadata | Fresh text title, own MAC/version, supported room product catalog | Opaque `$ct`/unknown records and unknown imported product codes are not preserved by the present state schema. |
| Legacy maintenance | Reject unsupported requests; never interpret 8051 firmware bytes as an ESP32 update | The 30 additional original command prefixes below, EEPROM/bootloader ABI, solar data, diagnostics, and remote configuration semantics. |

Resource ceilings are replacement policies: 32 rooms, 100 shades, eight shades
per room, 32 scenes, 64 schedules, 100 actions per batch, 1,024 pending request
bytes, a conservative 48 KiB snapshot budget, and 64 KiB state/response bounds.
These are not claims about original capacity. The state validator rejects
combinations that exceed the snapshot budget even when each individual count
is within its ceiling.

## TCP 522 framing and session behavior

| Requirement | Evidence and qualification |
| --- | --- |
| Plain TCP port 522; server speaks first | LIVE: `N HunterDouglas Shade Controller` followed by LF CR. No Telnet negotiation. |
| Replies end in bytes `0a 0d` | LIVE. Each record normally carries decimal connection ID plus space. Use reusable IDs 1–9 for legacy clients that remove exactly two prefix bytes. |
| Requests have no transport terminator | APP and LIVE. Parse the grammar across fragmented/coalesced TCP writes; packet boundaries are not command boundaries. Tolerating CR/LF is a compatibility extension. |
| Numeric fields vary in padding | APP mostly sends unpadded decimal values; iOS captures often use padded fields. Response records require the documented fixed widths. |
| Position command may omit its final hyphen | APP capture: `$pss03-04-126`, no CR/LF. Three value digits establish its end; partial TCP reads must not complete a shorter value prematurely. |
| Name fields use declared length | APP: UTF-16 code units, carried in UTF-8; maximum 25 units in the UI. Hyphens belong to names. Neither `$` nor UTF-8 byte length can replace the declared length. |
| Keepalive remains responsive during RF operations | Original app uses a 180-second Android keepalive interval; original captures acknowledge `$dmy` while Sync is active. |
| Connection interruption cancels unsubmitted staging | New implementation policy. A submitted RF operation must not be repeated automatically merely because a connection closes. |
| Position is requested state | `$done`, TX completion, and `$act00-00-` do not prove motor position or new-identity enrollment. |

The original TCP protocol has no authentication. The network adapter must apply
the installation's trusted-LAN policy and enforce bounded clients, receive
buffers, output queues, staging, timeouts, and a single radio owner.

## Ordinary app commands

Numbers below accept padded or unpadded decimal input. `L` is a UTF-16 unit
count; `NAME` has no additional terminator. IDs are zero-based. Response
placeholders `II`, `RR`, `SS`, `KK`, `FF`, and `LL` have two decimal digits;
positions and schedule-day masks have three. These are the required client
contracts; the README identifies what the current hardware adapter can execute.

| Request | Required behavior / response | Evidence |
| --- | --- | --- |
| `$dat` | Metadata, `$upd00-`, `$reset`, complete definitions and state, `$upd01-` | LIVE, APP |
| `$dmy` | `$ack`, also during Sync | LIVE; original handler executed independently |
| `$sdtMM-DD-WW-YYYY-` | Validate date and Sunday=1…Saturday=7; `$done` | APP; original date response is source-derived |
| `$stmHH-MM-SS-` | Validate local clock fields; `$done` | APP |
| `$chksyYYYY-` | Current-year capture returned `$chksy01-`; broader year/solar meaning unresolved | LIVE |
| `$LEDlP-` | Brightness 0–255, persisted; snapshot `$LEDlPPP-` | APP; physical LED mapping is board-specific |
| `$arTT-L-NAME` | Add room, allocate RF identity, return `$crRR-TT-0xHHHH-NAME` | APP, FW |
| `$merRR-TT-L-NAME` | Edit room type/name; app does not read an explicit acknowledgement | APP |
| `$rrRR-` | Delete room and return complete replacement snapshot | APP; exact original cascade needs more evidence |
| `$asR-L-NAME` | Add shade to room, allocate free group slot; `$csII-RR-GG-NAME` | APP, FW |
| `$mesII-RR-L-NAME` | Edit/move shade; preserve or explicitly rebind RF identity as appropriate | APP; original move behavior unresolved |
| `$rsI-` | Delete shade, compact IDs and rewrite references; return snapshot | APP; FW confirms metadata compaction and scene reference rewriting |
| `$pssI-F-P-` | Stage shade action; action-start, requested `$cpII-FF-PPP-`, `$done` | LIVE for primary/Jog; APP for other UI features |
| `$rls` | Submit staged work; room action records and `$act00-00-` | LIVE; original exact RF start boundary unresolved |
| `$psrR-F-P-0-` | Execute room action directly without requiring `$rls` | APP; includes legacy padded final `00-` variant |
| `$rscI-` | Start bounded Sync for selected shade; action and feature-01 status | APP, LIVE; new-identity pairing remains unqualified |
| `$stps` | Stop Sync processing | APP grammar; ability to cancel an already triggered repeater train is unverified |
| `$amL-NAME` | Add scene; `$cmSS-NAME` | APP |
| `$cmnSS-L-NAME` | Rename scene; no explicit response read | APP |
| `$rmS-` | Delete scene; complete replacement snapshot | APP |
| `$smlS-I-LL-` | Link (`01`) or unlink (`00`) shade; `$cqSS-II-LL-` | APP |
| `$mrpS-R-F-P-0-` | Store scene room feature; snapshot `$cxSS-RR-FF-PPP-UU-` | APP; `UU` is ignored by Android, original meaning unresolved |
| `$inmS-` | Execute linked shades using stored scene room features | APP; source clients wait for action-end |
| `$ateS-D-H-M-` | Add timed event; `$caKK-SS-DDD-HH-MM-` | APP |
| `$mteK-S-D-H-M-` | Edit timed event; no explicit response read | APP |
| `$rteK-` | Delete timed event; complete replacement snapshot | APP |
| `$RepTst` | Request repeater test | APP grammar; RF behavior remains unresolved, so unsupported |

The `DDD` schedule bits are Sunday `1`, Monday `2`, Tuesday `4`, Wednesday `8`,
Thursday `16`, Friday `32`, Saturday `64`, plus enabled `128`. The Android parser
uses the greater-than-128 test, so an event with no selected day does not execute.
It reads `$ca` fields as **event, scene, day mask, hour, minute**; an older
community client's conflicting ordering must not override the APK evidence.
A complete scheduler requires a running local clock, explicit behavior after
clock correction/reboot, and duplicate suppression, not only stored records.

The original Android app uses IDs as array indices. Inventory definitions must
remain dense and ordered; deleting a record requires all dependent IDs and
staged references to remain coherent. The HOST implementation's conservative
tail-only deletion policy is not an original-protocol requirement. FW confirms
that original shade deletion shifts record pointers and removes/remaps scene
references. No direct radio unlink operation was identified in that path.

## Snapshot and persistent state

| Record | Fields / preservation rule |
| --- | --- |
| `$firmNN-TEXT` | Actual replacement version; do not claim to run the vendor's firmware. Live original also emitted a bare version line. |
| `$MAC0xHHHHHHHHHHHH-` | Replacement device identity; do not reuse the original bridge's MAC. |
| `$LEDlPPP-` | Brightness 0–255. |
| `$upd00-`, `$reset`, `$upd01-` | Atomic client-side snapshot rebuild. |
| `$set006-` | Original snapshot setting; meaning unresolved. |
| `$ct...` | Original capture contains opaque bytes, not trustworthy UTF-8. Preserve byte-for-byte when importing; do not use text trimming. |
| `$crRR-TT-0xHHHH-NAME` | Room ID, product type, two-byte room RF identity, name. |
| `$csII-RR-GG-NAME` | Global shade ID, room ID, room-local group slot, name. |
| `$cpII-FF-PPP-` | Requested feature state. Jog/Sync status must not be mistaken for measured position. |
| `$cmSS-NAME` | Scene definition. |
| `$cqSS-II-LL-` | Scene-to-shade inclusion flag. |
| `$cxSS-RR-FF-PPP-UU-` | Scene room feature value and final legacy field. |
| `$caKK-SS-DDD-HH-MM-` | Schedule definition. |
| `$ctb...` and other unknown records | Preserve opaque imported data; absence from a fresh database is not evidence of incompatibility by itself. |

Persist complete inventory, referential integrity, room RF identities, shade
slots, requested state, clocks/settings, and the next RF sequence before
acknowledging committed changes. The radio sequence reservation must reach
durable storage before transmission and remain consumed after failure. A power
loss must expose either the previous valid state or the next valid state, never
a partially written database. Storage schema changes need explicit migration.

The original room identity uses two PRNG bytes. Original shade allocation
chooses an unused one-hot group in its room; the eight-slot limit is established.
The replacement may use collision-checked randomness and a deterministic free
slot without claiming that its allocation sequence matches the original.

## Product features

The 25 observed product codes and names are in
[products.py](../../../src/hd_platinum/products.py). Every product exposes
primary feature `04`; product codes `2`, `13`, and `25` also expose `18`, codes
`6` and `8` expose `07` and `19`, and codes `9` and `10` expose `07`.

| Feature | Client meaning | Physical qualification |
| --- | --- | --- |
| `01` | Sync, value `0` | Original RF captured; existing-target resync demonstrated with HOST. New RF identity enrollment unresolved. |
| `04` | Primary position, `0` closed to `255` open | HOST has observed movement on a particular installation. ESP32 packet radio still needs qualification. |
| `07` | Product-specific tilt | Client control established; receiver behavior unqualified. |
| `10` | Intermediate preset, app value `7` | Do not relabel as a universal emergency stop. |
| `12` | Jog, requested `0`; status/RF normalized to `1` | Original capture and payload oracle established; ESP32 execution unqualified. |
| `18` | Second rail / second position | Client control established; receiver behavior unqualified. |
| `19` | Product-specific additional control | Client control established; receiver behavior unqualified. |

## Complete remaining original dispatcher inventory

The preceding ordinary-command table contains 27 distinct prefixes. The other
30 dollar-prefixed matchers are below, giving **57 total**. A matcher prefix is
not a complete command specification. `0x` is literal where shown; `...` means
the remaining field grammar or semantics has not been established for public
compatibility. These commands remain explicitly unsupported rather than
returning invented success responses.

| Prefix | Established fact / unresolved boundary |
| --- | --- |
| `$wrtC0x...` | Legacy firmware write protocol; vendor image address space is not an ESP32 update format. |
| `$ssvrIP0x...` | Original network configuration path; exact remote-server behavior unresolved. |
| `$sshdIP0x...` | Original network configuration path; exact purpose unresolved. |
| `$setN-` | Sets an original configuration byte; meaning of bits unresolved. |
| `$reset` | Original reset/configuration path; not equivalent to the snapshot response token. |
| `$sigN-` | Stores an original signal/configuration byte; semantic mapping unresolved. |
| `$stnN-...` | Original name/title-related path; complete body and behavior unresolved. |
| `$sidR-0x...` | Room identifier configuration path; complete binding behavior unresolved. |
| `$sgnI-...` | Shade group configuration path; complete behavior unresolved. |
| `$psiI-...` | Additional position/action path; not an established alias for `$pss`. |
| `$pseI-...` | Additional position/action path; not an established alias for `$pss`. |
| `$mrrS-...` | Scene room operation; complete behavior unresolved. |
| `$test` | Original test handler; radio and memory effects unresolved. |
| `$RepBtl` | Original repeater bootloader path; unsupported. |
| `$BdgBtl0x...` | Original bridge bootloader request; Android sends address `D000`. Unsupported. |
| `$rcalN-` | Original calibration-related handler; purpose and effect unresolved. |
| `$cb` | Original bootloader handshake; Android expects `$cb01`. Unsupported. |
| `$verC0x...` | Original firmware verification/checksum workflow. Unsupported. |
| `$reqC` | Original firmware verification workflow; expects `$chkC`/`$finC` families. Unsupported. |
| `$reqhea` | Original storage/header request; do not interpret as an ESP32 health check. |
| `$reqepr0x...` | Original nonvolatile-memory read workflow; ABI unresolved. |
| `$wrtepr0x...` | Original nonvolatile-memory write workflow; ABI unresolved. |
| `$finepr` | Original nonvolatile-memory workflow completion. |
| `$setsmN-...` | Additional calendar/solar storage handler; full semantics unresolved. |
| `$getsdN-...` | Additional calendar/solar data handler; full semantics unresolved. |
| `$clrsd` | Additional calendar/solar data handler; full semantics unresolved. |
| `$stIP0x...` | Original static-IP configuration; byte order and persistence/network lifecycle need qualification. |
| `$gwIP0x...` | Original gateway-IP configuration; byte order and network lifecycle need qualification. |
| `$gwMAC0x...` | Original gateway-MAC configuration; not permission to replace the ESP32's MAC. |
| `$dynIP` | Original dynamic-addressing configuration; complete response/lifecycle unresolved. |

Request variants such as optional position hyphens are not separate commands.
The additional non-dollar matcher fragments are `Welco`, `OK`, and `Hello` in
an internal `S?` routing envelope. They are not established public TCP commands.
The firmware's internal `S?`, `#`, and ESC routing syntax must not appear on the
replacement TCP socket merely because it appears in dispatcher analysis.

## Original error labels

The APK defines the following labels; exact original trigger conditions and
capacity thresholds, except eight shades per room, remain incompletely known.

| Code | APK meaning |
| --- | --- |
| `00` | Bootloader error |
| `01` | TCP output buffer error |
| `02` | Maximum shades |
| `03` | Maximum shades in room |
| `04` | Maximum rooms in scene |
| `05` | Cycle error |
| `06` | RAM error |
| `07` | Maximum rooms |
| `08` | Maximum scenes |
| `09` | Maximum timed events |

The HOST emulator historically assigns several of those codes different
meanings. New firmware must document its own additional malformed, unsupported,
busy, storage, and unavailable-radio errors separately rather than attributing
them to original behavior.

This implementation uses extension codes `90` malformed input, `91` unsupported
operation/feature, `92` target/grant/staging failure, `93` busy/incompatible
operation, `94` invalid state or persistence failure, `95` backend rejection or
execution failure, `96` resource limit, and `97` invalid date/time. Unknown
command grammars close the offending session with `90`; the recognized
unsupported repeater-test/bootloader prefixes use `91`. This distinction is a
replacement policy, not recovered vendor behavior.

## UDP 137 discovery

`discoveryResponse` handles one uncompressed, unscoped RFC 1002 question of
exactly 50 bytes. It answers `PLATLINK-PDBU` and `PLATLINK-FDBU`, suffix `00` or
`20`, for NB (`0020`) and NBSTAT (`0021`), and the standard wildcard node-status
query. It ignores unrelated names, responses, registration opcodes, malformed
encodings, wrong class, trailing records, and truncation. Name answers advertise
the acquired interface IPv4 address with a 30-second TTL. Node-status returns
the two supported names and unspecified unit-ID/statistics, never the original
bridge MAC. The network adapter owns source restrictions and rate limits.

Native tests cover byte-level response fields, both names, wildcard node status,
case/suffix handling, every truncated packet size, overlong packets, malformed
headers/encodings, unrelated names, invalid advertised addresses, and rejection
of reflected responses. They do not establish discovery on a physical LAN.
