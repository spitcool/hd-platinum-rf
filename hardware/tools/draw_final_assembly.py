#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Draw the appliance stack as an original vector illustration (not a fit model).

Uses the existing hardware Docker image's ReportLab and Poppler installation.
Vendor cases/ports are schematic; PCB perimeter comes from the reference JSON.
"""
from pathlib import Path
import json
import math
import subprocess

from reportlab.graphics import renderPDF, renderSVG
from reportlab.graphics.shapes import Drawing, Rect, Polygon, Line, Circle, String, Path as ShapePath
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "manufacturing"
W, H = 1200, 900
INK = "#183246"
MUTED = "#607382"
LINE = "#CCD8DE"
TEAL = "#007F79"
MINT = "#EAF6F2"
GREEN = "#318B69"
GOLD = "#D4AA53"
AMBER = "#AC5D21"
WHITE = "#FFFFFF"

font_dir = Path("/usr/share/fonts/truetype/dejavu")
pdfmetrics.registerFont(TTFont("Diagram", str(font_dir / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DiagramBold", str(font_dir / "DejaVuSans-Bold.ttf")))
d = Drawing(W, H)


def rect(x, y, w, h, fill=WHITE, stroke=None, radius=0, sw=1):
    d.add(Rect(x, H-y-h, w, h, rx=radius, ry=radius,
               fillColor=HexColor(fill) if fill else None,
               strokeColor=HexColor(stroke) if stroke else None, strokeWidth=sw))


def poly(points, fill=WHITE, stroke=INK, sw=1):
    d.add(Polygon([v for x, y in points for v in (x, H-y)],
                  fillColor=HexColor(fill) if fill else None,
                  strokeColor=HexColor(stroke) if stroke else None, strokeWidth=sw))


def line(x1, y1, x2, y2, color=LINE, sw=1, dash=None):
    d.add(Line(x1, H-y1, x2, H-y2, strokeColor=HexColor(color),
               strokeWidth=sw, strokeDashArray=dash))


def circle(x, y, r, fill=WHITE, stroke=None, sw=1):
    d.add(Circle(x, H-y, r, fillColor=HexColor(fill) if fill else None,
                 strokeColor=HexColor(stroke) if stroke else None, strokeWidth=sw))


def text(s, x, y, size=12, bold=False, color=INK, anchor="start"):
    d.add(String(x, H-y, s, fontName="DiagramBold" if bold else "Diagram",
                 fontSize=size, fillColor=HexColor(color), textAnchor=anchor))


def lines(ss, x, y, size=12, leading=19, color=MUTED):
    for s in ss:
        text(s, x, y, size=size, color=color)
        y += leading


def arrow(x1, y1, x2, y2, color=TEAL, sw=1.8):
    line(x1, y1, x2, y2, color, sw)
    angle = math.atan2(y2-y1, x2-x1)
    length = 7
    poly([(x2, y2), (x2-length*math.cos(angle-.45), y2-length*math.sin(angle-.45)),
          (x2-length*math.cos(angle+.45), y2-length*math.sin(angle+.45))], color, None)


def curve(start, c1, c2, end, color=TEAL, sw=2):
    path = ShapePath(fillColor=None, strokeColor=HexColor(color), strokeWidth=sw)
    path.moveTo(start[0], H-start[1])
    path.curveTo(c1[0], H-c1[1], c2[0], H-c2[1], end[0], H-end[1])
    d.add(path)


def badge(n, x, y, color=INK):
    circle(x, y, 16, color)
    text(str(n), x, y+5, 14, True, WHITE, "middle")


def projection(x0, y0, scale=1):
    return lambda x, y, z=0: (x0+scale*(4.15*x+1.9*y), y0+scale*(-.75*x+1.13*y-2.3*z))


def face(p, corners, fill, stroke=INK, sw=.8):
    poly([p(*v) for v in corners], fill, stroke, sw)


def flat(p, x, y, w, h, z, fill, stroke=None):
    face(p, [(x,y,z),(x+w,y,z),(x+w,y+h,z),(x,y+h,z)], fill, stroke)


def block(p, x, y, w, h, top, depth, topcolor, front, side, stroke="#6D808C"):
    face(p, [(x,y,top),(x,y+h,top),(x,y+h,top-depth),(x,y,top-depth)], side, stroke)
    face(p, [(x,y+h,top),(x+w,y+h,top),(x+w,y+h,top-depth),(x,y+h,top-depth)], front, stroke)
    flat(p,x,y,w,h,top,topcolor,stroke)


def core(p):
    block(p,0,0,54,54,0,15.5,"#EDF1F2","#D5DEE2","#BECBD2")
    flat(p,2,2,50,50,.2,"#172632",None)
    flat(p,7,8,40,35,.3,"#234858",None)
    # Neutral shade glyphs, not a representation of implemented firmware UI.
    for x in (11,23,35):
        flat(p,x,13,8,23,.4,"#D5E8E7")
        for yy in (16,19,22,25,28):
            a,b=p(x+.5,yy,.5),p(x+7.5,yy,.5)
            line(*a,*b,"#6DA6A7",.8)
    # USB-C indication on a case side; port positions are schematic.
    face(p,[(0,22,-5),(0,30,-5),(0,30,-9),(0,22,-9)],"#3D5664",None)
    for yy in (38,41,44):
        a,b=p(0,yy,-5),p(0,yy,-9)
        line(*a,*b,"#889BA5",.9)


def ring(p):
    # Open enclosure frame, with visible inner walls and open centre.
    block(p,0,0,54,54,0,13.2,"#6B7B84","#263F4C","#1C3340")
    flat(p,3,3,48,48,.15,"#EAF6F2",None)
    face(p,[(3,3,0),(51,3,0),(51,3,-10),(3,3,-10)],"#82929B",None)
    face(p,[(51,3,0),(51,51,0),(51,51,-10),(51,3,-10)],"#405B69",None)
    # Front lips cover the walls in the physical viewing order.
    flat(p,0,51,54,3,.3,"#596F7C")
    flat(p,0,0,3,54,.3,"#667E8A")
    for x,y in [(5,5),(49,5),(5,49),(49,49)]:
        xx,yy=p(x,y,.4)
        circle(xx,yy,2.4,"#243C49")


def header(p, top=0, body=True, scale=1):
    if body:
        block(p,43.55,7.5,5,39,top,9.5,"#334652","#172C38","#203846")
    for y in [9.22+2.54*r for r in range(15)]:
        for x in (44.78,47.32):
            a,b = p(x,y,top),p(x,y,top+6.6)
            line(*a,*b,GOLD,1.3*scale)


def carrier(p):
    geom=json.loads((ROOT/"design/module132-mechanical.json").read_text())
    outline=[(x+2,y+2) for x,y in geom["outline_vertices"]]
    poly([p(x,y,-1.6) for x,y in outline],"#1E5C45",INK,.7)
    poly([p(x,y,0) for x,y in outline],"#419D79",INK,.9)
    for group in ("stack_holes","retention_holes"):
        for hole in geom[group]:
            x,y=p(hole["x"]+2,hole["y"]+2,.1)
            circle(x,y,hole["source_drill"]*.9,"#EAF6F2","#D2BE76",.8)
    # No top-side radio: all populated devices are beneath this visible face.
    for y in (14,18,22):
        a,b=p(12,y,.2),p(32,y,.2)
        line(*a,*b,"#7CC6A3",1)
    header(p,body=False)


def lan(p, small=False):
    block(p,0,0,54,54,0,28,"#E9EEF0","#CED9DE","#B6C7CF")
    flat(p,3,3,48,48,.1,"#D4DEE0","#8E9EA6")
    header(p,top=.4,body=False,scale=.55 if small else 1)
    flat(p,17,22,10,10,.3,"#273D47")
    for x,y in [(5,5),(49,5),(5,49),(49,49)]:
        xx,yy=p(x,y,.4)
        circle(xx,yy,1.8 if small else 2.8,"#4B626E")
    # RJ45 opening on a visible outer wall.
    face(p,[(21,54,-7),(36,54,-7),(36,54,-22),(21,54,-22)],"#69808B","#4E6371")
    face(p,[(22,54.1,-9),(35,54.1,-9),(35,54.1,-20),(22,54.1,-20)],"#142D3A",None)
    for x in range(24,33):
        a,b=p(x,54.2,-9),p(x,54.2,-11)
        line(*a,*b,GOLD,.55)


rect(0,0,W,H,"#FAFCFD")
rect(0,0,W,105,INK)
text("HD PLATINUM  /  HARDWARE REV A",36,30,12,True,"#9FCBCB")
text("Final assembly: the M5Stack shade bridge",36,68,29,True,WHITE)
text("Three enclosure layers. The custom radio carrier lives inside the middle M032 housing.",36,128,15)

text("EXPLODED VIEW  /  TOP TO BOTTOM",42,160,11,True,MUTED)
rect(42,315,746,229,MINT,None,12)

# Alignment guides are behind the exploded parts.
for x,y in [(3,3),(51,51)]:
    a=projection(91,219)(x,y,-15.5)
    b=projection(91,585)(x,y,0)
    line(*a,*b,"#BACAD2",1,[4,6])

core(projection(91,219))
carrier(projection(91,355))
ring(projection(91,451))
lan(projection(91,585))

badge(1,470,215)
text("CoreS3 SE",500,213,22,True)
text("M5Stack K128-SE",500,236,12,True,MUTED)
lines(["ESP32-S3 compute + touchscreen", "USB-C power enters this layer."],500,262,12)
line(416,238,449,238,"#91A8B4",1.2)

badge(2,470,345,TEAL)
text("M032 radio layer",500,343,22,True,TEAL)
text("Custom carrier PCB - lifted out for clarity",500,367,12,True)
lines(["50 x 50 mm carrier replaces the perfboard.",
       "Radio and components face DOWN inside.",
       "M5Stack A089 socket is part of this PCBA."],500,391,12,19)
line(420,378,450,378,TEAL,1.2)
text("Module13.2 Proto housing",500,475,16,True)
text("M5Stack M032 - retain this frame",500,498,12,True,MUTED)
text("The board and frame form ONE middle layer.",500,523,12,color=TEAL)
line(420,490,450,490,TEAL,1.2)
line(450,378,450,490,TEAL,1.2)
arrow(240,415,240,450,TEAL,1.7)

badge(3,470,585)
text("Base LAN v1.2",500,583,22,True)
text("M5Stack K012-B-V12",500,607,12,True,MUTED)
lines(["W5500 Ethernet + bottom enclosure", "RJ45 network connection enters here.",
       "No additional battery-bottom layer."],500,633,12,19)
line(420,627,449,627,"#91A8B4",1.2)
text("30-pin M-Bus passes through the carrier between Core and LAN base.",58,734,11,color=MUTED)

# Compact assembled view with external antenna and connection legends.
rect(815,151,349,288,WHITE,LINE,12)
text("ASSEMBLED APPLIANCE",837,178,12,True)
pbase=projection(840,286,.52)
lan(pbase,small=True)
ring(projection(840,286-13.2*2.3*.52,.52))
core(projection(840,286-(13.2+15.5)*2.3*.52,.52))
# An external whip and bulkhead are indicative positions, not a drill template.
rect(1018,198,10,98,"#263D4A",None,5)
rect(1016,291,14,14,"#273D47",None,3)
rect(1007,297,14,9,GOLD,"#9C7A35",2)
text("External",1041,240,11,True)
text("2.4 GHz",1041,256,11,True)
text("GW.11.A153",1041,275,10,color=MUTED)
text("RP-SMA",1031,339,10,True)
text("bulkhead",1031,354,10,color=MUTED)
line(1043,325,1017,306,MUTED,1)
text("USB-C",837,342,10,True)
line(866,329,875,282,MUTED,1)
text("Ethernet",899,370,10,True)
line(938,355,950,324,MUTED,1)
lines(["Core / M032 / LAN are the three case layers.",
       "Views simplify ports and antenna placement."],837,405,10,17)

# Section makes the otherwise hidden underside unambiguous.
rect(815,453,349,281,WHITE,LINE,12)
text("INSIDE THE M032",837,481,12,True,TEAL)
text("Simplified side section - Core above, LAN below",837,503,10,color=MUTED)
rect(845,552,305,90,"#F1F7F5")
rect(845,552,12,90,"#263F4C")
rect(1138,552,12,90,"#263F4C")
rect(857,552,281,7,GREEN,TEAL,.2)
# Regulator and RF connector are stylized; A089 direction follows design.
rect(871,559,14,8,GOLD,"#9C7A35")
rect(908,559,77,22,"#CAD5DA","#6C828E",2)
rect(1006,559,17,10,"#314A56")
rect(1076,559,37,68,"#233D4B",None,2)
for x in (1087,1102):
    line(x,552,x,526,GOLD,3)
    rect(x-2,618,4,10,"#95ACB4")
text("PCB",858,541,10,True,TEAL)
text("Male tails UP",1008,523,10,True)
text("F.Cu",915,547,8,color=TEAL)
text("RF2401F20",913,574,8,color=INK)
curve((878,567),(862,588),(868,610),(841,613),TEAL,2)
text("U.FL",865,596,9,True)
text("Radio shield",901,616,10,True)
line(944,601,944,583,MUTED,1)
text("A089",1095,645,10,True,INK,"middle")
lines(["All SMT parts face down into the ring.",
       "A089 female socket faces the LAN base.",
       "Coax stays inside; antenna is outside."],837,677,10.5,18)

line(36,755,1164,755,LINE,1)
text("INSTALLATION DETAILS",36,780,11,True,MUTED)
text("Keep the M032 frame",36,806,12,True)
lines(["Remove its original perforated PCB. Reuse its four",
       "M2 x 5 mm self-tapping PCB retention screws."],36,827,10.5,17)
text("Internal cable + external antenna",427,806,12,True)
lines(["CAB.628: U.FL-compatible plug to RP-SMA bulkhead.",
       "Add strain relief; mount antenna to the bulkhead."],427,827,10.5,17)
text("First-article fit details",838,806,12,True)
lines(["Confirm pin engagement, stack screw lengths",
       "and bulkhead hole location on an actual sample."],838,827,10.5,17)
text("HD-P / FA-01   |   2026-10-25   |   Exploded view, not to scale",36,880,9,color=MUTED)
text("Engineering first article - see final-assembly.md for parts and assembly sequence",1164,880,9,color=MUTED,anchor="end")

OUT.mkdir(parents=True,exist_ok=True)
pdf=OUT/"final-assembly.pdf"
c=canvas.Canvas(str(pdf),pagesize=(W,H))
c.setTitle("HD Platinum - M5Stack final assembly")
c.setAuthor("Christopher Spitler")
c.setSubject("Rev A: CoreS3 SE / M032 carrier layer / Base LAN v1.2")
renderPDF.draw(d,c,0,0)
c.showPage()
c.save()
svg=OUT/"final-assembly.svg"
renderSVG.drawToFile(d,str(svg))
# ReportLab's PDF font aliases are not installed browser fonts. Keep SVG text
# editable with an explicit family/fallback and bold weight, and add metadata.
svg_text=svg.read_text()
svg_text=svg_text.replace("font-family: DiagramBold;", "font-family: 'DejaVu Sans', Arial, sans-serif; font-weight: 700;")
svg_text=svg_text.replace("font-family: Diagram;", "font-family: 'DejaVu Sans', Arial, sans-serif;")
svg_text=svg_text.replace("<title>...</title>", "<title>HD Platinum - M5Stack final assembly</title>")
svg_text=svg_text.replace("<desc>...</desc>", "<desc>CoreS3 SE above M032 with the custom radio carrier inside, above Base LAN v1.2. Exploded view and side section; not to scale.</desc>")
svg_text=svg_text.replace("<svg ", "<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler\nSPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->\n<svg ",1)
svg.write_text(svg_text)
subprocess.run(["pdftoppm","-singlefile","-scale-to","2400","-png",str(pdf),str(ROOT/"reports/final-assembly")],check=True)
print("Created final-assembly.pdf, final-assembly.svg and reports/final-assembly.png")
