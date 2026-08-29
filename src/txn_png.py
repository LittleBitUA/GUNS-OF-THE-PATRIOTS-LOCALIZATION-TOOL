# -*- coding: utf-8 -*-
r"""Lossless PNG round trip for MGS4 textures - edit without stacking losses.

The obvious workflow destroys the image, and it is not obvious why:

    original DXT1 -> unpack to .dds -> edit -> save as .dds -> re-encode

An editor saves whatever format it defaults to (usually DXT5), so the pixels go
through THREE lossy block compressions before they reach the game, on top of a
format change the descriptor never asked for.  Block compression keeps two
endpoint colours per 4x4 tile; each pass drags them further off, and smooth
gradients - a fox's body, a soft logo edge - fall apart into blotches while the
edit itself may have touched under 3 % of pixels.

With PNG in the middle there is exactly ONE lossy step, the final encode:

    original -> PNG (lossless) -> edit -> PNG -> encode once -> game

`inject` also re-encodes only the 4x4 blocks that actually changed, so
everything the artist did not touch keeps its original bytes and its original
quality.

    txn_png.py export --txn title/cache/00897aa9.txn
    txn_png.py inject edited.png --txn title/cache/00897aa9.txn --apply
"""
import argparse, csv, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
from PIL import Image
import lz4.block
import mgstex, mgsbc, vpak
import txn_inject as TI

import mgs4paths
INV = os.path.join(os.getcwd(), 'unpack',
                   'common_PC_TXN_UP', 'inventory.tsv')
PAK = mgs4paths.texture_pak('common')
OUT = os.path.join(os.getcwd(), 'edit')
FMT = {'DXT1': mgstex.DXT1, 'DXT5': mgstex.DXT5}


def rows_for(txn, img, inventory):
    rows = [r for r in csv.DictReader(open(inventory, encoding='utf-8'),
                                      delimiter='\t')
            if txn in r['txn'] and int(r['img']) == img]
    if not rows:
        raise SystemExit('nothing in the inventory matches %r img %d' % (txn, img))
    return rows


def cmd_export(a):
    rows = rows_for(a.txn, a.img, a.inventory)
    r = rows[0]
    w, h, fmt = int(r['w']), int(r['h']), FMT[r['format']]
    blob = vpak.fetch(a.pak, vpak.toc(a.pak)[r['blob_path']])
    rgba = mgstex.decode_bc(blob[:mgstex.level_size(w, h, fmt)], w, h, fmt)
    os.makedirs(a.out, exist_ok=True)
    stem = os.path.splitext(os.path.basename(r['txn']))[0]
    p = os.path.join(a.out, '%s_%02d_%dx%d_%s.png' % (stem, a.img, w, h, r['format']))
    Image.fromarray(rgba, 'RGBA').save(p)
    print('%s  %dx%d %s' % (os.path.basename(r['txn']), w, h, r['format']))
    print('   -> %s' % p)
    print('   edit this and keep it PNG.  The name records the format the game')
    print('   wants; inject reads it back from the inventory, not from the file.')


def cmd_inject(a):
    rows = rows_for(a.txn, a.img, a.inventory)
    im = Image.open(a.png).convert('RGBA')
    new = np.array(im, dtype=np.uint8)
    print('source PNG %dx%d' % (im.size[0], im.size[1]))

    for r in rows:
        w, h, fmt = int(r['w']), int(r['h']), FMT[r['format']]
        want = int(r['declared'])
        if im.size != (w, h):
            print('   resizing %dx%d -> %dx%d' % (im.size[0], im.size[1], w, h))
            src = np.array(Image.fromarray(new, 'RGBA').resize((w, h), Image.LANCZOS))
        else:
            src = new
        orig = vpak.fetch(a.pak, vpak.toc(a.pak)[r['blob_path']])
        blob, ch, tot = TI.patch_chain(orig, src, w, h, fmt)
        print('   %s' % r['blob_path'].split('/')[-1])
        print('      %d of %d blocks re-encoded (%.2f%%), %d bytes %s'
              % (ch, tot, 100.0 * ch / max(1, tot), len(blob),
                 'OK' if len(blob) == want else 'SIZE MISMATCH'))
        if len(blob) != want or not a.apply:
            if not a.apply:
                print('      (dry run - pass --apply)')
            continue
        relocate(a.pak, r['blob_path'], blob)


def relocate(pak, name, blob):
    """Append the blob before the TOC and re-point every alias at it."""
    recs = vpak.records(pak)
    rec = recs[name]
    aliases = [n for n, v in recs.items()
               if v['off'] == rec['off'] and v['unc'] == rec['unc']]
    comp = lz4.block.compress(blob, mode='high_compression', compression=12,
                              store_size=False)
    size = os.path.getsize(pak)
    with open(pak, 'rb') as f:
        f.seek(12)
        toc_size = struct.unpack('<I', f.read(4))[0]
    toc_at = size - toc_size
    with open(pak, 'r+b') as f:
        f.seek(toc_at)
        toc = f.read(toc_size)
        f.seek(toc_at)
        f.write(comp)
        f.write(toc)
        for n in aliases:
            r = recs[n]
            f.seek(r['field_off'] + len(comp) + 8)
            f.write(struct.pack('<QQ', len(comp), toc_at))
            if r['chunks']:
                f.seek(r['chunk_off'] + len(comp))
                f.write(struct.pack('<%dQ' % len(r['chunks']),
                                    *([0] * len(r['chunks']))))
    ok = vpak.fetch(pak, vpak.toc(pak)[name]) == blob
    print('      written at 0x%X, %d alias(es) re-pointed, verify %s'
          % (toc_at, len(aliases), 'OK' if ok else 'FAILED'))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('export', 'inject'):
        p = sub.add_parser(name)
        if name == 'inject':
            p.add_argument('png')
            p.add_argument('--apply', action='store_true')
        p.add_argument('--txn', required=True)
        p.add_argument('--img', type=int, default=0)
        p.add_argument('--inventory', default=INV)
        p.add_argument('--pak', default=PAK)
        p.add_argument('--out', default=OUT)
    a = ap.parse_args()
    (cmd_export if a.cmd == 'export' else cmd_inject)(a)


if __name__ == '__main__':
    main()
