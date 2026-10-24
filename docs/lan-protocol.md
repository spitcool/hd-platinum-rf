<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Hunter Douglas Platinum bridge LAN protocol

Status: independently documented, incomplete, and unofficial

Last evidence review: 2026-10-24

Observed bridge: private-LAN address redacted, firmware banner `2018-HD gateway 2.18a`

This document describes the Ethernet-side protocol spoken by the discontinued Hunter Douglas Platinum bridge. It does **not** describe the proprietary 2.4 GHz over-the-air protocol between the bridge and the shades. The LAN protocol is still useful for a replacement project: the original bridge can serve as a behavioral oracle while RF captures are correlated with precise LAN commands.

All names and the bridge MAC address in the examples below are fictional. The live unit's actual MAC address and household room/shade names are intentionally not recorded here.

## Evidence labels

Protocol notes on old hardware tend to become folklore. Every claim in this document is therefore qualified by its evidence:

- **LIVE** — observed byte-for-byte on the user's original bridge. The initial 2026-10-13 probe was non-mutating; the later 2026-10-24 startup/year-query capture is identified separately below.
- **CONTROLLED** — observed during bounded, operator-authorized primary-position transactions on 2026-10-23, with before/after inventory and timestamped RF capture. Command receipts do not establish motor position.
- **APP** — observed from the original Platinum mobile app while connecting to the replacement emulator on 2026-10-24. This establishes client requests, not the original bridge's replies.
- **EMULATOR** — implemented by this repository's replacement service; live results are identified separately from implemented behavior.
- **N** — implemented by Aaron Taylor's [`node-hunterdouglas`](https://github.com/exPHAT/node-hunterdouglas), inspected at commit `9bb23b79ef6beb75b26885d70b5e175c8628ba77`.
- **H** — implemented by Roland Schemers's [`homebridge-hunterdouglas-platinum`](https://github.com/schemers/homebridge-hunterdouglas-platinum), version 2.1.0, inspected at commit `1bdd2cba5ef293da08bb4b6608421a306c64e83c`.
- **A** — implemented or asserted by James Wilkinson's [`aio-powerrise-api`](https://pypi.org/project/aio-powerrise-api/0.1.0.dev3/), version 0.1.0.dev3.
- **G** — implemented by Gengen's Platinum Shade Vera plug-in v1.8, published in the [Hunter Douglas Platinum Bridge App thread](https://community.ezlo.com/t/hunter-douglas-platinum-bridge-app/187439?page=3).
- **INFERRED** — a conservative interpretation supported by evidence, but not directly demonstrated.
- **UNKNOWN** — observed or source-listed, but its meaning or behavior is not established.

“Source-derived” does not mean “verified on this firmware.” The original live
probe was non-mutating; later controlled feature-`04` transactions are explicitly
marked below. Other actuation, configuration, and pairing commands remain
source-derived unless stated otherwise.

## Executive summary

- **LIVE:** The bridge listens on plain TCP port `522`. Of the specifically targeted ports checked, `522/tcp` was open.
- **LIVE:** The server speaks first with `N HunterDouglas Shade Controller`, where this connection used `N = 5`.
- **LIVE, N, H:** Responses are records delimited by the unusual byte sequence **LF CR** (`0a 0d`, `\n\r`), not conventional CR LF.
- **LIVE:** Sending exactly the four ASCII bytes `$dat`, with no newline or other terminator, returns a complete database/status snapshot ending in `$upd01-`.
- **LIVE, APP:** An early delimiter-free `$dmy` probe was silent for approximately seven seconds. Later original-app captures received `$ack` both while idle and during Sync; the emulator now acknowledges keepalives in both states.
- **LIVE:** Most response records begin with a decimal connection number and one ASCII space. The initial capture recorded a bare firmware/version line; a later end-to-end client check returned the same text as `$firm03-...`. Treat both the connection prefix and the firmware wrapper as version-dependent.
- **APP, N, H, G:** Requests can be sent without a line ending. The original app sent a primary-position request without a final hyphen to the emulator. **A** appends CR LF; that dialect was not tested live and should not be treated as the canonical framing.
- **CONTROLLED, H, A, G:** Send a position command, wait for `$done`, then send `$rls` and observe the action lifecycle. The controlled sessions received `$act01-00-` and a `$cp` update during the position call, before `$done`; command acceptance can precede release, and RF-start semantics are not isolated.
- **LIVE, N, H, A, G:** There is no TLS. The read-only live session had no authentication exchange; all community implementations also send mutating commands without authentication. Keep port 522 restricted to a trusted LAN.

## Network endpoint and discovery

| Property | Value | Evidence |
|---|---|---|
| Addressing | Private IPv4 address; installation-specific value redacted | LIVE |
| Control/status transport | TCP | LIVE, N, H, A, G |
| TCP port | `522` | LIVE, N, H, A, G |
| Encryption | None; cleartext | LIVE |
| Authentication | No challenge or credential step observed; none implemented by the sources | LIVE, N, H, A, G |
| Optional discovery | NetBIOS Name Service broadcast on UDP `137` | A, G; APP and EMULATOR discovery demonstrated on the local setup |
| Reported NetBIOS name | `PlatLink-PDBU` in A; `PLATLINK-FDBU` in G | A, G; spelling unresolved |

The port statement above is deliberately narrow: it does not claim that every TCP and UDP port was exhaustively scanned.

For a production integration, prefer a DHCP reservation or explicit address
where the client supports it. **APP, EMULATOR:** the optional UDP 137 responder
answered a LAN broadcast, after which the original mobile app found the emulator
and updated its bridge address. The responder supports both source-listed name
variants and advertises the explicitly configured replacement-host IPv4 address.
This does not establish which name the original bridge advertises or whether
every app/platform combination discovers it. No manual-IP entry flow has been
established for the original app.

## Current emulator coverage — 2026-10-24

The `bridge-emulate` service exposes the TCP 522 protocol alongside the shared
HTTP dispatcher. Its TCP banner and replies use a decimal connection prefix and
LF CR framing. Active connection IDs are reused within `1`–`9`, preserving the
two-byte prefix expected by some integrations. A saved original inventory
seeds the database, including opaque records. Subsequent edits, requested
positions, and virtual clock fields share one atomic private state file.

