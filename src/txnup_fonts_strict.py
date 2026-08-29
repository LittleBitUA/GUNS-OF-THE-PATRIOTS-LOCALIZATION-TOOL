r"""Re-filter the loose font candidates with the strict atlas test.

`txnup_fonts.py` runs `looks_like_atlas(loose=True)` because that is cheap over
tens of thousands of textures, but on MGS4 art it is far too permissive - it
flags hair sheets and opaque body textures whose ink happens to be periodic.
On the `ww` tree it returned 1 264 hits of which only 63 were real.

The strict test adds the two things a font actually has and a noise texture
does not: a clear first cell, and a gutter at the cell boundary (`gap_score`).
It also groups the survivors by content hash, because these sheets are
duplicated heavily - the main Latin-1 face exists in 53 identical copies in
`ww` alone, and patching one of them changes nothing on screen.
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import os
import struct
import sys

import numpy as np

import mgstex                                          # noqa: E402

FCC = {b'DXT1': mgstex.DXT1, b'DXT5': mgstex.DXT5, b'DXT3': mgstex.DXT5}


def load(path):
    d = open(path, 'rb').read()
    if d[:4] != b'DDS ':
        return None
    h, w = struct.unpack_from('<2I', d, 12)
    fmt = FCC.get(d[84:88])
    if not fmt:
        return None
    n = mgstex.level_size(w, h, fmt)
    if 128 + n > len(d):
        return None
    try:
        return mgstex.decode_bc(d[128:128 + n], w, h, fmt), w, h, d
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('root', help='the unpacked tree (has dds/ inside)')
    ap.add_argument('loose', help='font_sheets.tsv from txnup_fonts.py')
    ap.add_argument('out', help='where to write previews and strict.tsv')
    a = ap.parse_args()

    dds_root = os.path.join(a.root, 'dds')
    rows = list(csv.DictReader(open(a.loose, encoding='utf-8'), delimiter='\t'))
    os.makedirs(a.out, exist_ok=True)
    from PIL import Image

    groups = collections.defaultdict(list)
    kept = {}
    for i, r in enumerate(rows):
        p = os.path.join(dds_root, r['file'])
        got = load(p)
        if not got:
            continue
        rgba, w, h, raw = got
        ink = mgstex.ink_map(rgba)
        hit = mgstex.looks_like_atlas(ink, loose=False)
        if not hit:
            continue
        sha = hashlib.sha1(raw).hexdigest()[:12]
        groups[sha].append(r['file'])
        if sha not in kept:
            kept[sha] = (w, h, hit, ink)
        if (i + 1) % 2000 == 0:
            print('   %d / %d checked, %d distinct so far'
                  % (i + 1, len(rows), len(groups)), flush=True)

    order = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    with open(os.path.join(a.out, 'strict.tsv'), 'w', encoding='utf-8') as fh:
        fh.write('sha\tcopies\tw\th\tcell_h\trows\taz\tfile\n')
        for sha, files in order:
            w, h, hit, _ink = kept[sha]
            for f in files:
                fh.write('%s\t%d\t%d\t%d\t%d\t%d\t%d\t%s\n'
                         % (sha, len(files), w, h, hit[0], hit[1], hit[2], f))
    for sha, files in order:
        w, h, hit, ink = kept[sha]
        Image.fromarray((255 - np.clip(ink, 0, 255)).astype(np.uint8)).save(
            os.path.join(a.out, '%s_%dx%d_x%d.png' % (sha, w, h, len(files))))

    print('\nstrict atlases: %d occurrences, %d distinct'
          % (sum(len(v) for v in groups.values()), len(groups)))
    for sha, files in order[:25]:
        w, h, hit, _ = kept[sha]
        print('   %s %5dx%-5d cell%3d rows%2d az%3d  x%d'
              % (sha, w, h, hit[0], hit[1], hit[2], len(files)))


if __name__ == '__main__':
    main()
