# MGS4 (PC, Master Collection) file formats

Everything here was worked out by unpacking the game and cross-checking against
a second, independent decoder where one existed. Offsets are little-endian
unless noted.

---

## VPAK archives (`*.pak`)

The container for almost everything. Header, body, then a table of contents at
the very end.

```
header   'VPAK'  u16 verMajor  u16 verMinor  u32 entryCount  u32 tocSize
body     entry regions, each raw or LZ4-block compressed (no framing)
toc      the last `tocSize` bytes, one record per entry:
             u32 nameLen
             u16 flags
             char name[nameLen]
             u64 zero
             u64 uncompressedSize
             u64 compressedSize        (0 = stored raw)
             u64 offset
             u32 chunkSize
             u32 chunkCount
             u64 chunkOffset[chunkCount]     relative to the entry's offset
```

Two things bite here. The TOC record is **variable length** (the chunk list at
the end), so a fixed stride finds almost nothing. And anything larger than
`chunkSize` (1 MB) is stored as several independently LZ4-compressed chunks, so
it cannot be decoded with a single call. `vpak.fetch` handles both.

LZ4 is the plain block format — no dictionary, no frame header.

---

## Textures: PC_TXN_UP

Under `common\textures\PC_TXN_UP` and `ww\textures\PC_TXN_UP`:

```
txn_up.1.pak, txn_up.2.pak    the INDEX  - one .txn descriptor per texture
paks\TextureData.pak          the DATA   - one .data blob per pixel buffer
```

### The `.txn` descriptor

A `.txn` is big-endian (the header and tables), with one little-endian field
noted below.

```
0x00  u32 _, u32 flags, u32 imageCount, u32 imageOffset,
      u32 texCount,     u32 texOffset,  u32 0, u32 0

image[i]  16 bytes:  u32 (width << 16) | height
                     u32 (format << 16) | mipFlags
                         0x09 = DXT1, 0x0A = DXT3, 0x0B = DXT5, 0x03 = ARGB32
                     u32 start, u32 end                cumulative, 16-byte padded

texture[i] 48 bytes: u32 type, u32 hash, u32 setStrcode,
                     u32 (w << 16) | h, _, u32 imageRef, _,
                     f32 uScale, f32 vScale, ...

tail      imageCount slots of 256 bytes:
                     the blob's build path, ASCII, NUL padded
                     +0xFC  u32 LITTLE-endian uncompressed size
```

**The join is positional and exact.** Image descriptor `i` pairs with path slot
`i`, and the size at `+0xFC` matches the image's byte length exactly. The path
in the slot is a verbatim key into `TextureData.pak`'s table of contents — no
fuzzy matching. `txnup_unpack.py` resolves 100% of images this way.

### Two layers, and which one wins

`stage_data_compressed` holds an older descriptor layer; `PC_TXN_UP` holds the
Master Collection's replacements, usually at higher resolution. **98.7% of the
older layer's textures also exist in `PC_TXN_UP`**, and the `PC_TXN_UP` copy is
the one that renders. The `.txn` inside `stage_data_compressed` are headers
only — no path slots, and their image offsets run past the end of the file — so
do not try to read pixels out of them.

### Block compression (BC1 / DXT1, BC3 / DXT5)

- **DXT1**, 8 bytes per 4x4 block: `u16 c0, u16 c1` (RGB565) then sixteen 2-bit
  indices. If `c0 > c1` the block has four colours; if `c0 <= c1` it has three
  colours **plus a punch-through transparent index**. The stock title art uses
  the transparent mode in ~85% of blocks, so an encoder that ignores it turns
  every soft edge hard.
- **DXT3/DXT5**, 16 bytes per block: an alpha block then a DXT1-style colour
  block. DXT5 alpha interpolates 8 levels between two endpoints; DXT3 alpha is
  explicit 4 bits per pixel. (MGS4 itself ships no DXT3 texture - 34,854 DXT1 /
  54,177 DXT5 / 91 uncompressed in a full unpack - but the id is mapped.)
