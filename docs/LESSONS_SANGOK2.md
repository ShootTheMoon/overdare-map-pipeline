# 산곡 II 이관에서 실측한 규칙 (2026-09-06 ~ 07, Studio 39.1)

전부 스크린샷·프로브로 확인한 것만 적었다. 코드는 [heritage-maps/sangok2/scripts](https://github.com/ShootTheMoon/heritage-maps/tree/main/sangok2/scripts).

## 1. 좌표 — README 의 `(X, Z, Y)` 매핑은 거울상이다. 고쳐야 한다

Blender `(x, y, z)` → 엔진 `(X=x, Y=z, Z=+y)` 는 행렬식 −1, 즉 거울이다. FBX 익스포터는 정상 회전(`Z = −y`)으로 내보내므로 메시 **내용**과 **배치 위치**가 남북으로 어긋난다. 여기에 Studio 가 임포트 메시를 **Y축 180° 돌려 그리는** 것이 겹쳐, 타일·산벽마다 "제자리에서 뒤집힌" 그림이 됐다.

확정 규칙:
- 위치: `X = x·100 + X0`, `Y = z·100`, **`Z = −y·100 + Z0`**
- 회전: yaw = **+rot_z**, 그리고 **모든 MeshPart yaw 에 +180°** (콜리전 Part 는 메시가 아니므로 180 없이 Z=−y 만)
- 판정법: 의심 메시 사본을 허공(Y=5000, 맵 밖)에 띄우고 +X 빨강 / +Z 파랑 큐브를 세워 한 장 찍는다. 값 대조(CFrame·노멀·텍스처)로는 절대 안 보인다.
- 화면 좌우: 카메라가 +Z 를 볼 때 **화면 왼쪽이 +X**. 스크린샷으로 x 경계를 판단할 때 늘 뒤집힌다.

Studio 는 CFrame 에 메시 bbox 중심을 놓는다(음수 Y 포함). "음수 중심 보정" 같은 건 필요 없다 — 한때 오진했었다.

## 2. 텍스처 알파는 아예 안 쓴다

1024² 든 아니든, Glass 든 DoubleSided 든 무관하게 MeshPart 는 알파를 무시한다. 잎 카드 사각형이 통째로 그려지고 투명 영역 RGB(보통 검정)가 보인다.
- 잎 삼각형을 알파 실루엣의 볼록껍질로 **잘라서** 카드 바깥을 기하로 없앤다 (`sgk_export._cut_alpha_faces`).
- 아틀라스 투명 영역을 잎 색으로 **채우고** 가장자리 알파를 미리 합성 (`sgk_texbake._infill_transparent`). PIL RGBA resize 는 프리멀티플라이해서 알파 0 RGB 를 검정으로 만드니 RGB/알파를 따로 resize.
- Blender 에서 "무알파 모습"을 볼 땐 `image.alpha_mode='CHANNEL_PACKED'`. 기본 STRAIGHT 는 EEVEE 가 알파 0 픽셀을 검게 그린다.
- 같은 이름은 새 에셋으로 안 올라간다 → 재익스포트마다 접두를 올린다(`SGK_` → `SGK3_`).

## 3. 이음선 — 베이크 쪽 원인 3개와 Studio 쪽 1개

베이크(고쳐짐): 타일별 시드 밝기 얼룩, 타일별 노멀 재계산, 패딩 없는 0..1 UV. → 월드 연속 노이즈·마스크, `TEX_PAD=8`, 해석적 커스텀 노멀. 파일은 경계에서 연속임을 수치로 확인(노멀 0.01°).

Studio(남음): 경계에서 ~12% 밝기 단차. 높이 8~35 m 어디서나 같음(LOD 아님), Blender 렌더엔 없음. 태양만 남기면 사라지고 하늘광만 남기면 커진다 → 메시 단위 스카이 오클루전. Lighting 서비스 속성(ClockTime·AmbientSkyBrightness·SunCastShadow)은 `level.apply` 로 즉시 반영되니 조명 원인 분리에 쓸 것. 후속 처방은 [화성 기록](../README.md) 참고(경계를 랜덤으로 뒤엉키게, 소형 식물로 덮기).

`level.apply` 직후 스크린샷의 회색 줄은 **선택 아웃라인**이다. LOD 틈으로 오독하지 말 것.

## 4. 모바일 미리보기는 월드 ±1 km 밖을 안 그린다

맵을 X −1000 m 에 두면 그 선을 넘는 순간 세상이 통째로 잘린다(산벽도 안 보임). 맵은 ±1 km 안에, 다른 맵과는 Z 로 분리.

## 5. 콜리전

- 지형 슬랩은 플레이 rect 가 아니라 **산벽 띠까지** 깔아야 장벽을 넘어도 안 떨어진다. rect 밖은 오차 1.5 m·최소 8 m 셀로 성기게.
- 거대한 투명 차단벽(260 m × 45 m)은 모바일에서 **흰 리본으로 그려지고 길을 막는다**. 쓰지 말 것.
- 나무는 밑동 4 m 줄기 기둥(수종별 반지름 0.12~0.55 m), 바위·그루터기는 몸통 박스, 풀은 통과.
- 투명 콜리전 Part 의 Material 은 반드시 `Unlit` (Basic 이면 안드로이드에서 화면이 깨진다).

## 6. 단면 컬링

판형 메시가 위에서 안 보이면 위치가 아니라 면 방향이다. 물 메시가 FBX 노멀 z −1 로 나가 위에서 컬링됐다 → MeshPart `DoubleSided` 로 해결(재임포트 불필요).

## 7. 임포트 직후 재시작하면 에셋이 사라진다

재시작 시 프로젝트 폴더 전체가 허브에서 다시 내려와 로컬 변경을 덮는다. **임포트 후 프로젝트 저장 확인 뒤 재시작.** 유실돼도 서버엔 남아 있다:
- RPC `hub.token.read` 로 토큰 → `GET https://create.overdare.com/backend/sandbox/world-asset/file-url?worldAssetId=ID`, `POST …/user/world-assets/exist {"worldAssetIds":[…]}`
- CDN `…/assets/world-asset/raw/live/ID/0/build.zip` 안 uasset 에 이름이 들어 있다(텍스처/메시는 `Texture2D`/`StaticMesh` 문자열 수로 구분). 이름으로 서버를 검색하는 API 는 없다(`world-asset?name=` 은 공개 스토어만).
- 업로드 직후 에셋을 참조하면 다운로드 3회 실패 → 기본 메시로 캐시 + 에러 팝업. 몇 분 대기.

## 8. MeshPart 치수

`Size` 는 절대 cm, `UnitExtent` 는 실제 bbox 반폭 `(X/2, Y/2, −Z/2)`. 자리표시자 ±50 을 쓰면 Studio 가 Size/100 을 배율로 잡아 40 m 타일이 1.6 km 로 보인다.

## 9. 레벨 편집 RPC 경계

- `level.apply` 는 새 인스턴스 추가·삭제는 반영하지만 **기존 인스턴스의 속성 변경은 반영하지 않았다**(MeshPart 텍스처·재질 교체 실험 3회 픽셀 동일). 서비스(Lighting) 속성은 반영된다. 바꾸려면 지웠다 다시 넣는다.
- `instance.upsert` 는 사이드카 카탈로그엔 있지만 Studio 39.1 은 "Method not found".
- 플레이테스트 중엔 `viewport.camera.set` 이 거부된다. 캐릭터 시점 캡처는 `game.screenshot` 만.
- 투표 전체 경로 검증은 `M.DEBUG_VOTE="sgk"` 로 서버가 대신 표를 넣게 한 뒤 `Sandbox.log` 의 `[Map]` 줄을 읽는다. 끝나면 반드시 nil.
