r"""DDS mip arithmetic and BC1 / BC3 (DXT1 / DXT5) decoding for MGS4.

    level_size / level_sizes   DDS mip-chain byte sizes
    decode_bc                  BC1 (DXT1) and BC3 (DXT5) -> RGBA, via Pillow
    ink_map                    premultiplied luminance ("is there art here")
    row_period / cell_grid / gap_score / looks_like_atlas
                               a typeface-blind glyph-grid detector

The glyph-grid detector assumes 32 columns, which is what the MGS4 font
atlases use.  A hit means "worth a look", not proof.
"""
from __future__ import annotations

import numpy as np

DXT1, DXT5, RGBA32 = 0x09, 0x0B, 0x03
NAMES = {DXT1: 'DXT1', DXT5: 'DXT5', RGBA32: 'RGBA32'}

COLS = 32
AZ = slice(1, 27)               # columns of row 1 holding 'A'..'Z'
MIN_GAP = 1.25                  # lowest real atlas 1.47, highest foliage 1.01


# ------------------------------------------------------------------- dds --

def level_size(w: int, h: int, fmt: int) -> int:
    if fmt in (DXT1, DXT5):
        return (max(1, (w + 3) // 4) * max(1, (h + 3) // 4)
                * (8 if fmt == DXT1 else 16))
    return w * h * 4


def level_sizes(w: int, h: int, fmt: int):
    out = []
    while True:
        out.append(level_size(w, h, fmt))
        if w == 1 and h == 1:
            return out
        w, h = max(1, w // 2), max(1, h // 2)


# ---------------------------------------------------------------- decode --

def _c565(v):
    r = ((v >> 11) & 31).astype(np.uint16)
    g = ((v >> 5) & 63).astype(np.uint16)
    b = (v & 31).astype(np.uint16)
    return (((r * 255 + 15) // 31).astype(np.uint8),
            ((g * 255 + 31) // 63).astype(np.uint8),
            ((b * 255 + 15) // 31).astype(np.uint8))


def decode_bc(data: bytes, w: int, h: int, fmt: int) -> np.ndarray:
    """BC1 (0x09) / BC3 (0x0B) -> (h, w, 4) uint8.

    Backed by Pillow's DDS reader, which is a battle-tested reference decoder.
    The previous hand-rolled numpy path had a colour-interpolation bug that
    scattered wrong pixels through flat fills (the "grunge" on the FOXHOUND
    logo), so it was replaced wholesale rather than patched.

    We wrap the raw block data in a minimal DDS header and let Pillow decode a
    single mip level.
    """
    from PIL import Image
    import io, struct

    fourcc = b'DXT1' if fmt == DXT1 else b'DXT5'
    n = level_size(w, h, fmt)
    payload = data[:n] + bytes(max(0, n - len(data)))

    hdr = bytearray(128)
    hdr[0:4] = b'DDS '
    struct.pack_into('<I', hdr, 4, 124)                       # dwSize
    struct.pack_into('<I', hdr, 8, 0x1 | 0x2 | 0x4 | 0x1000)  # caps|height|width|pixelformat
    struct.pack_into('<I', hdr, 12, h)
    struct.pack_into('<I', hdr, 16, w)
    struct.pack_into('<I', hdr, 20, n)                        # linear size
    struct.pack_into('<I', hdr, 28, 1)                        # mip count
    struct.pack_into('<I', hdr, 76, 32)                       # pf size
    struct.pack_into('<I', hdr, 80, 0x4)                      # DDPF_FOURCC
    hdr[84:88] = fourcc
    struct.pack_into('<I', hdr, 108, 0x1000)                  # caps texture

    im = Image.open(io.BytesIO(bytes(hdr) + payload)).convert('RGBA')
    return np.array(im, dtype=np.uint8)[:h, :w]

# ------------------------------------------------------------- structure --

def ink_map(rgba):
    """Premultiplied luminance: equals alpha for white-on-transparent sheets
    and luminance for sheets that keep the glyphs in colour with no alpha."""
    lum = (rgba[:, :, :3].astype(np.uint32).sum(axis=2) // 3).astype(np.float32)
    return lum * (rgba[:, :, 3].astype(np.float32) / 255.0)


def row_period(ink, thr):
    """Cell height from the row-ink profile.  Take the SMALLEST period whose
    rows agree - the 2x/3x harmonics often correlate better, so a plain argmax
    returns 72 for a font whose rows are 24 px tall."""
    prof = (ink > 8).mean(axis=1)
    nz = np.nonzero(prof > 0.002)[0]
    if len(nz) < 8:
        return None
    p = prof[:nz[-1] + 1].astype(np.float64)
    for ch in range(6, len(p) // 2 + 1):
        rows = len(p) // ch
        if rows < 2:
            break
        m = p[:rows * ch].reshape(rows, ch)
        m = m - m.mean(axis=1, keepdims=True)
        nrm = np.linalg.norm(m, axis=1)
        if (nrm < 1e-9).any():
            continue
        u = m / nrm[:, None]
        c = u @ u.T
        if (c.sum() - rows) / (rows * (rows - 1)) > thr:
            return ch
    return None


def cell_grid(ink, ch, maxrows=6, cols=COLS):
    h, w = ink.shape
    cw = w // cols
    rows = min(maxrows, h // ch)
    return np.array([[(ink[r * ch:(r + 1) * ch, k * cw:(k + 1) * cw] > 8).mean()
                      for k in range(cols)] for r in range(rows)])


def gap_score(ink, ch, cols=COLS):
    """How much emptier a cell's edges are than its middle.  Foliage masks are
    periodic in both axes and pass every other test; what they lack is the
    gutter a font leaves at the cell boundary."""
    h, w = ink.shape
    cw = w // cols
    rows = min(6, h // ch)
    band = (ink[:rows * ch] > 8).mean(axis=0)
    fold = band[:cols * cw].reshape(cols, cw).mean(axis=0)
    if fold.max() < 1e-6:
        return 0.0
    edge = max(1, cw // 8)
    outer = float(np.concatenate([fold[:edge], fold[-edge:]]).mean())
    inner = float(fold[edge:-edge].mean()) if cw > 2 * edge else float(fold.mean())
    return inner / (outer + 1e-6)


def looks_like_atlas(ink, loose=False, cols=COLS):
    """-> (cell_height, rows, az_hits) if this looks like a glyph grid."""
    ch = row_period(ink, 0.60 if loose else 0.75)
    if ch is None:
        return None
    g = cell_grid(ink, ch, cols=cols)
    if g.shape[0] < 2:
        return None
    az = int((g[1, AZ] > 0.02).sum())
    if loose:
        return (ch, g.shape[0], az) if az >= 20 else None
    if g[0, 0] > 0.06 or az < 26 or gap_score(ink, ch, cols) < MIN_GAP:
        return None
    return ch, g.shape[0], az
