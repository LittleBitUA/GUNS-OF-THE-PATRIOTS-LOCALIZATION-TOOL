# -*- coding: utf-8 -*-
r"""Put an edited .dds back into a PC_TXN_UP TextureData.pak - safely.

An edited texture almost never comes back in the shape the engine wants, and
the engine will not complain, it will read past the end of the blob.  Two
things have to be rebuilt rather than trusted:

  * the FORMAT.  An editor writes whatever it defaults to (usually DXT5 with
    no mips).  The descriptor in the .txn says what the engine will decode -
    e.g. title/00897aa9 is DXT1, and a DXT5 file of the right dimensions is
    still wrong.
  * the MIP CHAIN.  The blob length is fixed by the .txn.  A full chain down
    to 1x1 reproduces it exactly: 2048x512 DXT1 -> 699 080 bytes,
    2048x2048 DXT5 -> 5 592 432, which is what the inventory declares.

So: decode whatever the user saved, downscale, re-encode to the target format,
verify the byte count matches the declaration, and only then write.

The same texture usually exists under SEVERAL blob paths (title/00897aa9 has
one under `title/` and another under `stage00/title/`, with different hashes),
and each of those may be aliased by more TOC records again - vpak_write
handles the second part, this handles the first.
"""
import argparse, csv, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
from PIL import Image
import mgstex, mgsbc
import vpak

FMT = {'DXT1': mgstex.DXT1, 'DXT3': mgstex.DXT3, 'DXT5': mgstex.DXT5}
FCC = {mgstex.DXT1: b'DXT1', mgstex.DXT3: b'DXT3', mgstex.DXT5: b'DXT5'}


def read_dds(path):
    d = open(path, 'rb').read()
    if d[:4] != b'DDS ':
        raise SystemExit('%s is not a DDS' % path)
    h, w = struct.unpack_from('<2I', d, 12)
    fcc = d[84:88]
    fmt = FMT.get(fcc.decode('latin1', 'replace'))
    if fmt is None:
        raise SystemExit('%s: unsupported %r' % (path, fcc))
    n = mgstex.level_size(w, h, fmt)
    return mgstex.decode_bc(d[128:128 + n], w, h, fmt), w, h


def build_chain(rgba, w, h, fmt):
    """Full mip chain, encoded to `fmt`, down to 1x1."""
    out = bytearray()
    img = Image.fromarray(rgba, 'RGBA')
    cw, ch = w, h
    while True:
        lvl = np.array(img.resize((max(1, cw), max(1, ch)), Image.LANCZOS)
                       if (cw, ch) != img.size else img, dtype=np.uint8)
        pw_, ph = max(4, cw), max(4, ch)
        if lvl.shape[1] != pw_ or lvl.shape[0] != ph:      # BC needs 4x4 blocks
            pad = np.zeros((ph, pw_, 4), np.uint8)
            pad[:lvl.shape[0], :lvl.shape[1]] = lvl
            lvl = pad
        out += mgsbc.encode(lvl, fmt)
        if cw == 1 and ch == 1:
            break
        cw, ch = max(1, cw // 2), max(1, ch // 2)
    return bytes(out)


def patch_chain(orig, rgba, w, h, fmt):
    """Rebuild the blob, re-encoding ONLY what the edit actually reaches.

    Two separate reasons to leave a block alone, and the second one is easy to
    get wrong:

    * at level 0, the block's pixels are unchanged;
    * at a MIP level, the area it covers was unchanged at level 0.

    Testing a mip block by comparing it against a freshly downscaled image does
    not work: our resample filter is not the one the original tool used, so
    every mip block looks "different" and gets re-encoded.  That silently
    degraded ~7% of blocks on a texture with NO edit at all.  So the mask is
    computed once at level 0 and then scaled down, and a mip block is only
    touched when the edit really lands inside it.
    """
    stride = 8 if fmt == mgstex.DXT1 else 16
    out = bytearray(orig)
    base = mgstex.decode_bc(bytes(orig[:mgstex.level_size(w, h, fmt)]), w, h, fmt)
    dirty = np.abs(base.astype(int) - rgba.astype(int)).max(axis=2) > 8
    src = Image.fromarray(rgba, 'RGBA')

    pos, cw, ch, changed, total = 0, w, h, 0, 0
    while pos < len(orig):
        n = mgstex.level_size(cw, ch, fmt)
        if pos + n > len(orig):
            break
        want = rgba if (cw, ch) == (w, h) else             np.array(src.resize((cw, ch), Image.LANCZOS), dtype=np.uint8)
        # the level-0 mask, scaled to this level
        if (cw, ch) == (w, h):
            m = dirty
        else:
            m = np.array(Image.fromarray(dirty.astype(np.uint8) * 255)
                         .resize((cw, ch), Image.BOX), dtype=np.uint8) > 0
        bw = max(1, cw // 4)
        for by in range(0, max(4, ch), 4):
            for bx in range(0, max(4, cw), 4):
                total += 1
                if not m[by:by + 4, bx:bx + 4].any():
                    continue
                b = want[by:by + 4, bx:bx + 4]
                blk = np.zeros((4, 4, 4), np.uint8)
                blk[:b.shape[0], :b.shape[1]] = b
                o = pos + ((by // 4) * bw + (bx // 4)) * stride
                if o + stride <= len(out):
                    out[o:o + stride] = mgsbc.encode_block(blk, fmt)
                    changed += 1
        pos += n
        if cw == 1 and ch == 1:
            break
        cw, ch = max(1, cw // 2), max(1, ch // 2)
    return bytes(out), changed, total
