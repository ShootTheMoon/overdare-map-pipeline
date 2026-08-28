# -*- coding: utf-8 -*-
"""
Recover the embedded textures from the wave-4 (Gwollaegaksa) FBX files.

Why this is needed
------------------
The first 17 KHS assets record their textures as `T_<Name>_BC.png`, which is also
how the loose PNGs are named inside the zip, so matching by basename worked.
The Gwollaegaksa batch was exported differently: the FBX internally references
`MI_<Material>_BaseColor.png` while the loose PNGs in the same zip are still
`T_<Name>_BC.png`, and the two names do NOT correspond one-to-one
(MI_ChangBang03B -> T_ChangBang09A_BC). Blender therefore imported 760 images it
could never resolve and every Gwollaegaksa building rendered magenta.

The authoritative mapping is the embedded blob itself, so pull the bytes straight
out of the FBX and write them under the name the FBX uses.

FBX binary layout: inside each Video node, `RelativeFilename` is an 'S' (string)
property and `Content` is an 'R' (raw bytes) property that follows it.

Run with system Python:  python cdg_unembed.py
"""
import os
import re
import struct
import sys

ROOT = r"C:\Work\blender\CDG_Changdeokgung"
FBX_DIR = os.path.join(ROOT, "_extracted", "FBX")
TEXLIB = os.path.join(ROOT, "_extracted", "_TexLib")

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def read_str_prop(buf, pos):
    """At pos expect property type 'S' then u32 length then the bytes."""
    if pos + 5 > len(buf) or buf[pos:pos + 1] != b"S":
        return None, pos
    n = struct.unpack("<I", buf[pos + 1:pos + 5])[0]
    if n > 4096:
        return None, pos
    s = buf[pos + 5:pos + 5 + n]
    return s, pos + 5 + n


def extract(path):
    with open(path, "rb") as f:
        buf = f.read()

    # collect (offset, name) for every RelativeFilename, and (offset, blob) for Content
    names = []
    for m in re.finditer(b"RelativeFilename", buf):
        s, _ = read_str_prop(buf, m.end())
        if s:
            base = s.replace(b"\\", b"/").split(b"/")[-1]
            try:
                names.append((m.start(), base.decode("utf-8", "replace")))
            except Exception:
                pass

    blobs = []
    for m in re.finditer(b"Content", buf):
        p = m.end()
        if p + 5 > len(buf) or buf[p:p + 1] != b"R":
            continue
        n = struct.unpack("<I", buf[p + 1:p + 5])[0]
        if n < 64 or p + 5 + n > len(buf):
            continue
        data = buf[p + 5:p + 5 + n]
        if data[:8] != PNG_MAGIC:
            continue
        blobs.append((m.start(), data))

    # pair each blob with the nearest RelativeFilename that precedes it
    out = {}
    ni = 0
    for off, data in blobs:
        while ni + 1 < len(names) and names[ni + 1][0] < off:
            ni += 1
        if not names:
            continue
        nm = names[min(ni, len(names) - 1)][1]
        if nm.lower().endswith(".png"):
            out[nm] = data
    return out


def main():
    os.makedirs(TEXLIB, exist_ok=True)
    existing = {f.lower() for f in os.listdir(TEXLIB)}
    fbx = sorted(f for f in os.listdir(FBX_DIR) if f.lower().endswith(".fbx"))
    total_new = 0
    total_bytes = 0
    for f in fbx:
        got = extract(os.path.join(FBX_DIR, f))
        new = 0
        for nm, data in got.items():
            if nm.lower() in existing:
                continue
            with open(os.path.join(TEXLIB, nm), "wb") as w:
                w.write(data)
            existing.add(nm.lower())
            new += 1
            total_bytes += len(data)
        total_new += new
        print("  {:<22} blobs {:>3}  new {:>3}".format(
            os.path.splitext(f)[0][:21], len(got), new))
    print("\nrecovered {} textures, {:.2f} GB".format(total_new, total_bytes / 1073741824))
    print("_TexLib now", len(os.listdir(TEXLIB)), "files")


main()
