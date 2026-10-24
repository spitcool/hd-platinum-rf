#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check the KiCad-exported schematic graph against the design specification."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
spec = json.loads((root / "design/board-spec.json").read_text())
path = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "reports/schematic-netlist.xml"
tree = ET.parse(path)
actual: dict[tuple[str, str], str] = {}
for net in tree.findall("./nets/net"):
    for node in net.findall("node"):
        actual[node.attrib["ref"], node.attrib["pin"]] = net.attrib["name"]
expected = {(c["ref"], pin): net for c in spec["components"]
            for pin, net in c["pins"].items() if net}
mismatches = [{"ref": ref, "pin": pin, "expected": net,
               "actual": actual.get((ref, pin))}
              for (ref, pin), net in sorted(expected.items())
              if actual.get((ref, pin)) != net]
unexpected = [{"ref": ref, "pin": pin, "net": net}
              for (ref, pin), net in sorted(actual.items())
              if (ref, pin) not in expected and not net.startswith("unconnected-")
              and not ref.startswith("#")]
summary = {"connected_pins": len(expected), "intended_nets": len(set(expected.values())),
           "mismatches": mismatches, "unexpected_connected_pins": unexpected,
           "passed": not mismatches and not unexpected}
print(json.dumps(summary, indent=2))
sys.exit(0 if summary["passed"] else 1)
