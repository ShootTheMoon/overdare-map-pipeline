# -*- coding: utf-8 -*-
"""placements.csv + asset_ids.json -> overdare_create_instances 용 itemsFile 배치 묶음.

에셋 ID는 **컴퓨터마다 다르다**. 다른 컴퓨터에서 FBX를 다시 발행하면 새 ID가
나오므로, asset_ids.json 을 그 컴퓨터의 UGCLocalAssetTable.json 기준으로 갱신한
뒤 이 스크립트를 돌린다.

  python ovd_place_build.py [--scale-mode percent|unit] [--limit N]

출력: 06_OVERDARE/_place/place_000.json ... (한 파일당 200개)
"""
import argparse
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVD = os.path.join(ROOT, "06_OVERDARE")
OUT = os.path.join(OVD, "_place")
BATCH = 200          # overdare_create_instances 의 itemsFile 한계


def refresh_ids(table_path):
    """실행 중인 컴퓨터의 에셋 테이블에서 이름->ID 를 다시 읽어 asset_ids.json 을 갱신."""
    d = json.load(open(table_path, encoding="utf-8")).get("localAssetList", {})
    mesh, tex = {}, {}
    for k, v in d.items():
        t, n = v.get("worldAssetType"), v.get("name", "")
        if t == "STATIC_MESH":
            mesh[n] = k
        elif t == "TEXTURE":
            tex[n] = k
    out = {}
    for n, mid in mesh.items():
        out[n] = {"meshId": mid, "textureId": tex.get(n, "")}
    p = os.path.join(OVD, "asset_ids.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("갱신 %d개 -> %s" % (len(out), p))
    miss = [n for n, v in out.items() if not v["textureId"]]
    if miss:
        print("텍스처 못 찾음:", miss)
    return out


def build(scale_mode="percent", limit=0):
    ids = json.load(open(os.path.join(OVD, "asset_ids.json"), encoding="utf-8"))
    rows = list(csv.DictReader(open(os.path.join(OVD, "placements.csv"), encoding="utf-8")))
    if limit:
        rows = rows[:limit]
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    for f in os.listdir(OUT):
        if f.startswith("place_") and f.endswith(".json"):
            os.remove(os.path.join(OUT, f))

    items, missing = [], set()
    for r in rows:
        a = ids.get(r["master"])
        if a is None:
            missing.add(r["master"])
            continue
        props = {
            "meshId": a["meshId"],
            "position": [float(r["X"]), float(r["Y"]), float(r["Z"])],
            "orientation": [float(r["pitch"]), float(r["yaw"]), float(r["roll"])],
            "anchored": True,
            "mobility": "Static",
            "castShadow": True,
            "raw": {"TextureId": a["textureId"]},
        }
        sx, sy, sz = float(r["sx"]), float(r["sy"]), float(r["sz"])
        if scale_mode == "percent":
            # 가설 A: Size 는 백분율. 임포트 직후 Size 가 항상 [100,100,100] 인 것과 부합
            props["size"] = [100.0 * sx, 100.0 * sy, 100.0 * sz]
        elif scale_mode == "unit":
            # 가설 B: Size 는 절대 스터드. UnitExtent(절반값)를 두 배 해서 곱한다
            props["size"] = [sx, sy, sz]
        items.append({"className": "MeshPart", "name": r["name"], "props": props})

    if missing:
        print("asset_ids.json 에 없는 마스터:", sorted(missing))
    n = 0
    for i in range(0, len(items), BATCH):
        p = os.path.join(OUT, "place_%03d.json" % n)
        json.dump(items[i:i + BATCH], open(p, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        n += 1
    print("인스턴스 %d개 -> %s 안에 %d 파일 (한 파일 %d개)" % (len(items), OUT, n, BATCH))
    print("호출: overdare_create_instances(itemsFile=<각 파일>) 를 %d회" % n)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", help="UGCLocalAssetTable.json 경로. 주면 asset_ids.json 을 먼저 갱신")
    ap.add_argument("--scale-mode", default="percent", choices=["percent", "unit"])
    ap.add_argument("--limit", type=int, default=0, help="앞에서 N개만 (검증용)")
    a = ap.parse_args()
    if a.table:
        refresh_ids(a.table)
    build(a.scale_mode, a.limit)


if __name__ == "__main__":
    sys.exit(main())
