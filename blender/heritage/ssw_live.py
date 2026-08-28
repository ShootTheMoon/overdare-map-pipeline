# -*- coding: utf-8 -*-
"""SSW Soswaewon 300m garden. MCP calls functions; heavy FBX goes through timers."""
import json
import math
import os
import re
import time

import bpy
import bmesh
from mathutils import Matrix, Vector, Euler

HERE = os.path.dirname(os.path.abspath(__file__))
LAYOUT = json.load(open(os.path.join(HERE, "ssw_layout.json"), encoding="utf-8"))
ROOT = LAYOUT["root"]
SCALE_JSON = os.path.join(HERE, "ssw_scale.json")
MASTER = os.path.join(ROOT, "50_ASSEMBLY", "SSW_Master.blend")
DNS = bpy.app.driver_namespace


def _state():
    st = DNS.get("SSW_STATE")
    if st is None:
        st = {"queue": [], "job": None, "state": "idle", "last": None, "log": [], "t0": None}
        DNS["SSW_STATE"] = st
    return st


def _log(msg):
    st = _state()
    st["log"].append(msg)
    print("[SSW]", msg)


def status():
    st = _state()
    out = {"state": st["state"], "job": st["job"], "queued": len(st["queue"])}
    if st["t0"] and st["state"] == "running":
        out["elapsed"] = round(time.time() - st["t0"], 1)
    if st["last"]:
        out["last"] = st["last"]
    if st["log"]:
        out["log"] = st["log"][-8:]
    return out


def asset(key):
    for a in LAYOUT["assets"]:
        if a["key"] == key:
            return a
    raise KeyError(key)


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
    xs = [c.x for c in co]
    ys = [c.y for c in co]
    zs = [c.z for c in co]
    me.calc_loop_triangles()
    out = {
        "name": obj.name,
        "verts": len(me.vertices),
        "tris": len(me.loop_triangles),
        "dims": [round(max(xs) - min(xs), 3),
                 round(max(ys) - min(ys), 3),
                 round(max(zs) - min(zs), 3)],
        "min": [round(min(xs), 3), round(min(ys), 3), round(min(zs), 3)],
        "max": [round(max(xs), 3), round(max(ys), 3), round(max(zs), 3)],
        "min_z": round(min(zs), 3),
        "materials": [m.name if m else None for m in obj.data.materials],
    }
    ev.to_mesh_clear()
    return out


def stream_x(y):
    """Meander. Zero at the south gate (y=-38) so water exits the wall gap."""
    t = y + 38.0
    return 3.25 * math.sin(t * 0.058) + 1.2 * math.sin(t * 0.135 + 0.4)


def height_at(x, y):
    """Hills + meander trench + micro-relief + soft outer roll-off."""
    yn = max(0.0, min(1.0, (y + 20.0) / 140.0))
    hill_n = 8.0 * yn * yn
    edge = max(0.0, (abs(x) - 55.0) / 95.0)
    hill_side = 12.0 * edge * edge
    dx = x - stream_x(y)
    sw = 2.15 + 0.95 * math.sin(y * 0.11) + 0.4 * math.sin(y * 0.27 + 0.8)
    stream_w = math.exp(-(dx / max(1.2, sw)) ** 2)
    stream_len = 1.0 if -56.0 < y < 22.0 else max(0.0, 1.0 - (min(abs(y + 56.0), abs(y - 22.0))) / 16.0)
    stream = -0.48 * stream_w * stream_len
    n = 0.55 * math.sin(x * 0.07) * math.cos(y * 0.05)
    n += 0.28 * math.sin(x * 0.13 + y * 0.09)
    n += 0.16 * math.sin(x * 0.33 + y * 0.21) * math.cos(x * 0.19)
    # soft drop so the 300 m plate is not a knife edge
    r = max(abs(x), abs(y))
    if r > 128.0:
        t = min(1.0, (r - 128.0) / 22.0)
        n -= 2.8 * t * t
    return hill_n + hill_side + stream + n


# ---------------------------------------------------------------- setup


def boot():
    p = bpy.context.preferences
    p.edit.undo_steps = 4
    p.edit.undo_memory_limit = 64
    sc = bpy.context.scene
    sc.unit_settings.system = "METRIC"
    sc.unit_settings.length_unit = "METERS"
    sc.render.engine = "BLENDER_EEVEE_NEXT" if hasattr(bpy.types, "EEVEE_NEXT") else sc.render.engine
    try:
        sc.render.engine = "BLENDER_EEVEE_NEXT"
    except Exception:
        try:
            sc.render.engine = "BLENDER_EEVEE"
        except Exception:
            pass
    sc.render.resolution_x = 1920
    sc.render.resolution_y = 1080
    n = 0
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type != "VIEW_3D":
                continue
            for sp in area.spaces:
                if sp.type != "VIEW_3D":
                    continue
                sp.shading.type = "MATERIAL"
                sp.clip_start = 0.1
                sp.clip_end = 2000.0
                n += 1
    _log("boot viewports=%d" % n)
    return {"ok": True, "viewports": n}


def clean_default():
    killed = []
    for name in ("Cube", "Light", "Camera"):
        o = bpy.data.objects.get(name)
        if o is not None:
            bpy.data.objects.remove(o, do_unlink=True)
            killed.append(name)
    _log("clean_default %s" % killed)
    return {"removed": killed}


def make_collections():
    made = []
    for name in LAYOUT["collections"]:
        if name not in bpy.data.collections:
            made.append(name)
        _coll(name)
    for name in LAYOUT["collections_no_render"]:
        c = bpy.data.collections.get(name)
        if c:
            c.hide_render = True
    return {"created": made}


def _mesh_obj(name, bm, coll, mat=None):
    me = bpy.data.meshes.new("MD_" + name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    _move_to(ob, coll)
    if mat:
        me.materials.append(mat)
    return ob


def _mat_rgb(name, color, rough=0.85, spec=0.2):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = 0.0
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = spec
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def make_guides():
    e = LAYOUT["world"]["extent"] * 0.5
    mat = _mat_rgb("M_SSW_Guide", (0.9, 0.75, 0.15), 0.6)
    bm = bmesh.new()
    verts = [
        bm.verts.new((x, y, 0.15))
        for x, y in [(-e, -e), (e, -e), (e, e), (-e, e)]
    ]
    bm.verts.ensure_lookup_table()
    for i in range(4):
        bm.edges.new((verts[i], verts[(i + 1) % 4]))
    sq = _mesh_obj("GUIDE_300M_SQUARE", bm, "SSW_GUIDES", mat)

    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=8, radius=0.6)
    origin = _mesh_obj("GUIDE_ORIGIN", bm, "SSW_GUIDES", mat)

    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=0.4, radius2=0.05, depth=4.0)
    north = _mesh_obj("GUIDE_NORTH", bm, "SSW_GUIDES", mat)
    north.location = (0.0, 8.0, 2.0)
    north.rotation_euler = (math.radians(-90), 0, 0)

    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x *= 0.45
        v.co.y *= 0.35
        v.co.z *= 1.8
        v.co.z += 0.9
    player = _mesh_obj("GUIDE_PLAYER_180CM", bm, "SSW_GUIDES", mat)
    player.location = (0.0, -55.0, 0.0)
    return {"guides": [sq.name, origin.name, north.name, player.name]}


def make_terrain():
    size = LAYOUT["world"]["extent"]
    segs = 192
    mat_g = _mat_rgb("M_SSW_Grass", (0.22, 0.32, 0.14), 0.92)
    mat_d = _mat_rgb("M_SSW_Dirt", (0.28, 0.22, 0.14), 0.95)
    mat_s = _mat_rgb("M_SSW_Streambed", (0.18, 0.16, 0.12), 0.7)

    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=segs, y_segments=segs, size=size * 0.5)
    for v in bm.verts:
        v.co.z = height_at(v.co.x, v.co.y)
    # shade smooth later
    terr = _mesh_obj("SSW_Terrain", bm, "SSW_TERRAIN", mat_g)
    terr.data.materials.append(mat_d)
    terr.data.materials.append(mat_s)
    for p in terr.data.polygons:
        p.use_smooth = True
    terr.data.update()

    # water strip
    mat_w = _mat_rgb("M_SSW_Water", (0.12, 0.22, 0.28), 0.08, spec=0.5)
    if "Transmission Weight" in mat_w.node_tree.nodes["Principled BSDF"].inputs:
        mat_w.node_tree.nodes["Principled BSDF"].inputs["Transmission Weight"].default_value = 0.65
        mat_w.node_tree.nodes["Principled BSDF"].inputs["IOR"].default_value = 1.333
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=8, y_segments=48, size=1.0)
    for v in bm.verts:
        v.co.x *= 3.2
        v.co.y *= 80.0
        v.co.z = 0.06
    water = _mesh_obj("SSW_StreamWater", bm, "SSW_WATER", mat_w)
    for p in water.data.polygons:
        p.use_smooth = True

    # dirt path east of stream
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=4, y_segments=40, size=1.0)
    for v in bm.verts:
        v.co.x = 7.0 + v.co.x * 1.6
        v.co.y *= 55.0
        v.co.z = height_at(v.co.x, v.co.y) + 0.04
    path = _mesh_obj("SSW_DirtPath", bm, "SSW_TERRAIN", mat_d)

    st = _mesh_stats(terr)
    return {"terrain": st, "water": water.name, "path": path.name}


CDG_TEX = r"C:\Work\blender\CDG_Changdeokgung\_extracted\_TexLib"
YMR_SAND = os.path.join(ROOT, "_extracted", "Sand")
PADDY_JPG = os.path.join(
    ROOT, "_extracted", "TerracedPaddy", "남해 가천마을 다랑이 논", "M_TerracedPaddy.jpg"
)


def _pbr_set(nt, prefix, bc, nm, rn, loc_x):
    """Image nodes for one PBR set. Returns (color, normal, rough) sockets."""
    n_bc = nt.nodes.new("ShaderNodeTexImage")
    n_bc.location = (loc_x, 220)
    n_bc.image = _img(bc, False)
    n_bc.label = prefix + "_BC"
    n_nm = nt.nodes.new("ShaderNodeTexImage")
    n_nm.location = (loc_x, 0)
    n_nm.image = _img(nm, True)
    n_nm.label = prefix + "_NM"
    n_rn = nt.nodes.new("ShaderNodeTexImage")
    n_rn.location = (loc_x, -220)
    n_rn.image = _img(rn, True)
    n_rn.label = prefix + "_RN"
    return n_bc.outputs["Color"], n_nm.outputs["Color"], n_rn.outputs["Color"], (n_bc, n_nm, n_rn)


