"""Run the OVERDARE import preparation over the whole delivery, in one Blender session.

Why this exists: the v14 FBX were handed straight to Studio's importer and it crashed twice.
The logs say why, and `overdare_mesh_prepare`'s own description says the same thing:

    "joins meshes, decimates to the per-mesh triangle budget, and downscales textures
     (OVERDARE recommends 512; large 4K textures OOM the importer)"

and `overdare_mesh_bulk_import` takes "prepared *_overdare.fbx files". We skipped that step.
Both crashes follow from it:

  1. texture OOM        - 158 distinct images re-embedded as 386 copies = 699 MB decompressed
  2. LevelActor.cpp:583 - "Cannot generate unique name for 'MetaBaseWorldSettings' in level
                          /Engine/Transient.Untitled". The importer publishes one world-asset
                          model per OBJECT in the file; FRN_04 published FRN_04, EXP_FRN_LAMP,
                          EXP_FRN_SUBENT in turn, and ZK_WaterTank_A published its name twice
                          before the name generator gave up. Joining to one object per file
                          removes the collision.

The Berlin pack imported 46 assets in one session without either failure - and its files were
named *_overdare.fbx, i.e. they had been through this step.

Doing it here rather than 94 separate MCP calls: the operation is join + downscale + export,
and the result is checked against the tool's own output for UP_UtilityPole_A
(parts 1, materials 4, textures 512, 1,836 tris) before anything is shipped.

    blender --background --factory-startup --python prepare_all.py -- <src> <dst> <texpx>
"""
import bpy
import os
import sys
import json

sys.path.insert(0, r"C:\Work\MeshTest")
from texture_caps import KEEP_FULL, FULLPX   # noqa: E402  same definition the exporter uses
from ucx_lib import BOX_FACES, box_corners, read_parts   # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
SRC = argv[0] if argv else r"C:\Work\MeshTest\Shibuya_OVERDARE_v14"
DST = argv[1] if len(argv) > 1 else r"C:\Work\MeshTest\_PREPARED"
TEXPX = int(argv[2]) if len(argv) > 2 else 512
MAX_TRIS = 30000
# The five standalone UCX_*.fbx are not importable - Studio rejected every one with "Failed
# to create asset". They are not deliverables either way; see EMBED_UCX.
SKIP_PREFIX = ("UCX_",)

# OFF, and it must stay off. Embedding the hulls as UCX_ meshes inside the render files was
# tried and it CRASHES Studio:
#
#     Fatal error: LevelActor.cpp:583
#     Cannot generate unique name for 'MetaBaseWorldSettings' in level
#     '/Engine/Transient.Untitled:PersistentLevel'
#
# which is the exact failure this file's header already describes. OVERDARE's importer does
# not implement Unreal's UCX convention; it publishes one world asset PER OBJECT, so 32 hulls
# are 32 more publishes, and the transient-world leak exhausts unique-name generation. That is
# the whole reason everything is joined into one object above - the colliders were made an
# exception to that rule and hit it immediately.
#
# It is also unaffordable even when it does not crash: a 1-material file goes from 3 published
# assets to 35, and the delivery from 456 to over 1,600 - 15 Studio sessions become ~47.
#
# Collision is built from engine Parts instead (make_collision_parts.py). Every hull is an
# axis-aligned box, a Part is a native primitive, and Parts cost no published assets at all.
EMBED_UCX = False


def clear():
    for d in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.images):
        for x in list(d):
            if getattr(x, "name", "") in ("Render Result", "Viewer Node"):
                continue
            try:
                d.remove(x, do_unlink=True)
            except Exception:
                pass


def tri(me):
    return sum(len(p.vertices) - 2 for p in me.polygons)


def bbox_of(objs):
    """world-space (min, max) in Blender metres Z-up, measured from actual vertices.

    From vertices and not `bound_box`, which is stale on freshly imported objects carrying a
    quaternion rotation - a trap this pipeline has hit in three separate passes.
    """
    lo = [1e18] * 3
    hi = [-1e18] * 3
    for o in objs:
        M = o.matrix_world
        for v in o.data.vertices:
            p = M @ v.co
            for i in range(3):
                lo[i] = min(lo[i], p[i])
                hi[i] = max(hi[i], p[i])
    return ([round(v, 4) for v in lo], [round(v, 4) for v in hi]) if hi[0] > -1e17 else (None, None)


