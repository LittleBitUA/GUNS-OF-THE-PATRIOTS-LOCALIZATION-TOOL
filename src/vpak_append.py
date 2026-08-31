# -*- coding: utf-8 -*-
r"""Replace a VPAK entry with data that does NOT fit its slot, by relocating it.

`vpak_write.replace` writes in place and refuses when the recompressed blob is
larger than the original - which is the normal case for an edited texture.  The
stock art is extremely compressible (title/00897aa9 is 699 080 bytes stored in
54 152 - almost 13:1) because it is mostly flat, and any real edit breaks those
long runs.  Even keeping 97.7 % of the original bytes and re-encoding only the
changed 4x4 blocks still came out 10 % over the slot.

So the blob has to move.  A VPAK record carries an explicit `offset`, so that
is legitimate here because the record carries an explicit offset field;
formats that bake offsets into code cannot be relocated this way.

Layout is  [16-byte header][body][toc, exactly tocSize bytes at the end].
To relocate:

    1. lift the TOC off the end
    2. write the new blob where the TOC used to start
    3. put the TOC back after it - its size does not change, so the header
       needs no edit
    4. patch that record's `compressed`, `offset` and chunk table, which have
       all shifted down by len(new blob)

The old bytes stay where they were, so any OTHER record still pointing at them
keeps working untouched - which matters, because 60 % of the records in this
pak are aliases sharing a byte range.
"""
import json, os, shutil, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lz4.block
import vpak

# Where the relocation registry is kept.  Override with MGS4_RELOCATE_DIR.
STOCK = os.environ.get('MGS4_RELOCATE_DIR') or os.path.join(
    os.path.expanduser('~'), '.mgs4-tools', 'vpak_relocate')
LEVEL = 12


def _index_path():
    os.makedirs(STOCK, exist_ok=True)
    return os.path.join(STOCK, 'relocated.json')


def _load():
    p = _index_path()
    return json.load(open(p)) if os.path.isfile(p) else {}


def _save(d):
    json.dump(d, open(_index_path(), 'w'), indent=1)


def append_replace(pak: str, name: str, data: bytes, dry: bool = False) -> bool:
    recs = vpak.records(pak)
    if name not in recs:
        print('   [no such entry] %s' % name)
        return False
    rec = recs[name]
    if len(data) != rec['unc']:
        print('   [size changed] %d != %d' % (len(data), rec['unc']))
        return False

    csize = rec['csize'] or len(data)
    ccount = max(1, len(rec['chunks']) or 1)
    parts, offs = bytearray(), []
    for i in range(ccount):
        offs.append(len(parts))
        parts += lz4.block.compress(data[i * csize:(i + 1) * csize],
                                    mode='high_compression', compression=LEVEL,
                                    store_size=False)
    blob = bytes(parts)

    size = os.path.getsize(pak)
    with open(pak, 'rb') as f:
        f.seek(12)
        toc_size = struct.unpack('<I', f.read(4))[0]
    toc_at = size - toc_size
    print('   new blob %d bytes (slot was %d) -> relocating to 0x%X'
          % (len(blob), rec['comp'], toc_at))
    if dry:
        return True

    idx = _load()
    # `pak_size` is the guard: every other value here is an ABSOLUTE offset
    # into this pak as it is right now, and relocating moves the table of
    # contents.  Anything that replays these entries must refuse when the
    # pak's current size differs, or it will write over the moved TOC.
    idx.setdefault(os.path.basename(pak), {})[name] = {
        'off': rec['off'], 'comp': rec['comp'], 'csize': rec['csize'],
        'chunks': rec['chunks'], 'field_off': rec['field_off'],
        'chunk_off': rec['chunk_off'], 'pak_size': size}
    _save(idx)

    with open(pak, 'r+b') as f:
        f.seek(toc_at)
        toc = f.read(toc_size)
        f.seek(toc_at)
        f.write(blob)
        f.write(toc)
        shift = len(blob)
        # the record's fields have moved down by `shift`
        fo = rec['field_off'] + shift
        f.seek(fo + 8)
        f.write(struct.pack('<Q', len(blob)))          # compressed
        f.write(struct.pack('<Q', toc_at))             # offset
        if rec['chunks']:
            f.seek(rec['chunk_off'] + shift)
            f.write(struct.pack('<%dQ' % len(offs), *offs))
    return True


def verify(pak: str, name: str, expect: bytes) -> bool:
    got = vpak.fetch(pak, vpak.toc(pak)[name])
    ok = got == expect
    print('   verify: %s (%d bytes)' % ('OK' if ok else 'MISMATCH', len(got)))
    return ok


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['restore', 'list'])
    a = ap.parse_args()
    idx = _load()
    if a.cmd == 'list':
        for pk, ents in idx.items():
            print(pk)
            for n, v in ents.items():
                print('   %s  off 0x%X comp %d' % (n, v['off'], v['comp']))
    else:
        print('restore is not implemented - the original bytes are still in the '
              'pak; re-point the record using the values in relocated.json')


if __name__ == '__main__':
    main()
