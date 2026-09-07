# -*- coding: utf-8 -*-
r"""UnityFS bundle reader and writer, for the MGS4 launcher (Unity 6000.0.25f1).

The launcher is a separate Unity application shipped next to the game, and its
text and fonts live in Addressables bundles rather than in any MGS4 container.

Header:

    "UnityFS\0", u32BE version, cstr unityVersion, cstr unityRevision,
    i64BE size, u32BE compressedBlocksInfoSize, u32BE uncompressedBlocksInfoSize,
    u32BE flags
    version >= 7   -> align the stream to 16 bytes
    flags & 0x80   -> blocksInfo is stored at the END of the file
    flags & 0x200  -> align to 16 AFTER blocksInfo, before the blocks

blocksInfo, once decompressed:

    16-byte hash, u32BE blockCount,
    blockCount x { u32BE uncompressed, u32BE compressed, u16BE flags }
    u32BE nodeCount,
    nodeCount x { i64BE offset, i64BE size, u32BE flags, cstr path }

Compression lives in the low 6 bits of flags: 0 none, 1 LZMA, 2 LZ4, 3 LZ4HC.

Writing: the blocks are LZ4HC-compressed, but blocksInfo itself is left raw.
The low bits of the flags field in the HEADER describe how blocksInfo is
stored, while every block carries its own flag - so 0x40 in the header and 3
per block is a valid combination, and there is no need to reproduce the exact
stream Unity would have produced for the directory.
"""
from __future__ import annotations

import io
import struct

import lz4.block

ALIGN16 = 16
BLOCK = 128 * 1024


def _cstr(f):
    out = bytearray()
    while True:
        c = f.read(1)
        if not c or c == b'\0':
            return bytes(out).decode('utf-8', 'replace')
        out += c


def _decompress(data: bytes, kind: int, out_size: int) -> bytes:
    kind &= 0x3f
    if kind == 0:
        return data
    if kind in (2, 3):
        return lz4.block.decompress(data, uncompressed_size=out_size)
    if kind == 1:
        import lzma
        d = lzma.LZMADecompressor(lzma.FORMAT_ALONE)
        return d.decompress(data[:5] + struct.pack('<Q', out_size) + data[5:])
    raise ValueError('unknown compression %d' % kind)


def read_nodes(path: str):
    """-> (header dict, [{'name', 'offset', 'size', 'flags', 'data'}])"""
    f = open(path, 'rb')
    if f.read(8) != b'UnityFS\0':
        raise ValueError('not a UnityFS bundle: ' + path)
    ver = struct.unpack('>I', f.read(4))[0]
    uver, urev = _cstr(f), _cstr(f)
    size, csize, usize, flags = struct.unpack('>qIII', f.read(20))
    if ver >= 7:
        f.seek((f.tell() + 15) & ~15)

    if flags & 0x80:
        here = f.tell()
        f.seek(-csize, io.SEEK_END)
        blob = f.read(csize)
        f.seek(here)
    else:
        blob = f.read(csize)
    if flags & 0x200 and not (flags & 0x80):
        f.seek((f.tell() + 15) & ~15)
    info = io.BytesIO(_decompress(blob, flags, usize))

    info.read(16)
    nblocks = struct.unpack('>I', info.read(4))[0]
    blocks = [struct.unpack('>IIH', info.read(10)) for _ in range(nblocks)]
    nnodes = struct.unpack('>I', info.read(4))[0]
    nodes = []
    for _ in range(nnodes):
        off, sz, fl = struct.unpack('>qqI', info.read(20))
        nodes.append({'offset': off, 'size': sz, 'flags': fl,
                      'name': _cstr(info)})

    data = bytearray()
    for un, cn, bfl in blocks:
        data += _decompress(f.read(cn), bfl, un)
    data = bytes(data)
    for n in nodes:
        n['data'] = data[n['offset']:n['offset'] + n['size']]
    return {'version': ver, 'unity': uver, 'revision': urev}, nodes


def read(path: str):
    """Convenience view: -> [(node name, bytes)]"""
    _h, nodes = read_nodes(path)
    return [(n['name'], n['data']) for n in nodes]


def write(path: str, header: dict, nodes: list, compress: bool = True):
    """Assemble a bundle from ready nodes.  Returns the file size written."""
    payload = bytearray()
    meta = []
    for n in nodes:
        meta.append((len(payload), len(n['data']), n['flags'], n['name']))
        payload += n['data']
    payload = bytes(payload)

    raw = [payload[i:i + BLOCK] for i in range(0, len(payload), BLOCK)] or [b'']
    blocks = []
    for b in raw:
        c = lz4.block.compress(b, mode='high_compression', compression=9,
                               store_size=False) if compress else b
        # If compression did not help, store the block raw.
        blocks.append((b, c, 3) if len(c) < len(b) else (b, b, 0))
    info = bytearray(b'\0' * 16)
    info += struct.pack('>I', len(blocks))
    for un, cn, fl in blocks:
        info += struct.pack('>IIH', len(un), len(cn), fl)
    info += struct.pack('>I', len(meta))
    for off, sz, fl, name in meta:
        info += struct.pack('>qqI', off, sz, fl) + name.encode('utf-8') + b'\0'
    info = bytes(info)

    uver = header.get('unity', '5.x.x').encode()
    urev = header.get('revision', '6000.0.25f1').encode()
    flags = 0x40                    # blocksInfo and directory together, raw
    head_len = 8 + 4 + len(uver) + 1 + len(urev) + 1 + 8 + 4 + 4 + 4
    pad = (-head_len) % ALIGN16
    body = b''.join(c for _u, c, _f in blocks)
    total = head_len + pad + len(info) + len(body)

    out = bytearray(b'UnityFS\0')
    out += struct.pack('>I', header.get('version', 8))
    out += uver + b'\0' + urev + b'\0'
    out += struct.pack('>qIII', total, len(info), len(info), flags)
    out += b'\0' * pad
    out += info
    out += body
    assert len(out) == total, (len(out), total)
    open(path, 'wb').write(bytes(out))
    return total
