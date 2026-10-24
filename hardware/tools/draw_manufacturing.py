#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Readable assembly and fabrication drawings, extracted from native PCB."""
from pathlib import Path
import json, math
import pcbnew as k
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4,landscape
from reportlab.lib.colors import HexColor,white,black
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import simpleSplit
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'manufacturing'
SPEC=json.loads((ROOT/'design/board-spec.json').read_text())
b=k.LoadBoard(str(ROOT/'kicad'/f"{SPEC['name']}.kicad_pcb"))
pdfmetrics.registerFont(TTFont('DejaVu','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
pdfmetrics.registerFont(TTFont('DejaVuBold','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))
W,H=landscape(A4);BLUE=HexColor('#153852');MUTED=HexColor('#546875');RED=HexColor('#9d352c')
def xy(p):return k.ToMM(p.x),k.ToMM(p.y)
def text(c,s,x,y,size=9,bold=False,color=BLUE):
    c.setFillColor(color);c.setFont('DejaVuBold' if bold else 'DejaVu',size);c.drawString(x,y,s)
def para(c,s,x,y,width=310,size=9):
    for line in simpleSplit(s,'DejaVu',size,width):text(c,line,x,y,size);y-=size*1.45
    return y-7
def header(c,title,subtitle):
    c.setFillColor(BLUE);c.rect(0,H-76,W,76,fill=1,stroke=0)
    text(c,'HD PLATINUM  /  CARRIER REV A',32,H-26,10,True,white)
    text(c,title,32,H-51,20,True,white)
    text(c,subtitle,32,H-96,9)
def footer(c,page):
    c.setStrokeColor(HexColor('#b9c6cf'));c.line(32,43,W-32,43)
    text(c,'ENGINEERING FIRST ARTICLE - physical fit and native-radio operation not yet validated',32,29,8,True,RED)
    text(c,'2026-10-24  |  '+page,W-160,13,7)
def draw_board(c,mirror=False,scale=8.50394,x0=40,y0=65,assembly=True):
    def p(x,y):return x0+(50-x if mirror else x)*scale,y0+(50-y)*scale
    c.setFillColor(HexColor('#edf4ef'));c.setStrokeColor(BLUE);c.setLineWidth(.8)
    outline=[(2,0),(8.5,0),(9.5,1),(12.5,1),(13.5,0),(36.5,0),(37.5,1),(40.5,1),(41.5,0),(48,0),(50,2),(50,48),(48,50),(2,50),(0,48),(0,2)]
    path=c.beginPath();path.moveTo(*p(*outline[0]))
    for q in outline[1:]:path.lineTo(*p(*q))
    path.close();c.drawPath(path,fill=1,stroke=1)
    if assembly:
        for fp in b.GetFootprints():
            for g in fp.GraphicalItems():
                if g.GetLayer()!=k.B_Fab or not hasattr(g,'GetShape'):continue
                c.setStrokeColor(HexColor('#49636f'));c.setLineWidth(.6)
                if g.GetShape()==k.SHAPE_T_SEGMENT:c.line(*p(*xy(g.GetStart())),*p(*xy(g.GetEnd())))
                elif g.GetShape()==k.SHAPE_T_RECT:
                    X,Y=p(*xy(g.GetStart()));XX,YY=p(*xy(g.GetEnd()))
                    c.rect(min(X,XX),min(Y,YY),abs(X-XX),abs(Y-YY),fill=0,stroke=1)
        # Radio shield and header are explicit physical envelopes.
        for x,y,w,h in [(11,12,20,13.02),(41.55,5.5,5,39)]:
            X,Y=p(x,y);XX,YY=p(x+w,y+h)
            c.setFillColor(HexColor('#d4dce0'));c.setStrokeColor(MUTED)
            c.rect(min(X,XX),min(Y,YY),abs(X-XX),abs(Y-YY),fill=1,stroke=1)
        X,Y=p(21,18.51);text(c,'U1  RF2401F20',X-45,Y+5,9,True);text(c,'shield faces you',X-39,Y-10,8)
    for fp in b.GetFootprints():
        for pad in fp.Pads():
            x,y=xy(pad.GetPosition());w,h=xy(pad.GetSize());X,Y=p(x,y)
            if pad.GetAttribute()==k.PAD_ATTRIB_NPTH:
                c.setFillColor(white);c.setStrokeColor(BLUE);c.circle(X,Y,w*scale/2,fill=1,stroke=1);continue
            if not assembly and fp.GetReference()!='J1':continue
            c.saveState();c.translate(X,Y);c.rotate((-1 if mirror else 1)*pad.GetOrientationDegrees())
            c.setFillColor(HexColor('#c9a44e'));c.setStrokeColor(HexColor('#88733f'));c.setLineWidth(.3)
            if pad.GetShape()==k.PAD_SHAPE_CIRCLE:c.circle(0,0,w*scale/2,fill=1,stroke=1)
            else:c.rect(-w*scale/2,-h*scale/2,w*scale,h*scale,fill=1,stroke=1)
            if pad.GetAttribute()==k.PAD_ATTRIB_PTH:
                c.setFillColor(white);c.circle(0,0,k.ToMM(pad.GetDrillSize().x)*scale/2,fill=1,stroke=0)
            c.restoreState()
        if assembly and fp.GetReference() not in ['U1','J1'] and fp.Reference().IsVisible():
            X,Y=p(*xy(fp.Reference().GetPosition()));c.setFillColor(BLUE);c.setFont('DejaVuBold',6.6);c.drawCentredString(X,Y-2,fp.GetReference())
    if assembly:
        u1=next(fp for fp in b.GetFootprints() if fp.GetReference()=='U1')
        for pad in u1.Pads():
            px,py=xy(pad.GetPosition());num=int(pad.GetNumber())
            X,Y=p(px-1.8 if num<=8 else px+1.8,py)
            c.setFillColor(RED if num==1 else BLUE);c.setFont('DejaVuBold',5.5);c.drawCentredString(X,Y-2,str(num))
        # A red dot marks the pin-1 corner of the SOT-23-5 body.
        X,Y=p(29.6,33.1);c.setFillColor(RED);c.circle(X,Y,1.8,fill=1,stroke=0)
        for label,x,y in [('1',45.32,7.22),('30',42.78,42.78)]:
            X,Y=p(x,y);text(c,label,X+9,Y-2,7,True,RED)
        X,Y=p(44,24);c.saveState();c.translate(X,Y);c.rotate(90);text(c,'J1 / A089 / HOUSING THIS SIDE',-100,0,8,True);c.restoreState()
        # RF trace is shown as routed, without decorative signal wiring.
        c.setStrokeColor(RED);c.setLineWidth(.35*scale);c.line(*p(7.55,13.53),*p(11.4,13.53))
    return p

c=canvas.Canvas(str(OUT/'assembly-bottom.pdf'),pagesize=(W,H))
c.setTitle('HD Platinum Rev A - bottom assembly')
header(c,'Bottom assembly','View into the expansion housing. Mirrored from normal PCB top coordinates. Drawing scale 3:1.')
draw_board(c,True)
y=H-124;x=495
for title,body in [
 ('Populate 18 SMT parts', 'All radio, power and passive parts mount on B.Cu, facing down into the M032 expansion ring. Use bom.csv and the native footprints for exact parts and land patterns.'),
 ('Install J1 separately', 'A089 is a through-hole pass-through socket. Female plastic housing faces you in this drawing. Male tails project through the PCB toward CoreS3 SE. Pin 1 is the square ground pad at the north end.'),
 ('RF connection', 'J2 is Hirose U.FL-R-SMT-1(10). U1 pad 11 connects by a straight 3.85 mm trace. Attach Taoglas CAB.628, then GW.11.A153 on the RP-SMA female bulkhead. Add cable strain relief.'),
 ('Placement convention', 'positions.csv is native KiCad bottom placement in mm: unmirrored X, negative Y from the top-left board origin, and KiCad bottom rotations. The assembler must map rotations to its machine library.'),
 ('Inspect before power', 'Confirm U1 pad 1, U2 pin 1 (red dot), RF pad 11 and all three radio ground pads. No component substitutions for U1. Do not populate the no-connect pad U2.4 with a bridge.'),
 ('Fit check', 'Radio body height 2.1 +/-0.1 mm; A089 housing 9.5 mm nominal. Verify PCB seat height, pin engagement, cable bend and all component clearances in the actual housing.')]:
    text(c,title,x,y,10,True);y-=16;y=para(c,body,x,y,310,8.6)
footer(c,'Assembly 1/1');c.showPage();c.save()

c=canvas.Canvas(str(OUT/'fabrication-drawing.pdf'),pagesize=(W,H))
c.setTitle('HD Platinum Rev A - fabrication drawing')
header(c,'Fabrication drawing','Top view, toward CoreS3 SE. Dimensions in mm. Native Edge.Cuts and drill files control geometry.')
p=draw_board(c,False,scale=7.5,x0=52,y0=90,assembly=False)
c.setStrokeColor(BLUE);c.setLineWidth(.5)
for a,z in [((0,-2),(50,-2)),((-2,0),(-2,50))]:c.line(*p(*a),*p(*z))
for x in [0,50]:c.line(*p(x,-1),*p(x,-3))
for y in [0,50]:c.line(*p(-1,y),*p(-3,y))
X,Y=p(22,-2.5);text(c,'50.00',X,Y,9,True)
X,Y=p(-5,25);c.saveState();c.translate(X,Y);c.rotate(90);text(c,'50.00',-13,0,9,True);c.restoreState()
text(c,'Board thickness 1.60 nominal; 2.00 corner chamfers.',52,65,8)
x=472;y=H-125
text(c,'Four layers / JLC04161H-7628',x,y,11,True);y-=20
for s in ['L1 F.Cu: signals + ground, 0.035 mm copper','Prepreg: 0.2104 mm, nominal Dk 4.4','L2 In1.Cu: ground, 0.0152 mm copper','Core: 1.065 mm, nominal Dk 4.6','L3 In2.Cu: ground, 0.0152 mm copper','Prepreg: 0.2104 mm, nominal Dk 4.4','L4 B.Cu: components + RF, 0.035 mm copper']:
    text(c,s,x,y,8.4);y-=15
y-=8;text(c,'Fabrication requirements',x,y,10,True);y-=17
y=para(c,'ENIG; lead-free process; FR-4. Minimum design track / space 0.20 / 0.20. Signal traces 0.25; power 0.50. Vias 0.60 land / 0.30 finished drill. Soldermask expansion 0.05; minimum web 0.10. Tent vias both sides. J2 has an intentional merged mask opening; preserve its copper keepout.',x,y,330,8.5)
y=para(c,'RF ANT: 0.35 mm trace, 0.50 mm side clearance to B.Cu ground, referenced to solid L3. Fabricator must confirm 50 ohm +/-10% using the actual stack and soldermask. No copper or drill changes without design review.',x,y,330,8.5)
y=para(c,'Drills: 4 x 3.00 NPTH at (3,3), (47,3), (3,47), (47,47). 4 x 1.80 NPTH at (7,3), (43,3), (7,47), (43,47). J1: 30 x 1.00 PTH on 2.54 pitch with 1.80 lands; row X=42.78 / 45.32, first Y=7.22.',x,y,330,8.5)
y=para(c,'Quote tolerances: routed outline +/-0.10; finished holes +/-0.08; board thickness +/-0.10 mm. Confirm actual M032 seat and A089 pin fit before approving a production batch. Board-only STEP excludes component heights and the enclosure.',x,y,330,8.5)
footer(c,'Fabrication 1/1');c.showPage();c.save()
print('Created assembly-bottom.pdf and fabrication-drawing.pdf')
