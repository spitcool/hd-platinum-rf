#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check that the exported package covers the exact reviewed native design."""
from pathlib import Path
import csv, hashlib, json, re, zipfile
import pcbnew as k
ROOT=Path(__file__).resolve().parents[1];NAME='hd-platinum-carrier-rev-a'
PCB=ROOT/'kicad'/f'{NAME}.kicad_pcb';OUT=ROOT/'manufacturing'
spec=json.loads((ROOT/'design/board-spec.json').read_text())
b=k.LoadBoard(str(PCB));checks=[]
def check(name,ok):
    checks.append({'check':name,'passed':bool(ok)})
    if not ok:raise AssertionError(name)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
drc=json.loads((ROOT/'reports/pcb-drc.json').read_text())
check('Native DRC, connectivity and schematic parity are clear',not any(drc[x] for x in ['violations','unconnected_items','schematic_parity']))
erc=(ROOT/'reports/schematic-erc.rpt').read_text()
check('Native ERC is clear','ERC messages: 0  Errors 0  Warnings 0' in erc)
mech=json.loads((ROOT/'reports/mechanical-check.json').read_text())
check('Mechanical report matches final PCB',mech['board_sha256']==sha(PCB) and mech['checks_passed']==mech['checks_total']==95)
nl=json.loads((ROOT/'reports/schematic-netlist-check.json').read_text())
check('Independent schematic graph matches 65 pins and 17 nets',nl['passed'] and nl['connected_pins']==65 and nl['intended_nets']==17)
bom=list(csv.DictReader((OUT/'bom.csv').open()));pos=list(csv.DictReader((OUT/'positions.csv').open()))
parts={c['ref']:c for c in spec['components'] if not c['ref'].startswith('TP')}
check('BOM has exactly 19 physical parts',len(bom)==len(parts)==19 and {r['Designator'] for r in bom}==set(parts))
check('BOM manufacturers and MPNs match design',all(r['MPN']==parts[r['Designator']]['mpn'] and r['Manufacturer']==parts[r['Designator']]['manufacturer'] and r['Quantity']=='1' for r in bom))
check('Placement file has exactly 18 SMT parts, all bottom',len(pos)==18 and {r['Ref'] for r in pos}==set(parts)-{'J1'} and all(r['Side']=='bottom' for r in pos))
fps={f.GetReference():f for f in b.GetFootprints()}
check('Placement coordinates match native CAD',all(abs(float(r['PosX'])-k.ToMM(fps[r['Ref']].GetPosition().x))<1e-5 and abs(float(r['PosY'])+k.ToMM(fps[r['Ref']].GetPosition().y))<1e-5 for r in pos))
for entry in json.loads((ROOT/'references/kicad-footprints-sources.json').read_text())['files']:
    check('Library checksum '+Path(entry['path']).name,sha(ROOT/entry['path'])==entry['sha256'])
ger=OUT/'gerbers'
expected=['F_Cu.gtl','In1_Cu.g1','In2_Cu.g2','B_Cu.gbl','F_Mask.gts','B_Mask.gbs','F_Silkscreen.gto','B_Silkscreen.gbo','B_Paste.gbp','Edge_Cuts.gm1','PTH.drl','NPTH.drl','job.gbrjob']
for suffix in expected:check('Fabrication file '+suffix,(ger/f'{NAME}-{suffix}').stat().st_size>50)
for suffix,expected_count in [('PTH.drl',sum(isinstance(t,k.PCB_VIA) for t in b.GetTracks())+30),('NPTH.drl',8)]:
    data=(ger/f'{NAME}-{suffix}').read_text()
    check('Drill hit count '+suffix,len(re.findall(r'^X[-\d.]+Y[-\d.]+$',data,re.M))==expected_count)
with zipfile.ZipFile(OUT/f'{NAME}-gerbers.zip') as z:
    check('Gerber archive matches loose files',all(z.read(p.name)==p.read_bytes() for p in ger.iterdir()))
for name in ['schematic.pdf','assembly-bottom.pdf','fabrication-drawing.pdf','carrier-board-only.step','board-outline.dxf','electrical-test.ipc','pcb-bottom.svg','pcb-top.svg']:
    check('Review output '+name,(OUT/name).is_file() and (OUT/name).stat().st_size>200)
check('No DRC exclusions',json.loads(PCB.with_suffix('.kicad_pro').read_text())['board']['design_settings']['drc_exclusions']==[])
summary={'passed':True,'checks_passed':len(checks),'board_sha256':sha(PCB),'schematic_sha256':sha(PCB.with_suffix('.kicad_sch')),'assembled_parts':19,'smt_placements':18,'checks':checks}
(ROOT/'reports/manufacturing-check.json').write_text(json.dumps(summary,indent=2)+'\n')
print('PASS:',len(checks),'manufacturing-package checks')
