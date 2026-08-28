# JSN_Sangok — 오버데어 배치 명세서

2026-08-18. 조선 산곡 자연지형 맵.
**반입(에셋 발행)은 완료.** 이 문서는 남은 **인스턴스 배치** 작업의 명세다.

프로젝트: `C:\Work\blender-test\blender-test.ovdrjm`
데이터 루트: `C:\Work\blender\JSN_Sangok\06_OVERDARE\`

---

## 1. 이미 끝난 것 — 손대지 말 것

| | |
|---|---|
| 에셋 발행 | **30개 전부 완료** (지형 16 + 마스터 11 + 정적 3), 텍스처 27장 |
| STATIC 배치 | **19개 완료** — `Workspace` 아래 `STA_*` 19개가 원점(0,0,0)에 있음 |

STATIC은 월드 좌표를 메시에 구워 넣었으므로 **(0,0,0)에 놓기만 하면 제자리에 조립된다.**
검증: `STA_TER_00` 의 `UnitExtent` = 3250 × 3380 × 3250 (절반값) → 실제 65 × 67.6 × 65 m.
타일 설계값과 일치.

## 2. 남은 것 — 인스턴스 2,383개

원본: `placements.csv` (UTF-8, 헤더 있음)

```
master, name, X, Y, Z, pitch, yaw, roll, sx, sy, sz
```

| 컬럼 | 의미 |
|---|---|
| `master` | 아래 3절의 마스터 이름 |
| `name` | 인스턴스 이름 (Blender 원본 오브젝트명) |
| `X, Y, Z` | **오버데어 월드 좌표 cm, Y-up.** 그대로 `position` 에 넣으면 된다 |
| `pitch, yaw, roll` | 도(degree). `orientation` = `[pitch, yaw, roll]` |
| `sx, sy, sz` | 배율 (1.0 = 마스터 원본 크기). 항상 균등 |

값 범위: X −12,799 ~ 12,644 / Y −78 ~ 6,570 / Z −12,787 ~ 12,747 cm.
배율 0.098 ~ 2.094.

### 좌표 변환 근거 (이미 CSV에 적용됨 — 다시 하지 말 것)

Blender는 Z-up 미터, 오버데어는 Y-up 센티미터다.

```
X = blender_x * 100
Y = blender_z * 100      <- 높이
Z = blender_y * 100
yaw = -degrees(blender_rot_z)
```

마스터는 각자 **자기 바닥 중앙**을 원점으로 재중심했으므로, CSV의 X/Y/Z는 그
피벗 기준의 월드 위치다. 원본 오브젝트 원점이 아니다.

## 3. 마스터 에셋 ID

| master | 개수 | meshId | textureId | 원본 크기(m) | tris |
|---|---:|---|---|---|---:|
| `MST_PINE` | 1,096 | 42146400 | 42146300 | 10.48 × 10.32 × 16.98 | 8,329 |
| `MST_PEBBLE` | 703 | 42148600 | 42157400 | 0.12~0.36 | 20 |
| `MST_EULALIA` | 313 | 42154100 | 42152300 | 0.89 × 0.85 × 1.25 | 3,350 |
| `MST_ARTEMISIA` | 204 | 42153100 | 42152100 | 0.49 × 0.54 × 1.02 | 840 |
| `MST_ROCK_B` | 13 | 42152500 | 42156200 | 2.11 × 2.45 × 14.06 | 26,999 |
| `MST_ROCK_A` | 12 | 42156100 | 42157400 | 5.99 × 7.09 × 12.45 | 26,999 |
| `MST_ROCK_D` | 11 | 42155300 | 42152900 | 4.03 × 4.36 × 8.96 | 27,000 |
| `MST_ROCK_F` | 10 | 42157200 | 42153000 | 6.27 × 6.60 × 9.67 | 27,000 |
| `MST_ROCK_C` | 9 | 42151400 | 42152700 | 5.17 × 4.74 × 10.41 | 27,000 |
| `MST_ROCK_E` | 9 | 42157100 | 42153300 | 6.32 × 7.79 × 16.20 | 27,000 |
| `MST_ROCK_MASS` | 3 | 42153500 | 42157300 | 10.6 × 6.9 × 6.1 (0.115배 기준) | 26,998 |

기계가 읽을 형태: `asset_ids.json` (30개 전부, mesh+texture 쌍).

## 4. 인스턴스 생성 형식

```json
{
  "className": "MeshPart",
  "name": "<CSV의 name>",
  "props": {
    "meshId":  "<3절 meshId>",
    "position": [X, Y, Z],
    "orientation": [pitch, yaw, roll],
    "size": [?, ?, ?],
    "anchored": true,
    "mobility": "Static",
    "castShadow": true,
    "raw": { "TextureId": "<3절 textureId>" }
  }
}
```

`overdare_create_instances` 는 `items` 최대 50개, `itemsFile` 최대 200개.
2,383개면 **최소 12회** 나눠 호출해야 한다.

## 5. **미해결 — 스케일을 어떻게 거는가**

이것만 정하면 나머지는 기계적이다.

측정된 사실:
- 임포트된 `MeshPart` 의 `Size` 는 메시 실제 크기와 무관하게 **항상 `[100,100,100]`**
- `UnitExtent` 는 메시 고유값이며 **절반값**이다 (곰솔 524×849×516 → 실제 10.48×16.98×10.32 m)
- `Size` 를 50/100/200 으로 준 곰솔 3그루를 놓아 봤으나 **육안 확인 실패**(뷰포트에 안 보임)

가설 A: `Size` 는 백분율 → `size = [100*sx, 100*sy, 100*sz]`
가설 B: `Size` 는 무시되고 메시 고유 크기로 렌더 → 배율을 걸 다른 수단이 필요
  (마스터를 배율 구간별로 여러 개 발행하거나, `PivotOffsetCFrame`/스케일 속성 탐색)

**먼저 곰솔 2~3그루로 A를 검증한 뒤 전체를 돌릴 것.** 배율이 틀리면 숲 1,096그루가
전부 잘못 나오고, 재작업 비용이 크다.

배율이 실제로 필요한 근거: 곰솔 0.55~1.17배(수령 편차), 자갈 0.12~0.36,
`MST_ROCK_MASS` 는 **0.098~0.128배로 줄여 써야 한다**(원본이 97 m 절벽이라 그대로
쓰면 맵 서쪽 절반을 먹는다). 배율을 못 걸면 최소한 ROCK_MASS는 별도 처리가 필요하다.

## 6. 충돌 — FBX에 넣지 말 것

오버데어는 **UCX 규약을 구현하지 않는다.** 두 경로 다 죽는다.

- 단독 `UCX_*.fbx` → "Failed to create asset"
- 렌더 파일 안의 `UCX_` 메시 → **Studio 크래시** (`LevelActor.cpp:583`)

임포터가 **오브젝트마다 월드 에셋을 발행하고 누수**시키기 때문이다.

**엔진 `Part` 를 쓴다.** 이 맵의 헐은 전부 축정렬/회전 박스이고 Part가 곧 박스라
1:1로 대응된다. Part는 네이티브 프리미티브라 **발행 에셋이 0개**다.
설정: `Transparency 1`, `CanCollide true`, `Anchored`, `Static`.

주의: 지형 타일 반입 시 로그에 `Convex hull generation produced zero convex particles,
collision will fail` 경고가 뜬다. **정상이다** — 지형 충돌은 Part로 따로 만든다.

바위·나무는 **회전 박스**를 써야 한다. 45° 돌아간 물체를 축정렬 박스로 감싸면
40% 이상 부풀어 통로를 막는다.

## 7. 반입 규칙 (재반입이 필요할 때만)

- **폴리곤 30,000은 파일 단위다.** 오류 메시지가 명시한다:
  `Maximum allowed polygon count: 30,000`
- `overdare_mesh_bulk_import` 는 넘긴 파일들을 **한 번들 FBX로 합친다.**
  이 프로젝트 메시는 개당 최대 27,000이라 두 개만 합쳐도 초과한다.

| 번들 | 총 tris | 결과 |
|---|---:|---|
| 곰솔 단독 | 8,329 | 성공 |
| 바위A 단독 | 26,999 | 성공 |
| 바위A + 곰솔 | 36,329 | 등록 0 |
| 바위 B+C+D | 81,000 | **Studio 크래시** |

→ `files` 에는 **항상 하나만**.

- 같은 파일을 다시 올리면 교체가 아니라 **중복 발행**이다. 재개 시 반드시
  `UGCLocalAssetTable.json` 과 대조할 것 (`ovd_import_state.py`).
- GUI 자동화는 Studio 자동저장·포커스 상실과 겹치면 `NO_FILE_DIALOG` 로 실패한다.
  재시도하면 통과한다. 실패해도 에셋은 발행되지 않으므로 중복 걱정은 없다.

## 8. 파일 목록

| 파일 | 내용 |
|---|---|
| `placements.csv` | 인스턴스 2,383행 (이 작업의 입력) |
| `asset_ids.json` | 30개 mesh/texture ID 쌍 |
| `items_static.json` | STATIC 19개 배치 (이미 적용됨) |
| `import_state.json` | 반입 진행 대장 |
| `IMPORT_ORDER.md` | 반입 순서와 규칙 |
| `PLAN.md` | 전체 파이프라인 계획 |
| `01_TERRAIN/` `02_STATIC/` `10_MASTERS/` | FBX 30개 + 지형 타일 텍스처 16장 |
| `_texwork/` | 512 텍스처 14장 + 아틀라스 3장 + 지형 베이크 소스 |

Blender 원본: `..\00_Source_Blender\JSN_Master_OVD.blend`
재생성 스크립트: `..\_scripts\ovd_*.py` (`PLAN.md` 참조)
