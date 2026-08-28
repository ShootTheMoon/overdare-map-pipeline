# -*- coding: utf-8 -*-
"""
Diagnose why COLLAPSE decimation stalls on some Injeongjeon materials.

Hypothesis: MI_Capital01B (1,236,462 tris) is built from tens of thousands of
SEPARATE closed shells (one per bracket member). Collapse cannot merge across
disconnected components, so each shell bottoms out at ~4 triangles and the
material has a hard floor of 4 x shell_count - which would explain the observed
360,456 (ratio 0.29 when 0.021 was requested).

If that is the cause, welding by distance first fuses touching shells into a
manifold that collapse CAN reduce.

blender.exe --background --factory-startup --python cdg_shelltest.py
"""
import os

import bmesh
import bpy

FBX = r"C:\Work\blender\CDG_Changdeokgung\_extracted\FBX\Injeongjeon.fbx"
TEST_MATS = ["MI_Capital01B", "MI_Gongpo01E", "MI_GreenWood", "MI_Giwa"]
WELDS = [0.0, 0.002, 0.01, 0.03]
TARGET_RATIO = 0.02


def tri(me):
    me.calc_loop_triangles()
    return len(me.loop_triangles)


def shell_count(me):
    bm = bmesh.new()
    bm.from_mesh(me)
    seen = set()
    n = 0
    for f in bm.faces:
        if f.index in seen:
            continue
        n += 1
        stack = [f]
        seen.add(f.index)
        while stack:
            cur = stack.pop()
            for e in cur.edges:
                for lf in e.link_faces:
                    if lf.index not in seen:
                        seen.add(lf.index)
                        stack.append(lf)
    bm.free()
    return n


def submesh(src_me, mat_index):
    polys = [p for p in src_me.polygons if p.material_index == mat_index]
    vmap = {}
    verts = []
    faces = []
    for p in polys:
        idx = []
        for li in p.loop_indices:
            vi = src_me.loops[li].vertex_index
            if vi not in vmap:
                vmap[vi] = len(verts)
                verts.append(src_me.vertices[vi].co.copy())
            idx.append(vmap[vi])
        faces.append(tuple(idx))
    me = bpy.data.meshes.new("T")
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.update()
    return me


def apply_mods(o):
    dg = bpy.context.evaluated_depsgraph_get()
    nm = bpy.data.meshes.new_from_object(o.evaluated_get(dg))
    o.modifiers.clear()
    o.data = nm


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=FBX, use_image_search=False,
                             use_anim=False, use_custom_normals=False)
    src = next(o for o in bpy.data.objects if o.type == "MESH")
    me = src.data
    names = [ms.material.name if ms.material else "" for ms in src.material_slots]

    print("\n{:<18}{:>10}{:>9}{:>10}{:>12}{:>10}".format(
        "material", "src_tris", "weld_m", "shells", "after_weld", "collapsed"))
    for mat in TEST_MATS:
        if mat not in names:
            print(mat, "not found")
            continue
        mi = names.index(mat)
        base = submesh(me, mi)
        base_t = tri(base)
        for w in WELDS:
            m2 = base.copy()
            o = bpy.data.objects.new("t", m2)
            bpy.context.scene.collection.objects.link(o)
            if w > 0:
                bm = bmesh.new()
                bm.from_mesh(m2)
                bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=w)
                bm.to_mesh(m2)
                bm.free()
                m2.update()
            welded_t = tri(m2)
            sh = shell_count(m2) if base_t < 1500000 else -1
            d = o.modifiers.new("D", "DECIMATE")
            d.decimate_type = "COLLAPSE"
            d.ratio = TARGET_RATIO
            d.use_collapse_triangulate = True
            apply_mods(o)
            got = tri(o.data)
            print("{:<18}{:>10,}{:>9.3f}{:>10,}{:>12,}{:>10,}  -> actual ratio {:.4f}".format(
                mat, base_t, w, sh, welded_t, got, got / max(base_t, 1)))
            bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.meshes.remove(base)


main()
