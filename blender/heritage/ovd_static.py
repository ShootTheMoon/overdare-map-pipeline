# -*- coding: utf-8 -*-
"""3-2단계 — STATIC 지오메트리(지형 타일·수면·석단) 준비.

STATIC 은 `mesh.users == 1` 인 것들이다. 마스터와 달리 **월드 좌표 그대로** 내보내
임포터가 (0,0,0)에 떨구면 맵이 저절로 조립되게 한다(시부야에서 검증된 방식).
"""
import json
import math
import os

import bpy
import bmesh

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXWORK = os.path.join(ROOT, "06_OVERDARE", "_texwork")
TERDIR = os.path.join(ROOT, "06_OVERDARE", "01_TERRAIN")
WORK = "OVD_WORK"
EXTENT = 260.0
HALF = EXTENT * 0.5
TILES = 4


def _coll(name):
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(c)
    return c


def _mat_with(name, image_path, alpha=False):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (400, 0)
    b = nt.nodes.new("ShaderNodeBsdfPrincipled"); b.location = (120, 0)
    b.inputs["Metallic"].default_value = 0.0
    b.inputs["Roughness"].default_value = 0.9
    nt.links.new(b.outputs["BSDF"], out.inputs["Surface"])
    if image_path and os.path.exists(image_path):
        key = os.path.basename(image_path)
        im = bpy.data.images.get(key) or bpy.data.images.load(image_path)
        n = nt.nodes.new("ShaderNodeTexImage"); n.location = (-220, 0)
        n.image = im
        nt.links.new(n.outputs["Color"], b.inputs["Base Color"])
        if alpha:
            nt.links.new(n.outputs["Alpha"], b.inputs["Alpha"])
            mat.blend_method = "HASHED"
    return mat


def flat_png(name, rgb=None, px=64):
    """상수색 머티리얼은 텍스처가 없으면 FBX에서 회색으로 나온다(기록된 함정 D).

    **Blender 내장 파이썬에는 PIL이 없다.** 여기서 만들려 하면 조용히 실패한다.
    파일은 밖에서 미리 만들고(ovd_textures 계열) 여기서는 로드만 한다."""
    p = os.path.join(TEXWORK, name + ".png")
    if not os.path.exists(p):
        raise RuntimeError("미리 만들어야 하는 단색 텍스처가 없다: " + p)
    return p


def split_terrain(src_name="JSN_Terrain", tiles=TILES):
    """지형을 월드 위치 기준 타일로 쪼개고 타일별 UV/머티리얼을 준다."""
    src = bpy.data.objects.get(src_name)
    if src is None:
        return {"error": "없음 " + src_name}
    me0 = src.data
    mw = src.matrix_world
    step = EXTENT / tiles

    # 면을 무게중심 기준으로 타일에 배정
    buckets = {}
    for p in me0.polygons:
        c = mw @ p.center
        tx = int(min(tiles - 1, max(0, math.floor((c.x + HALF) / step))))
        ty = int(min(tiles - 1, max(0, math.floor((c.y + HALF) / step))))
        buckets.setdefault((tx, ty), []).append(p.index)

    made = []
    for (tx, ty), idxs in sorted(buckets.items()):
        bm = bmesh.new()
        bm.from_mesh(me0)
        bm.faces.ensure_lookup_table()
        keep = set(idxs)
        drop = [f for f in bm.faces if f.index not in keep]
        if drop:
            bmesh.ops.delete(bm, geom=drop, context="FACES")
        me = bpy.data.meshes.new("MD_TER_%d%d" % (tx, ty))
        bm.to_mesh(me)
        bm.free()

        # 월드 좌표를 굽고 타일 로컬 UV를 만든다
        for v in me.vertices:
            v.co = mw @ v.co
        x0 = -HALF + tx * step
        y0 = -HALF + ty * step
        uv = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
        for poly in me.polygons:
            for li in poly.loop_indices:
                co = me.vertices[me.loops[li].vertex_index].co
                u = min(1.0, max(0.0, (co.x - x0) / step))
                v2 = min(1.0, max(0.0, (co.y - y0) / step))
                uv.data[li].uv = (u, v2)
        me.materials.clear()
        me.materials.append(_mat_with("OVD_TER_%d%d" % (tx, ty),
                                      os.path.join(TERDIR, "TER_%d%d.png" % (tx, ty))))
        for poly in me.polygons:
            poly.material_index = 0
        me.update()

        obj = bpy.data.objects.new("STA_TER_%d%d" % (tx, ty), me)
        _coll(WORK).objects.link(obj)
        obj.hide_set(True)
        obj.hide_render = True
        me.calc_loop_triangles()
        made.append({"name": obj.name, "tris": len(me.loop_triangles),
                     "verts": len(me.vertices)})
    return made


def prep_water():
    """계류·지류 수면. 절차적 재질이라 단색 PNG를 물린다."""
    out = []
    for src_name, col in (("JSN_StreamWater", (0.10, 0.20, 0.22)),
                          ("JSN_TribWater", (0.10, 0.20, 0.22))):
        src = bpy.data.objects.get(src_name)
        if src is None:
            continue
        obj = src.copy()
        obj.data = src.data.copy()
        obj.name = "STA_" + src_name.replace("JSN_", "")
        _coll(WORK).objects.link(obj)
        me = obj.data
        mw = obj.matrix_world.copy()
        for v in me.vertices:
            v.co = mw @ v.co
        obj.matrix_world.identity()
        uv = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
        for poly in me.polygons:
            for li in poly.loop_indices:
                co = me.vertices[me.loops[li].vertex_index].co
                uv.data[li].uv = ((co.x % 8.0) / 8.0, (co.y % 8.0) / 8.0)
        me.materials.clear()
        me.materials.append(_mat_with("OVD_WATER", flat_png("WATER_FLAT", col)))
        for poly in me.polygons:
            poly.material_index = 0
        me.update(); me.calc_loop_triangles()
        obj.hide_set(True); obj.hide_render = True
        out.append({"name": obj.name, "tris": len(me.loop_triangles),
                    "verts": len(me.vertices)})
    return out


def prep_steps():
    src = bpy.data.objects.get("JSN_TrailSteps")
    if src is None:
        return {"error": "없음"}
    obj = src.copy()
    obj.data = src.data.copy()
    obj.name = "STA_STEPS"
    _coll(WORK).objects.link(obj)
    me = obj.data
    mw = obj.matrix_world.copy()
    for v in me.vertices:
        v.co = mw @ v.co
    obj.matrix_world.identity()
    # 절차적 슬랩이라 UV가 없다 — 박스 투영으로 만든다
    uv = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
    for poly in me.polygons:
        n = poly.normal
        for li in poly.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            if abs(n.z) >= max(abs(n.x), abs(n.y)):
                a, b2 = co.x, co.y
            elif abs(n.x) >= abs(n.y):
                a, b2 = co.y, co.z
            else:
                a, b2 = co.x, co.z
            uv.data[li].uv = ((a % 1.6) / 1.6, (b2 % 1.6) / 1.6)
    me.materials.clear()
    me.materials.append(_mat_with("OVD_STEPS", os.path.join(TEXWORK, "ROCK_A.png")))
    for poly in me.polygons:
        poly.material_index = 0
    me.update(); me.calc_loop_triangles()
    obj.hide_set(True); obj.hide_render = True
    return {"name": obj.name, "tris": len(me.loop_triangles), "verts": len(me.vertices)}
