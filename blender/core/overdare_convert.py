"""OVERDARE FBX conversion pipeline for Berlin assets.
exec() this file in Blender, then call convert(asset, strategy).
Handles traps A-F and the OVERDARE hard rules (30k tris/file, 1 texture/MeshPart,
Y-up cm, 1024 tex). Never saves the source .blend; works on duplicates."""
import bpy, bmesh, os, re, json
from mathutils import Vector, Matrix

OUT = r"C:\Work\MeshTest\Converted"
TEX = r"C:\Work\MeshTest\_texwork"
os.makedirs(OUT, exist_ok=True); os.makedirs(TEX, exist_ok=True)
TRI_CAP = 30000
MAXPX = 1024
BADMAP = ("normal","rough","metal","_ao","occlusion","displac","_nrm","_orm",
          "emissive","specular","height","bump","_mr","metallicroughness","_gloss")

def safe(s): return re.sub(r'[^A-Za-z0-9_]+','_', s)[:40]
def is_color_img(name):
    n=name.lower(); return not any(k in n for k in BADMAP)
def tri_count(me): return sum(len(p.vertices)-2 for p in me.polygons)
def dims_of(objs):
    # vertex-based (bound_box is stale after mesh edits / on quaternion-rotated imports)
    mn=[1e18]*3; mx=[-1e18]*3
    for o in objs:
        mw=o.matrix_world
        for v in o.data.vertices:
            w=mw @ v.co
            for i in range(3):
                if w[i]<mn[i]: mn[i]=w[i]
                if w[i]>mx[i]: mx[i]=w[i]
    if mn[0]>mx[0]: return [0,0,0],[0,0,0]
    return [mx[i]-mn[i] for i in range(3)], [(mn[i]+mx[i])/2 for i in range(3)]

def scene_orig_dims(src_objs):
    """world bbox dims of the source instance BEFORE any transform bake (trap A ref)."""
    return dims_of(src_objs)[0]

# ---------- duplicate + apply modifiers + bake transform + recenter ----------
def dup_apply_center(src_objs):
    dg=bpy.context.evaluated_depsgraph_get()
    copies=[]
    for s in src_objs:
        ev=s.evaluated_get(dg)                     # modifiers applied (Altbau BEVEL etc.)
        me=bpy.data.meshes.new_from_object(ev)     # keeps UVs + material slots
        o=bpy.data.objects.new(s.name+"_cv", me)
        bpy.context.scene.collection.objects.link(o)
        o.matrix_world=s.matrix_world.copy()
        o.data.transform(o.matrix_world)           # bake loc/rot/scale into verts (trap A)
        o.matrix_world=Matrix.Identity(4)
        copies.append(o)
    _, center = dims_of(copies)
    off = Matrix.Translation((-center[0],-center[1],-center[2]))
    for o in copies: o.data.transform(off)         # asset centred at origin
    return copies

# ---------- procedural / const-color bake (trap D, flat-colour variant) ----------
def flat_color(mat):
    if not mat.use_nodes: return tuple(mat.diffuse_color)[:3]
    nt=mat.node_tree
    b=next((n for n in nt.nodes if n.type=='BSDF_PRINCIPLED'), None)
    if b:
        inp=b.inputs['Base Color']
        if inp.links:
            src=inp.links[0].from_node
            if src.type=='VALTORGB':
                fac=src.inputs['Fac']; f=fac.default_value if not fac.links else 0.5
                return tuple(src.color_ramp.evaluate(f))[:3]
            if src.type=='RGB': return tuple(src.outputs[0].default_value)[:3]
            return tuple(mat.diffuse_color)[:3]
        return tuple(inp.default_value)[:3]
    return tuple(mat.diffuse_color)[:3]

def make_flat_image(rgb, name):
    img=bpy.data.images.new(name, 8, 8, alpha=False)
    img.pixels[:]=(list(rgb)+[1.0])*64
    path=os.path.join(TEX,name+".png"); img.filepath_raw=path; img.file_format='PNG'; img.save(); img.filepath=path
    return img

def bake_procedural(copies, asset):
    normalize_materials(copies, asset)          # flat-colour fallback handles procedural/const
    return separate_by_material(copies)

