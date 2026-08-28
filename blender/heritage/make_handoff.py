# -*- coding: utf-8 -*-
"""인수인계용 압축본 생성.

04_Previews는 반복 렌더가 누적돼 217 MB다. 최종 세트만 담는다.
_extracted / _TexLib 는 반드시 포함해야 다른 PC에서 자립한다.
"""
import os
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(os.path.expanduser("~"), "Desktop",
                   "JSN_Sangok_handoff_20260814.zip")

KEEP_PREVIEW = ("walk_", "s34_", "now_", "vp_", "walkability")
INCLUDE_TOP = ("00_Source_Blender", "05_Documentation", "_TexLib",
               "_extracted", "_scripts")


def want(rel):
    p = rel.replace(os.sep, "/")
    if "/__pycache__/" in p or p.endswith(".pyc"):
        return False
    top = p.split("/")[0]
    if top == "04_Previews":
        return os.path.basename(p).startswith(KEEP_PREVIEW)
    return top in INCLUDE_TOP


def main():
    files, total = [], 0
    for r, ds, fs in os.walk(ROOT):
        ds[:] = [d for d in ds if d != "__pycache__"]
        for f in fs:
            full = os.path.join(r, f)
            rel = os.path.relpath(full, ROOT)
            if want(rel):
                files.append((full, rel))
                total += os.path.getsize(full)

    print("담을 파일 %d개 / %.1f MB" % (len(files), total / 1048576))
    t0 = time.time()
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for i, (full, rel) in enumerate(files):
            z.write(full, "JSN_Sangok/" + rel.replace(os.sep, "/"))
            if i % 200 == 0:
                print("  %d/%d" % (i, len(files)), flush=True)
    print("압축 %.0f초 -> %.1f MB" % (time.time() - t0,
                                       os.path.getsize(OUT) / 1048576))
    print(OUT)


if __name__ == "__main__":
    sys.exit(main())