| Request | Implemented behavior | Evidence or limitation |
|---|---|---|
| `$dat` | Return the imported snapshot, with current requested positions, through `$upd01-` | EMULATOR; exercised over live TCP |
| `$dmy` | Reply `$ack`, including while this connection's Sync backend is active | EMULATOR; matches later original-app idle and active-Sync captures |
| `$pssII-04-PPP-` or `$pssII-04-PPP` | Stage an allowed shade's primary position; reply `$act01-00-`, requested `$cp`, then `$done` | EMULATOR; APP used the no-final-hyphen form successfully; `PPP` is `000`–`255`; other features are rejected |
| `$psrR-4-P-0-` (also padded fields and `00-`) | Immediately submit primary positions for the room's configured, enabled targets; no `$rls` required | Android APK client contract; EMULATOR tested with fake RF; every target must be enabled |
| `$rls` | Consume the staged batch and submit finite RF commands; broadcast submitted `$cp` records and the room/action-end lifecycle | EMULATOR; RF starts on release in this implementation, while the original bridge's staging/release boundary remains unresolved |
| `$sdtMM-DD-D-YYYY-` or `$sdtMM-DD-WW-YYYY-` | Validate and persist supplied date and weekday fields; return `$done` | APP requests observed; one- and two-digit weekday accepted; original `$done` response is source-derived from G |
| `$stmHH-MM-SS-` | Validate and persist supplied time fields; return `$done` | APP request observed; original `$done` response is source-derived from G |
| `$chksyYYYY-` | Record the supplied year and return `$chksy01-` | APP request observed; LIVE original reply captured for the current calendar year, `2026`; status meaning and other-year behavior are UNKNOWN |
| `$rscII-` | Start one enabled Sync request; send action-start and feature-01 status, then room/action completion | APP and original RF captured; EMULATOR existing-target resync observed with the original bridge off |
| `$pssII-12-000-` or omitted final hyphen, then `$rls` | Stage one explicitly enabled Jog; reply action-start, `$cpII-12-001-`, `$done`; submit on release | Original stage/release and RF captured; EMULATOR fake-backend tested, physical Jog unverified; mixed position/Jog batches rejected |

Date/time fields are virtual emulator state. These requests do not set the host
clock, transmit RF, implement a running schedule engine, or generate solar
tables. The `$chksy01-` reply matches the captured original response to the
current-year request. The emulator returns that literal response for every
accepted year, but other-year behavior has not been verified on the original
bridge. Neither the meaning of `01` nor a sunrise/sunset interpretation is
established.
Malformed or unsupported requests receive emulator error codes whose meanings
must not be attributed to the original bridge. Scene invocation and additional
position features are not yet implemented. Database setup is described below;
new-identity enrollment still requires a physical validation case.

### Room and shade setup from the Android app

Static inspection of the user-supplied Platinum Android 1.1 build 14 APK supplies
the command grammar and expected response families below. The APK was neither
installed nor executed. These facts inform an independent implementation;
the app, decompiled code, and firmware assets remain outside the repository.
This is client-side evidence, not proof of every original-firmware behavior.

| Request | Meaning | Client expects |
|---|---|---|
| `$arTT-L-NAME` | Add room of product type `TT` | `$cr` room record |
| `$merRR-TT-L-NAME` | Edit room name/type | No explicit reply read |
| `$rrRR-` | Delete room | Immediate inventory snapshot through `$upd01-` |
| `$asR-L-NAME` | Add shade to room | `$cs` shade record |
| `$mesII-RR-L-NAME` | Edit shade name/room | No explicit reply read |
| `$rsI-` | Delete shade | Immediate inventory snapshot through `$upd01-` |

Legacy short `$psr` requests remain staged when followed by a command boundary;
the parser waits for a full suffix across TCP fragments before deciding. Android
`$pss` and `$rsc` requests also accept unpadded numbers. The default idle timeout
is 300 seconds to accommodate Android's 180-second keepalive interval.

`L` is the name's length in UTF-16 code units, padded to at least two decimal
digits. Names travel as UTF-8 and may contain hyphens. There is no extra request
terminator. Android uses two digits for room/type fields in room edits and
shade edits, but unpadded room IDs in `$as` and shade IDs in `$rs`/`$rsc`.
The observed iOS app used padded `$as` and `$rsc` fields. The parser accepts
both and waits for the complete declared name across TCP fragments.

The app limits names to 25 UTF-16 code units and reports eight shades per room.
The emulator validates the 25 known room product codes, assigns an unused
two-byte room RF identity and a free room-local shade slot, and persists edits
before replying. Imported unknown records and product codes are preserved.
Database creation does not enable RF control; moving, deleting/recreating, or
changing a target's product/RF binding revokes existing grants. Scene-dependent
deletion is refused while reference rewriting remains unimplemented. Stable
database IDs are retained and snapshot definitions are sorted by ID. The APK
uses those IDs as array indices, so LAN deletion refuses a non-tail entry or
room cascade that would leave a new hole. Original-bridge compaction behavior
still needs reference evidence before that restriction can be lifted.

Room creation and shade addition were previously rejected, causing the iOS
app's connection-loss dialog. The above handlers address those captured
requests. In a subsequent live app check, room creation persisted and shade
addition reached the Sync/Jog screen. The new room could not be entered until
the app was force-closed and reopened. The Android APK establishes no missing
completion record in the supplied `$cr` reply; the active iOS client's immediate
refresh issue remains unresolved pending an original-bridge comparison.
Enrollment of the newly assigned RF identity is a separate physical check.

**APP:** startup traffic included `$sdt10-24-07-2026-`, `$stmHH-MM-SS-` with
numeric time fields, and `$chksy2026-`. Initially rejecting these requests caused
a reconnect loop. The date example establishes the app's two-digit weekday
form; it does not establish the original bridge's acceptance or response.
Date/time handling was added for compatibility. An initial provisional `$done`
reply to the year request was superseded by the original response captured
below. With `$chksy01-`, the app proceeded to `$dat`, received the 759-byte
snapshot, and displayed the existing rooms and shades. The subsequent app
position/release transaction reached the RF backend, and the operator confirmed
the selected shade moved to roughly halfway while the original bridge was off.

The following preserves the app's position value and request framing but uses
fictional shade and room IDs. Each server line also carries the usual decimal
connection prefix, represented by `N`:

```text
C: $chksy2026-
S: N $chksy01-<LF><CR>
C: $dat
S: [snapshot records through $upd01-; private contents omitted]
C: $pss03-04-126
S: N $act01-00-<LF><CR>
S: N $cp03-04-126-<LF><CR>
S: N $done<LF><CR>
C: $rls
S: N $cp03-04-126-<LF><CR>
S: N $act02-02-<LF><CR>
S: N $act00-00-<LF><CR>
```

