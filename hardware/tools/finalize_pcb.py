#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apply stackup, fabrication settings and legible silkscreen to routed PCB."""
from pathlib import Path
import json, math
import xml.etree.ElementTree as ET
import sexpdata as sx
from shapely.geometry import Point, box, LineString
from shapely.affinity import rotate
import pcbnew as k
ROOT=Path(__file__).resolve().parents[1];NAME='hd-platinum-carrier-rev-a'
path=ROOT/'kicad'/f'{NAME}.kicad_pcb'
b=k.LoadBoard(str(path))
def xy(p):return k.ToMM(p.x),k.ToMM(p.y)
def v(x,y):return k.VECTOR2I(k.FromMM(x),k.FromMM(y))

# Remove fanout vias that routing did not use to change layers.
remove_ids=set()
remove_track_ids=set()
for t in list(b.GetTracks()):
    if not isinstance(t,k.PCB_VIA) or t.GetNetname()=='GND':continue
    pos=Point(*xy(t.GetPosition()));used=set()
    for s in b.GetTracks():
        if isinstance(s,k.PCB_VIA) or s.GetNetname()!=t.GetNetname():continue
        if LineString([xy(s.GetStart()),xy(s.GetEnd())]).distance(pos)<k.ToMM(t.GetWidth(k.F_Cu)+s.GetWidth())/2-.01:used.add(s.GetLayer())
    if len(used)<2:
        remove_ids.add(t.m_Uuid.AsString())
        for s in b.GetTracks():
            if isinstance(s,k.PCB_VIA) or s.GetNetname()!=t.GetNetname():continue
            a,z=xy(s.GetStart()),xy(s.GetEnd())
            if abs(math.dist(a,z)-1.9)<.00001 and min(math.dist(a,xy(t.GetPosition())),math.dist(z,xy(t.GetPosition())))<.00001:
                remove_track_ids.add(s.m_Uuid.AsString())

# Preserve native no-connect net identifiers for exact schematic parity.
netlist=ET.parse(ROOT/'reports/schematic-netlist.xml')
fpmap={fp.GetReference():fp for fp in b.GetFootprints()}
for net in netlist.findall('./nets/net'):
    name=net.attrib['name']
    if not name.startswith('unconnected-'):continue
    native=b.FindNet(name)
    if native is None or native.GetNetname()!=name:
        native=k.NETINFO_ITEM(b,name);b.Add(native)
    for node in net.findall('node'):
        for p in fpmap[node.attrib['ref']].Pads():
            if p.GetNumber()==node.attrib['pin']:p.SetNet(native)
fpmap['J1'].Reference().SetMirrored(False)
# Hirose's library land pattern intentionally opens mask under the connector.
# Its no-copper keepout prevents a conductive bridge; allow the intentional
# merged mask aperture only within this footprint (not globally).
j2=fpmap['J2'];j2.SetAttributes(j2.GetAttributes()|k.FP_ALLOW_SOLDERMASK_BRIDGES)
# Reference labels must clear exposed lands and printed component outlines.
obstacles=[]
for fp in b.GetFootprints():
    for p in fp.Pads():
        if not p.IsOnLayer(k.B_Mask):continue
        x,y=xy(p.GetPosition());w,h=xy(p.GetSize())
        g=Point(x,y).buffer(w/2) if p.GetShape()==k.PAD_SHAPE_CIRCLE else rotate(box(x-w/2,y-h/2,x+w/2,y+h/2),p.GetOrientationDegrees(),origin=(x,y))
        obstacles.append(g.buffer(.18))
    for g in fp.GraphicalItems():
        if g.GetLayer()!=k.B_SilkS:continue
        if isinstance(g,k.PCB_SHAPE):obstacles.append(LineString([xy(g.GetStart()),xy(g.GetEnd())]).buffer(.15))
for t in b.GetDrawings():
    if isinstance(t,k.PCB_TEXT) and t.GetLayer()==k.B_SilkS:
        bb=t.GetBoundingBox();x,y=xy(bb.GetPosition());w,h=xy(bb.GetSize());obstacles.append(box(x,y,x+w,y+h).buffer(.1))
