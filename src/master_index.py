r"""One index over everything that has been unpacked out of MGS4.

Walks the unpack trees and writes a single browsable TSV plus a summary, so a
texture or a string can be found without remembering which of the four
container layers it came out of.

What the file types turned out to be, measured on the extracted data rather
than assumed:

    .txn    texture descriptor tables.  In PC_TXN_UP they carry blob paths and
            resolve to real pixels; in stage_data they are HEADERS ONLY - their
            image offsets run past the end of the file and there are no path
            slots.
    .data   the pixel blobs themselves (PC_TXN_UP only)
    .cnf    a load MANIFEST - plain text listing the .txn a stage or slot pulls
            in, e.g. `s01a55l/cache/006d31ae.txn`.  This is how to tell which
            textures an area actually uses.
    .octs   camouflage / item names, several languages per record, separated by
            slashes: TIGERSTRIPE/TIGERSTRIPE/TIGR/TIGERSTREIFEN/MIM. TIGRATA/
            RAYA DE TIGRE, plus loose per-language strings.  A text container.
    .gcx    scripts - MGSCrypto-encrypted, so they read as noise until decoded.
    .la2    binary UI layouts.  No readable text in them; the "ASCII runs" a
            naive scan finds are repeated-byte noise, not strings.
    .mdn    models (the most numerous type by far)
    .jpg    ordinary JPEGs, directly viewable
"""

from __future__ import annotations

import argparse
import collections
import csv
import os

CATEGORY = {
    '.txn': 'texture-desc', '.data': 'texture-blob', '.dds': 'texture',
    '.jpg': 'image', '.png': 'image',
    '.cnf': 'manifest', '.octs': 'TEXT', '.gcx': 'script(enc)',
    '.la2': 'ui-layout', '.mdn': 'model', '.geom': 'model', '.vlm': 'model',
    '.mtar': 'material', '.mtsq': 'material', '.cpef': 'effect',
    '.bgm': 'audio', '.dbm': 'audio', '.ssp': 'audio', '.spc': 'audio',
    '.vfp': 'shader', '.dat': 'container',
}


def walk(roots):
    for root in roots:
        if not os.path.isdir(root):
            continue
        label = os.path.basename(root.rstrip('\\/'))
        for dp, _d, fs in os.walk(root):
            for f in fs:
                if f.startswith('_contents') or f in ('inventory.tsv',):
                    continue
                p = os.path.join(dp, f)
                ext = os.path.splitext(f)[1].lower()
                try:
                    size = os.path.getsize(p)
                except OSError:
                    continue
                yield {'tree': label, 'path': os.path.relpath(p, root),
                       'ext': ext, 'category': CATEGORY.get(ext, 'other'),
                       'size': size}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('roots', nargs='+')
    ap.add_argument('-o', '--out', required=True)
    a = ap.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or '.', exist_ok=True)

    by_tree = collections.Counter()
    by_ext = collections.Counter()
    by_cat = collections.Counter()
    bytes_cat = collections.Counter()
    n = 0
    with open(a.out, 'w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=['tree', 'category', 'ext', 'size',
                                           'path'], delimiter='\t')
        w.writeheader()
        for row in walk(a.roots):
            w.writerow({k: row[k] for k in w.fieldnames})
            by_tree[row['tree']] += 1
            by_ext[row['ext']] += 1
            by_cat[row['category']] += 1
            bytes_cat[row['category']] += row['size']
            n += 1
            if n % 20000 == 0:
                print('  %d files...' % n, flush=True)

    print('\n%d files indexed -> %s\n' % (n, a.out))
    print('%-16s %8s' % ('tree', 'files'))
    for k, v in by_tree.most_common():
        print('%-16s %8d' % (k, v))
    print('\n%-16s %8s %12s' % ('category', 'files', 'GB'))
    for k, v in by_cat.most_common():
        print('%-16s %8d %12.2f' % (k, v, bytes_cat[k] / 1e9))
    print('\ntop extensions: %s' % dict(by_ext.most_common(14)))


if __name__ == '__main__':
    main()
