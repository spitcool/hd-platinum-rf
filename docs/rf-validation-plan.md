<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Next tests toward complete Platinum RF control

The next decisive test is **one native Jog of an already paired shade**, with
the operator watching. Unattended tests established reception of synthesized
native packets on all three frequencies. They have not established shade
acceptance. Preserve the existing binding for this comparison; new enrollment
would introduce another unknown.

The operator asked to be consulted before tests requiring movement observation,
button presses or wiring changes and is away for the night. No such test is
queued. Offline analysis, software checks and preparation can continue. Named
targets, installation identities, artifacts and exact resume state belong in
the ignored private handoff.

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
| Jog / identify, feature 12 | Original builders and captures; fictional native train received on all three channels | Existing shade acceptance, repeatability, public backend integration |
| Primary position, feature 04 | Original bodies; observed app-driven movement through 2440 MHz route | Native hopping position scheduler; repeatability by route, target and product |
| Sync / enrollment, feature 01 | Original bodies; existing-target resync observed | Full native enrollment train, fresh binding, cancellation and subsequent control |
| Secondary rail, feature 18 | APK product/control mapping | Original RF encoding/schedule and physical rail behavior |
| Vane / opposing tilt, features 07 and 19 | APK/client mappings | Exact values, original RF encoding and physical behavior |
| Feature 10 / preset / stop | Conflicting client interpretations | Determine behavior on the relevant product before implementation |
| Handheld up/down and button release | Captured native bodies and original-code checks | Hopping schedule, held/release behavior and group selection |
| Room / multiple-shade control | Sequential per-target primary-position dispatch | Physical selection, ordering and partial failure; combined-mask/multi-command RF remains separate |
| Scenes and schedules | Source-derived LAN records and parser/preservation support | Original semantics, RF fan-out, implementation and client/physical tests |
| Removal, reassignment and reset | Database CRUD subset | Determine whether an operation changes shade memory; establish recovery before destructive tests |

The 25-entry [product catalog](../src/hd_platinum/products.py) describes app
metadata. It does not qualify all products or their RF features. Mark hardware
that is unavailable for observation as untested.

1. **Freeze the transport and prepare the exact existing-target test.**
   Preserve image/library hashes, original flash backup, update receipts and
   receiver reports. Recheck matched versions on the next opening, including
   after power cycling: the FPGA is in RAM and needs the verified 0.16.0 image
   again. Do not reuse an old FPGA fallback. Generate a native Jog waveform for
   the exact saved identity and one-hot mask. Compare its main, alternate and
   tail bodies with the successful original reference, then independently
   decode the full written IQ. Preserve the tested shaping and channel rotation.
   Initial channel, alternation state and phase packet counts remain explicit
   assumptions. If saved Jog permission is disabled, use an explicit one-shot
   grant for that target; a Sync grant or product code does not authorize Jog.

2. **Observe one existing-binding native Jog.**
   Ask whether the operator is ready, then confirm the target and topology.
   To establish direct-to-shade operation, the original bridge and repeaters
   must be off; changing their power requires the operator. Retain the reviewed
   antenna arrangement unless a change is needed and confirmed. Send one bounded
   Jog while the DK records expected packets. Record whether the intended shade
   jogged and whether another shade moved. Success needs both correct RF and
   the physical observation. Do not automatically repeat a failed trial. If a
   fresh original-bridge control also fails on the existing binding, resolve
   that baseline before blaming the emulator: original success has previously
   been intermittent.

3. **Validate primary position and distinguish the two RF routes.**
   Implement a native position event planner with original per-packet hopping
   across command/followup phases; do not substitute the older sequential
   backend. Check original-code vectors, written IQ and independent reception
   before a watched trial. On a proven target, test an intermediate position
   and endpoints with that product's observed direction and rail meaning.
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
   Begin with available hardware: feature 18 applies to product codes 2, 13 and
   25; features 7/19 to 6 and 8; feature 7 also to 9 and 10. Capture the original
   app feature/value request, execute its original RF builder and compare
   transmitted phases. Keep raw features separate from composite UI sliders.
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

The first session back should cover the existing-binding Jog comparison and,
if successful, a small primary-position comparison. Enrollment and remaining
features are subsequent controlled sessions, not a long unattended sequence
of shade commands.
