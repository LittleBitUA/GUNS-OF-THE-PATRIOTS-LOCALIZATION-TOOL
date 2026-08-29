r"""Find the font sheets in an unpacked PC_TXN_UP tree, and preview them.

Runs over what `txnup_unpack.py` wrote - it does not touch the game.

Why this exists: the earlier font hunt in this project paired blobs to images
by searching for a mip chain of the right length, which is a guess.  The
inventory now carries the exact pairing, so every sheet's real width, height
and format are known, and a glyph-grid test can be run against the truth
rather than against a reconstruction.

A sheet is reported when its ink is periodic in both axes and it leaves the
gutter a font leaves at cell boundaries - the same structural detector in `mgstex`, calibrated on known font atlases.
"""

from __future__ import annotations

import argparse
import csv
import os
import struct
import sys

import numpy as np

import mgstex                                   # noqa: E402

FOURCC = {b'DXT1': mgstex.DXT1, b'DXT5': mgstex.DXT5, b'DXT3': mgstex.DXT5}


def read_dds(path: str):
    d = open(path, 'rb').read()
    if d[:4] != b'DDS ':
        return None
    h, w = struct.unpack_from('<2I', d, 12)
    fmt = FOURCC.get(d[84:88])
    if not fmt or not (0 < w <= 8192 and 0 < h <= 8192):
        return None
    n = mgstex.level_size(w, h, fmt)
    if 128 + n > len(d):
        return None
    try:
        return mgstex.decode_bc(d[128:128 + n], w, h, fmt), w, h, fmt
    except Exception:
        return None


def scan(root: str, out_dir: str, min_px: int = 64, max_px: int = 4 << 20,
         preview: bool = True, limit: int = 0) -> dict:
    from PIL import Image
    dds_root = os.path.join(root, 'dds')
    os.makedirs(out_dir, exist_ok=True)
    rows, n, hits = [], 0, 0

    for dirpath, _dirs, files in os.walk(dds_root):
        for fn in sorted(files):
            if not fn.lower().endswith('.dds'):
                continue
            p = os.path.join(dirpath, fn)
            r = read_dds(p)
            n += 1
            if not r:
                continue
            rgba, w, h, fmt = r
            if w * h < min_px or w * h > max_px:
                continue
            ink = mgstex.ink_map(rgba)
            hit = mgstex.looks_like_atlas(ink, loose=True)
            if not hit:
                continue
            hits += 1
            rel = os.path.relpath(p, dds_root)
            rows.append({'file': rel, 'w': w, 'h': h,
                         'format': 'DXT5' if fmt == mgstex.DXT5 else 'DXT1',
                         'cell_h': hit[0], 'rows': hit[1], 'az_hits': hit[2],
                         'ink': round(float((ink > 8).mean()), 4)})
            if preview:
                d = os.path.join(out_dir, os.path.dirname(rel))
                os.makedirs(d, exist_ok=True)
                png = os.path.join(d, os.path.splitext(os.path.basename(rel))[0]
                                   + '.png')
                Image.fromarray(255 - rgba[..., 3]).save(png)
            if limit and hits >= limit:
                break
        if limit and hits >= limit:
            break

    with open(os.path.join(out_dir, 'font_sheets.tsv'), 'w', encoding='utf-8',
              newline='') as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else
                            ['file', 'w', 'h', 'format', 'cell_h', 'rows',
                             'az_hits', 'ink'], delimiter='\t')
        wr.writeheader()
        wr.writerows(rows)
    return {'dds_seen': n, 'font_like': hits, 'out': out_dir}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('root', help='what txnup_unpack.py wrote')
    ap.add_argument('out', help='where to put previews and the report')
    ap.add_argument('--no-preview', action='store_true')
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    s = scan(a.root, a.out, preview=not a.no_preview, limit=a.limit)
    print('\n'.join('%-10s %s' % kv for kv in s.items()))


if __name__ == '__main__':
    main()
