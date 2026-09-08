# -*- coding: utf-8 -*-
"""
Blender 없이 FBX의 실제 규모를 재는 도구. zip 안에 든 채로도 잰다.

왜 필요한가
-----------
유산 스캔 데이터셋은 zip 하나가 수백 MB~수 GB다. 뭘 쓸지 고르려고 전부 풀어서
Blender로 열어 볼 수는 없다. 그리고 **FBX 파일 크기는 폴리곤 수의 지표가 아니다** —
대부분이 임베드 텍스처인 경우가 흔하다 (실측 예: 164 MB 파일 중 155 MB가 텍스처).

이 도구는 FBX 바이너리 노드 헤더만 스트리밍으로 훑어서 다음을 보고한다:
  * PolygonVertexIndex 코너 수 → 삼각형 추정치
  * Vertices 배열 길이 → 정점 수
  * Content(임베드 미디어) 바이트 합계
  * Material / Geometry 노드 개수
  * 참조된 텍스처 파일명

정확도 경고 (중요)
------------------
이 헤더 스캔은 **다중 오브젝트 FBX에서 최대 42% 과소 계측**한다. 단일 병합 메시
FBX에서는 Blender 실측과 0.01% 안에서 일치했지만, 오브젝트가 여러 개로 쪼개진
export batch 에서는 크게 어긋났다. **선별용으로만 쓰고, 확정 수치는 Blender로 재라.**

사용
----
    python fbx_stats.py model.fbx
    python fbx_stats.py archive.zip              # zip 안의 모든 FBX
    python fbx_stats.py folder/ --csv out.csv    # 폴더 일괄

MIT.
"""
import argparse
import csv
import os
import re
import struct
import sys
import zipfile

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
CHUNK = 1 << 23          # 8 MB
OVERLAP = 64             # 노드 이름이 청크 경계에 걸려도 놓치지 않을 만큼


def _u32(buf, i):
    return struct.unpack("<I", buf[i:i + 4])[0]


def scan_stream(fh):
    """열린 바이너리 스트림에서 FBX 통계를 뽑는다."""
    corners = vert_doubles = content_bytes = 0
    n_geometry = n_material = n_content = 0
    textures = set()
    version = None
    buf = b""
    first = True

    while True:
        chunk = fh.read(CHUNK)
        if not chunk:
            break
        if first:
            head = chunk[:27]
            if head.startswith(b"Kaydara FBX Binary"):
                version = _u32(chunk, 23)
            first = False
        buf = buf[-OVERLAP:] + chunk

        for m in re.finditer(b"PolygonVertexIndex", buf):
            i = m.end()
            if i + 5 <= len(buf) and buf[i:i + 1] == b"i":
                n = _u32(buf, i + 1)
                if 0 < n < 300_000_000:
                    corners += n

        for m in re.finditer(b"Vertices", buf):
            i = m.end()
            if i + 5 <= len(buf) and buf[i:i + 1] == b"d":
                n = _u32(buf, i + 1)
                if 0 < n < 300_000_000:
                    vert_doubles += n

        for m in re.finditer(b"Content", buf):
            i = m.end()
            if i + 5 <= len(buf) and buf[i:i + 1] == b"R":
                n = _u32(buf, i + 1)
                if 64 < n < 300_000_000:
                    content_bytes += n
                    n_content += 1

        for m in re.finditer(b"RelativeFilename", buf):
            i = m.end()
            if i + 5 <= len(buf) and buf[i:i + 1] == b"S":
                n = _u32(buf, i + 1)
                if 0 < n <= 4096:
                    raw = buf[i + 5:i + 5 + n]
                    name = raw.replace(b"\\", b"/").split(b"/")[-1]
                    try:
                        textures.add(name.decode("utf-8", "replace"))
                    except Exception:
                        pass

        n_geometry += len(re.findall(rb"\x08Geometry", buf))
        n_material += len(re.findall(rb"\x08Material", buf))

    return {
        "fbx_version": version,
        "corners": corners,
        "tris_est": corners // 3,
        "verts": vert_doubles // 3,
        "embedded_blobs": n_content,
        "embedded_bytes": content_bytes,
        "geometry_nodes": n_geometry,
        "material_nodes": n_material,
        "textures": sorted(textures),
    }


