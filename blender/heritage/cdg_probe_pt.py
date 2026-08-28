import bpy
from mathutils import Vector
M=r"C:\Work\blender\CDG_Changdeokgung\20_ARCHITECTURE\CDG_Master.blend"
bpy.ops.wm.open_mainfile(filepath=M)
P=Vector((-100.0,-72.0,1.8)); R=14.0
hits=[]
for o in bpy.data.objects:
    if o.type!='MESH' or o.name.startswith('GUIDE_'): continue
    mw=o.matrix_world
    lo=[1e18]*3; hi=[-1e18]*3; near=False
    for v in o.data.vertices:
        w=mw@v.co
        for i in range(3):
            lo[i]=min(lo[i],w[i]); hi[i]=max(hi[i],w[i])
    if lo[0]-R<=P.x<=hi[0]+R and lo[1]-R<=P.y<=hi[1]+R and lo[2]<=P.z+12 and hi[2]>=P.z-4:
        hits.append((o.name, [round(v,1) for v in lo],[round(v,1) for v in hi]))
hits.sort(key=lambda t:-(t[2][2]))
print("geometry overlapping the camera cell (-100,-72,1.8):", len(hits))
for n,lo,hi in hits[:14]:
    print("   {:<46} z {:>6.1f}..{:<6.1f} xy {}..{}".format(n[:45],lo[2],hi[2],lo[:2],hi[:2]))