for fp in sorted(b.GetFootprints(),key=lambda f:f.GetReference()):
    t=fp.Reference()
    if not t.IsVisible() or t.GetLayer()!=k.B_SilkS:continue
    x,y=xy(fp.GetPosition());old=xy(t.GetPosition())
    candidates=[old]
    for r in [1.7,2.1,2.6,3.1,3.6,4.2]:
        candidates += [(x,y-r),(x,y+r),(x-r,y),(x+r,y),(x-r,y-r),(x+r,y-r),(x-r,y+r),(x+r,y+r)]
    for X,Y in candidates:
        t.SetPosition(v(X,Y));t.SetTextAngle(k.EDA_ANGLE(0,k.DEGREES_T))
        bb=t.GetBoundingBox();xx,yy=xy(bb.GetPosition());w,h=xy(bb.GetSize());g=box(xx,yy,xx+w,yy+h).buffer(.05)
        if not box(.5,.5,49.5,49.5).contains(g):continue
        if any(g.intersects(o) for o in obstacles):continue
        obstacles.append(g);break
    else:raise RuntimeError('No silkscreen position '+fp.GetReference())

b.GetDesignSettings().m_SolderMaskMargin=k.FromMM(.05)
b.GetTitleBlock().SetTitle('HD Platinum RF carrier - engineering first article')
b.GetTitleBlock().SetRevision('A');b.GetTitleBlock().SetDate('2026-10-24')
k.ZONE_FILLER(b).Fill(b.Zones())
k.SaveBoard(str(path),b)

stack='''
    (stackup
      (layer "F.SilkS" (type "Top Silk Screen"))
      (layer "F.Mask" (type "Top Solder Mask") (thickness 0.01) (epsilon_r 3.8) (loss_tangent 0.02))
      (layer "F.Cu" (type "copper") (thickness 0.035))
      (layer "dielectric 1" (type "prepreg") (thickness 0.2104) (material "7628 x1") (epsilon_r 4.4) (loss_tangent 0.02))
      (layer "In1.Cu" (type "copper") (thickness 0.0152))
      (layer "dielectric 2" (type "core") (thickness 1.065) (material "FR4") (epsilon_r 4.6) (loss_tangent 0.02))
      (layer "In2.Cu" (type "copper") (thickness 0.0152))
      (layer "dielectric 3" (type "prepreg") (thickness 0.2104) (material "7628 x1") (epsilon_r 4.4) (loss_tangent 0.02))
      (layer "B.Cu" (type "copper") (thickness 0.035))
      (layer "B.Mask" (type "Bottom Solder Mask") (thickness 0.01) (epsilon_r 3.8) (loss_tangent 0.02))
      (layer "B.SilkS" (type "Bottom Silk Screen"))
      (copper_finish "ENIG") (dielectric_constraints yes)
    )
'''
tree=sx.loads(path.read_text())
def uid(node):
    return next((str(x[1]) for x in node if isinstance(x,list) and x and str(x[0])=='uuid'),'')
tree=[x for x in tree if not (isinstance(x,list) and x and ((str(x[0])=='via' and uid(x) in remove_ids) or (str(x[0])=='segment' and uid(x) in remove_track_ids)))]
setup=next(x for x in tree if isinstance(x,list) and x and str(x[0])=='setup')
for name,value in [('pad_to_mask_clearance',.05),('solder_mask_min_width',.1)]:
    existing=next((x for x in setup if isinstance(x,list) and x and str(x[0])==name),None)
    if existing is not None:existing[1]=value
    else:setup.append([sx.Symbol(name),value])
text=sx.dumps(tree)
if '(stackup' not in text:text=text.replace('(setup','(setup'+stack,1)
path.write_text(text)
# Native re-save canonicalizes the stackup syntax.
b=k.LoadBoard(str(path));k.ZONE_FILLER(b).Fill(b.Zones());k.SaveBoard(str(path),b)
pro=path.with_suffix('.kicad_pro');j=json.loads(pro.read_text())
rules=j['board']['design_settings']['rules']
rules.update(min_text_height=.65,min_silk_clearance=.10,min_text_thickness=.10,min_via_annular_width=.15)
j['board']['design_settings']['track_widths']=[.25,.35,.50]
j['board']['design_settings']['via_dimensions']=[{'diameter':.6,'drill':.3}]
j['net_settings']['classes'][0]['track_width']=.25
j['board']['design_settings']['drc_exclusions']=[]
pro.write_text(json.dumps(j,indent=2)+'\n')
path.with_suffix('.kicad_dru').write_text('''(version 1)
(rule "RF feed fixed width"
  (condition "A.Type == 'Track' && A.NetName == 'ANT'")
  (constraint track_width (min 0.35) (max 0.35))
  (constraint clearance (min 0.50)))
''')
print('Finalized stackup, fabrication settings and silkscreen')
