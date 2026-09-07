# How MGS4 (PC) draws text

Everything below was measured against the shipped game, not inferred. If you
are adding a language whose alphabet is not Latin-1, this is the part that
will cost you the most time, so it is written out in full.

---

## There are two renderers

A string is drawn either by a **byte-indexed bitmap atlas** or by a
**TrueType face**. Both are used on the same screen, sometimes in the same
list, and they fail in completely different ways.

The bitmap atlases are ordinary textures — see `FORMATS.md` for how to unpack
and re-inject one. A strict scan of every unpacked DDS finds about **20
distinct glyph atlases**, duplicated across the game into **336 copies**.

## The atlas is indexed by the RAW BYTE

There is no code-point path. The engine takes a byte from the string and uses
it directly as a cell index — on the flat sheets, `cell = byte - 0x20`.

Two sheet shapes exist, and they behave differently:

- **flat Latin-1 grid** — rows run `0x20..0x7E`, then `0xA0..0xFF`;
- **compact sheets** — the C1 block (`0x80..0x9F`) is *skipped*, so the grid
  is not a flat byte ladder and the arithmetic above does not hold.

Measure the cell height per atlas. It is not constant across sheets.

## Reading the failure on screen

The symptom tells you which of the four mistakes you made. This table is the
single most useful thing in this document:

| what you see | what it means |
|---|---|
| letter-shaped but wrong glyphs (`ä`, `°`, `½`) | the string reached a bitmap atlas **you did not patch** — it is drawing the stock Latin-1 glyph that your byte happens to index |
| the line is completely blank | the string is in a single-byte encoding but the widget draws it with the **TTF**: the bytes are not valid UTF-8, so the engine drops the whole string |
| only an ASCII prefix survives (`16 `, `/`) | same as above, except the string starts with ASCII characters, which are valid UTF-8 and get through |
| one glyph per two bytes, with gaps | the opposite mistake: **UTF-8 text reached a bitmap atlas**, and every lead byte draws an empty cell |

## Adding an alphabet: a single-byte code page

Because indexing is by byte, an alphabet outside Latin-1 needs its own code
page: paint the glyphs into free cells of the atlas and write those byte
values into the text container.

Two traps that are only visible in the game:

1. **Some bytes never reach the atlas.** A few values in the `0x80..0x9F`
   range are consumed by the port as control codes. Probe the whole range
   with a test string, find which bytes vanish, and give those letters
   different cells.
2. **The engine advances by the STOCK glyph width.** A replacement glyph
   wider than the character it replaces is clipped, because the advance comes
   from the original metrics, not from your artwork. Budget the width per
   cell before drawing.

## The renderer is NOT recorded in the text

This is worth stating plainly, because it looks as though it should be. Each
string record carries three 64-bit ids — module, widget, key — then a length
and the bytes. There is no font field. Four separate checks:

1. Taking a widget where both renderers are known from the screen, neither
   the module id nor the key id separates the two sets, and **no single bit**
   of either does.
2. The `lang_global_id` file is only an id map (`<joined>=<a>_<b>_<c>`).
3. The widget id appears in **none** of 8907 `.la2 .gcx .dar .mdn .rlc .cnf`
   files.
4. The Japanese build is a tempting oracle — a bitmap sheet holds no kana, so
   a string written in kana must be TTF *there*. It does not transfer: of 24
   such strings, at least four are drawn by a bitmap atlas in the English
   build. The Japanese data tells you what the Japanese build needed.

**Practical consequence:** the widget id is the best predictor available, and
individual keys inside a widget can go the other way. Keep a per-widget map
plus a short per-key exception list, and settle the ambiguous ones by looking
at the screen. Expect a mixed widget where all-caps section headers are
bitmap and mixed-case row labels are TTF.

> A worked example of getting this wrong: a rule that split a mixed widget by
> string length (32 characters) cut one homogeneous settings list in half —
> a 32-character label was converted and vanished, while the 33-character
> label right below it rendered correctly. Case turned out to be the real
> split for that widget: 78 all-caps rows bitmap, 0 exceptions; 102
> mixed-case rows TTF.



