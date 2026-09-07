# -*- coding: utf-8 -*-
r"""Export and re-import the MGS4 launcher's UI text.

The launcher is a separate Unity application, so none of the MGS4 text tools
reach it.  Its strings live in Addressables bundles under

    Launcher\launcher_Data\StreamingAssets\aa\StandaloneWindows64

in three containers, all built the same way - an id followed by one string
per language:

    textdata_ui.asset      UI_xxx     the menus
    textdata_gdpr.asset    GDPR_xxx   the privacy notice
    textdata_terms.asset   TS_xxx     the terms

Usage:

    python launcher_text.py list
    python launcher_text.py export <out.txt>
    python launcher_text.py import <in.txt> <out-dir>

`export` writes the same `### N  - KEY - ORIGINAL` block format the MGS4 text
tools use, so one editor and one workflow covers both.  `import` writes
rebuilt bundles into a directory you choose - it never writes into the game.

Which language column is replaced is chosen with --lang (default EN, because
the launcher, like the game, is set to English to load a translation).

Nothing here needs UABEANext or Unity: the type tree is in the bundle, so
the object is read and written directly (see typetree.py).
"""
from __future__ import annotations

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import launcher_paths
import serialized
import typetree
import unityfs

CONTAINERS = [
    ('ui', r'defaultlocalgroup_assets_module\textdata\textdata_ui.asset.bundle'),
    ('gdpr', r'defaultlocalgroup_assets_module\textdata\textdata_gdpr.asset.bundle'),
    ('terms', r'defaultlocalgroup_assets_module\textdata\textdata_terms.asset.bundle'),
]
LANGS = ['JP', 'EN', 'FR', 'IT', 'DE', 'ES', 'PT']
KEY = re.compile(r'^(UI|GDPR|TS)_\d+$')
HEAD = re.compile(r'^### (\d+)\s+-\s+(\S+)\s+-\s?(.*)$')


def _rows(obj):
    """Find the list of {id, per-language strings} inside a decoded object.

    The shape is not hardcoded: walk the decoded tree and take the first list
    whose entries carry a key like `UI_006`.  That survives a container being
    laid out slightly differently.
    """
    found = []

    def walk(v):
        if isinstance(v, dict):
            arr = v.get('Array')
            if isinstance(arr, list) and arr:
                first = arr[0]
                if isinstance(first, dict) and any(
                        isinstance(x, str) and KEY.match(x)
                        for x in first.values()):
                    found.append(arr)
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(obj)
    return found[0] if found else []


def _load(path):
    header, nodes = unityfs.read_nodes(path)
    for i, n in enumerate(nodes):
        if not n['data'].startswith(b'UnityFS'):
            try:
                sf = serialized.read(n['data'])
            except Exception:
                continue
            for o in sf['objects']:
                if not o['tree']:
                    continue
                blob = n['data'][o['start']:o['start'] + o['size']]
                try:
                    val, _n = typetree.read_object(o['tree'], blob)
                except Exception:
                    continue
                if _rows(val):
                    return header, nodes, i, sf, o, val
    raise SystemExit('no string table found in ' + os.path.basename(path))


def _key_of(row):
    for v in row.values():
        if isinstance(v, str) and KEY.match(v):
            return v
    return None


def _lang_fields(row):
    """Field names holding the per-language strings, in file order."""
    return [k for k, v in row.items()
            if isinstance(v, str) and not KEY.match(v)]


def cmd_list(_argv):
    root = launcher_paths.streaming_assets()
    for tag, rel in CONTAINERS:
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            print('  %-6s missing: %s' % (tag, rel))
            continue
        _h, _n, _i, _sf, _o, val = _load(p)
        rows = _rows(val)
        fields = _lang_fields(rows[0]) if rows else []
        print('  %-6s %4d rows, %d language columns %s'
              % (tag, len(rows), len(fields),
                 '(' + ', '.join(LANGS[:len(fields)]) + ')'))


def cmd_export(argv):
    out = argv[0]
    root = launcher_paths.streaming_assets()
    lang = _lang_index(argv)
    n = 0
    with io.open(out, 'w', encoding='utf-8', newline='\r\n') as fh:
        fh.write('# Launcher UI text.  Edit the line under each header.\n')
        fh.write('# A line break inside a string is written as |\n\n')
        for tag, rel in CONTAINERS:
            p = os.path.join(root, rel)
            if not os.path.exists(p):
                continue
            _h, _nd, _i, _sf, _o, val = _load(p)
            for row in _rows(val):
                key = _key_of(row)
                fields = _lang_fields(row)
                if not key or lang >= len(fields):
                    continue
                src = row[fields[lang]].replace('\n', '|')
                n += 1
                fh.write('### %d  - %s - %s\n%s\n\n' % (n, key, src, src))
    print('exported %d rows -> %s' % (n, out))


def _lang_index(argv):
    if '--lang' in argv:
        name = argv[argv.index('--lang') + 1].upper()
        if name not in LANGS:
            raise SystemExit('unknown language %r, expected one of %s'
                             % (name, ', '.join(LANGS)))
        return LANGS.index(name)
    return LANGS.index('EN')


def cmd_import(argv):
    txt, outdir = argv[0], argv[1]
    lang = _lang_index(argv)
    root = launcher_paths.streaming_assets()

    want = {}
    key = None
    body = []
    for line in io.open(txt, encoding='utf-8'):
        m = HEAD.match(line.rstrip('\r\n'))
        if m:
            if key and body:
                want[key] = '\n'.join(body).strip()
            key, body = m.group(2), []
        elif key is not None and not line.startswith('#'):
            body.append(line.rstrip('\r\n'))
    if key and body:
        want[key] = '\n'.join(body).strip()
    print('translations read: %d' % len(want))

    os.makedirs(outdir, exist_ok=True)
    for tag, rel in CONTAINERS:
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            continue
        header, nodes, ni, sf, obj, val = _load(p)
        hit = 0
        for row in _rows(val):
            k = _key_of(row)
            fields = _lang_fields(row)
            if k in want and lang < len(fields):
                row[fields[lang]] = want[k].replace('|', '\n')
                hit += 1
        if not hit:
            continue
        blob = typetree.write_object(obj['tree'], val)
        nodes[ni]['data'] = serialized.rebuild(nodes[ni]['data'], sf,
                                               {obj['path_id']: blob})
        dst = os.path.join(outdir, os.path.basename(rel))
        size = unityfs.write(dst, header, nodes)
        print('  %-6s %4d rows -> %s (%d bytes)'
              % (tag, hit, os.path.basename(dst), size))

    print()
    print('Bundles written to %s.' % outdir)
    print('The launcher has no mod system: installing them means overwriting '
          'the originals, so back those up first.')
    print('A rebuilt bundle also changes size, and the Addressables catalog '
          'stores a CRC - see docs/LAUNCHER.md.')


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('list', 'export', 'import'):
        raise SystemExit(__doc__)
    argv = [a for a in sys.argv[2:]]
    {'list': cmd_list, 'export': cmd_export, 'import': cmd_import}[sys.argv[1]](argv)


if __name__ == '__main__':
    main()
