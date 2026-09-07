# -*- coding: utf-8 -*-
r"""A single-byte code page for the bitmap font — the kerning fix.

The engine draws `cell = byte - 0x20` and never decodes UTF-8, so a two-byte
letter costs an extra advance for its blank lead cell, and text comes out
spaced: `Н О В А  Г Р А`. Packing one byte per letter removes the gap, and it
also means a translated string is the same *length* as the original — which
matters wherever a field is fixed size.

This module is the mechanism, not a finished alphabet. The map below is the
one this project uses for Ukrainian; adapt it to yours. What is worth copying
is the shape of the problem:

  * **Pick the cells you repaint, then map letters onto those bytes.** The
    atlas has no notion of code points. Any byte can hold any glyph, and the
    only rule is that both sides — the text and the sheet — agree.

  * **Some bytes never arrive.** Roughly half the usable range is the C1
    control block (0x80..0x9F) and the port intercepts an unpredictable subset
    of it before the atlas lookup. Map a ruler onto the range and read it off
    a screenshot; see byte_probe.py. Move any letter that lands on a byte
    that does not survive.

  * **Some bytes belong to the engine.** Inline icon tokens expand to a byte,
    and a few more are reserved outright. Repaint one of those cells and the
    icon turns into a letter. Leave them stock and put your alphabet
    elsewhere. See docs/FONTS.md.

  * **One unknown character loses the whole string.** `convert` returns None
    rather than a partial result, because a half-encoded string is worse than
    an unconverted one: it renders as a mix and hides where the fault is.
    Map your punctuation deliberately — a single guillemet dropped 237 rows
    back to raw UTF-8 in this project before anyone noticed.
"""
from __future__ import annotations

# --- the map ------------------------------------------------------------
# Cyrillic block, laid onto the cells this project repaints:
#     U+0410..U+043F  А..Я а..п  ->  0x90..0xBF
#     U+0440..U+044F  р..я       ->  0x80..0x8F
#     Є І Ї Ґ є і ї ґ            ->  0xC0..0xC7   (a row added below the grid)
SBC = {}
for _k in range(0x30):
    SBC[chr(0x410 + _k)] = 0x90 + _k
for _k in range(0x10):
    SBC[chr(0x440 + _k)] = 0x80 + _k
for _k, _ch in enumerate('ЄІЇҐєіїґ'):
    SBC[_ch] = 0xC0 + _k

# Relocations. Every one of these was a letter that did not draw where the
# arithmetic said it should, found with a byte ruler on screen:
#   - two bytes in the C1 block are eaten by the port;
#   - one cell is where an inline icon token lands;
#   - one small run is reserved by the engine and clips whatever is drawn in it.
del SBC['ъ'], SBC['ы']              # those cells now hold two moved capitals
SBC['З'] = 0x8A
SBC['И'] = 0x8B
SBC['Л'] = 0xC9
SBC['ф'] = 0xCB

# Punctuation. The cells below 0x80 are untouched stock, so anything mapped
# there is guaranteed to be what the original font drew.
SBC['’'] = 0x27
SBC['ʼ'] = 0x27
SBC['«'] = 0x22
SBC['»'] = 0x22
SBC['—'] = 0x2D


def convert(text: str):
    """UTF-8 text -> single-byte bytes, or None if anything is unmapped.

    ASCII passes through unchanged, so mixed strings work.  Returning None on
    the FIRST unknown character is deliberate: see the module docstring.
    """
    out = bytearray()
    for ch in text:
        if ch == '\n' or ord(ch) < 0x80:
            out.append(ord(ch))
            continue
        code = SBC.get(ch)
        if code is None:
            return None
        out.append(code)
    return bytes(out)


def unmapped(text: str) -> set:
    """Which characters would make convert() give up.  Use this to build the
    punctuation half of the map instead of discovering it on screen."""
    return {c for c in text
            if ord(c) >= 0x80 and c != '\n' and c not in SBC}


def collisions() -> dict:
    """Bytes that two different characters map to.  Intentional for the
    quote marks here; anywhere else it is a bug in your map."""
    seen = {}
    for ch, code in SBC.items():
        seen.setdefault(code, []).append(ch)
    return {k: v for k, v in seen.items() if len(v) > 1}