def _mix(nt, loc, fac, a, b, label=""):
    n = nt.nodes.new("ShaderNodeMix")
    n.data_type = "RGBA"
    n.location = loc
    n.label = label
    try:
        nt.links.new(fac, n.inputs["Factor"])
    except Exception:
        nt.links.new(fac, n.inputs[0])
    # Blender 4/5 Mix RGBA sockets
    for key_a, key_b in (("A", "B"), ("Color1", "Color2")):
        if key_a in n.inputs and key_b in n.inputs:
            nt.links.new(a, n.inputs[key_a])
            nt.links.new(b, n.inputs[key_b])
            break
    else:
        nt.links.new(a, n.inputs[6])
        nt.links.new(b, n.inputs[7])
    return n.outputs["Result"] if "Result" in n.outputs else n.outputs[2]


def _blend_at(x, y):
    """R=packed earth (pads/path), B=wet stream. Court is mostly grass."""
    sx = stream_x(y)
    dx = x - sx
    stream_len = 1.0 if -54.0 < y < 18.0 else max(0.0, 1.0 - min(abs(y + 54.0), abs(y - 18.0)) / 14.0)
    bank = 2.4 + 0.85 * math.sin(y * 0.19 + 1.1) + 0.35 * math.sin(y * 0.41)
    stream = math.exp(-(dx / bank) ** 2) * stream_len
    path_len = 1.0 if -48.0 < y < 50.0 else 0.0
    px = sx + 3.6 + 1.1 * math.sin(y * 0.19 + 0.6)
    pw = 1.05 + 0.55 * math.sin(y * 0.15) + 0.25 * math.sin(y * 0.37)
    path = math.exp(-((x - px) / pw) ** 2) * path_len
    if math.sin(y * 0.43) * math.cos(x * 0.31) < -0.5:
        path *= 0.15
    # building pads (dirt only near structures, not a full rectangle)
    pads = (
        (6.8, 8.0, 7.5),    # 광풍각
        (0.0, 48.0, 7.0),   # 제월당
        (-20.0, 20.0, 4.5), # 초정
        (18.0, 40.0, 4.5),  # 대봉대
        (0.0, -35.0, 3.5),  # 오곡문
        (-18.0, -28.0, 3.0),
        (-12.0, -10.0, 1.15),
    )
    pad = 0.0
    for px, py, rad in pads:
        d2 = (x - px) ** 2 + (y - py) ** 2
        pad = max(pad, math.exp(-d2 / (rad * rad)))
    # faint worn earth, noisy, not a box
    inside = abs(x) < 21.0 and -35.0 < y < 54.0
    wear = 0.0
    if inside:
        wear = 0.22 * (0.55 + 0.45 * math.sin(x * 0.19 + 0.4) * math.cos(y * 0.14))
        wear *= max(0.0, 1.0 - stream * 1.5)
    r = max(wear, path * 0.52, pad * 0.80)
    b = min(1.0, stream * 1.2)
    return r, 0.0, b


def upgrade_terrain():
    """Replace flat-green terrain with heritage PBR (창덕궁 마당/이끼 + 신두리 젖은모래)."""
    grass_bc = os.path.join(CDG_TEX, "T_Ground02A_BC.png")
    grass_nm = os.path.join(CDG_TEX, "T_Ground02A_NM.png")
    grass_rn = os.path.join(CDG_TEX, "T_Ground02A_RN.png")
    dirt_bc = os.path.join(CDG_TEX, "T_Ground01A_BC.png")
    dirt_nm = os.path.join(CDG_TEX, "T_Ground01A_NM.png")
    dirt_rn = os.path.join(CDG_TEX, "T_Ground01A_RN.png")
    sand_bc = os.path.join(YMR_SAND, "T_Sand_ColorB_BC4k.png")
    sand_nm = os.path.join(YMR_SAND, "T_Sand_ColorB_NM4k.png")
    sand_rn = os.path.join(YMR_SAND, "T_Sand_ColorB_RN4k.png")
    for p in (grass_bc, dirt_bc, sand_bc):
        if not os.path.exists(p):
            return {"error": "missing tex " + p}

    for name in ("SSW_Terrain", "SSW_DirtPath"):
        o = bpy.data.objects.get(name)
        if o:
            bpy.data.objects.remove(o, do_unlink=True)

    size = LAYOUT["world"]["extent"]
    segs = 384
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=segs, y_segments=segs, size=size * 0.5)
    uv_lay = bm.loops.layers.uv.new("UVMap")
    col_lay = bm.loops.layers.color.new("blend")
    tile = 8.0
    for v in bm.verts:
        v.co.z = height_at(v.co.x, v.co.y)
        # keep large form; add only high-frequency grit so buildings stay seated
        v.co.z += 0.045 * math.sin(v.co.x * 1.7) * math.cos(v.co.y * 1.35)
        v.co.z += 0.03 * math.sin(v.co.x * 3.1 + v.co.y * 2.4)
    for face in bm.faces:
        face.smooth = True
        for loop in face.loops:
            x, y = loop.vert.co.x, loop.vert.co.y
            loop[uv_lay].uv = ((x + 150.0) / tile, (y + 150.0) / tile)
            r, g, b = _blend_at(x, y)
            loop[col_lay] = (r, g, b, 1.0)

    mat = bpy.data.materials.get("M_SSW_TerrainPBR")
    if mat is None:
        mat = bpy.data.materials.new("M_SSW_TerrainPBR")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (1680, 80)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (1400, 80)
    bsdf.inputs["Metallic"].default_value = 0.0
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    uv = nt.nodes.new("ShaderNodeUVMap")
    uv.location = (-980, 80)
    uv.uv_map = "UVMap"

    gc, gn, gr, g_nodes = _pbr_set(nt, "Grass", grass_bc, grass_nm, grass_rn, -640)
    dc, dn, dr, d_nodes = _pbr_set(nt, "Dirt", dirt_bc, dirt_nm, dirt_rn, -640)
    sc, sn, sr, s_nodes = _pbr_set(nt, "Sand", sand_bc, sand_nm, sand_rn, -640)
    # stack the three sets vertically
    for i, nodes in enumerate((g_nodes, d_nodes, s_nodes)):
        for j, n in enumerate(nodes):
            n.location = (-640, 520 - i * 420 - j * 130)
    for nodes in (g_nodes, d_nodes, s_nodes):
        for n in nodes:
            nt.links.new(uv.outputs["UV"], n.inputs["Vector"])

    vcol = nt.nodes.new("ShaderNodeVertexColor")
    vcol.location = (-640, 780)
    vcol.layer_name = "blend"
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    sep.location = (-400, 780)
    nt.links.new(vcol.outputs["Color"], sep.inputs["Color"])

    # optional large-scale 다랑이 논 albedo mottling on grass
    grass_col = gc
    if os.path.exists(PADDY_JPG):
        uv2 = nt.nodes.new("ShaderNodeTexCoord")
        uv2.location = (-980, 900)
        map2 = nt.nodes.new("ShaderNodeMapping")
        map2.location = (-780, 900)
        map2.inputs["Scale"].default_value = (0.42, 0.42, 1.0)
        nt.links.new(uv2.outputs["Object"], map2.inputs["Vector"])
        pj = nt.nodes.new("ShaderNodeTexImage")
        pj.location = (-560, 900)
        pj.image = _img(PADDY_JPG, False)
        pj.extension = "EXTEND"
        nt.links.new(map2.outputs["Vector"], pj.inputs["Vector"])
        mul = nt.nodes.new("ShaderNodeMix")
        mul.data_type = "RGBA"
        mul.blend_type = "MULTIPLY"
        mul.location = (-280, 520)
        mul.inputs["Factor"].default_value = 0.28
        try:
            nt.links.new(gc, mul.inputs["A"])
            nt.links.new(pj.outputs["Color"], mul.inputs["B"])
        except Exception:
            nt.links.new(gc, mul.inputs[6])
            nt.links.new(pj.outputs["Color"], mul.inputs[7])
        grass_col = mul.outputs["Result"] if "Result" in mul.outputs else mul.outputs[2]

    col1 = _mix(nt, (40, 400), sep.outputs["Red"], grass_col, dc, "grass|dirt")
    col2 = _mix(nt, (280, 400), sep.outputs["Blue"], col1, sc, " +sand")
    nrm1 = _mix(nt, (40, 80), sep.outputs["Red"], gn, dn, "n grass|dirt")
    nrm2 = _mix(nt, (280, 80), sep.outputs["Blue"], nrm1, sn, "n +sand")
    rgh1 = _mix(nt, (40, -200), sep.outputs["Red"], gr, dr, "r grass|dirt")
    rgh2 = _mix(nt, (280, -200), sep.outputs["Blue"], rgh1, sr, "r +sand")
    nrm = nt.nodes.new("ShaderNodeNormalMap")
    nrm.location = (520, 80)
    nrm.inputs["Strength"].default_value = 1.15
    nt.links.new(nrm2, nrm.inputs["Color"])

    nt.links.new(col2, bsdf.inputs["Base Color"])
    nt.links.new(nrm.outputs["Normal"], bsdf.inputs["Normal"])
    nt.links.new(rgh2, bsdf.inputs["Roughness"])

    terr = _mesh_obj("SSW_Terrain", bm, "SSW_TERRAIN", mat)
    terr.data.update()

    # richer water
    water = bpy.data.objects.get("SSW_StreamWater")
    if water:
        wmat = bpy.data.materials.get("M_SSW_Water") or _mat_rgb(
            "M_SSW_Water", (0.07, 0.16, 0.18), 0.06, spec=0.55
        )
        wmat.use_nodes = True
        bs = None
        for n in wmat.node_tree.nodes:
            if n.type == "BSDF_PRINCIPLED":
                bs = n
                break
        if bs:
            bs.inputs["Base Color"].default_value = (0.06, 0.14, 0.16, 1.0)
            bs.inputs["Roughness"].default_value = 0.045
            if "Transmission Weight" in bs.inputs:
                bs.inputs["Transmission Weight"].default_value = 0.72
            if "IOR" in bs.inputs:
                bs.inputs["IOR"].default_value = 1.333
            if "Alpha" in bs.inputs:
                bs.inputs["Alpha"].default_value = 0.78
            wmat.blend_method = "BLEND"
        water.data.materials.clear()
        water.data.materials.append(wmat)

    st = _mesh_stats(terr)
    _log("upgrade_terrain verts=%s" % (st or {}).get("verts"))
    return {"terrain": st, "material": mat.name}


