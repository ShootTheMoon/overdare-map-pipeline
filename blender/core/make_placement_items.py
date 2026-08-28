"""Turn placements.csv into overdare_create_instances itemsFile chunks.

The delivery arrives in two shapes and they are placed differently:

  STATIC    files were baked in WORLD coordinates. A MeshPart still centres its mesh inside
            its Size box, so the CFrame must be the bbox CENTRE - not (0,0,0), which is the
            mistake that scattered the first attempt across the origin.
  INSTANCED masters were recentred on their own pivot and are cloned from placements.csv.
            There the CSV Y is the BASE of the asset, while CFrame is its CENTRE, so every
            row needs + height/2.

Both need Size written explicitly: omitted, it stores 0 and the part does not render.

    python make_placement_items.py [out_dir] [--core] [--chunk 200]

Writes items_NNN.json, each an array for one overdare_create_instances(itemsFile=...) call,
plus _placement_plan.json listing them. Masters with no MODEL asset yet are skipped and
reported - the file is safe to re-run as more imports land.
"""
import csv
import io
import json
import math
import os
import sys

MT = r"C:\Work\MeshTest"
DELIVERY = os.path.join(MT, "Shibuya_OVERDARE_v17")     # placement CSVs and master pivots
# Bounds come from the PREPARED tree, not the delivery manifest, because the prepared files
# now carry UCX collider hulls and the delivery manifest predates them. `_prepared.json`
# records both boxes: `render_bbox_*` (geometry only) and `bbox_*` (geometry + hulls).
PREPARED = os.path.join(MT, "_PREPARED_V18")
PROJECT = os.environ.get("OVERDARE_PROJECT", r"C:\Work\SHIBUYA")
TABLE = os.path.join(PROJECT, "UGCLocalAssetTable.json")
# Which of the two boxes Studio derives the STATIC_MESH bounds from is a Phase 0 question -
# the smoke session settles it by reading Size/UnitExtent back off ROADS_02. "full" is the
# default because Unreal's FBX importer computes bounds over every mesh in the file.
SIZE_FROM = os.environ.get("OVERDARE_SIZE_FROM", "full")   # "full" | "render"

argv = [a for a in sys.argv[1:] if not a.startswith("--")]
OUT = argv[0] if argv else os.path.join(MT, "_PLACEMENT")
CORE = "--core" in sys.argv
CHUNK = 200
for i, a in enumerate(sys.argv):
    if a == "--chunk" and i + 1 < len(sys.argv):
        CHUNK = int(sys.argv[i + 1])


def model_ids():
    """prepared stem -> {mesh, textures} for every completely imported file.

    NOT the MODEL id. A MeshPart needs the STATIC_MESH; pointing MeshId at the MODEL is what
    made the first placement pass invisible while reporting total success - see
    asset_resolve.py for how that was diagnosed.
    """
    sys.path.insert(0, MT)
    from asset_resolve import resolve
    return resolve(TABLE)


def prepared_bounds():
    """output stem -> (min, max) in Blender metres, per SIZE_FROM.

    A MeshPart stretches its whole STATIC_MESH to fill `Size`, so `Size` has to be the bounds
    the engine gave that mesh. If the importer folds the UCX hulls into those bounds and Size
    is computed from the render box alone, every static file is scaled up slightly and sits
    off-centre - visible as a Size/UnitExtent ratio that is no longer 2.000.
    """
    key = "bbox" if SIZE_FROM == "full" else "render_bbox"
    out = {}
    for r in json.load(io.open(os.path.join(PREPARED, "_prepared.json"), encoding="utf-8")):
        lo, hi = r.get(key + "_min"), r.get(key + "_max")
        if lo and hi:
            out[r["output"].replace(".fbx", "")] = (lo, hi)
    return out


