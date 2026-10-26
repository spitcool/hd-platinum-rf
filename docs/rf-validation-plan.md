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

Later direct-native requests reached intermediate positions at raw 127, 129
and 191. **The fourth raw-128 trial moved from the operator's 129 mark to the
128 mark**, with no other shade moving. It reused the exact earlier raw-128
waveform, timing and gain; the independent receiver recovered 2,424 matching
valid packets. This establishes one watched raw-128 intermediate success.
The earlier no-motion and full-opening results remain unexplained, and general
repeatability remains unqualified.

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
| Primary position, feature 04 | Original scheduler matched across 18 cases/1,374 events; written IQ and independent RF reception; direct raw-255/raw-0 endpoints and raw-127/raw-128/raw-129/raw-191 intermediate results; original-app intermediate observations and matching native RF bodies | Raw 128 now has one precise-mark success following no movement, full opening and no movement. Establish repeatability while preserving those unexplained outcomes; then validate other targets/products |
| Sync / enrollment, feature 01 | Original bodies; existing-target resync observed | Full native enrollment train, fresh binding, cancellation and subsequent control |
| Secondary rail, decimal feature 18 (`0x12`) | APK mapping; original `0x6D`/`0x32` bodies; watched original-app and direct-synthetic raw-63 coupled movement on a confirmed two-moving-rail shade, with independent RF reception | Repeatability, additional values and NiceRF hardware qualification |
| Vane / opposing tilt, features 07 and 19 | APK/client mappings | Exact values, original RF encoding and physical behavior |
| Feature 10 / preset / stop | Conflicting client interpretations | Determine behavior on the relevant product before implementation |
| Handheld up/down and button release | Captured native bodies and original-code checks | Hopping schedule, held/release behavior and group selection |
| Room / multiple-shade control | Sequential per-target primary-position dispatch | Physical selection, ordering and partial failure; combined-mask/multi-command RF remains separate |
| Scenes and schedules | Source-derived LAN records and parser/preservation support | Original semantics, RF fan-out, implementation and client/physical tests |
| Removal, reassignment and reset | Database CRUD subset | Determine whether an operation changes shade memory; establish recovery before destructive tests |

The 25-entry [product catalog](../src/hd_platinum/products.py) describes app
metadata. It does not qualify all products or their RF features. Mark hardware
that is unavailable for observation as untested.

A subsequent trial targeted a different, operator-confirmed top-down/bottom-up
shade with both moving rails initially at the top and the window exposed.
One native **feature 4/value 128** request produced **no visible movement**.
The independent channel-52 receiver captured 2,938 matching CRC-valid packets
(2,449 held and 489 followup); both radio sessions closed cleanly. This proves
transmission and nearby reception, not reception or acceptance by that shade.
Subsequent watched original-app references establish the following behavior:

| Original-app action | Physical response on the confirmed dual-rail shade |
| --- | --- |
| Feature 4/raw 127, from both rails at the top | Bottom rail lowered halfway; top rail stayed at the top |
| Feature 18/raw 63, from top at top and bottom halfway | Bottom rail lowered fully first, then top rail lowered roughly one-quarter |
| Bottom-rail halfway request from that secondary configuration | Top rail rose to the top first, then bottom rail rose halfway |

No other shade moved in these three references. The first two closed LAN
traces each contain one selected-feature request and release. Their native RF
captures independently decode the corresponding `0x50`/`0x32` and
`0x6D`/`0x32` bodies, respectively. The app also indicated the companion rail
change. Thus these controls select coupled operating modes on this installation;
they are not independently achievable rail coordinates. Do not generate an
extra companion command or transfer this behavior to a single-rail shade.
The reason for the earlier synthetic raw-128 no-motion result remains unknown.

A subsequent **single direct-synthetic feature-18/raw-63** request reproduced
the original coupled result: bottom rail fully down, then top rail roughly
one-quarter down, with no other shade moving. The independent DK received
2,990 matching CRC-valid packets (2,491 held and 499 followup), three CRC-bad
records and no unexpected valid bodies. Both sessions closed cleanly. This
qualifies one SDR trial on that existing binding; it does not qualify the
unassembled NiceRF hardware. The subsequent matched **feature-4/raw-127**
synthetic reverse request produced **no motion**, despite 2,976 exact valid
packets at the independent DK (2,489 held, 487 followup). All 26 RF/lifecycle
checks passed and the source closed cleanly. At that checkpoint, synthetic
primary values 128 and 127 had failed despite original-primary and
synthetic-secondary successes. Those failures motivated the full-transmission
investigation below; later outcomes, including a successful primary request,
are retained separately. Received bodies alone do not resolve the discrepancy.

