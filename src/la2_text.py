# -*- coding: utf-8 -*-
r"""List and edit the text baked into UI layout files (`.la2`).

A layout carries its own strings, separate from every text container. Some of
them are live — the label you see on screen — and most are design-time
placeholders the code overwrites at runtime. There is nothing in the file that
says which, so **change one field to something unmistakable and look** before
investing in a layout edit. See docs/FORMATS.md.

    python la2_text.py list <dir>
    python la2_text.py set  <file.la2> <offset> <text> <out.la2>

`list` walks a directory of extracted layouts and prints every text record it
finds, with the offset and the field size. `set` rewrites one record and
writes the result to a new file — it never edits in place, and never touches
the game.

The record, big-endian:

    00 0D | 00 14 | 00 00 00 09 | 'OLD SNAKE' 00 00 00
    tag     size    length        payload

`size` counts the whole record including its 8-byte header, so the payload
budget is `size - 8` — for 0x14 that is 12 bytes, not 20. The field is fixed:
a longer string does not fit, and this tool refuses rather than truncating
silently.

Encoding: pass `--sbc` to write the text through a single-byte code page
(see sbc_codepage.py), which is what you want when the field is drawn by the
bitmap atlas — one byte per letter, so a translated name is the same length
as the original it replaces. Without it the text is written as UTF-8.
"""
from __future__ import annotations

import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

TAG = 0x000D              # text record tag
HDR = 8                   # tag+size (4) and length (4)
ASCII = re.compile(rb'[\x20-\x7e]{3,}')


def fields(data: bytes):
    """-> [(offset, field size, used length, payload)] for every 0x0D record."""
    out = []
    for m in ASCII.finditer(data):
        off = m.start()
        if off < HDR:
            continue
        tag, size = struct.unpack_from('>HH', data, off - HDR)
        ln = struct.unpack_from('>I', data, off - 4)[0]
        if tag != TAG or size <= HDR:
            continue
        field = size - HDR
        raw = data[off:off + field]
        if ln > field or raw[ln:].strip(b'\0'):
            continue
        out.append((off, field, ln, raw[:ln]))
    return out


def cmd_list(argv):
    root = argv[0]
    total = 0
    for dp, _dn, fn in os.walk(root):
        for f in sorted(fn):
            if not f.endswith('.la2'):
                continue
            p = os.path.join(dp, f)
            got = fields(open(p, 'rb').read())
            if not got:
                continue
            print(os.path.relpath(p, root))
            for off, field, ln, txt in got:
                print('   0x%06X  field %2d, used %2d  %r'
                      % (off, field, ln, txt.decode('latin-1')))
                total += 1
    print()
    print('text fields: %d' % total)


def encode(text: str, field: int, sbc: bool) -> bytes:
    if sbc:
        import sbc_codepage
        raw = sbc_codepage.convert(text)
        if raw is None:
            raise SystemExit('cannot encode %r in the single-byte page' % text)
    else:
        raw = text.encode('utf-8')
    if len(raw) > field:
        raise SystemExit('%r is %d bytes, but the field holds only %d'
                         % (text, len(raw), field))
    return raw


def cmd_set(argv):
    src, off, text, dst = argv[0], int(argv[1], 0), argv[2], argv[3]
    sbc = '--sbc' in sys.argv
    data = bytearray(open(src, 'rb').read())
    tag, size = struct.unpack_from('>HH', data, off - HDR)
    if tag != TAG or size <= HDR:
        raise SystemExit('offset 0x%X is not a text record '
                         '(tag %04X, size %d)' % (off, tag, size))
    field = size - HDR
    old = bytes(data[off:off + field]).rstrip(b'\0')
    raw = encode(text, field, sbc)
    struct.pack_into('>I', data, off - 4, len(raw))
    data[off:off + field] = raw + bytes(field - len(raw))

    print('%s @0x%X' % (os.path.basename(src), off))
    print('   field  %d bytes' % field)
    print('   was    %-18r (%d bytes)' % (old.decode('latin-1'), len(old)))
    print('   now    %-18s (%d bytes)  %s'
          % (text, len(raw), ' '.join('%02X' % c for c in raw)))
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    open(dst, 'wb').write(bytes(data))
    print('   -> %s' % dst)
    print()
    print('Remember: layouts store every field TWICE, a few dozen bytes '
          'apart. Patch both, or the change shows in only one state.')


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('list', 'set'):
        raise SystemExit(__doc__)
    argv = [a for a in sys.argv[2:] if not a.startswith('--')]
    {'list': cmd_list, 'set': cmd_set}[sys.argv[1]](argv)


if __name__ == '__main__':
    main()
