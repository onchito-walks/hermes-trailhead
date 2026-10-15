#!/usr/bin/env python3
"""Trailhead favicon — hand-built 32x32 pixel-art derivative of the logo.

Same palette as the main logo: navy field, golden sky, cream sun/mist,
blue ridge band, dark wanderer on a peak. Writes a P3 PPM (1px per cell)
for lossless conversion; never resampled except by nearest-neighbor.
"""
CELLS = [
    "GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG",
    "GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG",
    "GGGGGGGGGGGGGGGGGGSSSGGGGGGGGGGG",
    "GGGGGGGGGGGGGGGGGSSSSSGGGGGGGGGG",
    "GGGGGGGGGGGGGGGGGSSSSSGGGGGGGGGG",
    "GGGGGGGGGGGGGGGGGGSSSGGGGGGGGGGG",
    "GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG",
    "GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG",
    "GGGGGGGGGGGGGGGHHGGGGGGGGGGGGGGG",
    "GGGGGGGGGGGGGGGFFGGGGGGGGGGGGGGG",
    "GGGGGGGGGGGGGGFFFFGGGGGGGGGGGGGG",
    "GGGGGGGGGGGGGGFFFFGFGGGGGGGGGGGG",
    "SSSSSSSSSSSSSSFFFFSFSSSSSSSSSSSS",
    "BBBBBBBBBBBBBBFFFFBFBBBBBBBBBBBB",
    "BBBBBBBBBBBBBBFFFFBFBBBBBBBBBBBB",
    "BBBBBBBBBBBBBBFFFFBFBBBBBBBBBBBB",
    "..............FFFF.F............",
    ".............KFFFFKF............",
    ".............KFFFFKF............",
    "............KKKKKKKK............",
    "...........KKKKKKKKKK...........",
    "..........KKKKKKKKKKKK..........",
    ".........KKKKKKKKKKKKKK.........",
    "........KKKKKKKKKKKKKKKK........",
    ".......KKKKKKKKKKKKKKKKKK.......",
    "......KKKKKKKKKKKKKKKKKKKK......",
    ".....KKKKKKKKKKKKKKKKKKKKKK.....",
    "....KKKKKKKKKKKKKKKKKKKKKKKK....",
    "...KKKKKKKKKKKKKKKKKKKKKKKKKK...",
    "..KKKKKKKKKKKKKKKKKKKKKKKKKKKK..",
    ".KKKKKKKKKKKKKKKKKKKKKKKKKKKKKK.",
    "KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK",
]

PALETTE = {
    "G": (232, 196, 106),   # golden sky
    "S": (245, 237, 214),   # cream sun / mist
    "B": (108, 127, 181),   # blue ridge band
    "K": (46, 58, 98),      # near peak
    ".": (20, 26, 48),      # navy field
    "F": (13, 16, 32),      # wanderer silhouette
    "H": (138, 90, 60),     # hair
}

assert len(CELLS) == 32 and all(len(r) == 32 for r in CELLS)

with open("favicon-32.ppm", "w") as f:
    f.write("P3\n32 32\n255\n")
    for row in CELLS:
        for ch in row:
            f.write(" ".join(str(c) for c in PALETTE[ch]) + " ")
        f.write("\n")
print("wrote favicon-32.ppm")
