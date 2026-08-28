# -*- coding: utf-8 -*-
"""JSN_Sangok — 조선 산곡(소나무 능선) 자연지형 맵.

설계 승계: SSW_Soswaewon/_scripts/ssw_live.py 에서 검증된
  - _import_fbx_file (KHS FBX 축 -Z / Y)
  - 정점컬러 마스크 + Mix 노드 PBR 지형 블렌딩
  - OP(알파) 채널 식생 배선
를 산곡 지형용으로 다시 구성했다.

좌표계: 1 BU = 1 m. 맵 260 x 260 m, 플레이 가능 코어 약 190 x 200 m.
계류(溪流)가 남북으로 흐르는 골짜기, 서쪽은 주상절리 암반 능선,
동쪽은 완만한 소나무 사면, 북쪽에 고갯길(saddle) 초크포인트.
"""
import json
import math
import os
import re

import bpy
import bmesh
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXTRACT = os.path.join(ROOT, "_extracted")
VEG_DIR = os.path.join(EXTRACT, "VEG")
MASTER = os.path.join(ROOT, "00_Source_Blender", "JSN_Master.blend")

# 지면·석재 텍스처는 원래 CDG(창덕궁)와 SSW(소쇄원) 프로젝트에서 참조해 썼다.
# 다른 컴퓨터로 넘길 때 그 절대경로가 깨지므로, 필요한 12장을 프로젝트 안
# `_TexLib/`에 동봉하고 **로컬을 우선 사용**한다. 로컬에 없으면 원래 경로로 폴백해
# 이 PC에서의 기존 동작도 유지한다.
LOCAL_TEX = os.path.join(ROOT, "_TexLib")
_NEED = ("T_Ground01A_BC.png", "T_Ground02A_BC.png", "T_Stone01B_BC.png",
         "T_Sand_ColorB_BC4k.png")
_HAVE_LOCAL = all(os.path.exists(os.path.join(LOCAL_TEX, f)) for f in _NEED)

CDG_TEX = LOCAL_TEX if _HAVE_LOCAL else \
    r"C:\Work\blender\CDG_Changdeokgung\_extracted\_TexLib"
SSW_SAND = LOCAL_TEX if _HAVE_LOCAL else \
    r"C:\Work\blender\SSW_Soswaewon\_extracted\Sand"

EXTENT = 260.0          # 전체 한 변
HALF = EXTENT * 0.5
SEGS = 340              # 0.76 m 격자 (계류 도랑 단면을 해상하려면 1 m로는 부족)

COLL = {
    "TERRAIN": "JSN_TERRAIN",
    "ROCK": "JSN_ROCK",
    "VEG": "JSN_VEG",
    "WATER": "JSN_WATER",
    "LIGHT": "JSN_LIGHTING",
    "CAM": "JSN_CAMERAS",
    "KIT": "JSN_KIT_SOURCE",     # 원본 소스(숨김) — 인스턴스의 부모
}


# ---------------------------------------------------------------- helpers

def _coll(name):
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(c)
    return c


def _move_to(obj, coll_name):
    c = _coll(coll_name)
    for old in list(obj.users_collection):
        old.objects.unlink(obj)
    c.objects.link(obj)


