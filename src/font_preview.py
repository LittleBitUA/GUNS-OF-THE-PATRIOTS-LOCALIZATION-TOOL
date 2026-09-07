# -*- coding: utf-8 -*-
r"""Draw a string exactly the way the engine will draw it.

The engine indexes a font atlas by the RAW BYTE: `cell = byte - 0x20`, on a
32-column grid.  So to see what a screen will show, take the bytes of the
string and blit those cells in order.  That is all this does — which is what
makes it useful: if the preview and the screenshot agree, your model of the
sheet is right.  If they disagree, the model is wrong, and you have learned
that without another rebuild-and-look round.

    python font_preview.py "TEXT" [atlas-id]
    python font_preview.py --cells [atlas-id]     dump the grid, cell-numbered
    python font_preview.py --bytes "9a 90 9c" [atlas-id]

`atlas-id` is a texture strcode, e.g. `00a2cbe0`.  Use `--cells` first on a
sheet you have not looked at before: it prints the ink coverage and the
horizontal extent of every cell in 0x80..0xDF, which tells you at a glance
which cells are empty, which hold punctuation, and where a repaint would land.

Output goes to the directory in MGS4_OUT, or ./font-preview.

Reading the result
------------------
Feed it the bytes your text will actually be stored as.  Two different
questions need two different inputs:

  * a string in raw UTF-8 -> pass the text; the lead bytes D0/D1 will land on
    whatever cells they land on, and you will see the sparse look they cause;
  * a string in a single-byte code page -> pass `--bytes`, because that is
    what the file will hold.

A glyph that comes out cut off is not the same as one that comes out small.
See docs/FONTS.md.
"""
from __future__ import annotations

import os
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import mgs4paths
import mgstex
import vpak
from txnup_unpack import Txn

COLS = 32
OUT = os.environ.get('MGS4_OUT', os.path.join(os.getcwd(), 'font-preview'))
UP_PAKS = ['common/textures/PC_TXN_UP/txn_up.1.pak',
           'common/textures/PC_TXN_UP/txn_up.2.pak',
           'ww/textures/PC_TXN_UP/txn_up.1.pak',
           'ww/textures/PC_TXN_UP/txn_up.2.pak']
DATA_PAKS = ['common/textures/PC_TXN_UP/paks/TextureData.pak',
             'ww/textures/PC_TXN_UP/paks/TextureData.pak']


def load_atlas(fid: str):
    """Alpha plane of the first large image with that strcode, as shipped.

    -> (alpha ndarray, where it came from)
    """
    game = mgs4paths.find_game()
    for rel in DATA_PAKS:
        data_pak = os.path.join(game, rel.replace('/', os.sep))
        if not os.path.exists(data_pak):
            continue
        dtoc = vpak.toc(data_pak)
        branch = rel.split('/')[0]
        for up in UP_PAKS:
            if not up.startswith(branch):
                continue
            p = os.path.join(game, up.replace('/', os.sep))
            if not os.path.exists(p):
                continue
            for name, rec in vpak.toc(p).items():
                if fid not in name:
                    continue
                t = Txn(name, vpak.fetch(p, rec))
                for img, blob in t.pairs():
                    if not blob or img['w'] < 256:
                        continue
                    if img['fmt'] not in (0x09, 0x0B):
                        continue
                    if blob['path'] not in dtoc:
                        continue
                    raw = vpak.fetch(data_pak, dtoc[blob['path']])
                    a = mgstex.decode_bc(raw, img['w'], img['h'], img['fmt'])
                    return a[:, :, 3], name
    raise SystemExit('atlas %s not found in the texture archives' % fid)


def cell_height(alpha, cw):
    """The reference sheet is 64x52; scale that ratio to this one."""
    return max(1, round(cw * 52 / 64))


def cell_of(alpha, cell, cw, ch):
    h, _w = alpha.shape
    r, k = divmod(cell, COLS)
    if (r + 1) * ch > h:
        return None
    return alpha[r * ch:(r + 1) * ch, k * cw:(k + 1) * cw]