def main():
    ids = model_ids()
    bounds = prepared_bounds()
    masters = {m["master"]: m for m in
               json.load(io.open(os.path.join(DELIVERY, "_manifest_masters.json"),
                                 encoding="utf-8"))}
    statics = json.load(io.open(os.path.join(DELIVERY, "_manifest_static.json"),
                                encoding="utf-8"))

    items, skipped = [], {}

    # ---- static: one instance per delivered file, at its own bbox centre ----------------
    for s in statics:
        stem = s["file"].replace(".fbx", "") + "_overdare"
        a = ids.get(stem)
        if not a:
            skipped[stem] = "not fully imported (no MODEL + STATIC_MESH pair)"
            continue
        lo, hi = bounds.get(stem, (s.get("bbox_min"), s.get("bbox_max")))
        if not lo or not hi:
            skipped[stem] = "no bbox in _prepared.json or the delivery manifest"
            continue
        # Blender metres Z-up -> OVERDARE cm Y-up
        cx = (lo[0] + hi[0]) / 2 * 100.0
        cy = (lo[2] + hi[2]) / 2 * 100.0
        cz = (lo[1] + hi[1]) / 2 * 100.0
        # Size IS written, and the manifest bbox is the right source for it. The ratio to
        # UnitExtent reads 2.000 on every correctly-assigned part, which is not stretching -
        # UnitExtent is a HALF-extent, Unreal's usual convention. (Measured the other way
        # first, against parts still holding a stale inherited UnitExtent, and misread it as
        # a 2x stretch.) That ratio is also the cheapest check that a part has a real mesh:
        # anything not 2.000 is still pointing at something that has no geometry.
        size = [(hi[0] - lo[0]) * 100.0, (hi[2] - lo[2]) * 100.0, (hi[1] - lo[1]) * 100.0]
        props = {"meshId": "ovdrassetid://%d" % a["mesh"],
                 "position": [round(v, 1) for v in (cx, cy, cz)],
                 "size": [round(max(v, 1.0), 1) for v in size],
                 "anchored": True, "mobility": "Static"}
        if a["textures"]:
            props["raw"] = {"TextureId": "ovdrassetid://%d" % a["textures"][0]}
        items.append({"className": "MeshPart",
                      "name": stem.replace("_overdare", ""), "props": props})

    # ---- instanced: one per placements.csv row -----------------------------------------
    csv_name = "placements_core120m.csv" if CORE else "placements.csv"
    with io.open(os.path.join(DELIVERY, csv_name), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    counts = {}
    for r in rows:
        m = r["master"]
        man = masters.get(m)
        a = ids.get(m + "_overdare")
        if not man:
            skipped[m] = "not in the masters manifest"
            continue
        if not a:
            skipped[m + "_overdare"] = "not fully imported (no MODEL + STATIC_MESH pair)"
            continue
        lo, hi = bounds.get(m + "_overdare", (man["bbox_min"], man["bbox_max"]))
        size = [(hi[0] - lo[0]) * 100.0, (hi[2] - lo[2]) * 100.0, (hi[1] - lo[1]) * 100.0]
        counts[m] = counts.get(m, 0) + 1
        # The offset is to the mesh's bbox CENTRE, not half its height. Those are only the
        # same when the master's pivot sits exactly at its base, which is true of the paving
        # tiles - and false for every signboard stack (bbox z 0.35..3.07) and shopfront
        # (0.10..2.80). Using height/2 put 2,954 of 9,995 placements 1.7 m out of position,
        # and the smoke test could not see it because it used a tile whose pivot IS its base.
        y = float(r["Y"]) + (lo[2] + hi[2]) / 2.0 * 100.0
        props = {"meshId": "ovdrassetid://%d" % a["mesh"],
                 "position": [round(float(r["X"]), 1), round(y, 1), round(float(r["Z"]), 1)],
                 "orientation": [0.0, round(float(r["yaw_deg"]), 2), 0.0],
                 "size": [round(max(v, 1.0), 1) for v in size],
                 "anchored": True, "mobility": "Static"}
        if a["textures"]:
            props["raw"] = {"TextureId": "ovdrassetid://%d" % a["textures"][0]}
        items.append({"className": "MeshPart",
                      "name": "%s_%04d" % (m, counts[m]), "props": props})

    os.makedirs(OUT, exist_ok=True)
    for n in os.listdir(OUT):
        if n.startswith("items_") or n == "_placement_plan.json":
            os.remove(os.path.join(OUT, n))
    # The 39 static files carry the whole map's ground, buildings and roads and are placed by
    # a DIFFERENT rule than the clones (bbox centre vs base+height/2). Emit them as their own
    # chunk so they can go in first and be checked: if the rule is wrong, that is 39 instances
    # to undo instead of ten thousand.
    stat = [it for it in items if "orientation" not in it["props"]]
    rest = [it for it in items if "orientation" in it["props"]]
    plan = []
    if stat:
        p = os.path.join(OUT, "items_000_static.json")
        json.dump(stat, io.open(p, "w", encoding="utf-8"), indent=1)
        plan.append({"file": p, "count": len(stat), "kind": "static"})
    for i in range(0, len(rest), CHUNK):
        p = os.path.join(OUT, "items_%03d.json" % (i // CHUNK + 1))
        json.dump(rest[i:i + CHUNK], io.open(p, "w", encoding="utf-8"), indent=1)
        plan.append({"file": p, "count": len(rest[i:i + CHUNK]), "kind": "instanced"})
    json.dump(plan, io.open(os.path.join(OUT, "_placement_plan.json"), "w", encoding="utf-8"),
              indent=1)

    print("=== %s  (%s)" % (OUT, csv_name))
    print("  project : %s" % PROJECT)
    print("  bounds  : %s bbox from %s" % (SIZE_FROM, os.path.basename(PREPARED)))
    print("  instances to create : %d  -> %d chunk file(s) of <=%d" % (len(items), len(plan), CHUNK))
    print("  static (world-baked): %d" % sum(1 for it in items if "orientation" not in it["props"]))
    print("  cloned from the CSV : %d" % sum(1 for it in items if "orientation" in it["props"]))
    if skipped:
        print("\n  skipped (%d distinct):" % len(skipped))
        for k, v in sorted(skipped.items()):
            print("     %-42s %s" % (k, v))
    print("\nPLACEMENT ITEMS DONE")


if __name__ == "__main__":
    main()