## A clipped glyph reads as a different letter

Two failures look similar at a glance and have opposite causes. Telling them
apart is worth doing before you change anything.

**Smaller than its neighbours** — the glyph was scaled down to fit the cell
width. Harmless in itself, ugly at small sizes.

**Cut off** — the right-hand side is missing. This is the dangerous one,
because the remainder is often a *valid different letter*: a Cyrillic `В` with
its right edge gone reads as `Е`, and a cut `А` reads as `F`. A screenshot of
`НОМАД` came back as `НОМFД`, and the obvious conclusion — that the engine was
substituting a character at runtime — was wrong. Nothing was substituted. One
letter was clipped.

That misreading cost a full round of investigation, so: **zoom the screenshot
before theorising**. At thumbnail scale a clipped letter and a substituted one
are indistinguishable.

### Measuring it

Your Cyrillic sits in cells that held Latin-1 punctuation and accents, and
those stock glyphs are often much narrower than a capital letter. Compare each
of your glyphs against the stock glyph **in the same cell**, not against the
sheet's widest letter:

```
2048x512    Й +29px   Д +27   А +21   В +18   З +18   Г +17   К +17
1024x256    Й +20     Д +16   В +15   К +15   Ь +15   А +14   Г +14
512x256     Н +10     Д +7    М +6    А +5    Г +4    Ь +2
```

On the smallest sheet the injected glyphs reach 16px in a 16px cell — edge to
edge, with no gap at all. Leaving two pixels of margin is cheap insurance.

### Ink below the baseline

The same measurement catches a second problem. Letters with legs or a breve —
`Д`, `Ц`, `Щ`, `Й` — can extend below the lowest ink of any stock glyph on the
sheet:

```
1024x256   stock ink ends at y=33;   Д=36  Ц=36  Щ=36  Й=34
```

Three pixels is enough to show as smudges under the line of text on screen.
Measure against the stock bottom, not against the cell height.


## Bytes the engine keeps for itself

`cell = byte - 0x20` holds, but not every byte reaches the atlas. Three groups
are spoken for, and a letter placed on one of them fails in a way that looks
like a font bug:

- **The C1 range `0x80..0x9F`** is control space for the port. Most of it does
  draw, but not all — verify each byte you intend to use with an on-screen
  ruler rather than assuming.
- **`0x84`** is substituted for an inline button-icon token. Repaint that cell
  and the icon becomes a letter: a control hint reading `EXIT: PRESS <icon>`
  turns into `EXIT: PRESS ф`. Leave the cell stock.
- **`0xCC..0xCF` and `0xD7`** are reserved. A glyph written there comes out
  **clipped** on screen even though the atlas itself is correct.

The symptom tells you which of the two you hit. A glyph that is *smaller* than
its neighbours was scaled down to fit the cell width budget. A glyph that is
*cut off* is standing on a byte the engine reserved. They need opposite fixes,
so it is worth being precise about which one you are looking at.

Safe ground for extra letters is the row addressed by `0xC0..0xCB` — outside
the control range and outside the reserved block.


## Coverage: patch every copy, not every screen you visited

The obvious pipeline — log which textures the game reads, patch those — only
ever covers the screens someone walked through. Every unvisited screen keeps
a stock sheet and shows row 1 of the table above.

Build the list from a census of the archives instead, and patch **all** the
copies of every sheet.

Two things that census can still miss:

- **Mixed sheets.** An atlas that carries artwork alongside the glyph block
  can score too low for a correlation-based font detector and be skipped. One
  2048x2048 sheet in this game is half artwork, half font.
- **Sheets with no room.** Some atlases are three rows of ASCII only
  (`0x20..0x7E`) in a 512x128 texture. There is physically nowhere to put
  extra letters. Those strings either stay in the Latin alphabet, or the
  texture has to be rebuilt at a larger size.