The position request has no final hyphen or transport delimiter. Its accepted
value was `126`; the physical observation was approximate halfway, not a
calibrated position measurement. This verifies discovery, startup, inventory
display, and one existing shade's primary-position control through the original
app on this setup. New-identity pairing, room/shade setup, scenes, schedules,
other feature channels, and Control4 remain separate unverified paths.

**LIVE, original startup/year query — 2026-10-24:** with the app closed, one
connection received only the banner during the initial observation window.
Sending the app's same-year request produced this exchange, with the connection
number represented generically:

```text
S: N HunterDouglas Shade Controller<LF><CR>
C: $chksy2026-
S: N $chksy01-<LF><CR>
```

No shade, RF-control, or pairing command was sent in this probe. It establishes
the exact reply for this request and bridge state, not a general meaning for
the status field or the command's possible state effects.

**EMULATOR, bounded live result:** a TCP position/release transaction drove the
RF backend while the original bridge was off. The operator confirmed the shade
closed; independent receive decoding recovered all ten generated packets and
ten matching response packets, with valid CRCs and no capture gaps or clipping.
This demonstrates one TCP-to-RF actuation path in addition to the app transaction
above. It does not establish complete mobile-app, enrollment, or Control4
compatibility. Returned position records continue to represent requested state
rather than measured motor feedback.

## Wire framing

### Connection banner

Immediately after TCP connect, the live bridge sent:

```text
35 20 48 75 6e 74 65 72 44 6f 75 67 6c 61 73 20
53 68 61 64 65 20 43 6f 6e 74 72 6f 6c 6c 65 72
0a 0d
```

Rendered with control characters named:

```text
5 HunterDouglas Shade Controller<LF><CR>
```

The decimal value appears to be a connection/session slot allocated by the bridge. It was stable as `5` for the observed connection. Whether it is active-client count, a monotonically cycling slot, or something else remains **UNKNOWN**. Do not assume it is one digit.

Read and validate the banner before sending a command. H's history specifically records failures when clients attempted to set a shade before consuming the first line.

### Request framing

The strongest observed request format is simply the command bytes, with no transport delimiter:

```text
24 64 61 74
$  d  a  t
```

That exact write produced the live snapshot. N, H, and G also write bare commands. A writes `command + "\r\n"`; this may be tolerated by some firmware, but it was not verified on the live bridge.

Recommended rule:

1. Encode command tokens and numeric fields as ASCII.
2. Include any trailing hyphen required by that command's grammar.
3. Do **not** append LF, CR, CR LF, LF CR, or NUL unless compatibility testing proves it necessary for a particular firmware.
4. Send one logical command at a time and wait for its completion marker before sending an unrelated command.

A trailing field hyphen, such as the final `-` in `$pss01-04-128-`, belongs to the command. It is not a line terminator.

**APP:** the successful emulator control transaction used `$pss03-04-126`
(fictional shade ID), without that final hyphen or any CR/LF. The emulator
accepts both position forms. This client observation does not establish the
original bridge's acceptance of every request-ending variant.

### Response framing

**LIVE, N, H:** response records end with `0a 0d` (LF CR). TCP does not preserve record boundaries, so one `recv()` can contain a partial record, one record, or many records. Buffer bytes and split only when the two-byte delimiter is present.

Conceptual parser:

```text
buffer += tcp_bytes
while buffer contains 0a 0d:
    raw_record, buffer = split_once(buffer, 0a 0d)
    if raw_record begins with one-or-more ASCII digits followed by byte 0x20:
        connection_number, payload = split at the first space
    else:
        connection_number = absent
        payload = raw_record
    dispatch payload as bytes
```

Important implementation details:

- Strip a prefix matching `^[0-9]+ `, not a fixed two bytes. N's historical `slice(2)` works for a one-digit prefix but is not robust.
- The prefix is optional in the observed corpus. The initial capture recorded bare `2018-HD gateway 2.18a`; a later capture returned `$firm03-2018-HD gateway 2.18a` after prefix removal.
- Do not decode the entire stream as strict UTF-8. The live `$ct` payload contained 24 apparently binary/non-UTF-8 bytes.
- Do not call a generic whitespace `strip()` on raw records before field extraction. It can destroy meaningful bytes or spaces in a name. Remove only the framing delimiter and the optional connection prefix.
- If an API reads through LF, it may return the following CR at the start of the next buffer or attached to the prior line. Handle the actual `LF CR` order explicitly.
- There are no observed request IDs. Serializing commands is the only reliable way to associate a response with a request.

### Source dialect comparison

| Aspect | LIVE | N | H | A | G |
|---|---|---|---|---|---|
| `$dat` spelling | `$dat` | `$dat` | `$dat` | `$dat` | `$dat-` |
| Request terminator | none | none | none | CR LF | none |
| Response delimiter | LF CR | LF CR | LF CR | uses LF-oriented `readline()`; tests model CR LF | framework configured as `crlf` |
| Prefix handling | optional, `5 ` observed | discards fixed 2 bytes | regex `^\d+ ` | regex `^\d+ ` | patterns require `^%d ` |
| Connection style | one probe connection | persistent | new connection per operation | persistent | persistent |

Use the **LIVE** column as the compatibility baseline for this bridge.

## Sanitized live transcript

The following preserves the observed order and record shapes while replacing the real MAC, hashes, positions, and names with safe examples. Ellipses in square brackets are annotations, not bytes on the wire.

```text
S: 5 HunterDouglas Shade Controller<LF><CR>
C: $dat
S: 5 $firm03-2018-HD gateway 2.18a<LF><CR>
S: 5 $MAC0x02AABBCCDDEE-<LF><CR>
S: 5 $LEDl064-<LF><CR>
S: 5 $upd00-<LF><CR>
S: 5 $reset<LF><CR>
S: 5 $set006-<LF><CR>
S: 5 $ct[24 opaque bytes]$<LF><CR>
S: 5 $cr00-01-0x1A2B-Room A<LF><CR>
S: 5 $cr01-10-0x3C4D-Room B<LF><CR>
S: 5 $cs00-00-00-Shade A<LF><CR>
S: 5 $cp00-04-128-<LF><CR>
S: 5 $cs01-00-00-Shade B<LF><CR>
S: 5 $cp01-04-255-<LF><CR>
S: [nine more sanitized $cs/$cp pairs; 11 shades total]<LF><CR>
S: 5 $upd01-<LF><CR>
```

