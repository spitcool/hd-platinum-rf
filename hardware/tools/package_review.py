#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Create an engineering-review archive and file checksums, without ordering."""
from pathlib import Path
import hashlib, zipfile
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent
archive=ROOT/'hd-platinum-carrier-rev-a-review.zip'
def include(p):
    return p.is_file() and p.name != '.DS_Store' and p not in [archive,ROOT/'SHA256SUMS',ROOT/(archive.name+'.sha256')] and '__pycache__' not in p.parts and p.suffix not in ['.pyc','.kicad_prl','.lck']
files=sorted(p for p in ROOT.rglob('*') if include(p))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
(ROOT/'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.relative_to(ROOT)}\n' for p in files))
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for p in files+[ROOT/'SHA256SUMS']:z.write(p,p.relative_to(REPO))
    for name in ['LICENSE','LICENSING.md','LICENSES/AGPL-3.0-or-later.txt','LICENSES/CC-BY-SA-4.0.txt']:
        z.write(REPO/name,name)
    z.writestr('README-HARDWARE-ARCHIVE.txt','HD Platinum carrier Rev A - engineering first article\n\nStart with hardware/README.md. Native KiCad source, manufacturing files,\nvalidation reports, source references and tools are included. Links into\nthe software repository require the full repository checkout; this archive\ncontains hardware only. Physical fit, RF behavior and deployable ESP32\nfirmware remain qualification work. No production release is implied.\n')
(ROOT/(archive.name+'.sha256')).write_text(f'{sha(archive)}  {archive.name}\n')
with zipfile.ZipFile(archive) as z:assert z.testzip() is None
print('Created',archive.name,'with',len(files),'hardware files; archive CRCs verified')
