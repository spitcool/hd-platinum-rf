<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Next tests toward complete Platinum RF control

**One watched native Jog of an already paired shade succeeded on 2026-10-25**,
with the original bridge and all repeaters off. The operator observed the
intended shade jog and no other shade move. This establishes one direct-native
acceptance result; repeatability remains unproven. Preserve that binding for
the next comparisons. The native primary-position scheduler and written-IQ
checks are complete. A fictional position train passed independent RF reception,
but the first watched raw-128 trial produced **no observed movement**, including
no movement of another shade. An explicitly requested repeat after moving
closer produced motion: the sole moving top rail lowered fully, changing the
window from fully covered to fully exposed; no other shade moved. The bottom
rail is fixed. **This is an observed native motion response, not intermediate-
position accuracy or a half-travel result.** Subsequent watched feature-4
requests established two endpoint responses on this same single-controllable-
top-rail shade: raw 255 raised the top rail to cover the window, and raw 0
lowered it to expose the window. Neither moved another shade.

Tests requiring movement observation, button presses or wiring changes need
current operator readiness. The native position trials and their RF audits
are complete. An original-app comparison captured initialization and inventory
traffic but no position/release request despite the reported slider gesture.
Its continuous RF recording yielded no decoded Platinum packets. After a full
app restart and a fresh connection, the app's "bottom rail" control sent
feature 4/value 134 and moved the physical
top rail roughly halfway; its feature-18/value-126 "middle rail" action had
no reported effect. Both commands arrived after that RF window ended.
A subsequent feature-4/value-191 request and release occurred inside a
continuous **60-second recording** and moved the same top rail from roughly
halfway to roughly three-quarters covered, with no other shade moving.
The command-window searches recovered **no CRC-valid native 2 Mbps or
2440 MHz / 250 kbps packets** for that raw-191 transaction. A later narrow
2452 MHz capture accompanied a feature-4/value-127 request and another
roughly-halfway result. It recovered **63 native packets** whose command and
followup bodies match the primary-position planner. Sparse reception leaves
the complete phase timing and packet counts unmeasured. Improve independent
reception before changing native encoding or timing, or attributing the
raw-128 result to a specific cause. Named targets, installation identities,
artifacts and exact resume state belong in the ignored private handoff.

The primary planner matched all **1,374 original-code packet events** across
18 cases. All **9,000 packets** in each full fictional and existing-target
written waveform independently decoded with correct bodies and CRCs. The full
local **356-test suite** and package build passed. Five finite position trials
then used the matched transport and fresh fixed-channel receiver sessions:

| Position trial | Exact CRC-valid / expected at 2452 MHz | Bad CRC | Absent records | Result |
| --- | ---: | ---: | ---: | --- |
| Fictional identity, raw 128 | 2,839 / 3,000 | 60 | 101 | First and last expected packets received; no physical target claim |
| Existing binding, raw 128 | 2,753 / 3,000 | 9 | 238 | Operator observed no movement and no other shade moving |
| Requested raw-128 repeat after moving closer | 2,703 / 3,000 | 60 aligned + 1 unassigned | 237 | Moving top rail lowered fully, exposing the window; no other shade moved |
| Existing binding, raw 255 | 2,916 / 3,000 | 17 aligned + 1 unassigned | 67 | Top rail rose fully, covering the window; no other shade moved |
| Existing binding, raw 0 | 2,666 / 3,000 | 71 aligned + 1 unassigned | 263 | Top rail lowered fully, exposing the window; no other shade moved |

