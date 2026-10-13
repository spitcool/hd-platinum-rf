<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Hunter Douglas Platinum bridge LAN protocol

Status: independently documented, incomplete, and unofficial

Last evidence review: 2026-10-13

Observed bridge: private-LAN address redacted, firmware banner `2018-HD gateway 2.18a`

This document describes the Ethernet-side protocol spoken by the discontinued Hunter Douglas Platinum bridge. It does **not** describe the proprietary 2.4 GHz over-the-air protocol between the bridge and the shades. The LAN protocol is still useful for a replacement project: the original bridge can serve as a behavioral oracle while RF captures are correlated with precise LAN commands.

All names and the bridge MAC address in the examples below are fictional. The live unit's actual MAC address and household room/shade names are intentionally not recorded here.

## Evidence labels

Protocol notes on old hardware tend to become folklore. Every claim in this document is therefore qualified by its evidence:

- **LIVE** — observed byte-for-byte on the user's bridge during a non-mutating probe on 2026-10-13.
- **N** — implemented by Aaron Taylor's [`node-hunterdouglas`](https://github.com/exPHAT/node-hunterdouglas), inspected at commit `9bb23b79ef6beb75b26885d70b5e175c8628ba77`.
- **H** — implemented by Roland Schemers's [`homebridge-hunterdouglas-platinum`](https://github.com/schemers/homebridge-hunterdouglas-platinum), version 2.1.0, inspected at commit `1bdd2cba5ef293da08bb4b6608421a306c64e83c`.
- **A** — implemented or asserted by James Wilkinson's [`aio-powerrise-api`](https://pypi.org/project/aio-powerrise-api/0.1.0.dev3/), version 0.1.0.dev3.
- **G** — implemented by Gengen's Platinum Shade Vera plug-in v1.8, published in the [Hunter Douglas Platinum Bridge App thread](https://community.ezlo.com/t/hunter-douglas-platinum-bridge-app/187439?page=3).
- **INFERRED** — a conservative interpretation supported by evidence, but not directly demonstrated.
- **UNKNOWN** — observed or source-listed, but its meaning or behavior is not established.

“Source-derived” does not mean “verified on this firmware.” In particular, no mutating command was sent during the live probe.

## Executive summary

- **LIVE:** The bridge listens on plain TCP port `522`. Of the specifically targeted ports checked, `522/tcp` was open.
- **LIVE:** The server speaks first with `N HunterDouglas Shade Controller`, where this connection used `N = 5`.
- **LIVE, N, H:** Responses are records delimited by the unusual byte sequence **LF CR** (`0a 0d`, `\n\r`), not conventional CR LF.
- **LIVE:** Sending exactly the four ASCII bytes `$dat`, with no newline or other terminator, returns a complete database/status snapshot ending in `$upd01-`.
- **LIVE:** Sending exact, delimiter-free `$dmy` after consuming the banner produced no bridge bytes during an approximately seven-second observation window. A terminal display of `$dmy` was local PTY echo, not a device response.
- **LIVE:** Most response records begin with a decimal connection number and one ASCII space. The initial capture recorded a bare firmware/version line; a later end-to-end client check returned the same text as `$firm03-...`. Treat both the connection prefix and the firmware wrapper as version-dependent.
- **N, H, G:** Requests can be sent without a line ending. **A** appends CR LF; that dialect was not tested live and should not be treated as the canonical framing.
- **H, A, G:** Shade movement is a staged operation: send one or more position commands, receive `$done` for each, then send `$rls` to release/execute them.
- **LIVE, N, H, A, G:** There is no TLS. The read-only live session had no authentication exchange; all community implementations also send mutating commands without authentication. Keep port 522 restricted to a trusted LAN.

## Network endpoint and discovery

| Property | Value | Evidence |
|---|---|---|
| Addressing | Private IPv4 address; installation-specific value redacted | LIVE |
| Control/status transport | TCP | LIVE, N, H, A, G |
| TCP port | `522` | LIVE, N, H, A, G |
| Encryption | None; cleartext | LIVE |
| Authentication | No challenge or credential step observed; none implemented by the sources | LIVE, N, H, A, G |
| Optional discovery | NetBIOS Name Service broadcast on UDP `137` | A, G |
| Reported NetBIOS name | `PlatLink-PDBU` in A; `PLATLINK-FDBU` in G | A, G; spelling unresolved |

The port statement above is deliberately narrow: it does not claim that every TCP and UDP port was exhaustively scanned.

