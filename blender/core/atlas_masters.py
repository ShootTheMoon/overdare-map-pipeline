"""Atlas the 66 instance masters - plan, bake and apply in one pass.

Separate from atlas_pack.py because the grouping is different in a way that matters: a master
is ONE shared mesh datablock instanced thousands of times, so remapping it once moves every
copy. The static files group many distinct meshes; here each master is its own group and its
own sheet, sized to what it actually holds rather than a fixed 4096.

    211 materials now -> 141 after
     11 masters are entirely tiling and are left alone
     53 need a 2048 sheet, 2 need 1024

The gap between 141 and the 66 that a full collapse would give is the 70 TILING materials -
the box-projected ones from this session (M_ZK_Frame on every signboard, M_UP_* on the pole,
the imported vehicle materials). Folding those in would mean replacing a world-space box
projection with a 0..1 crop, which is defensible on a 60-triangle signboard and risky on a
vehicle, so it is deliberately not done here.

Runs system Python for the blit and Blender for the UV work, like the static path:
    blender --background <scene> --python atlas_masters.py -- plan   <atlas_dir>
    python  atlas_masters.py bake  <atlas_dir>
    blender --background <scene> --python atlas_masters.py -- apply  <atlas_dir>
"""
import os
import sys
import json

MODE = None
ATLAS = r"C:\Work\MeshTest\_ATLAS_MASTERS"
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
if argv:
    MODE = argv[0]
    if len(argv) > 1:
        ATLAS = argv[1]
PLAN = os.path.join(ATLAS, "_master_plan.json")
PAD = 4
TOL = 0.05      # matches do_plan()'s tiling threshold; see the guard in do_apply
MT = r"C:\Work\MeshTest"
BLEND_DIR = r"C:\Work\blender\Shibuya"
TEXW = os.path.join(MT, "_texwork_v14")


# ----------------------------------------------------------------- shared: packing
def shelf_pack(items, sheet, pad):
    items = sorted(items, key=lambda it: -it[2])
    place = {}
    x = y = row_h = 0
    for key, w, h in items:
        w2, h2 = w + pad * 2, h + pad * 2
        if w2 > sheet or h2 > sheet:
            return None
        if x + w2 > sheet:
            x = 0; y += row_h; row_h = 0
        if y + h2 > sheet:
            return None
        place[key] = (x + pad, y + pad, w, h)
        x += w2
        row_h = max(row_h, h2)
    return place


# ----------------------------------------------------------------- plan (Blender)
def do_plan():
    import bpy
    sys.path.insert(0, MT)
    from texture_caps import cap_for
    G = {"bpy": bpy, "__name__": "sx2"}
    exec(compile(open(os.path.join(MT, "shibuya_export_v2.py"), encoding="utf-8").read(),
                 "sx2", "exec"), G)
    man = json.load(open(os.path.join(MT, "Shibuya_OVERDARE_v14",
                                      "_manifest_masters.json"), encoding="utf-8"))
    masters = {m["master"] for m in man}

    def dsize(im):
        c = cap_for(im.name); w, h = im.size
        if not w or not h:
            return (0, 0)
        k = min(1.0, c / float(max(w, h)))
        return (max(1, int(w * k)), max(1, int(h * k)))

    recs, seen = [], set()
    for cn in G["INSTANCED_COLLECTIONS"]:
        c = bpy.data.collections.get(cn)
        if not c:
            continue
        for o in c.objects:
            if o.type != 'MESH' or not o.data.polygons or not o.data.uv_layers:
                continue
            base = o.data.name.split('.')[0]
            if base not in masters or base in seen:
                continue
            seen.add(base)
            me = o.data
            uvl = me.uv_layers[0].data
            names = [m.name if m else "" for m in me.materials]
            rng = {}
            for p in me.polygons:
                mn = names[p.material_index] if p.material_index < len(names) else ""
                for li in p.loop_indices:
                    u, v = uvl[li].uv
                    lo, hi = rng.get(mn, (1e9, -1e9))
                    rng[mn] = (min(lo, u, v), max(hi, u, v))
            imgs, sizes, tiling = {}, {}, []
            for m in me.materials:
                if not m or not m.use_nodes:
                    continue
                lo, hi = rng.get(m.name, (0.0, 0.0))
                if lo < -0.05 or hi > 1.05:
                    tiling.append(m.name)
                    continue
                im = None
                for n in m.node_tree.nodes:
                    if n.type == 'TEX_IMAGE' and n.image and "FacadeDetail" not in n.image.name:
                        if im is None or max(n.image.size) > max(im.size):
                            im = n.image
                if im is None:
                    continue
                imgs[m.name] = im.filepath
                sizes[m.name] = list(dsize(im))
            if not imgs:
                continue
            px = sum(w * h for w, h in sizes.values())
            sheet = next((s for s in (256, 512, 1024, 2048, 4096) if s * s >= px * 1.35), 4096)
            place = shelf_pack([(k, sizes[k][0], sizes[k][1]) for k in sizes], sheet, PAD)
            while place is None and sheet < 4096:
                sheet *= 2
                place = shelf_pack([(k, sizes[k][0], sizes[k][1]) for k in sizes], sheet, PAD)
            recs.append({"master": base, "mesh": me.name, "sheet": sheet,
                         "images": imgs, "sizes": sizes, "tiling": sorted(set(tiling)),
                         "rects": {k: list(v) for k, v in (place or {}).items()},
                         "fits": place is not None})
    os.makedirs(ATLAS, exist_ok=True)
    json.dump(recs, open(PLAN, "w"), indent=1)
    before = sum(len(r["rects"]) + len(r["tiling"]) for r in recs)
    after = sum(1 + len(r["tiling"]) for r in recs)
    print("  planned %d masters | do not fit: %d" % (len(recs), sum(1 for r in recs if not r["fits"])))
    print("  their import units: %d -> %d" % (before, after))
    print("  wrote %s" % PLAN)