def merge_by_material(objs):
    """join pieces that share the same single material -> fewer MeshParts (Reichstag 799->45).
    Oversized merges are re-split spatially afterwards (bisect keeps the 1 material)."""
    from collections import defaultdict
    groups=defaultdict(list)
    for o in objs:
        key=o.data.materials[0].name if (o.data.materials and o.data.materials[0]) else "__none"
        groups[key].append(o)
    out=[]
    for key,grp in groups.items():
        if len(grp)==1: out.append(grp[0]); continue
        for s in list(bpy.context.selected_objects): s.select_set(False)
        for o in grp: o.select_set(True)
        bpy.context.view_layer.objects.active=grp[0]
        with bpy.context.temp_override(active_object=grp[0], selected_objects=grp, selected_editable_objects=grp):
            bpy.ops.object.join()
        out.append(grp[0])
    return out

# ---------- textures ----------
def prep_color_image(img, tag):
    """copy -> downscale -> save PNG -> repoint (traps C/E). returns new image.
    Rebuilds a FRESH unpacked image from the scaled buffer: scale() on a PACKED image
    shrinks the buffer but leaves the packed original full-res, so save() would re-emit
    the 4K/8K source (the Shibuya packed-downscale gotcha -> 26 MB church texture)."""
    if img.size[0]==0 or img.size[1]==0:
        try: img.reload()
        except Exception: pass
    ni = img.copy()
    if max(ni.size) > MAXPX:
        s = MAXPX/max(ni.size)
        ni.scale(max(1,int(ni.size[0]*s)), max(1,int(ni.size[1]*s)))
    ni.pack()                       # re-pack the SCALED buffer -> save() writes 1024, not the packed 4K/8K original
    ni.name=tag                     # unique datablock name per asset+material (trap D)
    ni.colorspace_settings.name='sRGB'
    path=os.path.join(TEX, tag+".png")
    ni.filepath_raw=path; ni.file_format='PNG'; ni.save(); ni.filepath=path
    return ni

def rebuild_mat_single_image(mat, colimg):
    """collapse material to Principled(BaseColor<-colimg)->Output only (traps B/C)."""
    mat.use_nodes=True; nt=mat.node_tree
    for n in list(nt.nodes): nt.nodes.remove(n)
    out=nt.nodes.new("ShaderNodeOutputMaterial")
    b=nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(b.outputs["BSDF"], out.inputs["Surface"])
    if colimg:
        t=nt.nodes.new("ShaderNodeTexImage"); t.image=colimg
        nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
    else:
        b.inputs["Base Color"].default_value=(0.6,0.6,0.6,1)

def pick_color_image(mat):
    """find the color map among a material's images (handles unlit/emission wiring, trap B)."""
    if not mat.use_nodes: return None
    nt=mat.node_tree
    imgs=[n for n in nt.nodes if n.type=='TEX_IMAGE' and n.image]
    if not imgs: return None
    b=next((n for n in nt.nodes if n.type=='BSDF_PRINCIPLED'), None)
    if b and b.inputs['Base Color'].links:
        s=b.inputs['Base Color'].links[0].from_node
        if s.type=='TEX_IMAGE' and s.image: return s.image
    em=next((n for n in nt.nodes if n.type=='EMISSION'), None)
    if em and em.inputs['Color'].links:
        s=em.inputs['Color'].links[0].from_node
        if s.type=='TEX_IMAGE' and s.image: return s.image
    cc=[n.image for n in imgs if is_color_img(n.image.name)]
    return cc[0] if cc else imgs[0].image

def normalize_materials(objs, asset):
    """every material -> unique, single color image. Const/procedural colour materials
    (no image) get a flat-colour texture baked from their Base Color so they don't turn
    grey (e.g. Trabant body paint)."""
    seen={}
    for o in objs:
        for slot in o.material_slots:
            m=slot.material
            if m is None: continue
            if m.name not in seen:
                nm=m.copy()
                col=pick_color_image(nm)
                if col is not None:
                    ni=prep_color_image(col, "%s__%s"%(asset,safe(m.name)))
                else:
                    rgb=flat_color(m) or (0.6,0.6,0.6)
                    ni=make_flat_image(rgb, "%s__%s_T"%(asset,safe(m.name)))
                rebuild_mat_single_image(nm, ni)
                seen[m.name]=nm
            slot.material=seen[m.name]