Offline review found a concrete difference in burst structure. The original
builder flushes the TX FIFO, writes its five-byte payload and enables payload
reuse; the original scheduler holds CE around a software delay. Earlier
instruction fixtures stopped before those peripheral operations, so their
event counts never established one transmitted packet per trigger. Successful
original primary recordings contain distinct adjacent packets about 44.5 µs
apart within a continuous carrier burst; secondary recordings also contain
such pairs. The current synthesis emits one 88-bit packet per burst. Ordinary
single-packet envelope duration and nominal bit rate match closely. None of
these findings proves why synthetic primary control failed, particularly
because synthetic secondary succeeded with the same single-packet structure.

A historical wideband original-primary capture also contains a preceding
2440 MHz / 250 kbps command/control stage. The recent 8 MS/s recordings exclude
that frequency. Its necessity for this target remains unproven; do not add a
prelude, alter the timing grid or change modulation settings as an established
fix. Freeze measured differences and vary one justified factor in a bounded
diagnostic before changing the firmware's qualification claims.

One experimental raw-127 trial added a second identical packet to 170 of the
9,000 existing trigger slots, with a measured one-zero-symbol interval and
continuous burst envelope. The remaining 8,830 slots were byte-identical to
the unsuccessful baseline; value, power, timing grid and total duration stayed
unchanged. It also produced **no movement**. All 9,170 written packets passed
independent decoding/CRC checks, but the DK's receive-rearm interval prevented
it from observing all 56 second members on its channel. It received 2,990 valid
first-member packets and one CRC-bad record, with clean lifecycle checks. This
does not qualify the experimental cadence as a fix or prove actual paired RF
completeness.

A subsequent **original-bridge feature-4/raw-127** request again succeeded:
top rail to the top, then bottom rail up to roughly halfway, with no other
shade moving. Its six-second 48 MS/s recording covers 2440 MHz and all three
native channels at once. All 288 million samples were retained with no
metadata gaps, overruns or error-status blocks; the receive session and bridge
connection closed cleanly. Full-band decoding is in progress. Capture
continuity and the watched movement establish a usable original reference;
they do not yet identify which RF difference explains the synthetic failures.

A later standard native **feature-4/raw-191** request from the confirmed
original-primary position (top at the top, bottom halfway) also produced no
movement. The DK received 2,989 matching valid packets (2,492 held and 497
followup), three aligned CRC-bad records, and no unexpected or unassigned
records. Eight channel-52 slots were unobserved; all 26 RF/lifecycle checks
passed. Changing the requested value in this state did not establish native
primary control on the dual-rail target.

The first standard native **feature-4/raw-127** trial on the separately bound,
single-moving-bottom-rail shade also produced no movement from fully open.
The DK received 2,988 matching valid packets (2,490 held and 498 followup),
four CRC-bad records and no unexpected valid bodies. Ten planned channel-52
slots were unobserved; two late CRC-bad records remained unassigned. All 26
RF/lifecycle checks passed. This extends the unresolved physical-acceptance
problem beyond the dual-rail target. Repeat the previously successful
secondary-63 request from its original starting state before attributing the
failure specifically to primary control or changing waveform parameters.

An exact repeat of the previously successful **secondary-63** waveform, from
the same top-at-top/bottom-halfway starting state, then produced **no movement**.
The DK received 2,987 matching valid packets (2,490 held and 497 followup), four
CRC-bad records, ten unobserved slots and one late unassigned bad record; all
26 RF/lifecycle checks passed. This result rules out treating the observed
failures as a demonstrated primary-only problem. Preserve both secondary
outcomes and check repeatability of RF delivery before changing command
encoding or claiming a required extra protocol stage.

