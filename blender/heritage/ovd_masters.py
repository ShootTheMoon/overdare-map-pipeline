# -*- coding: utf-8 -*-
"""2단계 — 인스턴스 마스터 감량 + FBX 반출.

마스터는 배치 테이블이 이름으로 지목하는 단위라 **절대 쪼개면 안 된다**
(쪼개면 placement 행이 그만큼 배가된다). 그래서 마스터 하나 = 오브젝트 하나 =
머티리얼 하나 = 텍스처 하나로 만든다.

- 바위: 머티리얼 1개 + UV 0~1이라 감량만 하면 끝난다. 자연 암석이므로 collapse 가능.
- 식생: 잎은 카드 섬 단위로 솎고(collapse는 알파 카드를 부순다), 수피는 collapse.
  수피/줄기 UV가 타일링(v 11~66배)이라 0~1로 정규화한 뒤 아틀라스해 1머티리얼로 합친다.
- 자갈: UV가 없다(BOX 투영). 박스 투영 UV를 손으로 만든다.
"""
import json
import math
import os

import bpy
import bmesh

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXWORK = os.path.join(ROOT, "06_OVERDARE", "_texwork")
OUTDIR = os.path.join(ROOT, "06_OVERDARE", "10_MASTERS")
# 오버데어 규칙이 두 갈래다: 공식 문서는 "메시당 30k", 초기 실측은 "파일 총합 30k".
# 스모크 테스트에서 36,329 tris 번들(2메시)이 등록 0으로 실패하고, 단일 파일
# 26,999 / 8,329 은 통과했다. **양쪽을 다 만족시킨다 — 파일당 메시 하나, 27k 이하.**
TRI_CAP = 27000

WORK = "OVD_WORK"


def _coll(name):
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(c)
    return c


def _clear_work():
    c = bpy.data.collections.get(WORK)
    if c:
        for o in list(c.objects):
            bpy.data.objects.remove(o, do_unlink=True)


