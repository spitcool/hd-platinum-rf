#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Export release-review files from the final checked-in native KiCad project."""
from pathlib import Path
import csv, json, subprocess, zipfile
ROOT=Path(__file__).resolve().parents[1]
SPEC=json.loads((ROOT/'design/board-spec.json').read_text());NAME=SPEC['name']
PCB=ROOT/'kicad'/f'{NAME}.kicad_pcb';SCH=PCB.with_suffix('.kicad_sch')
OUT=ROOT/'manufacturing';GER=OUT/'gerbers';GER.mkdir(exist_ok=True)
def run(*args):subprocess.run([str(a) for a in args],check=True)
run('kicad-cli','pcb','export','gerbers','--layers','F.Cu,In1.Cu,In2.Cu,B.Cu,F.Mask,B.Mask,F.SilkS,B.SilkS,B.Paste,Edge.Cuts','--subtract-soldermask','--output',str(GER)+'/',PCB)
run('kicad-cli','pcb','export','drill','--output',str(GER)+'/', '--format','excellon','--excellon-units','mm','--excellon-separate-th','--generate-map','--map-format','svg','--generate-report','--report-path',ROOT/'reports/drill-report.txt',PCB)
run('kicad-cli','pcb','export','pos','--output',OUT/'positions.csv','--side','back','--format','csv','--units','mm','--smd-only','--exclude-fp-th','--use-drill-file-origin',PCB)
run('kicad-cli','pcb','export','ipcd356','--output',OUT/'electrical-test.ipc',PCB)
run('kicad-cli','sch','export','pdf','--output',OUT/'schematic.pdf',SCH)
for side,layer in [('top','F'),('bottom','B')]:
    run('kicad-cli','pcb','export','svg','--output',OUT/f'pcb-{side}.svg','--layers',f'{layer}.Cu,{layer}.SilkS,Edge.Cuts','--mode-single','--fit-page-to-board','--exclude-drawing-sheet',*(['--mirror'] if side=='bottom' else []),PCB)
run('kicad-cli','pcb','export','step','--output',OUT/'carrier-board-only.step','--board-only','--cut-vias-in-body','--force',PCB)
run('kicad-cli','pcb','export','dxf','--output',OUT/'board-outline.dxf','--layers','Edge.Cuts','--mode-single','--output-units','mm',PCB)
columns=['Designator','Quantity','Value','Manufacturer','MPN','Footprint','Side','Supplier reference','Assembly','Notes']
with (OUT/'bom.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=columns);w.writeheader()
    for c in SPEC['components']:
        if c['ref'].startswith('TP'):continue
        w.writerow({'Designator':c['ref'],'Quantity':1,'Value':c['value'],'Manufacturer':c['manufacturer'],'MPN':c['mpn'],'Footprint':c['footprint'],'Side':'Bottom','Supplier reference':c.get('supplier_code',''),'Assembly':'Manual through-hole' if c['ref']=='J1' else 'SMT','Notes':c.get('note','')})
with zipfile.ZipFile(OUT/f'{NAME}-gerbers.zip','w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(GER.iterdir()):z.write(p,p.name)
print('Exported fabrication, placement, BOM, electrical-test and drawing files')
