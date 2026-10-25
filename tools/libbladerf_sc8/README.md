<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# libbladeRF SC8 metadata TX regression

`sc8-metadata.patch` adds `BLADERF_FORMAT_SC8_Q7_META` to two existing TX
format checks in Nuand's libbladeRF. Without the first change, SC8 bypasses
metadata validation, scheduled burst handling, and end-of-burst padding.
Without the second, successful `BURST_END` leaves `in_burst` set and the next
`BURST_START` is rejected. The patch leaves the shared serializer unchanged.

The offline regression compiles the actual selected upstream functions, rather
than a Python reimplementation. It runs the unmodified source, a diagnostic
version with only the first change, and the complete patch. It requires the
first two versions to reproduce the defects and the complete patch to pass.
Every serialized SC16 byte must remain identical across all three versions.

## Pinned input

Supply an **unmodified** checkout or source archive of
[Nuand/bladeRF revision `fcf9423325ae49f5fdd2e5b52ab68bfc2576ad47`](https://github.com/Nuand/bladeRF/tree/fcf9423325ae49f5fdd2e5b52ab68bfc2576ad47).
This is a libbladeRF 2.6 API revision; it is not a claim about every 2.6 build.
No submodules, installed libbladeRF, device, or USB access are needed.

The source under test is
`host/libraries/libbladeRF/src/streaming/sync.c`:

- Input SHA-256: `7fdfa93cd7d999c5a7907f1b6926834ba442429bd1faa465eefa65a743a550ba`
- Patched SHA-256: `8ae1f54865aacf2bae57a99ef0c86a728e12d5bab75cc01367031403e599a1fd`

`check.py` also pins the SHA-256 of `sync.h`, `metadata.h`, `libbladeRF.h`,
`bladeRF1.h`, and `bladeRF2.h`. It refuses changed inputs, including an already
patched tree. It verifies the distributed patch against the tested change,
generates copies into a new output directory, and checks that the supplied
inputs remain unchanged. It does not fetch source or install anything.

## Run

Use Python 3.9 or later and a C11 compiler on a POSIX host. The probe links only
the C runtime. The largest input allocation is about 174 MB; sanitizer overhead
is additional. Each compiler and probe invocation has a wall-clock timeout.

```sh
python3 tools/libbladerf_sc8/check.py \
  --source-dir /path/to/unmodified/bladeRF \
  --output-dir /path/to/new-regression-output
```

The output directory's parent must exist, and the output directory must be
outside the upstream tree. Use `--cc clang --sanitize` for AddressSanitizer and
UndefinedBehaviorSanitizer when supported. `--cc` selects one executable;
`--cflag` passes one additional compiler argument and can be repeated, for
example `--cflag=-isysroot --cflag=/path/to/MacOSX.sdk`. No shell evaluates these
arguments. `CC` is used only as the default compiler executable.

Successful output includes `report.json`, compiler/probe logs, the generated
upstream function copies and headers with their notices, and three complete
SC16 wire-byte files. The comparison covers **13,369,344 identical SC16 bytes
per variant** in the pinned matrix. The report also gives their SHA-256.
No radio library is loaded or linked, and the executable has no device or
network implementation.

The ordinary Python test suite checks source rejection and runner safeguards
without bundling upstream source. To additionally run the actual-source matrix
through that test module, provide the same checkout explicitly:

```sh
LIBBLADERF_SC8_SOURCE=/path/to/unmodified/bladeRF \
  python3 -m unittest discover -s tests -p test_libbladerf_sc8.py
```

For this optional test, `CC`, `LIBBLADERF_SC8_CFLAGS` (a JSON array of individual
arguments), and `LIBBLADERF_SC8_SANITIZE=1` select the compiler settings.

## Coverage and limits

Each variant produces 44 result rows: 19 SC16 burst cases, 21 SC8 burst cases,
and metadata-validation/timestamp-update cases for each format. Burst cases
check the first burst and a subsequent burst on the same stream.

- Both 2,048-byte and 8,192-byte metadata-message geometries.
- Two- and four-byte complex sample widths, explicit TX_X1 configuration.
- Small tails and boundaries around samples-per-message and samples-per-buffer;
  for legacy SC8 these are 1,016 and 65,024 samples.
- Single and split calls, `START | END`, valid `TX_NOW`, valid
  `TX_UPDATE_TIMESTAMP` with a zero-filled gap, and invalid null/flag cases.
- Every sample byte, metadata timestamp, metadata flags/packet length, zero
  tail padding, and buffer redzones.
- An 86,616,000-sample SC8 call at both message geometries.

The extracted source consists of `samples2bytes`, `msg_per_buf`,
`samples_per_msg`, `left_in_msg`, `advance_tx_buffer`, `timestamp_in_past`,
`handle_tx_parameters`, `sync_tx`, and their TX options type. Mutex operations,
the worker, buffer availability, and asynchronous USB submission are inert
substitutes. `sync_init` is not executed: the fixture explicitly sets the
format, sample width, layout, and message size.

This establishes the tested **host serialization and burst state behavior**.
It does not test RX, TX_X2, concurrency, USB transfer timing, FPGA/FX3 behavior,
RFIC configuration, sustained throughput, or reception of transmitted samples.
A software pass does not establish that a radio transmission works.

## Patch and license

The patch changes only the two format conditions. To apply it separately, first
run the regression on the unmodified tree, then use the upstream tree as the
working directory:

```sh
git apply --check /path/to/hd-platinum-rf/tools/libbladerf_sc8/sc8-metadata.patch
git apply /path/to/hd-platinum-rf/tools/libbladerf_sc8/sc8-metadata.patch
```

The patch is derived from Nuand's source, copyright 2014–2015 Nuand LLC. The
patch additions and test tools are copyright 2026 Christopher Spitler. The
patch, `check.py`, `probe.c`, and their focused test module use
`LGPL-2.1-or-later`, separately from the main project's AGPL software.
Generated upstream copies retain their original copyright and license notices.

[LICENSE](LICENSE) is the unchanged canonical LGPL 2.1 text from the pinned
upstream `legal/licenses/LICENSE.LGPLv2.1`, SHA-256
`592987e8510228d546540b84a22444bde98e48d03078d3b2eefcd889bec5ce8c`.
The upstream source files grant version 2.1 **or any later version**.
This README retains the project's documentation license stated above.
