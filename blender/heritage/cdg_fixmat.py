# -*- coding: utf-8 -*-
"""
Rebuild every building material as a plain textured Principled, using the
material->texture map and the 512px library.

Fixes three things at once:
  1. The Gwollaegaksa assets referenced an unshipped authoring library and rendered
     magenta. cdg_matmap.json restores the link from the material name.
  2. CDG_Master.blend had grown to 8.83 GB because every 2K/4K source texture was
     packed into it. Pointing at _TexLib512 files instead drops that to a few hundred MB.
  3. Trap B - FBX exports only an image wired DIRECTLY to Principled Base Color, so
     every material is rebuilt as TEX_IMAGE -> Base Color -> Output with nothing between.

blender.exe --background --factory-startup --python cdg_fixmat.py
"""
import json
import os

import bpy

ROOT = r"C:\Work\blender\CDG_Changdeokgung"
MASTER = os.path.join(ROOT, "20_ARCHITECTURE", "CDG_Master.blend")
LIB512 = os.path.join(ROOT, "_extracted", "_TexLib512")
MAP = os.path.join(ROOT, "_scripts", "cdg_matmap.json")

SKIP_PREFIX = ("MAT_CDG_", "MAT_GUIDE_")   # ground kit + QA guides already correct


def main():
    bpy.ops.wm.open_mainfile(filepath=MASTER)
    mapping = json.load(open(MAP, encoding="utf-8"))
    have = {f.lower(): f for f in os.listdir(LIB512)}

    cache = {}

    def img_for(texname):
        key = texname.lower()
        if key in cache:
            return cache[key]
        hit = have.get(key)
        if not hit:
            cache[key] = None
            return None
        im = bpy.data.images.load(os.path.join(LIB512, hit), check_existing=True)
        cache[key] = im
        return im

    done = skipped = unmapped = 0
    for m in list(bpy.data.materials):
        if m.name.startswith(SKIP_PREFIX):
            skipped += 1
            continue
        base = m.name.split(".")[0] if m.name.split(".")[-1].isdigit() else m.name
        tex = mapping.get(m.name) or mapping.get(base)
        if not tex:
            unmapped += 1
            continue
        im = img_for(tex)
        if im is None:
            unmapped += 1
            continue
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        out.location = (400, 0)
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (120, 0)
        bsdf.inputs["Roughness"].default_value = 0.82
        t = nt.nodes.new("ShaderNodeTexImage")
        t.location = (-220, 0)
        t.image = im
        nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
        done += 1

    # drop every image datablock nothing points at any more (this is the 8.8 GB)
    removed = 0
    for im in list(bpy.data.images):
        if im.name in ("Render Result", "Viewer Node"):
            continue
        if im.users == 0:
            bpy.data.images.remove(im)
            removed += 1

    bad = [i.name for i in bpy.data.images
           if i.name not in ("Render Result", "Viewer Node") and not i.has_data]
    print("materials rebuilt %d, skipped %d, unmapped %d" % (done, skipped, unmapped))
    print("orphan images removed %d, remaining %d, still without data %d"
          % (removed, len(bpy.data.images), len(bad)))
    if bad[:5]:
        print("   e.g.", bad[:5])
    bpy.ops.wm.save_as_mainfile(filepath=MASTER, compress=True)
    print("saved %s  %.2f GB" % (MASTER, os.path.getsize(MASTER) / 1073741824))


main()
