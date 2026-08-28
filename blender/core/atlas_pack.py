"""Pack each export file's textures into ONE sheet so it imports as ONE material.

The blocker this removes: OVERDARE counts import units per MATERIAL, and Studio's importer
leaks a transient world per published asset until unique-name generation fails
(LevelActor.cpp:583). A session survived 46 units and died by ~153. The delivery carries
1,301 units, so 29-44 Studio restarts.

    02_BUILDINGS          958 units   73.6%
    10_INSTANCE_MASTERS   208         16.0%
    01_TERRAIN             68          5.2%
    everything else        67          5.2%

Atlasing repacks pixels; it does not add any. The delivered images are already capped by
prep_image, so the sum of a file's delivered image areas is what the sheet must hold - and
the worst file needs 11,337,728 px, which is 3367 x 3367. A 4096 sheet holds 16,777,216, so
this costs NOTHING in sharpness. (8192 would have been 268 MB decompressed per sheet against
4096's 67 MB - three building files would have exceeded the 699 MB that already crashed the
importer.)

WHAT IS NOT ATLASED, AND WHY
Packing rescales each material's UVs into its sub-rect of the sheet. That is only valid when
the UVs live inside 0..1. Anything box-projected tiles far outside it and would sample its
neighbours in the sheet, so the 36 tiling materials stay exactly as they are:

    M_FAC_A..D, M_OUT_A..D   facade / outskirts, 12 m box projection
    M_ST_*, M_VD_*, M_SH_*   infrastructure, 3-8 m box projection
    M_ZK_Frame, M_ZK_Concrete, M_BLDG_PARAPET, M_SHIBUYA_KERB
    a handful of imported-asset materials on vehicles and trees

    528 materials atlasable  ->  one per file
     44 material slots tiling ->  36 distinct, shared, left alone

This is pure arithmetic on UVs and a PIL blit - no bpy.ops.object.bake, which this build
cannot run, and no img.scale() on a packed image, which crashed the pipeline twice.

    blender --background <scene.blend> --python atlas_pack.py -- <out_dir> [sheet_px]
"""
import bpy
import os
import sys
import json
import math

MT = r"C:\Work\MeshTest"
if MT not in sys.path:
    sys.path.insert(0, MT)
from texture_caps import cap_for                      # noqa: E402  shared with make_texwork

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = argv[0] if argv else os.path.join(MT, "_ATLAS")
SHEET = int(argv[1]) if len(argv) > 1 else 4096
PAD = 4                       # texels of gutter, so bilinear taps never cross a neighbour
DETAIL = "FacadeDetail"


def delivered_size(im):
    """the size prep_image will ship, which is what has to fit in the sheet"""
    c = cap_for(im.name)
    w, h = im.size
    if not w or not h:
        return (0, 0)
    k = min(1.0, c / float(max(w, h)))
    return (max(1, int(w * k)), max(1, int(h * k)))


def photo_of(mat):
    """the material's colour image - never the detail overlay"""
    if not mat or not mat.use_nodes:
        return None
    best = None
    for n in mat.node_tree.nodes:
        if n.type == 'TEX_IMAGE' and n.image and DETAIL not in n.image.name:
            if best is None or max(n.image.size) > max(best.size):
                best = n.image
    return best


def uv_range(objs, mat_name):
    lo, hi = 1e9, -1e9
    for o in objs:
        me = o.data
        if not me.uv_layers:
            continue
        uvl = me.uv_layers[0].data
        names = [m.name if m else "" for m in me.materials]
        for p in me.polygons:
            if p.material_index >= len(names) or names[p.material_index] != mat_name:
                continue
            for li in p.loop_indices:
                u, v = uvl[li].uv
                lo = min(lo, u, v)
                hi = max(hi, u, v)
    return lo, hi


def shelf_pack(items, sheet, pad):
    """classic shelf packing, tallest first. items = [(key, w, h)] -> {key: (x, y, w, h)}"""
    items = sorted(items, key=lambda it: -it[2])
    place = {}
    x = y = row_h = 0
    for key, w, h in items:
        w2, h2 = w + pad * 2, h + pad * 2
        if w2 > sheet or h2 > sheet:
            return None
        if x + w2 > sheet:
            x = 0
            y += row_h
            row_h = 0
        if y + h2 > sheet:
            return None
        place[key] = (x + pad, y + pad, w, h)
        x += w2
        row_h = max(row_h, h2)
    return place