# ----------------------------------------------------------------- bake (PIL)
def do_bake():
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None

    def resolve(src, mat):
        """EX_ copy first, then the blend-relative original, then the _raw unpack.

        The four vehicles came from a Sketchfab import and their images still point into a
        temp folder that no longer exists - they live only inside the .blend as packed data.
        scan_textures.py already wrote those out to _texwork_v14/_raw when it prepared v14,
        so the pixels are on disk under the ORIGINAL filename rather than the material name.
        Without this branch 40 of 94 vehicle rects baked as empty background.
        """
        ex = os.path.join(TEXW, "EX_" + mat.split('.')[0] + ".png")
        if os.path.exists(ex):
            return ex
        if src.startswith("//"):
            p = os.path.join(BLEND_DIR, src[2:].replace('/', os.sep))
            if os.path.exists(p):
                return p
        elif src and os.path.exists(src):
            return src
        raw = os.path.join(TEXW, "_raw")
        if src:
            stem = os.path.basename(src.replace(chr(92), '/'))
            for cand in (stem, stem + ".png"):
                p = os.path.join(raw, cand)
                if os.path.exists(p):
                    return p
        return ""

    def bleed(sheet, box, pad):
        x, y, w, h = box
        sheet.paste(sheet.crop((x, y, x + 1, y + h)).resize((pad, h)), (x - pad, y))
        sheet.paste(sheet.crop((x + w - 1, y, x + w, y + h)).resize((pad, h)), (x + w, y))
        sheet.paste(sheet.crop((x - pad, y, x + w + pad, y + 1)).resize((w + 2 * pad, pad)),
                    (x - pad, y - pad))
        sheet.paste(sheet.crop((x - pad, y + h - 1, x + w + pad, y + h)).resize((w + 2 * pad, pad)),
                    (x - pad, y + h))

    plan = json.load(open(PLAN, encoding="utf-8"))
    n, miss = 0, 0
    for rec in plan:
        if not rec["fits"]:
            continue
        S = rec["sheet"]
        sheet = Image.new("RGB", (S, S), (28, 28, 30))
        ok = 0
        for mat, (x, y, w, h) in rec["rects"].items():
            src = resolve(rec["images"].get(mat, ""), mat)
            if not src:
                miss += 1
                continue
            im = Image.open(src).convert("RGB")
            if im.size != (w, h):
                im = im.resize((w, h), Image.LANCZOS)
            sheet.paste(im, (x, y))
            bleed(sheet, (x, y, w, h), PAD)
            ok += 1
        p = os.path.join(ATLAS, "ATLASM_%s.png" % rec["master"])
        sheet.save(p, optimize=True)
        n += 1
        print("  %-34s %2d/%2d rects  %d px  %5.2f MB"
              % (os.path.basename(p), ok, len(rec["rects"]), S,
                 os.path.getsize(p) / 1048576.0))
    print("\n  baked %d master sheets | missing sources: %d" % (n, miss))


