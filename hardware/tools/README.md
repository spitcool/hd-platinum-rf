# Rebuilding and checking the hardware

The checked-in KiCad 9 project is editable directly. All required 2D symbols
and footprints are local to `hardware/kicad`. Standard 3D component models are
optional and are not included; `carrier-board-only.step` contains the finished
PCB and drill geometry, not a populated appliance model.

From the repository root, with Docker running:

```sh
docker build -t hd-platinum-hardware:local -f hardware/tools/Dockerfile hardware/tools
docker run --rm -v "$PWD:/work" hd-platinum-hardware:local python3 hardware/tools/build.py
```

This validates the **existing native CAD**, checks schematic/PCB agreement,
verifies mechanical coordinates and exports the manufacturing files. It fails
on ERC/DRC violations or incomplete/inconsistent exports. The checked-in
`reports/tool-versions.txt` records the tools used for this revision.

To intentionally regenerate the schematic and routed layout from
`design/board-spec.json` and the Python generators:

```sh
docker run --rm -v "$PWD:/work" hd-platinum-hardware:local python3 hardware/tools/build.py --regenerate
```

**Regeneration replaces native CAD edits.** Preserve any manual revision before
using this option. Changes to parts, electrical connectivity or geometry must
also be reflected in the generator/specification if regeneration is desired.
The router uses both outer copper layers; the two inner layers are ground.
It preserves the explicitly routed RF connection. Generated UUIDs and export
timestamps may change; byte-identical regeneration is not promised.

`verify_mechanics.py` independently loads the PCB and checks it against the
published M5Stack geometry and explicit radio/connector polarity anchors.
`check_schematic_netlist.py` checks KiCad's exported electrical graph against
the component specification. `verify_manufacturing.py` checks BOM, placements,
drills, footprint hashes and exported files. KiCad is the authoritative DRC/ERC
engine; the custom router is not treated as proof of electrical correctness.

Review the regenerated PDFs and copper plots visually after any change. The
automated checks do not establish solderability, mechanical fit, radio behavior,
antenna performance or production readiness. Those checks are specified in
`manufacturing/acceptance-test.md`.