A third transmission of that **unchanged secondary-63 waveform** succeeded:
bottom fully down, then top roughly one-quarter down, with no other shade
moving. The DK received 2,918 matching valid packets (2,445 held, 473 followup),
30 CRC-bad records and no unexpected valid bodies. Fifty-five planned slots
were unobserved; three bad records remained unassigned. All 26 RF/lifecycle
checks passed. The operator clarified that the DK remained roughly three feet
from the shade because of its short USB cable; its repositioning did not
establish a closer or shade-side measurement. Preserve the success–failure–
success sequence without attributing it to receiver placement, power or a
protocol change.

The next **unchanged native primary-127 reverse request succeeded physically**:
top rail to the top, then bottom rail up to halfway, with no other shade moving.
The source completed one finite submission and closed, but the independent DK
captured **zero records** in its completed five-second window. Its control
profile and shutdown checks passed; received-packet and timing qualification
therefore failed. This is an operator-observed primary response, with no
independent RF recording for that attempt. It does not erase the earlier
failures or establish reliable operation.

The controlled transmitter-gain comparison then retained the original
bottom-up shade's primary-127 packet data and timing while increasing device
gain from 50 to 56. The matched driver read back DSA −10 instead of −16 dB;
this is a relative hardware setting, not a calibrated radiated-power
measurement. After the operator reconnected the relocated DK, the shade
lowered from fully open to roughly halfway with no other shade moving.
The DK recorded 2,798 matching valid packets (2,344 held, 454 followup) and
103 aligned CRC-bad records; 99 planned slots were unobserved, with no
unexpected valid or unassigned records. All 31 RF/lifecycle/power checks
passed, and the original gain-50 artifact remained unchanged. This supports
continued testing of signal margin but does not prove power caused the earlier
failure.

Two subsequent requests at the same gain established this bottom-up shade's
endpoints: **raw 0 lowered the rail fully and covered the window; raw 255
raised it fully and exposed the window**. No other shade moved in either test.
The raw-0 recording contained 2,844 matching valid packets, 82 aligned CRC-bad
records and 74 unobserved slots; raw 255 contained 2,748 matching valid packets,
134 aligned CRC-bad records and 118 unobserved slots. Both passed all 31
RF/lifecycle/power checks. These directions are opposite to the observed
single-moving-top-rail shade, so endpoint mapping must remain explicit per
shade.

The unchanged raw-127/gain-56 repeat from that confirmed open position
produced **no movement**, including no other shade moving. Its recording
contained 2,650 matching valid packets, 199 aligned CRC-bad records and 151
unobserved slots; all 31 RF/lifecycle/power checks passed. The shade remained
fully open. Thus gain 56 has both a successful and a failed raw-127 request
from the same observed starting position.

The final single raw-127 comparison raised device gain from 56 to 60
(DSA −10 to −6 dB), keeping the waveform, timing and observed open baseline
unchanged. The operator observed the rail lower roughly halfway, with no
other shade moving. The DK recovered **2,986 matching valid packets**
(2,486 held and 500 followup), four aligned CRC-bad records and three
additional off-grid CRC-bad records; ten planned slots had no aligned record.
All 31 RF/lifecycle/power checks passed. Local valid-packet coverage improved
from 88.33% to 99.53% for these two trials. This supports investigating signal
margin, but one comparison does not establish reliability or prove the cause
of the earlier no-motion outcomes. Device gain is not calibrated radiated power.

