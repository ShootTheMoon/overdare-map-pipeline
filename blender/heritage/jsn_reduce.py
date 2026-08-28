# -*- coding: utf-8 -*-
"""JSN_Sangok → OVERDARE 반입용 감량 실험/적용.

핵심 판단
---------
- **알파 카드 식생은 collapse decimate 하면 안 된다.** 잎은 독립된 사각/삼각
  카드 다발이고, collapse는 카드를 삼각형 파편으로 무너뜨려 UV와 실루엣을
  동시에 망가뜨린다. 카드는 **섬(loose part) 단위로 통째 솎아낸다.**
- 수간(수피)은 이어진 통 메시라 collapse가 통한다.
- 자연 암석(주상절리)은 구조물이 아니라 유기체 형상이므로 collapse 가능.
  (창덕궁에서 상자형 구조물을 collapse했다가 산산조각 난 것과는 다른 경우)

오버데어 기준(docs.overdare.com): 메시당 ≤30,000 tris, 파일 ≤250 MB,
텍스처 ≤15 MB(권장 512), 프롭당 ~700 verts, 화면당 ~70,000 verts.
**정점을 센다** — 삼각형보다 정점이 기준이다.
"""
import bpy
import bmesh


def _islands(bm, face_set):
    """면 집합을 연결 요소(카드)로 나눈다."""
    seen = set()
    out = []
    for f in face_set:
        if f.index in seen:
            continue
        stack = [f]
        seen.add(f.index)
        comp = []
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


def reduce_foliage(obj, leaf_slots, keep_ratio, bark_ratio, name=None):
    """잎은 카드 단위 솎기, 수피는 collapse. 새 오브젝트를 반환한다."""
    new = obj.copy()
    new.data = obj.data.copy()
    new.name = name or (obj.name + "_LOD")
    bpy.context.scene.collection.objects.link(new)

    me = new.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()

    leaf_faces = {f for f in bm.faces if f.material_index in leaf_slots}
    isl = _islands(bm, leaf_faces)
    isl.sort(key=lambda c: -sum(f.calc_area() for f in c))   # 큰 카드부터 남긴다
    keep_n = max(1, int(round(len(isl) * keep_ratio)))
    drop = []
    for comp in isl[keep_n:]:
        drop.extend(comp)
    if drop:
        bmesh.ops.delete(bm, geom=drop, context="FACES")
    bm.to_mesh(me)
    bm.free()
    me.update()

    # 남은 카드를 조금 키워 빈 곳을 메운다(솎아낸 만큼 수관이 성겨지므로)
    if keep_ratio < 0.9:
        pass  # 스케일 보정은 호출측에서 판단

    if bark_ratio < 1.0:
        mod = new.modifiers.new("DEC_BARK", "DECIMATE")
        mod.ratio = bark_ratio
        mod.use_collapse_triangulate = True
    return new


def stats(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    me.calc_loop_triangles()
    v, t = len(me.vertices), len(me.loop_triangles)
    ev.to_mesh_clear()
    return v, t