def make_trees():
    """Placeholder vegetation, not heritage scans."""
    mat_t = _mat_rgb("M_SSW_Trunk", (0.22, 0.14, 0.08), 0.9)
    mat_l = _mat_rgb("M_SSW_Leaf", (0.14, 0.28, 0.10), 0.85)
    srcs = []
    for i, (r1, r2, h) in enumerate(((0.18, 0.05, 1.6), (0.22, 0.06, 2.2), (0.15, 0.04, 1.3))):
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=7, radius1=0.12, radius2=0.08, depth=h * 0.45)
        for v in bm.verts:
            v.co.z += h * 0.2
        trunk = _mesh_obj("SSW_TreeTrunk_%d" % i, bm, "SSW_VEG", mat_t)
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=2, radius=r1 * 4.2)
        for v in bm.verts:
            v.co.z += h * 0.75
            v.co.z *= 1.15
        crown = _mesh_obj("SSW_TreeCrown_%d" % i, bm, "SSW_VEG", mat_l)
        srcs.append((trunk, crown, h))

    rng = 17
    placed = 0
    half = 138.0
    for i in range(70):
        ang = (i * 137.508) % 360.0
        rad = 95.0 + (i * 7) % 50
        x = math.cos(math.radians(ang)) * rad
        y = math.sin(math.radians(ang)) * rad
        if abs(x) < 38 and abs(y) < 62:
            continue
        if abs(x) > half or abs(y) > half:
            continue
        k = i % 3
        trunk, crown, h = srcs[k]
        z = height_at(x, y)
        s = 0.85 + (i % 5) * 0.12
        for src in (trunk, crown):
            inst = src.copy()
            inst.data = src.data
            inst.location = (x, y, z)
            inst.scale = (s, s, s)
            inst.rotation_euler = (0, 0, math.radians((i * 29) % 360))
            inst.name = src.name.replace("SSW_Tree", "SSW_Veg") + "_%02d" % i
            _move_to(inst, "SSW_VEG")
            placed += 1
    for trunk, crown, _h in srcs:
        trunk.hide_set(True)
        crown.hide_set(True)
        trunk.hide_render = True
        crown.hide_render = True
    return {"instances": placed}


def make_lighting():
    data = bpy.data.lights.new("SSW_Sun", "SUN")
    data.energy = 5.0
    data.color = (1.0, 0.94, 0.84)
    data.angle = math.radians(0.53)
    sun = bpy.data.objects.new("SSW_Sun", data)
    sun.rotation_euler = (math.radians(48), 0.0, math.radians(38))
    _move_to(sun, "SSW_LIGHTING")

    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("SSW_World")
        bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    bg = nt.nodes.new("ShaderNodeBackground")
    sky = nt.nodes.new("ShaderNodeTexSky")
    try:
        sky.sky_type = "NISHITA"
    except Exception:
        pass
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    bg.inputs["Strength"].default_value = 0.75

    def _cam(name, loc, target):
        cam_d = bpy.data.cameras.new(name)
        cam_d.lens = 35
        cam_d.clip_start = 0.1
        cam_d.clip_end = 2000.0
        ob = bpy.data.objects.new(name, cam_d)
        ob.location = loc
        direction = Vector(target) - Vector(loc)
        ob.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        _move_to(ob, "SSW_CAMERAS")
        return ob

    c0 = _cam("CAM_Overview", (190, -195, 145), (0, 0, 8))
    _cam("CAM_Entrance", (3, -58, 1.7), (0, -35, 3.2))
    _cam("CAM_Stream", (22, -10, 2.4), (2, 8, 3.5))
    bpy.context.scene.camera = c0
    return {"sun": sun.name, "camera": c0.name}


# ---------------------------------------------------------------- import / materials


def _fbx_path(a):
    return os.path.join(ROOT, "_extracted", a["dir"], a["fbx"])


def _tex_dir(a):
    return os.path.join(ROOT, "_extracted", a["dir"])


def _bake_identity(obj, extra_scale=1.0):
    M = Matrix.Scale(extra_scale, 4) @ obj.matrix_world
    obj.data.transform(M)
    obj.data.update()
    obj.matrix_world = Matrix.Identity(4)


def _do_import(key):
    a = asset(key)
    fbx = _fbx_path(a)
    if not os.path.exists(fbx):
        return {"error": "missing FBX", "path": fbx}
    extra = LAYOUT["scale"]["FBX_SCALE"]
    before = set(bpy.data.objects.keys())
    bpy.ops.import_scene.fbx(
        "EXEC_DEFAULT",
        filepath=fbx,
        use_custom_normals=True,
        use_image_search=False,
        global_scale=1.0,
        axis_forward="-Z",
        axis_up="Y",
    )
    new = [bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before]
    meshes = [o for o in new if o.type == "MESH"]
    if not meshes:
        return {"error": "no mesh", "new": [o.name for o in new]}
    out = []
    for i, o in enumerate(meshes):
        o.name = "SM_SSW_%s%s" % (key, "" if i == 0 else "_%d" % i)
        o.data.name = "MD_" + o.name
        _bake_identity(o, extra)
        _move_to(o, a["coll"])
        out.append(o.name)
    for o in new:
        if o.type == "EMPTY" and not o.children:
            bpy.data.objects.remove(o, do_unlink=True)
    wired = wire_materials(key)
    st = _mesh_stats(bpy.data.objects[out[0]])
    _log("import %s objs=%d dims=%s" % (key, len(out), (st or {}).get("dims")))
    return {"key": key, "objects": out, "wired": wired, **(st or {})}


def gate_scale():
    """Import Stonewall, measure, persist FBX_SCALE. Does not place the wall yet."""
    r = _do_import("Stonewall")
    if "error" in r:
        return r
    dims = r.get("dims") or [0, 0, 0]
    longest = max(dims)
    scale = 1.0
    note = "importer object-scale bake only"
    if longest > 80:
        scale = 0.01
        note = "longest dim %.1f m — applying extra 0.01" % longest
        ob = bpy.data.objects.get(r["objects"][0])
        _bake_identity(ob, 0.01)
        r = _mesh_stats(ob)
        r["objects"] = [ob.name]
        dims = r["dims"]
        longest = max(dims)
    LAYOUT["scale"]["FBX_SCALE"] = scale
    LAYOUT["scale"]["gated"] = True
    rec = {
        "FBX_SCALE": scale,
        "probe": "Stonewall",
        "dims_m": dims,
        "longest_m": longest,
        "note": note,
    }
    with open(SCALE_JSON, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=2)
    _log("scale gate %s" % rec)
    return rec


def _find_maps(tex_dir):
    maps = {}
    if not os.path.isdir(tex_dir):
        return maps
    for fn in os.listdir(tex_dir):
        m = re.match(r"(.+)_(BC|NM|RN|AO|MT)\.png$", fn, re.I)
        if not m:
            continue
        stem, ch = m.group(1), m.group(2).upper()
        maps.setdefault(stem, {})[ch] = os.path.join(tex_dir, fn)
    return maps


def _stem_for_mat(mat_name, stems):
    n = re.sub(r"\.\d{3}$", "", mat_name)
    n = re.sub(r"^(MI_|M_|T_|SM_)", "", n)
    for s in stems:
        tail = re.sub(r"^T_", "", s)
        if tail.lower() in n.lower() or n.lower() in tail.lower():
            return s
    if len(stems) == 1:
        return stems[0]
    return None


def _img(path, non_color=False):
    img = bpy.data.images.get(os.path.basename(path))
    if img is None:
        if not os.path.exists(path):
            return None
        img = bpy.data.images.load(path, check_existing=True)
    img.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    return img


def wire_materials(key):
    a = asset(key)
    tex_dir = _tex_dir(a)
    maps = _find_maps(tex_dir)
    stems = list(maps.keys())
    prefix = "SM_SSW_%s" % key
    objs = [o for o in bpy.data.objects if o.name == prefix or o.name.startswith(prefix + "_")]
    linked = 0
    missing = []
    for o in objs:
        for slot in o.material_slots:
            mat = slot.material
            if mat is None:
                continue
            stem = _stem_for_mat(mat.name, stems)
            if stem is None:
                missing.append(mat.name)
                continue
            ch = maps[stem]
            mat.use_nodes = True
            nt = mat.node_tree
            nt.nodes.clear()
            out = nt.nodes.new("ShaderNodeOutputMaterial")
            out.location = (620, 0)
            bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
            bsdf.location = (300, 0)
            bsdf.inputs["Metallic"].default_value = 0.0
            bsdf.inputs["Roughness"].default_value = 0.7
            nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
            if "BC" in ch:
                n = nt.nodes.new("ShaderNodeTexImage")
                n.location = (-360, 200)
                n.image = _img(ch["BC"], False)
                color_out = n.outputs["Color"]
                if "AO" in ch:
                    ao = nt.nodes.new("ShaderNodeTexImage")
                    ao.location = (-360, 0)
                    ao.image = _img(ch["AO"], True)
                    mul = nt.nodes.new("ShaderNodeMix")
                    mul.data_type = "RGBA"
                    mul.blend_type = "MULTIPLY"
                    mul.inputs["Factor"].default_value = 1.0
                    mul.location = (-40, 160)
                    nt.links.new(color_out, mul.inputs["A"])
                    nt.links.new(ao.outputs["Color"], mul.inputs["B"])
                    color_out = mul.outputs["Result"]
                nt.links.new(color_out, bsdf.inputs["Base Color"])
            if "NM" in ch:
                n = nt.nodes.new("ShaderNodeTexImage")
                n.location = (-360, -220)
                n.image = _img(ch["NM"], True)
                nrm = nt.nodes.new("ShaderNodeNormalMap")
                nrm.location = (-40, -220)
                nt.links.new(n.outputs["Color"], nrm.inputs["Color"])
                nt.links.new(nrm.outputs["Normal"], bsdf.inputs["Normal"])
            if "RN" in ch:
                n = nt.nodes.new("ShaderNodeTexImage")
                n.location = (-360, -420)
                n.image = _img(ch["RN"], True)
                nt.links.new(n.outputs["Color"], bsdf.inputs["Roughness"])
            linked += 1
    return {"linked": linked, "stems": stems, "missing": missing}


def place(key):
    a = asset(key)
    if a.get("place") == "wall_kit":
        return place_walls()
    prefix = "SM_SSW_%s" % key
    objs = [o for o in bpy.data.objects if o.name == prefix or o.name.startswith(prefix + "_")]
    if not objs:
        return {"error": "not imported", "key": key}
    x, y = a["xy"]
    yaw = a.get("yaw", 0.0)
    sink = a.get("sink", 0.0)
    stats = [(_mesh_stats(o), o) for o in objs]
    zs = [st["min_z"] for st, _o in stats if st]
    mz = min(zs) if zs else 0.0
    loc = (x, y, height_at(x, y) - mz - sink)
    placed = []
    for st, o in stats:
        o.location = loc
        o.rotation_euler = (0.0, 0.0, yaw)
        placed.append({"name": o.name, "dims": (st or {}).get("dims")})
    return {"key": key, "loc": list(loc), "parts": len(placed), "min_z": mz}


