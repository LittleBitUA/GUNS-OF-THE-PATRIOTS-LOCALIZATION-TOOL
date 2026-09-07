# Proving what broke the game

A translated container can be perfectly well formed and still crash the game.
This page is about closing that gap: how to find out which file, which record,
and why — without days of guessing.

The short version, learned the expensive way:

> An audit proves a file is **well formed**. It never proves the engine
> **accepts** it. Only the game can tell you that, so get it to tell you as
> early and as cheaply as possible.

---

## Get the repro first

The single largest time sink in this project was several days spent theorising
about a crash from its symptoms. It ended in one sentence from the person
playing: *"it happens when you skip the graveyard scene."*

A reproduction you can trigger on demand turns every later step into a
measurement. Without one, every experiment costs a full playthrough and proves
nothing when it does not crash.

Ask for the repro before writing a single diagnostic. If the answer is "it
just crashes sometimes", the next task is narrowing that, not reading code.

---

## Bisect by swapping whole files

Once it reproduces, do not read the data looking for something suspicious.
Swap.

1. Put back the **original** containers. Confirm it does not crash.
2. Put back **one** translated container. Test.
3. Repeat until it crashes. That names the file.

In this project four of the five containers were safe translated and one was
not, and the swap found it in under an hour. Reading the data first would not
have — the guilty file looked exactly as correct as the others.

Then bisect **inside** the file the same way: translate the first half of the
records, keep the second half original, test, repeat. The record you land on
is the one to look at.

---

## Read the crash dump

The game writes dumps to `MGS4\crash_dumps`. They are worth opening even if
you are not going to reverse anything, because two facts come out immediately:

- **Is it the same crash every time?** A stable faulting address means one
  bug. A wandering one means memory corruption, and the file you are testing
  may be innocent.
- **Where is it?** Subtract the module base from the faulting address to get
  an RVA, which is stable across runs and can be compared between dumps and
  looked up in a disassembler.

In this project every dump faulted at the same RVA, which is what turned a
vague "sometimes crashes" into a single deterministic bug worth chasing.

---

## What the bug turned out to be, and what it teaches

A bounded list with room for **1025 entries**, overflowing.

It had nothing to do with encoding, or with any individual string being
malformed. Translated strings are simply *longer* than English ones, and past
a certain total the engine walks off the end of a fixed buffer. The trigger
was cumulative, which is exactly why it looked random and why no per-record
audit could have found it.

Two things generalise:

- **A limit you have not measured is a limit you will hit.** If a container
  has any fixed-size structure in it, find the bound and check against it in
  the packer, rather than discovering it from a dump.
- **A crash that correlates with "more translation" is a size problem, not a
  content problem.** Stop looking for the bad string.

---

## Test yourself before testing the game

Two habits that caught real bugs here, both cheap:

**Round-trip with no edits.** Export a container and import it straight back,
then compare bytes. It should be identical. Ours was not — 15 of 4291 strings
changed, because the editable text format ate a `\r` and stripped a trailing
newline. Every one of those would have looked like a mysterious game-side
problem later.

**Validate a codec against an independent implementation, never against
itself.** Our block-compression decoder was wrong in a way that made edited
textures come back grainy, and it passed every self-test we had, because the
encoder and the decoder shared the same mistake. Decode with something else —
any image library that reads DDS — and compare.

---

## When it is not your file at all

Some things that look like translation bugs are not:

- A label that is present in the text container, translated, and still shows
  in English is often read from somewhere else entirely — a UI layout, a
  baked texture, or the executable. See
  [FORMATS.md](FORMATS.md#text-that-is-not-in-the-text-containers).
- A glyph that draws wrong is not always the text. Check whether the sheet is
  even yours before touching the encoding: see
  [FONTS.md](FONTS.md#reading-the-failure-on-screen).
- If you use a runtime override loader, check the log before anything else.
  A file that was never served explains a great deal of otherwise baffling
  behaviour: see [MODLOADER.md](MODLOADER.md#reading-the-log).