def plan():
    """-> [{folder, index, objects, atlasable {mat: image}, tiling [mat]}]"""
    G = {"bpy": bpy, "__name__": "sx2"}
    exec(compile(open(os.path.join(MT, "shibuya_export_v2.py"), encoding="utf-8").read(),
                 "sx2", "exec"), G)
    FOLD = dict(G["STATIC_FOLDER"])
    groups = []
    for cn, fold in FOLD.items():
        c = bpy.data.collections.get(cn)
        if not c:
            continue
        objs = [o for o in c.objects
                if o.type == 'MESH' and o.data.polygons and not o.hide_render]
        if not objs:
            continue
        for gi, grp in enumerate(G["pack_files"](objs), 1):
            groups.append((fold, gi, grp))

    # ---- classify GLOBALLY, per material, not per folder ----------------------------
    # A material tiling anywhere is tiling everywhere: M_BLDG_PARAPET measured outside 0..1
    # on the buildings and inside it on the landmarks, so a per-folder verdict atlased the
    # landmark copies and remapped box-projected UVs as if they were 0..1 - 511 objects
    # landed outside the sheet. The union is the only safe reading.
    rng = {}
    for fold, gi, grp in groups:
        names = set()
        for o in grp:
            for m in o.data.materials:
                if m:
                    names.add(m.name)
        for mn in names:
            lo, hi = uv_range(grp, mn)
            if lo > hi:
                continue
            p = rng.get(mn)
            rng[mn] = (min(p[0], lo), max(p[1], hi)) if p else (lo, hi)
    tiling_global = {mn for mn, (lo, hi) in rng.items() if lo < -0.05 or hi > 1.05}
    print("  global classification: %d materials measured, %d tiling everywhere"
          % (len(rng), len(tiling_global)))

    out = []
    for fold, gi, grp in groups:
        seen, atl, tile = set(), {}, []
        for o in grp:
            for m in o.data.materials:
                if not m or m.name in seen:
                    continue
                seen.add(m.name)
                if m.name in tiling_global:
                    tile.append(m.name)
                    continue
                im = photo_of(m)
                if im is None:
                    continue
                atl[m.name] = im
        out.append({"folder": fold, "index": gi, "objects": grp,
                    "atlasable": atl, "tiling": tile})
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    files = plan()
    print("=== atlas plan: %d export files, sheet %d px, pad %d" % (len(files), SHEET, PAD))
    recs = []
    for f in files:
        atl = f["atlasable"]
        if not atl:
            print("  %-14s %2d  no atlasable material - unchanged" % (f["folder"], f["index"]))
            continue
        items = []
        for mn, im in atl.items():
            w, h = delivered_size(im)
            if w and h:
                items.append((mn, w, h))
        place = shelf_pack(items, SHEET, PAD)
        used = sum(w * h for _, w, h in items)
        rec = {"folder": f["folder"], "index": f["index"],
               "objects": [o.name for o in f["objects"]],
               "n_atlas": len(items), "n_tiling": len(f["tiling"]),
               "tiling": sorted(set(f["tiling"])),
               "used_px": used, "fill": round(used / float(SHEET * SHEET), 3),
               "fits": place is not None,
               "rects": {k: list(v) for k, v in (place or {}).items()},
               "images": {mn: bpy.data.images[atl[mn].name].filepath for mn in atl},
               "sizes": {mn: list(delivered_size(atl[mn])) for mn in atl}}
        recs.append(rec)
        print("  %-14s %2d  %3d atlas + %2d tiling   fill %5.1f%%  %s"
              % (f["folder"], f["index"], len(items), rec["n_tiling"],
                 rec["fill"] * 100, "OK" if rec["fits"] else "DOES NOT FIT"))
    bad = [r for r in recs if not r["fits"]]
    p = os.path.join(OUT, "_atlas_plan.json")
    json.dump(recs, open(p, "w"), indent=1)
    units_before = sum(r["n_atlas"] + r["n_tiling"] for r in recs)
    units_after = sum(1 + r["n_tiling"] for r in recs)
    print("\n  files planned: %d | do not fit: %d" % (len(recs), len(bad)))
    print("  import units for these files: %d -> %d" % (units_before, units_after))
    print("  wrote %s" % p)
    print("ATLAS PLAN DONE")


if __name__ == "__main__":
    main()