Live findings from this snapshot:

- Two room records and eleven shade records were returned.
- A second read-only `$dat` verification returned firmware as `$firm03-2018-HD gateway 2.18a`; the meaning of subfield `03` is unknown. The initial manual capture had recorded the same version text without the `$firm03-` wrapper, so decoders must tolerate both.
- Each live shade definition was immediately followed by a primary-position record using feature `04`.
- No scene, scene-link, scene-room-position, or schedule record appeared. Their formats below are source-derived only.
- `$upd00-` and `$upd01-` bracketed the database update section. Metadata appeared before `$upd00-`.
- `$reset` appeared inside the snapshot and is best interpreted as “clear/rebuild the client's cached database,” consistent with G.
- `$set006-` was observed but its meaning is **UNKNOWN**.
- The `$ct` payload did not resemble the textual house-title format assumed by H and A on this firmware. Preserve it as opaque bytes until its purpose is established.

## Field notation

| Symbol | Meaning |
|---|---|
| `N` | Variable-width decimal connection number added to responses, followed by one space |
| `II` | Two-digit decimal shade ID, usually zero-padded |
| `RR` | Two-digit decimal room ID, usually zero-padded |
| `SS` | Two-digit decimal scene ID, usually zero-padded |
| `KK` | Two-digit decimal schedule ID |
| `BB` | Two-digit room/product type |
| `GG` | Two-digit shade field called a group number by A and a hash by G; semantics unverified |
| `FF` | Two-digit feature/operation code |
| `PPP` | Three-digit wire value, normally `000` through `255` |
| `LL` | Two-digit link flag; `00` false, nonzero true in source parsers |
| `HHHH` | Four hexadecimal digits in a room hash/identifier |
| `UU` | Two-digit field whose meaning is unknown; source examples use `00` |
| `Name` | Remaining bytes after all fixed fields; may contain spaces and hyphens |

Responses consistently use padded widths in the evidence. G sends some command fields without padding, demonstrating likely permissive input parsing. New clients should emit the padded canonical form.

## Read-only and keep-alive commands

These commands do not intentionally move a shade or rewrite configuration.

| Command | Meaning | Expected completion | Evidence and notes |
|---|---|---|---|
| `$dat` | Return complete bridge metadata, rooms, shades, positions, scenes, and schedules | `$upd01-` | LIVE, N, H, A. Live form has no trailing hyphen. G uses `$dat-`. |
| `$dmy` | Dummy/keep-alive | `$ack` in later original-app idle and active-Sync captures | APP, EMULATOR. An earlier standalone probe was silent. G and A's `ping()` wait for `$ack`; A's periodic keep-alive treats it as fire-and-forget. |

The earlier silent `$dmy` probe was sent after consuming the banner. Its PTY echo was local, while the later app-session `$ack` records were received from the original bridge. The condition behind that difference remains unresolved; the emulator follows the positive app-session evidence.

Even `$dat` exposes household names and a hardware address. Treat captures as sensitive and sanitize them before publication.

## Runtime actuation commands

These commands can move physical equipment. Bounded, single-shade feature-`04`
position/release transactions were tested on 2026-10-23. The original probe was
non-mutating; room, scene, stop, jog, and other feature operations below remain
source-derived unless explicitly marked.

### Position one shade

Canonical form:

```text
$pssII-FF-PPP-
```

Examples with fictional IDs:

```text
$pss03-04-000-    primary feature fully closed
$pss03-04-255-    primary feature fully open
$pss03-04-128-    raw midpoint under the source clients' percent conversion
```

H omits the final hyphen, while A and G include it; N also constructs a
no-final-hyphen form. **CONTROLLED:** the final-hyphen form above, sent as bare
ASCII with no CR/LF, returned `$done` for requested values `0`, `128`, and `255`.
**APP, EMULATOR:** a later original-app transaction sent the no-final-hyphen
form with value `126`; release reached the RF backend and the operator observed
the selected shade roughly halfway with the original bridge off. The original
bridge's acceptance of this variant has not been separately probed.

**CONTROLLED, H, A, G:** a position command produces `$done`. The observed order
was action-start and position-update records, then `$done`; these can be
coalesced in one TCP read. Queueing multiple `$pss` commands before release is
supported by source clients but was not part of the single-target local tests.

### Release a staged shade operation

```text
$rls
```

Send `$rls` after all intended `$pss` commands have returned `$done`.

Source behavior differs slightly:

- H waits for `$act00-00-` after `$rls`.
- N waits for a response containing `act`.
- G treats the action lifecycle as completion and blocks other operations until it ends.
- A sends `$rls` without waiting and describes later `$act...` records as unsolicited movement events.

The compatible interpretation is: `$rls` has no small, dedicated acknowledgement; action records report the resulting bridge activity and may also describe actions initiated by another client.

**CONTROLLED:** one `$rls` followed each acknowledged position request, and the
client observed `$act00-00-` with a finite timeout. No automatic retry or restore
was performed by the transaction primitive. Separately requested restore
transactions were journaled as new requests. Later inventories reported the
requested raw values, but those values are bridge state, not independent motor
feedback. RX was armed before both position and release after the initial
capture showed activity during position staging. A measured delay between the
two commands would be needed to isolate their RF effects.

### Position a room

G implements:

```text
$psrRR-FF-PPP-00-
```

It waits for `$act00-00-`. This is more efficient than issuing a `$pss` for every shade, but it is not live-verified.

### Invoke a stored scene

A implements:

```text
$inmSS-
```

A waits for `$act00-00-`. Scene IDs come from `$cm` records in the snapshot.

### Intermediate preset / “stop”

Community implementations disagree on the exact semantics:

```text
$pssII-10-007-    G: invoke the shade's intermediate preset
$pssII-10-000-    A: exposed as stop-at-current-position
```

G calls feature `10` “Intermediate stop” and uses wire value `007`; it cannot determine the resulting physical position and displays 50%. A sends `000`, calls it a stop, and warns that some hubs do not return `$done`. Do not assume feature `10` is a universal emergency stop. Verify it on the exact shade type before exposing it to automation.

### Test/jog

A implements the identification jog as:

```text
$pssII-12-000-
```

