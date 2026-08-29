# -*- coding: utf-8 -*-
r"""Locate the Metal Gear Solid 4 (PC, Master Collection) install.

Resolution order:
    1. the MGS4_DIR environment variable
    2. every Steam library on the machine, looking for the MGS4 folder
    3. give up and tell the user to set MGS4_DIR

Nothing here writes into the game; it only resolves read paths.  Keep it that
way - every tool in this repo reads from the game and writes elsewhere.
"""
from __future__ import annotations

import os
import sys

APPID = '2379780'                      # MGS4 Master Collection on Steam
LEAF = os.path.join('METAL GEAR SOLID 4', 'MGS4')


def _steam_libraries():
    roots = []
    if os.name == 'nt':
        try:
            import winreg
            for hive, key in ((winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam'),
                              (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam')):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        roots.append(winreg.QueryValueEx(k, 'SteamPath')[0])
                except OSError:
                    pass
        except ImportError:
            pass
    roots += [r'C:\Program Files (x86)\Steam', os.path.expanduser('~/.steam/steam')]

    libs = []
    for r in roots:
        vdf = os.path.join(r, 'steamapps', 'libraryfolders.vdf')
        libs.append(r)
        if os.path.isfile(vdf):
            import re
            for m in re.finditer(r'"path"\s*"([^"]+)"', open(vdf, encoding='utf-8', errors='ignore').read()):
                libs.append(m.group(1).encode().decode('unicode_escape'))
    return libs


def find_game(explicit: str | None = None) -> str:
    for cand in (explicit, os.environ.get('MGS4_DIR')):
        if cand and os.path.isdir(cand):
            return cand
    for lib in _steam_libraries():
        p = os.path.join(lib, 'steamapps', 'common', LEAF)
        if os.path.isdir(p):
            return p
    raise SystemExit(
        'MGS4 install not found.  Set the MGS4_DIR environment variable to the '
        'folder that contains mgs4.exe, e.g.\n'
        r'  set MGS4_DIR=D:\SteamLibrary\steamapps\common\METAL GEAR SOLID 4\MGS4')


def txn_up(branch: str = 'common', game: str | None = None) -> str:
    return os.path.join(find_game(game), branch, 'textures', 'PC_TXN_UP')


def texture_pak(branch: str = 'common', game: str | None = None) -> str:
    return os.path.join(txn_up(branch, game), 'paks', 'TextureData.pak')
