import math, os, sys, bpy
from mathutils import Vector
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
ROOT=r"C:\Work\blender\CDG_Changdeokgung"
MASTER=os.path.join(ROOT,"20_ARCHITECTURE","CDG_Master.blend")
OUT=os.path.join(ROOT,"_renders")
TEXLIB=os.path.join(ROOT,"_extracted","_TexLib")
bpy.ops.wm.open_mainfile(filepath=MASTER)
# Do NOT relink/reload here. The FBX import embedded these textures and they are
# PACKED in the reduced blends, so the packed data is already the correct pixels.
# Calling reload() on a packed image whose original external path is gone crashed
# Blender outright (the known use-after-free signature).
npack=sum(1 for i in bpy.data.images if i.packed_file)
print("images %d, packed %d"%(len(bpy.data.images),npack))
lo=Vector((1e18,)*3); hi=Vector((-1e18,)*3)
for o in bpy.data.objects:
    if o.type!="MESH": continue
    for v in o.data.vertices:
        w=o.matrix_world@v.co
        for i in range(3):
            lo[i]=min(lo[i],w[i]); hi[i]=max(hi[i],w[i])
print("extent X %.1f..%.1f  Y %.1f..%.1f  Z %.1f..%.1f"%(lo.x,hi.x,lo.y,hi.y,lo.z,hi.z))
w=bpy.data.worlds[0] if bpy.data.worlds else bpy.data.worlds.new("W")
bpy.context.scene.world=w; w.use_nodes=True
bg=w.node_tree.nodes.get("Background")
if bg: bg.inputs[0].default_value=(0.60,0.70,0.85,1.0); bg.inputs[1].default_value=1.5
ld=bpy.data.lights.new("Sun","SUN"); ld.energy=4.0; ld.angle=math.radians(2.0)
so=bpy.data.objects.new("Sun",ld); bpy.context.scene.collection.objects.link(so)
so.rotation_euler=(math.radians(50),0,math.radians(30))
ctr=(lo+hi)*0.5
sc=bpy.context.scene
avail=sc.render.bl_rna.properties["engine"].enum_items.keys()
for e in ("BLENDER_EEVEE_NEXT","BLENDER_EEVEE","CYCLES"):
    if e in avail: sc.render.engine=e; break
try: sc.eevee.taa_render_samples=8
except Exception: pass
sc.render.resolution_x=1400; sc.render.resolution_y=950
sc.view_settings.view_transform="AgX"; sc.render.image_settings.file_format="PNG"
def shot(name,loc,look,lens=45):
    for c in [o for o in bpy.data.objects if o.type=="CAMERA"]: bpy.data.objects.remove(c,do_unlink=True)
    cd=bpy.data.cameras.new("C"); cd.lens=lens
    cam=bpy.data.objects.new("C",cd); bpy.context.scene.collection.objects.link(cam)
    sc.camera=cam; cam.location=loc
    cam.rotation_euler=(Vector(look)-Vector(loc)).to_track_quat('-Z','Y').to_euler()
    sc.render.filepath=os.path.join(OUT,name)
    bpy.ops.render.render(write_still=True); print("  ",sc.render.filepath)
# hide the OSM guide plates for presentation renders
for o in bpy.data.objects:
    if o.name.startswith("GUIDE_"):
        o.hide_render=True
shot("MAP_aerial.png",(150,-300,205),(-35,-25,4),34)
shot("MAP_aerial2.png",(-260,60,150),(-30,-20,6),34)
shot("MAP_court_eye.png",(2.0,-58.0,1.7),(1.0,-8.0,14.0),30)
shot("MAP_seonwonjeon_eye.png",(-40.0,-30.0,9.0),(-85.0,20.0,8.0),32)
shot("MAP_gwollaegaksa_eye.png",(-101.0,-22.0,1.7),(-131.0,-44.0,7.0),30)