def _mesh_stats(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    if not me.vertices:
        ev.to_mesh_clear()
        return None
    mw = obj.matrix_world
    co = [mw @ v.co for v in me.vertices]
    xs = [c.x for c in co]; ys = [c.y for c in co]; zs = [c.z for c in co]
    me.calc_loop_triangles()
    out = {
        "name": obj.name,
        "verts": len(me.vertices),
        "tris": len(me.loop_triangles),
        "dims": [round(max(xs) - min(xs), 2), round(max(ys) - min(ys), 2), round(max(zs) - min(zs), 2)],
        "min_z": round(min(zs), 3),
        "materials": [m.name if m else None for m in obj.data.materials],
    }
    ev.to_mesh_clear()
    return out


def _img(path, non_color=False):
    if path is None or not os.path.exists(path):
        return None
    key = os.path.basename(path)
    im = bpy.data.images.get(key)
    if im is None:
        im = bpy.data.images.load(path, check_existing=True)
        im.name = key
    if non_color:
        try:
            im.colorspace_settings.name = "Non-Color"
        except Exception:
            pass
    return im


# ---------------------------------------------------------------- 지형 함수

def stream_x(y):
    """계류 중심선. 남쪽 출구(y=-118)에서 거의 0."""
    t = y + 118.0
    return 7.5 * math.sin(t * 0.0165) + 2.8 * math.sin(t * 0.049 + 0.7)


STREAM_S, STREAM_N, STREAM_FADE = -96.0, 90.0, 13.0


def stream_len(y):
    """계류의 종단 존재 범위 0~1.

    이걸 넣지 않으면 도랑이 맵 끝(y=±118)까지 파여 외곽 산벽을 관통해
    절단면을 만들고, 수면이 산벽을 타고 z=+17 m까지 기어올라가 화면에
    검은 수직 벽으로 노출된다. 계류는 산벽에 닿기 전에 끝나야 한다.
    """
    if STREAM_S <= y <= STREAM_N:
        return 1.0
    d = min(abs(y - STREAM_S), abs(y - STREAM_N))
    return max(0.0, 1.0 - d / STREAM_FADE)


TRIB_X0, TRIB_X1 = -66.0, 7.0


def trib_y(x):
    """지류(支流) 중심선. 서쪽 사면 협곡에서 내려와 본류에 합류한다."""
    t = max(0.0, min(1.0, (x - TRIB_X0) / (TRIB_X1 - TRIB_X0)))
    return -38.0 + 24.0 * t ** 1.15 + 2.6 * math.sin(t * 4.4)


def trib_amt(x):
    """지류의 존재 범위 0~1. 양 끝에서 페이드."""
    if x <= TRIB_X0 - 4.0 or x >= TRIB_X1 + 4.0:
        return 0.0
    a = min(1.0, (x - (TRIB_X0 - 4.0)) / 10.0)
    b = min(1.0, ((TRIB_X1 + 4.0) - x) / 7.0)
    return max(0.0, min(a, b))


def trail_x(y):
    """고갯길(산길) 중심선. 계류 동안을 따라 오르다 북쪽 안부로 붙는다."""
    base = stream_x(y) + 13.0 + 4.0 * math.sin((y + 60.0) * 0.035)
    # 북쪽 안부(y≈96)로 수렴
    w = max(0.0, min(1.0, (y - 40.0) / 56.0))
    return base * (1.0 - w) + (8.0 + 6.0 * math.sin(y * 0.09)) * w


def height_at(x, y):
    sx = stream_x(y)
    d = x - sx

    # 골짜기 단면 — 서쪽이 가파르고 높다
    if d < 0.0:
        t = min(1.0, -d / 74.0)
        base = 30.0 * t ** 1.85
    else:
        t = min(1.0, d / 84.0)
        base = 22.0 * t ** 1.95

    # 종단 상승 — 남쪽 입구가 낮고 북쪽이 높다
    yn = min(1.0, max(0.0, (y + 120.0) / 240.0))
    base += 11.0 * yn ** 1.5

    # 서쪽 암반 능선(주상절리 노두 자리)
    gw = math.exp(-((x + 78.0) / 26.0) ** 2)
    crest = 14.0 * gw * (0.75 + 0.25 * math.sin(y * 0.045))
    # y≈-20 에 측면 우회로용 안부를 판다
    crest *= 1.0 - 0.55 * math.exp(-((y + 20.0) / 18.0) ** 2)
    base += crest

    # 동쪽 소나무 능선(완만)
    ge = math.exp(-((x - 86.0) / 34.0) ** 2)
    base += 10.0 * ge * (0.8 + 0.2 * math.sin(y * 0.031 + 1.2))

    # 북쪽 고갯길 안부 — 능선을 끊어 초크포인트를 만든다.
    # 절개를 9.5 m로 잡았더니 산길이 안부로 '내려가는' 지형이 됐다(측정 결과
    # y=76→94에서 z 4.09→0.89). 고개는 올라가는 곳이다. 절개를 줄여 안부가
    # 골짜기 바닥보다 높게 남도록 한다. 능선 마루가 훨씬 높으므로 절개가 얕아도
    # 통로(초크)는 그대로 성립한다.
    saddle = math.exp(-((y - 96.0) / 22.0) ** 2) * math.exp(-((x - 8.0) / 30.0) ** 2)
    base -= 4.0 * saddle
    # 안부 직전 짧고 가파른 오르막(깔딱고개). 여기에만 석단을 놓는다.
    base += 5.5 * math.exp(-((y - 84.0) / 13.0) ** 2) * math.exp(-((x - 10.0) / 34.0) ** 2)

    # 계류 도랑. 폭 1.9 m / 깊이 2.3 m로 팠더니 1 m 격자가 단면을 해상하지 못해
    # 도랑 벽이 톱니로 갈라지고 수면이 뚫고 나왔다. 넓고 얕게 — 격자로 표현 가능한 범위.
    sw = 2.9 + 0.7 * math.sin(y * 0.09) + 0.35 * math.sin(y * 0.23 + 0.5)
    trench = -1.7 * math.exp(-(d / max(1.4, sw)) ** 2) * stream_len(y)

    # 산길 노반 — 살짝 깎아 평탄화
    tx = trail_x(y)
    trail = math.exp(-((x - tx) / 1.25) ** 2)
    bench = -0.35 * trail

    # 미세 기복 — 골짜기 바닥은 잔잔하게
    n = 0.95 * math.sin(x * 0.052) * math.cos(y * 0.041)
    n += 0.52 * math.sin(x * 0.11 + y * 0.07)
    n += 0.27 * math.sin(x * 0.24 + y * 0.17) * math.cos(x * 0.13)
    n *= 0.35 + 0.65 * min(1.0, abs(d) / 25.0)
    n *= 1.0 - 0.7 * trail

    # 지류 협곡 — 서쪽 사면을 가로질러 본류로 내려온다.
    # 사면에 골을 하나 더 만들어 능선 이동을 끊고 도섭(徒涉) 지점을 만든다.
    ta = trib_amt(x)
    if ta > 0.0:
        tw = 2.6 + 0.6 * math.sin(x * 0.13)
        h_trib = -2.1 * math.exp(-((y - trib_y(x)) / max(1.4, tw)) ** 2) * ta
    else:
        h_trib = 0.0

    h = base + trench + bench + n + h_trib

    # 외곽 산벽 — 맵을 자연스럽게 가둔다(투명벽 대신)
    r = max(abs(x), abs(y))
    if r > 100.0:
        t = min(1.0, (r - 100.0) / 30.0)
        h += 30.0 * t * t
    return h


def _slope_at(x, y, e=1.5):
    hx = (height_at(x + e, y) - height_at(x - e, y)) / (2 * e)
    hy = (height_at(x, y + e) - height_at(x, y - e)) / (2 * e)
    return math.sqrt(hx * hx + hy * hy)


def blend_at(x, y):
    """정점컬러 마스크. R=마사토 산길, G=암반(경사), B=젖은 하상."""
    sx = stream_x(y)
    d = x - sx

    # 계류 하상 + 물가 자갈
    sw = 2.4 + 0.8 * math.sin(y * 0.09)
    b = math.exp(-(d / max(1.2, sw)) ** 2) * stream_len(y)
    # 지류 하상도 같은 젖은 자갈로
    ta = trib_amt(x)
    if ta > 0.0:
        b = max(b, math.exp(-((y - trib_y(x)) / 2.2) ** 2) * ta * 0.9)

    # 산길 — 조선의 산골 소로(嶺路)는 사람·지게가 다니는 폭이다.
    # 2.3 m 균질 마사토로 두면 화면에서 현대 탐방로로 읽힌다(고증 메모 4절).
    tx = trail_x(y)
    tw = 0.72 + 0.22 * math.sin(y * 0.13)
    r = math.exp(-((x - tx) / tw) ** 2)
    # 풀 침입 — 노면이 균질하면 포장로가 된다. 군데군데 풀에 먹힌다.
    inv = math.sin(y * 0.31) * math.cos(x * 0.21)
    if inv < -0.62:
        r *= 0.18
    r *= 0.72 + 0.28 * math.sin(y * 0.77 + x * 0.41)
    # 계류 건널목 근처 흙 노출
    r = max(r, 0.5 * math.exp(-((y + 46.0) / 8.0) ** 2 - ((x - sx) / 5.5) ** 2))

    # 석단 구간은 답압이 심해 노면 흙이 넓게 드러난다. 여기만 노면을 넓힌다
    # (돌만 놓고 지면이 잔디면 '잔디밭 위 징검돌'로 보인다).
    r = max(r, 0.90 * math.exp(-((y - 77.8) / 4.2) ** 2 - ((x - tx) / 1.6) ** 2))

    # 솔가리(松落葉) — 소나무 수관 아래 지면은 잔디가 아니라 마른 낙엽층이다.
    # 이게 s9까지 화면을 '골프장'으로 만든 가장 큰 원인이었다(고증 메모 마지막 절).
    r = max(r, 0.78 * pine_density(x, y))

    # 암반 — 경사에서 자연 노출
    s = _slope_at(x, y)
    g = max(0.0, min(1.0, (s - 0.42) / 0.55))
    g = g * g * (3 - 2 * g)
    # 서쪽 능선 크레스트는 확실히 바위
    g = max(g, 0.85 * math.exp(-((x + 78.0) / 15.0) ** 2))

    r = min(1.0, r * (1.0 - g * 0.8))
    b = min(1.0, b * (1.0 - g * 0.5))
    return r, g, b


# ---------------------------------------------------------------- 씬 구성

def boot():
    """빈 씬에서 시작 — SSW 마스터를 절대 건드리지 않는다."""
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.unit_settings.system = "METRIC"
    sc.unit_settings.scale_length = 1.0
    # 레이트레이싱을 켜지 않으면 계류 수면이 반사 없는 검은 아스팔트로 렌더된다.
    ee = sc.eevee
    for k, v in (("use_raytracing", True), ("use_shadows", True), ("use_fast_gi", True)):
        if hasattr(ee, k):
            setattr(ee, k, v)
    if hasattr(ee, "ray_tracing_method"):
        try:
            ee.ray_tracing_method = "SCREEN"
        except Exception:
            pass
    for name in COLL.values():
        _coll(name)
    # 기본 큐브/램프/카메라 제거
    for o in list(bpy.data.objects):
        if o.name in ("Cube", "Light", "Camera"):
            bpy.data.objects.remove(o, do_unlink=True)
    return {"engine": sc.render.engine, "collections": sorted(COLL.values())}


def _pbr(nt, name, bc, nm, rn, x, tile=4.0):
    """한 벌의 PBR 이미지 노드.

    Object 좌표 + BOX(삼중평면) 투영. Generated 좌표를 쓰면 82 m 기복의
    지형에서 바운딩박스 정규화 때문에 급경사면 텍스처가 세로로 늘어난다.
    tile = 텍스처 1장이 덮는 실제 거리(m).
    """
    uv = nt.nodes.new("ShaderNodeTexCoord"); uv.location = (x - 620, 0)
    mp = nt.nodes.new("ShaderNodeMapping"); mp.location = (x - 430, 0)
    s = 1.0 / max(0.001, tile)
    mp.inputs["Scale"].default_value = (s, s, s)
    nt.links.new(uv.outputs["Object"], mp.inputs["Vector"])

    outs = []
    for i, (p, non, dy) in enumerate(((bc, False, 240), (nm, True, 0), (rn, True, -240))):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.location = (x, dy)
        n.label = "%s_%d" % (name, i)
        n.image = _img(p, non)
        n.extension = "REPEAT"
        n.projection = "BOX"
        n.projection_blend = 0.5
        nt.links.new(mp.outputs["Vector"], n.inputs["Vector"])
        outs.append(n.outputs["Color"])
    return outs


def _mix(nt, loc, fac, a, b, label=""):
    n = nt.nodes.new("ShaderNodeMix")
    n.data_type = "RGBA"
    n.location = loc
    n.label = label
    nt.links.new(fac, n.inputs["Factor"])
    for ka, kb in (("A", "B"), ("Color1", "Color2")):
        if ka in n.inputs and kb in n.inputs:
            nt.links.new(a, n.inputs[ka])
            nt.links.new(b, n.inputs[kb])
            break
    else:
        nt.links.new(a, n.inputs[6])
        nt.links.new(b, n.inputs[7])
    return n.outputs["Result"] if "Result" in n.outputs else n.outputs[2]


def _terrain_material():
    """잔디/이끼 기반 + R 마사토 + G 암반 + B 젖은 하상, 정점컬러 마스크 구동."""
    rockdir = os.path.join(EXTRACT, "ROCK_ColumnarA", "Texture")
    # 마지막 값 = 텍스처 1장이 덮는 실제 거리(m)
    sets = {
        "grass": (os.path.join(CDG_TEX, "T_Ground02A_BC.png"),
                  os.path.join(CDG_TEX, "T_Ground02A_NM.png"),
                  os.path.join(CDG_TEX, "T_Ground02A_RN.png"), 5.0),
        "earth": (os.path.join(CDG_TEX, "T_Ground01A_BC.png"),
                  os.path.join(CDG_TEX, "T_Ground01A_NM.png"),
                  os.path.join(CDG_TEX, "T_Ground01A_RN.png"), 4.0),
        # 암반 베이스는 주상절리 스캔(4k, 평균 97 / 편차 33 — 실제 암면).
        # T_Stone01A는 다듬은 기단석이라 평균 178 / 편차 21로 사실상 무늬가 없어
        # 능선이 콘크리트처럼 보였다. 타일 반복은 아래 노이즈 믹스로 깬다.
        "rock":  (os.path.join(rockdir, "T_MDS_UnitA_BC.png"),
                  os.path.join(rockdir, "T_MDS_UnitA_N.png"),
                  os.path.join(rockdir, "T_MDS_UnitA_R.png"), 3.5),
        "rock2": (os.path.join(CDG_TEX, "T_Stone01B_BC.png"),
                  os.path.join(CDG_TEX, "T_Stone01B_NM.png"),
                  os.path.join(CDG_TEX, "T_Stone01B_RN.png"), 9.0),
        "wet":   (os.path.join(SSW_SAND, "T_Sand_ColorB_BC4k.png"),
                  os.path.join(SSW_SAND, "T_Sand_ColorB_NM4k.png"),
                  os.path.join(SSW_SAND, "T_Sand_ColorB_RN4k.png"), 3.0),
    }
    missing = [k for k, v in sets.items() if not os.path.exists(v[0])]

    mat = bpy.data.materials.get("M_JSN_Terrain")
    if mat is None:
        mat = bpy.data.materials.new("M_JSN_Terrain")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (1500, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (1200, 0)
    bsdf.inputs["Metallic"].default_value = 0.0
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    ca = nt.nodes.new("ShaderNodeVertexColor"); ca.location = (-900, -520)
    ca.layer_name = "Blend"
    sep = nt.nodes.new("ShaderNodeSeparateColor"); sep.location = (-700, -520)
    nt.links.new(ca.outputs["Color"], sep.inputs["Color"])

    chans = {}
    xs = {"grass": -1400, "earth": -1000, "rock": -600, "rock2": -600, "wet": -200}
    for k in ("grass", "earth", "rock", "rock2", "wet"):
        bc, nm, rn, tl = sets[k]
        yoff = -900 if k == "rock2" else 0
        chans[k] = _pbr(nt, k, bc, nm, rn, xs[k], tile=tl)
        for s in chans[k]:
            s.node.location = (s.node.location.x, s.node.location.y + yoff)

    # 두 화강암 세트를 대형 노이즈로 섞어 타일 반복을 깬다
    nz = nt.nodes.new("ShaderNodeTexNoise"); nz.location = (-380, -640)
    nz.inputs["Scale"].default_value = 0.09
    nz.inputs["Detail"].default_value = 3.0
    nzco = nt.nodes.new("ShaderNodeTexCoord"); nzco.location = (-560, -640)
    nt.links.new(nzco.outputs["Object"], nz.inputs["Vector"])
    # 노이즈를 그대로 Factor로 쓰면 평균 0.5 — 밝고 밋밋한 T_Stone01B가 절반이나
    # 섞여 암면 대비가 죽는다. 0.08~0.42로 좁혀 디테일 있는 주상절리를 주역으로.
    mr = nt.nodes.new("ShaderNodeMapRange"); mr.location = (-200, -640)
    mr.inputs["To Min"].default_value = 0.08
    mr.inputs["To Max"].default_value = 0.42
    nt.links.new(nz.outputs["Fac"], mr.inputs["Value"])
    nzf = mr.outputs["Result"]
    r1, r2 = chans["rock"], chans["rock2"]
    rcol = _mix(nt, (-60, -520), nzf, r1[0], r2[0], "rock_break_col")
    # 주상절리 스캔은 이미 어둡다. 화강암 쪽으로 살짝만 따뜻하게.
    rtint = nt.nodes.new("ShaderNodeMixRGB")
    rtint.blend_type = "MULTIPLY"
    rtint.location = (120, -520)
    rtint.inputs["Fac"].default_value = 1.0
    nt.links.new(rcol, rtint.inputs["Color1"])
    rtint.inputs["Color2"].default_value = (1.05, 1.00, 0.92, 1.0)
    chans["rock"] = (
        rtint.outputs["Color"],
        _mix(nt, (-60, -700), nzf, r1[1], r2[1], "rock_break_nrm"),
        _mix(nt, (-60, -880), nzf, r1[2], r2[2], "rock_break_rgh"),
    )

    g, e, r, w = chans["grass"], chans["earth"], chans["rock"], chans["wet"]
    fr, fg, fb = sep.outputs[0], sep.outputs[1], sep.outputs[2]

    # T_Ground02A는 이끼(avg 122,129,52)라 그대로 쓰면 골프장처럼 보인다.
    # 산지 하부식생 톤으로 눌러준다. (CDG 프로젝트에서 확인된 함정)
    tint = nt.nodes.new("ShaderNodeMixRGB")
    tint.blend_type = "MULTIPLY"
    tint.location = (-1150, 420)
    tint.inputs["Fac"].default_value = 1.0
    nt.links.new(g[0], tint.inputs["Color1"])
    tint.inputs["Color2"].default_value = (0.44, 0.50, 0.31, 1.0)
    g = (tint.outputs["Color"], g[1], g[2])

    # T_Ground01A(190,152,121)는 밝은 마사토라 그대로 쓰면 산길이 현대
    # 탐방로로, 수관 아래 솔가리가 모래밭으로 보인다. 적황·회색 쪽으로 누른다.
    etint = nt.nodes.new("ShaderNodeMixRGB")
    etint.blend_type = "MULTIPLY"
    etint.location = (-760, 420)
    etint.inputs["Fac"].default_value = 1.0
    nt.links.new(e[0], etint.inputs["Color1"])
    etint.inputs["Color2"].default_value = (0.56, 0.45, 0.33, 1.0)
    e = (etint.outputs["Color"], e[1], e[2])

    # 신두리 해변 모래는 크림색이라 그대로 쓰면 계류변이 백사장이 된다.
    # 산간 계류의 젖은 자갈 톤으로 눌러준다.
    wtint = nt.nodes.new("ShaderNodeMixRGB")
    wtint.blend_type = "MULTIPLY"
    wtint.location = (60, 420)
    wtint.inputs["Fac"].default_value = 1.0
    nt.links.new(w[0], wtint.inputs["Color1"])
    wtint.inputs["Color2"].default_value = (0.60, 0.59, 0.55, 1.0)
    w = (wtint.outputs["Color"], w[1], w[2])

    col = _mix(nt, (300, 300), fr, g[0], e[0], "col_earth")
    col = _mix(nt, (500, 300), fb, col, w[0], "col_wet")
    col = _mix(nt, (700, 300), fg, col, r[0], "col_rock")
    nt.links.new(col, bsdf.inputs["Base Color"])

    nrm = _mix(nt, (300, 40), fr, g[1], e[1], "nrm_earth")
    nrm = _mix(nt, (500, 40), fb, nrm, w[1], "nrm_wet")
    nrm = _mix(nt, (700, 40), fg, nrm, r[1], "nrm_rock")
    nmap = nt.nodes.new("ShaderNodeNormalMap"); nmap.location = (900, 40)
    nmap.inputs["Strength"].default_value = 0.85
    nt.links.new(nrm, nmap.inputs["Color"])

    # --- 근거리 디테일 레이어 -------------------------------------------------
    # 잔디 5 m / 마사토 4 m 타일은 발밑 1~2 m에서 저주파로 뭉갠다. 타일을 더 줄이면
    # 원경에서 반복이 드러나므로, 타일은 그대로 두고 고주파 레이어를 얹는다.
    dtc = nt.nodes.new("ShaderNodeTexCoord"); dtc.location = (500, -560)
    dmp = nt.nodes.new("ShaderNodeMapping"); dmp.location = (660, -560)
    dmp.inputs["Scale"].default_value = (1.7, 1.7, 1.7)      # 약 0.6 m 단위
    nt.links.new(dtc.outputs["Object"], dmp.inputs["Vector"])
    dn = nt.nodes.new("ShaderNodeTexNoise"); dn.location = (840, -560)
    dn.inputs["Scale"].default_value = 2.2
    dn.inputs["Detail"].default_value = 8.0
    dn.inputs["Roughness"].default_value = 0.62
    nt.links.new(dmp.outputs["Vector"], dn.inputs["Vector"])
    # 알갱이 — 자갈·흙덩이 크기의 요철
    dv = nt.nodes.new("ShaderNodeTexVoronoi"); dv.location = (840, -760)
    dv.inputs["Scale"].default_value = 9.0
    nt.links.new(dmp.outputs["Vector"], dv.inputs["Vector"])
    dmix = nt.nodes.new("ShaderNodeMixRGB"); dmix.location = (1010, -640)
    dmix.inputs["Fac"].default_value = 0.20
    nt.links.new(dn.outputs["Fac"], dmix.inputs["Color1"])
    nt.links.new(dv.outputs["Distance"], dmix.inputs["Color2"])
    bump = nt.nodes.new("ShaderNodeBump"); bump.location = (1050, 40)
    bump.inputs["Strength"].default_value = 0.20
    bump.inputs["Distance"].default_value = 0.05
    nt.links.new(dmix.outputs["Color"], bump.inputs["Height"])
    nt.links.new(nmap.outputs["Normal"], bump.inputs["Normal"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    # 색 얼룩 — 같은 노이즈로 명암을 흔들어 '칠한 면'을 깬다
    cbrk = nt.nodes.new("ShaderNodeMapRange"); cbrk.location = (760, 440)
    cbrk.inputs["To Min"].default_value = 0.80
    cbrk.inputs["To Max"].default_value = 1.18
    nt.links.new(dn.outputs["Fac"], cbrk.inputs["Value"])
    cmul = nt.nodes.new("ShaderNodeMixRGB"); cmul.location = (960, 300)
    cmul.blend_type = "MULTIPLY"
    cmul.inputs["Fac"].default_value = 1.0
    nt.links.new(col, cmul.inputs["Color1"])
    nt.links.new(cbrk.outputs["Result"], cmul.inputs["Color2"])
    nt.links.new(cmul.outputs["Color"], bsdf.inputs["Base Color"])

    rough = _mix(nt, (300, -220), fr, g[2], e[2], "rgh_earth")
    rough = _mix(nt, (500, -220), fb, rough, w[2], "rgh_wet")
    rough = _mix(nt, (700, -220), fg, rough, r[2], "rgh_rock")
    nt.links.new(rough, bsdf.inputs["Roughness"])
    return mat, missing


def make_terrain():
    old = bpy.data.objects.get("JSN_Terrain")
    if old:
        bpy.data.objects.remove(old, do_unlink=True)

    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=SEGS, y_segments=SEGS, size=HALF)
    for v in bm.verts:
        v.co.z = height_at(v.co.x, v.co.y)

    # 스커트 — 격자 판의 절단면이 바깥 시점에서 그대로 노출된다.
    # 경계 엣지를 아래로 뽑아 치마를 만들면 어느 각도에서도 판이 떠 보이지 않는다.
    border = [e for e in bm.edges if e.is_boundary]
    if border:
        res = bmesh.ops.extrude_edge_only(bm, edges=border)
        new_v = [g for g in res["geom"] if isinstance(g, bmesh.types.BMVert)]
        for v in new_v:
            v.co.z -= 55.0
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    me = bpy.data.meshes.new("MD_JSN_Terrain")
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new("JSN_Terrain", me)
    _move_to(obj, COLL["TERRAIN"])

    # 정점컬러 마스크
    ca = me.color_attributes.new(name="Blend", type="FLOAT_COLOR", domain="CORNER")
    # blend_at은 pine_density -> _slope_at(height_at 4회)을 타므로 코너마다
    # 부르면 46만 회가 된다. 정점당 한 번만 계산해 캐시한다.
    cache = [None] * len(me.vertices)
    for poly in me.polygons:
        poly.use_smooth = True
        for li in poly.loop_indices:
            vi = me.loops[li].vertex_index
            c = cache[vi]
            if c is None:
                co = me.vertices[vi].co
                c = blend_at(co.x, co.y)
                cache[vi] = c
            ca.data[li].color = (c[0], c[1], c[2], 1.0)
    me.update()

    mat, missing = _terrain_material()
    me.materials.append(mat)
    st = _mesh_stats(obj)
    return {"terrain": st, "missing_textures": missing}


def _water_material():
    """계류 수면.

    평면 + 낮은 거칠기만으로는 고인 물로 보인다. 산간 계류는 (a) 흐름 방향으로
    늘어난 잔물결과 (b) 급한 여울·물가에 생기는 흰 포말이 있어야 물로 읽힌다.
    포말은 정점컬러 "Flow"로 구동한다 — R=유속(종단 경사), G=물가 근접도.
    """
    mat = bpy.data.materials.get("M_JSN_Water") or bpy.data.materials.new("M_JSN_Water")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (860, 0)
    b = nt.nodes.new("ShaderNodeBsdfPrincipled"); b.location = (600, 0)
    b.inputs["Metallic"].default_value = 0.0
    if "Transmission Weight" in b.inputs:
        b.inputs["Transmission Weight"].default_value = 0.62
        b.inputs["IOR"].default_value = 1.333
    nt.links.new(b.outputs["BSDF"], out.inputs["Surface"])

    ca = nt.nodes.new("ShaderNodeVertexColor"); ca.location = (-820, -260)
    ca.layer_name = "Flow"
    sep = nt.nodes.new("ShaderNodeSeparateColor"); sep.location = (-640, -260)
    nt.links.new(ca.outputs["Color"], sep.inputs["Color"])
    f_speed, f_bank = sep.outputs[0], sep.outputs[1]

    # 포말량 = 유속 x 물가가중. 더하면 안 된다 — 유속과 무관하게 물가 전체에
    # 흰 줄이 그어져 페인트로 그은 선처럼 보인다. 잔잔한 물엔 포말이 없어야 한다.
    bank = nt.nodes.new("ShaderNodeMapRange"); bank.location = (-460, -360)
    bank.inputs["To Min"].default_value = 0.45
    bank.inputs["To Max"].default_value = 1.5
    nt.links.new(f_bank, bank.inputs["Value"])
    add = nt.nodes.new("ShaderNodeMath"); add.location = (-280, -260)
    add.operation = "MULTIPLY"; add.use_clamp = True
    nt.links.new(f_speed, add.inputs[0])
    nt.links.new(bank.outputs["Result"], add.inputs[1])

    # 포말 자체도 얼룩져야 한다 — 노이즈로 끊어 준다
    tc = nt.nodes.new("ShaderNodeTexCoord"); tc.location = (-1000, 240)
    mp = nt.nodes.new("ShaderNodeMapping"); mp.location = (-820, 240)
    mp.inputs["Scale"].default_value = (0.55, 0.55, 0.55)
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    fn = nt.nodes.new("ShaderNodeTexNoise"); fn.location = (-640, 240)
    fn.inputs["Scale"].default_value = 3.5
    fn.inputs["Detail"].default_value = 4.0
    nt.links.new(mp.outputs["Vector"], fn.inputs["Vector"])
    fmul = nt.nodes.new("ShaderNodeMath"); fmul.location = (-260, -120)
    fmul.operation = "MULTIPLY"; fmul.use_clamp = True
    nt.links.new(add.outputs[0], fmul.inputs[0])
    nt.links.new(fn.outputs["Fac"], fmul.inputs[1])
    boost = nt.nodes.new("ShaderNodeMath"); boost.location = (-80, -120)
    boost.operation = "MULTIPLY"; boost.use_clamp = True
    boost.inputs[1].default_value = 1.9
    nt.links.new(fmul.outputs[0], boost.inputs[0])
    foam = boost.outputs[0]

    # 색: 맑은 계류(짙은 청록) -> 포말(흰색)
    col = nt.nodes.new("ShaderNodeMixRGB"); col.location = (300, 180)
    col.inputs["Color1"].default_value = (0.055, 0.115, 0.125, 1.0)
    col.inputs["Color2"].default_value = (0.86, 0.90, 0.90, 1.0)
    nt.links.new(foam, col.inputs["Fac"])
    nt.links.new(col.outputs["Color"], b.inputs["Base Color"])

    # 거칠기: 잔잔한 곳 거울, 포말은 거칠게
    rgh = nt.nodes.new("ShaderNodeMapRange"); rgh.location = (300, -60)
    rgh.inputs["To Min"].default_value = 0.045
    rgh.inputs["To Max"].default_value = 0.62
    nt.links.new(foam, rgh.inputs["Value"])
    nt.links.new(rgh.outputs["Result"], b.inputs["Roughness"])

    # 포말은 물이 아니라 기포 덩어리다 — 투과를 꺼야 흰색이 산다
    if "Transmission Weight" in b.inputs:
        tr = nt.nodes.new("ShaderNodeMapRange"); tr.location = (300, -240)
        tr.inputs["To Min"].default_value = 0.62
        tr.inputs["To Max"].default_value = 0.0
        nt.links.new(foam, tr.inputs["Value"])
        nt.links.new(tr.outputs["Result"], b.inputs["Transmission Weight"])

    # 잔물결: 흐름 방향(Y)으로 늘린 노이즈 2겹을 Bump로
    wtc = nt.nodes.new("ShaderNodeTexCoord"); wtc.location = (-1000, -520)
    wmp = nt.nodes.new("ShaderNodeMapping"); wmp.location = (-820, -520)
    wmp.inputs["Scale"].default_value = (7.0, 1.1, 7.0)   # 흐름축으로 길게
    nt.links.new(wtc.outputs["Object"], wmp.inputs["Vector"])
    n1 = nt.nodes.new("ShaderNodeTexNoise"); n1.location = (-620, -520)
    n1.inputs["Scale"].default_value = 5.5
    n1.inputs["Detail"].default_value = 6.0
    nt.links.new(wmp.outputs["Vector"], n1.inputs["Vector"])
    n2 = nt.nodes.new("ShaderNodeTexNoise"); n2.location = (-620, -720)
    n2.inputs["Scale"].default_value = 22.0
    n2.inputs["Detail"].default_value = 3.0
    nt.links.new(wmp.outputs["Vector"], n2.inputs["Vector"])
    nmix = nt.nodes.new("ShaderNodeMixRGB"); nmix.location = (-380, -600)
    nmix.inputs["Fac"].default_value = 0.42
    nt.links.new(n1.outputs["Fac"], nmix.inputs["Color1"])
    nt.links.new(n2.outputs["Fac"], nmix.inputs["Color2"])
    bump = nt.nodes.new("ShaderNodeBump"); bump.location = (300, -440)
    bump.inputs["Strength"].default_value = 0.22
    bump.inputs["Distance"].default_value = 0.035
    nt.links.new(nmix.outputs["Color"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return mat


def _paint_flow(obj, rows, speeds):
    """수면 메시에 Flow 정점컬러를 굽는다. R=유속, G=물가 근접도."""
    me = obj.data
    ca = me.color_attributes.get("Flow")
    if ca is None:
        ca = me.color_attributes.new(name="Flow", type="FLOAT_COLOR", domain="CORNER")
    ncols = len(rows[0])
    # 정점 -> (행, 열) 역인덱스
    idx = {}
    k = 0
    for j, row in enumerate(rows):
        for i in range(len(row)):
            idx[k] = (j, i)
            k += 1
    for poly in me.polygons:
        for li in poly.loop_indices:
            vi = me.loops[li].vertex_index
            j, i = idx.get(vi, (0, 0))
            spd = speeds[min(j, len(speeds) - 1)]
            edge = abs(i / (ncols - 1) * 2.0 - 1.0) ** 2.2    # 물가에서 상승
            ca.data[li].color = (spd, edge, 0.0, 1.0)
    me.update()


def make_water():
    """계류 수면 — 지형 도랑 바닥보다 살짝 위."""
    old = bpy.data.objects.get("JSN_StreamWater")
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
    # 수면은 도랑이 실제로 파여 있는 구간에서만 만든다. 산벽까지 끌고 가면
    # 좁은 짙은 띠가 급벽을 타고 올라가 검은 수직 벽으로 보인다.
    y0 = STREAM_S - STREAM_FADE * 0.55
    y1 = STREAM_N + STREAM_FADE * 0.55
    bm = bmesh.new()
    seg_y = 240
    verts = []
    beds = []
    for j in range(seg_y + 1):
        y = y0 + (y1 - y0) * j / seg_y
        sx = stream_x(y)
        # 수위 = 도랑 바닥 + 수심. 수심도 종단 페이드를 따른다.
        level = height_at(sx, y) + 0.42 * stream_len(y)
        # 좌우 汀線(waterline)을 이분법으로 찾는다.
        # 고정 폭 평면을 쓰면 수면 가장자리가 둑을 사선으로 잘라 면도날 같은
        # 직선이 생긴다. 지형이 수위와 만나는 지점까지만 채워야 물처럼 보인다.
        edges = []
        for sgn in (-1.0, 1.0):
            lo, hi = 0.0, 9.0
            if height_at(sx + sgn * hi, y) <= level:
                edges.append(sx + sgn * hi)
                continue
            for _ in range(24):
                mid = 0.5 * (lo + hi)
                if height_at(sx + sgn * mid, y) <= level:
                    lo = mid
                else:
                    hi = mid
            edges.append(sx + sgn * 0.5 * (lo + hi))
        xl, xr = edges[0], edges[1]
        row = []
        for i in range(9):
            t = i / 8.0
            row.append(bm.verts.new((xl + (xr - xl) * t, y, level)))
        verts.append(row)
        # 유속은 '하상' 기울기로 잰다. 수면 높이에는 종단 페이드(수심 0.42->0)가
        # 섞여 있어 맵 남북 끝에 인위적 급경사가 생기고 거기가 전부 포말이 된다.
        beds.append(height_at(sx, y))
    for j in range(seg_y):
        for i in range(8):
            bm.faces.new((verts[j][i], verts[j][i + 1], verts[j + 1][i + 1], verts[j + 1][i]))
    me = bpy.data.meshes.new("MD_JSN_Water")
    bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new("JSN_StreamWater", me)
    _move_to(obj, COLL["WATER"])

    me.materials.append(_water_material())
    # 유속 = 종단 경사. 여울(급경사)에서 포말이 생긴다.
    dy = (y1 - y0) / seg_y
    speeds = []
    for j in range(len(beds)):
        a = beds[max(0, j - 1)]
        b2 = beds[min(len(beds) - 1, j + 1)]
        g = abs(b2 - a) / (2 * dy)
        yy = y0 + (y1 - y0) * j / seg_y
        speeds.append(max(0.0, min(1.0, (g - 0.02) / 0.13)) * stream_len(yy))
    _paint_flow(obj, verts, speeds)
    for p in me.polygons:
        p.use_smooth = True
    return _mesh_stats(obj)


def make_trib_water():
    """지류 수면. 본류와 같은 汀線 이분법으로 골 단면에 맞춘다."""
    old = bpy.data.objects.get("JSN_TribWater")
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
    bm = bmesh.new()
    seg = 120
    x0, x1 = TRIB_X0 - 2.0, TRIB_X1 + 2.0
    rows = []
    levels = []
    for j in range(seg + 1):
        x = x0 + (x1 - x0) * j / seg
        amt = trib_amt(x)
        cy = trib_y(x)
        level = height_at(x, cy) + 0.22 * amt
        edges = []
        for sgn in (-1.0, 1.0):
            lo, hi = 0.0, 6.0
            if height_at(x, cy + sgn * hi) <= level:
                edges.append(cy + sgn * hi)
                continue
            for _ in range(22):
                mid = 0.5 * (lo + hi)
                if height_at(x, cy + sgn * mid) <= level:
                    lo = mid
                else:
                    hi = mid
            edges.append(cy + sgn * 0.5 * (lo + hi))
        yl, yr = edges[0], edges[1]
        rows.append([bm.verts.new((x, yl + (yr - yl) * (i / 6.0), level)) for i in range(7)])
        levels.append(height_at(x, cy))     # 하상 기준
    for j in range(seg):
        for i in range(6):
            bm.faces.new((rows[j][i], rows[j][i + 1], rows[j + 1][i + 1], rows[j + 1][i]))
    me = bpy.data.meshes.new("MD_JSN_TribWater")
    bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new("JSN_TribWater", me)
    _move_to(obj, COLL["WATER"])
    me.materials.append(_water_material())
    for p in me.polygons:
        p.use_smooth = True
    # 지류는 본류보다 가파르다 — 포말이 더 많이 나오는 게 정상이다
    dx = (x1 - x0) / seg
    speeds = []
    for j in range(len(levels)):
        a = levels[max(0, j - 1)]
        b2 = levels[min(len(levels) - 1, j + 1)]
        g = abs(b2 - a) / (2 * dx)
        xx = x0 + (x1 - x0) * j / seg
        speeds.append(max(0.0, min(1.0, (g - 0.03) / 0.16)) * trib_amt(xx))
    _paint_flow(obj, rows, speeds)
    return _mesh_stats(obj)


STEPS_Y0, STEPS_Y1 = 76.0, 79.6


def make_steps():
    """깔딱고개 가운데의 디딤돌 한 줄.

    1차에서 13단·단높이 0.30 m·폭 2 m로 깔았더니 영로가 아니라 **현대 석계**가 됐고
    길(가시폭 1.4 m)보다 넓어 흙길이 돌계단에 먹혔다(고증 메모 s24 답신 B).

    영로 권고는 단높이 0.18~0.24 m지만, 이 구간의 실측 종단 기울기는 20~23%다.
    그 기울기에서 답면 0.5 m를 잡으면 단높이가 0.11 m밖에 안 나온다. 계단을 만들려고
    지형보다 가파른 단을 쌓으면 오히려 인공 구조물이 되므로, **지형을 따라가는
    디딤돌 한 줄**로 간다("중간에 디딤돌 한 줄만 있으면 깔딱고개로 읽힌다").
    전체 융기 구간(y 69~81)이 아니라 가장 가파른 가운데 3.6 m만 덮는다.
    """
    old = bpy.data.objects.get("JSN_TrailSteps")
    if old:
        bpy.data.objects.remove(old, do_unlink=True)

    n = 6
    bm = bmesh.new()
    for k in range(n):
        t = (k + 0.5) / n
        y = STEPS_Y0 + (STEPS_Y1 - STEPS_Y0) * t
        cx = trail_x(y)
        z = height_at(cx, y)
        # 폭은 흙길(가시폭 1.4 m)보다 좁아야 양옆에 풀이 남는다.
        w = 0.55 + 0.13 * _h01(k, 3, 71.0)        # 반폭 → 전폭 1.10~1.36 m
        d = 0.25 + 0.06 * _h01(k, 3, 72.0)        # 반깊이 → 답면 0.50~0.62 m
        th = 0.12 + 0.06 * _h01(k, 3, 73.0)       # 두께 0.12~0.18 m
        cx += (_h01(k, 3, 75.0) - 0.5) * 0.42     # 어긋난 1열 — 일직선은 사찰 진입로
        yaw = math.radians((_h01(k, 3, 74.0) - 0.5) * 26.0)
        ca, sa = math.cos(yaw), math.sin(yaw)
        # 흙에 반쯤 묻힌다. 지면 위에 얹으면 잔디에 뜬 콘크리트 슬래브로 보인다.
        # 중심은 지면보다 살짝 아래. 사면이 기울어 있으므로 내리막 쪽 절반만
        # 드러나고 오르막 쪽은 흙에 묻힌다 = 반쯤 묻힌 디딤돌.
        top = z - 0.03
        corners = []
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            lx, ly = sx * w, sy * d
            corners.append((cx + lx * ca - ly * sa, y + lx * sa + ly * ca))
        vt = [bm.verts.new((px, py, top)) for px, py in corners]
        vb = [bm.verts.new((px, py, top - th)) for px, py in corners]
        bm.faces.new(vt)
        bm.faces.new(list(reversed(vb)))
        for i in range(4):
            j = (i + 1) % 4
            bm.faces.new((vb[i], vb[j], vt[j], vt[i]))
    me = bpy.data.meshes.new("MD_JSN_TrailSteps")
    bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new("JSN_TrailSteps", me)
    _move_to(obj, COLL["TERRAIN"])

    mat = bpy.data.materials.get("M_JSN_Step")
    if mat is None:
        mat = bpy.data.materials.new("M_JSN_Step")
    # 다듬은 기단석(T_Stone01B)이 아니라 주상절리 부스러기여야 한다.
    # 밝고 매끈한 화강암을 쓰면 장대석 석계로 읽힌다.
    rockdir = os.path.join(EXTRACT, "ROCK_ColumnarA", "Texture")
    _wire_mat(mat,
              os.path.join(rockdir, "T_MDS_UnitA_BC.png"),
              os.path.join(rockdir, "T_MDS_UnitA_N.png"),
              os.path.join(rockdir, "T_MDS_UnitA_R.png"),
              box_tile=0.9)   # 절차적 슬랩이라 UV가 없다 — 삼중평면 필수
    # 주상절리 원본은 평균 97로 매우 어둡다. 작은 디딤돌에 그대로 쓰면
    # 그늘에서 검은 얼룩이 되므로 풍화된 회색 쪽으로 끌어올린다.
    nt = mat.node_tree
    bsdf = next((nd for nd in nt.nodes if nd.type == "BSDF_PRINCIPLED"), None)
    lk = next((l for l in nt.links if l.to_node == bsdf and l.to_socket.name == "Base Color"), None)
    if lk:
        src = lk.from_socket
        mul = nt.nodes.new("ShaderNodeMixRGB"); mul.location = (-60, 220)
        mul.blend_type = "MULTIPLY"; mul.inputs["Fac"].default_value = 1.0
        mul.blend_type = "SCREEN"
        mul.inputs["Fac"].default_value = 0.24
        mul.inputs["Color2"].default_value = (0.62, 0.60, 0.53, 1.0)
        nt.links.new(src, mul.inputs["Color1"])
        nt.links.new(mul.outputs["Color"], bsdf.inputs["Base Color"])
    me.materials.append(mat)
    return _mesh_stats(obj)


def make_lighting():
    for n in ("JSN_Sun", "JSN_Fill"):
        o = bpy.data.objects.get(n)
        if o:
            bpy.data.objects.remove(o, do_unlink=True)
    sd = bpy.data.lights.new("LD_JSN_Sun", type="SUN")
    sd.energy = 5.0
    sd.angle = math.radians(2.2)
    sd.color = (1.0, 0.965, 0.90)
    sun = bpy.data.objects.new("JSN_Sun", sd)
    sun.rotation_euler = (math.radians(46), 0.0, math.radians(-118))
    _move_to(sun, COLL["LIGHT"])

    # 하늘광이 너무 파랗고 세면 그늘진 사면이 전부 슬레이트색으로 죽는다.
    # 위(하늘)는 옅은 하늘색, 아래(지면 반사)는 따뜻한 흙색으로 그라디언트.
    w = bpy.data.worlds.get("JSN_World") or bpy.data.worlds.new("JSN_World")
    bpy.context.scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld"); out.location = (400, 0)
    bg = nt.nodes.new("ShaderNodeBackground"); bg.location = (200, 0)
    bg.inputs[1].default_value = 0.62
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    # 방향 Z로 직접 램프를 구동한다. Mapping 회전으로 그라디언트를 돌리면
    # 전이 지점이 어긋나 지평선 아래 색이 화면 상단까지 올라온다(하늘이 갈색이 됨).
    tc = nt.nodes.new("ShaderNodeTexCoord"); tc.location = (-720, 0)
    sep = nt.nodes.new("ShaderNodeSeparateXYZ"); sep.location = (-540, 0)
    nt.links.new(tc.outputs["Generated"], sep.inputs["Vector"])
    mr = nt.nodes.new("ShaderNodeMapRange"); mr.location = (-360, 0)
    mr.inputs["From Min"].default_value = -0.30
    mr.inputs["From Max"].default_value = 0.55
    nt.links.new(sep.outputs["Z"], mr.inputs["Value"])
    ramp = nt.nodes.new("ShaderNodeValToRGB"); ramp.location = (-120, 0)
    cr = ramp.color_ramp
    # 지평선 아래는 흙색이 아니라 원경 연무여야 한다. 갈색을 두면 하늘이 흙이 된다.
    cr.elements[0].position = 0.0
    cr.elements[0].color = (0.40, 0.42, 0.42, 1.0)
    cr.elements[1].position = 0.42
    cr.elements[1].color = (0.55, 0.63, 0.72, 1.0)
    e2 = cr.elements.new(1.0)
    e2.color = (0.36, 0.50, 0.78, 1.0)
    nt.links.new(mr.outputs["Result"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bg.inputs[0])
    return {"sun": sun.name, "world": w.name}


def make_cameras():
    # 카메라는 반드시 외곽 산벽(|x| 또는 |y| > 100)의 안쪽에 둔다.
    def _eye(x, y, h):
        return (x, y, height_at(x, y) + h)

    specs = [
        # 골짜기 바닥에서 북쪽 고갯길을 올려다봄 (플레이어 시점)
        ("JSN_CAM_Valley", _eye(11.0, -92.0, 1.7), (math.radians(87), 0, math.radians(-6))),
        # 서쪽 암반 능선에서 골짜기 부감.
        # 능선 위 6 m에 두면 수목이 화면을 벽처럼 막는다 — 수관 위로 올려야 한다.
        ("JSN_CAM_Ridge", _eye(-79.0, -58.0, 19.0), (math.radians(73), 0, math.radians(-58))),
        # 고갯길 초크포인트를 남쪽에서
        ("JSN_CAM_Pass", _eye(8.0, 40.0, 2.0), (math.radians(86), 0, math.radians(2))),
        # 깔딱고개 아래에서 석단을 올려다봄
        ("JSN_CAM_Steps", _eye(trail_x(71.0) - 0.8, 71.0, 1.7), (math.radians(93), 0, math.radians(-5))),
        # 지류 합류부 도섭 지점 — 새 지형 특징 확인용
        # 사면 아래 숲의 수관이 18 m라 눈높이에서는 배제 반경을 아무리 키워도
        # 시야가 막힌다. 능선 카메라와 같이 수관 위로 올려 부감한다.
        ("JSN_CAM_Ford", _eye(-56.0, -46.0, 24.0), (math.radians(67), 0, math.radians(-62))),
        # 전체 부감(원근) — 지형 형태 확인용
        ("JSN_CAM_Survey", (0.0, -235.0, 175.0), (math.radians(56), 0, 0.0)),
        ("JSN_CAM_Top", (0.0, 0.0, 400.0), (0.0, 0.0, 0.0)),
    ]
    made = []
    for name, loc, rot in specs:
        o = bpy.data.objects.get(name)
        if o:
            bpy.data.objects.remove(o, do_unlink=True)
        cd = bpy.data.cameras.new("CD_" + name)
        cd.lens = 28.0 if "Top" not in name else 20.0
        cd.clip_end = 2000.0
        if name.endswith("Top"):
            cd.type = "ORTHO"
            cd.ortho_scale = 280.0
        c = bpy.data.objects.new(name, cd)
        c.location = loc
        c.rotation_euler = rot
        _move_to(c, COLL["CAM"])
        made.append(name)
    bpy.context.scene.camera = bpy.data.objects["JSN_CAM_Valley"]
    return {"cameras": made}


# ---------------------------------------------------------------- 에셋 임포트

def _bake_identity(obj, extra_scale=1.0):
    """KHS FBX는 100배 스케일이 붙어 들어온다. 트랜스폼을 메시에 굽는다."""
    from mathutils import Matrix
    mw = obj.matrix_world.copy()
    if extra_scale != 1.0:
        mw = Matrix.Scale(extra_scale, 4) @ mw
    obj.data.transform(mw)
    obj.matrix_world = Matrix.Identity(4)
    obj.data.update()


def _import_fbx_file(filepath, name, coll, extra_scale=1.0):
    if not os.path.exists(filepath):
        return {"error": "missing " + filepath}
    before = set(bpy.data.objects.keys())
    bpy.ops.import_scene.fbx(
        "EXEC_DEFAULT",
        filepath=filepath,
        use_custom_normals=True,
        use_image_search=False,
        global_scale=1.0,
        axis_forward="-Z",
        axis_up="Y",
    )
    new = [bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before]
    meshes = [o for o in new if o.type == "MESH"]
    out = []
    for i, o in enumerate(meshes):
        o.name = "%s%s" % (name, "" if i == 0 else "_%d" % i)
        o.data.name = "MD_" + o.name
        _bake_identity(o, extra_scale)
        _move_to(o, coll)
        out.append(o.name)
    for o in new:
        if o.type == "EMPTY" and not o.children:
            bpy.data.objects.remove(o, do_unlink=True)
    return out


def _wire_mat(mat, bc, nm, rn, op=None, box_tile=None):
    """머티리얼 '하나'를 배선한다.

    주의: 예전에는 이 함수가 오브젝트를 받아 모든 슬롯을 돌았다. 그러면 슬롯마다
    다른 텍스처를 계산해 넘겨도 마지막 호출이 앞의 슬롯을 전부 덮어써서,
    곰솔 수피(T_BlackPine_Bark_*)가 한 번도 쓰이지 않고 잎 텍스처가 줄기에까지
    입혀졌다. 억새/쑥의 Stem·Head도 같은 증상이었다.
    """
    if mat is not None:
        mat.use_nodes = True
        if op:
            mat.blend_method = "HASHED"
            if hasattr(mat, "shadow_method"):
                mat.shadow_method = "HASHED"
        nt = mat.node_tree
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (560, 0)
        b = nt.nodes.new("ShaderNodeBsdfPrincipled"); b.location = (280, 0)
        b.inputs["Metallic"].default_value = 0.0
        nt.links.new(b.outputs["BSDF"], out.inputs["Surface"])

        # box_tile: UV가 없는 절차적 메시(bmesh로 만든 석단 등)를 위한 삼중평면 투영.
        # UV 없이 이미지 텍스처를 연결하면 샘플이 안 돼 새까맣게 렌더된다.
        vec = None
        if box_tile:
            tc = nt.nodes.new("ShaderNodeTexCoord"); tc.location = (-900, 0)
            mp = nt.nodes.new("ShaderNodeMapping"); mp.location = (-700, 0)
            s = 1.0 / max(0.001, box_tile)
            mp.inputs["Scale"].default_value = (s, s, s)
            nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
            vec = mp.outputs["Vector"]

        def _tex(path, non_color, loc):
            n = nt.nodes.new("ShaderNodeTexImage")
            n.location = loc
            n.image = _img(path, non_color)
            if vec is not None:
                n.projection = "BOX"
                n.projection_blend = 0.4
                n.extension = "REPEAT"
                nt.links.new(vec, n.inputs["Vector"])
            return n

        if bc:
            nt.links.new(_tex(bc, False, (-320, 220)).outputs["Color"], b.inputs["Base Color"])
        if op:
            n = _tex(op, True, (-320, 20))
            if "Alpha" in b.inputs:
                nt.links.new(n.outputs["Color"], b.inputs["Alpha"])
        if nm:
            n = _tex(nm, True, (-320, -200))
            nmap = nt.nodes.new("ShaderNodeNormalMap"); nmap.location = (-40, -200)
            nt.links.new(n.outputs["Color"], nmap.inputs["Color"])
            nt.links.new(nmap.outputs["Normal"], b.inputs["Normal"])
        if rn:
            nt.links.new(_tex(rn, True, (-320, -420)).outputs["Color"], b.inputs["Roughness"])


ROCK_UNITS = ["A", "B", "C", "D", "E", "F"]


def import_rocks():
    """무등산 주상절리대 유닛 A~F. 텍스처 접미사는 _BC/_N/_R (건조물의 _NM/_RN 과 다름)."""
    made = {}
    for u in ROCK_UNITS:
        d = os.path.join(EXTRACT, "ROCK_Columnar" + u)
        fbx = os.path.join(d, "FBX", "SM_MDS_Unit%s.fbx" % u)
        names = _import_fbx_file(fbx, "SM_JSN_Rock%s" % u, COLL["KIT"])
        if isinstance(names, dict):
            made[u] = names
            continue
        tex = os.path.join(d, "Texture")
        bc = os.path.join(tex, "T_MDS_Unit%s_BC.png" % u)
        nm = os.path.join(tex, "T_MDS_Unit%s_N.png" % u)
        rn = os.path.join(tex, "T_MDS_Unit%s_R.png" % u)
        for n in names:
            o = bpy.data.objects[n]
            for slot in o.material_slots:      # 암반은 슬롯이 하나뿐이지만 명시적으로
                _wire_mat(slot.material, bc, nm, rn)
            o.hide_set(True)
            o.hide_render = True
        made[u] = {"objects": names, "stats": _mesh_stats(bpy.data.objects[names[0]])}
    return made


# 실제로 배치하는 것만 임포트한다. 쓰지 않는 사구 특산종(해당화·순비기·갯쇠보리)을
# 소스로만 들고 있으면 OVERDARE 매니페스트에 위반으로 계속 잡힌다
# (해당화 40,540 tris = 30k 초과). 파일은 _extracted/VEG에 그대로 보존.
VEG_KEYS = {
    "BlackPine": "SM_Black_Pine.fbx",
    "Eulalia": "SM_Eulalia.fbx",
    "Artemisia": "SM_Artemisia.fbx",
}
VEG_EXCLUDED = {
    "Lugose": "해당화 — 해안 장미",
    "Vitex": "순비기나무 — 사구 관목",
    "Anthephoroides": "갯쇠보리 — 전사구 특산 벼과",
}


def _wire_veg(key, names):
    files = os.listdir(VEG_DIR)
    linked = 0
    for n in names:
        o = bpy.data.objects[n]
        for slot in o.material_slots:
            mat = slot.material
            if mat is None:
                continue
            mn = re.sub(r"\.\d{3}$", "", mat.name)
            part = None
            for tok in ("Leaf", "Bark", "Stem", "Flower", "Head", "Branch"):
                if tok.lower() in mn.lower():
                    part = tok
                    break
            if part is None:
                # 3ds Max 슬롯 번호 규약: 7=줄기, 8=잎, 9=꽃/이삭
                part = {"7": "Stem", "8": "Leaf", "9": "Head"}.get(
                    next((c for c in mn if c in "789"), ""), "Leaf")
            stem = "T_%s_%s" % (key, part)

            def _p(ch, st=None):
                fn = "%s_%s.png" % (st or stem, ch)
                return os.path.join(VEG_DIR, fn) if fn in files else None

            if _p("BC") is None:
                for tok in ("Stem", "Bark", "Leaf", "Branch", "Head"):
                    alt = "T_%s_%s" % (key, tok)
                    if "%s_BC.png" % alt in files:
                        stem = alt
                        break
            bc = _p("BC")
            if bc is None:
                continue
            _wire_mat(mat, bc, _p("NM"), _p("RN"), _p("OP"))
            linked += 1
    return linked


def tune_pine():
    """곰솔 스캔을 적송(赤松) 대역으로 읽히게 손본다.

    KHS 카탈로그에 적송 스캔은 없다(적송/육송/소나무/Pinus 검색 0건). 교체가
    불가능하므로 대역으로 쓰되, 근경에서 적송으로 읽히는 유일한 신호인
    **수간 상부의 적갈색**을 만들어 준다. 적송은 기부가 흑갈, 상부가 적갈 박편이다.
    침엽은 해변 곰솔의 진녹이라 채도를 내린다.
    """
    src = bpy.data.objects.get("VEG_BlackPine")
    if src is None:
        return {"error": "VEG_BlackPine 없음"}
    done = {"bark": 0, "leaf": 0}
    for slot in src.material_slots:
        mat = slot.material
        if mat is None or not mat.use_nodes:
            continue
        nt = mat.node_tree
        bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            continue
        link = next((l for l in nt.links if l.to_node == bsdf
                     and l.to_socket.name == "Base Color"), None)
        if link is None:
            continue
        srcsock = link.from_socket
        # 머티리얼 이름은 3ds Max가 붙인 'Standardmaterial_7' 류라 부위 정보가 없다.
        # 실제로 연결된 텍스처 파일명으로 판별해야 한다.
        img = getattr(link.from_node, "image", None)
        tex = (img.name if img else "").lower()
        is_bark = any(t in tex for t in ("bark", "stem", "trunk"))

        if is_bark:
            # 수간 Z(오브젝트 공간)로 기부 흑갈 -> 상부 적갈 그라디언트
            tc = nt.nodes.new("ShaderNodeTexCoord"); tc.location = (-980, -640)
            sep = nt.nodes.new("ShaderNodeSeparateXYZ"); sep.location = (-800, -640)
            nt.links.new(tc.outputs["Object"], sep.inputs["Vector"])
            mr = nt.nodes.new("ShaderNodeMapRange"); mr.location = (-620, -640)
            mr.inputs["From Min"].default_value = 2.0
            mr.inputs["From Max"].default_value = 13.0
            nt.links.new(sep.outputs["Z"], mr.inputs["Value"])
            grad = nt.nodes.new("ShaderNodeMixRGB"); grad.location = (-440, -640)
            grad.blend_type = "MIX"
            grad.inputs["Color1"].default_value = (0.42, 0.33, 0.26, 1.0)  # 기부 흑갈
            grad.inputs["Color2"].default_value = (0.95, 0.52, 0.30, 1.0)  # 상부 적갈
            nt.links.new(mr.outputs["Result"], grad.inputs["Fac"])
            mul = nt.nodes.new("ShaderNodeMixRGB"); mul.location = (-240, -640)
            mul.blend_type = "MULTIPLY"
            mul.inputs["Fac"].default_value = 0.85
            nt.links.new(srcsock, mul.inputs["Color1"])
            nt.links.new(grad.outputs["Color"], mul.inputs["Color2"])
            nt.links.new(mul.outputs["Color"], bsdf.inputs["Base Color"])
            done["bark"] += 1
        else:
            # 침엽 — 채도 하향 + 명도 소폭 상승
            hs = nt.nodes.new("ShaderNodeHueSaturation"); hs.location = (-240, 380)
            hs.inputs["Saturation"].default_value = 0.84
            hs.inputs["Value"].default_value = 0.98
            nt.links.new(srcsock, hs.inputs["Color"])
            nt.links.new(hs.outputs["Color"], bsdf.inputs["Base Color"])
            done["leaf"] += 1
    return done


def import_veg():
    made = {}
    for key, fn in VEG_KEYS.items():
        names = _import_fbx_file(os.path.join(VEG_DIR, fn), "VEG_" + key, COLL["KIT"])
        if isinstance(names, dict):
            made[key] = names
            continue
        linked = _wire_veg(key, names)
        for n in names:
            o = bpy.data.objects[n]
            o.hide_set(True)
            o.hide_render = True
        made[key] = {"objects": names, "wired": linked,
                     "stats": _mesh_stats(bpy.data.objects[names[0]])}
    return made


# ---------------------------------------------------------------- 배치(스캐터)

def _h01(i, j, salt=0.0):
    """결정적 해시 [0,1). 난수 시드에 의존하지 않아 재실행이 재현된다."""
    v = math.sin(i * 127.1 + j * 311.7 + salt * 74.7) * 43758.5453
    return v - math.floor(v)


def _clear(prefix):
    n = 0
    for o in list(bpy.data.objects):
        if o.name.startswith(prefix):
            bpy.data.objects.remove(o, do_unlink=True)
            n += 1
    return n


def _instance(src, name, coll, loc, scale, rotz, tilt=0.0, tiltdir=0.0):
    inst = src.copy()
    inst.data = src.data           # 메시 공유 — 인스턴스
    inst.name = name
    inst.hide_set(False)
    inst.hide_render = False
    inst.location = loc
    inst.scale = (scale, scale, scale)
    if tilt:
        inst.rotation_euler = (tilt * math.cos(tiltdir), tilt * math.sin(tiltdir), rotz)
    else:
        inst.rotation_euler = (0.0, 0.0, rotz)
    _move_to(inst, coll)
    return inst


# 프리뷰 카메라 앞을 바위/나무가 막지 않도록 비워 둘 지점 (x, y, 반경)
CAM_KEEPOUT = [
    (11.0, -92.0, 9.0),    # JSN_CAM_Valley
    (-79.0, -58.0, 15.0),  # JSN_CAM_Ridge
    (8.0, 40.0, 9.0),      # JSN_CAM_Pass
    # 곰솔 수관이 10.5 m라 반경 8 m 배제로는 렌즈가 가지에 파묻힌다.
    # 배제 반경 >= 카메라~수간 거리 + 수관 반경(약 5 m).
    (-46.0, -40.0, 17.0),  # JSN_CAM_Ford
    (8.3, 71.0, 9.0),      # JSN_CAM_Steps
]


def _off_limits(x, y):
    """계류 수로·산길 노반·카메라 앞 — 여기엔 아무것도 심지 않는다."""
    if abs(x - stream_x(y)) < 3.0:
        return True
    if abs(x - trail_x(y)) < 2.2:
        return True
    if trib_amt(x) > 0.25 and abs(y - trib_y(x)) < 2.6:
        return True
    for cx, cy, rad in CAM_KEEPOUT:
        if (x - cx) ** 2 + (y - cy) ** 2 < rad * rad:
            return True
    return False


def talus_amt(x, y):
    """서쪽 크레스트 아래 너덜(岩屑)지대 0~1. 여기는 돌만 있고 식생이 없다."""
    if not (-104.0 < y < 96.0):
        return 0.0
    gx = math.exp(-(((x + 46.0) / 15.0) ** 2))
    return gx * (0.55 + 0.45 * math.sin(y * 0.055 + 1.1))


def pine_density(x, y):
    """소나무 밀도 0~1. 급경사·물길·능선 정상부는 낮다."""
    r = max(abs(x), abs(y))
    outer = min(1.0, max(0.0, (r - 96.0) / 26.0))
    s = _slope_at(x, y)
    # 외곽 산벽은 급경사지만 배경 숲으로 반드시 덮어야 한다.
    # 고정 컷오프 1.05를 쓰면 산벽에 나무가 한 그루도 안 붙어 회색 벽이 그대로 드러난다.
    if s > 1.05 + 1.75 * outer:
        return 0.0
    d = abs(x - stream_x(y))
    # 하천변은 활엽/관목 구역이라 소나무를 비운다
    near = 1.0 - math.exp(-((d / 13.0) ** 2))
    # 사면 중턱이 가장 빽빽
    band = math.exp(-(((d - 46.0) / 34.0) ** 2))
    # 서쪽 암반 크레스트는 나무가 못 붙는다
    crest = math.exp(-(((x + 78.0) / 17.0) ** 2))
    # 군집감 — 2옥타브. 단일 사인은 파장이 일정해 화면에서 열식 조림지로 읽힌다.
    # 긴 파장이 임분(林分)을, 짧은 파장이 그 안의 성김을 만든다.
    c1 = math.sin(x * 0.085 + 1.3) * math.cos(y * 0.071)
    c2 = math.sin(x * 0.031 - 0.6) * math.cos(y * 0.027 + 1.9)
    clump = 0.5 + 0.30 * c1 + 0.30 * c2
    base = max(0.78 * near * (0.42 + 0.58 * band), 0.98 * outer)
    base *= 1.0 - 0.92 * crest
    base *= 0.40 + 0.60 * clump
    # 급경사 감쇠는 외곽 산벽에는 적용하지 않는다
    base *= 1.0 - 0.55 * (1.0 - outer) * max(0.0, min(1.0, (s - 0.55) / 0.5))
    # 너덜지대에는 나무가 서지 못한다
    base *= 1.0 - 0.88 * talus_amt(x, y)

    # 동사면 공터 — 서쪽은 너덜이 구멍을 만들어 주지만 동쪽은 수관이 맞닿아
    # 지붕이 된다. 지붕이 되면 점유율이 50%여도 조림지로 읽힌다.
    if x > 8.0:
        for gx, gy, gr in ((46.0, -58.0, 21.0), (68.0, 24.0, 25.0), (28.0, 68.0, 17.0)):
            base *= 1.0 - 0.86 * math.exp(-(((x - gx) / gr) ** 2 + ((y - gy) / gr) ** 2))
    return max(0.0, min(1.0, base))


def scatter_pines(step=7.5, jitter=3.2):
    """곰솔(黑松) — 이 맵의 뼈대.

    **격자 + 지터로는 열식 조림지가 된다.** 지터를 키워도 위에서 보면 줄이 보인다
    (고증 메모: "지터만 있는 그리드는 위에서 보면 줄이 보인다").
    그래서 격자 셀을 **군락 씨앗**으로만 쓰고, 씨앗마다 3~8그루를 반경 안에
    뿌린다. 셀 간격을 9 m로 넓혀 군락 사이에 공터가 생기게 한다.
    키도 섞는다 — 전 주가 같은 18 m면 그것만으로 조림으로 읽힌다.
    """
    src = bpy.data.objects.get("VEG_BlackPine")
    if src is None:
        return {"error": "VEG_BlackPine 없음"}
    _clear("JSN_Pine_")
    n = 0
    clumps = 0
    steps = int(EXTENT / step)
    for i in range(steps):
        for j in range(steps):
            hx, hy = _h01(i, j, 1.0), _h01(i, j, 2.0)
            cxs = -HALF + step * (i + 0.5) + (hx - 0.5) * 2 * jitter
            cys = -HALF + step * (j + 0.5) + (hy - 0.5) * 2 * jitter
            dens = pine_density(cxs, cys)
            if _h01(i, j, 3.0) > dens:
                continue
            clumps += 1
            # 군락 규모 — 밀도가 높을수록 크게
            cnt = 3 + int(round(6.0 * dens * _h01(i, j, 6.0)))
            rad = 2.6 + 3.4 * _h01(i, j, 7.0)     # 군락은 조밀하게, 사이는 공터로
            for k in range(cnt):
                a = _h01(i * 31 + k, j, 8.0) * 6.28318
                rr = rad * math.sqrt(_h01(i * 31 + k, j, 9.0))
                x = cxs + math.cos(a) * rr
                y = cys + math.sin(a) * rr
                if abs(x) > HALF - 2 or abs(y) > HALF - 2:
                    continue
                if _off_limits(x, y):
                    continue
                # 군락 씨앗이 이미 밀도 테스트를 통과했으므로 구성원은 느슨하게
                # 건다. 씨앗과 같은 기준으로 다시 걸면 군락이 2~3그루로 쪼그라든다.
                if _h01(i * 31 + k, j, 10.0) > pine_density(x, y) * 2.0:
                    continue
                # 키 편차: 대부분 성목, 군락 가장자리에 치수(4~8 m)를 섞는다
                edge = rr / max(0.001, rad)
                if edge > 0.72 and _h01(i * 31 + k, j, 11.0) < 0.28:
                    s = 0.22 + 0.20 * _h01(i * 31 + k, j, 12.0)     # 4~7.7 m 치수
                else:
                    s = 0.55 + 0.62 * _h01(i * 31 + k, j, 4.0)      # 10~21 m 성목
                z = height_at(x, y) - 0.25 * s
                _instance(src, "JSN_Pine_%04d" % n, COLL["VEG"],
                          (x, y, z), s, math.radians(_h01(i * 31 + k, j, 5.0) * 360.0))
                n += 1
    return {"pines": n, "clumps": clumps, "tris_each": 17331, "tris_total": n * 17331}


# 이 팩의 식생은 전부 태안 신두리 '해안사구' 스캔이다. 내륙 산곡 맵에서는
# 사구 특산종을 심는 순간 화면이 해안으로 읽힌다(Grok 고증 메모 3절).
#   제외: 해당화(사구 장미) / 순비기나무(사구 관목, 보라 수상화가 근경에서 들킴)
#         / 갯쇠보리(전사구 특산 벼과 — 물가에 깔면 해안)
#   유지: 억새(내륙에도 흔함, 단 양지·안부에만) / 쑥(실루엣이 범용, 하안·길섶)
UNDERSTORY = [
    # key,        step, 배치대역(하천중심 거리 min,max), 크기범위,   salt, 수관제한
    ("Eulalia",    5.0, (12.0, 78.0), (0.95, 2.1), 11.0, 0.42),
    ("Artemisia",  4.2, (4.5, 26.0),  (0.8, 1.6),  23.0, 0.60),
]


def scatter_understory():
    _clear("JSN_Und_")
    out = {}
    for key, step, (dmin, dmax), (smin, smax), salt, canopy_max in UNDERSTORY:
        src = bpy.data.objects.get("VEG_" + key)
        if src is None:
            out[key] = "missing"
            continue
        n = 0
        steps = int(EXTENT / step)
        for i in range(steps):
            for j in range(steps):
                x = -HALF + step * (i + 0.5) + (_h01(i, j, salt) - 0.5) * step * 0.9
                y = -HALF + step * (j + 0.5) + (_h01(i, j, salt + 1) - 0.5) * step * 0.9
                if _off_limits(x, y):
                    continue
                d = abs(x - stream_x(y))
                if not (dmin <= d <= dmax):
                    continue
                if _slope_at(x, y) > 0.95:
                    continue
                # 수관 아래에는 심지 않는다. 억새는 양지 식물이라 소나무 그늘
                # 아래에 깔면 사구 초지처럼 보인다(고증 메모 3절).
                if pine_density(x, y) > canopy_max:
                    continue
                if talus_amt(x, y) > 0.30:      # 너덜은 돌만
                    continue
                # 군집 — 개체를 흩뿌리지 말고 큰 덩어리로 모은다
                cl = 0.5 + 0.5 * math.sin(x * 0.085 + salt) * math.cos(y * 0.072 + salt * 0.5)
                if _h01(i, j, salt + 2) > max(0.0, 1.25 * cl - 0.22):
                    continue
                s = smin + (smax - smin) * _h01(i, j, salt + 3)
                _instance(src, "JSN_Und_%s_%04d" % (key, n), COLL["VEG"],
                          (x, y, height_at(x, y) - 0.05), s,
                          math.radians(_h01(i, j, salt + 4) * 360.0))
                n += 1
        out[key] = n
    return out


def scatter_rocks():
    """주상절리 — 서쪽 크레스트에 직립 노두, 사면 아래에 너덜(倒石)."""
    srcs = [bpy.data.objects.get("SM_JSN_Rock" + u) for u in ROCK_UNITS]
    srcs = [s for s in srcs if s is not None]
    if not srcs:
        return {"error": "암반 소스 없음"}
    _clear("JSN_Rock_")
    n = 0

    # (1) 서쪽 능선 크레스트 직립 노두 — 이 맵의 랜드마크
    for k in range(22):
        y = -104.0 + 200.0 * k / 21.0
        x = -78.0 + (_h01(k, 7, 41.0) - 0.5) * 17.0
        if _off_limits(x, y):
            continue
        src = srcs[k % len(srcs)]
        s = 0.85 + 0.55 * _h01(k, 7, 42.0)
        z = height_at(x, y) - 1.4 * s
        _instance(src, "JSN_Rock_Crest_%02d" % k, COLL["ROCK"], (x, y, z), s,
                  math.radians(_h01(k, 7, 43.0) * 360.0),
                  tilt=math.radians(_h01(k, 7, 44.0) * 9.0),
                  tiltdir=_h01(k, 7, 45.0) * 6.283)
        n += 1

    # (2) 크레스트 아래 너덜지대 — 쓰러진 기둥이 엄폐물이 된다.
    # 하층식생을 걷어낸 만큼 돌을 늘려 '돌만 있는 사면'으로 읽히게 한다.
    for k in range(44):
        y = -98.0 + 194.0 * _h01(k, 11, 51.0)
        x = -62.0 + 32.0 * _h01(k, 11, 52.0)
        if _off_limits(x, y) or talus_amt(x, y) < 0.22:
            continue
        src = srcs[k % len(srcs)]
        s = 0.42 + 0.5 * _h01(k, 11, 53.0)
        _instance(src, "JSN_Rock_Talus_%02d" % k, COLL["ROCK"],
                  (x, y, height_at(x, y) - 0.4), s,
                  math.radians(_h01(k, 11, 54.0) * 360.0),
                  tilt=math.radians(62.0 + 28.0 * _h01(k, 11, 55.0)),
                  tiltdir=_h01(k, 11, 56.0) * 6.283)
        n += 1

    # (3) 계류 안팎의 전석(轉石)
    for k in range(14):
        y = -100.0 + 195.0 * _h01(k, 13, 61.0)
        side = 1.0 if _h01(k, 13, 62.0) > 0.5 else -1.0
        x = stream_x(y) + side * (2.4 + 5.5 * _h01(k, 13, 63.0))
        if any((x - cx) ** 2 + (y - cy) ** 2 < rad * rad for cx, cy, rad in CAM_KEEPOUT):
            continue
        src = srcs[k % len(srcs)]
        s = 0.22 + 0.22 * _h01(k, 13, 64.0)
        _instance(src, "JSN_Rock_Stream_%02d" % k, COLL["ROCK"],
                  (x, y, height_at(x, y) - 0.5), s,
                  math.radians(_h01(k, 13, 65.0) * 360.0),
                  tilt=math.radians(55.0 + 40.0 * _h01(k, 13, 66.0)),
                  tiltdir=_h01(k, 13, 67.0) * 6.283)
        n += 1
    return {"rocks": n}


def import_rock_mass():
    """무등산 주상절리 '원본'(Entire) — 유닛과 스케일이 다르다.

    실측 97.3 x 52.6 x 30.2 m / 1,797,148 tris. 서석대 절벽 전체이지 암괴가 아니다.
    통째로 세우면 이 260 m 맵의 서쪽 절반을 절벽이 먹는다. 0.10 안팎으로 줄여
    **서쪽 너덜의 큰 암괴**로만 쓴다(고증 메모 s28/s31: 동쪽·길·하안 금지).
    """
    o = bpy.data.objects.get("SM_JSN_RockMass")
    if o is None:
        fbx = os.path.join(EXTRACT, "ROCK_ColumnarMass", "FBX", "SM_MDS_Entire.fbx")
        names = _import_fbx_file(fbx, "SM_JSN_RockMass", COLL["KIT"])
        if isinstance(names, dict):
            return names
        tex = os.path.join(EXTRACT, "ROCK_ColumnarMass", "Texture")
        for n in names:
            ob = bpy.data.objects[n]
            for slot in ob.material_slots:
                _wire_mat(slot.material,
                          os.path.join(tex, "T_MDS_Entire_BC.png"),
                          os.path.join(tex, "T_MDS_Entire_N.png"),
                          os.path.join(tex, "T_MDS_Entire_R.png"))
            ob.hide_set(True)
            ob.hide_render = True
        o = bpy.data.objects[names[0]]
    return {"object": o.name, "stats": _mesh_stats(o)}


def place_rock_mass():
    """너덜 안에 큰 암괴 3개. 지류·길·하안을 막지 않는 자리만."""
    src = bpy.data.objects.get("SM_JSN_RockMass")
    if src is None:
        return {"error": "SM_JSN_RockMass 없음 — import_rock_mass() 먼저"}
    _clear("JSN_Mass_")
    # (x, y, scale, tilt_deg, yaw_deg) — 전부 너덜 대역(x -62~-32) 안
    spots = [
        (-52.0, -70.0, 0.115, 26.0, 34.0),
        (-44.0, 18.0, 0.098, 18.0, 148.0),
        # (-57, 58)은 talus_amt 0.08로 너덜 밖이라 거부됐다. 너덜 강도는
        # y≈8.6에서 최대, y≈-48에서 최소(주기 114 m)이므로 남쪽 강대역으로 옮긴다.
        (-38.0, -88.0, 0.128, 33.0, 261.0),
    ]
    made = []
    for k, (x, y, s, tilt, yaw) in enumerate(spots):
        if talus_amt(x, y) < 0.2:
            continue
        if trib_amt(x) > 0.2 and abs(y - trib_y(x)) < 14.0:
            continue                      # 지류를 막지 않는다
        inst = src.copy()
        inst.data = src.data
        inst.name = "JSN_Mass_%02d" % k
        inst.hide_set(False)
        inst.hide_render = False
        # min_z -4.0 x s 만큼 이미 아래로 나오므로 추가로 조금만 묻는다
        inst.location = (x, y, height_at(x, y) - 1.6 * s * 10.0 * 0.12)
        inst.scale = (s, s, s)
        inst.rotation_euler = (math.radians(tilt), math.radians(tilt * 0.35),
                               math.radians(yaw))
        _move_to(inst, COLL["ROCK"])
        made.append(inst.name)
    return {"masses": made}


def _pebble_mesh():
    """저폴리 자갈 원본 1개. 주상절리 유닛(118k~311k tris)을 축소해 쓰면
    자갈 하나에 30만 삼각형이 붙는다."""
    me = bpy.data.meshes.get("MD_JSN_Pebble")
    if me is not None:
        return me
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=1, radius=0.5)
    for k, v in enumerate(bm.verts):
        v.co.x *= 0.72 + 0.55 * _h01(k, 1, 81.0)
        v.co.y *= 0.72 + 0.55 * _h01(k, 2, 82.0)
        v.co.z *= 0.34 + 0.34 * _h01(k, 3, 83.0)          # 납작하게 — 구르다 앉은 돌
    me = bpy.data.meshes.new("MD_JSN_Pebble")
    bm.to_mesh(me); bm.free()
    for p in me.polygons:
        p.use_smooth = False
    rockdir = os.path.join(EXTRACT, "ROCK_ColumnarA", "Texture")
    mat = bpy.data.materials.get("M_JSN_Pebble") or bpy.data.materials.new("M_JSN_Pebble")
    _wire_mat(mat,
              os.path.join(rockdir, "T_MDS_UnitA_BC.png"),
              os.path.join(rockdir, "T_MDS_UnitA_N.png"),
              os.path.join(rockdir, "T_MDS_UnitA_R.png"),
              box_tile=0.45)
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    lk = next((l for l in nt.links if l.to_node == bsdf and l.to_socket.name == "Base Color"), None)
    if lk:
        src = lk.from_socket
        sc = nt.nodes.new("ShaderNodeMixRGB"); sc.location = (-60, 220)
        sc.blend_type = "SCREEN"; sc.inputs["Fac"].default_value = 0.10
        sc.inputs["Color2"].default_value = (0.60, 0.58, 0.52, 1.0)
        nt.links.new(src, sc.inputs["Color1"])
        nt.links.new(sc.outputs["Color"], bsdf.inputs["Base Color"])
    me.materials.append(mat)
    return me


def scatter_pebbles():
    """돌부스러기 — 길섶·물가·석단 주변 2 m 안에만.

    발밑 디테일은 텍스처만으로 안 된다. 실제 요철이 하나도 없으면 근경이
    '칠한 면'으로 남는다. 다만 숲 전체에 깔면 자갈밭이 되므로 사람과 물이
    지나는 곳에만 둔다(고증 메모 s28: "길·석단·물가 2 m만").
    """
    _clear("JSN_Peb_")
    me = _pebble_mesh()
    src = bpy.data.objects.get("JSN_PebbleSrc")
    if src is None:
        src = bpy.data.objects.new("JSN_PebbleSrc", me)
        _move_to(src, COLL["KIT"])
    src.hide_set(True)
    src.hide_render = True

    n = 0
    zones = []
    # 길섶 — 노면 바로 옆에 굴러 나온 돌
    for k in range(260):
        y = -104.0 + 200.0 * _h01(k, 21, 91.0)
        side = 1.0 if _h01(k, 21, 92.0) > 0.5 else -1.0
        off = side * (0.6 + 3.6 * _h01(k, 21, 93.0) ** 1.7)
        zones.append((trail_x(y) + off, y, 0.12 + 0.16 * _h01(k, 21, 94.0)))
    # 물가 자갈 — 계류 양안
    for k in range(300):
        y = STREAM_S + (STREAM_N - STREAM_S) * _h01(k, 23, 95.0)
        side = 1.0 if _h01(k, 23, 96.0) > 0.5 else -1.0
        off = side * (1.5 + 5.0 * _h01(k, 23, 97.0) ** 1.8)
        zones.append((stream_x(y) + off, y, 0.14 + 0.22 * _h01(k, 23, 98.0)))
    # 지류 물가
    for k in range(120):
        x = TRIB_X0 + (TRIB_X1 - TRIB_X0) * _h01(k, 27, 99.0)
        side = 1.0 if _h01(k, 27, 100.0) > 0.5 else -1.0
        off = side * (1.3 + 4.0 * _h01(k, 27, 101.0) ** 1.7)
        zones.append((x, trib_y(x) + off, 0.12 + 0.18 * _h01(k, 27, 102.0)))
    # 석단 주변 — 6.6 m 구간에 70개는 눈높이에서 자갈밭이 된다(walk_07에서 확인).
    for k in range(26):
        y = STEPS_Y0 - 1.5 + (STEPS_Y1 - STEPS_Y0 + 3.0) * _h01(k, 29, 103.0)
        side = 1.0 if _h01(k, 29, 104.0) > 0.5 else -1.0
        off = side * (0.7 + 2.4 * _h01(k, 29, 105.0) ** 1.6)
        zones.append((trail_x(y) + off, y, 0.11 + 0.15 * _h01(k, 29, 106.0)))

    for k, (x, y, s) in enumerate(zones):
        if abs(x) > HALF - 3 or abs(y) > HALF - 3:
            continue
        # 물속·노면 한가운데는 비운다
        if abs(x - stream_x(y)) < 1.1 or abs(x - trail_x(y)) < 0.45:
            continue
        # 메시는 z로 0.34~0.68배 납작하므로 반높이가 s*0.17~0.34다.
        # 매몰량을 s*0.34로 빼면 돌 상단이 지면 아래로 내려가 완전히 사라진다.
        z = height_at(x, y) - s * 0.098   # Grok s31: 매몰 30~40% 증량
        inst = src.copy()
        inst.data = me
        inst.name = "JSN_Peb_%04d" % n
        inst.hide_set(False)
        inst.hide_render = False
        inst.location = (x, y, z)
        inst.scale = (s, s, s)
        inst.rotation_euler = (math.radians(_h01(k, 31, 107.0) * 22.0),
                               math.radians(_h01(k, 31, 108.0) * 22.0),
                               math.radians(_h01(k, 31, 109.0) * 360.0))
        _move_to(inst, COLL["ROCK"])
        n += 1
    return {"pebbles": n, "tris_each": len(me.polygons) * 2}


def stage2():
    import_rocks()
    import_veg()
    tune_pine()
    r = scatter_rocks()
    p = scatter_pines()
    u = scatter_understory()
    pb = scatter_pebbles()
    import_rock_mass()
    mm = place_rock_mass()
    return {"rocks": r, "pines": p, "understory": u, "pebbles": pb, "mass": mm}


def scene_report():
    tot = 0
    per = {}
    dg = bpy.context.evaluated_depsgraph_get()
    for o in bpy.data.objects:
        if o.type != "MESH" or o.hide_render:
            continue
        t = len(o.data.loop_triangles) or sum(max(0, len(p.vertices) - 2) for p in o.data.polygons)
        if not o.data.loop_triangles:
            o.data.calc_loop_triangles()
            t = len(o.data.loop_triangles)
        tot += t
        c = o.users_collection[0].name if o.users_collection else "?"
        d = per.setdefault(c, {"objs": 0, "tris": 0})
        d["objs"] += 1
        d["tris"] += t
    return {"total_tris": tot, "by_collection": per,
            "objects": len(bpy.data.objects), "materials": len(bpy.data.materials)}


# ---------------------------------------------------------------- 보행성 감사

# 판정 기준 (FPS 표준 관례)
WALK_DEG = 40.0      # 이하: 정상 보행
SCRAMBLE_DEG = 55.0  # 이하: 기어오름 가능(느림)  / 초과: 통행 불가
PLAY_HALF = 105.0    # 플레이 가능 범위 반경(외곽 산벽 안쪽)
CELL = 1.5


def _rock_blockers():
    """배치된 암반의 XY 원기둥 근사. 바위는 넘어갈 수 없는 장애물이다."""
    out = []
    dg = bpy.context.evaluated_depsgraph_get()
    for o in bpy.data.objects:
        if not o.name.startswith("JSN_Rock_") or o.hide_render:
            continue
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        if not me.vertices:
            ev.to_mesh_clear()
            continue
        mw = o.matrix_world
        xs, ys, zs = [], [], []
        for v in me.vertices:
            c = mw @ v.co
            xs.append(c.x); ys.append(c.y); zs.append(c.z)
        ev.to_mesh_clear()
        cx, cy = (min(xs) + max(xs)) * 0.5, (min(ys) + max(ys)) * 0.5
        # 높이 1.2 m 미만이면 뛰어넘을 수 있다고 보고 장애물에서 제외
        if (max(zs) - min(zs)) < 1.2:
            continue
        rad = 0.5 * max(max(xs) - min(xs), max(ys) - min(ys)) * 0.8
        out.append((cx, cy, rad))
    return out


def walkability():
    """경사도로 통행 가능 구역을 만들고 연결성분을 라벨링한다.

    게임 맵이므로 '보기 좋은가'와 별개로 '다닐 수 있는가'를 반드시 검증해야 한다.
    코드는 0=불가, 1=기어오름, 2=보행.
    """
    import collections
    n = int(2 * PLAY_HALF / CELL) + 1
    walk_t = math.tan(math.radians(WALK_DEG))
    scr_t = math.tan(math.radians(SCRAMBLE_DEG))
    rocks = _rock_blockers()

    grid = [[0] * n for _ in range(n)]
    hist = {"walk": 0, "scramble": 0, "blocked_slope": 0, "blocked_rock": 0}
    # 경사 분포 — 지형이 실제로 이동을 제약하는지 정량화한다
    bands = [0] * 9   # 0-10, 10-20, ... 70-80, 80+
    slope_samples = 0
    for j in range(n):
        y = -PLAY_HALF + j * CELL
        for i in range(n):
            x = -PLAY_HALF + i * CELL
            blocked_by_rock = False
            for cx, cy, rad in rocks:
                if (x - cx) ** 2 + (y - cy) ** 2 < rad * rad:
                    blocked_by_rock = True
                    break
            if blocked_by_rock:
                hist["blocked_rock"] += 1
                continue
            s = _slope_at(x, y, e=CELL)
            deg = math.degrees(math.atan(s))
            bands[min(8, int(deg // 10))] += 1
            slope_samples += 1
            if s <= walk_t:
                grid[j][i] = 2; hist["walk"] += 1
            elif s <= scr_t:
                grid[j][i] = 1; hist["scramble"] += 1
            else:
                hist["blocked_slope"] += 1

    # 4-이웃 연결성분 (보행+기어오름을 통행 가능으로 본다)
    label = [[-1] * n for _ in range(n)]
    comps = []
    for j0 in range(n):
        for i0 in range(n):
            if grid[j0][i0] == 0 or label[j0][i0] != -1:
                continue
            cid = len(comps)
            q = collections.deque([(i0, j0)])
            label[j0][i0] = cid
            cnt = 0
            while q:
                i, j = q.popleft()
                cnt += 1
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ii, jj = i + di, j + dj
                    if 0 <= ii < n and 0 <= jj < n and grid[jj][ii] and label[jj][ii] == -1:
                        label[jj][ii] = cid
                        q.append((ii, jj))
            comps.append(cnt)

    def cell_of(x, y):
        return (int(round((x + PLAY_HALF) / CELL)), int(round((y + PLAY_HALF) / CELL)))

    KEY = {
        "남쪽 진입로": (stream_x(-95.0) + 12.0, -95.0),
        "북쪽 고갯길 안부": (trail_x(96.0), 96.0),
        "석단 상단": (trail_x(81.0), 81.0),
        "서쪽 암반 능선": (-78.0, -40.0),
        "동쪽 소나무 능선": (86.0, 0.0),
        "지류 도섭 지점": (-26.0, trib_y(-26.0)),
        "너덜지대": (-46.0, 20.0),
        "계류 건널목": (stream_x(-46.0), -46.0),
    }
    keys = {}
    for name, (x, y) in KEY.items():
        i, j = cell_of(x, y)
        ok = 0 <= i < n and 0 <= j < n
        code = grid[j][i] if ok else 0
        comp = label[j][i] if ok else -1
        snap = 0.0
        # 표본점이 바위 안에 떨어질 수 있다. 그건 지형 결함이 아니라 표본 오차이므로
        # 가장 가까운 통행 가능 셀로 스냅하고 그 거리를 함께 보고한다.
        if code == 0 and ok:
            best = None
            for rr in range(1, 9):
                for dj in range(-rr, rr + 1):
                    for di in range(-rr, rr + 1):
                        if max(abs(di), abs(dj)) != rr:
                            continue
                        ii, jj = i + di, j + dj
                        if 0 <= ii < n and 0 <= jj < n and grid[jj][ii]:
                            dist = math.hypot(di, dj) * CELL
                            if best is None or dist < best[0]:
                                best = (dist, ii, jj)
                if best:
                    break
            if best:
                snap, i, j = best[0], best[1], best[2]
                code, comp = grid[j][i], label[j][i]
        keys[name] = {
            "xy": [round(x, 1), round(y, 1)],
            "code": code,
            "component": comp,
            "snapped_m": round(snap, 1),
            "slope_deg": round(math.degrees(math.atan(_slope_at(x, y, e=CELL))), 1),
        }

    total = n * n
    biggest = max(range(len(comps)), key=lambda c: comps[c]) if comps else None
    isolated = [k for k, v in keys.items() if v["component"] != biggest]
    unreachable = [k for k, v in keys.items() if v["code"] == 0]

    data = {
        "criteria": {"walk_deg": WALK_DEG, "scramble_deg": SCRAMBLE_DEG,
                     "cell_m": CELL, "play_half_m": PLAY_HALF},
        "grid_n": n,
        "rock_blockers": len(rocks),
        "coverage_pct": {k: round(100.0 * v / total, 1) for k, v in hist.items()},
        "slope_bands_pct": {"%d-%d도" % (b * 10, b * 10 + 10): round(100.0 * bands[b] / max(1, slope_samples), 1)
                            for b in range(9)},
        "components": {"count": len(comps),
                       "largest_cells": comps[biggest] if biggest is not None else 0,
                       "largest_pct": round(100.0 * comps[biggest] / total, 1) if biggest is not None else 0.0,
                       "sizes_top5": sorted(comps, reverse=True)[:5]},
        "key_points": keys,
        "isolated_key_points": isolated,
        "unreachable_key_points": unreachable,
        "verdict": "PASS" if not isolated and not unreachable else "FAIL",
    }
    out = os.path.join(ROOT, "05_Documentation", "walkability.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    # 히트맵 생성을 위해 원시 격자도 남긴다
    raw = os.path.join(ROOT, "05_Documentation", "walkability_grid.json")
    with open(raw, "w", encoding="utf-8") as f:
        json.dump({"n": n, "cell": CELL, "half": PLAY_HALF,
                   "grid": grid, "label": label, "largest": biggest}, f)
    return data


def export_manifest():
    """Codex QA(validate_delivery.py --overdare)가 대조할 씬 명세.

    인스턴스가 많으므로 유니크 메시 기준과 오브젝트 기준을 함께 낸다.
    OVERDARE 규칙: 30k tris/메시, <=200 메시/FBX, 텍스처 1장/메시.
    """
    meshes = {}
    objs = []
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        me = o.data
        if not me.loop_triangles:
            me.calc_loop_triangles()
        tris = len(me.loop_triangles)
        mats = [m.name for m in me.materials if m]
        if me.name not in meshes:
            imgs = set()
            for mn in mats:
                mt = bpy.data.materials.get(mn)
                if mt and mt.use_nodes:
                    for n in mt.node_tree.nodes:
                        if n.type == "TEX_IMAGE" and n.image:
                            imgs.add(n.image.name)
            meshes[me.name] = {
                "mesh": me.name, "tris": tris, "materials": mats,
                "textures": sorted(imgs), "users": 0,
            }
        meshes[me.name]["users"] += 1
        objs.append({
            "object": o.name,
            "collection": o.users_collection[0].name if o.users_collection else None,
            "mesh": me.name,
            "hidden_render": bool(o.hide_render),
        })

    rules = {"max_tris_per_mesh": 30000, "max_meshes_per_fbx": 200, "max_textures_per_mesh": 1}
    violations = []
    for md in meshes.values():
        if md["tris"] > rules["max_tris_per_mesh"]:
            violations.append({"mesh": md["mesh"], "rule": "max_tris_per_mesh",
                               "value": md["tris"], "limit": rules["max_tris_per_mesh"]})
        if len(md["textures"]) > rules["max_textures_per_mesh"]:
            violations.append({"mesh": md["mesh"], "rule": "max_textures_per_mesh",
                               "value": len(md["textures"]), "limit": rules["max_textures_per_mesh"]})

    per_coll = {}
    for od in objs:
        if od["hidden_render"]:
            continue
        d = per_coll.setdefault(od["collection"], {"objects": 0, "tris": 0})
        d["objects"] += 1
        d["tris"] += meshes[od["mesh"]]["tris"]

    data = {
        "project": "JSN_Sangok",
        "blender": bpy.app.version_string,
        "note": "감량 미착수 — 위반 목록은 감량 착수 시점의 기준선(baseline)",
        "rules": rules,
        "world": {"extent_m": EXTENT, "grid_segments": SEGS},
        "summary": {
            "objects": len(objs),
            "unique_meshes": len(meshes),
            "total_tris_rendered": sum(v["tris"] for v in per_coll.values()),
            "materials": len(bpy.data.materials),
            "images": len(bpy.data.images),
            "packed_images": sum(1 for i in bpy.data.images if i.packed_file),
        },
        "by_collection": per_coll,
        "unique_meshes": sorted(meshes.values(), key=lambda d: -d["tris"]),
        "violations": violations,
        "objects": objs,
    }
    out = os.path.join(ROOT, "05_Documentation", "scene_manifest.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return {"manifest": out, "unique_meshes": len(meshes), "violations": len(violations)}


def save():
    os.makedirs(os.path.dirname(MASTER), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=MASTER)
    return {"saved": MASTER, "mb": round(os.path.getsize(MASTER) / 1048576, 1)}


def walkthrough(tag="walk", res=(1100, 620)):
    """산길을 따라 눈높이(1.7 m)로 훑는다.

    지금까지의 프리뷰는 부감이 많아 '지도'는 보여줬지만 플레이어가 실제로 무엇을
    보는지는 못 보여줬다. 리뷰 판단에 필요한 건 이쪽이다.
    """
    # 78은 석단(y 76~79.6) 위에 서게 돼 정작 석단이 발밑에 가린다. 71로 앞당긴다.
    pts = [-92.0, -70.0, -46.0, -20.0, 4.0, 30.0, 56.0, 71.0, 88.0]
    out = os.path.join(ROOT, "04_Previews")
    os.makedirs(out, exist_ok=True)
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    made = []
    for k, y in enumerate(pts):
        nx = pts[min(k + 1, len(pts) - 1)]
        if k == len(pts) - 1:
            nx = y + 8.0
        x0, x1 = trail_x(y), trail_x(nx)
        dx, dy = x1 - x0, nx - y
        yaw = math.atan2(dy, dx) - math.pi / 2.0     # 카메라 기본이 +Y를 보므로 보정
        # 다음 지점과의 표고차로 시선 상하각을 맞춘다
        z0 = height_at(x0, y) + 1.7
        z1 = height_at(x1, nx) + 1.7
        # 표고차가 크면 시선이 땅바닥이나 하늘로 꽂힌다. 수평 +-12도로 제한.
        rise = math.atan2(z1 - z0, math.hypot(dx, dy))
        rise = max(-math.radians(12.0), min(math.radians(12.0), rise))
        pitch = math.pi / 2.0 - rise
        name = "JSN_CAM_Walk%02d" % k
        old = bpy.data.objects.get(name)
        if old:
            bpy.data.objects.remove(old, do_unlink=True)
        cd = bpy.data.cameras.new("CD_" + name)
        cd.lens = 24.0                                # FPS에 가까운 화각
        cd.clip_end = 2000.0
        c = bpy.data.objects.new(name, cd)
        c.location = (x0, y, z0)
        c.rotation_euler = (pitch, 0.0, yaw)
        _move_to(c, COLL["CAM"])
        sc.camera = c
        sc.render.filepath = os.path.join(out, "%s_%02d_y%+04d.png" % (tag, k, int(y)))
        bpy.ops.render.render(write_still=True)
        made.append(os.path.basename(sc.render.filepath))
    return {"shots": made}


def render(cams=("Survey", "Valley", "Ridge"), tag="s1", res=(1100, 620)):
    out = os.path.join(ROOT, "04_Previews")
    os.makedirs(out, exist_ok=True)
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    made = []
    for c in cams:
        name = "JSN_CAM_" + c
        if name not in bpy.data.objects:
            continue
        sc.camera = bpy.data.objects[name]
        sc.render.filepath = os.path.join(out, "%s_%s.png" % (tag, c))
        bpy.ops.render.render(write_still=True)
        made.append(sc.render.filepath)
    return made


def stage1():
    boot()
    t = make_terrain()
    w = make_water()
    tw = make_trib_water()
    st = make_steps()
    make_lighting()
    make_cameras()
    return {"terrain": t, "water": w, "trib_water": tw, "steps": st}