def draw(alpha, data: bytes, tight: bool = True):
    """Blit one cell per byte.

    tight=True trims each glyph to its own ink, which is what a proportional
    renderer does; tight=False keeps the whole cell, which is what a
    fixed-advance one does.  Try both if the screenshot sits between them.
    """
    cw = alpha.shape[1] // COLS
    ch = cell_height(alpha, cw)
    canvas = np.zeros((ch, len(data) * (cw + 4) + 8), np.uint8)
    x = 0
    for b in data:
        blk = cell_of(alpha, b - 0x20, cw, ch)
        if blk is None:
            x += cw // 2
            continue
        if tight:
            xs = np.where(blk.max(0) > 8)[0]
            if not len(xs):
                x += cw // 3
                continue
            g = blk[:, xs.min():xs.max() + 1]
        else:
            g = blk
        gw = g.shape[1]
        canvas[:, x:x + gw] = np.maximum(canvas[:, x:x + gw], g)
        x += gw + max(2, cw // 16)
    return canvas[:, :x]


def cmd_cells(fid: str):
    alpha, where = load_atlas(fid)
    cw = alpha.shape[1] // COLS
    ch = cell_height(alpha, cw)
    rows = alpha.shape[0] // ch
    print('atlas %s -> %s  %dx%d, cell %dx%d, %d rows'
          % (fid, where, alpha.shape[1], alpha.shape[0], cw, ch, rows))

    scale = max(1, 48 // ch + 1)
    img = Image.fromarray(alpha[:rows * ch]).convert('RGB')
    img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    d = ImageDraw.Draw(img)
    for cell in range(rows * COLS):
        r, k = divmod(cell, COLS)
        d.rectangle([k * cw * scale, r * ch * scale,
                     (k + 1) * cw * scale - 1, (r + 1) * ch * scale - 1],
                    outline=(0, 90, 0))
        d.text((k * cw * scale + 2, r * ch * scale + 2), '%d' % cell,
               fill=(255, 60, 60))
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, 'cells_%s.png' % fid)
    img.save(p)
    print('->', p)

    for cell in range(rows * COLS):
        blk = cell_of(alpha, cell, cw, ch)
        if blk is None:
            continue
        byte = cell + 0x20
        if not 0x80 <= byte <= 0xDF:
            continue
        xs = np.where(blk.max(0) > 8)[0]
        span = '%2d..%2d' % (xs.min(), xs.max()) if len(xs) else '  empty'
        print('  cell %3d  byte %02X  ink %.3f  x %s'
              % (cell, byte, (blk > 8).mean(), span))


def main():
    argv = sys.argv[1:]
    if not argv:
        raise SystemExit(__doc__)

    if '--cells' in argv:
        i = argv.index('--cells')
        fid = argv[i + 1] if len(argv) > i + 1 else '00a2cbe0'
        return cmd_cells(fid)

    if '--bytes' in argv:
        i = argv.index('--bytes')
        data = bytes(int(x, 16) for x in argv[i + 1].split())
        rest = [a for j, a in enumerate(argv) if j not in (i, i + 1)]
        label = 'bytes'
    else:
        data = argv[0].encode('utf-8')
        rest = argv[1:]
        label = argv[0]
    fid = rest[0] if rest else '00a2cbe0'

    alpha, where = load_atlas(fid)
    print('atlas %s -> %s' % (fid, where))
    print('bytes: %s' % ' '.join('%02X' % b for b in data))
    os.makedirs(OUT, exist_ok=True)
    for tight, tag in ((True, 'prop'), (False, 'fixed')):
        im = Image.fromarray(draw(alpha, data, tight))
        im = im.resize((im.width * 2, im.height * 2), Image.NEAREST)
        p = os.path.join(OUT, 'preview_%s_%s.png' % (fid, tag))
        im.save(p)
        print('  %-5s -> %s' % (tag, p))


if __name__ == '__main__':
    main()