- **Uncompressed** (format 0x03): stored **A, R, G, B** byte order - the first
  byte of every pixel is alpha, not red.

`mgstex.decode_bc` decodes via Pillow's DDS reader (a reference implementation).
`mgsbc.encode` writes both, choosing the punch-through mode for DXT1 when a
block has transparency and fitting endpoints along the block's principal colour
axis.

### Why an edited texture has to be relocated

Stock art is mostly flat, so it compresses ~13:1 (a 699 KB texture stored in
54 KB). Any real edit breaks those runs and the recompressed blob no longer
fits its slot. Because a VPAK record carries an explicit `offset`, the fix is to
append the new blob before the TOC, move the TOC after it, and patch the
record's `compressed` / `offset` / chunk table. The old bytes stay put, so any
other record that shared them keeps working — and 60% of the records in
`TextureData.pak` are aliases sharing a byte region, so that matters.

---

## Text: the localization containers

Under `common\localization\{codec,lang,spc,demo,movie}`, one file per language
(`codec_en`, `codec_fr`, ...). Plain UTF-8, little-endian, not encrypted.

```
file    u16 version, u32 groupCount

codec   group  u32 id1, u32 id2, u32 nLines
               nLines x { u32 len, bytes[len] }          len counts the NUL
lang    flat   u64 id1, u64 id2, u64 index, u32 len, bytes[len]
spc     group  u32 gid, u32 nLines, u32 size
               nLines x { u16 L, u32 a, u32 b, u32 gid, u16 L, u16 flag, cstring }
               size = the sum of the L values in the group
demo    group  u32 gid, u32 x, u32 nLines, u32 size          (same line shape)
movie          same line shape as spc
```

The `a` / `b` fields on `spc` / `demo` / `movie` lines are subtitle timings, not
offsets — copy them through unchanged. **Every string carries its byte length**
(`len` for codec/lang, the two `L` fields plus the group `size` for the others),
and all of those must be recomputed when the text changes, or the game reads one
string into the next. `text_tool.py` does this; `text_tool.py verify` proves a
no-op rebuild is byte-identical.

### Line breaks

`codec` and `lang` store a real newline inside a string. `spc`, `demo` and
`movie` store a `|` character instead. Keep whichever the container you are
editing already uses.

### The length limit that crashes the game

A handful of short on-screen labels — checkpoint, pause, continue, HUD text —
are copied into a fixed-size list when drawn. If a translation of one of them is
longer than the original **in characters** (not bytes — a longer byte string of
the same character count is fine), the list overflows and the game crashes at
the moment that label appears. Long dialogue, subtitles and briefings have no
such limit and can be any length. Keep short UI labels at or under the
original character count.

The list is bounded at 1025 entries, and the overflow always faults at the
same instruction, so a crash that reproduces on one specific screen and
nowhere else is almost certainly this. To find which string, swap whole
container files rather than reasoning about them: put the stock file back,
confirm the crash goes away, then bisect your translated file in halves. An
audit can prove a file is well-formed; it can never prove the engine accepts
it.

---

## Other containers (read-only for now)

`pak_extract.py` will unpack any VPAK whole. Notable contents of
`stage_data_compressed`:

- `.txn` — texture descriptors (headers only, as above)
- `.cnf` — a plain-text load manifest listing which `.txn` a stage or slot uses
- `.octs` — **a text container**, and an easy one to miss: 457 files holding
  camouflage and item names in five languages. If your camo names stay English
  after you have translated every `common\localization` file, they are here
- `.mdn`, `.geom`, `.vlm` — models
- `.la2` — binary UI layouts (no readable text in them)
- `.gcx` — scripts

`ww\dat_compressed` holds the streamed cutscene and movie data. `sound_compressed`
holds audio. These are catalogued but this toolkit does not edit them.

---

## Text that is NOT in the text containers

Three places a translator loses time looking in the wrong file:

