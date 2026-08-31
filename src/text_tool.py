# -*- coding: utf-8 -*-
r"""Export and import the MGS4 (PC, Master Collection) text containers.

    python text_tool.py export codec_en  export\codec_en.txt
    python text_tool.py import codec_en  export\codec_en.txt  build\codec_en
    python text_tool.py verify codec_en                 prove a no-op is byte-exact

The five container families live under `common\localization\{codec,lang,spc,
demo,movie}\<family>_<lang>`.  Nothing is encrypted - plain UTF-8, little
endian - but each family stores strings differently and, crucially, records the
byte length of every string in a field that must be recomputed when the text
changes.  Get that wrong and the game reads past the string into the next one.

    file    u16 version, u32 groupCount

    codec   group  u32 id1, u32 id2, u32 nLines
                   nLines x { u32 len, bytes[len] }          len counts the NUL
    lang    flat   u64 id1, u64 id2, u64 idx, u32 len, bytes[len]
    spc     group  u32 gid, u32 nLines, u32 size
                   nLines x { u16 L, u32 a, u32 b, u32 gid, u16 L, u16 flag, cstr }
                   size = sum of the L values in the group
    demo    group  u32 gid, u32 x, u32 nLines, u32 size          (same line shape)
    movie          same line shape as spc

The `a`/`b` fields on spc/demo/movie lines are subtitle timings, not offsets,
so they are copied through untouched.

The editable .txt uses one block per string:

    ### 0
    Original English text, line breaks shown as they are stored.
    <blank line>

Translate the line(s) under each `###` header and keep the header.  A block you
leave equal to the original is written back byte-for-byte.
"""
from __future__ import annotations

import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mgs4paths

FAMILIES = ('codec', 'lang', 'spc', 'demo', 'movie')


def _family(name: str) -> str:
    base = os.path.basename(name).rsplit('_', 1)[0]
    if base not in FAMILIES:
        raise SystemExit('%s: not one of %s' % (name, ', '.join(FAMILIES)))
    return base


def container_path(name: str, game: str | None = None) -> str:
    fam = _family(name)
    return os.path.join(mgs4paths.find_game(game), 'common', 'localization',
                        fam, os.path.basename(name))


# --------------------------------------------------------------------------
# parse: -> (version, [record...]) where a record is a dict with the string and
# everything needed to write it back in place
# --------------------------------------------------------------------------

def parse(data: bytes, kind: str):
    ver, count = struct.unpack_from('<HI', data, 0)
    p, recs = 6, []

    if kind == 'lang':
        while p < len(data):
            ln = struct.unpack_from('<I', data, p + 24)[0]     # after 3x u64
            body = data[p + 28:p + 28 + ln]
            recs.append({'head': data[p:p + 24], 'text': body[:-1]})
            p += 28 + ln
        return ver, recs

    if kind == 'codec':
        for _ in range(count):
            a, b, n = struct.unpack_from('<III', data, p)
            recs_head = data[p:p + 12]
            p += 12
            group = {'head': recs_head, 'lines': []}
            for _k in range(n):
                ln = struct.unpack_from('<I', data, p)[0]
                body = data[p + 4:p + 4 + ln]
                group['lines'].append(body[:-1])
                p += 4 + ln
            recs.append(group)
        return ver, recs

    # spc / demo / movie
    hdr = 12 if kind == 'spc' else 16
    for _ in range(count):
        ghead = data[p:p + hdr]
        n = struct.unpack_from('<I', data, p + (4 if kind == 'spc' else 8))[0]
        p += hdr
        group = {'head': bytearray(ghead), 'lines': []}
        for _k in range(n):
            L, a, b, gid, L2, flag = struct.unpack_from('<HIIIHH', data, p)
            end = data.index(b'\0', p + 18)                    # 18-byte line head
            group['lines'].append({'a': a, 'b': b, 'gid': gid, 'flag': flag,
                                   'text': data[p + 18:end]})
            p = end + 1
        recs.append(group)
    return ver, recs


# --------------------------------------------------------------------------
# rebuild
# --------------------------------------------------------------------------

def build(kind: str, ver: int, recs, new_text) -> bytes:
    """`new_text` maps a flat string index -> replacement str (or bytes)."""
    def enc(i, original):
        v = new_text.get(i)
        if v is None:
            return original
        return v.encode('utf-8') if isinstance(v, str) else v

    out = bytearray(struct.pack('<HI', ver, len(recs) if kind != 'lang' else len(recs)))
    idx = 0

    if kind == 'lang':
        out = bytearray(struct.pack('<HI', ver, len(recs)))
        for r in recs:
            body = enc(idx, r['text']); idx += 1
            out += r['head'] + struct.pack('<I', len(body) + 1) + body + b'\0'
        return bytes(out)

    if kind == 'codec':
        for g in recs:
            out += g['head']
            for line in g['lines']:
                body = enc(idx, line); idx += 1
                out += struct.pack('<I', len(body) + 1) + body + b'\0'
        return bytes(out)

    # spc / demo / movie - recompute each L and the group size
    soff = 8 if kind == 'spc' else 12
    for g in recs:
        head = bytearray(g['head'])
        lines, total = bytearray(), 0
        for ln in g['lines']:
            body = enc(idx, ln['text']); idx += 1
            nl = 16 + len(body) + 1
            lines += struct.pack('<HIIIHH', nl, ln['a'], ln['b'], ln['gid'],
                                 nl, ln['flag']) + body + b'\0'
            total += nl
        struct.pack_into('<I', head, soff, total)
        out += head + lines
    return bytes(out)