Controlled original-bridge transactions returned `$cpII-12-001-` followed by
`$done`, then accepted `$rls` and emitted the room/action-end lifecycle. A fresh
action included `$act01-00-` before the status; a stage during an earlier action
did not emit a new start marker. G also identifies feature `12` as “Test.”

The captured 250 kbps request uses feature `0x0c`, value `1`, and flags `1`,
despite the LAN request carrying value `000`. The emulator accepts only that
observed shade request, requires `jog_enabled`, and stages exactly one Jog.
Additional Jog or position stages clear the pending batch and return an error;
release consumes the stage before dispatch, including on failure. No feature-12
status is persisted as a position, and an RF receipt does not confirm motion.
The public Jog backend uses the narrow profile and three seconds of diagnostic
RX; the optional wide Sync profile does not change Jog.

## Action and command responses

All examples may be preceded by the optional `N ` connection prefix.

| Record | Meaning | Evidence |
|---|---|---|
| `$done` | Command accepted/completed at the bridge-command layer; locally observed after `$pss`; date/time use remains source-derived | CONTROLLED, H, A, G |
| `$chksy01-` | Exact reply to `$chksy2026-` in the 2026-10-24 original-bridge probe; meaning of `01` and other-year responses remain unknown | LIVE |
| `$ack` | Acknowledgement to `$dmy`; captured after app startup, including during Sync | APP, A, G; an earlier standalone probe was silent |
| `$errorNN-` | Error with two-digit code | A; meanings of codes `00`–`09` are unknown |
| `$act01-00-` | Action-start record; locally arrived before the position call's `$done` | CONTROLLED, G |
| `$act02-RR-...` | Room-action record; local raw records included a leading-NUL variant | CONTROLLED, G |
| `$act00-00-` | End of the reported action lifecycle; not a motor-position acknowledgement | CONTROLLED, H, A, G |

Action events are not correlated to a request ID. A client that shares the bridge with the legacy app or another controller must be prepared to see action events that it did not initiate.

Two original-bridge Sync references emitted action-start after about 11–28 ms,
the room-action record after 0.78–0.81 seconds, and action-end after
16.13–16.22 seconds. `RR` identifies the room; a nonzero value is not an error
code. These are observed timings, not fixed protocol deadlines.

The emulator sends the Sync room-action record once the checked finite TX
returns successfully, before waiting for its eighteen-second diagnostic RX.
Action-end still waits for backend validation and cleanup. Neither event
confirms enrollment. A later receive failure can therefore follow room-action
with an error instead of action-end. Notification failure does not resend RF.
The operator measured a 15-second countdown in the original app. That client
display interval is distinct from the emulator backend's 18-second receive
window and is not proof that the shade entered programming mode.
Sync runs in one owned, non-daemon worker while the connection reader continues
replying to `$dmy` with `$ack`. Other commands received on that connection during
Sync receive the emulator's busy error and are discarded, never queued for a
later RF action. A fragmented command retains that busy status even if its final
bytes arrive after Sync completes; fragmented keepalives remain acknowledged.
Socket writes are serialized, and the shared service still
permits only one RF action at a time. Disconnect or shutdown does not retry or
abandon a submitted action: the finite backend retains ownership through cleanup,
and server close waits for it. Position release remains synchronous. Receive-log
times describe reads by the server, not exact arrival times on the network.

Recommended movement state machine:

```text
connect -> consume banner
        -> send $pss for shade 1 -> wait $done
        -> send $pss for shade 2 -> wait $done
        -> send $rls
        -> observe action events through $act00-00- (with timeout)
        -> optionally run $dat to reconcile cached state
```

Do not pipeline unrelated commands. G's queue and H's throttling both reflect the bridge's limited command handling.

## Snapshot record reference

The payload forms below omit the optional connection prefix and LF CR delimiter.

### Bridge metadata and snapshot control

| Record | Interpretation | Evidence |
|---|---|---|
| `2018-HD gateway 2.18a` | Bare startup/firmware text recorded in the initial live capture | LIVE |
| `$MAC0xMMMMMMMMMMMM-` | Twelve hexadecimal MAC digits | LIVE, H, A |
| `$LEDlPPP-` | LED brightness as a raw value, apparently `0`–`255` | LIVE, H, A |
| `$firmNN-TEXT` | Firmware record. A later live verification returned `$firm03-2018-HD gateway 2.18a`; the meaning of `NN = 03` is unknown | LIVE, H, A |
| `$upd00-` | Start snapshot/update | LIVE, A, G |
| `$reset` | Clear or mark stale the previously cached database before rebuilding | LIVE, G |
| `$set006-` | Unknown snapshot setting | LIVE, UNKNOWN |
| `$ct<bytes>` | Source clients call this a house title; live payload was 24 opaque bytes followed by `$` | LIVE, H, A; meaning unresolved |
| `$upd01-` | End snapshot/update; commit the newly parsed cache | LIVE, N, H, A, G |
| `$ctb...` | Unknown; A explicitly ignores records containing this token | A, UNKNOWN |

Firmware parsing needs to accept both observed forms: bare free text and `$firmNN-TEXT`. Preserve `NN` as an unknown numeric subfield and expose the remaining text as the human-readable version. A's fixed integer parse of examples such as `$firm00-0018-` is too narrow for the live text dialect.

### Room

```text
$crII-BB-0xHHHH-Name
```

| Field | Meaning |
|---|---|
| `II` | Room ID |
| `BB` | Product/room type controlling feature semantics |
| `0xHHHH` | Four-hex-digit room hash or identifier; purpose unknown |
| `Name` | Remainder of record; room name |

This exact shape was observed live and is also parsed by G. H accepts any non-hyphen third field. A's documentation instead models fixed padding before the name; use delimiter/fixed-field parsing rather than A's fixed name offset.

### Shade

```text
$csII-RR-GG-Name
```

| Field | Meaning |
|---|---|
| `II` | Shade ID |
| `RR` | Owning room ID |
| `GG` | Unknown two-digit field; called group number by A and hash by G |
| `Name` | Remainder of record; shade name |

The exact shape was observed live. Names are tail fields: split only the three header separators so a name containing `-` remains intact.

### Shade position/state

```text
$cpII-FF-PPP-
```

| Field | Meaning |
|---|---|
| `II` | Shade ID |
| `FF` | Feature whose state is being reported |
| `PPP` | Raw position/state value, normally `000`–`255` |

The live bridge returned feature `04` positions for all eleven shades. H, A, and G also parse this form. `$cp` records can be part of `$dat` and can be unsolicited state updates in G/A-style persistent clients.

