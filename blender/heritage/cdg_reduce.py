# -*- coding: utf-8 -*-
"""
CDG - stage 3: reduce one KHS asset to its triangle budget, per-material.

Strategy
--------
Material names in these KHS assets are semantic (MI_Giwa, MI_Gongpo01E,
MI_ChangBang01A, MI_Stone01A ...), so each material gets a TIER RATIO expressing
how much of it is worth keeping.  Silhouette carries the read of a Korean palace
building - the eave curve, the bracket sets, the ridge ornaments - so those tiers
keep the most; flat stone and floors keep the least because their detail already
lives in the authored _NM normal maps, which stay valid because collapse
decimation preserves the surviving vertices' original UVs.

The tiers are RELATIVE.  A single scalar k is solved by bisection so that
    sum over materials of  clamp(tier_ratio * k, floor, 1.0) * src_tris
lands on the asset's budget.  That keeps the priority shape identical across
assets while hitting each asset's number exactly.

Everything runs headless-safe:
  * no bpy.ops.object.mode_set('EDIT')  - it does not fail under --background,
    it spins forever (cost a previous project 2h26m of dead CPU)
  * modifiers are applied through the depsgraph, not bpy.ops.modifier_apply
  * transforms are baked from the EVALUATED mesh and measured from real
    vertices, never bound_box (stale on quaternion-rotated imports)

Usage:
  blender.exe --background --factory-startup --python cdg_reduce.py -- <Key> [<Key> ...]
"""
import json
import math
import os
import sys
import time

import bmesh
import bpy
from mathutils import Matrix

ROOT = r"C:\Work\blender\CDG_Changdeokgung"
FBX_DIR = os.path.join(ROOT, "_extracted", "FBX")
LAYOUT = os.path.join(ROOT, "_scripts", "cdg_layout.json")
BLEND_DIR = os.path.join(ROOT, "20_ARCHITECTURE")
REPORT = os.path.join(ROOT, "_extracted", "REDUCE_REPORT.json")

WELD_DIST = 0.0002    # OVERDARE counts VERTS, so welding is worth more than tris
# All ratio/floor thresholds live in cdg_layout.json -> decimation_policy, so the
# policy has exactly one authoritative home (a previous project shipped every
# atlas at 1/64 scale because a cap constant was duplicated across four files).


# --------------------------------------------------------------------- policy
def load_cfg():
    with open(LAYOUT, encoding="utf-8") as f:
        return json.load(f)


def tier_for(mat_name, policy):
    """-> (tier_name, mode, ratio, planar_angle, min_absolute_ratio)"""
    n = mat_name.lower()
    for tier in policy["tiers"]:
        for pat in tier["patterns"]:
            if pat in n:
                return (tier.get("name", "?"), tier["mode"],
                        tier.get("ratio", 1.0), tier.get("planar_angle"),
                        tier.get("min_absolute_ratio", 0.0))
    return ("default", policy["default_mode"], policy["default_ratio"], None, 0.0)


def solve_k(items, target, policy):
    """items: list of (src_tris, tier_ratio) for COLLAPSE parts only.
    Find the scalar k so the collapse group totals `target`."""
    min_ratio = policy["min_ratio"]
    floor_tris = policy["min_tris_floor"]
    keep_below = policy["keep_below_tris"]

    def out_for(src, r, k, minabs=0.0):
        if src <= keep_below:
            return src
        eff = max(min_ratio, min(1.0, r * k))
        eff = max(eff, minabs)
        return max(min(src, floor_tris), eff * src)

    def total(k):
        return sum(out_for(s, r, k, ma) for s, r, ma in items)

    lo, hi = 1e-6, 1e6
    if total(hi) <= target:
        return hi
    if total(lo) >= target:
        return lo
    for _ in range(80):
        mid = math.sqrt(lo * hi)
        if total(mid) > target:
            hi = mid
        else:
            lo = mid
    return math.sqrt(lo * hi)


# ------------------------------------------------------------------- geometry
def tri_count(me):
    me.calc_loop_triangles()
    return len(me.loop_triangles)


def apply_modifiers(obj):
    """Apply every modifier via the depsgraph - no bpy.ops, headless-safe."""
    dg = bpy.context.evaluated_depsgraph_get()
    new_me = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    old = obj.data
    obj.modifiers.clear()
    obj.data = new_me
    if old.users == 0:
        bpy.data.meshes.remove(old)


def decimate(obj, ratio, planar_angle=None, dissolve_boundaries=False,
             delimit=None):
    if planar_angle:
        m = obj.modifiers.new("PLANAR", "DECIMATE")
        m.decimate_type = "DISSOLVE"
        m.angle_limit = math.radians(planar_angle)
        m.delimit = delimit if delimit is not None else {"UV", "MATERIAL", "SHARP"}
        m.use_dissolve_boundaries = dissolve_boundaries
        apply_modifiers(obj)
        # DISSOLVE makes ngons; bring it back to triangles before collapsing
        t = obj.modifiers.new("TRI", "TRIANGULATE")
        t.min_vertices = 4
        apply_modifiers(obj)

    if ratio < 0.999:
        cur = tri_count(obj.data)
        if cur > 3:
            m = obj.modifiers.new("COLLAPSE", "DECIMATE")
            m.decimate_type = "COLLAPSE"
            m.ratio = max(1.0 / cur, ratio)
            m.use_collapse_triangulate = True
            apply_modifiers(obj)


