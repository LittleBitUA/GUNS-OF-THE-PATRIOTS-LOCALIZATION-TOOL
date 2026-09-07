# -*- coding: utf-8 -*-
r"""Unity type trees: read an object's values, and write them back.

These bundles ship with `m_EnableTypeTree = 1`, so every object carries its
own structure description.  That is what lets a MonoBehaviour be rebuilt with
no game assemblies, no Il2CppDumper and no Unity install.

A tree node (SerializedFile v22 -> 32 bytes):

    u16 version, u8 level, u8 typeFlags,
    u32 typeStrOffset, u32 nameStrOffset,
    i32 byteSize, i32 index, i32 metaFlag,
    u64 refTypeHash

String offsets: the high bit (0x80000000) means Unity's BUILT-IN table,
otherwise the offset is into the type's own string buffer.

Everything rests on two rules:
  * metaFlag & 0x4000  -> align the stream to 4 bytes AFTER the field;
  * an array is a node with typeFlags & 1 and exactly two children,
    `size` and `data`.

Honesty check: read an object through the tree and write it straight back.
If the bytes are identical, the tree was parsed correctly.
"""
from __future__ import annotations

import struct

# Unity's built-in string table (offset -> name).  Only what actually occurs
# in these files; an unknown offset raises rather than sliding silently.
COMMON = (
    "AABB\0AnimationClip\0AnimationCurve\0AnimationState\0Array\0Base\0"
    "BitField\0bitset\0bool\0char\0ColorRGBA\0Component\0data\0deque\0"
    "double\0dynamic_array\0FastPropertyName\0first\0float\0Font\0"
    "GameObject\0Generic Mono\0GradientNEW\0GUID\0GUIStyle\0int\0list\0"
    "long long\0map\0Matrix4x4f\0MdFour\0MonoBehaviour\0MonoScript\0"
    "m_ByteSize\0m_Curve\0m_EditorClassIdentifier\0m_EditorHideFlags\0"
    "m_Enabled\0m_ExtensionPtr\0m_GameObject\0m_Index\0m_IsArray\0m_IsStatic\0"
    "m_MetaFlag\0m_Name\0m_ObjectHideFlags\0m_PrefabInternal\0m_PrefabParentObject\0"
    "m_Script\0m_StaticEditorFlags\0m_Type\0m_Version\0Object\0pair\0PPtr<Component>\0"
    "PPtr<GameObject>\0PPtr<Material>\0PPtr<MonoBehaviour>\0PPtr<MonoScript>\0"
    "PPtr<Object>\0PPtr<Prefab>\0PPtr<Sprite>\0PPtr<TextAsset>\0PPtr<Texture>\0"
    "PPtr<Texture2D>\0PPtr<Transform>\0Prefab\0Quaternionf\0Rectf\0RectInt\0"
    "RectOffset\0second\0set\0short\0size\0SInt16\0SInt32\0SInt64\0SInt8\0staticvector\0"
    "string\0TextAsset\0TextMesh\0Texture\0Texture2D\0Transform\0TypelessData\0"
    "UInt16\0UInt32\0UInt64\0UInt8\0unsigned int\0unsigned long long\0unsigned short\0"
    "vector\0Vector2f\0Vector3f\0Vector4f\0m_ScriptingClassIdentifier\0Gradient\0"
    "Type*\0int2_storage\0int3_storage\0BoundsInt\0m_CorrespondingSourceObject\0"
    "m_PrefabInstance\0m_PrefabAsset\0FileSize\0Hash128\0"
).encode('utf-8')


def _str_at(buf: bytes, off: int) -> str:
    if off & 0x80000000:
        b = COMMON
        off &= 0x7FFFFFFF
    else:
        b = buf
    end = b.index(b'\0', off)
    return b[off:end].decode('utf-8', 'replace')


class Node:
    __slots__ = ('version', 'level', 'flags', 'type', 'name', 'size',
                 'index', 'meta', 'children')

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self.children = []

    @property
    def align(self):
        return bool(self.meta & 0x4000)

    def __repr__(self):
        return '<%s %s lvl%d>' % (self.type, self.name, self.level)