def scan_path(path):
    """파일/zip/폴더 -> [(label, stats), ...]"""
    out = []
    if os.path.isdir(path):
        for root, _dirs, files in os.walk(path):
            for f in sorted(files):
                if f.lower().endswith((".fbx", ".zip")):
                    out.extend(scan_path(os.path.join(root, f)))
        return out

    if path.lower().endswith(".zip"):
        try:
            z = zipfile.ZipFile(path)
        except zipfile.BadZipFile:
            print("  !! not a zip:", path, file=sys.stderr)
            return out
        for info in z.infolist():
            if not info.filename.lower().endswith(".fbx"):
                continue
            with z.open(info) as fh:
                st = scan_stream(fh)
            st["fbx_bytes"] = info.file_size
            st["loose_png"] = sum(
                1 for i in z.infolist() if i.filename.lower().endswith(".png"))
            out.append(("%s :: %s" % (os.path.basename(path), info.filename), st))
        return out

    if path.lower().endswith(".fbx"):
        with open(path, "rb") as fh:
            st = scan_stream(fh)
        st["fbx_bytes"] = os.path.getsize(path)
        st["loose_png"] = 0
        out.append((os.path.basename(path), st))
    return out


def main():
    # Windows consoles default to cp949/cp1252 here and the docstring contains
    # characters they cannot encode, which makes even --help crash. Force UTF-8.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help=".fbx / .zip / folder")
    ap.add_argument("--csv", help="write a CSV summary here")
    ap.add_argument("--textures", action="store_true", help="list referenced texture names")
    args = ap.parse_args()

    rows = []
    for p in args.paths:
        rows.extend(scan_path(p))

    if not rows:
        print("no FBX found")
        return

    print("{:<44}{:>9}{:>12}{:>12}{:>6}{:>6}{:>10}".format(
        "asset", "fbxMB", "tris_est", "verts", "geo", "mat", "embedMB"))
    print("-" * 99)
    tot_t = tot_b = 0
    for label, st in rows:
        tot_t += st["tris_est"]
        tot_b += st["fbx_bytes"]
        print("{:<44}{:>9.1f}{:>12,}{:>12,}{:>6}{:>6}{:>10.0f}".format(
            label[-43:], st["fbx_bytes"] / 1048576, st["tris_est"], st["verts"],
            st["geometry_nodes"], st["material_nodes"],
            st["embedded_bytes"] / 1048576))
        if args.textures and st["textures"]:
            for t in st["textures"]:
                print("        tex:", t)
    print("-" * 99)
    print("{:<44}{:>9.1f}{:>12,}".format(
        "TOTAL (%d files)" % len(rows), tot_b / 1048576, tot_t))
    print()
    print("NOTE: tris_est is a header scan. It matched Blender to 0.01% on single-mesh")
    print("      FBX but UNDERCOUNTED BY UP TO 42% on multi-object exports.")
    print("      Use it to triage; measure the final numbers in Blender.")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["asset", "fbx_bytes", "tris_est", "verts", "geometry_nodes",
                        "material_nodes", "embedded_blobs", "embedded_bytes",
                        "loose_png", "fbx_version"])
            for label, st in rows:
                w.writerow([label, st["fbx_bytes"], st["tris_est"], st["verts"],
                            st["geometry_nodes"], st["material_nodes"],
                            st["embedded_blobs"], st["embedded_bytes"],
                            st["loose_png"], st["fbx_version"]])
        print("wrote", args.csv)


if __name__ == "__main__":
    main()
