"""Collision for the Shibuya map as engine Parts, because embedded colliders are impossible.

WHY NOT UCX
    Two ways were tried and both are dead:

      standalone UCX_*.fbx      "Failed to create asset" - UCX_ names a hull for the render
                                mesh IN THE SAME FILE, so a file with no render mesh has
                                nothing to attach to.
      UCX_ meshes inside the    Fatal error, LevelActor.cpp:583, "Cannot generate unique name
      render file               for 'MetaBaseWorldSettings' in /Engine/Transient.Untitled".

    The second one is the informative failure. OVERDARE's importer publishes one world asset
    PER OBJECT in a file and leaks a transient world for each, so 32 hulls are 32 extra
    publishes and the name generator gives out. That is exactly why `prepare_all.py` joins
    every file to a single object - the colliders were made an exception to that rule and hit
    the crash the rule exists to prevent. The importer does not implement the UCX convention
    at all.

WHY PARTS ARE ACTUALLY THE BETTER FIT HERE
    Every hull in this map is an axis-aligned box (buildings and landmarks are per-object
    AABBs, the terrain is an adaptive quadtree of flat-topped boxes), and a Part IS a box.
    So the mapping is 1:1 with no approximation, and Parts cost ZERO published assets - the
    whole 456-unit / 15-session import budget is untouched. They are also editable in Studio
    afterwards, which a baked hull is not.

    Transparency 1 rather than a hidden flag: an invisible-but-colliding Part is the standard
    shape for this, and it stays selectable in the editor.

OUTPUT
    items_col_NNN.json chunks for overdare_create_instances(itemsFile=...), same shape as
    make_placement_items.py writes, so the same MCP path places both.

    python make_collision_parts.py [out_dir] [--core] [--chunk 200]
"""
import csv
import io
import json
import math
import os
import sys

sys.path.insert(0, r"C:\Work\MeshTest")
from ucx_lib import PARTS_DIR      # noqa: E402

MT = r"C:\Work\MeshTest"
DELIVERY = os.path.join(MT, "Shibuya_OVERDARE_v17")

argv = [a for a in sys.argv[1:] if not a.startswith("--")]
OUT = argv[0] if argv else os.path.join(MT, "_COLLISION_PARTS")
CORE = "--core" in sys.argv
CHUNK = 200
for i, a in enumerate(sys.argv):
    if a == "--chunk" and i + 1 < len(sys.argv):
        CHUNK = int(sys.argv[i + 1])

# Minimum thickness in metres. A Part with a zero axis does not collide, and a few hulls are
# near-flat (paving, the Q-FRONT screen was already excluded upstream).
MIN_EDGE = 0.05


def part(name, mn, mx, yaw_deg=0.0):
    """Blender metres Z-up -> an OVERDARE Part in centimetres Y-up.

    Same axis mapping make_placement_items.py uses: X=x*100, Y=z*100, Z=y*100. CFrame is the
    part CENTRE, which for a box is just the midpoint of its bounds.
    """
    size = [max(mx[i] - mn[i], MIN_EDGE) for i in range(3)]
    ctr = [(mx[i] + mn[i]) / 2.0 for i in range(3)]
    props = {"position": [round(ctr[0] * 100, 1), round(ctr[2] * 100, 1),
                          round(ctr[1] * 100, 1)],
             "size": [round(size[0] * 100, 1), round(size[2] * 100, 1),
                      round(size[1] * 100, 1)],
             "anchored": True, "mobility": "Static",
             "raw": {"Transparency": 1.0, "CanCollide": True, "CastShadow": False,
                     "CanTouch": False}}
    if yaw_deg:
        props["orientation"] = [0.0, round(yaw_deg, 2), 0.0]
    return {"className": "Part", "name": name, "props": props}


def static_hulls():
    """Every world-space hull the sidecars hold, regardless of which file was to carry it.

    The file assignment was only ever a way to fit the 32-per-mesh collider cap. Parts have no
    such cap, so it is dropped here - and with it the compromise it forced. Worth noting for
    whoever re-tunes the terrain: `ucx_lib.TERRAIN_BANDS` loosened the outer bands purely to
    fit that budget, and nothing needs it to now.
    """
    out = []
    for n in sorted(os.listdir(PARTS_DIR)):
        if not n.endswith(".json") or n.startswith("_"):
            continue
        d = json.load(io.open(os.path.join(PARTS_DIR, n), encoding="utf-8"))
        if d.get("space") != "world":
            continue
        for h in d["hulls"]:
            out.append((h["name"], h["min"], h["max"]))
    return out


