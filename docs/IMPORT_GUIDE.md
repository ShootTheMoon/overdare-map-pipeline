# 오버데어 임포트 — 처음부터

2026-08-18. JSN_Sangok 기준으로 쓴 실전 절차서.
"에셋을 어떻게 오버데어에 넣는가"를 0부터 설명한다.

---

## 0. 먼저 알아야 할 것 — 임포트는 2단계다

오버데어에서 "임포트"라는 말은 서로 다른 두 작업을 뭉뚱그린 말이다.
**이 둘을 구분하지 못하면 반드시 중복 발행으로 망가진다.**

| | 무엇 | 결과물 | 되돌리기 |
|---|---|---|---|
| **1단계 발행** | FBX 파일을 Studio에 등록 | 에셋 ID (숫자). `UGCLocalAssetTable.json` 에 영구 기록 | **불가.** 같은 파일 다시 올리면 교체가 아니라 새 ID로 또 생김 |
| **2단계 배치** | 그 ID를 가진 `MeshPart` 를 씬에 놓기 | 씬 안의 인스턴스 | 자유롭게 지우고 다시 놓아도 됨 |

**맵이 망가졌을 때 다시 해야 하는 건 2단계뿐이다.**
1단계는 이미 끝났고, 다시 하면 안 된다.

### 이 프로젝트의 현재 상태 (실측)

```
UGCLocalAssetTable.json : STATIC_MESH 34 / TEXTURE 34 / MODEL 33
asset_ids.json 의 30개 : 전부 테이블에 존재함 (누락 0, 이름 중복 0)
blender-test.ovdrjm    : STA_* 19개 배치돼 있음 (지형 16 + 수면 2 + 석단 1)
```

→ **FBX를 다시 올릴 이유가 없다.** `asset_ids.json` 의 ID를 그대로 쓰면 된다.
(`import_state.json` 은 작업 도중에 쓰인 것이라 낡았다. 무시할 것.
근거는 위의 실측 대조다.)

---

## 1. 맵을 갈아엎고 다시 배치하는 법 (지금 필요한 것)

### 1-1. 씬 비우기

`overdare_browse` 로 `Workspace` 아래를 읽고, `STA_*` / `JSN_*` 이름의 노드
GUID를 모아 `overdare_delete_instance` 로 지운다. 그 다음 `overdare_save`.

에셋은 그대로 남는다. 지워지는 건 씬 인스턴스뿐이다.

### 1-2. STATIC 19개 다시 놓기

```
overdare_create_instances(itemsFile="06_OVERDARE/items_static.json")
```

19개 전부 `position: [0,0,0]` 이다. **이게 정상이다.**
STATIC 메시는 월드 좌표를 정점에 구워 넣었으므로 원점에 떨구면 제자리에 조립된다.

검증: `overdare_read_instance("Workspace.STA_TER_00")` → `UnitExtent` 가
`3250 × 3380 × 3250` 이어야 한다. **UnitExtent 는 절반값**이므로 실제
65 × 67.6 × 65 m. 타일 설계값과 일치.

### 1-3. 인스턴스 2,383개 놓기

`placements.csv` 를 읽어 `overdare_create_instances` 용 JSON 으로 바꾼다.
좌표 변환은 **이미 CSV 에 적용돼 있다** (Blender Z-up 미터 → 오버데어 Y-up cm).
그대로 `position` 에 넣으면 된다.

한 번에 `items` 50개 / `itemsFile` 200개가 한계라 최소 12회 나눠 호출한다.

**스케일 검증을 먼저 할 것.** 곰솔 2~3그루를 `size` 를 달리해 놓고
눈으로 확인한 뒤 전체를 돌린다. 특히 `MST_ROCK_MASS` 는 원본이 97 m 절벽이라
0.098~0.128 배로 줄이지 않으면 맵 서쪽 절반을 먹는다.

---

## 2. FBX 를 새로 만들어야 할 때 (Blender 부터)

지형 형상 자체를 고쳤을 때만 해당한다. 순서:

| 순서 | 스크립트 | 실행 위치 | 하는 일 |
|---|---|---|---|
| 1 | `jsn_live.py` | Blender | 지형·산포 전체를 다시 생성 (결정적 해시라 재실행하면 똑같이 나옴) |
| 2 | `ovd_textures.py` | 그냥 파이썬 (PIL) | 텍스처 58장 735 MB → 14장 5.3 MB. BC만 남기고 OP를 알파로 합성, 512 리샘플 |
| 3 | `ovd_atlas.py` | Blender | 식생 아틀라스 3장 (곰솔·억새·쑥) 1024 베이크 |
| 4 | `ovd_terrain.py` | 그냥 파이썬 | 지형 타일 텍스처 16장 베이크 (`blend_at()` 를 격자로 평가해 PIL 합성) |
| 5 | `ovd_masters.py` | Blender | 마스터 11개 감량 → `10_MASTERS/*_overdare.fbx` |
| 6 | `ovd_static.py` | Blender | 지형 4×4 분할 + 수면 + 석단 → `01_TERRAIN/`, `02_STATIC/` |

**Blender 내장 파이썬에는 PIL 이 없다.** 2·4번은 반드시 밖에서 돌린다.
안에서 하려 하면 조용히 실패하고 텍스처 없는 오브젝트가 나온다.

FBX 내보내기 설정 (이미 스크립트에 박혀 있음):
`axis_forward="-Z", axis_up="Y", path_mode="COPY", embed_textures=True`

---

