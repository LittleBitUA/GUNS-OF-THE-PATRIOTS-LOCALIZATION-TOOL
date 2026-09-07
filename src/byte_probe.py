# -*- coding: utf-8 -*-
r"""Paint a BYTE RULER into a bitmap-drawn menu, so one screenshot maps the atlas.

Why this exists
---------------
When you add an alphabet through a single-byte code page, roughly half your
code points land in 0x80..0x9F — the C1 control block — and the PC port
swallows SOME of those bytes before they ever reach the atlas.  Which ones is
not documented, not guessable, and not the same as on other platforms.

Finding them one at a time costs a screenshot, a guess, a rebuild and another
screenshot, per byte.  There are 96 candidates.  That does not scale.

Instead, replace three stacked labels on one screen with runs of consecutive
bytes.  A single screenshot then maps the whole range: every byte that draws
its expected glyph is safe, every gap or wrong glyph is a byte to avoid.

    python byte_probe.py <lang_en> <out lang_en> [--widget 0x1AE757]

Reads a localization container, writes a patched copy to the path you give,
and prints what it wrote.  It never touches the game — install the result the
same way you install any other translated container, take the screenshot, then
put your real file back.

Pick a widget you have already seen drawn by the atlas rather than the TTF;
the default is the pause menu, which is bitmap-drawn.  Any widget with three
or more strings works — the point is only that they are on screen together.

Reading the screenshot
----------------------
Row 1 is 0x90..0x9F, row 2 is 0x80..0x8F, row 3 is 0xC0..0xCF.  Count along
from the left: the Nth glyph is byte (start + N).  A blank where a glyph
should be, or a glyph belonging to a different cell, means that byte does not
survive the trip and the letter assigned to it has to move somewhere else.
"""
from __future__ import annotations

import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import text_tool

DEFAULT_WIDGET = 0x1AE757          # the pause menu, proven bitmap-drawn
ROWS = [bytes(range(0x90, 0xA0)),
        bytes(range(0x80, 0x90)),
        bytes(range(0xC0, 0xD0))]


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(argv) < 2:
        raise SystemExit(__doc__)
    src, dst = argv[0], argv[1]

    widget = DEFAULT_WIDGET
    if '--widget' in sys.argv:
        widget = int(sys.argv[sys.argv.index('--widget') + 1], 0)

    data = open(src, 'rb').read()
    ver, recs = text_tool.parse(data, 'lang')
    targets = [i for i, r in enumerate(recs)
               if struct.unpack_from('<Q', r['head'], 8)[0] == widget]
    print('strings in widget %08X: %d' % (widget, len(targets)))
    if len(targets) < 3:
        raise SystemExit('need at least 3 strings in that widget to fill '
                         'three rows; pick another widget with --widget')

    new = {}
    for k, i in enumerate(targets[:3]):
        new[i] = ROWS[k]
        print('  row %d, record #%-5d <- %s'
              % (k + 1, i, ' '.join('%02X' % b for b in ROWS[k])))

    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    open(dst, 'wb').write(text_tool.build('lang', ver, recs, new))
    print()
    print('written: %s' % dst)
    print('Install it, open that screen, screenshot it, then restore your own '
          'file.')


if __name__ == '__main__':
    main()
