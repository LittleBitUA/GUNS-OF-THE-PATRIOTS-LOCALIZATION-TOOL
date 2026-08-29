r"""MGS4 PC VPAK texture archives - fully decoded 2026-08-27.

Three files under common\textures\PC_TXN_UP:

    txn_up.1.pak / txn_up.2.pak   the INDEX: one entry per source .txn
    paks\TextureData.pak          the DATA: one blob per pixel buffer

Both share one container format:

    header   'VPAK' u16 ver(3) u16 flags(1) u32 entryCount u32 tocSize
    body     entry regions, raw or LZ4-block-compressed (no framing)
    toc      last tocSize bytes: per entry
                 <name>\0  +7: u64 uncompressedSize, u64 compressedSize
                           (0 = stored raw), u64 offset, u32, u32, ...

The TOC field offsets are from the name's NUL with NO alignment - aligning
to 8 misreads half the records.  LZ4 is the plain block format, no dictionary,
no frame header; the bytes I once took for an 8-byte "block header" were the
first two tokens.  Entries are not 4-byte aligned, which is why signature
scans found only a fraction of them.

An INDEX entry decompresses to the same embedded-.txn shape the loose
additions files use (big-endian header `_, flag, nimg, ioff, ntex, toff, 0, 0`
then 16-byte image and 48-byte texture descriptors) followed by the asset's
build path and a small tail.  A DATA entry decompresses to the raw pixel
buffer its descriptors point into.

Index entry names and blob names share the same build path, so the join is
by name.
"""

from __future__ import annotations

import os
import re
import struct

import mgs4paths
BASE = mgs4paths.txn_up('common')

_NAME = re.compile(rb'[A-Za-z0-9_./-]{8,200}\.(txn|data)\x00')


def lz4(src: bytes, want: int | None = None) -> bytes:
    """Plain LZ4 block decode."""
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        tok = src[i]; i += 1
        lit = tok >> 4
        if lit == 15:
            while True:
                b = src[i]; i += 1
                lit += b
                if b != 255:
                    break
        out += src[i:i + lit]; i += lit
        if i >= n:
            break
        off = src[i] | (src[i + 1] << 8); i += 2
        ml = tok & 15
        if ml == 15:
            while True:
                b = src[i]; i += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        if want is not None and len(out) + ml > want:
            raise ValueError('overrun')
        for _ in range(ml):
            out.append(out[-off])
    if want is not None and len(out) != want:
        raise ValueError(f'expected {want}, got {len(out)}')
    return bytes(out)


def records(path: str):
    """Same walk as toc(), but also hands back where each record's fields sit
    in the FILE, so a writer can patch `compressed` and the chunk offsets in
    place without rebuilding the TOC.

    -> {name: dict(unc, comp, off, csize, chunks, field_off, chunk_off)}
    where field_off addresses the `uncompressed` u64 and chunk_off the first
    chunk offset, both as absolute file positions.
    """
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        magic, ver, flags, count, toc_size = struct.unpack('<4s2H2I', f.read(16))
        assert magic == b'VPAK', path
        toc_at = size - toc_size
        f.seek(toc_at)
        t = f.read(toc_size)
    out = {}
    p = 0
    for _ in range(count):
        nlen = struct.unpack_from('<I', t, p)[0]
        s, e = p + 6, p + 6 + nlen
        unc, comp, off = struct.unpack_from('<3Q', t, e + 8)
        csize, ccount = struct.unpack_from('<2I', t, e + 32)
        chunks = list(struct.unpack_from('<%dQ' % ccount, t, e + 40)) if ccount else []
        out[t[s:e].rstrip(b'\0').decode('latin1')] = dict(
            unc=unc, comp=comp, off=off, csize=csize, chunks=chunks,
            field_off=toc_at + e + 8, chunk_off=toc_at + e + 40)
        p = e + 40 + 8 * ccount
    assert len(out) == count, f'{path}: TOC {len(out)} != header {count}'
    return out