## 3. FBX 를 실제로 발행하는 법 (1단계)

### 3-1. 절대 규칙 — 한 번에 파일 하나

`overdare_mesh_bulk_import` 는 넘긴 파일들을 **하나의 번들 FBX로 합친다.**
그리고 폴리곤 한계 30,000 은 **메시가 아니라 파일 단위**다.
오류 메시지가 명시한다: `Maximum allowed polygon count: 30,000`

실측:

| 번들 구성 | 총 tris | 결과 |
|---|---:|---|
| 곰솔 단독 | 8,329 | 성공 |
| 바위A 단독 | 26,999 | 성공 |
| 바위A + 곰솔 | 36,329 | 등록 0 — 실패 |
| 바위 B+C+D | 81,000 | **Studio 크래시** |

이 프로젝트 메시는 개당 최대 27,000 tris 라 두 개만 합쳐도 넘는다.
→ `files` 에는 **항상 하나만** 넘긴다.

### 3-2. 수동 경로 (실제로 이게 제일 안정적이었다)

Studio → `Bulk Import` → 파일 하나 선택 → 등록될 때까지 대기 → 다음.

MCP 자동화는 Studio 자동저장·포커스 상실과 겹치면 `NO_FILE_DIALOG` 로 실패한다.
재시도하면 통과하지만 빈도가 높아 30개 중 19개는 손으로 했다.
**실패해도 에셋은 발행되지 않으므로 중복 걱정은 없다.**

### 3-3. 발행 후

새 ID는 `C:\Work\blender-test\UGCLocalAssetTable.json` 에 적힌다.
`ovd_import_state.py` 를 돌리면 FBX 목록과 대조해 뭐가 빠졌는지 알려준다.
`asset_ids.json` 을 새 ID로 갱신해야 배치가 맞는다.

---

## 4. 지켜야 하는 한계값

| 항목 | 한계 | 비고 |
|---|---|---|
| 폴리곤 | 30,000 / **파일** | 메시 단위가 아니다. 이 프로젝트는 27,000 으로 여유를 뒀다 |
| 파일 | 250 MB | |
| 텍스처 | 15 MB, **권장 512** | 4K 는 임포터를 죽인다 |
| 포맷 | `.fbx` / `.obj` 만 | |
| 성능 | 프롭당 ~700 verts, 화면당 ~70,000 verts | 오버데어는 삼각형이 아니라 **정점**을 센다 |
| 발행 단위 | **머티리얼** | 파일도 오브젝트도 아니다. 텍스처를 줄이는 게 곧 에셋 수를 줄이는 것 |

---

## 5. 충돌 — FBX 에 넣지 말 것

오버데어는 **UCX 규약을 구현하지 않는다.** 두 경로 다 죽는다.

- 단독 `UCX_*.fbx` → `Failed to create asset`
- 렌더 파일 안의 `UCX_` 메시 → **Studio 크래시** (`LevelActor.cpp:583`)

임포터가 오브젝트마다 월드 에셋을 발행하고 누수시키기 때문이다.

**엔진 `Part` 를 쓴다.** 네이티브 프리미티브라 발행 에셋이 0개다.
설정: `Transparency 1`, `CanCollide true`, `Anchored`, `Static`.
바위·나무는 **회전 박스**로. 45° 돌아간 물체를 축정렬 박스로 감싸면
40% 이상 부풀어 통로를 막는다.

지형 반입 시 뜨는 `Convex hull generation produced zero convex particles,
collision will fail` 경고는 **정상이다.** 지형 충돌은 Part 로 따로 만든다.

---

## 6. 자주 당하는 함정

1. **재임포트는 교체가 아니라 중복 발행이다.** 되돌릴 수 없다
2. `UnitExtent` 는 **절반값**. 모르면 정상 임포트가 50% 축소로 보인다
3. 플레이테스트 중에는 편집·임포트 금지 — Studio 가 멈춘다. 먼저 `overdare_stop`
4. FBX 는 **Principled Base Color 에 물린 이미지 하나만** 내보낸다.
   NM/RN/AO 를 붙여봐야 안 나가고 표면만 오염시킨다
5. 상수색 머티리얼은 텍스처가 없으면 FBX 에서 회색으로 나온다. 단색 PNG 라도 물릴 것
6. 헤드리스 Blender 에서 `bpy.ops.mesh.separate` 는 실패하지 않고 **무한정 돈다**
7. `Decimate.ratio` 는 정점 그룹이 아니라 **메시 전체 기준**이다.
   그룹만 지정하고 비율을 주면 엉뚱한 데서 깎여 나간다
8. 알파 카드(잎)는 collapse 로 감량하면 **파편으로 부서진다.** 섬 단위로 솎아야 하고,
   섬 **개수**가 아니라 **면수** 기준으로 예산을 잡아야 한다

---

## 7. 파일 위치

| | |
|---|---|
| FBX 30개 | `06_OVERDARE/10_MASTERS/`, `01_TERRAIN/`, `02_STATIC/` (`*_overdare.fbx`) |
| 에셋 ID | `06_OVERDARE/asset_ids.json` |
| STATIC 배치 | `06_OVERDARE/items_static.json` |
| 인스턴스 2,383행 | `06_OVERDARE/placements.csv` |
| 배치 명세 | `06_OVERDARE/PLACEMENT_SPEC.md` |
| 오버데어 프로젝트 | `C:\Work\blender-test\blender-test.ovdrjm` |
| 에셋 테이블 | `C:\Work\blender-test\UGCLocalAssetTable.json` |