**Testing is paused for the night at the operator's request.** The final source
session closed and the DK halted with its process reaped; both radios may be
disconnected. Resume only after reconnection/setup confirmation, using fresh
receiver and attempt records. The ESP32 bench images are prepared; physical
NiceRF qualification remains outstanding.

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
   Those first two trials did not demonstrate an intermediate position. The
   fixed bottom rail and moving top rail are physical observations; the saved
   product code's dual-slider UI does not override them. Raw 255 subsequently covered
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
   schedule; only one channel was recorded. Subsequent five-second DK captures
   recovered 549 valid original raw-191 packets and 460 valid original raw-128
   packets, all matching the expected primary bodies and requested bytes.
   Those two trials had no physical observation. Their timing includes jitter
   and phase shifts absent from the synthesized constant grid. Source execution
   rules out periodic queue refresh in the observed mode and demonstrates
   coalescing of unserviced timer triggers; actual service delays and clock
   frequency remain unmeasured. The operator later reported roughly-halfway
   coverage on returning after the original raw-128 request; this is a current
   state observation, not a watched outcome of the unattended trials. Keep
   nominal timing unchanged pending a qualified comparison. Neither the matching
   bytes nor retained decoder controls explain the direct raw-128 endpoint
   response.
   A later unchanged raw-191 repeat after moving closer reached roughly
   three-quarters coverage, with no other shade moving; the preceding attempt
   was excluded at the operator's request. The next unchanged raw-128 request
   from that observed position produced no movement. Its independent DK
   capture recovered 2,711 matching valid packets, including the first and
   last expected receive-channel slots. Transmission is established; shade
   reception and acceptance are not. Preserve the raw-191 intermediate success
   and the raw-128 negative result separately, without attributing either to
   a timing, power or encoding cause that was not measured.
   After reconnecting and confirming the same setup, one unchanged raw-127
   request moved from three-quarters to roughly halfway covered, with no other
   shade moving. The independent receiver recovered 1,008 matching valid
   packets; two absolute alignments remain possible. This qualifies one
   raw-127 result, not a reserved-value interpretation of raw 128. A subsequent
   raw-191 request again reached three-quarters coverage, and raw 129 then
   reached roughly halfway, each with no other shade moving. The operator
   confirmed the 129 mark and reported visible marks that distinguish 127,
   128 and 129; a return to three-quarters is unnecessary for those comparisons.
   At the operator's request, a fourth raw-128 trial reused the exact original
   waveform, timing and gain. It moved from the 129 mark to the 128 mark,
   with no other shade moving. Its 2,424 matching valid packets included the
   first and last expected receive-channel slots. This is the first watched
   raw-128 intermediate success; preserve the earlier failures and full opening
   without assigning an unmeasured cause. The proposed original-bridge
   comparison was not run, since the requested synthetic repeat succeeded.
   Continue repeatability comparisons from observed marks with unchanged
   waveform settings.
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
   with fictional identities. A reviewed private DK variant now records five
   seconds but retains the 4,096-record limit. Longer enrollment trains still
   need selected windows or a separately reviewed recorder with sufficient
   capacity, not silently widened limits. After watched enrollment, issue an
   ordinary Jog or position command using the **new identity** and observe the
   result. Check old-binding
   behavior and unrelated targets separately. An acknowledgement jog alone is
   insufficient. Enrollment need not wait for every secondary product family.

5. **Add product-specific controls from original evidence.**
   Decimal feature 18 (`0x12`) applies to product codes 2, 13 and 25. Its original
   builder and bounded scheduler now establish held code `0x6D`, followup code
   `0x32` and unchanged requested values 0/128/255. In the tested native context
   with the queue-mode bit clear, it shares primary position's fixed phase
   bodies and per-packet channel rotation, without Jog alternation or periodic
   refresh. Exact original phase counts, complete endpoint mappings and
   repeatability remain unproven.
   The separate secondary offline planner now matches all 1,374 source events;
   written-IQ checks pass, with primary APIs and waveforms unchanged. No Python
   live backend or saved grant has been widened. The ESP32 has an explicitly
   unqualified secondary bench candidate. The app labels primary as bottom rail
   and secondary as middle/top-down,
   but that static mapping does not establish the installed mechanism. The
   single-top-down target has a fixed bottom rail; the separately identified
   two-moving-rail and bottom-up targets require their own mappings. Room
   product metadata does not establish those mechanisms.
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
   Native ESP32 test images now include finite Jog, primary and secondary
   plans, separate operation access, cancellation and deadline failure handling.
   Per-shade physical mappings and feature-specific touch/web/HTTP controls
   distinguish bottom-up, top-down and dual-rail installations in simulation.
   The assembly is not yet available: measure the NiceRF candidate's framing,
   channel rotation and timing with a fictional target before shade tests.
   See the [test-image procedure](../firmware/esp32_gateway/docs/radio-qualification.md).
   Keep bounded airtime, serialization, operation grants, hashes and receipts.
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
has source, written-IQ and independent RF checks, observed raw-255/raw-0
endpoints, and intermediate results at raw 127, 128, 129 and 191. Raw 191 has
two watched successes; raw 128 has one precise 129-mark-to-128-mark success
following three inconsistent outcomes. Preserve all individual observations.
Original-app results and matching received bodies provide separate references;
the complete original schedule and the cause of earlier failures remain
unresolved. Next establish repeatability from observed marks with unchanged
settings. Enrollment and remaining features need their own controlled trials.