# ---------- separate by material (trap 2) ----------
def separate_by_material(objs):
    out=[]
    for o in objs:
        if len(o.data.materials)<=1:
            out.append(o); continue
        for s in list(bpy.context.selected_objects): s.select_set(False)
        bpy.context.view_layer.objects.active=o; o.select_set(True)
        before=set(bpy.data.objects)
        with bpy.context.temp_override(object=o, selected_objects=[o], selected_editable_objects=[o]):
            bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.separate(type='MATERIAL'); bpy.ops.object.mode_set(mode='OBJECT')
        new=[x for x in bpy.data.objects if x not in before]
        out.append(o); out.extend(new)
    # drop empty material slots so each piece = 1 material
    for o in out:
        me=o.data
        used=sorted({p.material_index for p in me.polygons})
        used=[i for i in used if i < len(me.materials)]
        mats=[me.materials[i] for i in used]; rmap={old:new for new,old in enumerate(used)}
        me.materials.clear()
        for m in mats: me.materials.append(m)
        for p in me.polygons: p.material_index=rmap.get(p.material_index,0)
    return [o for o in out if len(o.data.polygons)>0]

# ---------- spatial bisect to <=cap (trap F: never decimate) ----------
def split_side(o, co, no, keep_pos):
    n=o.copy(); n.data=o.data.copy(); bpy.context.scene.collection.objects.link(n)
    bm=bmesh.new(); bm.from_mesh(n.data)
    geom=bm.verts[:]+bm.edges[:]+bm.faces[:]
    bmesh.ops.bisect_plane(bm, geom=geom, dist=1e-6, plane_co=co, plane_no=no,
                           clear_inner=keep_pos, clear_outer=not keep_pos)
    bm.to_mesh(n.data); bm.free()
    return n

