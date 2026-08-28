# -*- coding: utf-8 -*-
"""반입 진행 대장.

Studio가 중간에 죽어도 **어디까지 발행됐는지**를 잃지 않기 위한 것.
같은 파일을 다시 반입하면 교체가 아니라 **중복 발행**이 되므로, 재개할 때는
반드시 이 대장과 실제 에셋 테이블을 대조해 빠진 것만 올려야 한다.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVD = os.path.join(ROOT, "06_OVERDARE")
STATE = os.path.join(OVD, "import_state.json")
TABLE = r"C:\Work\blender-test\UGCLocalAssetTable.json"
SUBS = ("10_MASTERS", "01_TERRAIN", "02_STATIC")


def targets():
    out = []
    for sub in SUBS:
        d = os.path.join(OVD, sub)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.endswith("_overdare.fbx"):
                out.append({"dir": sub, "file": f,
                            "path": os.path.join(d, f),
                            "stem": f[:-len("_overdare.fbx")]})
    return out


def table_names():
    """에셋 테이블에 이미 올라간 이름들 (STATIC_MESH 기준)."""
    if not os.path.exists(TABLE):
        return {}
    d = json.load(open(TABLE, encoding="utf-8")).get("localAssetList", {})
    out = {}
    for k, v in d.items():
        out.setdefault(v.get("worldAssetType", "?"), {})[v.get("name", "")] = k
    return out


def status():
    tn = table_names()
    mesh = tn.get("STATIC_MESH", {})
    tex = tn.get("TEXTURE", {})
    done, todo = [], []
    for t in targets():
        # 번들 이름이 에셋 이름이 된다 — 파일 하나만 넘기므로 bundleName = stem 으로 맞춘다
        if t["stem"] in mesh:
            t["meshId"] = mesh[t["stem"]]
            done.append(t)
        else:
            todo.append(t)
    return {"done": done, "todo": todo, "textures": tex,
            "counts": {"done": len(done), "todo": len(todo)}}


def save(state):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def main():
    s = status()
    print("반입 완료 %d / 남음 %d" % (s["counts"]["done"], s["counts"]["todo"]))
    if s["todo"]:
        print("다음:", s["todo"][0]["file"])
    save({"done": [t["stem"] for t in s["done"]],
          "todo": [t["stem"] for t in s["todo"]]})
    print(STATE)


if __name__ == "__main__":
    sys.exit(main())