def place_walls():
    return rebuild_walls()


def rebuild_walls():
    """Continuous 3 m wall runs. Pivot is the LEFT end (object X 0..3).
    South/north/west/east meet at corners. South keeps a gate gap at 오곡문."""
    src = bpy.data.objects.get("SM_SSW_Stonewall")
    if src is None:
        return {"error": "Stonewall not imported"}
    for o in list(bpy.data.objects):
        if o.name.startswith("SM_SSW_Stonewall_"):
            bpy.data.objects.remove(o, do_unlink=True)
    src.hide_set(True)
    src.hide_render = True
    st = _mesh_stats(src)
    length = 3.0
    y_s, y_n = -38.0, 58.0
    x_w, x_e = -24.0, 24.0
    spots = []
    x = x_w
    while x + 1e-4 < x_e:
        mid = x + length * 0.5
        if mid < -3.2 or mid > 3.2:
            spots.append((x, y_s, 0.0))
        x += length
    x = x_e
    while x - 1e-4 > x_w:
        spots.append((x, y_n, math.pi))
        x -= length
    y = y_s
    while y + 1e-4 < y_n:
        spots.append((x_w, y, math.pi * 0.5))
        y += length
    y = y_n
    while y - 1e-4 > y_s:
        spots.append((x_e, y, -math.pi * 0.5))
        y -= length
    mz = st["min_z"] if st else 0.0
    names = []
    for i, (x, y, yaw) in enumerate(spots):
        inst = src.copy()
        inst.data = src.data
        inst.hide_set(False)
        inst.hide_render = False
        inst.location = (x, y, height_at(x, y) - mz)
        inst.rotation_euler = (0.0, 0.0, yaw)
        inst.name = "SM_SSW_Stonewall_%02d" % i
        _move_to(inst, "SSW_ARCH")
        names.append(inst.name)
    return {"wall_src_dims": (st or {}).get("dims"), "instances": len(names),
            "south_gap": "ogongmun"}


YMR_VEG = os.path.join(ROOT, "_extracted", "VEG")
YMR_TEXVEG = os.path.join(ROOT, "_extracted", "VEG")
YMR_OBJ = os.path.join(ROOT, "_extracted", "Sanbangsan")


def remove_placeholders():
    killed = []
    for o in list(bpy.data.objects):
        if o.name.startswith("SSW_Veg") or o.name.startswith("SSW_Tree"):
            killed.append(o.name)
            bpy.data.objects.remove(o, do_unlink=True)
    return {"removed": len(killed)}


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


def import_rock_d():
    fbx = os.path.join(ROOT, "_extracted", "Rock_D", "SM_Rock01d.fbx")
    names = _import_fbx_file(fbx, "SM_SSW_Rock_D", "SSW_PROPS")
    if isinstance(names, dict):
        return names
    # reuse existing PBR wirer by faking an asset entry
    tex_dir = os.path.join(ROOT, "_extracted", "Rock_D")
    maps = _find_maps(tex_dir)
    for n in names:
        o = bpy.data.objects[n]
        for slot in o.material_slots:
            mat = slot.material
            if mat is None or not maps:
                continue
            stem = list(maps.keys())[0]
            ch = maps[stem]
            mat.use_nodes = True
            nt = mat.node_tree
            nt.nodes.clear()
            out = nt.nodes.new("ShaderNodeOutputMaterial")
            bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
            bsdf.inputs["Metallic"].default_value = 0.0
            nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
            if "BC" in ch:
                im = nt.nodes.new("ShaderNodeTexImage")
                im.image = _img(ch["BC"], False)
                nt.links.new(im.outputs["Color"], bsdf.inputs["Base Color"])
            if "NM" in ch:
                im = nt.nodes.new("ShaderNodeTexImage")
                im.image = _img(ch["NM"], True)
                nrm = nt.nodes.new("ShaderNodeNormalMap")
                nt.links.new(im.outputs["Color"], nrm.inputs["Color"])
                nt.links.new(nrm.outputs["Normal"], bsdf.inputs["Normal"])
            if "RN" in ch:
                im = nt.nodes.new("ShaderNodeTexImage")
                im.image = _img(ch["RN"], True)
                nt.links.new(im.outputs["Color"], bsdf.inputs["Roughness"])
    st = _mesh_stats(bpy.data.objects[names[0]])
    return {"objects": names, **(st or {})}


def import_veg(key):
    fbx = os.path.join(YMR_VEG, key + ".fbx")
    names = _import_fbx_file(fbx, "VEG_" + key, "SSW_VEG")
    if isinstance(names, dict):
        return names
    wired = _wire_veg(key, names)
    for n in names:
        o = bpy.data.objects[n]
        o.hide_set(True)
        o.hide_render = True
    st = _mesh_stats(bpy.data.objects[names[0]])
    return {"key": key, "objects": names, "wired": wired, **(st or {})}


def _wire_veg(key, names):
    if not os.path.isdir(YMR_TEXVEG):
        return {"error": "no tex dir"}
    files = os.listdir(YMR_TEXVEG)
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
                if "7" in mn:
                    part = "Stem"
                elif "8" in mn:
                    part = "Leaf"
                elif "9" in mn:
                    part = "Flower"
            if part is None:
                part = "Leaf"
            stem = "T_%s_%s" % (key, part)
            def _p(ch):
                fn = "%s_%s.png" % (stem, ch)
                return os.path.join(YMR_TEXVEG, fn) if fn in files else None
            bc, nm, rn, op = _p("BC"), _p("NM"), _p("RN"), _p("OP")
            if bc is None:
                for tok in ("Stem", "Bark", "Leaf", "Branch"):
                    alt = "T_%s_%s_BC.png" % (key, tok)
                    if alt in files:
                        stem = "T_%s_%s" % (key, tok)
                        bc, nm, rn, op = _p("BC"), _p("NM"), _p("RN"), _p("OP")
                        break
            if bc is None:
                continue
            mat.use_nodes = True
            mat.blend_method = "HASHED" if op else "OPAQUE"
            if hasattr(mat, "shadow_method"):
                mat.shadow_method = "HASHED" if op else "OPAQUE"
            nt = mat.node_tree
            nt.nodes.clear()
            out = nt.nodes.new("ShaderNodeOutputMaterial")
            out.location = (560, 0)
            bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
            bsdf.location = (280, 0)
            bsdf.inputs["Metallic"].default_value = 0.0
            nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
            im = nt.nodes.new("ShaderNodeTexImage")
            im.location = (-320, 180)
            im.image = _img(bc, False)
            nt.links.new(im.outputs["Color"], bsdf.inputs["Base Color"])
            if op:
                ao = nt.nodes.new("ShaderNodeTexImage")
                ao.location = (-320, -40)
                ao.image = _img(op, True)
                if "Alpha" in bsdf.inputs:
                    nt.links.new(ao.outputs["Color"], bsdf.inputs["Alpha"])
            if nm:
                ni = nt.nodes.new("ShaderNodeTexImage")
                ni.location = (-320, -240)
                ni.image = _img(nm, True)
                nrm = nt.nodes.new("ShaderNodeNormalMap")
                nrm.location = (-40, -240)
                nt.links.new(ni.outputs["Color"], nrm.inputs["Color"])
                nt.links.new(nrm.outputs["Normal"], bsdf.inputs["Normal"])
            if rn:
                ri = nt.nodes.new("ShaderNodeTexImage")
                ri.location = (-320, -420)
                ri.image = _img(rn, True)
                nt.links.new(ri.outputs["Color"], bsdf.inputs["Roughness"])
            linked += 1
    return {"linked": linked}


def scatter_heritage_veg():
    """Instance 신두리 식생 around the garden, never inside the wall court."""
    specs = [
        ("BlackPine", 28, (0.85, 1.3), 0),
        ("Lugose", 22, (0.7, 1.15), 1),
        ("Vitex", 18, (0.75, 1.2), 2),
        ("Eulalia", 24, (0.8, 1.25), 3),
        ("Artemisia", 18, (0.7, 1.1), 4),
        ("Anthephoroides", 16, (0.75, 1.15), 5),
    ]
    placed = {}
    for key, count, srange, seed in specs:
        srcs = [o for o in bpy.data.objects if o.name == "VEG_" + key or o.name.startswith("VEG_" + key + "_")]
        if not srcs:
            placed[key] = "missing"
            continue
        n = 0
        i = 0
        tries = 0
        while n < count and tries < count * 12:
            tries += 1
            i += 1
            ang = (i * 137.508 + seed * 17.0) % 360.0
            if key == "BlackPine":
                rad = 70.0 + (i * 11 + seed * 3) % 70
            elif key in ("Eulalia", "Artemisia", "Anthephoroides"):
                rad = 30.0 + (i * 9 + seed) % 55
            else:
                rad = 40.0 + (i * 10 + seed * 2) % 80
            x = math.cos(math.radians(ang)) * rad
            y = math.sin(math.radians(ang)) * rad
            # keep court interior clear
            if abs(x) < 28 and -42 < y < 62:
                continue
            if abs(x) > 145 or abs(y) > 145:
                continue
            src = srcs[n % len(srcs)]
            inst = src.copy()
            inst.data = src.data
            inst.hide_set(False)
            inst.hide_render = False
            s = srange[0] + (srange[1] - srange[0]) * ((i * 13 + seed) % 10) / 9.0
            inst.location = (x, y, height_at(x, y))
            inst.scale = (s, s, s)
            inst.rotation_euler = (0.0, 0.0, math.radians((i * 41 + seed * 19) % 360))
            inst.name = "VEG_%s_%02d" % (key, n)
            _move_to(inst, "SSW_VEG")
            n += 1
        placed[key] = n
    return {"placed": placed}


def scatter_rocks():
    srcs = []
    for key in ("Rock_A", "Rock_B", "Inscribed_Rock", "Rock_D"):
        o = bpy.data.objects.get("SM_SSW_" + key)
        if o:
            srcs.append(o)
    if not srcs:
        return {"error": "no rocks"}
    spots = [
        (-32, 10), (-36, -20), (32, 14), (36, -8),
        (-8, 70), (10, 74), (-40, 40), (42, 36),
        (-30, -48), (28, -52), (6, -70), (-14, 80),
        (48, -30), (-50, 8),
    ]
    names = []
    for i, (x, y) in enumerate(spots):
        src = srcs[i % len(srcs)]
        inst = src.copy()
        inst.data = src.data
        inst.hide_set(False)
        inst.hide_render = False
        st = _mesh_stats(src)
        mz = st["min_z"] if st else 0.0
        inst.location = (x, y, height_at(x, y) - mz - 0.15)
        inst.rotation_euler = (0.0, 0.0, math.radians((i * 47) % 360))
        inst.scale = (0.85 + (i % 4) * 0.12,) * 3
        inst.name = "SM_SSW_RockScatter_%02d" % i
        _move_to(inst, "SSW_PROPS")
        names.append(inst.name)
    return {"instances": len(names)}