def flat_strings(kind: str, recs):
    """The strings in file order, as a flat list of bytes."""
    if kind == 'lang':
        return [r['text'] for r in recs]
    if kind == 'codec':
        return [b for g in recs for b in g['lines']]
    return [ln['text'] for g in recs for ln in g['lines']]


# --------------------------------------------------------------------------
# the editable .txt
# --------------------------------------------------------------------------

def write_txt(path, strings, name):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('# %s - %d strings.  Translate under each ### header; keep the '
                 'header.\n' % (name, len(strings)))
        fh.write('# A block left equal to the original is written back byte-for-'
                 'byte.\n\n')
        for i, b in enumerate(strings):
            fh.write('### %d\n%s\n\n' % (i, b.decode('utf-8', 'replace')))


def read_txt(path):
    """Read the editable .txt back into {index: text}.

    `newline=''` matters: without it Python rewrites CRLF to LF while reading,
    and a game string that contains CRLF comes back changed when nobody
    touched it.  write_txt already writes with newline='\\n', so only the read
    side needed it.  Measured on the shipped lang_en: 4 strings.
    """
    out, cur, buf = {}, None, []
    for raw in open(path, encoding='utf-8', newline='').read().split('\n'):
        if raw.startswith('### '):
            if cur is not None:
                out[cur] = '\n'.join(buf).rstrip('\n')
            cur, buf = int(raw[4:].strip()), []
        elif raw.startswith('#') and cur is None:
            continue
        else:
            buf.append(raw)
    if cur is not None:
        out[cur] = '\n'.join(buf).rstrip('\n')
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _load(name, game):
    kind = _family(name)
    data = open(container_path(name, game), 'rb').read()
    ver, recs = parse(data, kind)
    return kind, ver, recs, data



def _diff(strings, edits):
    """Which blocks really changed -> {index: new text}.

    A block is compared against the original AS THE .TXT COULD SHOW IT.  The
    format ends every block with a blank line and read_txt strips that run,
    so a string whose own text ends in a newline can never come back with it.
    Re-attaching the original's trailing run before comparing keeps an
    untouched file byte-identical and leaves a real edit alone.  Measured on
    the shipped lang_en: 11 strings.
    """
    new = {}
    for i, s in edits.items():
        if i >= len(strings):
            continue
        orig = strings[i].decode('utf-8', 'replace')
        tail = orig[len(orig.rstrip('\n')):]
        cand = s + tail
        if cand != orig:
            new[i] = cand
    return new


def cmd_export(a):
    kind, ver, recs, _ = _load(a.name, a.game)
    strings = flat_strings(kind, recs)
    write_txt(a.txt, strings, a.name)
    print('%s: %d strings -> %s' % (a.name, len(strings), a.txt))


def cmd_import(a):
    kind, ver, recs, _ = _load(a.name, a.game)
    strings = flat_strings(kind, recs)
    edits = read_txt(a.txt)
    new = _diff(strings, edits)
    changed = len(new)
    data = build(kind, ver, recs, new)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or '.', exist_ok=True)
    open(a.out, 'wb').write(data)
    print('%s: %d strings changed -> %s (%d bytes)'
          % (a.name, changed, a.out, len(data)))
    print('   copy this over common\\localization\\%s\\%s in the game'
          % (_family(a.name), os.path.basename(a.name)))


def cmd_verify(a):
    kind, ver, recs, data = _load(a.name, a.game)
    rebuilt = build(kind, ver, recs, {})
    ok = rebuilt == data
    print('%s: no-op rebuild is %s (%d bytes)'
          % (a.name, 'BYTE-IDENTICAL' if ok else 'DIFFERENT', len(rebuilt)))

    # The rebuild above never touches the .txt, so it cannot catch a lossy
    # export/import.  Do the full trip through a temporary file: export it,
    # read it straight back with no edits, and rebuild.
    import tempfile
    strings = flat_strings(kind, recs)
    with tempfile.TemporaryDirectory() as tmp:
        txt = os.path.join(tmp, 'roundtrip.txt')
        write_txt(txt, strings, a.name)
        again = build(kind, ver, recs, _diff(strings, read_txt(txt)))
    ok2 = again == data
    print('%s: export -> import with no edits is %s'
          % (a.name, 'BYTE-IDENTICAL' if ok2 else 'DIFFERENT'))
    return 0 if (ok and ok2) else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    e = sub.add_parser('export'); e.add_argument('name'); e.add_argument('txt')
    i = sub.add_parser('import'); i.add_argument('name'); i.add_argument('txt'); i.add_argument('out')
    v = sub.add_parser('verify'); v.add_argument('name')
    for s in (e, i, v):
        s.add_argument('--game', default=None)
    a = ap.parse_args()
    return {'export': cmd_export, 'import': cmd_import, 'verify': cmd_verify}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main() or 0)
