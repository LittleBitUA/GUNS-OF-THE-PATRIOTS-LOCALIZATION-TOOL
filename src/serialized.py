# -*- coding: utf-8 -*-
r"""Unity SerializedFile: object table, type trees, and rebuilding.

Header (version 22):

    u32BE metadataSize, u32BE fileSize, u32BE version, u32BE dataOffset
    u8 endianess + 3 padding bytes
    version >= 22 -> u32BE metadataSize, i64BE fileSize, i64BE dataOffset,
                     i64BE unknown
    cstr unityVersion, i32 targetPlatform, u8 enableTypeTree
    then types, objects, scripts, externals

The type trees are parsed by typetree.py, and they are what makes it possible
to rebuild a MonoBehaviour without the game's assemblies and without Unity.
"""
from __future__ import annotations

import struct

CLASS = {1: 'GameObject', 21: 'Material', 28: 'Texture2D', 43: 'Mesh',
         48: 'Shader', 83: 'AudioClip', 114: 'MonoBehaviour',
         115: 'MonoScript', 128: 'Font', 213: 'Sprite', 687078895: 'SpriteAtlas'}


class Reader:
    def __init__(self, d):
        self.d, self.p = d, 0

    def u8(self):
        v = self.d[self.p]; self.p += 1; return v

    def i16(self):
        v = struct.unpack_from('<h', self.d, self.p)[0]; self.p += 2; return v

    def i32(self):
        v = struct.unpack_from('<i', self.d, self.p)[0]; self.p += 4; return v

    def u32(self):
        v = struct.unpack_from('<I', self.d, self.p)[0]; self.p += 4; return v

    def i64(self):
        v = struct.unpack_from('<q', self.d, self.p)[0]; self.p += 8; return v

    def raw(self, n):
        v = self.d[self.p:self.p + n]; self.p += n; return v

    def cstr(self):
        i = self.d.index(b'\0', self.p)
        v = self.d[self.p:i].decode('utf-8', 'replace'); self.p = i + 1
        return v

    def align(self, n=4):
        self.p = (self.p + n - 1) // n * n


def _read_type_tree(r, ver):
    """-> root node of the type tree; the reader is advanced past it."""
    import typetree
    root, newpos = typetree.parse_nodes(r.d, r.p, ver)
    r.p = newpos
    return root


def read(data: bytes):
    """-> dict with the header fields and the list of objects."""
    msize, fsize, ver, doff = struct.unpack_from('>IIII', data, 0)
    r = Reader(data)
    r.p = 16
    endian = r.u8(); r.p += 3
    if ver >= 22:
        msize = struct.unpack_from('>I', data, r.p)[0]; r.p += 4
        fsize = struct.unpack_from('>q', data, r.p)[0]; r.p += 8
        doff = struct.unpack_from('>q', data, r.p)[0]; r.p += 8
        r.p += 8                                   # unknown field
    unity = r.cstr()
    target = r.i32()
    tree = r.u8()

    ntypes = r.u32()
    types, trees = [], []
    for _ in range(ntypes):
        cid = r.i32()
        stripped = r.u8()
        script_idx = r.i16()
        if cid == 114:
            r.raw(16)                              # m_ScriptID
        r.raw(16)                                  # m_OldTypeHash
        root = None
        if tree:
            root = _read_type_tree(r, ver)
            if ver >= 21:
                ndep = r.u32()
                r.raw(ndep * 4)
        types.append(cid)
        trees.append(root)

    nobj = r.u32()
    objs = []
    for _ in range(nobj):
        r.align(4)
        rec = r.p
        path_id = r.i64()
        byte_start = r.i64() if ver >= 22 else r.u32()
        byte_size = r.u32()
        type_id = r.i32()
        cid = types[type_id] if 0 <= type_id < len(types) else type_id
        objs.append({'path_id': path_id, 'start': doff + byte_start,
                     'size': byte_size, 'class': cid, 'type_id': type_id,
                     'rec': rec,
                     'tree': trees[type_id] if 0 <= type_id < len(trees) else None,
                     'class_name': CLASS.get(cid, str(cid))})
    # Scripts and externals.  PPtr.m_FileID = 1 means the FIRST external, so
    # that list is one-based; 0 means "this file".
    nscript = r.i32()
    for _ in range(nscript):
        r.i32(); r.align(4); r.i64()
    next_ = r.i32()
    externals = []
    for _ in range(next_):
        r.cstr()                                   # tempEmpty
        r.raw(16)                                  # guid
        r.i32()                                    # type
        externals.append(r.cstr())

    return {'version': ver, 'unity': unity, 'data_offset': doff,
            'externals': externals,
            'file_size': fsize, 'enable_type_tree': tree,
            'types': types, 'trees': trees, 'objects': objs,
            'meta_end': r.p}


def rebuild(data: bytes, sf: dict, new_data: dict) -> bytes:
    """Rebuild a SerializedFile with some objects replaced.

    `new_data` is {path_id: bytes}.  The metadata is copied verbatim: object
    table records are FIXED LENGTH, so the table does not change size even
    when an object grows.  Only byteStart/byteSize are patched in place, plus
    the file size in the header.

    Objects in the data area are aligned to 16 bytes FROM data_offset, which
    is how Unity lays them out.  Using 8 produces a file 8-24 bytes short:
    the gaps between objects in an original are 12, 4, 12 - not divisible by
    8, but fine on 16.  Keep the original file order.
    """
    doff = sf['data_offset']
    out = bytearray(data[:doff])
    body = bytearray()
    for o in sorted(sf['objects'], key=lambda x: x['start']):
        blob = new_data.get(o['path_id'],
                            data[o['start']:o['start'] + o['size']])
        while len(body) % 16:
            body.append(0)
        start = len(body)
        body += blob
        struct.pack_into('<q', out, o['rec'] + 8, start)
        struct.pack_into('<I', out, o['rec'] + 16, len(blob))
    out += body
    if sf['version'] >= 22:
        # In version 22 the legacy 32-bit fields at offsets 0/4/12 stay
        # ZERO and the real ones follow as 64-bit.  Writing the size into the
        # legacy field as well produces a file that differs by three bytes.
        struct.pack_into('>q', out, 24, len(out))     # m_FileSize
    else:
        struct.pack_into('>I', out, 4, len(out) & 0xffffffff)
    return bytes(out)