def _import_obj(path):
    if hasattr(bpy.ops.wm, "obj_import"):
        bpy.ops.wm.obj_import("EXEC_DEFAULT", filepath=path)
    else:
        bpy.ops.import_scene.obj("EXEC_DEFAULT", filepath=path)


def import_sanbangsan():
    path = os.path.join(YMR_OBJ, "Sanbangsan.obj")
    jpg = os.path.join(YMR_OBJ, "Sanbangsan.jpg")
    if not os.path.exists(path):
        return {"error": "missing " + path}
    before = set(bpy.data.objects.keys())
    _import_obj(path)
    new = [bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before]
    meshes = [o for o in new if o.type == "MESH"]
    if not meshes:
        return {"error": "no mesh", "new": [o.name for o in new]}
    o = meshes[0]
    o.name = "SM_SSW_Sanbangsan"
    o.data.name = "MD_SSW_Sanbangsan"
    _bake_identity(o, 1.0)
    _move_to(o, "SSW_TERRAIN")
    st0 = _mesh_stats(o)
    minx, miny, minz = st0["min"]
    maxx, maxy, maxz = st0["max"]
    dx = -0.5 * (minx + maxx)
    dy = 180.0 - miny
    dz = -minz
    o.data.transform(Matrix.Translation((dx, dy, dz)))
    o.data.update()
    o.matrix_world = Matrix.Identity(4)
    mat = bpy.data.materials.get("MI_SSW_Sanbangsan") or bpy.data.materials.new("MI_SSW_Sanbangsan")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["Roughness"].default_value = 0.88
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    if os.path.exists(jpg):
        im = nt.nodes.new("ShaderNodeTexImage")
        im.image = _img(jpg, False)
        nt.links.new(im.outputs["Color"], bsdf.inputs["Base Color"])
    o.data.materials.clear()
    o.data.materials.append(mat)
    st = _mesh_stats(o)
    _log("sanbangsan dims=%s min=%s" % (st["dims"], st["min"]))
    return {"object": o.name, "raw": st0, "placed": st}


def import_paddy():
    path = os.path.join(ROOT, "_extracted", "TerracedPaddy", "남해 가천마을 다랑이 논", "M_TerracedPaddy.obj")
    jpg = os.path.join(ROOT, "_extracted", "TerracedPaddy", "남해 가천마을 다랑이 논", "M_TerracedPaddy.jpg")
    if not os.path.exists(path):
        return {"error": "missing paddy obj"}
    before = set(bpy.data.objects.keys())
    _import_obj(path)
    new = [bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before]
    meshes = [o for o in new if o.type == "MESH"]
    if not meshes:
        return {"error": "no mesh"}
    o = meshes[0]
    o.name = "SM_SSW_TerracedPaddy"
    o.data.name = "MD_SSW_TerracedPaddy"
    _bake_identity(o, 1.0)
    _move_to(o, "SSW_TERRAIN")
    st0 = _mesh_stats(o)
    minx, miny, minz = st0["min"]
    maxx, maxy, maxz = st0["max"]
    dx = -0.5 * (minx + maxx)
    dy = -90.0 - maxy
    dz = -minz
    o.data.transform(Matrix.Translation((dx, dy, dz)))
    o.data.update()
    o.matrix_world = Matrix.Identity(4)
    mat = bpy.data.materials.get("MI_SSW_Paddy") or bpy.data.materials.new("MI_SSW_Paddy")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["Roughness"].default_value = 0.9
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    if os.path.exists(jpg):
        im = nt.nodes.new("ShaderNodeTexImage")
        im.image = _img(jpg, False)
        nt.links.new(im.outputs["Color"], bsdf.inputs["Base Color"])
    o.data.materials.clear()
    o.data.materials.append(mat)
    st = _mesh_stats(o)
    _log("paddy dims=%s min=%s max=%s" % (st["dims"], st["min"], st["max"]))
    return {"object": o.name, "raw": st0, "placed": st}


def save():
    os.makedirs(os.path.dirname(MASTER), exist_ok=True)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile("EXEC_DEFAULT", filepath=MASTER, compress=True, relative_remap=True)
    mb = round(os.path.getsize(MASTER) / 1048576, 1)
    _log("saved %s (%.1f MB)" % (MASTER, mb))
    return {"saved": MASTER, "mb": mb}


def scene_report():
    terr = bpy.data.objects.get("SSW_Terrain")
    ts = _mesh_stats(terr) if terr else None
    arch = [o.name for o in _coll("SSW_ARCH").objects]
    return {
        "objects": len(bpy.data.objects),
        "terrain": ts,
        "arch_count": len(arch),
        "arch": arch[:40],
        "scale": LAYOUT["scale"],
    }


def _iter_group(prefix):
    return [o for o in bpy.data.objects
            if o.name == prefix or o.name.startswith(prefix + "_")]


def _group_minmax(objs):
    xs, ys, zs = [], [], []
    dg = bpy.context.evaluated_depsgraph_get()
    for o in objs:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        if me.vertices:
            for v in me.vertices:
                c = o.matrix_world @ v.co
                xs.append(c.x)
                ys.append(c.y)
                zs.append(c.z)
        ev.to_mesh_clear()
    if not xs:
        return None
    return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


def _nudge_group(prefix, dx=0.0, dy=0.0, dz=0.0):
    objs = _iter_group(prefix)
    for o in objs:
        o.location.x += dx
        o.location.y += dy
        o.location.z += dz
    return len(objs)


def hide_guides():
    n = 0
    for o in bpy.data.objects:
        if o.name.startswith("GUIDE"):
            o.hide_set(True)
            o.hide_render = True
            n += 1
    c = bpy.data.collections.get("SSW_GUIDES")
    if c:
        c.hide_viewport = True
        c.hide_render = True
    return {"hidden": n}


