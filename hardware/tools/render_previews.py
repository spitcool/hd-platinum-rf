#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Render the final drawings and routed bottom copper for visual review."""
from pathlib import Path
import subprocess, tempfile
from PIL import Image, ImageChops
ROOT=Path(__file__).resolve().parents[1]
def run(*args):subprocess.run(list(map(str,args)),check=True)
for src,dst,size in [('assembly-bottom.pdf','assembly',1500),('fabrication-drawing.pdf','fabrication',1500),('schematic.pdf','schematic',1800)]:
    run('pdftoppm','-scale-to',size,'-png','-singlefile',ROOT/'manufacturing'/src,ROOT/'reports'/dst)
with tempfile.TemporaryDirectory() as temp:
    d=Path(temp)
    run('kicad-cli','pcb','export','pdf','--layers','B.Cu,B.SilkS,Edge.Cuts','--mirror','--mode-single','--output',d/'copper.pdf',ROOT/'kicad/hd-platinum-carrier-rev-a.kicad_pcb')
    run('pdftoppm','-scale-to',5000,'-png','-singlefile',d/'copper.pdf',d/'copper')
    im=Image.open(d/'copper.png').convert('RGB');bb=ImageChops.difference(im,Image.new('RGB',im.size,'white')).getbbox()
    im.crop((max(0,bb[0]-12),max(0,bb[1]-12),min(im.width,bb[2]+12),min(im.height,bb[3]+12))).save(ROOT/'reports/bottom-copper.png')