For a production integration, prefer a DHCP reservation or explicit address. NetBIOS discovery is source-derived and has not yet been verified against this unit.

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
| `$dmy` | Dummy/keep-alive | No response observed over ~7 seconds on the live bridge | LIVE. G waits for `$ack`; A's `ping()` also waits for it, but A's periodic keep-alive treats it as fire-and-forget. For this firmware, use fire-and-forget semantics. |

The live `$dmy` probe was sent only after the banner had been consumed. The PTY echoed the characters typed by the client; raw receive monitoring showed no returned bytes. Do not mistake local terminal echo for a protocol echo or `$ack`.

Even `$dat` exposes household names and a hardware address. Treat captures as sensitive and sanitize them before publication.

## Runtime actuation commands

These commands can move physical equipment. Their formats are source-derived and were **not** sent during the live probe.

### Position one shade

Canonical form:

```text
$pssII-FF-PPP-
```

Examples with fictional IDs:

```text
$pss03-04-000-    primary feature fully closed
$pss03-04-255-    primary feature fully open
$pss03-04-128-    primary feature approximately 50%
```

H omits the final hyphen, while A and G include it; N also constructs a no-final-hyphen form. Both variants therefore have community precedent. Prefer the final hyphen for a canonical encoder, but make a decoder tolerant.

**H, A, G:** a normal position command produces `$done`. Queueing more than one `$pss` before release is supported by the clients and is how a group of shades can be staged.

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

It expects `$done`. G also identifies feature `12` as “Test.”

## Action and command responses

All examples may be preceded by the optional `N ` connection prefix.

| Record | Meaning | Evidence |
|---|---|---|
| `$done` | Command accepted/completed at the bridge-command layer; used after `$pss`, date, and time operations | H, A, G |
| `$ack` | Acknowledgement, associated with `$dmy` by G and one A code path | A, G; not returned by the live bridge within ~7 seconds |
| `$errorNN-` | Error with two-digit code | A; meanings of codes `00`–`09` are unknown |
| `$act01-00-` | Start of an action | G |
| `$act02-RR-...` | Action in room `RR` | G |
| `$act00-00-` | End of action | H, A, G |

Action events are not correlated to a request ID. A client that shares the bridge with the legacy app or another controller must be prepared to see action events that it did not initiate.

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

For the ordinary primary feature (`04`), all implementations use a raw range of 0–255:

```text
wire = round(percent * 255 / 100)
percent = round(wire * 100 / 255)
```

The source convention is `000 = closed` and `255 = open` for an ordinary bottom-up shade. Feature semantics vary by room/product type, so this conversion alone is insufficient for dual-rail and vane products.

### Known feature codes

| Code | Source-derived meaning | Notes |
|---|---|---|
| `01` | Sync status/operation | Seen in G's common feature table; command procedure not established |
| `04` | Primary rail, bottom-up motion, or traverse | LIVE for state; N, H, A, G for control |
| `07` | Vane/tilt or Luminette “close right” | A, G |
| `10` | Intermediate preset/stop | A and G disagree on exact semantics/value |
| `12` | Test/jog | A, G |
| `18` | Middle/top-down rail | H, G |
| `19` | Reverse tilt or Luminette “close left” | A, G |

### Room/product type map

`BB` in `$cr` selects the product family and therefore the valid features. This table is entirely source-derived; only the existence and shape of `BB` were verified live.

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
| `09` | Pirouette Window Shadings | G lists only `04`; A classifies it as tilt-capable. Unresolved. |
| `10` | Silhouette/Nantucket Window Shadings | `04` primary, `07` vane |
| `11` | Vignette Modern Roman traditional | `04` |
| `12` | Vignette Modern Roman tiered | `04` |
| `13` | Vignette tiered top-down/bottom-up | `04` bottom rail, `18` middle rail |
| `14` | Skyline Gliding Window Panels | `04` traverse |
| `15` | Pleated Shades | `04` |
| `16` | Alustra Woven Textures Roman | `04` |
| `17` | Solera Soft Shades | `04` |
| `18` | Design Studio Roman | `04` |
| `21` | Silhouette/Nantucket A Deux room-darkening variant | Listed by A; A's own type/tilt classifications are inconsistent, so calibrate |
| `22` | Provenance Woven Wood standard | Listed by A; feature presumed `04` |
| `23` | Provenance independently operable liner | Listed by A; multi-feature behavior unresolved |
| `24` | Provenance vertical drapery | Listed by A; feature presumed `04` |
| `25` | Provenance top-down/bottom-up | Listed by A as secondary-position capable; likely `04`/`18`, not verified |
| `30` | Alustra independently operated liner | Listed by A; multi-feature behavior unresolved |