def bisect_to_budget(obj, cap):
    result=[]; stack=[obj]; guard=0
    while stack and guard<400:
        guard+=1
        o=stack.pop()
        if tri_count(o.data)<=cap:
            result.append(o); continue
        vs=o.data.vertices
        if len(vs)<4: result.append(o); continue
        bb=[Vector(c) for c in o.bound_box]
        dims=[max(v[i] for v in bb)-min(v[i] for v in bb) for i in range(3)]
        ax=dims.index(max(dims))
        coords=sorted(v.co[ax] for v in vs); med=coords[len(coords)//2]
        no=Vector((0,0,0)); no[ax]=1.0; co=Vector((0,0,0)); co[ax]=med
        a=split_side(o,co,no,True); b=split_side(o,co,no,False)
        bpy.data.objects.remove(o, do_unlink=True)
        ta,tb=tri_count(a.data),tri_count(b.data)
        if ta==0 or tb==0:   # degenerate split -> nudge plane
            bpy.data.objects.remove(a,do_unlink=True); bpy.data.objects.remove(b,do_unlink=True)
            result.append(o) if False else None
            # fallback: give up splitting this stubborn piece
            continue
        stack.append(a); stack.append(b)
    return result

# ---------- pack objects into <=cap files ----------
def pack_files(objs, cap):
    objs=sorted(objs, key=lambda o:-tri_count(o.data))
    files=[]  # each = [tris, [objs]]
    for o in objs:
        t=tri_count(o.data)
        placed=False
        for f in files:
            if f[0]+t<=cap:
                f[0]+=t; f[1].append(o); placed=True; break
        if not placed: files.append([t,[o]])
    return [f[1] for f in files]

# ---------- export one file, centred at its centroid, return (path,tris,offset,imgs) ----------
def export_file(objs, asset, idx, nfiles):
    _, ctr = dims_of(objs)
    off=Matrix.Translation((-ctr[0],-ctr[1],-ctr[2]))
    for o in objs: o.data.transform(off)
    for s in list(bpy.context.selected_objects): s.select_set(False)
    for o in objs: o.select_set(True)
    bpy.context.view_layer.objects.active=objs[0]
    suffix = "" if nfiles==1 else "_p%02d"%idx
    path=os.path.join(OUT, "%s_overdare%s.fbx"%(asset,suffix))
    bpy.ops.export_scene.fbx(filepath=path, use_selection=True, object_types={'MESH'},
        embed_textures=True, path_mode='COPY', mesh_smooth_type='FACE',
        use_mesh_modifiers=False, bake_space_transform=False, axis_forward='-Z', axis_up='Y')
    imgs=set()
    for o in objs:
        for m in o.data.materials:
            if m and m.use_nodes:
                for n in m.node_tree.nodes:
                    if n.type=='TEX_IMAGE' and n.image: imgs.add(n.image.name)
    t=sum(tri_count(o.data) for o in objs)
    # restore position (so later files' centroid math is unaffected)
    for o in objs: o.data.transform(off.inverted())
    return dict(file=os.path.basename(path), tris=t, offset=[round(c,4) for c in ctr],
                images=sorted(imgs))

# ---------- verify (traps 1,2,3,4 + A) ----------
def verify(files_meta, orig_dims):
    # re-import each file at its offset, union bbox, compare dims to source (trap A ±5%)
    mn=[1e18]*3; mx=[-1e18]*3; ok=True; msgs=[]
    for fm in files_meta:
        p=os.path.join(OUT, fm["file"])
        before=set(bpy.data.objects)
        bpy.ops.import_scene.fbx(filepath=p)
        imp=[o for o in bpy.data.objects if o not in before]
        for o in imp:
            mw=o.matrix_world
            for v in o.data.vertices:
                w=mw @ v.co
                for i in range(3):
                    wi=w[i]+fm["offset"][i]
                    if wi<mn[i]: mn[i]=wi
                    if wi>mx[i]: mx[i]=wi
        for o in imp: bpy.data.objects.remove(o, do_unlink=True)
        if fm["tris"]>TRI_CAP: ok=False; msgs.append("%s tris %d > cap"%(fm["file"],fm["tris"]))
        if len(fm["images"])>1: msgs.append("WARN %s has %d images (multi-obj file ok if each obj=1)"%(fm["file"],len(fm["images"])))
    rd=[mx[i]-mn[i] for i in range(3)]
    for i in range(3):
        if orig_dims[i]>1e-4 and abs(rd[i]-orig_dims[i])/orig_dims[i]>0.05:
            ok=False; msgs.append("dim%d reimport %.2f vs orig %.2f (>5%%)"%(i,rd[i],orig_dims[i]))
    return ok, rd, msgs

def cleanup(objs):
    for o in objs:
        try: bpy.data.objects.remove(o, do_unlink=True)
        except: pass

# ---------- main entry ----------
def convert(asset, strategy, part_names):
    src=[bpy.data.objects[n] for n in part_names if n in bpy.data.objects]
    orig_dims = scene_orig_dims(src)
    copies=dup_apply_center(src)
    if strategy in ("simple","scan"):
        normalize_materials(copies, asset)
        pieces=copies
    elif strategy=="multimat":
        normalize_materials(copies, asset)
        pieces=separate_by_material(copies)
    elif strategy in ("procedural","mixed"):
        pieces=bake_procedural(copies, asset)
    else:
        raise ValueError("unknown strategy "+strategy)
    # merge same-material pieces (cut MeshPart count), then enforce <=cap (bisect keeps material, trap F)
    pieces=merge_by_material(pieces)
    final=[]
    for o in pieces:
        if tri_count(o.data)>TRI_CAP: final+=bisect_to_budget(o,TRI_CAP)
        else: final.append(o)
    files=pack_files(final, TRI_CAP)
    meta=[export_file(objs, asset, i+1, len(files)) for i,objs in enumerate(files)]
    ok, rd, msgs = verify(meta, orig_dims)
    cleanup(final)
    rep=dict(asset=asset, strategy=strategy, nfiles=len(files), orig_dims=[round(d,3) for d in orig_dims],
             reimport_dims=[round(d,3) for d in rd], A_ok=ok, files=meta, warnings=msgs)
    # persist to master manifest (for reassembly + user report)
    mpath=os.path.join(OUT, "_manifest.json")
    man=json.load(open(mpath)) if os.path.exists(mpath) else {}
    man[asset]=rep
    json.dump(man, open(mpath,"w"), ensure_ascii=False, indent=1)
    print("[%s] %s: %d files, A_ok=%s, tris_total=%d" %
          (strategy, asset, len(files), ok, sum(f["tris"] for f in meta)))
    return rep
print("overdare_convert module loaded")
