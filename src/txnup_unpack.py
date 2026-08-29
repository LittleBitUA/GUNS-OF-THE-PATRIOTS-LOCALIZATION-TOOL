r"""Unpack a whole PC_TXN_UP texture tree - index, blobs, and the join.

READ ONLY.  Nothing here writes into the game directory; everything lands
under `--out`.

## The three files

    txn_up.1.pak / txn_up.2.pak   the INDEX - one VPAK entry per source .txn
    paks/TextureData.pak          the DATA  - one VPAK entry per pixel buffer

## The .txn, decoded

Big-endian header, then two descriptor tables and a tail of path slots:

    0x00  u32 _, u32 flags, u32 imageCount, u32 imageOff,
          u32 texCount,     u32 texOff,     u32 0, u32 0

    image[i]   16 bytes:  u32 (w << 16) | h
                          u32 (format << 16) | mipFlags     format 0x0B = DXT5
                          u32 start, u32 end                cumulative, padded to 16

    texture[i] 48 bytes:  u32 type, u32 hash, u32 setStrcode,
                          u32 (w << 16) | h, ..., f32 uScale, f32 vScale, ...

    tail       imageCount slots of 256 bytes:
                          the blob's build path as ASCII, NUL padded
                          +0xFC  u32 little-endian uncompressed size

Note the mixed endianness - the header and descriptors are big-endian, the
size at +0xFC is little-endian.

## The join, and why it is now exact

**Image descriptor `i` pairs with path slot `i`, positionally**, and the sizes
agree exactly: on `0060c85f.txn` all twelve images match their slot's +0xFC
size byte for byte, including the odd ones (349 584 for a 1024x256, 174 800 for
a 256x512, 699 088 for a 512x1024).  Earlier work here paired blobs by
searching for a mip-chain of the right length, which is guesswork that goes
wrong the moment two textures share a size; there is no need for it.

The path stored in the slot is an **exact key** into `TextureData.pak`'s TOC -
not a suffix, not a normalised form.  Verified on every blob this tool
resolves.  The paths span `WW/`, `master/`, `platforms/PC/` and `temp/`, so
filtering to any one of those loses real data.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import vpak

FORMATS = {0x09: 'DXT1', 0x0A: 'DXT3', 0x0B: 'DXT5', 0x03: 'RGBA32'}
FOURCC = {0x09: b'DXT1', 0x0A: b'DXT3', 0x0B: b'DXT5'}
SLOT = 256
SIZE_AT = 0xFC


class Txn:
    """One parsed .txn index entry."""

    def __init__(self, name: str, data: bytes):
        self.name = name
        self.data = data
        (_, self.flags, self.n_img, self.img_off,
         self.n_tex, self.tex_off, _z1, _z2) = struct.unpack_from('>8I', data, 0)
        self.images, self.textures, self.blobs = [], [], []

        for i in range(self.n_img):
            dims, fmtw, start, end = struct.unpack_from('>4I', data, self.img_off + i * 16)
            self.images.append({
                'index': i, 'w': dims >> 16, 'h': dims & 0xFFFF,
                'fmt': fmtw >> 16, 'mip': fmtw & 0xFFFF,
                'start': start, 'end': end, 'size': end - start})

        for i in range(self.n_tex):
            r = struct.unpack_from('>12I', data, self.tex_off + i * 48)
            self.textures.append({
                'index': i, 'type': r[0], 'hash': r[1], 'set': r[2],
                'w': r[3] >> 16, 'h': r[3] & 0xFFFF, 'img': r[5],
                'u': struct.unpack('>f', struct.pack('>I', r[7]))[0],
                'v': struct.unpack('>f', struct.pack('>I', r[8]))[0]})

        tail = self.tex_off + self.n_tex * 48
        for i in range((len(data) - tail) // SLOT):
            s = data[tail + i * SLOT: tail + (i + 1) * SLOT]
            path = s.split(b'\0')[0].decode('latin1')
            size = struct.unpack_from('<I', s, SIZE_AT)[0]   # LE, unlike the rest
            self.blobs.append({'index': i, 'path': path, 'size': size})

    def pairs(self):
        """(image, blob) - positional, and the sizes are expected to agree."""
        for img in self.images:
            blob = self.blobs[img['index']] if img['index'] < len(self.blobs) else None
            yield img, blob


def dds_header(w: int, h: int, fmt: int, mips: int = 0) -> bytes:
    """A minimal DDS header so a blob can be opened in any viewer."""
    cc = FOURCC.get(fmt)
    if not cc:
        return b''
    flags = 0x0002100F | (0x00020000 if mips > 1 else 0)
    caps = 0x00001000 | (0x00400008 if mips > 1 else 0)
    hdr = bytearray(128)
    hdr[0:4] = b'DDS '
    struct.pack_into('<7I', hdr, 4, 124, flags, h, w, 0, 0, mips or 1)
    struct.pack_into('<2I', hdr, 76, 32, 0x4)          # pf size, FOURCC flag
    hdr[84:88] = cc
    struct.pack_into('<I', hdr, 108, caps)
    return bytes(hdr)


def mip_count(w: int, h: int, total: int, fmt: int) -> int:
    """How many levels `total` bytes covers - derived, not guessed."""
    block = 8 if fmt == 0x09 else 16
    n, acc, cw, ch = 0, 0, w, h
    while cw >= 1 and ch >= 1 and acc < total:
        acc += max(1, (cw + 3) // 4) * max(1, (ch + 3) // 4) * block
        n += 1
        if acc >= total:
            break
        cw, ch = max(1, cw // 2), max(1, ch // 2)
    return n


def unpack(base: str, out: str, write_dds: bool = True,
           write_txn: bool = True, limit: int = 0) -> dict:
    idx_paks = [p for p in (os.path.join(base, 'txn_up.1.pak'),
                            os.path.join(base, 'txn_up.2.pak'))
                if os.path.isfile(p)]
    data_pak = os.path.join(base, 'paks', 'TextureData.pak')
    if not idx_paks or not os.path.isfile(data_pak):
        raise SystemExit('%s: not a PC_TXN_UP tree' % base)

    blobs = vpak.toc(data_pak)
    os.makedirs(out, exist_ok=True)
    rows, stats = [], {'txn': 0, 'images': 0, 'resolved': 0, 'missing': 0,
                       'size_ok': 0, 'size_bad': 0, 'written': 0}
    missing = []

    inv = open(os.path.join(out, 'inventory.tsv'), 'w', encoding='utf-8')
    inv.write('txn\timg\tw\th\tformat\tmips\tdeclared\tblob_size\tmatch\t'
              'blob_path\tin_pak\n')

    for pak in idx_paks:
        toc = vpak.toc(pak)
        for k, (name, rec) in enumerate(sorted(toc.items())):
            if limit and stats['txn'] >= limit:
                break
            try:
                raw = vpak.fetch(pak, rec)
                t = Txn(name, raw)
            except Exception as exc:
                inv.write('%s\tPARSE FAILED: %s\n' % (name, exc))
                continue
            stats['txn'] += 1

            if write_txn:
                p = os.path.join(out, 'txn', name.replace('/', os.sep))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, 'wb') as fh:
                    fh.write(raw)

            for img, blob in t.pairs():
                stats['images'] += 1
                bp = blob['path'] if blob else ''
                in_pak = bp in blobs
                agree = bool(blob) and blob['size'] == img['size']
                stats['size_ok' if agree else 'size_bad'] += 1
                if in_pak:
                    stats['resolved'] += 1
                elif bp:
                    stats['missing'] += 1
                    missing.append(bp)
                inv.write('%s\t%d\t%d\t%d\t%s\t%d\t%d\t%d\t%s\t%s\t%s\n' % (
                    name, img['index'], img['w'], img['h'],
                    FORMATS.get(img['fmt'], '0x%X' % img['fmt']), img['mip'],
                    img['size'], blob['size'] if blob else -1,
                    'yes' if agree else 'NO', bp, 'yes' if in_pak else 'NO'))

                if write_dds and in_pak:
                    try:
                        payload = vpak.fetch(data_pak, blobs[bp])
                    except Exception:
                        continue
                    n = mip_count(img['w'], img['h'], len(payload), img['fmt'])
                    head = dds_header(img['w'], img['h'], img['fmt'], n)
                    if not head:
                        continue
                    rel = os.path.splitext(name)[0].replace('/', os.sep)
                    d = os.path.join(out, 'dds', rel)
                    os.makedirs(d, exist_ok=True)
                    with open(os.path.join(d, '%02d_%dx%d.dds'
                                           % (img['index'], img['w'], img['h'])),
                              'wb') as fh:
                        fh.write(head)
                        fh.write(payload)
                    stats['written'] += 1

            if stats['txn'] % 100 == 0:
                print('  %d .txn, %d images, %d written'
                      % (stats['txn'], stats['images'], stats['written']),
                      flush=True)
    inv.close()
    if missing:
        with open(os.path.join(out, 'missing_blobs.txt'), 'w',
                  encoding='utf-8') as fh:
            fh.write('\n'.join(sorted(set(missing))))
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('base', help='a PC_TXN_UP directory')
    ap.add_argument('out', help='where to write (never the game folder)')
    ap.add_argument('--no-dds', action='store_true', help='inventory only')
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    game = 'steamapps' in a.out.lower().replace('/', '\\')
    if game:
        raise SystemExit('refusing to write inside the game directory')
    s = unpack(a.base, a.out, write_dds=not a.no_dds, limit=a.limit)
    print('\n'.join('%-10s %d' % (k, v) for k, v in s.items()))


if __name__ == '__main__':
    main()
