# -*- coding: utf-8 -*-
"""반입 순서 문서 생성.

핵심 규칙 하나를 실측으로 확정했다: **한 번에 파일 하나.**
`overdare_mesh_bulk_import` 는 넘긴 파일들을 한 번들 FBX로 **합친다.**
이 프로젝트 메시는 개당 최대 27,000 tris라 두 개만 합쳐도 파일 총합 30k를 넘는다.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVD = os.path.join(ROOT, "06_OVERDARE")
SUBS = ("10_MASTERS", "01_TERRAIN", "02_STATIC")
UNITS_PER_FILE = 3          # MODEL + STATIC_MESH + TEXTURE
SESSION_UNIT_CAP = 36       # 기록된 세션 한계 40에 여유


def collect():
    rows = []
    for sub in SUBS:
        p = os.path.join(OVD, sub)
        if not os.path.isdir(p):
            continue
        for f in sorted(os.listdir(p)):
            if f.endswith("_overdare.fbx"):
                rows.append((sub, f, os.path.getsize(os.path.join(p, f)) / 1048576.0))
    return rows


def main():
    rows = collect()
    per = SESSION_UNIT_CAP // UNITS_PER_FILE
    out = [
        "# JSN_Sangok 오버데어 반입 순서", "",
        "## 절대 규칙 — 한 번에 파일 하나", "",
        "`overdare_mesh_bulk_import` 는 넘긴 파일들을 **한 번들 FBX로 합친다.**",
        "이 프로젝트 메시는 개당 최대 27,000 tris라 두 개만 합쳐도 파일 총합 30k를",
        "넘는다. 실측 결과:", "",
        "| 번들 구성 | 총 tris | 결과 |", "|---|---:|---|",
        "| 곰솔 단독 | 8,329 | 등록 3 — 성공 |",
        "| 바위A 단독 | 26,999 | 등록 2 — 성공 |",
        "| 바위A + 곰솔 | 36,329 | 등록 0 — 실패 |",
        "| 바위 B+C+D | 81,000 | **Studio 크래시** |", "",
        "따라서 `files` 에는 **항상 파일 하나만** 넘긴다.", "",
        "## 순서 (%d개, %.1f MB)" % (len(rows), sum(r[2] for r in rows)), "",
    ]
    for i, (sub, fn, mb) in enumerate(rows):
        if i and i % per == 0:
            out += ["", "> **여기서 Studio 재시작** — 세션당 %d유닛 한계, 파일당 %d유닛"
                    % (SESSION_UNIT_CAP + 4, UNITS_PER_FILE), ""]
        out.append("%3d. `%s/%s` — %.2f MB" % (i + 1, sub, fn, mb))
    out += ["", "반입이 끝나면 `placements.csv`(2,383행)로 인스턴스를 배치한다.",
            "STATIC(지형 16 + 수면 2 + 석단 1)은 월드 좌표 그대로라 (0,0,0)에 놓으면 된다.", ""]
    p = os.path.join(OVD, "IMPORT_ORDER.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("파일 %d개 / %.1f MB / 세션 %d회" % (len(rows), sum(r[2] for r in rows),
                                              (len(rows) + per - 1) // per))
    print(p)


if __name__ == "__main__":
    sys.exit(main())