All five recordings had no buffer drops. Unassigned bad-CRC records
did not align with the expected schedule and are excluded from slot counts.
The raw-0 recording has two possible absolute schedule offsets, one channel
slot apart; its packet totals and relative timing agree under both.
Independent reception establishes
the transmitted packets, not acceptance by the shade. The first real-target
negative observation is retained separately from the repeat's endpoint motion. See the
[position conformance record](protocol-conformance.md#native-primary-position-trials).

Preparation resumed on **2026-10-25**. The exact existing-target Jog waveform
has been generated and all **9,000 written packets** independently decoded,
with correct bodies and CRCs and **3,000 packets per channel**. The unchanged
planner also reproduced the previously receiver-tested fictional waveform byte
for byte. Initial channel, alternation state and phase counts remain the
explicit assumptions below.

Two existing-target attempts retained identical IQ and RF settings, each with
a fresh receiver session and its own consumed-attempt receipt:

| Attempt | Exact CRC-valid / expected at 2452 MHz | Bad CRC | Absent records | Physical observation |
| --- | ---: | ---: | ---: | --- |
| First | 584 / 3,000 | 572 | 1,844 | Missed; result unknown |
| Explicitly requested repeat | 2,662 / 3,000 | 177 | 161 | Intended shade jogged; no other shade moved |

Both recordings include held and tail phases with unique schedule alignment.
The successful trial recovered the first and last expected channel packets;
its fitted same-channel interval was **601.496209 microseconds**, with maximum
timing residual **0.597 microseconds**. Reception has gaps, and its variation
between attempts has no established cause. All radio sessions closed; the DK
finished and halted with no buffer drops. Saved bindings, grants and the
repeater-route sequence remained unchanged. See the
[watched-trial record](protocol-conformance.md#watched-existing-binding-native-jog).

The [conformance report](protocol-conformance.md#matched-firmware-comparison)
contains the measurements. The working comparison used a private patched
libbladeRF build, official FX3 firmware **2.6.0**, and volatile xA4 FPGA
**0.16.0**. The same 1.8045-second waveform was transmitted once per receiver
channel with unchanged RF settings:

| DK frequency | Exact CRC-valid packets / expected slots | Bad-CRC records | Coverage |
| --- | ---: | ---: | --- |
| 2433 MHz | 2,391 / 3,000 | 32 | First through last expected packet |
| 2452 MHz | 2,682 / 3,000 | 48 | First through last expected packet |
| 2471 MHz | 2,768 / 3,000 | 15 | First through last expected packet |

Every recording contains held and tail phases. Same-channel spacing is about
**601.496 microseconds**, within 6.3 ppm of nominal 601.5 microseconds. The
earlier timing stretch and USB timeout did not recur. These separate recordings
contain reception gaps; they are not lossless simultaneous measurements of all
three channels. All radio sessions closed and the DK stopped and was halted.
Repeating these identical checks is unnecessary without a new change or failure.

The [libbladeRF patch and regression harness](../tools/libbladerf_sc8/README.md)
are committed locally. The system library and public live backends have not
been switched to the private native transport. The older public 2 Mbps backend
sends whole trains sequentially by channel; it is not the per-packet hopping
implementation tested here.

| Transaction family | Evidence available | Remaining validation |
| --- | --- | --- |
| Jog / identify, feature 12 | Original builders and captures; fictional native train received on all three channels; one watched existing-binding direct-native success | Repeatability, additional targets/products, public backend integration |
| Primary position, feature 04 | Original scheduler matched across 18 cases/1,374 events; written IQ and independent RF reception; direct raw-255/raw-0 endpoints; original-app raw-134/raw-191 intermediate observations on a single moving top rail | First direct raw-128 trial had no movement; repeat opened fully. Recover the successful original action's RF for comparison, then establish direct intermediate behavior, repeatability and other targets/products |
| Sync / enrollment, feature 01 | Original bodies; existing-target resync observed | Full native enrollment train, fresh binding, cancellation and subsequent control |
| Secondary rail, decimal feature 18 (`0x12`) | APK mapping; original held/followup bodies `0x6D`/`0x32`; 48 builder rows and 18 scheduler cases/1,374 events | Offline public planner/written IQ, independent RF reception and physical rail behavior; no secondary control enabled |
| Vane / opposing tilt, features 07 and 19 | APK/client mappings | Exact values, original RF encoding and physical behavior |
| Feature 10 / preset / stop | Conflicting client interpretations | Determine behavior on the relevant product before implementation |
| Handheld up/down and button release | Captured native bodies and original-code checks | Hopping schedule, held/release behavior and group selection |
| Room / multiple-shade control | Sequential per-target primary-position dispatch | Physical selection, ordering and partial failure; combined-mask/multi-command RF remains separate |
| Scenes and schedules | Source-derived LAN records and parser/preservation support | Original semantics, RF fan-out, implementation and client/physical tests |
| Removal, reassignment and reset | Database CRUD subset | Determine whether an operation changes shade memory; establish recovery before destructive tests |

The 25-entry [product catalog](../src/hd_platinum/products.py) describes app
metadata. It does not qualify all products or their RF features. Mark hardware
that is unavailable for observation as untested.

1. **Preserve the matched transport and reviewed position inputs.**
   Preserve image/library hashes, original flash backup, update receipts and
   receiver reports. Recheck matched versions on the next opening, including
   after power cycling: the FPGA is in RAM and needs the verified 0.16.0 image
   again. Do not reuse an old FPGA fallback. The position waveforms are already
   generated and fully decoded. Preserve their tested shaping, channel rotation,
   exact target binding and raw value. Initial channel and phase packet counts
   remain explicit assumptions. Use a fresh consumed-attempt receipt and bounded
   receiver session for each explicitly requested trial. A Sync or Jog grant
   does not authorize position control; a temporary position grant must not
   change saved permissions.

2. **Resolve the raw-value response on the observed top-down shade.**
   The first raw-128 trial had correct independently received packets but no
   observed movement. Its explicitly requested repeat after moving closer
   lowered the sole moving top rail from fully covered to fully exposed.
   Raw 128 therefore has not demonstrated an intermediate position. The fixed
   bottom rail and moving top rail are physical observations; the saved product
   code's dual-slider UI does not override them. Raw 255 subsequently covered
   the window and raw 0 exposed it. Original-app transactions now establish
   feature 4/value 134 with roughly halfway coverage and feature 4/value 191
   with roughly three-quarters coverage. The app calls that control "bottom
   rail"; the actual moving rail is the top rail. Its feature-18/value-126
   "middle rail" request produced no observed movement. The operator also
   reports intermediate control with the handheld/wall control.
   The raw-191 request and release fell inside a continuous 60-second capture,
   but bounded native and 250 kbps searches recovered no source packets.
   A subsequent narrow 2452 MHz recording, with the receive pad removed and
   DC block retained, captured an original-app feature-4/value-127 request
   and roughly-halfway coverage. Blind decoding recovered 63 native packets:
   three command bodies and 60 followup bodies, all retaining raw 127 and
   matching the reviewed primary-position planner. Reception remains too
   sparse to establish the command phase's onset, total counts or complete
   schedule; only one channel was recorded. Improve independent reception
   before changing the transmission timing. Neither these matching bytes nor
   retained decoder controls explain the direct raw-128 endpoint response.
   Do not change value encoding or room metadata from that observation alone.
   Confirm readiness, target and topology before each bounded trial; for a
   direct-to-shade claim, the original bridge and repeaters must be off. Record
   moving-rail direction, final coverage and unrelated shade motion. Raw 128 is
   near the middle of the byte range, not a guarantee of half travel. Endpoint
   responses do not establish the intermediate mapping or repeatability.
   Preserve each negative result and never hide it with automatic retries.
   If a fresh original-bridge control also fails on the binding, resolve that
   baseline before attributing the result to the emulator.

3. **Establish repeatability and distinguish the two RF routes.**
   Native Jog has one watched success; its first attempt's observation was
   missed, so that attempt is neither another success nor a failure. Retain
   individual watched Jog and position outcomes as separate repeatability
   evidence. Correct RF plus the physical observation are both required.
   Do not substitute the older sequential-channel native backend for the
   reviewed per-packet hopping plan.
   Separately regress the app's TCP 522 → 250 kbps → repeater route after the
   firmware update, with one repeater on and original bridge off, recording
   later native output. A repeater LED or matching later 2440 MHz packet does
   not establish native shade output. Keep success records separate by route.
   Establish repeatability with individually observed commands, retaining
   failures rather than hiding them with retries.

4. **Establish fresh enrollment after existing control is repeatable.**
   Preserve inventory and old-binding facts. First establish a successful
   original-bridge procedure for a genuinely new identity on the chosen shade;
   previous new-identity attempts also failed with the original bridge. Follow
   the exact app/manual instructions and record one deliberate manual-button
   action. Do not infer a factory reset or repeated presses are required.
   Database creation/deletion and Sync acknowledgement are not proof of a
   physical binding change.
   Prepare native Sync as its own command family. The inspected Android app
   schedules a 15-second countdown, matching the operator's observed app flow;
   original-code evidence suggests a nominal 15-second held signal plus roughly
   0.3-second tail. Replaying the two-second Jog fixture is not
   enrollment. Qualify long-duration streaming and onset/tail timing first
   with fictional identities. The DK's three-second/4,096-record limit needs
   selected windows or a separately reviewed longer recorder, not silently
   widened limits. After watched enrollment, issue an ordinary Jog or position
   command using the **new identity** and observe the result. Check old-binding
   behavior and unrelated targets separately. An acknowledgement jog alone is
   insufficient. Enrollment need not wait for every secondary product family.

5. **Add product-specific controls from original evidence.**
   Decimal feature 18 (`0x12`) applies to product codes 2, 13 and 25. Its original
   builder and bounded scheduler now establish held code `0x6D`, followup code
   `0x32` and unchanged requested values 0/128/255. In the tested native context
   with the queue-mode bit clear, it shares primary position's fixed phase
   bodies and per-packet channel rotation, without Jog alternation or periodic
   refresh. Exact phase packet counts and physical rail behavior remain unproven.
   Review the shared offline planner design before adding secondary synthesis;
   preserve primary APIs and grants. No secondary transmitter or permission is
   enabled. The app labels primary as bottom rail and secondary as middle/top-down,
   but that static mapping does not establish the installed mechanism. The
   operator identifies the current target as top-down-only with a fixed bottom
   rail; it must not be described as a physically dual-rail shade.
   Features 7/19 apply to products 6 and 8; feature 7 also to 9 and 10. Capture
   each original app feature/value request, execute its RF builder and compare
   phases. Keep raw features separate from composite UI sliders.
   Validate intermediate values, endpoints, direction and rail/vane interactions
   before enabling each feature. Feature 10 has conflicting preset/stop
   interpretations and must not become a generic emergency stop. LAN `$rls`
   releases a staged transaction; native button-release/tail packets do not yet
   establish stop-at-current-position behavior. Capture `$stps`/Sync cancellation
   separately from ordinary motion commands.

6. **Validate selection, aggregation and persistence.**
   Test two known targets individually before room/group operation. Room `$psr`
   currently dispatches individual primary-position commands sequentially;
   verify all-target prevalidation, ordering and partial-failure reporting
   without claiming atomic or simultaneous motion. Handheld groups 1–4/all
   are distinct from room shade slots 1–8. Combined masks and multi-command
   bridge packets need original references, including command count versus
   transaction counter, duplicate behavior and wrap. Preserve the durable
   sequence store. Determine whether scene recall expands to individual/room
   commands before implementing it. Schedules must invoke a qualified command
   path and need clock/persistence tests. Metadata deletion, physical unlearning
   and factory reset are separate operations; prepare recovery before any
   destructive test.

7. **Integrate qualified commands into the emulator and clients.**
   Add native transport explicitly, with matched library/firmware checks,
   bounded airtime, serialization, operation grants, hashes and receipts.
   Do not silently fall back to the sequential-channel backend or another RF
   route after uncertain failure. Test the original app and plain TCP 522 for
   staging, release, action lifecycle, disconnects, reconnects and persistence.
   Verify entering a new room without restarting the app; that refresh issue
   remains open. Android APK analysis is not Android-device interoperability.
   Control4 driver testing is deferred as requested, using the same TCP
   interface. Continue reporting positions as requested state unless actual
   feedback is independently established.

8. **Promote support only with a complete evidence record.**
   For each operation/product/route, retain LAN bytes, target mapping,
   source/firmware versions, expected packet ledger, waveform hash, independent
   reception, physical observation and final inventory state. Record gaps and
   failures. Distinguish source-verified, receiver-tested, shade-tested and
   repeatable: a software acknowledgement or USB success is not shade success.
   Run the full local suite and package build before pushing implementation
   changes. Keep private identities, original firmware and raw RF outside Git.

The existing-binding Jog milestone has one observed success. Native position
has completed source, written-IQ and fictional RF checks, but its first watched
raw-128 trial had no movement. The requested repeat produced full opening on a
top-down-only shade, not a demonstrated intermediate position. Raw 255 and raw 0
then produced covered and exposed endpoints. Original-app primary requests
have now produced intermediate observations at raw 134, 191 and 127. The latest
narrow raw-127 capture recovered matching native command/followup bodies, but
its sparse reception does not establish the complete original schedule. The
next comparison requires better reception to measure phase timing and counts.
Enrollment and remaining features belong in subsequent controlled sessions,
not an unattended command sequence.
