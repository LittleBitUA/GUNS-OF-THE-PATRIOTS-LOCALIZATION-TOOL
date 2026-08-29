r"""Extract every entry of any MGS4 VPAK, whatever it holds.

`txnup_unpack.py` handles the PC_TXN_UP pair, where an index pak references
blobs in a data pak.  This one is the general case: it walks a pak's TOC and
writes each entry out under its own name, so `stage_data_compressed`,
`sound_compressed`, `vfp_PC` and `dat_compressed` all come out too.

READ ONLY.  It refuses to write anywhere under `steamapps`.

Two things worth knowing before reading the output:

* **The `.txn` in `stage_data_compressed` are headers, not textures.**  Their
  image descriptors point past the end of the file - a 256-byte `.txn` will
  claim an image ending at offset 366 336 - and unlike the PC_TXN_UP ones they
  carry **no path slots** in the tail.  They are an older
  descriptors; the Master Collection ships the actual pixels in PC_TXN_UP,
  often at a higher resolution.  `stage00/title/cache/00042faa.txn` is the
  clearest example: 1024x256 in the stage layer, 2048x512 in PC_TXN_UP.
* Entries over the pak's chunk size are stored as several independently
  LZ4-compressed chunks; `vpak.fetch` handles that.
"""

from __future__ import annotations

import argparse
import collections
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import vpak


def extract(pak: str, out: str, only: str = '', skip_over: int = 0,
            list_only: bool = False) -> dict:
    toc = vpak.toc(pak)
    stats = collections.Counter()
    sizes = collections.Counter()
    rows = []
    os.makedirs(out, exist_ok=True)
    label = os.path.basename(pak)

    for i, (name, rec) in enumerate(sorted(toc.items())):
        ext = os.path.splitext(name)[1].lower()
        sizes[ext] += rec[0]
        stats[ext] += 1
        if only and only.lower() not in name.lower():
            continue
        if skip_over and rec[0] > skip_over:
            stats['skipped_big'] += 1
            rows.append((name, rec[0], 'SKIPPED too big'))
            continue
        if list_only:
            rows.append((name, rec[0], ''))
            continue
        try:
            data = vpak.fetch(pak, rec)
        except Exception as exc:
            stats['failed'] += 1
            rows.append((name, rec[0], 'FAILED %s' % str(exc)[:60]))
            continue
        p = os.path.join(out, name.replace('/', os.sep).replace('\\', os.sep))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as fh:
            fh.write(data)
        stats['written'] += 1
        rows.append((name, len(data), ''))
        if stats['written'] % 500 == 0:
            print('   %s: %d written' % (label, stats['written']), flush=True)

    with open(os.path.join(out, '_contents_%s.tsv' % label), 'w',
              encoding='utf-8') as fh:
        fh.write('name\tsize\tnote\n')
        for r in rows:
            fh.write('%s\t%d\t%s\n' % r)
    return {'entries': len(toc), 'written': stats['written'],
            'failed': stats['failed'], 'skipped_big': stats['skipped_big'],
            'by_ext': {k: v for k, v in stats.items() if k.startswith('.')},
            'bytes_by_ext': {k: v for k, v in sizes.most_common(8)}}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('paks', nargs='+', help='.pak files, or a directory to walk')
    ap.add_argument('-o', '--out', required=True)
    ap.add_argument('--only', default='', help='substring filter on the entry name')
    ap.add_argument('--skip-over', type=int, default=0,
                    help='skip entries larger than this many bytes')
    ap.add_argument('--list', action='store_true', help='inventory only')
    a = ap.parse_args()
    if 'steamapps' in a.out.lower().replace('/', '\\'):
        raise SystemExit('refusing to write inside the game directory')

    targets = []
    for p in a.paks:
        if os.path.isdir(p):
            for dp, _d, fs in os.walk(p):
                targets += [os.path.join(dp, f) for f in fs
                            if f.lower().endswith('.pak')]
        else:
            targets.append(p)

    grand = collections.Counter()
    for p in sorted(targets):
        print('== %s' % p, flush=True)
        try:
            s = extract(p, a.out, a.only, a.skip_over, a.list)
        except Exception as exc:
            print('   FAILED: %s' % exc)
            continue
        print('   %d entries, %d written, %d failed, %d skipped'
              % (s['entries'], s['written'], s['failed'], s['skipped_big']))
        print('   %s' % s['by_ext'])
        for k in ('entries', 'written', 'failed', 'skipped_big'):
            grand[k] += s[k]
    print('\nTOTAL %s' % dict(grand))


if __name__ == '__main__':
    main()