def master_hulls():
    """-> {master: (min, max)} in the master's own local frame."""
    out = {}
    for n in sorted(os.listdir(PARTS_DIR)):
        if not n.endswith(".json") or n.startswith("_"):
            continue
        d = json.load(io.open(os.path.join(PARTS_DIR, n), encoding="utf-8"))
        if d.get("space") != "local":
            continue
        m = d["file"].replace("_overdare.fbx", "")
        out[m] = (d["hulls"][0]["min"], d["hulls"][0]["max"])
    return out


def main():
    statics = static_hulls()
    masters = master_hulls()
    items = [part("COL_%s" % n, mn, mx) for n, mn, mx in statics]
    n_static = len(items)

    # ---- one Part per placement of a master that collides -------------------------------
    # The CSV row is the instance BASE in engine cm; the hull is in the master's local frame,
    # so the Part sits at base + the hull's own local centre. Rotating the box by the row's
    # yaw keeps a 4.7 m taxi from inflating >40% the way a world AABB would.
    csv_name = "placements_core120m.csv" if CORE else "placements.csv"
    counts = {}
    with io.open(os.path.join(DELIVERY, csv_name), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            m = r["master"]
            h = masters.get(m)
            if not h:
                continue
            lo, hi = h
            counts[m] = counts.get(m, 0) + 1
            yaw = float(r["yaw_deg"])
            # Local centre offset, rotated into world by the instance yaw. Z (Blender) is the
            # vertical and is not affected by a yaw about the vertical axis.
            cx, cy = (lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0
            a = math.radians(-yaw)
            rx = cx * math.cos(a) - cy * math.sin(a)
            ry = cx * math.sin(a) + cy * math.cos(a)
            sx, sy = hi[0] - lo[0], hi[1] - lo[1]
            sz = hi[2] - lo[2]
            zc = (lo[2] + hi[2]) / 2.0
            props = {
                "position": [round(float(r["X"]) + rx * 100, 1),
                             round(float(r["Y"]) + zc * 100, 1),
                             round(float(r["Z"]) + ry * 100, 1)],
                "size": [round(max(sx, MIN_EDGE) * 100, 1),
                         round(max(sz, MIN_EDGE) * 100, 1),
                         round(max(sy, MIN_EDGE) * 100, 1)],
                "orientation": [0.0, round(yaw, 2), 0.0],
                "anchored": True, "mobility": "Static",
                "raw": {"Transparency": 1.0, "CanCollide": True, "CastShadow": False,
                        "CanTouch": False}}
            items.append({"className": "Part",
                          "name": "COL_%s_%04d" % (m, counts[m]), "props": props})

    os.makedirs(OUT, exist_ok=True)
    for n in os.listdir(OUT):
        if n.startswith("items_col_") or n == "_collision_plan.json":
            os.remove(os.path.join(OUT, n))
    plan = []
    for i in range(0, len(items), CHUNK):
        p = os.path.join(OUT, "items_col_%03d.json" % (i // CHUNK + 1))
        json.dump(items[i:i + CHUNK], io.open(p, "w", encoding="utf-8"), indent=1)
        plan.append({"file": p, "count": len(items[i:i + CHUNK])})
    json.dump(plan, io.open(os.path.join(OUT, "_collision_plan.json"), "w", encoding="utf-8"),
              indent=1)

    print("=== %s  (%s)" % (OUT, csv_name))
    print("  static world hulls  : %d" % n_static)
    print("  per-instance hulls  : %d" % (len(items) - n_static))
    for m, c in sorted(counts.items()):
        print("      %-26s %5d" % (m, c))
    print("  total Parts         : %d  -> %d chunk file(s) of <=%d"
          % (len(items), len(plan), CHUNK))
    print("  published assets    : 0   (Parts are native primitives)")
    print("COLLISION PARTS DONE")


if __name__ == "__main__":
    main()