def weld(obj, dist=WELD_DIST):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=dist)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def bake_world(src):
    """Duplicate from the evaluated mesh with matrix_world baked into verts."""
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(src.evaluated_get(dg))
    o = bpy.data.objects.new("BK_" + src.name, me)
    bpy.context.scene.collection.objects.link(o)
    o.data.transform(src.matrix_world)
    o.matrix_world = Matrix.Identity(4)
    return o


def split_by_material(o):
    """One object per material, built by hand. Never bpy.ops - see module docstring."""
    me = o.data
    if len(me.materials) <= 1:
        return [o]
    used = sorted({p.material_index for p in me.polygons})
    if len(used) <= 1:
        return [o]

    uvl = me.uv_layers[0] if me.uv_layers else None
    out = []
    buckets = {mi: [] for mi in used}
    for p in me.polygons:
        buckets[p.material_index].append(p)

    for mi in used:
        polys = buckets[mi]
        if not polys:
            continue
        vmap = {}
        verts = []
        faces = []
        uvs = []
        for p in polys:
            idx = []
            for li in p.loop_indices:
                vi = me.loops[li].vertex_index
                if vi not in vmap:
                    vmap[vi] = len(verts)
                    verts.append(me.vertices[vi].co.copy())
                idx.append(vmap[vi])
                uvs.append(tuple(uvl.uv[li].vector) if uvl else (0.0, 0.0))
            faces.append(tuple(idx))

        mat = me.materials[mi] if mi < len(me.materials) else None
        name = (mat.name if mat else "none")
        nm = bpy.data.meshes.new("ME_%s" % name[:56])
        nm.from_pydata([tuple(v) for v in verts], [], faces)
        nm.update()
        if mat:
            nm.materials.append(mat)
        if uvl:
            lay = nm.uv_layers.new(name="UVMap")
            flat = []
            for u, v in uvs:
                flat += [u, v]
            if len(flat) == len(nm.loops) * 2:
                lay.uv.foreach_set("vector", flat)
        no = bpy.data.objects.new("OB_%s" % name[:56], nm)
        bpy.context.scene.collection.objects.link(no)
        out.append(no)

    bpy.data.objects.remove(o, do_unlink=True)
    return [x for x in out if x.data.polygons]


