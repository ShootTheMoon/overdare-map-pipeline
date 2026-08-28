# -*- coding: utf-8 -*-
"""
MI_Capital01B / MI_GreenWood / MI_Gongpo01E plateau at ~30% under COLLAPSE while
MI_Giwa reaches 2% cleanly. Welding made it worse. Test what actually gets past it:

  A  PLANAR dissolve at several angles, then COLLAPSE
  B  UNSUBDIVIDE (a different algorithm entirely)
  C  COLLAPSE with use_collapse_triangulate off
  D  straight COLLAPSE (control)

blender.exe --background --factory-startup --python cdg_planartest.py
"""
import math

import bpy

FBX = r"C:\Work\blender\CDG_Changdeokgung\_extracted\FBX\Injeongjeon.fbx"
MATS = ["MI_Capital01B", "MI_GreenWood", "MI_Gongpo01E"]
TARGET = 0.02


def tri(me):
    me.calc_loop_triangles()
    return len(me.loop_triangles)


def submesh(src, mi):
    polys = [p for p in src.polygons if p.material_index == mi]
    vmap, verts, faces, uvs = {}, [], [], []
    uvl = src.uv_layers[0] if src.uv_layers else None
    for p in polys:
        idx = []
        for li in p.loop_indices:
            vi = src.loops[li].vertex_index
            if vi not in vmap:
                vmap[vi] = len(verts)
                verts.append(src.vertices[vi].co.copy())
            idx.append(vmap[vi])
            uvs.append(tuple(uvl.uv[li].vector) if uvl else (0, 0))
        faces.append(tuple(idx))
    me = bpy.data.meshes.new("T")
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.update()
    if uvl:
        lay = me.uv_layers.new(name="UVMap")
        flat = []
        for u, v in uvs:
            flat += [u, v]
        if len(flat) == len(me.loops) * 2:
            lay.uv.foreach_set("vector", flat)
    return me


def apply_mods(o):
    dg = bpy.context.evaluated_depsgraph_get()
    nm = bpy.data.meshes.new_from_object(o.evaluated_get(dg))
    o.modifiers.clear()
    o.data = nm


def mk(me):
    o = bpy.data.objects.new("t", me.copy())
    bpy.context.scene.collection.objects.link(o)
    return o


def run(base, label, fn):
    o = mk(base)
    fn(o)
    got = tri(o.data)
    uv = len(o.data.uv_layers)
    bpy.data.objects.remove(o, do_unlink=True)
    return label, got, uv


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=FBX, use_image_search=False,
                             use_anim=False, use_custom_normals=False)
    src = next(o for o in bpy.data.objects if o.type == "MESH")
    names = [ms.material.name if ms.material else "" for ms in src.material_slots]

    for mat in MATS:
        mi = names.index(mat)
        base = submesh(src.data, mi)
        bt = tri(base)
        print("\n=== {}  src {:,} tris   (target x{} = {:,})".format(
            mat, bt, TARGET, int(bt * TARGET)))

        def collapse(o, r=TARGET, trig=True):
            d = o.modifiers.new("D", "DECIMATE")
            d.decimate_type = "COLLAPSE"
            d.ratio = r
            d.use_collapse_triangulate = trig
            apply_mods(o)

        results = [run(base, "D control COLLAPSE", lambda o: collapse(o))]
        results.append(run(base, "C no-triangulate",
                           lambda o: collapse(o, trig=False)))

        for ang in (1, 5, 15, 30):
            def f(o, a=ang):
                d = o.modifiers.new("P", "DECIMATE")
                d.decimate_type = "DISSOLVE"
                d.angle_limit = math.radians(a)
                d.delimit = {"UV"}
                apply_mods(o)
                t = o.modifiers.new("T", "TRIANGULATE")
                t.min_vertices = 4
                apply_mods(o)
                collapse(o)
            results.append(run(base, "A planar %2d deg + collapse" % ang, f))

        for it in (1, 2, 3):
            def g(o, n=it):
                d = o.modifiers.new("U", "DECIMATE")
                d.decimate_type = "UNSUBDIV"
                d.iterations = n
                apply_mods(o)
            results.append(run(base, "B unsubdivide x%d" % it, g))

        for lab, got, uv in results:
            print("   {:<28}{:>10,}   ratio {:.4f}  uv_layers {}".format(
                lab, got, got / max(bt, 1), uv))
        bpy.data.meshes.remove(base)


main()
