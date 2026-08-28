# -*- coding: utf-8 -*-
"""Produce a viewing-safe copy of the master: swap every packed KHS texture for its
512px version on disk. The full-res master carries 1,286 packed images (~4 GB) and
switching the viewport to RENDERED crashed the NVIDIA driver outright
(EXCEPTION_ACCESS_VIOLATION in nvoglv64.dll). At 512 the image set is ~0.10 GB."""
import os, bpy
ROOT = r"C:\Work\blender\CDG_Changdeokgung"
MASTER = os.path.join(ROOT, "20_ARCHITECTURE", "CDG_Master.blend")
VIEW   = os.path.join(ROOT, "20_ARCHITECTURE", "CDG_Master_view.blend")
LIB512 = os.path.join(ROOT, "_extracted", "_TexLib512")

bpy.ops.wm.open_mainfile(filepath=MASTER)
low = {f.lower(): f for f in os.listdir(LIB512)}
ok = miss = err = 0
for img in list(bpy.data.images):
    if img.name in ("Render Result", "Viewer Node"):
        continue
    base = os.path.basename(img.filepath_from_user() or img.name)
    if not base.lower().endswith((".png", ".jpg", ".tga")):
        base += ".png"
    hit = low.get(base.lower())
    if not hit:
        miss += 1
        continue
    try:
        if img.packed_file:
            img.unpack(method='REMOVE')          # drop the 2K/4K packed copy
        img.filepath = os.path.join(LIB512, hit)
        img.source = 'FILE'
        img.reload()
        ok += 1
    except Exception as e:
        err += 1
print("images repointed to 512: %d, unmatched: %d, errors: %d" % (ok, miss, err))
print("still packed:", sum(1 for i in bpy.data.images if i.packed_file))
bpy.ops.wm.save_as_mainfile(filepath=VIEW)
print("saved", VIEW, os.path.getsize(VIEW)//1048576, "MB")
