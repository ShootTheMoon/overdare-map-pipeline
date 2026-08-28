"""Direct client for the BlenderMCP addon socket (127.0.0.1:9876).

The MCP bridge process is what keeps failing, not Blender. The addon itself answers
fine, so this talks to it straight over TCP and skips the bridge entirely.

  python bl.py info                 -> scene summary
  python bl.py run script.py        -> execute a file in Blender
  python bl.py -                    -> execute stdin
"""
import socket, json, sys, time

HOST, PORT, TIMEOUT = "127.0.0.1", 9876, 600.0


def call(mtype, params=None, timeout=TIMEOUT):
    s = socket.socket()
    s.settimeout(timeout)
    s.connect((HOST, PORT))
    s.sendall(json.dumps({"type": mtype, "params": params or {}}).encode())
    buf = b""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            d = s.recv(1 << 20)
        except socket.timeout:
            break
        if not d:
            break
        buf += d
        try:
            return json.loads(buf.decode())
        except Exception:
            continue
    s.close()
    raise RuntimeError("no complete reply (%d bytes)" % len(buf))


def run_code(code):
    r = call("execute_code", {"code": code})
    if r.get("status") != "success":
        print("ERROR:", r.get("message") or r)
        return 1
    res = r.get("result", {})
    print(res.get("result", res) if isinstance(res, dict) else res)
    return 0


def sk_search(query, count=12, downloadable=True):
    r = call("search_sketchfab_models",
             {"query": query, "count": count, "downloadable": downloadable}, timeout=90)
    out = []
    for m in (r.get("result") or {}).get("results", []):
        lic = (m.get("license") or {}).get("label") or (m.get("license") or {}).get("slug") or "?"
        out.append({"uid": m["uid"], "name": m.get("name"),
                    "author": ((m.get("user") or {}).get("username")),
                    "faces": m.get("faceCount"), "license": lic,
                    "downloadable": m.get("isDownloadable")})
    return out


def sk_download(uid, target_size=None):
    """The addon imports at native scale. target_size normalisation is done here by
    measuring the imported objects, exactly as the MCP wrapper used to."""
    r = call("download_sketchfab_model", {"uid": uid}, timeout=600)
    if r.get("status") != "success":
        return r
    if target_size:
        run_code("""
import bpy
from mathutils import Vector
sel=[o for o in bpy.context.selected_objects if o.type=='MESH'] or \\
    [o for o in bpy.data.objects if o.type=='MESH']
pts=[o.matrix_world @ Vector(c) for o in sel for c in o.bound_box]
if pts:
    mn=[min(p[i] for p in pts) for i in range(3)]; mx=[max(p[i] for p in pts) for i in range(3)]
    d=max(mx[i]-mn[i] for i in range(3))
    s=%f/d if d>1e-9 else 1.0
    roots=[o for o in sel if o.parent is None] or sel
    for o in roots: o.scale=[v*s for v in o.scale]
    bpy.context.view_layer.update()
    print("scaled by %%.6f -> %%.3f m" %% (s, d*s))
""" % float(target_size))
    return r


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "info":
        print(json.dumps(call("get_scene_info"), ensure_ascii=False, indent=1))
    elif a[0] == "run":
        sys.exit(run_code(open(a[1], encoding="utf-8").read()))
    elif a[0] == "-":
        sys.exit(run_code(sys.stdin.read()))
    elif a[0] == "sk":                       # bl.py sk "query" [count]
        for m in sk_search(a[1], int(a[2]) if len(a) > 2 else 12):
            print("%-34s %-22s %8s  %-18s %s" % (
                m["uid"], (m["author"] or "")[:22], m["faces"], m["license"][:18], m["name"]))
    elif a[0] == "skdl":                     # bl.py skdl <uid> [target_size]
        print(json.dumps(sk_download(a[1], a[2] if len(a) > 2 else None),
                         ensure_ascii=False)[:400])
    elif a[0] == "status":
        for t in ("get_sketchfab_status", "get_polyhaven_status", "get_hyper3d_status"):
            print("%-22s %s" % (t, call(t, {}, 20).get("result", {}).get("message")))
    else:
        sys.exit(run_code(" ".join(a)))
