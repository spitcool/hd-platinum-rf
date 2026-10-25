#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validate native CAD and export outputs; --regenerate also recreates CAD.

Use --regenerate only when intentionally discarding native CAD edits in favor
of board-spec.json and the generator sources.
"""
from pathlib import Path
import argparse, json, subprocess, sys
ROOT=Path(__file__).resolve().parents[1];NAME='hd-platinum-carrier-rev-a'
PCB=ROOT/'kicad'/f'{NAME}.kicad_pcb';SCH=PCB.with_suffix('.kicad_sch')
p=argparse.ArgumentParser();p.add_argument('--regenerate',action='store_true');args=p.parse_args()
def run(*argv,output=None):
    print('+',' '.join(map(str,argv)),flush=True)
    result=subprocess.run(list(map(str,argv)),check=True,text=True,stdout=subprocess.PIPE if output else None)
    if output:Path(output).write_text(result.stdout)
def script(name):run(sys.executable,ROOT/'tools'/name)
if args.regenerate:script('generate_schematic.py')
run('kicad-cli','sch','export','netlist','--format','kicadxml','--output',ROOT/'reports/schematic-netlist.xml',SCH)
run(sys.executable,ROOT/'tools/check_schematic_netlist.py',output=ROOT/'reports/schematic-netlist-check.json')
if args.regenerate:
    script('generate_pcb.py');script('route_pcb.py');script('finalize_pcb.py')
run('kicad-cli','sch','erc','--exit-code-violations','--output',ROOT/'reports/schematic-erc.rpt',SCH)
run('kicad-cli','pcb','drc','--format','json','--all-track-errors','--schematic-parity','--exit-code-violations','--output',ROOT/'reports/pcb-drc.json',PCB)
script('verify_mechanics.py')
script('export_manufacturing.py');script('draw_manufacturing.py');script('draw_final_assembly.py');script('render_previews.py');script('verify_manufacturing.py')
print('Hardware validation and manufacturing export complete.')