# ----------------------------------------------------------------------- main
def reduce_asset(key, cfg):
    asset = next((a for a in cfg["assets"] if a["key"] == key), None)
    if asset is None:
        return {"key": key, "error": "not in cdg_layout.json"}
    path = os.path.join(FBX_DIR, key + ".fbx")
    if not os.path.exists(path):
        return {"key": key, "error": "missing " + path}

    policy = cfg["decimation_policy"]
    target = asset["target_tris"]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    t0 = time.time()
    bpy.ops.import_scene.fbx(filepath=path, use_image_search=False,
                             use_anim=False, use_custom_normals=False)
    t_imp = time.time() - t0

    src_objs = [o for o in bpy.data.objects if o.type == "MESH"]
    baked = [bake_world(o) for o in src_objs]
    for o in src_objs:
        bpy.data.objects.remove(o, do_unlink=True)

    parts = []
    for o in baked:
        parts.extend(split_by_material(o))

    keep_below = policy["keep_below_tris"]
    floor_tris = policy["min_tris_floor"]
    min_ratio = policy["min_ratio"]

    meta = []
    for o in parts:
        mat = o.data.materials[0].name if o.data.materials else "__none"
        name, mode, ratio, pangle, minabs = tier_for(mat, policy)
        meta.append({"obj": o, "material": mat, "tier": name, "mode": mode,
                     "ratio": ratio, "planar_angle": pangle,
                     "min_absolute_ratio": minabs,
                     "src_tris": tri_count(o.data)})
    src_total = sum(m["src_tris"] for m in meta)

    t1 = time.time()

    # Pass 1: structural parts get PLANAR dissolve only. Box-like stone platforms,
    # floors and stairs lose their coplanar fans but keep their exact silhouette.
    # Collapsing them shatters the mesh - verified visually.
    struct_out = 0
    for m in meta:
        if m["mode"] != "planar_only":
            continue
        o = m["obj"]
        if m["src_tris"] > keep_below:
            decimate(o, 1.0, m["planar_angle"] or 3.0)
        weld(o)
        m["out_tris"] = tri_count(o.data)
        m["eff_ratio"] = round(m["out_tris"] / max(m["src_tris"], 1), 5)
        struct_out += m["out_tris"]

    # Pass 2: solve k over the collapse group against whatever budget is left.
    collapse = [m for m in meta if m["mode"] != "planar_only"]
    budget = max(target - struct_out, int(0.25 * target))
    k = solve_k([(m["src_tris"], m["ratio"], m.get("min_absolute_ratio", 0.0))
                 for m in collapse], budget, policy)

    cpp = policy.get("collapse_planar_prepass") or {}
    slack = float(cpp.get("plateau_slack", 1.6))
    for m in collapse:
        o = m["obj"]
        src = m["src_tris"]
        if src <= keep_below:
            eff = 1.0
        else:
            eff = max(min_ratio, min(1.0, m["ratio"] * k))
            if eff * src < floor_tris:
                eff = min(1.0, floor_tris / float(src))
            # A tier may declare a floor that the k solve cannot push through.
            eff = max(eff, m.get("min_absolute_ratio", 0.0))

        # Plain collapse first. It is lossless-ish on continuously mapped surfaces
        # and reaches the requested ratio exactly (MI_Giwa hits 0.0200).
        backup = o.data.copy() if (cpp and src >= cpp.get("min_src_tris", 1 << 30)) else None
        decimate(o, eff, None)
        got = tri_count(o.data)
        want = max(eff * src, 1.0)
        m["planar_prepass"] = False

        # ONLY if it plateaued (materials built from tens of thousands of separate
        # solid pieces bottom out around 22-32%) retry from the pristine mesh with a
        # dissolve prepass. Applying that prepass unconditionally destroyed the roof:
        # MI_Giwa collapsed to 0.0044 and the tile surface vanished, exposing the
        # rafters through it.
        if backup is not None and got > want * slack:
            old = o.data
            o.data = backup
            backup = None
            if old.users == 0:
                bpy.data.meshes.remove(old)
            decimate(o, eff, cpp["angle_deg"],
                     cpp.get("dissolve_boundaries", False), delimit={"UV"})
            got = tri_count(o.data)
            m["planar_prepass"] = True
        if backup is not None and backup.users == 0:
            bpy.data.meshes.remove(backup)

        weld(o)
        m["eff_ratio"] = round(eff, 5)
        m["out_tris"] = tri_count(o.data)
        m["plateaued"] = got > want * slack

    for m in meta:
        m["obj"].data.shade_smooth()

    rows = [{"material": m["material"], "tier": m["tier"], "mode": m["mode"],
             "src_tris": m["src_tris"], "eff_ratio": m["eff_ratio"],
             "out_tris": m["out_tris"],
             "out_verts": len(m["obj"].data.vertices)} for m in meta]
    t_dec = time.time() - t1

    out_total = sum(r["out_tris"] for r in rows)
    out_verts = sum(r["out_verts"] for r in rows)

    # measure the reduced result from real vertices
    lo = [1e18] * 3
    hi = [-1e18] * 3
    for o in parts:
        for v in o.data.vertices:
            for i in range(3):
                if v.co[i] < lo[i]:
                    lo[i] = v.co[i]
                if v.co[i] > hi[i]:
                    hi[i] = v.co[i]

    os.makedirs(os.path.join(BLEND_DIR, asset["zone"]), exist_ok=True)
    blend = os.path.join(BLEND_DIR, asset["zone"], "CDG_%s_reduced.blend" % key)
    bpy.ops.wm.save_as_mainfile(filepath=blend)

    return {
        "key": key,
        "zone": asset["zone"],
        "blend": blend,
        "import_sec": round(t_imp, 1),
        "decimate_sec": round(t_dec, 1),
        "k": round(k, 5),
        "structural_out_tris": struct_out,
        "collapse_budget": budget,
        "src_tris": src_total,
        "target_tris": target,
        "out_tris": out_total,
        "out_verts": out_verts,
        "overall_ratio": round(out_total / max(src_total, 1), 5),
        "part_count": len(parts),
        "dims": [round(hi[i] - lo[i], 4) for i in range(3)],
        "ground_z": round(lo[2], 4),
        "materials": sorted(rows, key=lambda r: -r["src_tris"]),
    }


def main():
    keys = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    cfg = load_cfg()
    report = {}
    if os.path.exists(REPORT):
        with open(REPORT, encoding="utf-8") as f:
            report = json.load(f)

    for k in keys:
        print("\n=== reducing", k, "===")
        r = reduce_asset(k, cfg)
        report[k] = r
        if "error" in r:
            print("  ERROR:", r["error"])
            continue
        print("  {:,} -> {:,} tris (target {:,}, k={})  {} parts  {:.1f}s".format(
            r["src_tris"], r["out_tris"], r["target_tris"], r["k"],
            r["part_count"], r["decimate_sec"]))
        print("  verts {:,}   dims {}   ground_z {}".format(
            r["out_verts"], r["dims"], r["ground_z"]))
        for m in r["materials"][:10]:
            print("    {:<24} {:>9,} -> {:>7,}  x{:<8.4f} {}".format(
                m["material"][:23], m["src_tris"], m["out_tris"],
                m["eff_ratio"], m["tier"]))
        with open(REPORT, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
    print("\nwrote", REPORT)


main()
