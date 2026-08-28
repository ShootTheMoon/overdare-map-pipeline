# 시부야 → OVERDARE 임포트 순서 (V18)

> 이 파일은 `MeshTest\` 바로 아래에 둔다. `make_import_batches.py`가 `_IMPORT_V18\`을
> 통째로 지우고 다시 만들기 때문에, 가이드를 그 안에 두면 재생성 때 사라진다.

배포본: `MeshTest\_PREPARED_V18` — **105 파일 / 505,508 tris / 246 MB / 파일당 메시 1개**
콜리전: **FBX에 없음.** 엔진 Part 3,807개로 별도 생성 (`_COLLISION_PARTS\`)

재임포트 검증 전항목 통과:
`meshes ≤30k · file ≤250MB · meshes/file ≤200 · 텍스처 없는 머티리얼 0 · 텍스처 ≤15MB`

---

## FBX에 콜라이더를 넣는 건 불가능하다 (실측 완료)

두 방식 다 죽었다:

| 방식 | 결과 |
|---|---|
| 단독 `UCX_*.fbx` 5개 | "Failed to create asset" — UCX는 *같은 파일 안* 렌더 메시의 헐이라 붙을 대상이 없음 |
| 렌더 파일 안에 `UCX_` 메시 내장 | **Studio 치명적 크래시** |

크래시 원문:

```
Fatal error: LevelActor.cpp:583
Cannot generate unique name for 'MetaBaseWorldSettings'
in level '/Engine/Transient.Untitled:PersistentLevel'
```

임포터는 **파일 안의 오브젝트마다 월드 에셋을 하나씩 발행**하고 transient world를
누수시킨다. 헐 32개 = 발행 32번 추가 → 이름 생성기 고갈. `prepare_all.py`가 모든 메시를
하나로 합치는 이유가 바로 이것이다.

프로젝트 에셋 테이블이 헐 개수와 실패 심각도의 비례를 그대로 기록했다:

| 파일 | 헐 | 결과 |
|---|---|---|
| `SF_TrafficSignal_A_overdare` | 0 | MODEL + STATIC_MESH + TEXTURE — **정상** |
| `ROADS_02_overdare` | 32 | STATIC_MESH만 — **반쪽** |
| `PROBE_UCX128_overdare` | 128 | **크래시** |

⚠ `_PROBES_DO_NOT_IMPORT\`의 파일들은 **실패하도록 만든 증거물**이다. 넣지 말 것.

---

## 0. 프로젝트

현재 `C:\Work\blender-test` 를 쓰고 있다. 다른 경로면
`set OVERDARE_PROJECT=<경로>` 를 스크립트 실행 전에 지정.

현재 테이블 상태: 5행. `SF_TrafficSignal_A`는 정상이라 그대로 두면 되고
(재생성된 배치가 자동으로 건너뛴다 — 그래서 105가 아니라 104파일), `ROADS_02`는
STATIC_MESH만 남은 반쪽이라 재임포트하면 고아 1행이 남는다. 456행 중 1행이므로
무시해도 되고, 완전히 깨끗하게 가고 싶으면 새 프로젝트를 만들어 105파일 전부 넣으면 된다.

---

## 1. 본 임포트 — 15 세션

| | |
|---|---|
| 파일 | 104 (`SF_TrafficSignal_A` 이미 완료) |
| 발행 에셋 | 453 |
| 세션 | 15 (`SESSION_01` … `SESSION_15`) |
| 세션당 | ≤34 유닛, ≤10 파일 |

- **한 번에 한 파일씩 (Home > Import). Bulk Import 금지** — 벌크는 26을 넘긴 적이 없고
  MODEL을 발행하지 않아 반쪽 임포트를 만든다. UI에서는 성공처럼 보인다.
- **세션마다 Studio 재시작.** transient world 누수는 재시작 외에 초기화되지 않는다.
- **실패해도 같은 파일 재시도 금지.** 교체가 아니라 중복 발행이다. 아래로 재개할 것.

진척 확인 / 재개:

```bash
python C:\Work\MeshTest\import_status.py "C:\Work\MeshTest\_PREPARED_V18" "C:\Work\blender-test\UGCLocalAssetTable.json"
```

```bash
python C:\Work\MeshTest\make_import_batches.py "C:\Work\MeshTest\_PREPARED_V18" "C:\Work\MeshTest\_IMPORT_V18" "C:\Work\blender-test\UGCLocalAssetTable.json"
```

⚠ **완료 표시는 MODEL 뿐이다.** STATIC_MESH만 있으면 반쪽이고 쓸 수 없다.
⚠ 재생성은 `_IMPORT_V18\`을 지운다. 스모크가 필요하면 `python make_smoke_session.py`.

---

## 2. yaw 부호 — 본 임포트 전에 한 번

아직 엔진 밖에서 검증 불가능한 것이 하나 남아 있다. `placements.csv`의
`yaw_deg = -degrees(rot_z)` 부호다. 틀리면 9,986개가 전부 돌아간다.

`SF_TrafficSignal_A`는 이미 들어가 있으므로 임포트가 아니라 **배치 확인**이다.
`_IMPORT_V18\SESSION_00_SMOKE\`의 `ROADS_01_overdare.fbx`를 하나 더 넣으면
신호등이 도로를 향하는지 판단할 바닥이 생긴다 (3유닛).

신호등이 도로를 따라 보지 않고 도로를 향해 옆으로 서 있으면 부호가 뒤집힌 것이다.

---

## 3. 배치 (MCP)

Lua 스포너 경로(`_SPAWNER_CORE\ShibuyaPlacements_*.lua`)는 **쓰지 않는다** — `Size`를
쓰지 않아 이전 프로젝트에서 죽은 파트 201개를 만든 원인이다.

```bash
python C:\Work\MeshTest\make_placement_items.py "C:\Work\MeshTest\_PLACEMENT_V18" --core --chunk 200
```

→ `items_000_static.json` (정적 39개) + 인스턴스 청크 약 50개 (≈9,986개).
정적부터 넣고 확인한 뒤 나머지를 `overdare_create_instances`로. 청크마다 `overdare_save`.

규칙(이미 스크립트에 반영됨): 정적은 **bbox 중심**에 · 인스턴스는 CSV Y가 밑면이므로
**+ bbox 중심 오프셋** · `meshId`는 **STATIC_MESH**(MODEL은 지오메트리가 없어 조용히
안 보임) · `size` 생략 금지(0으로 저장되고 렌더 안 됨).

---

## 4. 콜리전 (MCP, 임포트 불필요)

```bash
python C:\Work\MeshTest\make_collision_parts.py "C:\Work\MeshTest\_COLLISION_PARTS" --core --chunk 200
```

→ **Part 3,807개 / 20청크 / 발행 에셋 0개.** `overdare_create_instances`로 투입.
`Transparency 1`, `CanCollide true`, `Anchored`, `Static`.

| 대상 | Part | 방식 |
|---|---|---|
| 지형 | 3,118 | 적응형 쿼드트리, 평평한 박스 |
| 건물 | 597 | 건물당 AABB |
| 랜드마크 | 17 | 〃 |
| 전주 / 차량 | 75 | 배치 행마다 회전 박스 (45° 돌아간 택시를 월드 AABB로 잡으면 40% 부풀어 차선을 막음) |

지형 수직 오차: **코어 ±128 m 0.30 m** · 128–200 m 0.50 m · 200–340 m 1.00 m.
헐이 FBX 안에 있을 때는 파일당 32개 상한 때문에 바깥을 1.54 m/4.82 m로 풀어야 했는데,
Part에는 상한이 없어 되찾았다.

의도적으로 콜리전을 넣지 않은 것: 군중(넣으면 스크램블 통행 불가), 나무, 네온,
점자블록, 잡거빌딩 파사드 키트(건물 박스가 이미 덮음), 13 cm 연석(넘어다니는 것이라
넣으면 이동이 끈적해짐).

---

## 5. 검증

1. `python check_placed.py "<project>.ovdrjm"` → `Size/|UnitExtent| == 2.000`인 파트 수 == 전체
2. `overdare_screenshot` — 스크램블 교차로 (UI는 안 찍힘)
3. `overdare_play` → `Play.log` — 지형 위를 걷고 건물을 통과하지 않는지
4. 전주 1개 + 택시 1개 방향 육안 확인
