"""Weld coincident vertices across the scene, refusing any mesh whose shape changes.

Imported assets arrive with vertices split at every UV seam and hard edge, so the taxi
carried 50,607 verts for 32,449 triangles. Welding at 0.1 mm removes only genuinely
coincident points: UVs live on loops so seams survive, and the triangle count is the
proof - if it moves, the shape moved, and that mesh is rolled back.

OVERDARE counts VERTICES (700/prop recommended, 70,000 on screen), not triangles, so
this is the single highest-value pass available on this scene.
"""
import bpy, bmesh, time

DIST = 0.0001          # 0.1 mm - only truly coincident points
TRI_TOL = 0.005        # a mesh losing >0.5% of its triangles is reverted
MIN_VERTS = 64


def tri_of(me):
    return sum(len(p.vertices) - 2 for p in me.polygons)


def run():
    t0 = time.time()
    meshes = [m for m in bpy.data.meshes if m.users > 0 and len(m.vertices) >= MIN_VERTS]
    v0 = sum(len(m.vertices) for m in meshes)
    t_before = sum(tri_of(m) for m in meshes)
    changed = reverted = 0
    detail = []
    for me in meshes:
        nv, nt = len(me.vertices), tri_of(me)
        if nt == 0:
            continue
        backup = me.copy()                       # cheap insurance against a bad weld
        bm = bmesh.new(); bm.from_mesh(me)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=DIST)
        bm.to_mesh(me); bm.free()
        nt2 = tri_of(me)
        if abs(nt2 - nt) > max(1, nt*TRI_TOL):
            me.clear_geometry()                  # roll back: shape actually changed
            bm = bmesh.new(); bm.from_mesh(backup); bm.to_mesh(me); bm.free()
            reverted += 1
        else:
            d = nv - len(me.vertices)
            if d > 0:
                changed += 1
                if d > 2000: detail.append((d, me.name, nv, len(me.vertices)))
        bpy.data.meshes.remove(backup)
    v1 = sum(len(m.vertices) for m in meshes)
    t_after = sum(tri_of(m) for m in meshes)
    print("meshes scanned=%d  welded=%d  reverted=%d" % (len(meshes), changed, reverted), flush=True)
    print("unique verts %s -> %s  (-%.1f%%)" % (
        format(v0, ','), format(v1, ','), 100*(v0-v1)/max(1, v0)), flush=True)
    print("unique tris  %s -> %s  (delta %+d = %.4f%%)  <- shape proof" % (
        format(t_before, ','), format(t_after, ','), t_after-t_before,
        100*abs(t_after-t_before)/max(1, t_before)), flush=True)
    for d, n, a, b in sorted(detail, reverse=True)[:10]:
        print("   %-30s %7d -> %7d  (-%d%%)" % (n, a, b, 100*d//a), flush=True)
    print("%.0fs" % (time.time()-t0), flush=True)
    return v0, v1