def toc(path: str, whole: bytes | None = None):
    """{name: (unc, comp, off, csize, chunks)} from the trailing TOC."""
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        head = f.read(16)
        magic, ver, flags, count, toc_size = struct.unpack('<4s2H2I', head)
        assert magic == b'VPAK', path
        f.seek(size - toc_size)
        t = f.read(toc_size)
    # The real TOC record layout, derived byte by byte 2026-08-28:
    #
    #   u32 name_len | u16 flags | char name[name_len] | u64 zero
    #   u64 uncompressed | u64 compressed (0 = raw) | u64 offset
    #   u32 chunk_size  | u32 chunk_count
    #   u64 chunk_offset[chunk_count]     <- relative to the entry's offset
    #
    # so records are VARIABLE length - which is why a fixed stride found only
    # 2 of the 5,000 entries in the stage paks, and the older name regex
    # (which knew .txn/.data only) found 873.
    #
    # The chunk list is the important part: anything over `chunk_size`
    # (1 MB) is stored as SEVERAL independently LZ4-compressed chunks, so it
    # cannot be decoded with one lz4() call.  See fetch().
    out = {}
    p = 0
    for _ in range(count):
        nlen = struct.unpack_from('<I', t, p)[0]
        s, e = p + 6, p + 6 + nlen
        unc, comp, off = struct.unpack_from('<3Q', t, e + 8)
        csize, ccount = struct.unpack_from('<2I', t, e + 32)
        chunks = list(struct.unpack_from('<%dQ' % ccount, t, e + 40)) if ccount else []
        out[t[s:e].rstrip(b'\0').decode('latin1')] = (unc, comp, off, csize, chunks)
        p = e + 40 + 8 * ccount
    assert len(out) == count, f'{path}: TOC {len(out)} != header {count}'
    return out


def fetch(path: str, rec) -> bytes:
    """One entry, decompressed.

    Entries bigger than `chunk_size` are stored as several independently
    LZ4-compressed chunks; each decodes to chunk_size except the last.
    Feeding the whole blob to one lz4() call silently truncates them.
    """
    unc, comp, off, csize, chunks = _rec(rec)
    with open(path, 'rb') as f:
        f.seek(off)
        raw = f.read(comp if comp else unc)
    if not comp:
        return raw
    if len(chunks) <= 1:
        return lz4(raw, unc)
    out = bytearray()
    ends = list(chunks[1:]) + [len(raw)]
    for start, end in zip(chunks, ends):
        want = min(csize, unc - len(out))
        out += lz4(raw[start:end], want)
    return bytes(out)


def _rec(rec):
    """Accept both the new 5-field record and the old 3-field one."""
    if len(rec) == 5:
        return rec
    unc, comp, off = rec
    return unc, comp, off, 0, []


def index_entries():
    """Yield (index_name, images, textures, blob_path) over both index paks.

    images:   [{w,h,fmt,flag,off,mip}]   descriptors, big-endian
    textures: [{tex,txn,w,h,x,y,img}]
    blob_path: the build path stored inside the entry = the TextureData name.
    """
    for pak in ('txn_up.1.pak', 'txn_up.2.pak'):
        p = os.path.join(BASE, pak)
        for name, rec in toc(p).items():
            d = fetch(p, rec)
            _, flag, nimg, ioff, ntex, toff = struct.unpack_from('>6I', d, 0)
            imgs = []
            for i in range(nimg):
                o = ioff + i * 16
                w, h, fmt, ifl = struct.unpack_from('>4H', d, o)
                off, mip = struct.unpack_from('>2I', d, o + 8)
                imgs.append(dict(w=w, h=h, fmt=fmt, flag=ifl,
                                 off=off, mip=mip))
            texs = []
            for i in range(ntex):
                o = toff + i * 48
                tflag, tex_sc, txn_sc = struct.unpack_from('>3I', d, o)
                w, h, xo, yo = struct.unpack_from('>4H', d, o + 12)
                img_off = struct.unpack_from('>I', d, o + 20)[0]
                texs.append(dict(tex=tex_sc, txn=txn_sc, w=w, h=h, x=xo, y=yo,
                                 img=(img_off - ioff) // 16))
            body = max(ioff + nimg * 16, toff + ntex * 48)
            e = d.find(b'\0', body)
            blob_path = d[body:e].decode('latin1')
            yield name, imgs, texs, blob_path


if __name__ == '__main__':
    data_pak = os.path.join(BASE, 'paks', 'TextureData.pak')
    blobs = toc(data_pak)
    print(f'TextureData.pak: {len(blobs):,} blobs')
    n = miss = 0
    for name, imgs, texs, bp in index_entries():
        n += 1
        if bp not in blobs:
            miss += 1
    print(f'index entries: {n:,}   blob path not found: {miss:,}')