def add_ucx(out_name, render_obj):
    """Build this file's collider hulls as separate UCX_<mesh>_NN meshes - DISABLED.

    Kept, and kept working, because the decision to disable it is empirical rather than
    structural: if a future Studio build implements the UCX convention, flipping EMBED_UCX is
    the whole change. Read that constant before turning it on.
    """
    if not EMBED_UCX:
        return "world", []
    space, hulls = read_parts(out_name)
    made = []
    for i, h in enumerate(hulls):
        me = bpy.data.meshes.new("UCX_%s_%02d" % (render_obj.data.name, i))
        me.from_pydata(box_corners(h["min"], h["max"]), [], BOX_FACES)
        me.update()
        ob = bpy.data.objects.new("UCX_%s_%02d" % (render_obj.name, i), me)
        bpy.context.scene.collection.objects.link(ob)
        made.append(ob)
    return space, made


def prepare(path, out_dir, texpx):
    clear()
    try:
        bpy.ops.wm.fbx_import(filepath=path)
    except AttributeError:
        bpy.ops.import_scene.fbx(filepath=path)
    objs = [o for o in bpy.data.objects if o.type == 'MESH' and o.data.polygons]
    if not objs:
        return None
    n_in = len(objs)
    tris_in = sum(tri(o.data) for o in objs)

    # ---- join every mesh into one object -------------------------------------------
    # This is the part that stops the importer publishing a world-asset model per object,
    # which is what exhausted unique-name generation in the transient level.
    for o in bpy.data.objects:
        o.select_set(o in objs)
    bpy.context.view_layer.objects.active = objs[0]
    if len(objs) > 1:
        bpy.ops.object.join()
    merged = bpy.context.view_layer.objects.active
    stem = os.path.splitext(os.path.basename(path))[0]
    merged.name = stem
    merged.data.name = stem

    # ---- textures down to the cap ---------------------------------------------------
    # PIL is not available in Blender and img.scale() on a lazily-loaded image is the call
    # that crashed this pipeline before, so resize only what is actually oversized and only
    # after forcing the pixel buffer to load.
    sized = []
    for im in list(bpy.data.images):
        if im.name in ("Render Result", "Viewer Node"):
            continue
        w, h = im.size
        if not w or not h:
            continue
        # An atlas sheet is exempt from the blanket cap. It is not one texture - it is 60-odd
        # textures already capped at their own delivered size and repacked, so applying the
        # per-texture cap to the SHEET applies it 60 times over: a 4096 sheet at 512 leaves
        # each packed rect 63 px instead of 506, one sixty-fourth of the pixels. v15 shipped
        # exactly that, through this line and through make_texwork, and every cap check still
        # said PASS because each check only ever looked at the sheet as a single image.
        cap = FULLPX if im.name.startswith(KEEP_FULL) else texpx
        if max(w, h) > cap:
            k = cap / float(max(w, h))
            try:
                im.pixels[0]                     # force the buffer in before scaling
                im.scale(max(1, int(w * k)), max(1, int(h * k)))
                # RE-PACK. im.scale() only touches the in-memory buffer; the FBX exporter
                # writes from the PACKED data, so without this the file still carries the
                # original 1024 and the whole downscale is silently a no-op - which is
                # exactly what the first run produced (terrain still 34 MB of texture).
                if im.packed_file:
                    im.pack()
            except Exception as ex:
                print("     !! could not scale %s: %s" % (im.name, ex))
        sized.append((im.name, tuple(im.size)))

    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, stem + "_overdare.fbx")
    space, ucx = add_ucx(os.path.basename(out), merged)
    rlo, rhi = bbox_of([merged])
    flo, fhi = bbox_of([merged] + ucx)
    keep = set([merged] + ucx)
    for o in bpy.data.objects:
        o.select_set(o in keep)
    bpy.context.view_layer.objects.active = merged
    bpy.ops.export_scene.fbx(filepath=out, use_selection=True, object_types={'MESH'},
                             embed_textures=True, path_mode='COPY', mesh_smooth_type='FACE',
                             use_mesh_modifiers=False, bake_space_transform=False,
                             axis_forward='-Z', axis_up='Y', global_scale=1.0)
    t_out = tri(merged.data)
    return {
        "file": os.path.basename(path), "output": os.path.basename(out),
        "objects_in": n_in, "parts_out": 1,
        "tris_in": tris_in, "tris_out": t_out,
        # Two boxes, because it is not yet known which one Studio derives the STATIC_MESH
        # bounds from once UCX hulls are present. `Size` on the placed MeshPart must match
        # whichever it is, or the mesh gets scaled to fit a box it does not fill - so record
        # both and let the Phase 0 probe decide. Blender metres, Z-up.
        "ucx_hulls": len(ucx), "ucx_space": space,
        "render_bbox_min": rlo, "render_bbox_max": rhi,
        "bbox_min": flo, "bbox_max": fhi,
        "materials": len([m for m in merged.data.materials if m]),
        "textures": len(sized), "max_tex": max([max(s[1]) for s in sized], default=0),
        "over_budget": t_out > MAX_TRIS,
        "size_mb": round(os.path.getsize(out) / 1048576.0, 2),
        # decompressed VRAM cost, which is what actually OOMs the importer - a 4096 sheet is
        # 67 MB even though the PNG on disk is 8. Batch sizing has to use this, not size_mb.
        "tex_vram_mb": round(sum(w * h * 4 for _, (w, h) in sized) / 1048576.0, 1),
    }