Do not infer capability solely from a product name. Use the room type, observe the official application, and capture known-good commands before enabling secondary or vane features.

### Composite UI mappings are not protocol fields

G maps multi-feature products onto a single 0–100 UI slider. That mapping is an integration policy, not part of the wire protocol:

- For types `02` and `13`, G uses 0–50 for feature `18` and 50–100 for feature `04`; 50 represents fully closed.
- For Luminette types `06` and `08`, G divides a single slider among traverse and the two vane directions.
- A instead exposes primary position and tilt as separate concepts, and maps bidirectional tilt across features `19` and `07`.

A replacement API should expose raw feature channels first. A later Control4 layer can choose a user-facing composite model without baking that policy into the transport.

## Configuration-changing and hazardous commands

The following commands are present in source code but were not used in the live probe. They can change bridge configuration, pairing, schedules, or firmware state. Do not issue them while investigating a fragile bridge unless a recoverable test plan exists.

### Formats described by sources

| Command | Source-derived purpose | Expected response |
|---|---|---|
| `$sdtMM-DD-D-YYYY-` | Set bridge date; weekday `1 = Sunday` through `7 = Saturday` | `$done` in G |
| `$stmHH-MM-SS-` | Set bridge time | `$done` in G |
| `$mrpSS-RR-FF-PPP-00-` | Set a scene's room position | A; response not established |
| `$smlSS-II-LL-` | Link/unlink a shade in a scene | A; response not established |
| `$LEDlPPP-` | Set LED brightness | A token and matching response family; response not established |

G automatically set the date and time when it connected. A new controller should not do this by default; it is an unnecessary state change unless schedule execution depends on it.

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
- **Trailing command hyphen:** both forms exist in source. `$dat` without it is live-proven; `$pss` was not live-tested.
- **`$dmy` response:** the live bridge was silent for approximately seven seconds. Some source paths wait for `$ack`; another treats it as fire-and-forget. Do not block the command queue waiting for `$ack` on firmware 2.18a.
- **`$rls` response:** treat `$act...` as an asynchronous action lifecycle, not as a uniquely correlated reply.
- **State from handheld RF remotes:** G's author reported that the integration could observe actions from the mobile app but not necessarily from handheld remotes. The legacy shades/bridge may not provide true two-way position feedback for all control paths.
- **Concurrent clients:** source authors serialize work and community reports describe the bridge as sensitive to simultaneous activity. The exact connection limit is unknown.
- **Snapshot variants:** live captures produced both a bare version string and a `$firm03-...` record, plus `$set006-` and an opaque `$ct`; source fixtures often omit or reinterpret these.

## Open questions and safe next captures

The following should remain explicitly unresolved until captured:

1. Meaning and structure of the 24-byte live `$ct...$` payload.
2. Meaning of `$set006-`.
3. Whether `$dmy` ever emits a delayed `$ack`, and whether behavior changes with request terminator or firmware. The current bare-command capture was silent for ~7 seconds.
4. Which request endings are accepted for commands other than `$dat`.
5. Exact `$pss` → `$done` → `$rls` → `$act` timing and whether all events appear on this firmware.
6. Error-code meanings for `$errorNN-`.
7. Scene and schedule record layouts from this specific bridge configuration.
8. Feature `07`, `18`, and `19` behavior for the installed products.
9. Whether an RF handheld action causes an unsolicited `$cp` or any LAN event.
10. Connection-number allocation, wraparound, idle timeout, and simultaneous-client limit.
11. The actual NetBIOS name advertised by this unit.

Safe capture order:

1. Reconnect and record the banner plus raw byte timing.
2. Repeat exact bare `$dat`; compare order and opaque fields across connections.
3. Test `$dmy` on an otherwise idle connection and wait without sending follow-up data.
4. Capture traffic from the legacy mobile app while it performs a read-only refresh.
5. Only with explicit approval, choose one known shade and one reversible movement, capture both LAN and 2.4 GHz RF, and immediately reconcile with `$dat`.

Avoid room/shade database commands and the bootloader token during discovery.

## Using the LAN protocol as an RF oracle

The LAN IDs are bridge database indexes, not yet proven to be RF addresses. Nevertheless, synchronized captures can establish a mapping:

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
- Treat the bridge as irreplaceable: avoid bootloader, pairing, delete, rename, schedule, date/time, and LED writes until there is a recovery plan.
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
