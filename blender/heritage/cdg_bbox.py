import bpy,os,collections
from mathutils import Vector
M=r"C:\Work\blender\CDG_Changdeokgung\20_ARCHITECTURE\CDG_Master.blend"
bpy.ops.wm.open_mainfile(filepath=M)
agg=collections.defaultdict(lambda:[1e18,1e18,1e18,-1e18,-1e18,-1e18])
for o in bpy.data.objects:
    if o.type!="MESH" or o.name.startswith("GUIDE_"): continue
    key=o.name.split("_")[2] if o.name.startswith("SM_CDG_") else "OTHER"
    b=agg[key]; mw=o.matrix_world
    for v in o.data.vertices:
        w=mw@v.co
        for i in range(3):
            b[i]=min(b[i],w[i]); b[i+3]=max(b[i+3],w[i])
print("%-20s %8s %8s %8s %8s %8s %8s"%("asset","xmin","xmax","ymin","ymax","zmin","zmax"))
for k in sorted(agg,key=lambda k:agg[k][1]):
    b=agg[k]
    print("%-20s %8.1f %8.1f %8.1f %8.1f %8.1f %8.1f"%(k,b[0],b[3],b[1],b[4],b[2],b[5]))
