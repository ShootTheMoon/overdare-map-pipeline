# JSN_Sangok — 오버데어 배치 명세서

2026-08-18. 조선 산곡 자연지형 맵.
**반입(에셋 발행)은 완료.** 이 문서는 남은 **인스턴스 배치** 작업의 명세다.

> **2026-11-09 정정.** 이 문서의 2절 좌표식과 5절 "미해결"은 그대로 쓰면 안 된다.
> 뒤에 실측으로 확정된 내용이 [`LESSONS_SANGOK2.md`](LESSONS_SANGOK2.md) 에 있고,
> 해당 절에 무엇이 어떻게 바뀌었는지 각각 적어 두었다. 좌표식은 **거울상 버그**였고
> 5절의 스케일 문제는 **해결됐다**.

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

### 좌표 변환 근거 — **아래 식은 틀렸다. 2026-09 정정판을 쓸 것**

Blender는 Z-up 미터, 오버데어는 Y-up 센티미터다.

~~```
X = blender_x * 100
Y = blender_z * 100      <- 높이
Z = blender_y * 100
yaw = -degrees(blender_rot_z)
```~~

`Z = +blender_y` 는 **행렬식 −1, 즉 거울이다.** FBX 익스포터는 정상 회전(`Z = −y`)으로
내보내므로 메시 **내용**과 **배치 위치**가 남북으로 어긋난다. 여기에 Studio 가 임포트
메시를 Y축 180° 돌려 그리는 것이 겹쳐 "제자리에서 뒤집힌" 그림이 된다.

확정판 ([`LESSONS_SANGOK2.md` §1](LESSONS_SANGOK2.md)):

```
X = blender_x * 100 + X0
Y = blender_z * 100            <- 높이
Z = -blender_y * 100 + Z0      <- 부호 반전 필수
yaw = +degrees(blender_rot_z) + 180      <- MeshPart 한정
```

- **`+180°` 는 MeshPart 에만** 붙인다. 콜리전 `Part` 는 임포트 메시가 아니므로
  `Z = −y` 만 적용하고 180 은 붙이지 않는다.
- pitch/roll 이 0 이 아닌 인스턴스(바위·자갈)는 축별 부호반전으로 근사하면 안 된다.
  `R_e = M·R_b·Mᵀ` (`M = [[1,0,0],[0,0,1],[0,-1,0]]`) 를 구해 **ZXY 로 분해**한다.
  YXZ 로 분해하면 최대 160°, 전체의 24% 가 10° 넘게 틀어진다.
  Euler 순서 판정법은 [`DIAGNOSTICS.md`](DIAGNOSTICS.md) 의 짐벌락 탐침 참조.

마스터는 각자 **자기 바닥 중앙**을 원점으로 재중심했으므로, CSV의 X/Y/Z는 그
피벗 기준의 월드 위치다. 원본 오브젝트 원점이 아니다.
반면 **Studio 는 CFrame 에 메시 bbox 중심을 놓는다.** 바닥 중앙 피벗을 그대로 쓰면
인스턴스가 자기 높이의 절반만큼 파묻히므로, 로컬 up 으로 `h/2` 올려서 넣어야 한다.

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

## 5. 스케일 — **해결됨 (가설 A·B 둘 다 틀렸다)**

`Size` 는 백분율도 아니고 무시되는 것도 아니다. **절대 cm 실치수다.**

```
size = [ 메시_natural_cm.x * sx,
         메시_natural_cm.y * sy,
         메시_natural_cm.z * sz ]

메시_natural_cm = 2 × UnitExtent        <- UnitExtent 는 반폭이다
```

배율 1.0 로 놓으려면 `Size = 2 × UnitExtent` 를 그대로 넣는다.

**당시 "육안 확인 실패" 의 정체**: `Size = 100` 은 100 % 가 아니라 **1 m 큐브**였다.
UnitExtent 3250(=65 m) 짜리 지형 타일이 1 m 로 찌그러져 화면에서 사라진 것이다.
자리표시자 ±50 을 쓰면 Studio 가 `Size/100` 을 배율로 잡아 40 m 타일이 1.6 km 로 보인다.

판정에 쓴 방법: 엔진 `Part`(프리미티브라 cm 라는 데 이견이 없다)를 같은 자리에
`Size 6500×200×6500` 으로 놓으니 65 m 슬래브로 나왔고, 같은 자리의 MeshPart 는 안 보였다.
자세한 건 [`DIAGNOSTICS.md`](DIAGNOSTICS.md) 의 기준자 Part.

**메시를 교체(MeshId 변경)할 때는 `UnitExtent` 도 같이 갱신해야 한다.** 안 하면
새 메시가 옛 반폭을 기준으로 배율 계산돼 수십만 배로 늘어난다.

배율이 실제로 필요한 근거: 곰솔 0.55~1.17배(수령 편차), 자갈 0.12~0.36,
`MST_ROCK_MASS` 는 **0.098~0.128배로 줄여 써야 한다**(원본이 97 m 절벽이라 그대로
쓰면 맵 서쪽 절반을 먹는다).

## 6. 충돌 — FBX에 넣지 말 것

오버데어는 **UCX 규약을 구현하지 않는다.** 두 경로 다 죽는다.

- 단독 `UCX_*.fbx` → "Failed to create asset"
- 렌더 파일 안의 `UCX_` 메시 → **Studio 크래시** (`LevelActor.cpp:583`)

임포터가 **오브젝트마다 월드 에셋을 발행하고 누수**시키기 때문이다.

**엔진 `Part` 를 쓴다.** 이 맵의 헐은 전부 축정렬/회전 박스이고 Part가 곧 박스라
1:1로 대응된다. Part는 네이티브 프리미티브라 **발행 에셋이 0개**다.
설정: `Transparency 1`, `CanCollide true`, `Anchored`, `Static`.

지형면을 Part 로 덮는 **구체적인 생성 절차와 함정**(쿼드트리 적응 분할, 슬랩 높이,
`Shape` 기본값, `canQuery`)은 [`TERRAIN_COLLISION.md`](TERRAIN_COLLISION.md) 에 따로 있다.

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