**Cutscene subtitles** are not in `common\localization`. They sit as
**plain text** inside `demoSwapped.dat` in `ww\dat_compressed`, with the five
languages laid out one after another in the same file. Its sibling
`movieSwapped` is video only — there is no text in it.

**The intro captions and the end credits are textures.** "In the not too
distant future...", the staff roll, and the on-screen chapter cards exist in no
text container at all. They are baked images, so translating them means the
texture path, not the text path.

**Some UI strings are baked into atlases too.** Before concluding that a label
is missing from the containers, check whether it is drawn as part of a sheet.

---

## Replacing a file while the game runs

If you use a runtime override loader instead of patching the archives, note
that the engine does not always ask for the plain asset name. Alongside
`<asset>_<n>.data` it requests a twin in a `temp` subfolder named
`<asset>_<n>_<hash>.data`, and for many textures **only the twin is ever
read**. An override placed under the plain name alone will silently do
nothing; match the exact name the loader logs.

Fonts supplied as `.ttf` under `common\font` are a separate case: the game
reads them, but through a path a file-override layer does not intercept, so
replacing a TrueType face that way does not work.

---

## Fonts

The fonts are textures, and the engine indexes them by the **raw byte** of the
string — there is no code-point path. That has enough consequences to deserve
its own document: see **[FONTS.md](FONTS.md)** for the atlas layout, how to add
an alphabet outside Latin-1, how to read the four different ways it fails on
screen, and why the choice between the bitmap atlas and the TrueType face is
not recorded anywhere in the text files.

`txnup_fonts_strict.py` locates the atlases: about **20 distinct glyph sheets**,
duplicated into **336 copies** across the archives. Patch every copy, not only
the screens you happened to walk through.

---

## Mip chains live in TWO files

A texture cache is split across a pair of `.dlz` files, and the halves are
stored in the order the engine wants to stream them, which is not the order you
want to read them:

```
<name>_d.dlz     mip level 0, on its own
<name>.dlz       the rest of the chain, levels 1..n
```

`<name>.dlz` comes first in load order but holds the *small* levels, so a naive
concatenation gives you the chain backwards. This was first reported by the
author of the **Codec** tool, whose fix concatenates the entries in reverse.

**You do not have to infer the order — it is declared in the data.** Each entry
has a 0x20-byte header; the `u32` at `+0x0C` is the number of bytes that belong
*in front* of this entry:

```
parent == 0     this entry already starts at level 0
parent >  0     this is the tail; exactly `parent` bytes of base data go first,
                and they are the entry with the same (strcode, index)
                whose size == parent
```

Measured over 10753 chains: **8440 tails, every one matched its base**, and
9314 chains assemble to exactly the byte size the mip pyramid predicts. The
remainder are textures shipped without mips at all.

**Do not read the `mips` field as a content descriptor.** A `nodld` cache
stores level 0 alone and still stamps the same value there, so 1225 entries
that look like a complete chain hold only the base level. Compare the entry
size against the pyramid arithmetic instead.

When you rebuild a texture, the split has to be preserved: level 0 goes back
into `<name>_d.dlz`, the tail into `<name>.dlz`.

---

## Pitfalls when re-encoding a texture

Four mistakes that each cost a working day:

- **Validate your block codec against an independent implementation.** A
  hand-written BC decoder that is subtly wrong produces images that look
  plausibly grungy rather than obviously broken, and you will blame the game.
  Decode the same block with a second library and diff.
- **DXT1 has punch-through alpha.** When `c0 <= c1` the fourth palette entry is
  transparent black, not a colour. An encoder that ignores this makes edited
  art come back harsh at every soft edge.
- **Compare textures premultiplied.** In DXT5 the colour of a fully transparent
  texel is arbitrary, so a raw RGB diff between two versions of the same image
  reports enormous differences that are not there. Multiply by alpha first.
  (This exact mistake produced 98 false failures in one verification run.)
- **Non-square textures.** Vertical sizing of non-square `.txn` images is a
  known source of off-by-one height bugs; check a tall or wide sheet
  explicitly rather than trusting a square test case.