def main():
    files, skipped_src = [], []
    for dp, _, ns in os.walk(SRC):
        for n in sorted(ns):
            if not n.lower().endswith(".fbx"):
                continue
            (skipped_src if n.startswith(SKIP_PREFIX) else files).append(os.path.join(dp, n))
    print("=== preparing %d files -> %s  (textures <= %d px)" % (len(files), DST, TEXPX))
    if skipped_src:
        print("    skipping %d standalone collider file(s) - collision ships as engine Parts, "
              "not in the FBX (see EMBED_UCX)" % len(skipped_src))
    recs = []
    for i, p in enumerate(files, 1):
        rel = os.path.relpath(p, SRC)
        sub = os.path.join(DST, os.path.dirname(rel)) if os.path.dirname(rel) else DST
        r = prepare(p, sub, TEXPX)
        if r is None:
            print("  %3d/%d  %-34s SKIPPED (no mesh)" % (i, len(files), rel))
            continue
        r["folder"] = os.path.dirname(rel)
        recs.append(r)
        print("  %3d/%d  %-30s objs %4d -> 1   tris %7s   mats %3d  tex %2d@%4d  "
              "ucx %3d  %5.2f MB%s"
              % (i, len(files), r["file"], r["objects_in"], format(r["tris_out"], ','),
                 r["materials"], r["textures"], r["max_tex"], r["ucx_hulls"], r["size_mb"],
                 "   !! OVER 30k" if r["over_budget"] else ""), flush=True)
    os.makedirs(DST, exist_ok=True)
    json.dump(recs, open(os.path.join(DST, "_prepared.json"), "w"), indent=1)
    over = [r for r in recs if r["over_budget"]]
    print("\nprepared %d files | over 30,000 tris: %d | total %.1f MB"
          % (len(recs), len(over), sum(r["size_mb"] for r in recs)))
    nh = sum(r["ucx_hulls"] for r in recs)
    cap = [r for r in recs if r["ucx_hulls"] > 32]
    print("  collider hulls embedded: %d across %d file(s) | over the 32-per-mesh cap: %d"
          % (nh, sum(1 for r in recs if r["ucx_hulls"]), len(cap)))
    for r in cap:
        print("   OVER CAP: %s  %d hulls" % (r["output"], r["ucx_hulls"]))
    vr = sorted(recs, key=lambda r: -r["tex_vram_mb"])
    print("  decompressed texture load: %.0f MB total | heaviest file %.0f MB"
          % (sum(r["tex_vram_mb"] for r in recs), vr[0]["tex_vram_mb"] if vr else 0))
    for r in vr[:4]:
        print("      %-34s %6.0f MB" % (r["output"], r["tex_vram_mb"]))
    for r in over:
        print("   OVER: %s  %s tris" % (r["file"], format(r["tris_out"], ',')))
    print("PREPARE DONE")


if __name__ == "__main__":
    main()
