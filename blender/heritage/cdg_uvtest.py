import bpy
FBX=r"C:\Work\blender\CDG_Changdeokgung\_extracted\FBX\Injeongjeon.fbx"
def tri(me):
    me.calc_loop_triangles(); return len(me.loop_triangles)
def submesh(src,mi,with_uv):
    polys=[p for p in src.polygons if p.material_index==mi]
    vmap,verts,faces,uvs={},[],[],[]
    uvl=src.uv_layers[0] if src.uv_layers else None
    for p in polys:
        idx=[]
        for li in p.loop_indices:
            vi=src.loops[li].vertex_index
            if vi not in vmap: vmap[vi]=len(verts); verts.append(src.vertices[vi].co.copy())
            idx.append(vmap[vi]); uvs.append(tuple(uvl.uv[li].vector) if uvl else (0,0))
        faces.append(tuple(idx))
    me=bpy.data.meshes.new("T"); me.from_pydata([tuple(v) for v in verts],[],faces); me.update()
    if with_uv and uvl:
        lay=me.uv_layers.new(name="UVMap"); flat=[]
        for u,v in uvs: flat+=[u,v]
        if len(flat)==len(me.loops)*2: lay.uv.foreach_set("vector",flat)
    return me
def ap(o):
    dg=bpy.context.evaluated_depsgraph_get()
    nm=bpy.data.meshes.new_from_object(o.evaluated_get(dg)); o.modifiers.clear(); o.data=nm
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=FBX,use_image_search=False,use_anim=False,use_custom_normals=False)
src=next(o for o in bpy.data.objects if o.type=="MESH")
names=[ms.material.name if ms.material else "" for ms in src.material_slots]
print("\n%-18s %10s %8s %12s %12s"%("material","src","has_uv","collapsed","ratio"))
for mat in ["MI_Capital01B","MI_GreenWood","MI_Gongpo01E"]:
    mi=names.index(mat)
    for wuv in (True,False):
        me=submesh(src.data,mi,wuv); bt=tri(me)
        o=bpy.data.objects.new("t",me); bpy.context.scene.collection.objects.link(o)
        d=o.modifiers.new("D","DECIMATE"); d.decimate_type="COLLAPSE"; d.ratio=0.02; d.use_collapse_triangulate=True
        ap(o); got=tri(o.data)
        print("%-18s %10d %8s %12d %12.4f"%(mat,bt,wuv,got,got/bt))
        bpy.data.objects.remove(o,do_unlink=True)