### Scene

```text
$cmSS-Name
```

G parses one separator after the ID. A examples sometimes show extra dash padding. Treat the remainder after the first post-ID separator as the name; do not discard arbitrary leading hyphens unless captures establish them as padding.

### Scene-to-shade link

```text
$cqSS-II-LL-
```

`SS` is scene ID, `II` is shade ID, and `LL` is a link flag. Source parsers treat `00` as unlinked and nonzero as linked.

### Scene room position

```text
$cxSS-RR-FF-PPP-UU-
```

G captures the final `UU` field and source examples use `00`. A's parser models only through `PPP`, although A's command documentation includes a trailing zero field. Preserve `UU` rather than discarding it; its meaning is unknown.

### Schedule/timed event

G's stronger fixed-field parser describes:

```text
$caKK-SS-DDD-HH-MM-
```

| Field | Meaning according to G |
|---|---|
| `KK` | Schedule ID |
| `SS` | Scene ID |
| `DDD` | Three-digit day/enable bit mask; bit 7 (`128`) enables the schedule and bits 0–6 represent Sunday through Saturday |
| `HH` | Hour, `00`–`23` |
| `MM` | Minute, `00`–`59` |

A instead documents `$caII-HH-MM-DD-EE-`. These interpretations conflict, and no `$ca` was present in the live snapshot. Retain raw fields until a capture from a configured schedule resolves the layout.

## Feature codes and position values

### Raw value conversion