def rebuild_stream():
    """Short in-garden stream. Does not punch through the 300 m pad."""
    old = bpy.data.objects.get("SSW_StreamWater")
    wmat = None
    if old:
        if old.data.materials:
            wmat = old.data.materials[0]
        bpy.data.objects.remove(old, do_unlink=True)
    if wmat is None:
        wmat = _mat_rgb("M_SSW_Water", (0.06, 0.14, 0.16), 0.05, spec=0.55)
        wmat.blend_method = "BLEND"
        bs = next((n for n in wmat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bs:
            if "Transmission Weight" in bs.inputs:
                bs.inputs["Transmission Weight"].default_value = 0.7
            if "IOR" in bs.inputs:
                bs.inputs["IOR"].default_value = 1.333
            if "Alpha" in bs.inputs:
                bs.inputs["Alpha"].default_value = 0.8
            bs.inputs["Roughness"].default_value = 0.05

    y0, y1 = -50.0, 16.0
    segs_y = 64
    segs_x = 8
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=segs_x, y_segments=segs_y, size=1.0)
    for v in bm.verts:
        fy = v.co.y
        y = 0.5 * (y0 + y1) + fy * 0.5 * (y1 - y0)
        # slightly wider mid-garden, pinch at the gate
        half_w = 1.45 + 0.45 * abs(math.sin((y + 12.0) * 0.09)) + 0.2 * math.sin(y * 0.31)
        x = stream_x(y) + v.co.x * half_w
        v.co.x = x
        v.co.y = y
        v.co.z = height_at(x, y) + 0.08
    for f in bm.faces:
        f.smooth = True
    water = _mesh_obj("SSW_StreamWater", bm, "SSW_WATER", wmat)
    return {"water": water.name, "y": [y0, y1]}


def level_walls():
    walls = [o for o in bpy.data.objects if o.name.startswith("SM_SSW_Stonewall_")]
    south, north, west, east = [], [], [], []
    for o in walls:
        yaw = o.rotation_euler.z % (2 * math.pi)
        if yaw > math.pi:
            yaw -= 2 * math.pi
        if abs(yaw) < 0.2:
            south.append(o)
        elif abs(abs(yaw) - math.pi) < 0.2:
            north.append(o)
        elif abs(yaw - 0.5 * math.pi) < 0.2:
            west.append(o)
        elif abs(yaw + 0.5 * math.pi) < 0.2:
            east.append(o)
    sz = max(o.location.z for o in south) if south else 0.0
    nz = max(o.location.z for o in north) if north else sz
    y_s = min(o.location.y for o in south) if south else -38.0
    y_n = max(o.location.y for o in north) if north else 58.0
    for o in south:
        o.location.z = sz
    for o in north:
        o.location.z = nz
    span = max(0.001, y_n - y_s)
    for o in west + east:
        t = (o.location.y - y_s) / span
        t = max(0.0, min(1.0, t))
        o.location.z = sz + t * (nz - sz)
    return {"south_z": round(sz, 3), "north_z": round(nz, 3),
            "counts": [len(south), len(north), len(west), len(east)]}


def push_backdrops():
    out = {}
    san = bpy.data.objects.get("SM_SSW_Sanbangsan")
    if san:
        # shrink and send north so it reads as distant mountain, not a sea cliff glued to the pad
        st = _mesh_stats(san)
        miny = st["min"][1]
        # scale about south-center, then slide south edge to y=420
        pivot = Vector((0.0, miny, 0.0))
        s = 0.32
        M = Matrix.Translation(pivot) @ Matrix.Scale(s, 4) @ Matrix.Translation(-pivot)
        san.data.transform(M)
        san.data.update()
        st2 = _mesh_stats(san)
        dy = 420.0 - st2["min"][1]
        san.data.transform(Matrix.Translation((0.0, dy, 0.0)))
        san.data.update()
        out["sanbangsan"] = _mesh_stats(san)
    pad = bpy.data.objects.get("SM_SSW_TerracedPaddy")
    if pad:
        st = _mesh_stats(pad)
        maxy = st["max"][1]
        pivot = Vector((0.0, maxy, 0.0))
        s = 0.55
        M = Matrix.Translation(pivot) @ Matrix.Scale(s, 4) @ Matrix.Translation(-pivot)
        pad.data.transform(M)
        pad.data.update()
        st2 = _mesh_stats(pad)
        dy = -220.0 - st2["max"][1]
        pad.data.transform(Matrix.Translation((0.0, dy, 0.0)))
        pad.data.update()
        out["paddy"] = _mesh_stats(pad)
    return out


def retarget_terrain():
    """Rewrite Z + blend on the existing 300 m mesh. Keeps the PBR shader."""
    o = bpy.data.objects.get("SSW_Terrain")
    if o is None:
        return {"error": "no terrain"}
    bm = bmesh.new()
    bm.from_mesh(o.data)
    uv_lay = bm.loops.layers.uv.get("UVMap")
    col_lay = bm.loops.layers.color.get("blend")
    if col_lay is None:
        col_lay = bm.loops.layers.color.new("blend")
    for v in bm.verts:
        v.co.z = height_at(v.co.x, v.co.y)
        v.co.z += 0.04 * math.sin(v.co.x * 1.7) * math.cos(v.co.y * 1.35)
    for face in bm.faces:
        face.smooth = True
        for loop in face.loops:
            x, y = loop.vert.co.x, loop.vert.co.y
            r, g, b = _blend_at(x, y)
            loop[col_lay] = (r, g, b, 1.0)
            if uv_lay:
                loop[uv_lay].uv = ((x + 150.0) / 8.0, (y + 150.0) / 8.0)
    bm.to_mesh(o.data)
    bm.free()
    o.data.update()
    return {"verts": len(o.data.vertices)}


def snap_stream_props():
    """Keep 광풍각 / 다리 / 수구 / 오곡문 / 물레방아 on the meander."""
    out = {}

    def _set_xy(prefix, x, y, sink=0.05):
        objs = _iter_group(prefix)
        if not objs:
            return 0
        bb = _group_minmax(objs)
        cx = 0.5 * (bb[0] + bb[1])
        cy = 0.5 * (bb[2] + bb[3])
        _nudge_group(prefix, dx=x - cx, dy=y - cy)
        objs = _iter_group(prefix)
        bb = _group_minmax(objs)
        z0 = height_at(x, y)
        _nudge_group(prefix, dz=(z0 - sink) - bb[4])
        return len(objs)

    # 광풍각: sit on the east bank
    gy = 8.0
    gx = stream_x(gy) + 7.4
    out["gwang"] = _set_xy("SM_SSW_Gwangpunggak", gx, gy, 0.0)
    out["bridge"] = _set_xy("SM_SSW_Tujugwigyo", stream_x(-8.0), -8.0, -0.12)
    out["sugu"] = _set_xy("SM_SSW_Water_Gate", stream_x(-39.5), -39.5, 0.1)
    out["ogong"] = _set_xy("SM_SSW_Ogongmun_Gate", stream_x(-35.0), -35.0, -0.05)
    ww = bpy.data.objects.get("SM_SSW_Waterwheel")
    if ww:
        y = -46.5
        ww.location.x = stream_x(y) + 2.15
        ww.location.y = y
        ww.rotation_euler.z = 1.2
        st = _mesh_stats(ww)
        ww.location.z += height_at(ww.location.x, y) - st["min_z"] - 0.08
        out["wheel"] = [round(v, 2) for v in ww.location]
    return out


def plant_inner_garden():
    """Heritage shrubs/grasses inside the walls — breaks the empty court."""
    # clear previous inner set
    for o in list(bpy.data.objects):
        if o.name.startswith("VEG_Inner_"):
            bpy.data.objects.remove(o, do_unlink=True)

    specs = [
        ("Eulalia", 28, (0.85, 1.25), 1.7, 4.4),
        ("Artemisia", 22, (0.75, 1.15), 1.9, 5.2),
        ("Anthephoroides", 18, (0.8, 1.2), 2.0, 5.6),
        ("Vitex", 14, (0.8, 1.2), 4.5, 9.5),
        ("Lugose", 14, (0.7, 1.15), 5.5, 10.5),
    ]
    # keep clear of buildings
    blocks = [
        (6.8, 8.0, 7.0),
        (0.0, 48.0, 6.5),
        (-20.0, 20.0, 4.2),
        (18.0, 40.0, 4.2),
        (0.0, -35.0, 3.5),
        (stream_x(-8.0), -8.0, 3.0),
    ]
    placed = {}
    for key, count, srange, d0, d1 in specs:
        srcs = [o for o in bpy.data.objects
                if o.name == "VEG_" + key or (o.name.startswith("VEG_" + key + "_") and not o.name.startswith("VEG_Inner_"))]
        # prefer hidden source objects (no numeric inner copies)
        srcs = [o for o in srcs if o.hide_render or o.name == "VEG_" + key]
        if not srcs:
            srcs = [o for o in bpy.data.objects if o.name == "VEG_" + key]
        if not srcs:
            placed[key] = "missing"
            continue
        n = 0
        i = 0
        while n < count and i < count * 20:
            i += 1
            if key in ("Eulalia", "Artemisia", "Anthephoroides"):
                y = -42.0 + (i * 17.3 + hash(key) % 9) % 54.0
                side = -1.0 if (i + n) % 2 == 0 else 1.0
                x = stream_x(y) + side * (d0 + (i % 5) * 0.35)
            else:
                # corners / wall-adjacent
                corners = [(-19, 50), (19, 50), (-19, -20), (19, -18),
                           (-16, 8), (16, 22), (-14, 38), (12, -10)]
                cx, cy = corners[i % len(corners)]
                x = cx + 1.4 * math.sin(i * 1.7)
                y = cy + 1.2 * math.cos(i * 1.3)
            if abs(x) > 22 or y < -36 or y > 55:
                continue
            if abs(x - stream_x(y)) < 1.6:
                continue
            blocked = False
            for px, py, rad in blocks:
                if (x - px) ** 2 + (y - py) ** 2 < rad * rad:
                    blocked = True
                    break
            if blocked:
                continue
            src = srcs[n % len(srcs)]
            inst = src.copy()
            inst.data = src.data
            inst.hide_set(False)
            inst.hide_render = False
            s = srange[0] + (srange[1] - srange[0]) * ((i * 7) % 9) / 8.0
            inst.location = (x, y, height_at(x, y))
            inst.scale = (s, s, s)
            inst.rotation_euler = (0.0, 0.0, math.radians((i * 37) % 360))
            inst.name = "VEG_Inner_%s_%02d" % (key, n)
            _move_to(inst, "SSW_VEG")
            n += 1
        placed[key] = n
    return placed


def soften_garden():
    out = {}
    out["terrain"] = retarget_terrain()
    out["stream"] = rebuild_stream()
    out["walls"] = level_walls()
    out["snap"] = snap_stream_props()
    out["plants"] = plant_inner_garden()
    hide_guides()
    return out


def hide_kit_sources():
    hidden = []
    for name in ("SM_SSW_Rock_D", "SM_SSW_Stonewall", "SM_SSW_Rock_A"):
        o = bpy.data.objects.get(name)
        # Rock_A is placed, not a kit at origin — skip
        if name == "SM_SSW_Rock_A":
            continue
        if o:
            o.hide_set(True)
            o.hide_render = True
            hidden.append(name)
    o = bpy.data.objects.get("SM_SSW_Rock_D")
    if o:
        o.hide_set(True)
        o.hide_render = True
        hidden.append("SM_SSW_Rock_D")
    return hidden


def dress_banks():
    """Scale the huge 바위A, hide boxy ponds, scatter small bank rocks."""
    out = {}
    ra = bpy.data.objects.get("SM_SSW_Rock_A")
    if ra:
        ra.scale = (0.42, 0.42, 0.42)
        ra.location = (stream_x(11.0) - 3.4, 11.0, 0.0)
        ra.rotation_euler.z = 0.7
        st = _mesh_stats(ra)
        ra.location.z = height_at(ra.location.x, ra.location.y) - st["min_z"] - 0.18
        out["rock_a"] = [round(v, 2) for v in ra.location]

    for key in ("SM_SSW_Lower_Pond", "SM_SSW_Upper_Pond"):
        n = 0
        for o in _iter_group(key):
            o.hide_set(True)
            o.hide_render = True
            n += 1
        out[key] = n

    # 협문 against the west wall, as a side gate
    hx, hy = -23.2, -12.0
    objs = _iter_group("SM_SSW_Hyeopmun")
    if objs:
        bb = _group_minmax(objs)
        _nudge_group("SM_SSW_Hyeopmun", dx=hx - 0.5 * (bb[0] + bb[1]),
                     dy=hy - 0.5 * (bb[2] + bb[3]))
        bb = _group_minmax(_iter_group("SM_SSW_Hyeopmun"))
        _nudge_group("SM_SSW_Hyeopmun", dz=height_at(hx, hy) - bb[4] - 0.02)
        out["hyeopmun"] = True

    # bank stones from Rock_B / Rock_D / Inscribed
    for o in list(bpy.data.objects):
        if o.name.startswith("SM_SSW_BankRock_"):
            bpy.data.objects.remove(o, do_unlink=True)
    srcs = []
    for name in ("SM_SSW_Rock_B", "SM_SSW_Inscribed_Rock", "SM_SSW_Rock_D"):
        o = bpy.data.objects.get(name)
        if o:
            srcs.append(o)
    spots = []
    for i, y in enumerate((-44, -36, -28, -20, -12, -4, 2, 7, 12)):
        sx = stream_x(y)
        spots.append((sx - 2.3 - 0.3 * (i % 3), y + 0.4 * (i % 2), 0.55 + 0.1 * (i % 3)))
        spots.append((sx + 2.5 + 0.25 * ((i + 1) % 3), y - 0.5, 0.5 + 0.12 * ((i + 2) % 3)))
    n = 0
    for i, (x, y, sc) in enumerate(spots):
        src = srcs[i % len(srcs)]
        inst = src.copy()
        inst.data = src.data
        inst.hide_set(False)
        inst.hide_render = False
        inst.scale = (sc, sc, sc * 0.85)
        inst.rotation_euler.z = math.radians((i * 51) % 360)
        inst.location = (x, y, 0.0)
        st = _mesh_stats(inst)
        inst.location.z = height_at(x, y) - st["min_z"] - 0.12
        inst.name = "SM_SSW_BankRock_%02d" % i
        _move_to(inst, "SSW_PROPS")
        n += 1
    # hide kit originals that sit at origin
    for name in ("SM_SSW_Rock_B", "SM_SSW_Inscribed_Rock", "SM_SSW_Rock_D"):
        o = bpy.data.objects.get(name)
        if o and abs(o.location.x) < 0.2 and abs(o.location.y) < 0.2:
            o.hide_set(True)
            o.hide_render = True
        elif name == "SM_SSW_Rock_D":
            o.hide_set(True)
            o.hide_render = True
    out["bank_rocks"] = n
    return out


def plant_corner_pines():
    src = bpy.data.objects.get("VEG_BlackPine")
    if src is None:
        return 0
    for o in list(bpy.data.objects):
        if o.name.startswith("VEG_Inner_BlackPine_"):
            bpy.data.objects.remove(o, do_unlink=True)
    spots = [
        (-21, 52, 0.55), (20, 51, 0.5), (-21, -22, 0.48), (20, -20, 0.52),
        (-20, 8, 0.45), (19, 28, 0.47), (-18, 40, 0.5), (18, -6, 0.46),
    ]
    n = 0
    for i, (x, y, s) in enumerate(spots):
        inst = src.copy()
        inst.data = src.data
        inst.hide_set(False)
        inst.hide_render = False
        inst.scale = (s, s, s)
        inst.rotation_euler.z = math.radians(i * 40)
        inst.location = (x, y, height_at(x, y))
        inst.name = "VEG_Inner_BlackPine_%02d" % i
        _move_to(inst, "SSW_VEG")
        n += 1
    return n


def plant_clumps():
    """Fill empty lawn with heritage grass/shrub clumps. Does not wipe existing inner plants."""
    for o in list(bpy.data.objects):
        if o.name.startswith("VEG_Clump_"):
            bpy.data.objects.remove(o, do_unlink=True)
    specs = [
        ("Eulalia", 36, (0.7, 1.15)),
        ("Artemisia", 28, (0.65, 1.05)),
        ("Anthephoroides", 22, (0.7, 1.1)),
        ("Vitex", 10, (0.75, 1.1)),
        ("Lugose", 10, (0.65, 1.05)),
    ]
    blocks = [
        (stream_x(8.0) + 7.4, 8.0, 7.0),
        (0.0, 48.0, 6.5),
        (-20.0, 20.0, 4.0),
        (18.0, 40.0, 4.2),
        (0.0, -35.0, 3.2),
        (stream_x(-8.0), -8.0, 2.6),
    ]
    placed = {}
    for key, count, srange in specs:
        src = bpy.data.objects.get("VEG_" + key)
        if src is None:
            placed[key] = "missing"
            continue
        n = 0
        i = 0
        while n < count and i < count * 25:
            i += 1
            # clump centers biased to the empty west lawn and north court
            if i % 3 == 0:
                x = -16.0 + (i * 2.3) % 12.0
                y = -24.0 + (i * 5.1) % 68.0
            elif i % 3 == 1:
                x = 10.0 + (i * 1.7) % 10.0
                y = -26.0 + (i * 4.7) % 70.0
            else:
                x = -8.0 + (i * 3.1) % 18.0
                y = 16.0 + (i * 3.9) % 32.0
            x += 1.1 * math.sin(i * 2.2)
            y += 0.9 * math.cos(i * 1.8)
            if abs(x) > 21 or y < -34 or y > 54:
                continue
            if abs(x - stream_x(y)) < 2.0:
                continue
            blocked = any((x - px) ** 2 + (y - py) ** 2 < rad * rad for px, py, rad in blocks)
            if blocked:
                continue
            # 3-plant micro-clump
            for k in range(3):
                if n >= count:
                    break
                ox = x + 0.55 * math.cos(k * 2.2 + i)
                oy = y + 0.55 * math.sin(k * 2.2 + i)
                inst = src.copy()
                inst.data = src.data
                inst.hide_set(False)
                inst.hide_render = False
                s = srange[0] + (srange[1] - srange[0]) * ((i + k) % 8) / 7.0
                inst.scale = (s, s, s)
                inst.rotation_euler.z = math.radians((i * 29 + k * 50) % 360)
                inst.location = (ox, oy, height_at(ox, oy))
                inst.name = "VEG_Clump_%s_%02d" % (key, n)
                _move_to(inst, "SSW_VEG")
                n += 1
        placed[key] = n
    return placed


def extra_outer_pines():
    src = bpy.data.objects.get("VEG_BlackPine")
    if src is None:
        return 0
    for o in list(bpy.data.objects):
        if o.name.startswith("VEG_OuterClose_"):
            bpy.data.objects.remove(o, do_unlink=True)
    spots = [
        (-28, 54, 0.62), (28, 54, 0.58), (-28, -32, 0.55), (28, -30, 0.6),
        (-29, 20, 0.5), (29, 18, 0.52), (-29, 0, 0.48), (29, 4, 0.5),
        (-28, 40, 0.57), (28, 36, 0.53), (-32, -10, 0.46), (32, -8, 0.47),
        (0, 68, 0.65), (-12, 66, 0.5), (12, 67, 0.55),
        (0, -58, 0.5), (-14, -56, 0.48), (16, -57, 0.52),
    ]
    n = 0
    for i, (x, y, s) in enumerate(spots):
        inst = src.copy()
        inst.data = src.data
        inst.hide_set(False)
        inst.hide_render = False
        inst.scale = (s, s, s)
        inst.rotation_euler.z = math.radians(i * 33)
        inst.location = (x, y, height_at(x, y))
        inst.name = "VEG_OuterClose_%02d" % i
        _move_to(inst, "SSW_VEG")
        n += 1
    return n


def polish_again():
    hide_guides()
    hide_kit_sources()
    # 화계 reads as a gray plinth
    for o in _iter_group("SM_SSW_Hwagye"):
        o.hide_set(True)
        o.hide_render = True
    out = {}
    out["terrain"] = retarget_terrain()
    out["stream"] = rebuild_stream()
    out["walls"] = level_walls()
    out["snap"] = snap_stream_props()
    out["clumps"] = plant_clumps()
    out["outer_pines"] = extra_outer_pines()
    return out


def polish_more():
    hide_guides()
    out = {"kits": hide_kit_sources()}
    out["terrain"] = retarget_terrain()
    out["stream"] = rebuild_stream()
    out["walls"] = level_walls()
    out["snap"] = snap_stream_props()
    out["dress"] = dress_banks()
    out["plants"] = plant_inner_garden()
    out["pines"] = plant_corner_pines()
    return out


def polish_layout():
    """Fix the awkward pass listed in the review."""
    report = {}
    report["guides"] = hide_guides()
    report["stream"] = rebuild_stream()
    report["walls"] = level_walls()

    # 광풍각 onto the east bank so the stream runs along its west side
    report["gwang_nudge"] = _nudge_group("SM_SSW_Gwangpunggak", dx=4.8)

    # 수구: center on the stream at the south outlet
    wg = _iter_group("SM_SSW_Water_Gate")
    bb = _group_minmax(wg) if wg else None
    if bb:
        cx = 0.5 * (bb[0] + bb[1])
        report["sugu_nudge"] = _nudge_group(
            "SM_SSW_Water_Gate", dx=-cx, dy=-39.5 - wg[0].location.y
        )
        # sit on banks, not in the trench
        bb2 = _group_minmax(wg)
        want = height_at(0.0, -39.5) + 0.15
        report["sugu_lift"] = _nudge_group("SM_SSW_Water_Gate", dz=want - bb2[4])

    # 물레방아 onto the east bank, just south of the outlet
    ww = bpy.data.objects.get("SM_SSW_Waterwheel")
    if ww:
        ww.location.x = 2.4
        ww.location.y = -46.5
        ww.rotation_euler = (0.0, 0.0, math.radians(-15))
        st = _mesh_stats(ww)
        ww.location.z += height_at(2.4, -46.5) - st["min_z"] - 0.05
        report["waterwheel"] = [round(v, 2) for v in ww.location]

    # 오곡문: lift out of the trench, keep it spanning the gate gap
    og = _iter_group("SM_SSW_Ogongmun_Gate")
    if og:
        bb = _group_minmax(og)
        want = height_at(0.0, -35.0) + 0.55
        report["ogongmun_lift"] = _nudge_group("SM_SSW_Ogongmun_Gate", dz=want - bb[4])

    # 우물
    well = bpy.data.objects.get("SM_SSW_Well")
    if well:
        st = _mesh_stats(well)
        well.location.z += height_at(well.location.x, well.location.y) - st["min_z"] - 0.04
        report["well_z"] = round(well.location.z, 3)

    # 연못: sink so the rim sits in the ground (they are 2.2 m tall boxes)
    for key, extra in (("SM_SSW_Upper_Pond", 1.65), ("SM_SSW_Lower_Pond", 1.45)):
        objs = _iter_group(key)
        if not objs:
            continue
        bb = _group_minmax(objs)
        report[key] = _nudge_group(key, dz=-extra)

    # 화계: plant it, don't leave it as a floating plinth
    hw = _iter_group("SM_SSW_Hwagye")
    if hw:
        report["hwagye"] = _nudge_group("SM_SSW_Hwagye", dz=-0.55)

    # 투죽위교 onto the water
    br = _iter_group("SM_SSW_Tujugwigyo")
    if br:
        bb = _group_minmax(br)
        # keep deck a bit above water
        water_z = height_at(0.0, -8.0) + 0.07
        # the bridge mesh min should be near water, deck higher
        report["bridge"] = _nudge_group("SM_SSW_Tujugwigyo", dz=(water_z - 0.15) - bb[4])

    report["backdrops"] = push_backdrops()
    return report


# ---------------------------------------------------------------- queue


OPS = {
    "boot": lambda _a: boot(),
    "clean": lambda _a: clean_default(),
    "collections": lambda _a: make_collections(),
    "guides": lambda _a: make_guides(),
    "terrain": lambda _a: make_terrain(),
    "upgrade_terrain": lambda _a: upgrade_terrain(),
    "trees": lambda _a: make_trees(),
    "lighting": lambda _a: make_lighting(),
    "gate": lambda _a: gate_scale(),
    "import": lambda a: _do_import(a),
    "place": lambda a: place(a),
    "save": lambda _a: save(),
    "report": lambda _a: scene_report(),
    "remove_placeholders": lambda _a: remove_placeholders(),
    "rebuild_walls": lambda _a: rebuild_walls(),
    "import_rock_d": lambda _a: import_rock_d(),
    "import_veg": lambda a: import_veg(a),
    "scatter_veg": lambda _a: scatter_heritage_veg(),
    "scatter_rocks": lambda _a: scatter_rocks(),
    "import_sanbangsan": lambda _a: import_sanbangsan(),
    "import_paddy": lambda _a: import_paddy(),
    "fix_sanbangsan": lambda _a: fix_sanbangsan(),
    "hide_guides": lambda _a: hide_guides(),
    "polish": lambda _a: polish_layout(),
    "soften_garden": lambda _a: soften_garden(),
    "polish_more": lambda _a: polish_more(),
    "polish_again": lambda _a: polish_again(),
    "polish_v7": lambda _a: polish_v7(),
    "finish_terrain": lambda _a: finish_terrain(),
    "ground_all": lambda _a: ground_all(),
}


def _snap_group_ground(prefix, sink=0.06):
    objs = [o for o in _iter_group(prefix) if not o.hide_render]
    if not objs:
        return None
    bb = _group_minmax(objs)
    cx = 0.5 * (bb[0] + bb[1])
    cy = 0.5 * (bb[2] + bb[3])
    want = height_at(cx, cy) - sink
    dz = want - bb[4]
    for o in objs:
        o.location.z += dz
    return round(dz, 3)


def _snap_obj_ground(o, sink=0.06):
    bb = _group_minmax([o])
    if not bb:
        return None
    cx = 0.5 * (bb[0] + bb[1])
    cy = 0.5 * (bb[2] + bb[3])
    dz = (height_at(cx, cy) - sink) - bb[4]
    o.location.z += dz
    return round(dz, 3)


def ground_all():
    """Sit every visible asset on the terrain. No more hovering walls."""
    hide_guides()
    hide_kit_sources()
    out = {"groups": {}, "walls": 0, "rocks": 0, "veg": 0}

    groups = [
        "SM_SSW_Gwangpunggak",
        "SM_SSW_Jewoldang_Hall",
        "SM_SSW_Chojeong_Pavilion",
        "SM_SSW_Daebongdae",
        "SM_SSW_Ogongmun_Gate",
        "SM_SSW_Hyeopmun",
        "SM_SSW_Water_Gate",
        "SM_SSW_Tujugwigyo",
    ]
    for g in groups:
        out["groups"][g] = _snap_group_ground(g, 0.05)

    for name in ("SM_SSW_Well", "SM_SSW_Waterwheel", "SM_SSW_Stair", "SM_SSW_Yakjak",
                 "SM_SSW_Rock_A", "SM_SSW_Rock_B", "SM_SSW_Inscribed_Rock"):
        o = bpy.data.objects.get(name)
        if o and not o.hide_render:
            out["groups"][name] = _snap_obj_ground(o, 0.07)

    # walls: each segment on its own dirt, slight bury
    n = 0
    for o in bpy.data.objects:
        if o.name.startswith("SM_SSW_Stonewall_") and not o.hide_render:
            _snap_obj_ground(o, 0.08)
            n += 1
    out["walls"] = n

    n = 0
    for o in bpy.data.objects:
        if (o.name.startswith("SM_SSW_BankRock_") or o.name.startswith("SM_SSW_RockScatter_")) and not o.hide_render:
            _snap_obj_ground(o, 0.12)
            n += 1
    out["rocks"] = n

    skip = {"VEG_Eulalia", "VEG_Artemisia", "VEG_BlackPine", "VEG_Vitex",
            "VEG_Lugose", "VEG_Anthephoroides"}
    n = 0
    for o in bpy.data.objects:
        if not o.name.startswith("VEG_"):
            continue
        if o.name in skip or o.hide_render:
            continue
        o.location.z = height_at(o.location.x, o.location.y)
        n += 1
    out["veg"] = n
    return out


def remove_toon_lines():
    killed = []
    for o in list(bpy.data.objects):
        if o.type == "GREASEPENCIL" or "ToonLines" in o.name:
            killed.append(o.name)
            bpy.data.objects.remove(o, do_unlink=True)
    return killed


def make_outer_plain():
    """Larger grass skirt so the 300 m plate does not float in a void."""
    old = bpy.data.objects.get("SSW_OuterPlain")
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
    mat = bpy.data.materials.get("M_SSW_TerrainPBR")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=48, y_segments=48, size=260.0)
    for v in bm.verts:
        # keep the inner 150 m hole almost flat-under, outer rolls down
        r = max(abs(v.co.x), abs(v.co.y))
        if r < 148.0:
            v.co.z = -0.35
        else:
            t = min(1.0, (r - 148.0) / 110.0)
            v.co.z = -0.35 - 6.0 * t * t
        v.co.z += 0.2 * math.sin(v.co.x * 0.04) * math.cos(v.co.y * 0.035)
    for f in bm.faces:
        f.smooth = True
    uv = bm.loops.layers.uv.new("UVMap")
    col = bm.loops.layers.color.new("blend")
    for face in bm.faces:
        for loop in face.loops:
            x, y = loop.vert.co.x, loop.vert.co.y
            loop[uv].uv = ((x + 260.0) / 10.0, (y + 260.0) / 10.0)
            loop[col] = (0.05, 0.0, 0.0, 1.0)  # almost all grass
    ob = _mesh_obj("SSW_OuterPlain", bm, "SSW_TERRAIN", mat)
    return ob.name


