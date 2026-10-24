#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic two-signal-layer routing, with two unbroken ground planes.

This generator is a convenience, not an alternative to KiCad DRC or RF review.
The ANT feed is pre-routed by generate_pcb.py and never autorouted here.
"""
from pathlib import Path
import heapq, json, math, time
import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import Point, box, LineString, Polygon
from shapely.affinity import rotate
import pcbnew as k

ROOT=Path(__file__).resolve().parents[1]
NAME='hd-platinum-carrier-rev-a'
PATH=ROOT/'kicad'/f'{NAME}.kicad_pcb'
b=k.LoadBoard(str(PATH))
def v(x,y): return k.VECTOR2I(k.FromMM(x),k.FromMM(y))
def xy(p): return (k.ToMM(p.x),k.ToMM(p.y))
nets={n.GetNetname():n for n in b.GetNetInfo().NetsByNetcode().values()}
layers=[k.B_Cu,k.F_Cu]
STEP=.1; N=501
obstacles=[]
all_smd=[]
pads_by_net={}
holes=[]
transitions={}
for fp in b.GetFootprints():
    for p in fp.Pads():
        x,y=xy(p.GetPosition()); w,h=xy(p.GetSize())
        g=Point(x,y).buffer(w/2) if p.GetShape()==k.PAD_SHAPE_CIRCLE else rotate(box(x-w/2,y-h/2,x+w/2,y+h/2),p.GetOrientationDegrees(),origin=(x,y))
        ls=[i for i,L in enumerate(layers) if p.IsOnLayer(L)]
        if p.GetAttribute()==k.PAD_ATTRIB_NPTH: g=Point(x,y).buffer(w/2+.3)
        obstacles.append((p.GetNetname(),g,ls))
        if p.GetAttribute()==k.PAD_ATTRIB_PTH:
            holes.append((x,y,k.ToMM(p.GetDrillSize().x)/2,p.GetNetname()))
        if p.GetAttribute()==k.PAD_ATTRIB_SMD: all_smd.append(g)
        if p.GetNetname(): pads_by_net.setdefault(p.GetNetname(),[]).append((x,y,ls[0]))
for t in b.GetTracks():
    if isinstance(t,k.PCB_VIA): g=Point(*xy(t.GetPosition())).buffer(k.ToMM(t.GetWidth(k.F_Cu))/2); ls=[0,1]
    else: g=LineString([xy(t.GetStart()),xy(t.GetEnd())]).buffer(k.ToMM(t.GetWidth())/2); ls=[layers.index(t.GetLayer())]
    obstacles.append((t.GetNetname(),g,ls))
    if isinstance(t,k.PCB_VIA):
        x,y=xy(t.GetPosition()); holes.append((x,y,k.ToMM(t.GetDrillValue())/2,t.GetNetname()))
connector_keepout=box(4.925,12.58,7.015,14.48)
module_body=box(12,12.2,29.2,24.8)
outline=Polygon([(2,0),(8.5,0),(9.5,1),(12.5,1),(13.5,0),(36.5,0),(37.5,1),(40.5,1),(41.5,0),(48,0),(50,2),(50,48),(48,50),(2,50),(0,48),(0,2)])

def burn(draw,g,fill=1):
    if g.is_empty:return
    if hasattr(g,'geoms'):
        for h in g.geoms: burn(draw,h,fill)
        return
    draw.polygon([(round(x/STEP),round(y/STEP)) for x,y in g.exterior.coords],fill=fill)
    # Ignoring holes is intentionally conservative for obstacle masks.
def masks(net,width):
    ims=[Image.new('1',(N,N),1),Image.new('1',(N,N),1)]
    dr=[ImageDraw.Draw(i) for i in ims]
    for d in dr:burn(d,outline.buffer(-(.5+width/2)),0)
    for other,g,ls in obstacles:
        if other==net:continue
        for l in ls:burn(dr[l],g.buffer(.20+width/2+.025))
    for d in dr:burn(d,connector_keepout.buffer(width/2+.025))
    burn(dr[0],module_body)
    blocked=np.stack([np.asarray(i,dtype=np.bool_) for i in ims])
    im=Image.new('1',(N,N),1);d=ImageDraw.Draw(im)
    burn(d,outline.buffer(-.9),0)
    for other,g,ls in obstacles:
        if other!=net:burn(d,g.buffer(.20+.30+.025))
    for x,y,r,other in holes:burn(d,Point(x,y).buffer(r+.15+.25+.025))
    for g in all_smd:burn(d,g.buffer(.35)) # No via-in-pad.
    burn(d,connector_keepout.buffer(.35));burn(d,module_body.buffer(.35))
    no_via=np.asarray(im,dtype=np.bool_) | blocked[0] | blocked[1]
    transitions.clear()
    for x,y,r,other in holes:
        if other==net:
            X,Y=round(x/STEP),round(y/STEP)
            if not blocked[0,Y,X] and not blocked[1,Y,X]:
                no_via[Y,X]=False; transitions[(X,Y)]=(x,y)
    return blocked,no_via

def astar(a,z,blocked,no_via):
    sx,sy,sl=round(a[0]/STEP),round(a[1]/STEP),a[2]
    tx,ty,tl=round(z[0]/STEP),round(z[1]/STEP),z[2]
    if blocked[sl,sy,sx] or blocked[tl,ty,tx]:
        raise RuntimeError(f'Blocked endpoint {a} -> {z}')
    def idx(x,y,l):return (l*N+y)*N+x
    def unpack(i):return i%N,(i//N)%N,i//(N*N)
    start=idx(sx,sy,sl); goal=idx(tx,ty,tl)
    costs=np.full(2*N*N,np.inf); parent=np.full(2*N*N,-1,dtype=np.int32)
    costs[start]=0
    def heuristic(x,y,l):
        dx=abs(x-tx);dy=abs(y-ty)
        return max(dx,dy)+.41421356*min(dx,dy)+(45 if l!=tl else 0)
    heap=[(heuristic(sx,sy,sl),0,start)]
    moves=[(1,0,1),(-1,0,1),(0,1,1),(0,-1,1),(1,1,1.41421356),(-1,1,1.41421356),(1,-1,1.41421356),(-1,-1,1.41421356)]
    expanded=0
    while heap:
        _,cost,i=heapq.heappop(heap)
        if cost>costs[i]+1e-7:continue
        if i==goal:
            path=[]
            while i!=-1:path.append(unpack(i));i=int(parent[i])
            return path[::-1],expanded
        x,y,l=unpack(i); expanded+=1
        for dx,dy,dc in moves:
            X,Y=x+dx,y+dy
            if X<0 or X>=N or Y<0 or Y>=N or blocked[l,Y,X]:continue
            if dx and dy and (blocked[l,y,X] or blocked[l,Y,x]):continue
            j=idx(X,Y,l);nc=cost+dc
            if nc+1e-7<costs[j]:
                costs[j]=nc;parent[j]=i;heapq.heappush(heap,(nc+heuristic(X,Y,l),nc,j))
        if not no_via[y,x]:
            L=1-l;j=idx(x,y,L);nc=cost+(0.1 if (x,y) in transitions else 45)
            if nc+1e-7<costs[j]:
                costs[j]=nc;parent[j]=i;heapq.heappush(heap,(nc+heuristic(x,y,L),nc,j))
    raise RuntimeError(f'Unroutable {a} -> {z}; explored {expanded}')

def addtrack(a,z,net,layer,width):
    if math.dist(a,z)<.00001:return
    t=k.PCB_TRACK(b);t.SetStart(v(*a));t.SetEnd(v(*z));t.SetWidth(k.FromMM(width));t.SetLayer(layers[layer]);t.SetNet(nets[net]);b.Add(t)
    obstacles.append((net,LineString([a,z]).buffer(width/2),[layer]))
def addvia(x,y,net):
    t=k.PCB_VIA(b);t.SetPosition(v(x,y));t.SetWidth(k.FromMM(.6));t.SetDrill(k.FromMM(.3));t.SetLayerPair(k.F_Cu,k.B_Cu);t.SetViaType(k.VIATYPE_THROUGH);t.SetNet(nets[net]);b.Add(t)
    obstacles.append((net,Point(x,y).buffer(.3),[0,1])); holes.append((x,y,.15,net))
def connect(a,z,net,width):
    blocked,no_via=masks(net,width); path,count=astar(a,z,blocked,no_via)
    # Collapse collinear grid segments before writing native tracks.
    out=[path[0]];lastdir=None
    for prev,cur in zip(path,path[1:]):
        direction=tuple(cur[i]-prev[i] for i in range(3))
        if direction!=lastdir and prev!=out[-1]:out.append(prev)
        lastdir=direction
    if path[-1]!=out[-1]:out.append(path[-1])
    addtrack(a[:2],(path[0][0]*STEP,path[0][1]*STEP),net,a[2],width)
    for p,q in zip(out,out[1:]):
        if p[2]!=q[2]:
            if (p[0],p[1]) not in transitions:addvia(p[0]*STEP,p[1]*STEP,net)
        else:addtrack((p[0]*STEP,p[1]*STEP),(q[0]*STEP,q[1]*STEP),net,p[2],width)
    addtrack((path[-1][0]*STEP,path[-1][1]*STEP),z[:2],net,z[2],width)
    print(net,tuple(round(x,2) for x in a),tuple(round(x,2) for x in z),len(out),'segments',count,'nodes',flush=True)

order=['LDO_IN','RF_MISO','RF_3V3','BUS_5V','MOSI_HOST','MISO_HOST','CSN_HOST','CE_HOST','SCK_HOST','RF_CE','RF_CSN','RF_SCK','RF_MOSI','RF_IRQ','HOST_3V3']
connections=[]
for net in order:
    pts=pads_by_net[net]
    connected=[pts[0]];remaining=pts[1:]
    while remaining:
        dist,a,z=min((math.dist(a[:2],z[:2]),a,z) for a in connected for z in remaining)
        connections.append((dist,net,a,z))
        connected.append(z);remaining.remove(z)
for dist,net,a,z in sorted(connections):
    connect(a,z,net,.50 if net in ['LDO_IN','RF_3V3','BUS_5V'] else .25)

# Four-layer ground structure: solid L2/L3 planes, outer pours stitched together.
for layer in [k.F_Cu,k.In1_Cu,k.In2_Cu,k.B_Cu]:
    zone=k.ZONE(b);zone.SetLayer(layer);zone.SetNet(nets['GND'])
    zone.SetLocalClearance(k.FromMM(.2));zone.SetPadConnection(k.ZONE_CONNECTION_FULL)
    zone.SetThermalReliefGap(k.FromMM(.3));zone.SetThermalReliefSpokeWidth(k.FromMM(.3));zone.SetMinThickness(k.FromMM(.20))
    poly=zone.Outline();poly.NewOutline()
    for x,y in [(0,0),(50,0),(50,50),(0,50)]:poly.Append(int(k.FromMM(x)),int(k.FromMM(y)))
    b.Add(zone)

# Bottom RF feed has a 0.50 mm side clearance to coplanar ground. Internal ground
# is retained; the fab must calculate this microstrip/CPWG transition with mask.
keep=k.ZONE(b);keep.SetIsRuleArea(True);keep.SetLayer(k.B_Cu)
keep.SetDoNotAllowCopperPour(True);keep.SetDoNotAllowTracks(False);keep.SetDoNotAllowVias(False);keep.SetDoNotAllowPads(False);keep.SetDoNotAllowFootprints(False)
poly=keep.Outline();poly.NewOutline()
for x,y in [(7.05,12.855),(11.4,12.855),(11.4,14.205),(7.05,14.205)]:poly.Append(int(k.FromMM(x)),int(k.FromMM(y)))
b.Add(keep)
k.ZONE_FILLER(b).Fill(b.Zones())
k.SaveBoard(str(PATH),b)
print('Routed and filled',PATH,flush=True)