# ----------------------------------------------------------------- apply (Blender)
def do_apply():
    import bpy
    plan = json.load(open(PLAN, encoding="utf-8"))
    n_mesh = n_face = n_skip = 0
    for rec in plan:
        if not rec["fits"] or not rec["rects"]:
            continue
        me = bpy.data.meshes.get(rec["mesh"])
        if me is None or not me.uv_layers:
            print("     !! mesh %s missing" % rec["mesh"])
            continue
        S = rec["sheet"]
        name = "M_ATLM_" + rec["master"]
        m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        out = nt.nodes.new('ShaderNodeOutputMaterial'); out.location = (420, 0)
        b = nt.nodes.new('ShaderNodeBsdfPrincipled'); b.location = (160, 0)
        t = nt.nodes.new('ShaderNodeTexImage'); t.location = (-260, 0)
        t.image = bpy.data.images.load(os.path.join(ATLAS, "ATLASM_%s.png" % rec["master"]),
                                       check_existing=True)
        t.extension = 'CLIP'
        nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
        b.inputs["Roughness"].default_value = 0.72
        nt.links.new(b.outputs["BSDF"], out.inputs["Surface"])

        uvl = me.uv_layers[0].data
        names = [x.name if x else "" for x in me.materials]
        if name in names:
            slot = names.index(name)
        else:
            me.materials.append(m)
            names.append(name)
            slot = len(me.materials) - 1
        for p in me.polygons:
            mn = names[p.material_index] if p.material_index < len(names) else ""
            r = rec["rects"].get(mn)
            if r is None:
                continue
            # TOL is the same threshold do_plan() used to call a material tiling, so the guard
            # and the classification agree. At 0.001 they did not, and any material with a
            # small authoring overshoot was classified atlasable and then rejected face by
            # face - atlased in the plan, unatlased in the file, and still counted as a
            # delivered material.
            uvs = [tuple(uvl[li].uv) for li in p.loop_indices]
            if any(c < -TOL or c > 1.0 + TOL for uv in uvs for c in uv):
                n_skip += 1
                continue
            x, y, w, h = r
            for li, (u, v) in zip(p.loop_indices, uvs):
                # clamp into the rect; the 4-texel gutter is narrower than TOL allows
                u = 0.0 if u < 0.0 else (1.0 if u > 1.0 else u)
                v = 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)
                uvl[li].uv = ((x + u * w) / S, 1.0 - (y + (1.0 - v) * h) / S)
            p.material_index = slot
            n_face += 1
        n_mesh += 1
    print("  masters atlased: %d meshes, %s faces, %d skipped by the UV guard"
          % (n_mesh, format(n_face, ','), n_skip))

    # Drop the now-unused original slots. The exporter walks me.materials, so an unused slot
    # is still a delivered material and still an import unit. Indices are captured BEFORE
    # clear(), which resets every material_index to 0.
    n_slot = 0
    for me2 in bpy.data.meshes:
        if not me2.polygons or not me2.materials:
            continue
        used = sorted({p.material_index for p in me2.polygons})
        if len(used) >= len(me2.materials):
            continue
        keep = [me2.materials[i] for i in used if i < len(me2.materials)]
        remap = {o: n for n, o in enumerate(used)}
        idx = [remap.get(p.material_index, 0) for p in me2.polygons]
        n_slot += len(me2.materials) - len(keep)
        me2.materials.clear()
        for m2 in keep:
            me2.materials.append(m2)
        for p, i in zip(me2.polygons, idx):
            p.material_index = i
    print("  pruned %d unused material slots" % n_slot)
    # verify
    bad = 0
    for me in bpy.data.meshes:
        if not me.uv_layers:
            continue
        names = [x.name if x else "" for x in me.materials]
        if not any(n.startswith("M_ATLM_") for n in names):
            continue
        uvl = me.uv_layers[0].data
        for p in me.polygons:
            if p.material_index >= len(names) or not names[p.material_index].startswith("M_ATLM_"):
                continue
            for li in p.loop_indices:
                u, v = uvl[li].uv
                if u < -1e-4 or u > 1.0001 or v < -1e-4 or v > 1.0001:
                    bad += 1
                    break
    print("  verify: UV outside 0..1 on a master atlas: %d" % bad)
    return bad == 0


if __name__ == "__main__":
    if MODE == "plan":
        do_plan()
    elif MODE == "bake":
        do_bake()
    elif MODE == "apply":
        ok = do_apply()
        import bpy
        if ok:
            bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath, compress=False)
            print("SAVED %.1f MB" % (os.path.getsize(bpy.data.filepath) / 1048576.0))
        else:
            print("!! verify FAILED - not saving")
    else:
        print("usage: plan | bake | apply")
    print("MASTER ATLAS %s DONE" % (MODE or "?"))
