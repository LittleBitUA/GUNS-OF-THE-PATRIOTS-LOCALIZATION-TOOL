# Shipping a translation without touching the archives

MGS4 (PC) has a community runtime override loader — an ASI plugin that
intercepts the game's file reads and serves a replacement from a mod folder.
That turns a localization from "rebuild a 4.9 GB archive" into "drop a file in
a directory", and it is what makes an installable, uninstallable translation
practical.

This page is what we learned using it. It is not the loader's documentation —
read its own README for configuration — but the behaviour below cost us days
to work out, and none of it is obvious from the outside.

---

## What can be overridden, and what cannot

The loader indexes a mod package and serves files by the path the game asks
for. Three different mechanisms are in play, and they do not cover the same
things.

| Asked for as | Overridable | Notes |
|---|---|---|
| a virtual archive path | yes | textures, localization containers |
| a plain loose path | yes | logged as `loose-override` |
| an **extended-length** path (`\\?\C:\...`) | **no** | see below |
| a resource inside a `.slot` archive | yes, separately | `slots/` in the mod |
| a TrueType face under `common\font` | no | the game reads it through a path the loader never sees |

### The extended-length path blind spot

Windows lets a program open a file either as `C:\game\file` or as
`\\?\C:\game\file` — the second form lifts the 260-character path limit. The
game uses **both**, depending on which subsystem is loading.

The loader (v0.0.2) only resolves overrides for the plain form. Measured over
one session:

```
loose-override   plain path            3
loose            extended \\?\      1703      <- never overridden, not once
loose            plain path           36
```

Every single extended-length request fell through to the original file. This
is not configurable and there is no warning in the log — the read is simply
reported as `loose` instead of `loose-override`.

It matters because UI layout files (`.la2`) are requested that way. If you
need to replace one, a mod override will silently do nothing, and the only
route is placing the file where the game itself looks (see below).

---

## Directories a localization actually replaces

For orientation, here is the shape of a text-and-fonts mod. Paths are relative
to the mod package root (`MGS4\mods\<your mod>`).

```
common\localization\lang\lang_en          menus, HUD, item names
common\localization\codec\codec_en        codec dialogue
common\localization\demo\demo_en          cutscene subtitles
common\localization\movie\movie_en        pre-rendered movie subtitles
common\localization\spc\spc_en            in-mission speech

BolaTextures\textures-compression-output\PC_TXN_UP_Cache\...\*.data
                                          the font atlases (hundreds of copies)

slots\<slot>\<page>\<id>                  resources inside a .slot archive
```

The `*_en` naming is not a typo: a translation replaces the **English**
files, and the game has to be set to English for them to load. There is no
"add a language" path.

---

## Textures reload live; text does not

Texture overrides are served **on demand** — the game asks for a blob when it
loads a screen, so an edited font atlas appears as soon as you leave that
screen and come back. No restart.

The localization containers are read **once at startup**. Changing them needs
a full restart.

Two practical consequences:

- Iterating on fonts is much faster than it looks. Repaint, re-enter the menu,
  look. Do not restart the game every round.
- **Never delete or rebuild the mod folder while the game is running.** The
  next screen that asks for a sheet gets the stock one, and the text turns to
  Latin-1 punctuation — which looks exactly like a broken pipeline.

---

## Slot archives, and the logging catch-22

Layouts and some textures live inside `slotdat\*.slot` archives. Those are
never requested by file path, so a path override cannot reach them. The loader
has a separate mechanism:

```
slots/<slot>/<file>
slots/<slot>/<page>/<file>
```

- `<slot>` is the slot **name** (`slot_chibrowser`), and the loader hashes it.
- `<page>` must be hexadecimal.
- `<file>`'s stem is parsed as hex — that is an exact resource id. If it is not
  hex, the name is hashed instead.

To write one you need the page and resource id, and the loader will print them
for every resource the game loads — `LogSlotResources = true` emits
`Slot resource: slot=… page=… id=… size=…`.

**Except it prints nothing until you already have a slot override.** The
logger resolves the slot hash back to a name through a table that is populated
*only from the `slots/` folders in your own mod*. No folders, no names, no log
lines — and the hook fires the whole time, silently.

The way out is a listener: an entry whose page and id cannot match anything.

```
mods\<your mod>\slots\slot_chibrowser\ffffffff\ffffffff     (any small file)
```

It never resolves against a real resource, so it changes nothing in the game,
but it registers the slot name and the log starts naming that slot's
resources. Add one per slot you want to enumerate.

---

## UI layouts have a loose path the game checks first

Before falling back to the slot archive, the engine looks for a layout as a
loose file:

```
common\ui_rpl_files\PC\slot\<slot>\<page>\cache\<id>.la2
```

The game ships some layouts there already, so the path is supported rather
than a trick, and a file placed there **is** read (`opened=true` in the log).
Because these requests use the extended-length form, a mod override will not
work — this is the one case where the file has to go into the game folder.

Before spending effort on a layout edit, verify the field is live: see the
caution in [FORMATS.md](FORMATS.md#ui-layouts-la2-carry-live-text). Most of
those fields are placeholders the code overwrites, and an edit to one produces
no visible change at all.

---

## Reading the log

Three settings are worth turning on while working, and off before shipping:

```ini
LogOverrides      = true    ; what got replaced
LogAllFileReads   = true    ; every read, with source= and opened=
LogSlotResources  = true    ; slot resources (needs a listener, see above)
```

`LogAllFileReads` writes megabytes per session and slows loading, so a build
you hand to someone else must ship with it off. If your release script copies
the `.ini` out of your own game folder, it will copy your verbose settings
with it — make the script force them off instead of remembering to do it by
hand.

The field to read is `source=`:

| `source=` | meaning |
|---|---|
| `archive` | came from the game's own archive |
| `loose` | a real file on disk, not from your mod |
| `loose-override` / `mod-override` | your file was served |

If a file you overrode still shows `archive` or `loose`, the override did not
apply — check the exact name the log prints, including any `temp/` component.