For the ordinary primary feature (`04`), inspected source clients use a native
range of 0–255. H explicitly converts HomeKit percentages using the following
mapping in its [pinned platform source](https://github.com/schemers/homebridge-hunterdouglas-platinum/blob/1bdd2cba5ef293da08bb4b6608421a306c64e83c/src/platform.ts#L393-L407),
then formats that native integer directly into `$pss` in its
[controller](https://github.com/schemers/homebridge-hunterdouglas-platinum/blob/1bdd2cba5ef293da08bb4b6608421a306c64e83c/src/controller.ts#L102-L109):

```text
wire = round(percent * 255 / 100)
percent = round(wire * 100 / 255)
```

The source convention is `000 = closed` and `255 = open` for an ordinary bottom-up shade. Feature semantics vary by room/product type, so this conversion alone is insufficient for dual-rail and vane products.

**CONTROLLED:** requests `0`, `128`, and `255` were acknowledged and appeared
in later inventories. Correlated RF payloads contain `00`, `80`, and `FF`;
on the same target, requests `128` and `0` changed only the last payload byte.
This supports the raw command scale, including a middle value, but does not
calibrate physical travel or establish every value. The proposed alternative
of ordinary values `0–100` plus a special `255` endpoint is not how H generates
commands. See the [position RF observations](rf-protocol.md#position-packets-correlated-with-original-bridge-commands--2026-10-23).

### Known feature codes

| Code | Source-derived meaning | Notes |
|---|---|---|
| `01` | Sync status/operation | Original-app `$rsc` and RF captured; existing-target emulator resync observed |
| `04` | Primary rail, bottom-up motion, or traverse | LIVE for inventory; CONTROLLED for bounded single-target requests; N, H, A, G |
| `07` | Vane/tilt or Luminette “close right” | A, G |
| `10` | Intermediate preset/stop | A and G disagree on exact semantics/value |
| `12` | Test/jog | A, G |
| `18` | Middle/top-down rail | H, G |
| `19` | Reverse tilt or Luminette “close left” | A, G |

### Room/product type map

`BB` in `$cr` selects the product family and the app's controls. The 25 codes
below are confirmed by static inspection of Android 1.1 build 14, including an
independent DEX constant check. This resolves several community-source gaps;
it does not validate the physical behavior of untested RF feature channels.
The executable catalog is in `hd_platinum.products`.

| `BB` | Product family in community sources | Features/caveats |
|---|---|---|
| `00` | Alustra Woven Textures Roller | `04` |
| `01` | Duette/Applause standard | `04` |
| `02` | Duette/Applause DuoLite or top-down/bottom-up | `04` bottom rail, `18` middle rail |
| `03` | Duette/Applause top-down | `04`, direction semantics differ from standard |
| `04` | Duette/Applause Skylift | `04` |
| `05` | Designer Roller/Screen | `04` |
| `06` | Luminette Privacy Sheers | `04` traverse, `19` close-left, `07` close-right |
| `07` | Luminette Modern Draperies full panel | `04` traverse |
| `08` | Luminette Modern Draperies dual panel | `04` traverse, `19` close-left, `07` close-right |
| `09` | Pirouette Window Shadings | Android selects `04` and `07` |
| `10` | Silhouette/Nantucket Window Shadings | `04` primary, `07` vane |
| `11` | Vignette Modern Roman traditional | `04` |
| `12` | Vignette Modern Roman tiered | `04` |
| `13` | Vignette tiered top-down/bottom-up | `04` bottom rail, `18` middle rail |
| `14` | Skyline Gliding Window Panels | `04` traverse |
| `15` | Pleated Shades | `04` |
| `16` | Alustra Woven Textures Roman | `04` |
| `17` | Solera Soft Shades | `04` |
| `18` | Design Studio Roman | `04` |
| `21` | Silhouette/Nantucket A Deux room-darkening variant | Android selects `04` |
| `22` | Provenance Woven Wood standard | Android selects `04` |
| `23` | Provenance independently operable liner | Android selects `04` |
| `24` | Provenance vertical drapery | Android selects `04` |
| `25` | Provenance top-down/bottom-up | Android selects `04` and `18` |
| `30` | Alustra independently operated liner | Android selects `04` |

Do not infer capability solely from a product name. Use the room type, observe the official application, and capture known-good commands before enabling secondary or vane features.

### Composite UI mappings are not protocol fields

G maps multi-feature products onto a single 0–100 UI slider. That mapping is an integration policy, not part of the wire protocol:

- For types `02` and `13`, G uses 0–50 for feature `18` and 50–100 for feature `04`; 50 represents fully closed.
- For Luminette types `06` and `08`, G divides a single slider among traverse and the two vane directions.
- A instead exposes primary position and tilt as separate concepts, and maps bidirectional tilt across features `19` and `07`.

A replacement API should expose raw feature channels first. A later Control4 layer can choose a user-facing composite model without baking that policy into the transport.

## Configuration-changing and hazardous commands

The following commands are present in source code but were not used in the
original non-mutating probe. Later app startup requests are marked below. These
commands can change bridge configuration, pairing, schedules, or firmware state.
Historical read-only investigation guidance does not restrict the user's
subsequently authorized pairing and replacement scope. Establish the grammar
and preserve recoverable state for the specific authorized experiment; the
unresolved token list is not sufficient to construct an enrollment transaction.

### Formats described by sources

| Command | Source-derived purpose | Expected response |
|---|---|---|
| `$sdtMM-DD-D-YYYY-` | Set bridge date; weekday `1 = Sunday` through `7 = Saturday`; APP sends a two-digit weekday | `$done` in G; original response not locally captured |
| `$stmHH-MM-SS-` | Set bridge time; APP request observed | `$done` in G; original response not locally captured |
| `$chksyYYYY-` | Year-valued startup request observed from APP; purpose UNKNOWN | LIVE `$chksy2026-` returned `$chksy01-`; other-year responses and status meaning UNKNOWN |
| `$mrpSS-RR-FF-PPP-00-` | Set a scene's room position | A; response not established |
| `$smlSS-II-LL-` | Link/unlink a shade in a scene | A; response not established |
| `$LEDlPPP-` | Set LED brightness | A token and matching response family; response not established |

G automatically set the date and time when it connected, and APP startup also
sent those requests. A new client should make original-bridge clock writes an
explicit behavior. The emulator accepts them as virtual fields for app
compatibility, as described above.

### Tokens with unresolved grammar

A lists these additional command prefixes without complete, verified field layouts:

| Token | Reported purpose |
|---|---|
| `$ar` / `$mer` / `$rr` | Add / edit / remove room |
| `$as` / `$mes` / `$rs` | Add / edit / remove shade |
| `$rsc` / `$stps` / `$tss` | Start sync / stop sync / test shade |
| `$am` / `$cmn` / `$rm` | Add / rename-edit / remove scene |
| `$BdgBtl` | Enter bridge bootloader |

`$BdgBtl` is especially hazardous. Merely knowing a token exists is not enough to implement it.

## Robust client behavior

1. Maintain one TCP connection when practical and serialize commands through a queue.
2. Consume and validate the banner before writing.
3. Parse response framing as bytes using exact LF CR.
4. Remove an optional variable-width numeric prefix per record.
5. Keep unknown records and unknown fields; log sanitized hex rather than dropping them.
6. For `$dat`, collect through `$upd01-`. If the connection drops first, discard the partial snapshot.
7. Build the new room/shade/scene model separately and atomically replace the cached model only at `$upd01-`.
8. Associate records by IDs rather than relying on order, even though each live `$cs` was followed by its `$cp`.
9. Parse tail names after a fixed number of separators so embedded hyphens survive.
10. Allow unsolicited `$cp`, `$cr`, `$cs`, and `$act` records when no command is active.
11. After reconnect, obtain a fresh `$dat`; connection prefixes and state may have changed.
12. Put finite timeouts around `$done`, `$upd01-`, and `$act00-00-`. A missing completion marker must not deadlock the queue.

Community clients use timeouts between roughly 15 and 30 seconds for command/snapshot work. That is implementation precedent, not a measured protocol requirement.

## Known edge cases and disagreements

- **LF CR versus CR LF:** the live bridge, N, and H establish LF CR for responses. A's test fixtures use CR LF and its transport appends CR LF to requests. Preserve the distinction in tests.
- **Optional prefix:** most records were prefixed, but the initial firmware/version capture was not. Never discard the first two bytes unconditionally.
- **Prefix rollover:** a connection number of 10 or higher would break fixed-width prefix removal. Use a decimal regex/state machine.
- **Binary `$ct`:** source parsers assume text; the live record was not safe UTF-8. Store raw bytes.
- **Names with hyphens:** naive `split('-')` parsing truncates them. Parse fixed headers, then consume the tail unchanged.
- **Trailing command hyphen:** both position forms exist in source. Bare `$dat` and final-hyphen `$pssII-04-PPP-` are observed against the original bridge. APP used no-final-hyphen `$pssII-04-PPP` successfully against the emulator; other command-ending variants remain unverified.
- **Leading NUL bytes:** controlled captures retained room-action and action-end records preceded by 30 NUL bytes before their decimal connection prefixes. The parser normalizes leading NUL padding only for the complete `$act00-00-`, `$act01-00-`, and `$act02-RR-` forms, with an optional decimal connection prefix. It preserves every original byte in `BridgeRecord.raw`; other binary or malformed records retain their existing parsing behavior. This lets a padded action-end marker complete the transaction while preserving the evidence.
- **`$dmy` response:** an early standalone probe was silent for approximately seven seconds. Later original-app proxy captures received `$ack` while idle and during active Sync. The emulator matches those acknowledgements; the cause of the earlier silent probe remains unknown.
- **`$rls` response:** treat `$act...` as an asynchronous action lifecycle, not as a uniquely correlated reply.
- **State from handheld RF remotes:** G's author reported that the integration could observe actions from the mobile app but not necessarily from handheld remotes. The legacy shades/bridge may not provide true two-way position feedback for all control paths.
- **Concurrent clients:** source authors serialize work and community reports describe the bridge as sensitive to simultaneous activity. The exact connection limit is unknown.
- **Snapshot variants:** live captures produced both a bare version string and a `$firm03-...` record, plus `$set006-` and an opaque `$ct`; source fixtures often omit or reinterpret these.

## Open questions and safe next captures

The following should remain explicitly unresolved until captured:

1. Meaning and structure of the 24-byte live `$ct...$` payload.
2. Meaning of `$set006-`.
3. Why the early standalone `$dmy` probe was silent while later original-app idle and active-Sync sessions received `$ack`; firmware, session startup, and terminator effects are not isolated.
4. Which request endings the original bridge accepts beyond observed bare
   `$dat` and final-hyphen feature-`04` `$pss`. The app's no-final-hyphen position
   form is now observed working against the emulator.
5. The distinct RF effects of `$pss` and `$rls`: action-start and position-update records arrived before `$done`, but the local calls did not deliberately separate staging and release long enough to assign RF-start semantics.
6. Error-code meanings for `$errorNN-`.
7. Scene and schedule record layouts from this specific bridge configuration.
8. Feature `07`, `18`, and `19` behavior for the installed products.
9. Whether an RF handheld action causes an unsolicited `$cp` or any LAN event.
10. Connection-number allocation, wraparound, idle timeout, and simultaneous-client limit.
11. The actual NetBIOS name advertised by this unit.
12. The meaning of `01` in the captured `$chksy01-` reply, other-year responses,
    and possible state effects. Matching this reply let the app complete startup
    and control one existing shade; broader setup and enrollment compatibility
    remain unresolved.

Safe capture order:

1. Reconnect and record the banner plus raw byte timing.
2. Repeat exact bare `$dat`; compare order and opaque fields across connections.
3. Test `$dmy` on an otherwise idle connection and wait without sending follow-up data.
4. Capture traffic from the legacy mobile app while it performs a read-only refresh.
5. Within the user's authorized target and movement scope, choose one known
   shade and one reversible movement, capture both LAN and 2.4 GHz RF, and
   reconcile with `$dat` and an independent physical observation.

This order describes initial discovery. It does not prohibit subsequently
authorized pairing or configuration captures; those require a specific known
target and recorded before/after state. The bootloader token is unrelated to
normal discovery or enrollment.

## Using the LAN protocol as an RF oracle

The LAN shade IDs are bridge database indexes, not directly observed RF
addresses. **CONTROLLED:** the wide received position packets instead contain
the room's inventory RF identifier and a one-hot shade mask consistent with
`1 << (group_field - 1)`. Four targets in one room independently support that
mask mapping. A same-target `128 → 0` comparison changes the last payload byte
from `80 → 00`; another room's raw `255` request has `FF`. These observations
are summarized in the [RF specification](rf-protocol.md#position-packets-correlated-with-original-bridge-commands--2026-10-23),
with emitter and physical-response limitations retained.

The capture relation is:

```text
timestamp
  -> LAN command: shade II, feature FF, value PPP
  -> bridge response: $done / $act lifecycle
  -> simultaneous 2.4 GHz burst(s)
  -> optional LAN $cp update
```

Vary one field at a time and repeat each action. Record RF frequency, channel/bandwidth, packet bytes, retransmission count, and timing alongside `II`, `FF`, and `PPP`. This separates transport effects from payload encoding and is the cleanest path from a working bridge to an SDR transmitter.

## Security and preservation notes

- Port 522 is a cleartext, apparently unauthenticated control surface. Firewall it from untrusted VLANs and never expose it to the internet.
- Use a single designated research host to reduce accidental concurrent access.
- Save raw captures, but publish only sanitized extracts. `$dat` discloses names and the bridge MAC.
- Preserve the original bridge's state. For authorized pairing or configuration work, record the affected target and before/after state and plan recovery; initial read-only guidance is not a blanket prohibition on that work. Bootloader entry remains outside ordinary pairing and control.
- A passive packet capture or a read-only `$dat` is preferred whenever it can answer the question.

## Credits, provenance, and licenses

This is an original synthesis of live observations and prior community investigation. Protocol facts and short wire tokens are restated; no upstream implementation is copied into this document.

- **Aaron Taylor / ExPHAT — [`node-hunterdouglas`](https://github.com/exPHAT/node-hunterdouglas).** Early JavaScript implementation that established bare-command writes, LF CR parsing, `$dat`, `$pss`, `$rls`, room/shade parsing, and the 0–255 position scale. MIT License, copyright 2016 Aaron Taylor.
- **Roland Schemers — [`homebridge-hunterdouglas-platinum`](https://github.com/schemers/homebridge-hunterdouglas-platinum).** The clearest line-oriented TCP implementation and source for banner handling, variable numeric prefixes, exact LF CR framing, command completion markers, and feature `18`. MIT License, copyright 2020 schemers.
- **James Wilkinson — [`aio-powerrise-api` 0.1.0.dev3](https://pypi.org/project/aio-powerrise-api/0.1.0.dev3/).** Source for the broader record/command inventory, asynchronous state model, scene operation, discovery, and later product-type catalog. MIT License, copyright 2026 James Wilkinson. It is an alpha package and several claims remain unverified or conflict with live evidence.
- **Gengen — [Platinum Shade Vera plug-in](https://community.ezlo.com/t/hunter-douglas-platinum-bridge-app/187439?page=3).** Source for detailed action sequencing, room and schedule record layouts, `$psr`, date/time commands, multi-feature product behavior, and robust command queueing. The inspected v1.8 archive has SHA-256 `8e5b294d21123a82eb1861823d30c8470363fe4e46b7a5f75a4f4c0971de523c`; its Lua file declares GNU GPL v2.0, while the archive has no standalone license and its XML files lack headers. Its protocol findings are paraphrased here; copying its implementation would require a per-file license review.
- **Schwark Satyavolu — [`smartthings-hunterdouglasplatinum`](https://github.com/schwark/smartthings-hunterdouglasplatinum) and [`smartthings-edge-hunterdouglasplatinum`](https://github.com/schwark/smartthings-edge-hunterdouglasplatinum).** Long-running SmartThings integrations and protocol practice credited by A. The inspected legacy repository has a root MIT license, while three device-handler files declare Apache-2.0 and credit Allan Klein (`@allanak`) and Mike Maxwell as originating authors. Treat licensing per file; no code was copied here.
- **Sander Teunissen — [`aio-powerview-api`](https://github.com/sander76/aio-powerview-api).** Credited by A for API and architecture patterns. It targets the later PowerView family, not this Platinum wire protocol. BSD 3-Clause License, copyright 2017 Sander Teunissen.

Hunter Douglas, PowerRise, PowerView, and related product names are trademarks of their respective owner. This project is independent, unofficial, and not endorsed by Hunter Douglas.

## Compact implementation checklist

- [ ] TCP connect to port `522`
- [ ] Consume `N HunterDouglas Shade Controller<LF><CR>`
- [ ] Send bare ASCII `$dat`
- [ ] Split incoming bytes on `0a 0d`
- [ ] Strip optional `^[0-9]+ ` per record
- [ ] Preserve unknown and non-UTF-8 payloads as bytes
- [ ] Parse `$cr`, `$cs`, and `$cp` with fixed headers plus tail names
- [ ] Finish snapshot only on `$upd01-`
- [ ] Serialize all commands
- [ ] Require explicit enablement for mutating operations
- [ ] Stage `$pss` operations, wait `$done`, then `$rls`
- [ ] Treat `$act00-00-` as asynchronous action completion
- [ ] Re-run `$dat` after reconnect or uncertain completion
- [ ] Sanitize MAC and household names in logs and fixtures
