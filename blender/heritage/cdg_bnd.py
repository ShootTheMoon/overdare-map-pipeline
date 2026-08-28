import math, bpy
FBX=r"C:\Work\blender\CDG_Changdeokgung\_extracted\FBX\Injeongjeon.fbx"
MATS=["MI_Capital01B","MI_GreenWood","MI_Gongpo01E"]
def tri(me):
    me.calc_loop_triangles(); return len(me.loop_triangles)
def submesh(src,mi):
    polys=[p for p in src.polygons if p.material_index==mi]
    vmap,verts,faces={},[],[]
    for p in polys:
        idx=[]
        for li in p.loop_indices:
            vi=src.loops[li].vertex_index
            if vi not in vmap: vmap[vi]=len(verts); verts.append(src.vertices[vi].co.copy())
            idx.append(vmap[vi])
        faces.append(tuple(idx))
    me=bpy.data.meshes.new("T"); me.from_pydata([tuple(v) for v in verts],[],faces); me.update(); return me
def ap(o):
    dg=bpy.context.evaluated_depsgraph_get()
    nm=bpy.data.meshes.new_from_object(o.evaluated_get(dg)); o.modifiers.clear(); o.data=nm
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=FBX,use_image_search=False,use_anim=False,use_custom_normals=False)
src=next(o for o in bpy.data.objects if o.type=="MESH")
names=[ms.material.name if ms.material else "" for ms in src.material_slots]
d0=bpy.data.meshes.new("probe")
for mat in MATS:
    base=submesh(src.data,names.index(mat)); bt=tri(base)
    # count open boundary edges
    import bmesh
    bm=bmesh.new(); bm.from_mesh(base)
    bnd=sum(1 for e in bm.edges if len(e.link_faces)<2); tot=len(bm.edges); bm.free()
    print("\n=== %s  src %,d tris  boundary edges %,d / %,d (%.1f%%)".replace(",d","d")%(mat,bt,bnd,tot,100.0*bnd/max(tot,1)))
    for ang in (5,30):
        for db in (False,True):
            o=bpy.data.objects.new("t",base.copy()); bpy.context.scene.collection.objects.link(o)
            m=o.modifiers.new("P","DECIMATE"); m.decimate_type="DISSOLVE"
            m.angle_limit=math.radians(ang); m.delimit={"UV"}; m.use_dissolve_boundaries=db
            ap(o)
            t=o.modifiers.new("T","TRIANGULATE"); t.min_vertices=4; ap(o)
            after=tri(o.data)
            c=o.modifiers.new("C","DECIMATE"); c.decimate_type="COLLAPSE"; c.ratio=0.02; c.use_collapse_triangulate=True
            ap(o); got=tri(o.data)
            print("   planar %2d deg  dissolve_boundaries=%-5s  after_planar %8d  final %8d  ratio %.4f"%(ang,db,after,got,got/bt))
            bpy.data.objects.remove(o,do_unlink=True)
