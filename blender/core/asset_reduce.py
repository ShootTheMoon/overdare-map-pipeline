"""S4 asset reduction: measure what is actually invisible, then cut in the safe order.

Order matters and is not negotiable:
  1. delete faces that CANNOT be seen  - zero visual risk, and on these assets it is the
     single biggest cut (the vending machine is 38.3% interior by island containment)
  2. remove_doubles + dissolve_limit    - topology cleanup, silhouette preserved exactly
  3. Decimate COLLAPSE                  - last and least; this is the only step that can
     break a silhouette, so it only ever runs on what survives 1 and 2

Step 1 is measured, not guessed. Picking faces by MATERIAL NAME would be wrong: the taxi
has 59 slots with names like `Meshpart1Mtl` and `Fix0101Mtl` that say nothing about where
the geometry is. Instead every face is tested against a ring of realistic viewpoints - a
street prop is seen from eye height at a few metres, never from underneath - and a face is
kept if ANY viewpoint can see it.

    measure(obj)                 -> print the visibility/stage breakdown, change nothing
    reduce(obj, target, ...)     -> apply stages 1-3 and report each

Run headless. Never call bpy.ops.object.mode_set - it hangs under -b.
"""
import bpy
import bmesh
import math
import collections
from mathutils import Vector
from mathutils.bvhtree import BVHTree

# A pedestrian-scale prop is looked at from eye height a few metres away, and from the
# 45-degree aerials used for the map overview. Never from below: nothing in this map is
# ever seen from under the ground plane, which is exactly why undersides can go.
AZIMUTHS = 40
ELEVATIONS = (3.0, 12.0, 30.0, 55.0)
EPS = 0.004


def _viewpoints(centre, radius):
    out = []
    for el in ELEVATIONS:
        ce, se = math.cos(math.radians(el)), math.sin(math.radians(el))
        for i in range(AZIMUTHS):
            a = 2.0*math.pi*i/AZIMUTHS
            out.append(centre + Vector((math.cos(a)*ce, math.sin(a)*ce, se)) * radius)
    return out


def visibility(ob, pad=3.0):
    """-> (visible_face_indices set, viewpoints). A face is visible if any viewpoint sees
    its front side with nothing in between."""
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    verts = [v.co.copy() for v in bm.verts]
    tris = []
    for f in bm.faces:
        idx = [v.index for v in f.verts]
        for k in range(1, len(idx)-1):
            tris.append((idx[0], idx[k], idx[k+1]))
    bvh = BVHTree.FromPolygons(verts, tris)

    lo = Vector((min(v.x for v in verts), min(v.y for v in verts), min(v.z for v in verts)))
    hi = Vector((max(v.x for v in verts), max(v.y for v in verts), max(v.z for v in verts)))
    centre = (lo + hi) * 0.5
    radius = (hi - lo).length * pad
    vps = _viewpoints(centre, radius)

    vis = set()
    for f in bm.faces:
        c = f.calc_center_median()
        n = f.normal
        if n.length < 1e-9:
            vis.add(f.index)          # degenerate: keep, deleting it proves nothing
            continue
        origin = c + n*EPS
        for vp in vps:
            d = vp - origin
            dist = d.length
            if dist < 1e-6:
                continue
            d = d / dist
            if n.dot(d) <= 0.0:
                continue              # backfacing from this viewpoint
            hit = bvh.ray_cast(origin, d, dist)
            if hit[0] is None:
                vis.add(f.index)
                break
    bm.free()
    return vis, len(vps)


def _tris(me):
    return sum(len(p.vertices) - 2 for p in me.polygons)


def preview(ob, outdir, tag_prefix="S4", res=(640, 480)):
    """3-angle workbench render. Decimation can only break one thing - the silhouette -
    so this is the check that matters, and it has to be looked at, not assumed."""
    import os
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.film_transparent = False
    cam = bpy.data.objects.get("S4CAM")
    if cam is None:
        cam = bpy.data.objects.new("S4CAM", bpy.data.cameras.new("S4CAM"))
        sc.collection.objects.link(cam)
    cam.data.clip_end = 500.0
    sc.camera = cam
    # the asset .blends ship REF_Human / REF_Ground scale references, and REF_Human stands
    # right in front of the prop - the first render was three frames of the mannequin.
    hidden = []
    for o in bpy.data.objects:
        if o.type == 'MESH' and o is not ob and not o.hide_render:
            o.hide_render = True
            hidden.append(o)

    M = ob.matrix_world
    pts = [M @ v.co for v in ob.data.vertices]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    ctr = (lo + hi) * 0.5
    rad = max((hi - lo).x, (hi - lo).y, (hi - lo).z) * 2.2
    os.makedirs(outdir, exist_ok=True)
    out = []
    for tag, az, el in (("front", 20.0, 8.0), ("side", 100.0, 8.0), ("aerial", 55.0, 38.0)):
        a, e = math.radians(az), math.radians(el)
        cam.location = ctr + Vector((math.cos(a)*math.cos(e),
                                     math.sin(a)*math.cos(e),
                                     math.sin(e))) * rad
        # camera looks down local -Z with +Y up; building the euler by hand got this wrong
        # and rendered three frames of empty background.
        cam.rotation_euler = (ctr - cam.location).to_track_quat('-Z', 'Y').to_euler()
        p = os.path.join(outdir, "%s_%s_%s.png" % (ob.name, tag_prefix, tag))
        sc.render.filepath = p
        bpy.ops.render.render(write_still=True)
        out.append(p)
    for o in hidden:
        o.hide_render = False
    return out


