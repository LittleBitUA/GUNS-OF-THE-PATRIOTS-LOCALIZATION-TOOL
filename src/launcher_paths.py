# -*- coding: utf-8 -*-
r"""Locate the MGS4 launcher's Addressables folder.

The launcher sits next to the game, not inside it:

    METAL GEAR SOLID 4\
        MGS4\                       the game
        Launcher\                   a separate Unity application

so resolving it is one step up from what mgs4paths finds.  Reads only.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import mgs4paths

AA = os.path.join('launcher_Data', 'StreamingAssets', 'aa',
                  'StandaloneWindows64')


def launcher_dir() -> str:
    """-> ...\\METAL GEAR SOLID 4\\Launcher"""
    game = mgs4paths.find_game()               # ...\METAL GEAR SOLID 4\MGS4
    root = os.path.dirname(game)
    path = os.path.join(root, 'Launcher')
    if not os.path.isdir(path):
        raise SystemExit(
            'Launcher folder not found next to the game.\n'
            'Expected: %s' % path)
    return path


def streaming_assets() -> str:
    """-> the folder holding the Addressables bundles."""
    path = os.path.join(launcher_dir(), AA)
    if not os.path.isdir(path):
        raise SystemExit('Addressables folder not found:\n  %s' % path)
    return path
