# The launcher is a separate game

Metal Gear Solid 4 ships with a launcher — the window that appears before the
game and lets you pick a language, adjust settings and read the terms. None of
the MGS4 tools touch it, because it is not MGS4: it is an independent **Unity
6 (IL2CPP) application** sitting next to the game.

```
METAL GEAR SOLID 4\
    MGS4\           the game        — VPAK archives, .txn textures, lang_en …
    Launcher\       Unity 6         — Addressables bundles, TextMeshPro fonts
```

A translation that stops at the game is visibly unfinished: the first screen
the player sees is still English, and the language selector that decides
whether your translation loads at all lives here.

---

## What is inside

Everything is under

```
Launcher\launcher_Data\StreamingAssets\aa\StandaloneWindows64
```

as Addressables bundles. Three of them hold the text, in **321 rows**:

| bundle | ids | rows | content |
|---|---|---|---|
| `textdata_ui.asset.bundle` | `UI_xxx` | 180 | menus, buttons, settings |
| `textdata_gdpr.asset.bundle` | `GDPR_xxx` | 74 | privacy notice |
| `textdata_terms.asset.bundle` | `TS_xxx` | 67 | terms of use |

Every row is an id followed by one string per language, seven columns:

```
JP  EN  FR  IT  DE  ES  PT
```

There is no "add a language" path, exactly as in the game. A translation
replaces a column — `EN` if the launcher is set to English.

Fonts are a second set of bundles, six of them, and each uses a **different
atlas size**, so a font pipeline written for one will not fit the others
unmodified.

---

## Reading the bundles without Unity

The usual advice for Unity assets is UABEANext, AssetStudio, or dumping the
IL2CPP metadata. None of that is needed here, for one reason:

> These bundles ship with `m_EnableTypeTree = 1`.

The structure of every object is described **inside the file**. Read the type
tree, and you can decode a `MonoBehaviour` into plain values, edit them, and
serialise them back — with no game assemblies, no Il2CppDumper, and no Unity
install.

Three modules in `src/` implement that, and they are ordinary format code you
can reuse for any Unity 6 bundle built the same way:

| module | what it does |
|---|---|
| `unityfs.py` | the `UnityFS` container: blocks, nodes, LZ4/LZ4HC, and writing one back |
| `serialized.py` | `SerializedFile`: object table, type trees, rebuilding with objects replaced |
| `typetree.py` | decode an object to values through its tree, and encode it again |

### The honesty check that matters

A type-tree reader is easy to get subtly wrong, and a wrong one produces a
file the game rejects for no visible reason. Use a round trip as the test:
read an object through the tree, write it straight back **with no edits**, and
compare bytes. Identical means the tree was parsed correctly. Anything else
means stop and fix the reader before editing a single string.

Two rules carry most of the weight:

- `metaFlag & 0x4000` on a node means **align the stream to 4 bytes after
  that field**;
- an array is a node with `typeFlags & 1` and exactly two children, `size`
  and `data`.

---

## Rebuilding: two things that cost a day each

**Objects align to 16 bytes, not 8.** When writing the data area back, each
object starts on a 16-byte boundary measured from `dataOffset`. Using 8
produces a file 8-24 bytes short, and the reason is visible in any original:
the gaps between objects are 12, 4, 12 — not divisible by 8, but fine on 16.

**In SerializedFile v22 the legacy 32-bit header fields stay zero.** The real
`fileSize` and `dataOffset` are the 64-bit fields that follow. Writing the
size into the legacy field as well leaves a file that differs from a correct
one by three bytes.

The object table itself does not need rebuilding: its records are fixed
length, so an object growing does not move the table. Patch `byteStart` and
`byteSize` in place and correct the file size in the header.

---

## Installing, and the catalog CRC

The launcher has **no mod system**. There is no override loader here, so
installing a translation means overwriting the original bundles — back them
up first, and make your installer restore them.

Addressables also keeps a catalog (`catalog.bin`) that records a CRC per
bundle, and a rebuilt bundle is a different size and a different CRC.

> The CRC in the catalog is a **crc32 of the DECOMPRESSED bundle**, not of
> the file on disk.

That is worth knowing before you go looking for a hashing scheme: it is plain
crc32, applied to the wrong bytes if you use the file as it sits.

---

## The tool in this repo

```
python src/launcher_text.py list
python src/launcher_text.py export launcher.txt
python src/launcher_text.py import launcher.txt out-bundles [--lang EN]
```

`export` writes the same `### N  - KEY - ORIGINAL` block format the MGS4 text
tools use, so the same editor and the same review pass cover both. `import`
writes rebuilt bundles into a directory you name — like everything else here,
it reads from the game and never writes into it.

`list` is the quick check that the tools can see your install:

```
  ui      180 rows, 7 language columns (JP, EN, FR, IT, DE, ES, PT)
  gdpr     74 rows, 7 language columns (JP, EN, FR, IT, DE, ES, PT)
  terms    67 rows, 7 language columns (JP, EN, FR, IT, DE, ES, PT)
```

The string table is located by walking the decoded object and taking the first
list whose entries carry an id like `UI_006`, rather than by a hardcoded field
path — so a container laid out slightly differently still works.