def finish_terrain():
    out = {"lines": remove_toon_lines()}
    out["terrain"] = retarget_terrain()
    out["outer"] = make_outer_plain()
    out["stream"] = rebuild_stream()
    # tone the neon dirt path under toon
    mat = bpy.data.materials.get("M_SSW_TerrainPBR")
    if mat and mat.node_tree.nodes.get("TOON_SAT"):
        mat.node_tree.nodes["TOON_SAT"].inputs["Saturation"].default_value = 1.25
        mat.node_tree.nodes["TOON_SAT"].inputs["Value"].default_value = 1.02
    wat = bpy.data.materials.get("M_SSW_Water")
    if wat and wat.use_nodes:
        for n in wat.node_tree.nodes:
            if n.type == "BSDF_PRINCIPLED":
                n.inputs["Roughness"].default_value = 0.28
                if "Transmission Weight" in n.inputs:
                    n.inputs["Transmission Weight"].default_value = 0.05
                if "Alpha" in n.inputs:
                    n.inputs["Alpha"].default_value = 0.92
            if n.name == "TOON_SAT":
                n.inputs["Saturation"].default_value = 1.25
                n.inputs["Value"].default_value = 0.95
    hide_guides()
    return out


def make_skydome():
    old = bpy.data.objects.get("SSW_SkyDome")
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=900.0)
    bmesh.ops.reverse_faces(bm, faces=bm.faces)
    mat = bpy.data.materials.get("M_SSW_Sky") or bpy.data.materials.new("M_SSW_Sky")
    mat.use_nodes = True
    mat.use_backface_culling = False
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    nt.links.new(tc.outputs["Object"], sep.inputs["Vector"])
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = -80.0
    mr.inputs["From Max"].default_value = 700.0
    nt.links.new(sep.outputs["Z"], mr.inputs["Value"])
    nt.links.new(mr.outputs["Result"], ramp.inputs["Fac"])
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (0.70, 0.74, 0.76, 1)
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = (0.42, 0.55, 0.70, 1)
    em.inputs["Strength"].default_value = 1.0
    nt.links.new(ramp.outputs["Color"], em.inputs["Color"])
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    dome = _mesh_obj("SSW_SkyDome", bm, "SSW_LIGHTING", mat)
    dome.visible_shadow = False
    try:
        dome.visible_diffuse = False
        dome.visible_glossy = False
    except Exception:
        pass
    return dome.name


