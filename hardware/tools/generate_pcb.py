#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build the Rev A carrier from the checked-in specification using KiCad 9.

Coordinates are mm, viewed from the Core-facing top. SMT is on the bottom.
Run in the hardware Docker image. Native PCB is editable without this script.
"""
from pathlib import Path
import json, math, shutil, uuid
import pcbnew as k

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT/'design/board-spec.json').read_text())
NAME = SPEC['name']
OUT = ROOT/'kicad'
LIB = OUT/'HDPlatinum.pretty'
OUT.mkdir(exist_ok=True); LIB.mkdir(exist_ok=True)
def v(x,y): return k.VECTOR2I(k.FromMM(x),k.FromMM(y))
def lset(layers):
    s=k.LSET()
    for layer in layers: s.AddLayer(layer)
    return s
def all_copper_mask():
    s=k.LSET.AllCuMask(); s.AddLayer(k.F_Mask); s.AddLayer(k.B_Mask); return s
def mm(p): return (k.ToMM(p.x),k.ToMM(p.y))
def uid(s): return str(uuid.uuid5(uuid.NAMESPACE_URL,'hd-platinum/'+s))
board = k.BOARD()
board.SetCopperLayerCount(4)
board.SetFileName(str(OUT/(NAME+'.kicad_pcb')))
board.GetDesignSettings().SetBoardThickness(k.FromMM(1.6))
board.GetDesignSettings().m_MinClearance=k.FromMM(.20)
board.GetDesignSettings().m_TrackMinWidth=k.FromMM(.20)
board.GetDesignSettings().m_ViasMinSize=k.FromMM(.6)
board.GetDesignSettings().m_MinThroughDrill=k.FromMM(.3)
board.GetDesignSettings().m_CopperEdgeClearance=k.FromMM(.5)
board.GetDesignSettings().SetAuxOrigin(v(0,0))
board.GetDesignSettings().SetGridOrigin(v(0,0))
nets = {}
for name in sorted({n for c in SPEC['components'] for n in c['pins'].values() if n}):
    n = k.NETINFO_ITEM(board,name); board.Add(n); nets[name]=n

def line(parent,a,b,layer,width=.12):
    s = k.PCB_SHAPE(parent); s.SetShape(k.SHAPE_T_SEGMENT)
    s.SetStart(v(*a)); s.SetEnd(v(*b)); s.SetWidth(k.FromMM(width)); s.SetLayer(layer); parent.Add(s)
def rect(parent,a,b,layer,width=.12):
    x,y=a; X,Y=b
    for p,q in [((x,y),(X,y)),((X,y),(X,Y)),((X,Y),(x,Y)),((x,Y),(x,y))]: line(parent,p,q,layer,width)
def pad(fp,num,x,y,w,h,drill=0):
    p=k.PAD(fp); p.SetNumber(str(num)); p.SetPosition(v(x,y)); p.SetSize(v(w,h))
    p.SetShape(k.PAD_SHAPE_CIRCLE if drill else k.PAD_SHAPE_ROUNDRECT)
    if not drill: p.SetRoundRectRadiusRatio(.15)
    p.SetAttribute(k.PAD_ATTRIB_PTH if drill else k.PAD_ATTRIB_SMD)
    p.SetLayerSet(all_copper_mask() if drill else lset([k.F_Cu,k.F_Paste,k.F_Mask]))
    if drill: p.SetDrillSize(v(drill,drill))
    fp.Add(p); return p
def custom(name):
    fp=k.FOOTPRINT(None); fp.SetFPID(k.LIB_ID('HDPlatinum',name)); fp.SetValue(name)
    fp.SetAttributes(k.FP_SMD)
    return fp
def save_custom(fp,name):
    k.PCB_IO_MGR.PluginFind(k.PCB_IO_MGR.KICAD_SEXP).FootprintSave(str(LIB),fp)
    return fp

# Original land pattern derived from NiceRF V3.1 dimensional drawing.
fp=custom('NiceRF_RF2401F20')
for i in range(1,9): pad(fp,i,-9.6,2+1.27*(i-1)-6.51,2.5,1.0)
for i,y in [(9,10.68),(10,3.53),(11,1.53)]: pad(fp,i,9.6,y-6.51,2.5,1.36)
rect(fp,(-10,-6.51),(10,6.51),k.F_Fab,.1)
rect(fp,(-11.15,-7.01),(11.15,7.01),k.F_CrtYd,.05)
line(fp,(-9.9,-6.65),(9.9,-6.65),k.F_SilkS)
line(fp,(-9.9,6.65),(9.9,6.65),k.F_SilkS)
line(fp,(-10,-5.5),(-9.3,-6.2),k.F_SilkS)
save_custom(fp,'NiceRF_RF2401F20')

# Geometry from M5Stack's MIT-licensed Module13.2 Altium file. Housing is B-side.
fp=custom('M5Bus_A089_2x15'); fp.SetAttributes(k.FP_THROUGH_HOLE|k.FP_EXCLUDE_FROM_POS_FILES)
for r in range(15):
    for num,x in [(2*r+1,0),(2*r+2,2.54)]:
        p=pad(fp,num,x,2.54*r,1.8,1.8,1.0)
        if num==1: p.SetShape(k.PAD_SHAPE_RECT)
rect(fp,(-1.23,-1.72),(3.77,37.28),k.F_Fab,.1)
rect(fp,(-1.73,-2.22),(4.27,37.78),k.F_CrtYd,.05)
save_custom(fp,'M5Bus_A089_2x15')

fps={}
for c in SPEC['components']:
    lib,part=c['footprint'].split(':')
    src=LIB if lib=='HDPlatinum' else Path('/usr/share/kicad/footprints')/(lib+'.pretty')
    fp=k.FootprintLoad(str(src),part)
    if fp is None: raise ValueError(c['footprint'])
    # Vendor standard footprints are copied locally for a portable project.
    if lib!='HDPlatinum':
        dest=OUT/(lib+'.pretty'); dest.mkdir(exist_ok=True)
        shutil.copyfile(src/(part+'.kicad_mod'),dest/(part+'.kicad_mod'))
        if c['ref']=='J2':
            library_file=dest/(part+'.kicad_mod')
            library_file.write_text(library_file.read_text().replace('(attr smd)','(attr smd allow_soldermask_bridges)'))
    fp.SetFPID(k.LIB_ID(lib,part)); fp.SetReference(c['ref']); fp.SetValue(c['value'])
    fp.SetPath(k.KIID_PATH('/'+uid('root')+'/'+uid(c['ref'])))
    board.Add(fp)
    x,y,angle=c['at']; fp.SetPosition(v(x,y))
    fp.SetOrientationDegrees(angle)
    if c['side'] in ['B','B-TH']: fp.Flip(v(x,y),k.FLIP_DIRECTION_LEFT_RIGHT)
    for p in fp.Pads():
        name=c['pins'].get(p.GetNumber())
        if name: p.SetNet(nets[name])
    fp.Reference().SetTextSize(v(.7,.7)); fp.Reference().SetTextThickness(k.FromMM(.12))
    fp.Reference().SetPosition(v(x,y-1.5))
    fp.Value().SetVisible(False)
    if c['ref']=='U1': fp.Reference().SetPosition(v(21,10.5))
    if c['ref']=='J1':
        fp.SetLayer(k.B_Cu)
        fp.SetAttributes(fp.GetAttributes()|k.FP_EXCLUDE_FROM_POS_FILES)
        fp.Reference().SetPosition(v(44,5.3)); fp.Reference().SetLayer(k.F_SilkS)
    if c['ref'].startswith('TP'):
        fp.Reference().SetPosition(v(x,y-1.35))
        fp.SetAttributes(fp.GetAttributes()|k.FP_EXCLUDE_FROM_BOM|k.FP_EXCLUDE_FROM_POS_FILES)
    fps[c['ref']]=fp

outline=[(2,0),(8.5,0),(9.5,1),(12.5,1),(13.5,0),(36.5,0),(37.5,1),(40.5,1),(41.5,0),(48,0),(50,2),(50,48),(48,50),(2,50),(0,48),(0,2)]
for a,b in zip(outline,outline[1:]+outline[:1]): line(board,a,b,k.Edge_Cuts,.05)
hole_info=[]
for i,(x,y,d) in enumerate([(3,3,3),(47,3,3),(3,47,3),(47,47,3),(7,3,1.8),(43,3,1.8),(7,47,1.8),(43,47,1.8)],1):
    fp=custom('MountingHole_'+str(d)+'mm'); fp.SetReference('H'+str(i)); fp.SetValue(str(d)+'mm NPTH')
    fp.SetAttributes(k.FP_EXCLUDE_FROM_BOM|k.FP_EXCLUDE_FROM_POS_FILES|k.FP_BOARD_ONLY)
    p=pad(fp,'',0,0,d,d,d); p.SetAttribute(k.PAD_ATTRIB_NPTH); p.SetLayerSet(all_copper_mask())
    fp.Reference().SetVisible(False); fp.Value().SetVisible(False)
    save_custom(fp,'MountingHole_'+str(d)+'mm')
    board.Add(fp); fp.SetPosition(v(x,y)); hole_info.append((x,y,d))
for i,(x,y) in enumerate([(4,8),(37,43),(4,32)],1):
    fp=custom('Fiducial_1mm'); fp.SetReference('FID'+str(i)); fp.SetValue('1mm fiducial')
    fp.SetAttributes(k.FP_SMD|k.FP_EXCLUDE_FROM_BOM|k.FP_EXCLUDE_FROM_POS_FILES|k.FP_BOARD_ONLY)
    p=pad(fp,'',0,0,1,1); p.SetShape(k.PAD_SHAPE_CIRCLE); p.SetLayerSet(lset([k.F_Cu,k.F_Mask])); p.SetLocalSolderMaskMargin(k.FromMM(.5)); p.SetLocalClearance(k.FromMM(.65))
    fp.Reference().SetVisible(False); fp.Value().SetVisible(False)
    save_custom(fp,'Fiducial_1mm')
    board.Add(fp); fp.SetPosition(v(x,y)); fp.Flip(v(x,y),k.FLIP_DIRECTION_LEFT_RIGHT)

def label(s,x,y,layer=k.B_SilkS,size=.8):
    t=k.PCB_TEXT(board); t.SetText(s); t.SetPosition(v(x,y)); t.SetTextSize(v(size,size)); t.SetTextThickness(k.FromMM(.13)); t.SetLayer(layer)
    t.SetMirrored(layer==k.B_SilkS); board.Add(t)
label('HD PLATINUM / REV A',22,6,k.B_SilkS,1)
label('FIRST ARTICLE',21,28,k.B_SilkS,.8)
label('2.4 GHz / 50 ohm',9.5,9,k.B_SilkS,.7)
label('CORE SIDE - MALE TAILS',24,23,k.F_SilkS,1)
label('HD PLATINUM  A',24,27,k.F_SilkS,1.4)
label('2026-10 / ENGINEERING',24,30,k.F_SilkS,.9)
for s,x in [('GND',8),('5V',12),('RF3V3',16),('CE',20)]: label(s,x,35.7,k.B_SilkS,.65)
for s,x in [('CSN',8),('IRQ',12),('HOST3V3',16)]: label(s,x,44,k.B_SilkS,.65)

def track(a,b,net,layer=k.B_Cu,width=.25):
    if math.dist(a,b)<.00001: return
    t=k.PCB_TRACK(board); t.SetStart(v(*a)); t.SetEnd(v(*b)); t.SetWidth(k.FromMM(width)); t.SetLayer(layer); t.SetNet(nets[net]); board.Add(t); return t
def via(x,y,net):
    p=k.PCB_VIA(board); p.SetPosition(v(x,y)); p.SetWidth(k.FromMM(.6)); p.SetDrill(k.FromMM(.3)); p.SetViaType(k.VIATYPE_THROUGH); p.SetLayerPair(k.F_Cu,k.B_Cu); p.SetNet(nets[net]); board.Add(p); return p
def getpad(ref,n): return next(p for p in fps[ref].Pads() if p.GetNumber()==str(n))

# Fixed, straight, short RF feed. Preserve Hirose's all-layer connector keepout.
track(mm(getpad('U1',11).GetPosition()),mm(getpad('J2',1).GetPosition()),'ANT',width=.35)

# Ground returns get direct vias; placement is checked against pad geometry.
from shapely.geometry import Point, box, LineString
from shapely.affinity import rotate
pad_geoms=[]
for fp in board.GetFootprints():
    for p in fp.Pads():
        x,y=mm(p.GetPosition()); w,h=mm(p.GetSize())
        geom=Point(x,y).buffer(w/2) if p.GetShape()==k.PAD_SHAPE_CIRCLE else rotate(box(x-w/2,y-h/2,x+w/2,y+h/2),p.GetOrientationDegrees(),origin=(x,y))
        pad_geoms.append((p,geom))
keepout=box(6.5-1.575,13.53-.95,6.5+.515,13.53+.95)
gnd_vias=[]
for p,geom in pad_geoms:
    if p.GetNetname()!='GND' or p.GetAttribute()!=k.PAD_ATTRIB_SMD: continue
    x,y=mm(p.GetPosition()); chosen=None
    for r in [.9,1.1,1.3,1.5,1.7,2.0]:
        for dx,dy in [(0,1),(0,-1),(1,0),(-1,0),(1,1),(-1,1),(1,-1),(-1,-1)]:
            X,Y=round(x+r*dx,2),round(y+r*dy,2)
            vshape=Point(X,Y).buffer(.5)
            trace=LineString([(x,y),(X,Y)]).buffer(.375)
            if vshape.intersects(keepout): continue
            if any(vshape.intersects(g) or (q.GetNetname()!='GND' and trace.intersects(g)) for q,g in pad_geoms if q is not p): continue
            if geom.buffer(.1).intersects(Point(X,Y).buffer(.3)): continue
            if any(math.dist((X,Y),z)<.8 for z in gnd_vias): continue
            chosen=(X,Y); break
        if chosen: break
    if not chosen: raise RuntimeError('No ground via for '+p.GetParentFootprint().GetReference()+'.'+p.GetNumber())
    via(*chosen,'GND'); track((x,y),chosen,'GND',width=.35); gnd_vias.append(chosen)
for x,y in [(4,18),(4,24),(9,18),(9,24),(13,10),(18,10),(23,10),(28,10),(13,27),(18,27),(23,27),(28,27),(3,35),(23,43),(30,43),(40,38),(48,20),(48,30),(18,3)]:
    shape=Point(x,y).buffer(.6)
    if not shape.intersects(keepout) and not any(shape.intersects(g) for p,g in pad_geoms):
        via(x,y,'GND')

# Dedicated via escapes prevent adjacent radio pads being boxed in by later routes.
for n in [3,4,5,6,8]:
    p=getpad('U1',n); x,y=mm(p.GetPosition()); name=p.GetNetname()
    track((x,y),(32.5,y),name,width=.25); via(32.5,y,name)
assert math.dist(mm(getpad('U1',1).GetPosition()),(30.6,14)) < .00001
assert math.dist(mm(getpad('U1',11).GetPosition()),(11.4,13.53)) < .00001
k.SaveBoard(str(OUT/(NAME+'.kicad_pcb')),board)
(ROOT/'design/pad-map.json').write_text(json.dumps({fp.GetReference():[{"pad":p.GetNumber(),"net":p.GetNetname(),"xy":mm(p.GetPosition()),"size":mm(p.GetSize())} for p in fp.Pads()] for fp in board.GetFootprints()},indent=2)+'\n')
# Use local libraries so opening the files does not depend on a global lib table.
libs=sorted({c['footprint'].split(':')[0] for c in SPEC['components']})
(OUT/'fp-lib-table').write_text('(fp_lib_table\n'+''.join(f' (lib (name "{l}")(type "KiCad")(uri "${{KIPRJMOD}}/{l}.pretty")(options "")(descr "Vendored project footprint"))\n' for l in libs)+')\n')
print('Placed',len(fps),'components; generated',OUT/(NAME+'.kicad_pcb'))
