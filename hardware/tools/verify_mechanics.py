#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Independently check native Rev A PCB mechanics against source dimensions.

Run with KiCad 9's pcbnew Python module, for example in the hardware image:
    python3 hardware/tools/verify_mechanics.py

Checks do not import the PCB generator. The M032 coordinates come from the
separate manufacturer-source extraction; radio coordinates are the approved
bottom-side placement, derived from the NiceRF dimensional drawing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import pcbnew as k


ROOT = Path(__file__).resolve().parents[1]
TOLERANCE_MM = 0.00001


def xy(point):
    return [k.ToMM(point.x), k.ToMM(point.y)]


def close(a, b):
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(close(x, y) for x, y in zip(a, b))
    return abs(a - b) <= TOLERANCE_MM


def line_endpoints(item):
    return tuple(sorted(tuple(round(n, 5) for n in p)
                        for p in [xy(item.GetStart()), xy(item.GetEnd())]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', type=Path,
                        default=ROOT / 'kicad/hd-platinum-carrier-rev-a.kicad_pcb')
    parser.add_argument('--report', type=Path,
                        default=ROOT / 'reports/mechanical-check.json')
    args = parser.parse_args()
    reference = json.loads((ROOT / 'design/module132-mechanical.json').read_text())
    board = k.LoadBoard(str(args.board))
    checks = []

    def check(name, passed, actual=None, expected=None):
        entry = {'check': name, 'passed': bool(passed)}
        if actual is not None:
            entry['actual'] = actual
        if expected is not None:
            entry['expected'] = expected
        checks.append(entry)

    footprints = {fp.GetReference(): fp for fp in board.GetFootprints()}

    def single_pad(ref, number):
        pads = [p for p in footprints[ref].Pads() if p.GetNumber() == str(number)]
        if len(pads) != 1:
            raise ValueError(f'{ref}.{number} must have exactly one pad, got {len(pads)}')
        return pads[0]

    vertices = reference['outline_vertices']
    expected_edges = {
        tuple(sorted(tuple(float(v) for v in p) for p in [a, b]))
        for a, b in zip(vertices, vertices[1:] + vertices[:1])
    }
    edges = [s for s in board.GetDrawings() if s.GetLayer() == k.Edge_Cuts]
    line_edges = [s for s in edges if isinstance(s, k.PCB_SHAPE)
                  and s.GetShape() == k.SHAPE_T_SEGMENT]
    actual_edges = {line_endpoints(s) for s in line_edges}
    check('M032 50mm outline, chamfers and north notches',
          len(edges) == len(expected_edges) and actual_edges == expected_edges,
          {'edge_count': len(edges), 'vertices_mm': sorted({p for e in actual_edges for p in e})},
          {'edge_count': len(expected_edges), 'vertices_mm': sorted({p for e in expected_edges for p in e})})
    check('Finished thickness is specified 1.6mm',
          close(k.ToMM(board.GetDesignSettings().GetBoardThickness()), 1.6),
          k.ToMM(board.GetDesignSettings().GetBoardThickness()), 1.6)

    source_holes = reference['stack_holes'] + reference['retention_holes']
    actual_holes = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetAttribute() == k.PAD_ATTRIB_NPTH:
                actual_holes.append({'xy': xy(pad.GetPosition()), 'drill': xy(pad.GetDrillSize())})
    check('Exactly eight NPTH mounting/retention holes', len(actual_holes) == 8,
          len(actual_holes), 8)
    for hole in source_holes:
        expected_xy = [hole['x'], hole['y']]
        expected_drill = [hole['source_drill']] * 2
        matches = [p for p in actual_holes if close(p['xy'], expected_xy)]
        check(f'NPTH at {expected_xy}', len(matches) == 1
              and close(matches[0]['drill'], expected_drill), matches,
              {'xy': expected_xy, 'drill': expected_drill})

    check('A089 native assembly side is bottom', footprints['J1'].GetLayer() == k.B_Cu,
          footprints['J1'].GetLayerName(), 'B.Cu')
    header_pads = list(footprints['J1'].Pads())
    check('A089 has thirty contacts', len(header_pads) == 30, len(header_pads), 30)
    for expected in reference['mbus']['contacts']:
        pad = single_pad('J1', expected['pin'])
        check(f'J1 pin {expected["pin"]} source position',
              close(xy(pad.GetPosition()), [expected['x'], expected['y']]),
              xy(pad.GetPosition()), [expected['x'], expected['y']])
        check(f'J1 pin {expected["pin"]} finished PTH/land',
              pad.GetAttribute() == k.PAD_ATTRIB_PTH
              and close(xy(pad.GetDrillSize()), [1.0, 1.0])
              and close(xy(pad.GetSize()), [1.8, 1.8]),
              {'drill': xy(pad.GetDrillSize()), 'land': xy(pad.GetSize())},
              {'drill': [1.0, 1.0], 'land': [1.8, 1.8]})
    check('J1 pin 1 ground and rectangular polarity mark',
          single_pad('J1', 1).GetNetname() == 'GND'
          and single_pad('J1', 1).GetShape() == k.PAD_SHAPE_RECT)
    check('J1 source polarity anchors',
          single_pad('J1', 12).GetNetname() == 'HOST_3V3'
          and single_pad('J1', 28).GetNetname() == 'BUS_5V')
    header_fab = [xy(p) for g in footprints['J1'].GraphicalItems()
                  if isinstance(g, k.PCB_SHAPE) and g.GetLayer() == k.B_Fab
                  for p in [g.GetStart(), g.GetEnd()]]
    header_bounds = ([min(p[0] for p in header_fab), min(p[1] for p in header_fab),
                      max(p[0] for p in header_fab), max(p[1] for p in header_fab)]
                     if header_fab else [])
    check('A089 bottom housing envelope 5x39mm',
          close(header_bounds, [41.55, 5.50, 46.55, 44.50]),
          header_bounds, [41.55, 5.50, 46.55, 44.50])
    front_smd = [fp.GetReference() for fp in board.GetFootprints()
                 if fp.GetAttributes() & k.FP_SMD and fp.GetLayer() != k.B_Cu]
    check('All SMT components face into ring', not front_smd, front_smd, [])

    for ref in ['U1', 'J2']:
        check(f'{ref} native side is bottom', footprints[ref].GetLayer() == k.B_Cu,
              footprints[ref].GetLayerName(), 'B.Cu')
    radio = {pin: [30.6, round(14.0 + 1.27 * (pin - 1), 5)] for pin in range(1, 9)}
    radio.update({9: [11.4, 22.68], 10: [11.4, 15.53], 11: [11.4, 13.53]})
    for pin, expected_xy in radio.items():
        pad = single_pad('U1', pin)
        expected_size = [2.5, 1.0 if pin <= 8 else 1.36]
        check(f'U1 pin {pin} bottom-side mirror and land',
              close(xy(pad.GetPosition()), expected_xy)
              and close(xy(pad.GetSize()), expected_size)
              and pad.GetAttribute() == k.PAD_ATTRIB_SMD
              and pad.IsOnLayer(k.B_Cu),
              {'xy': xy(pad.GetPosition()), 'land': xy(pad.GetSize())},
              {'xy': expected_xy, 'land': expected_size})
    fab_points = [xy(p) for g in footprints['U1'].GraphicalItems()
                  if isinstance(g, k.PCB_SHAPE) and g.GetLayer() == k.B_Fab
                  for p in [g.GetStart(), g.GetEnd()]]
    bounds = [min(p[0] for p in fab_points), min(p[1] for p in fab_points),
              max(p[0] for p in fab_points), max(p[1] for p in fab_points)]
    check('U1 20.00x13.02mm body outline', close(bounds, [11.0, 12.0, 31.0, 25.02]),
          bounds, [11.0, 12.0, 31.0, 25.02])
    check('J2 signal faces radio', close(xy(single_pad('J2', 1).GetPosition()), [7.55, 13.53]),
          xy(single_pad('J2', 1).GetPosition()), [7.55, 13.53])
    check('ANT endpoints assigned to correct pads',
          single_pad('U1', 11).GetNetname() == 'ANT'
          and single_pad('J2', 1).GetNetname() == 'ANT')

    rf_items = [t for t in board.GetTracks() if t.GetNetname() == 'ANT']
    rf_tracks = [t for t in rf_items if not isinstance(t, k.PCB_VIA)]
    rf_length = sum(math.dist(xy(t.GetStart()), xy(t.GetEnd())) for t in rf_tracks)
    expected_rf_endpoints = tuple(sorted([(7.55, 13.53), (11.4, 13.53)]))
    check('ANT is one straight bottom 3.85mm segment without vias',
          len(rf_items) == len(rf_tracks) == 1
          and rf_tracks[0].GetLayer() == k.B_Cu
          and line_endpoints(rf_tracks[0]) == expected_rf_endpoints
          and close(rf_length, 3.85),
          {'tracks': len(rf_tracks), 'vias': len(rf_items) - len(rf_tracks),
           'length_mm': rf_length})
    check('ANT trace nominal width 0.35mm', len(rf_tracks) == 1
          and close(k.ToMM(rf_tracks[0].GetWidth()), 0.35))

    all_passed = all(c['passed'] for c in checks)
    report = {
        'result': 'PASS' if all_passed else 'FAIL',
        'scope': 'Native CAD mechanical and orientation checks; not physical fit certification',
        'board_file': str(args.board.relative_to(ROOT)) if args.board.is_relative_to(ROOT) else str(args.board),
        'board_sha256': hashlib.sha256(args.board.read_bytes()).hexdigest(),
        'source_revision': reference['source_revision'],
        'tolerance_mm': TOLERANCE_MM,
        'checks_passed': sum(c['passed'] for c in checks),
        'checks_total': len(checks),
        'checks': checks,
        'physical_checks_still_required': reference['unverified'],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(f'{report["result"]}: {report["checks_passed"]}/{len(checks)} mechanical checks; {args.report}')
    for c in checks:
        if not c['passed']:
            print('FAIL:', c['check'])
    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())