def _tris(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    me.calc_loop_triangles()
    n, v = len(me.loop_triangles), len(me.vertices)
    ev.to_mesh_clear()
    return n, v


def _apply_mods(obj):
    """모디파이어를 실제 메시로 굽는다. 평가된 메시에서 새로 만든다."""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
    old = obj.data
    obj.data = me
    obj.modifiers.clear()
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return obj


def _flat_mat(name, texname):
    """TEX_IMAGE -> Principled.Base Color -> Output 만. 여분 맵은 표면을 오염시킨다."""
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (400, 0)
    b = nt.nodes.new("ShaderNodeBsdfPrincipled"); b.location = (120, 0)
    b.inputs["Metallic"].default_value = 0.0
    b.inputs["Roughness"].default_value = 0.85
    nt.links.new(b.outputs["BSDF"], out.inputs["Surface"])
    path = os.path.join(TEXWORK, texname + ".png")
    if os.path.exists(path):
        im = bpy.data.images.get(texname + ".png")
        if im is None:
            im = bpy.data.images.load(path)
        n = nt.nodes.new("ShaderNodeTexImage"); n.location = (-220, 0)
        n.image = im
        nt.links.new(n.outputs["Color"], b.inputs["Base Color"])
        if im.channels == 4 or texname.endswith(("_LEAF", "_HEAD")) or "LEAF" in texname:
            if "Alpha" in b.inputs:
                nt.links.new(n.outputs["Alpha"], b.inputs["Alpha"])
                mat.blend_method = "HASHED"
    return mat


def prep_rock(src_name, tex_name, out_name):
    """바위 마스터 하나: 복제 -> collapse 감량 -> 단일 머티리얼 -> 원점 재중심."""
    src = bpy.data.objects.get(src_name)
    if src is None:
        return {"error": "없음 " + src_name}
    obj = src.copy()
    obj.data = src.data.copy()
    obj.name = out_name
    _coll(WORK).objects.link(obj)
    obj.matrix_world.identity()

    t0, v0 = _tris(obj)
    if t0 > TRI_CAP:
        mod = obj.modifiers.new("DEC", "DECIMATE")
        mod.ratio = min(1.0, TRI_CAP / float(t0))
        mod.use_collapse_triangulate = True
        _apply_mods(obj)

    obj.data.materials.clear()
    obj.data.materials.append(_flat_mat("OVD_" + out_name, tex_name))
    for p in obj.data.polygons:
        p.material_index = 0

    # 자기 피벗에 재중심: 바닥 중앙을 원점으로
    me = obj.data
    xs = [v.co.x for v in me.vertices]; ys = [v.co.y for v in me.vertices]
    zs = [v.co.z for v in me.vertices]
    cx, cy, cz = (min(xs)+max(xs))*0.5, (min(ys)+max(ys))*0.5, min(zs)
    for v in me.vertices:
        v.co.x -= cx; v.co.y -= cy; v.co.z -= cz
    me.update()

    t1, v1 = _tris(obj)
    return {"name": out_name, "tris": t1, "verts": v1,
            "from_tris": t0, "ratio": round(t1 / float(t0), 4),
            "dims": [round(max(xs)-min(xs), 2), round(max(ys)-min(ys), 2), round(max(zs)-min(zs), 2)]}


def prep_pebble(out_name="MST_PEBBLE"):
    """자갈 마스터. 원본은 BOX 투영을 써서 **UV가 아예 없다** — FBX는 UV를
    들고 가지 못하므로 손으로 만들어야 한다. 12정점짜리 저폴리라 구면 투영이면 충분."""
    src = bpy.data.objects.get("JSN_PebbleSrc")
    if src is None:
        return {"error": "JSN_PebbleSrc 없음"}
    obj = src.copy()
    obj.data = src.data.copy()
    obj.name = out_name
    _coll(WORK).objects.link(obj)
    obj.matrix_world.identity()
    me = obj.data

    uv = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
    for poly in me.polygons:
        for li in poly.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co.normalized()
            u = 0.5 + math.atan2(co.y, co.x) / (2.0 * math.pi)
            v = 0.5 - math.asin(max(-1.0, min(1.0, co.z))) / math.pi
            # 바위 텍스처의 중앙부만 쓴다 — 가장자리 이음매를 피한다
            uv.data[li].uv = (0.25 + u * 0.5, 0.25 + v * 0.5)

    me.materials.clear()
    me.materials.append(_flat_mat("OVD_" + out_name, "ROCK_A"))
    for p in me.polygons:
        p.material_index = 0
    zs = [v.co.z for v in me.vertices]
    for v in me.vertices:
        v.co.z -= min(zs)
    me.update()
    t, vv = _tris(obj)
    return {"name": out_name, "tris": t, "verts": vv}


def export_fbx(obj_names, path):
    """오버데어용 FBX 반출.

    axis_up='Y', axis_forward='-Z' 로 내면 Y-up cm 가 자동으로 맞는다.
    path_mode='COPY' + embed 로 텍스처를 파일에 넣는다(디스크의 512 PNG이지
    팩 이미지가 아니라서 원본 해상도가 되살아나는 함정에 걸리지 않는다).
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for o in bpy.data.objects:
        o.select_set(False)
    keep = []
    for n in obj_names:
        o = bpy.data.objects.get(n)
        if o is None:
            continue
        o.hide_set(False)
        o.hide_render = False
        o.select_set(True)
        keep.append(o)
    if not keep:
        return {"error": "선택할 오브젝트 없음"}
    bpy.context.view_layer.objects.active = keep[0]
    bpy.ops.export_scene.fbx(
        filepath=path,
        use_selection=True,
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_NONE",
        object_types={"MESH"},
        use_mesh_modifiers=True,
        mesh_smooth_type="FACE",
        path_mode="COPY",
        embed_textures=True,
        axis_forward="-Z",
        axis_up="Y",
        bake_space_transform=False,
    )
    for o in keep:
        o.select_set(False)
        o.hide_set(True)
        o.hide_render = True
    return {"file": path, "mb": round(os.path.getsize(path) / 1048576.0, 2),
            "objects": [o.name for o in keep]}


ROCKS = [("SM_JSN_RockA", "ROCK_A"), ("SM_JSN_RockB", "ROCK_B"),
         ("SM_JSN_RockC", "ROCK_C"), ("SM_JSN_RockD", "ROCK_D"),
         ("SM_JSN_RockE", "ROCK_E"), ("SM_JSN_RockF", "ROCK_F"),
         ("SM_JSN_RockMass", "ROCK_MASS")]


def build_rocks():
    out = []
    for src, tex in ROCKS:
        out.append(prep_rock(src, tex, "MST_" + tex))
    return out


# ---------------------------------------------------------------- 식생

def _islands(bm, face_set):
    seen, out = set(), []
    for f in face_set:
        if f.index in seen:
            continue
        stack, comp = [f], []
        seen.add(f.index)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for e in cur.edges:
                for nf in e.link_faces:
                    if nf in face_set and nf.index not in seen:
                        seen.add(nf.index)
                        stack.append(nf)
        out.append(comp)
    return out


def _uv_bounds(me, slots):
    uv = me.uv_layers.active
    lo = [9e9, 9e9]; hi = [-9e9, -9e9]
    for p in me.polygons:
        if p.material_index not in slots:
            continue
        for li in p.loop_indices:
            u, v = uv.data[li].uv
            lo[0] = min(lo[0], u); hi[0] = max(hi[0], u)
            lo[1] = min(lo[1], v); hi[1] = max(hi[1], v)
    return lo, hi


def prep_veg(src_name, out_name, atlas_name, slot_tex, leaf_slots, keep_ratio, bark_ratio):
    """식생 마스터 하나.

    slot_tex: {머티리얼 슬롯 인덱스: 아틀라스 rect 이름}
    leaf_slots: 카드 솎기를 적용할 슬롯 집합
    """
    src = bpy.data.objects.get(src_name)
    if src is None:
        return {"error": "없음 " + src_name}
    obj = src.copy()
    obj.data = src.data.copy()
    obj.name = out_name
    _coll(WORK).objects.link(obj)
    obj.matrix_world.identity()
    t0, v0 = _tris(obj)

    # 1) 잎 카드 솎기 — collapse는 알파 카드를 파편으로 부순다
    me = obj.data
    bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table()
    leaf = {f for f in bm.faces if f.material_index in leaf_slots}
    isl = _islands(bm, leaf)
    isl.sort(key=lambda c: -sum(f.calc_area() for f in c))
    # 섬 '개수'로 자르면 안 된다 — 면적 순 정렬이라 큰 섬이 면 대부분을 갖고 있어
    # 개수 22%를 남겨도 실제 면은 75%가 남는다. **면 수 예산으로 누적해 자른다.**
    total_leaf_faces = sum(len(c) for c in isl)
    budget = total_leaf_faces * keep_ratio
    acc, keep_n = 0, 0
    for c in isl:
        if acc + len(c) > budget and keep_n > 0:
            break
        acc += len(c); keep_n += 1
    drop = [f for comp in isl[keep_n:] for f in comp]
    if drop:
        bmesh.ops.delete(bm, geom=drop, context="FACES")
    bm.to_mesh(me); bm.free(); me.update()
    cards_before, cards_after = len(isl), keep_n

    # 2) 수피/줄기 collapse — 잎을 지키려면 잎 슬롯을 잠가야 한다
    if bark_ratio < 1.0:
        vg = obj.vertex_groups.new(name="BARK")
        idx = set()
        for p in me.polygons:
            if p.material_index not in leaf_slots:
                idx.update(p.vertices)
        vg.add(list(idx), 1.0, "REPLACE")
        # **Decimate의 ratio는 정점 그룹이 아니라 메시 전체 기준이다.**
        # 그룹만 지정하고 ratio=0.35를 주면, 깎을 수 없는 잎 카드 몫까지 수피에서
        # 빼내려 해서 수피가 96% 날아가고 수간이 통째로 사라진다(실제로 당함).
        # 수피만 bark_ratio로 줄어들도록 전체 기준 ratio로 환산한다.
        n_all = len(me.vertices)
        n_bark = len(idx)
        eff = (n_all - n_bark * (1.0 - bark_ratio)) / float(max(1, n_all))
        mod = obj.modifiers.new("DEC", "DECIMATE")
        mod.ratio = min(1.0, max(0.02, eff))
        mod.use_collapse_triangulate = True
        mod.vertex_group = "BARK"
        _apply_mods(obj)
        me = obj.data

    # 3) 타일링 UV 정규화 후 아틀라스 rect로 remap
    uv = me.uv_layers.active
    n = len(slot_tex)
    cols = 2 if n > 1 else 1
    rows = int(math.ceil(n / float(cols)))
    rects = {}
    for i, slot in enumerate(sorted(slot_tex)):
        rects[slot] = (i % cols, i // cols, cols, rows)
    bounds = {s: _uv_bounds(me, {s}) for s in slot_tex}
    for p in me.polygons:
        s = p.material_index
        if s not in rects:
            continue
        cx, cy, cc, rr = rects[s]
        lo, hi = bounds[s]
        du = max(1e-6, hi[0] - lo[0]); dv = max(1e-6, hi[1] - lo[1])
        for li in p.loop_indices:
            u, v = uv.data[li].uv
            # 타일링이면 전체 범위를 0~1로 압축, 아니면 그대로
            nu = (u - lo[0]) / du if (lo[0] < -0.05 or hi[0] > 1.05) else min(1.0, max(0.0, u))
            nv = (v - lo[1]) / dv if (lo[1] < -0.05 or hi[1] > 1.05) else min(1.0, max(0.0, v))
            uv.data[li].uv = ((cx + nu) / cc, 1.0 - (cy + (1.0 - nv)) / rr)

    # 4) 머티리얼 하나로
    me.materials.clear()
    me.materials.append(_flat_mat("OVD_" + out_name, atlas_name))
    for p in me.polygons:
        p.material_index = 0

    # 5) 자기 피벗 재중심 (바닥 중앙)
    xs = [v.co.x for v in me.vertices]; ys = [v.co.y for v in me.vertices]
    zs = [v.co.z for v in me.vertices]
    cx0, cy0, cz0 = (min(xs)+max(xs))*0.5, (min(ys)+max(ys))*0.5, min(zs)
    for v in me.vertices:
        v.co.x -= cx0; v.co.y -= cy0; v.co.z -= cz0
    me.update()

    t1, v1 = _tris(obj)
    return {"name": out_name, "tris": t1, "verts": v1, "from_tris": t0, "from_verts": v0,
            "cards": "%d->%d" % (cards_before, cards_after),
            "rects": {str(k): v for k, v in rects.items()},
            "dims": [round(max(xs)-min(xs), 2), round(max(ys)-min(ys), 2), round(max(zs)-min(zs), 2)]}