def parse_nodes(data: bytes, pos: int, file_version: int):
    """-> (root node, new position)"""
    n_nodes, strbuf = struct.unpack_from('<II', data, pos)
    pos += 8
    step = 32 if file_version >= 19 else 24
    flat = []
    for i in range(n_nodes):
        o = pos + i * step
        ver, lvl, tf, tso, nso, bs, idx, meta = struct.unpack_from(
            '<HBBIIiii', data, o)
        flat.append((ver, lvl, tf, tso, nso, bs, idx, meta))
    pos += n_nodes * step
    buf = data[pos:pos + strbuf]
    pos += strbuf

    root, stack = None, []
    for ver, lvl, tf, tso, nso, bs, idx, meta in flat:
        n = Node(version=ver, level=lvl, flags=tf, size=bs, index=idx,
                 meta=meta, type=_str_at(buf, tso), name=_str_at(buf, nso))
        if lvl == 0:
            root = n
            stack = [n]
        else:
            del stack[lvl:]
            stack[lvl - 1].children.append(n)
            stack.append(n)
    return root, pos


PRIM = {
    'SInt8': ('<b', 1), 'UInt8': ('<B', 1), 'char': ('<B', 1),
    'SInt16': ('<h', 2), 'short': ('<h', 2), 'UInt16': ('<H', 2),
    'unsigned short': ('<H', 2),
    'SInt32': ('<i', 4), 'int': ('<i', 4), 'UInt32': ('<I', 4),
    'unsigned int': ('<I', 4), 'Type*': ('<I', 4),
    'SInt64': ('<q', 8), 'long long': ('<q', 8), 'FileSize': ('<Q', 8),
    'UInt64': ('<Q', 8), 'unsigned long long': ('<Q', 8),
    'float': ('<f', 4), 'double': ('<d', 8),
    'bool': ('?', 1),
}


class Cursor:
    def __init__(self, d):
        self.d, self.p = d, 0

    def take(self, n):
        v = self.d[self.p:self.p + n]
        self.p += n
        return v

    def align(self):
        self.p = (self.p + 3) & ~3


def read_value(node: Node, cur: Cursor):
    t = node.type
    if t in PRIM:
        fmt, sz = PRIM[t]
        v = struct.unpack(fmt, cur.take(sz))[0]
        if node.align:
            cur.align()
        return v
    if t == 'string':
        n = struct.unpack('<i', cur.take(4))[0]
        v = cur.take(n).decode('utf-8', 'surrogateescape')
        cur.align()                       # a string always aligns
        return v
    if node.children and node.children[0].type == 'Array' \
            and node.children[0].flags & 1:
        arr = node.children[0]
        n = struct.unpack('<i', cur.take(4))[0]
        item = arr.children[1]
        if item.type in ('UInt8', 'SInt8', 'char') and not item.align:
            v = cur.take(n)
            if arr.align:
                cur.align()
            return {'Array': list(v)}
        out = [read_value(item, cur) for _ in range(n)]
        if arr.align:
            cur.align()
        return {'Array': out}
    out = {}
    for c in node.children:
        out[c.name] = read_value(c, cur)
    if node.align:
        cur.align()
    return out


class Writer:
    def __init__(self):
        self.b = bytearray()

    def align(self):
        while len(self.b) & 3:
            self.b += b'\0'


def write_value(node: Node, val, w: Writer):
    t = node.type
    if t in PRIM:
        fmt, _sz = PRIM[t]
        w.b += struct.pack(fmt, val)
        if node.align:
            w.align()
        return
    if t == 'string':
        raw = val.encode('utf-8', 'surrogateescape')
        w.b += struct.pack('<i', len(raw)) + raw
        w.align()
        return
    if node.children and node.children[0].type == 'Array' \
            and node.children[0].flags & 1:
        arr = node.children[0]
        item = arr.children[1]
        items = val['Array'] if isinstance(val, dict) else val
        w.b += struct.pack('<i', len(items))
        if item.type in ('UInt8', 'SInt8', 'char') and not item.align:
            w.b += bytes(items)
        else:
            for it in items:
                write_value(item, it, w)
        if arr.align:
            w.align()
        return
    for c in node.children:
        write_value(c, val[c.name], w)
    if node.align:
        w.align()


def read_object(root: Node, data: bytes):
    cur = Cursor(data)
    v = read_value(root, cur)
    return v, cur.p


def write_object(root: Node, val) -> bytes:
    w = Writer()
    write_value(root, val, w)
    return bytes(w.b)
