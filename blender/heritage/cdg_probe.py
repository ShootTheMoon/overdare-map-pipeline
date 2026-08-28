# -*- coding: utf-8 -*-
"""
CDG - stage 2 probe: import one KHS FBX headless and report the ground truth
that every later stage depends on.

Answers:
  * Does Blender's importer survive, how long, how much RAM
  * Real triangle count (my zip-header parse assumed corners/3)
  * Material list with per-material triangle counts  -> feeds the decimation policy
  * World bbox measured from ACTUAL VERTICES (bound_box is stale on
    quaternion-rotated imports - Trap A)
  * Ground Z, so layout can put every building's base on Z=0
  * UV layers present, and whether Base Color is a direct TEX_IMAGE (Trap B)

Usage:
  blender.exe --background --factory-startup --python cdg_probe.py -- <Key> [<Key> ...]
"""
import json
import os
import sys
import time

import bpy

ROOT = r"C:\Work\blender\CDG_Changdeokgung"
FBX_DIR = os.path.join(ROOT, "_extracted", "FBX")
OUT = os.path.join(ROOT, "_extracted", "PROBE.json")


def argv_after_dashes():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def wipe():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def rss_gb():
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1073741824
    except Exception:
        return -1.0


def probe(key):
    path = os.path.join(FBX_DIR, key + ".fbx")
    if not os.path.exists(path):
        return {"key": key, "error": "missing " + path}

    wipe()
    t0 = time.time()
    bpy.ops.import_scene.fbx(
        filepath=path,
        use_image_search=False,   # do NOT let Blender hunt 2K/4K PNGs
        use_anim=False,
        use_custom_normals=False,
    )
    t_import = time.time() - t0
    peak = rss_gb()

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    rec = {
        "key": key,
        "fbx_mb": round(os.path.getsize(path) / 1048576, 1),
        "import_sec": round(t_import, 1),
        "rss_gb_after_import": round(peak, 2),
        "object_count": len(bpy.data.objects),
        "mesh_object_count": len(meshes),
        "objects": [],
    }

    tot_tris = tot_verts = 0
    lo = [1e18] * 3
    hi = [-1e18] * 3
    mat_tris = {}

    dg = bpy.context.evaluated_depsgraph_get()
    for o in meshes:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        me.calc_loop_triangles()
        n_tris = len(me.loop_triangles)
        tot_tris += n_tris
        tot_verts += len(me.vertices)

        mw = o.matrix_world
        for v in me.vertices:                       # Trap A: real verts, not bound_box
            w = mw @ v.co
            for i in range(3):
                if w[i] < lo[i]:
                    lo[i] = w[i]
                if w[i] > hi[i]:
                    hi[i] = w[i]

        slots = [ms.material.name if ms.material else "__none"
                 for ms in o.material_slots] or ["__none"]
        for lt in me.loop_triangles:
            nm = slots[lt.material_index] if lt.material_index < len(slots) else "__none"
            mat_tris[nm] = mat_tris.get(nm, 0) + 1

        rec["objects"].append({
            "name": o.name,
            "tris": n_tris,
            "verts": len(me.vertices),
            "uv_layers": [l.name for l in me.uv_layers],
            "material_slots": len(o.material_slots),
            "rot_mode": o.rotation_mode,
            "scale": [round(s, 6) for s in o.scale],
        })
        ev.to_mesh_clear()

    rec["total_tris"] = tot_tris
    rec["total_verts"] = tot_verts
    rec["bbox_min"] = [round(v, 4) for v in lo]
    rec["bbox_max"] = [round(v, 4) for v in hi]
    rec["dims"] = [round(hi[i] - lo[i], 4) for i in range(3)]
    rec["ground_z"] = round(lo[2], 4)
    rec["materials"] = sorted(
        ({"name": k, "tris": v, "pct": round(100.0 * v / max(tot_tris, 1), 2)}
         for k, v in mat_tris.items()),
        key=lambda d: -d["tris"])

    # Trap B: FBX exports only an image wired DIRECTLY to Principled Base Color.
    direct = indirect = nonode = 0
    for m in bpy.data.materials:
        if not m.use_nodes:
            nonode += 1
            continue
        bsdf = next((n for n in m.node_tree.nodes
                     if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            nonode += 1
            continue
        inp = bsdf.inputs.get("Base Color")
        if inp and inp.is_linked:
            if inp.links[0].from_node.type == "TEX_IMAGE":
                direct += 1
            else:
                indirect += 1
    rec["basecolor_direct_teximage"] = direct
    rec["basecolor_via_chain"] = indirect
    rec["materials_without_principled"] = nonode
    rec["image_count"] = len(bpy.data.images)
    return rec


def main():
    keys = argv_after_dashes()
    results = {}
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            results = json.load(f)
    for k in keys:
        print("\n=== probing", k, "===")
        r = probe(k)
        results[k] = r
        if "error" in r:
            print("  ERROR:", r["error"])
            continue
        print("  import {}s  rss {} GB  objects {}".format(
            r["import_sec"], r["rss_gb_after_import"], r["mesh_object_count"]))
        print("  tris {:,}  verts {:,}  materials {}".format(
            r["total_tris"], r["total_verts"], len(r["materials"])))
        print("  dims  {} m   ground_z {}".format(r["dims"], r["ground_z"]))
        print("  basecolor: {} direct / {} via-chain / {} no-principled".format(
            r["basecolor_direct_teximage"], r["basecolor_via_chain"],
            r["materials_without_principled"]))
        print("  top materials:")
        for m in r["materials"][:8]:
            print("    {:<28} {:>9,} ({:>5.2f}%)".format(
                m["name"][:27], m["tris"], m["pct"]))
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=1)
    print("\nwrote", OUT)


main()