def plant_hedge():
    """Shrubs along the inner wall to break the empty perimeter."""
    for o in list(bpy.data.objects):
        if o.name.startswith("VEG_Hedge_"):
            bpy.data.objects.remove(o, do_unlink=True)
    srcs = [bpy.data.objects.get(n) for n in ("VEG_Vitex", "VEG_Lugose", "VEG_Artemisia")]
    srcs = [s for s in srcs if s]
    if not srcs:
        return 0
    spots = []
    for x in (-20.5, 20.5):
        y = -28.0
        while y < 52:
            spots.append((x, y))
            y += 5.5
    for y in (52.5, -30.5):
        x = -16.0
        while x < 16:
            if abs(x) < 4 and y < 0:
                x += 5.5
                continue
            spots.append((x, y))
            x += 6.0
    n = 0
    for i, (x, y) in enumerate(spots):
        src = srcs[i % len(srcs)]
        inst = src.copy()
        inst.data = src.data
        inst.hide_set(False)
        inst.hide_render = False
        s = 0.7 + (i % 4) * 0.08
        inst.scale = (s, s, s)
        inst.rotation_euler.z = math.radians(i * 33)
        inst.location = (x, y, height_at(x, y))
        inst.name = "VEG_Hedge_%02d" % n
        _move_to(inst, "SSW_VEG")
        n += 1
    return n


def polish_v7():
    hide_guides()
    hide_kit_sources()
    out = {"sky": make_skydome()}
    out["terrain"] = retarget_terrain()
    out["hedge"] = plant_hedge()
    # extra grasses along the west wall and north court
    src = bpy.data.objects.get("VEG_Eulalia")
    extra = 0
    if src:
        for o in list(bpy.data.objects):
            if o.name.startswith("VEG_Fill7_"):
                bpy.data.objects.remove(o, do_unlink=True)
        for i in range(30):
            x = -17.0 + (i * 2.9) % 10
            y = -22.0 + (i * 3.7) % 66
            if abs(x - stream_x(y)) < 2.5:
                continue
            inst = src.copy()
            inst.data = src.data
            inst.hide_set(False)
            inst.hide_render = False
            s = 0.75 + (i % 4) * 0.07
            inst.scale = (s, s, s)
            inst.location = (x, y, height_at(x, y))
            inst.rotation_euler.z = math.radians(i * 47)
            inst.name = "VEG_Fill7_%02d" % extra
            _move_to(inst, "SSW_VEG")
            extra += 1
    out["fill"] = extra
    return out


def fix_sanbangsan():
    o = bpy.data.objects.get("SM_SSW_Sanbangsan")
    if o is None:
        return {"error": "missing sanbangsan"}
    st = _mesh_stats(o)
    minx, miny, minz = st["min"]
    maxx, maxy, maxz = st["max"]
    dx = -0.5 * (minx + maxx)
    dy = 180.0 - miny
    dz = -minz
    o.data.transform(Matrix.Translation((dx, dy, dz)))
    o.data.update()
    o.matrix_world = Matrix.Identity(4)
    st2 = _mesh_stats(o)
    _log("fix_sanbangsan %s -> %s" % (st, st2))
    return {"before": st, "after": st2}


def enqueue(op, arg=None):
    st = _state()
    st["queue"].append((op, arg))
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.05)
    return {"queued": len(st["queue"]), "op": op, "arg": arg}


def _tick():
    st = _state()
    if st["state"] == "running":
        return 0.2
    if not st["queue"]:
        st["state"] = "idle"
        return None
    op, arg = st["queue"].pop(0)
    st["state"] = "running"
    st["job"] = [op, arg]
    st["t0"] = time.time()
    try:
        fn = OPS[op]
        result = fn(arg)
        if not isinstance(result, dict):
            result = {"result": result}
        result["elapsed"] = round(time.time() - st["t0"], 2)
        st["last"] = result
    except Exception as e:
        import traceback
        st["last"] = {"error": str(e), "op": op, "trace": traceback.format_exc()[-800:]}
        _log("ERR %s %s" % (op, e))
    st["state"] = "idle"
    st["job"] = None
    return 0.05 if st["queue"] else None