def measure(ob, pad=3.0):
    me = ob.data
    t0 = _tris(me)
    vis, nvp = visibility(ob, pad)
    bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table()
    hid_t = sum(len(f.verts)-2 for f in bm.faces if f.index not in vis)
    per = collections.Counter()
    tot = collections.Counter()
    for f in bm.faces:
        tot[f.material_index] += len(f.verts)-2
        if f.index not in vis:
            per[f.material_index] += len(f.verts)-2
    bm.free()
    print("  %-28s tris=%-8s faces=%-7d viewpoints=%d"
          % (ob.name, format(t0, ','), len(me.polygons), nvp))
    print("      NEVER VISIBLE: %s tris (%.1f%%)" % (format(hid_t, ','), 100.0*hid_t/max(1, t0)))
    rows = sorted(((per.get(mi, 0), mi) for mi in tot), reverse=True)[:10]
    for h, mi in rows:
        if not h:
            continue
        nm = me.materials[mi].name if mi < len(me.materials) and me.materials[mi] else "?"
        print("        mi=%-3d %-28s %6s / %6s hidden (%.0f%%)"
              % (mi, nm[:28], format(h, ','), format(tot[mi], ','), 100.0*h/tot[mi]))
    return hid_t, t0


def reduce(ob, target, pad=3.0, weld=0.0002, dissolve_deg=4.0, keep_visibility=True):
    """stages 1-3; returns a list of (stage, tris)"""
    me = ob.data
    log = [("start", _tris(me))]

    if keep_visibility:
        vis, _ = visibility(ob, pad)
        bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table()
        kill = [f for f in bm.faces if f.index not in vis]
        if kill:
            bmesh.ops.delete(bm, geom=kill, context='FACES')
            bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces],
                             context='VERTS')
        bm.to_mesh(me); bm.free()
        log.append(("hidden-removed", _tris(me)))

    bm = bmesh.new(); bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=weld)
    bm.to_mesh(me); bm.free()
    log.append(("welded", _tris(me)))

    bm = bmesh.new(); bm.from_mesh(me)
    # delimit on material so a dissolve never merges two shaded regions into one face
    bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(dissolve_deg),
                             verts=list(bm.verts), edges=list(bm.edges),
                             delimit={'MATERIAL', 'UV'})
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    bm.to_mesh(me); bm.free()
    log.append(("dissolved", _tris(me)))

    cur = _tris(me)
    if cur > target:
        mod = ob.modifiers.new("S4_Decimate", 'DECIMATE')
        mod.decimate_type = 'COLLAPSE'
        mod.ratio = max(0.02, float(target)/cur)
        mod.use_collapse_triangulate = True
        dg = bpy.context.evaluated_depsgraph_get()
        ev = ob.evaluated_get(dg)
        new = bpy.data.meshes.new_from_object(ev)
        ob.modifiers.remove(mod)
        old = ob.data
        name = old.name
        ob.data = new
        # remove the old datablock BEFORE renaming, or the new one gets `name.001` -
        # shibuya_export_v2.classify() keys on o.data.name and a .NNN suffix mis-buckets it
        # (the map already carries UP_UtilityPole_A.001 and SHIBUYA_GROUND.002 from exactly
        # this mistake).
        if old.users == 0:
            bpy.data.meshes.remove(old)
        new.name = name
        log.append(("decimated", _tris(ob.data)))

    for stage, n in log:
        print("      %-16s %8s" % (stage, format(n, ',')))
    return log


def prune_material_slots(ob):
    """Drop slots that carry no face. The taxi ships 59 and shibuya_export_v2 splits by
    material, so every empty slot is a wasted MeshPart.

    me.materials.clear() RESETS every polygon's material_index to 0, so the indices have to
    be captured before the clear and written back after. Doing it the other way round put
    all 2,500 taxi faces onto slot 0 and textured the whole car with its licence plate."""
    me = ob.data
    before = len(me.materials)
    if before < 2:
        return before, before
    used = sorted(set(p.material_index for p in me.polygons))
    if len(used) == before:
        return before, before
    remap = {old: new for new, old in enumerate(used)}
    mats = [me.materials[i] for i in used]
    idx = [remap[p.material_index] for p in me.polygons]      # capture FIRST
    me.materials.clear()
    for m in mats:
        me.materials.append(m)
    for p, i in zip(me.polygons, idx):                        # write back AFTER
        p.material_index = i
    assert sorted(set(p.material_index for p in me.polygons)) == list(range(len(mats)))
    return before, len(me.materials)
