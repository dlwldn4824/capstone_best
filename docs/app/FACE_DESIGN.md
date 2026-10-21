# Vity 얼굴 체크 (`/face`) — 설계

Vity(캡스톤, Team 삼삼오오)의 얼굴 카메라 부분 시연 PWA. 아이폰 Safari 전면 카메라로 30초 얼굴을 찍어 **심박 · 맥파 · 박동 간격(RMSSD) · 호흡 · 눈 깜빡임 · 머리 흔들림**을 기기 안에서 계산해 보여 준다. 화면 톤은 `webapp/static/check.html`(/check)을 따른다.
코드는 [`webapp/face/`](../../webapp/face/) (vity-face-test@4994ea7 에서 옮겨 왔다). 이 문서의 경로는 `webapp/face/` 기준이다.

`/check` 와는 계산 엔진이 다르다. `/check` 는 `webapp/static/vitals.js`(= `src/nesy/vitals.py`), `/face` 는 `webapp/face/src/pipeline/`.
[CHECK_DESIGN.md](CHECK_DESIGN.md) 의 공개 데이터 검증(심박 0.33 bpm 등)은 `vitals.js` 엔진 결과이고 `/face` 에는 해당하지 않는다.

## 절대 규칙
- 카메라 프레임, ROI 픽셀, 얼굴 랜드마크는 **메모리에서만** 쓰고 저장하지 않는다. 서버로 보내지 않는다.
- 외부 호스트에 요청하지 않는다. MediaPipe wasm · 모델은 같은 서버의 `/face/mediapipe/`에서 받는다 (빌드할 때 `scripts/sync-assets.mjs`가 채운다).
- `src/pipeline/`은 UI를 모른다. 공개 인터페이스는 `analyze(samples) → Result`, `quickBpm(samples)`, `faceState(samples)`. 타입을 바꾸면 `tests/`도 바꾼다.
- 수정 후 `npm --prefix webapp/face test`가 통과해야 한다.
- 화면에 보여 주는 숫자는 `src/ui/evidence.js`에 근거(열어 본 출처)가 있어야 한다. 스트레스 지수(Baevsky SI), 피부색, SpO2, 혈압, 표정→기분은 근거가 없어 보여 주지 않는다.
- 문구: 토스 톤. 짧게, 존댓말 "~해요". 면책 나열·"~하지 않는 것" 목록·placeholder 문구를 쓰지 않는다.

## 주소와 파일
| 주소 | 내용 | `python webapp/server.py` | 단독 nginx (`webapp/face/Dockerfile`) | `npm run dev` |
| --- | --- | --- | --- | --- |
| `/face/` | 앱 (vite `base: '/face/'`) | `webapp/face/dist/` (없으면 빌드 방법 안내, 503) | `dist/` → `/usr/share/nginx/html/face/` | vite |
| `/face/mediapipe/` | wasm · `face_landmarker.task` | `dist/mediapipe/` | 같음 | `public/mediapipe/` |
| `/assets/characters/…` · `/assets/fonts/…` | 캐릭터 · 글꼴 (/check 와 같은 파일) | 저장소 `assets/` (`STATIC_ROOTS`) | `shared-assets/` → `/usr/share/nginx/html/assets/` | `vite.config.js` 미들웨어가 `shared-assets/` 를 내보낸다 |

- `scripts/sync-assets.mjs` 는 `predev` · `prebuild` · `predeploy` 로 돈다. 저장소 `assets/` → `shared-assets/`, `node_modules/@mediapipe/tasks-vision/wasm` → `public/mediapipe/`, 얼굴 모델은 `webapp/static/vendor/mediapipe/`(fetch_vendor.py 사본)이 같은 파일(SHA-256)이면 복사하고 아니면 Google 저장소에서 한 번 받는다. 셋 다 git 제외.
- 사본을 `public/` 이나 `assets/` 에 두지 않는 까닭: vite 가 찾은 파일 주소를 `/face/assets/…` 로 바꾼다. `/assets/…` 를 찾지 못하면 그대로 두며, 빌드 때 "didn't resolve at build time" 한 줄이 나오는 것은 정상이다.
- 서비스 워커 `public/sw.js`: 범위 `/face/`. `/face/mediapipe/` · `/assets/` 는 cache-first, 나머지 `/face/…` 는 network-first. 캐시 이름이 `vity-face-` 로 시작하는 것만 정리한다.

## 구조 (`webapp/face/`)
```
src/main.js              홈 → 준비 시트 → 촬영(자세 맞추기 → 30초) → 결과 → 상세 시트, 기록 탭. ?demo 는 합성 신호(개발 확인용)
src/ui/view.js           resultView(scan): 결과 화면에 무엇을 보여 줄지 정하는 순수 함수
src/ui/overlay.js        촬영 오버레이(타원 안쪽만): 자세 맞추기엔 메시가 0.3초 퍼짐, 측정 중엔 메시 유지 + 빛 띠 · 박동마다 이마 · 볼 선 밝아짐 · 측정점 깜빡임
src/capture/framing.js   framingIssue(): 거리 · 위치 · 각도 · 밝기 · 흔들림 · 입 → 안내 한 줄
src/ui/evidence.js       지표별 설명 · 연구 수치 · 출처
src/ui/icons.js          Lucide 아이콘
src/capture/camera.js    getUserMedia 640×480 30fps 전면
src/capture/facemesh.js  MediaPipe FaceLandmarker 478점 + blendshapes, TESSELATION. WASM_URL · MODEL_URL = BASE_URL + 'mediapipe…'
src/capture/roi.js       ROI_INDEX(이마 · 양 볼), 160×120 캔버스 폴리곤 평균 RGB
src/pipeline/resample.js 타임스탬프 → 30Hz 균일 격자, coverage(얼굴 잡힌 비율 · 최대 구멍)
src/pipeline/pos.js      POS (Wang 2017)
src/pipeline/filter.js   Butterworth biquad + filtfilt
src/pipeline/spectrum.js FFT, 피크 bpm, SNR(1–3차 고조파), 서맥 f/2 보정
src/pipeline/hrv.js      협대역 → 250Hz 보간 → 피크 → RR → RMSSD(살아남은 이웃 쌍만) · SDNN
src/pipeline/resp.js     호흡: 머리 움직임 · 밝기 두 주기가 ±2회/분 안에서 맞을 때만
src/pipeline/face.js     깜빡임 횟수 · 눈 감긴 비율 · 하품 후보 · 머리 흔들림
src/pipeline/quality.js  발표 4조건 + 견고성 조건(coverage · interference · roi), 사용자 문구
src/pipeline/index.js    analyze()(G2: 창별 ROI 융합, 품질 미달이면 움직임 상쇄 재시도 → 그래도 미달이면 깨끗한 구간 선택), liveEstimate(), stableEnough()(빠른 측정 조기 종료), quickBpm()
src/pipeline/fuse.js     fuseWindows(): 6초 창마다 SNR 가중 ROI 융합
src/pipeline/motion.js   motionRefs() · nlmsCancel(): 얼굴 위치 · 크기 참조 NLMS 움직임 상쇄 (실패한 스캔에만)
scripts/experiments/     흔들림 보정 · 측정 시간 단축 합성 실험과 결과(results_*.md)
src/store/db.js          IndexedDB(scans, kv)
src/debug/synth.js       합성 Sample[] (간섭 · 구멍 · 고조파 옵션)
scripts/robustness/      합성 견고성 감사 스크립트와 결과(results_before.md / results_after.md)
scripts/sync-assets.mjs  위 "주소와 파일"
tests/legacy_vitals_parity.test.js  /check 의 rppg2.js + vitals.js 가 tests/test_vitals.py 기준값을 내는지 (엔진 대응 확인용)
public/sw.js             범위 /face/
Dockerfile, nginx.conf   단독 Cloud Run 정적 서빙(포트 8080, / → /face/)
```

## 데이터 타입
```ts
Sample = { t: ms, forehead:[r,g,b], lcheek:[r,g,b], rcheek:[r,g,b], faceWidth, faceCenter:[x,y], brightness: 0–255, blink: 0–1, mouthOpen: 0–1 }
Result = { bpm, snrDb, rr: ms[], rmssd, sdnn, pnn50, baevskySI, meanRR, hrvReliable, hrvPairs,
           quality: { pass, reason, brightnessOk, brightnessRatio, motionOk, motionRatio, blinkOk, blinkRatio, snrOk,
                      coverageOk, interferenceOk, roiAgreeOk, ... },
           roiBest, roiAgree: 0–3, perRoi: {name: {bpm, snrDb}}, fsEstimated(관측), fsGrid(30), durationSec,
           coverage: { ratio, maxGapSec }, interference, resp: { rate|NaN, agree },
           debug: { pulse: Float32Array, spectrum } }
FaceState = { durationSec, blinkPerMin, blinks, eyeClosedRatio, yawns, headMovePct, brightness, fps }
```

## 촬영 흐름
0. 측정 방식(준비 시트에서 고름, localStorage 'vity.mode'): 빠르게 = 최근 10초 실시간 추정 3번이 ±2 bpm 안 · SNR ≥ 3 dB · 10초 이상 · 전체 품질 통과면 끝(최대 30초, 심박 · 맥파만) / 전체 = 30초(박동 간격 · 호흡 · 깜빡임까지). 합성 실험: 중앙 10초, 일찍 틀린 값 수락 0%
1. 준비 시트: 휴대폰 세워 두기(눈높이) · 팔 길이(30–40cm) · 빛은 얼굴 앞 · 30초 말하지 않기
2. 자세 맞추기: 전체 화면 카메라, 타원 밖은 어둡게. `framingIssue` 우선순위 noface → far/near(얼굴 폭 = 타원 폭의 60–95%) → center(18%) → angle(좌우·갸웃 15°, 위아래 20°, MediaPipe 변환 행렬) → dark/bright(70–215) → shake(0.5초 코끝 2%) → mouth. 안내는 한 줄만. 모두 맞고 1초 유지되면 시작
3. 30초: 메시는 그대로, 빛 띠가 훑고 박동마다 이마 · 볼 선이 밝아지며 측정점이 깜빡인다. 타원 테두리가 진행 링. 샘플 시각은 requestVideoFrameCallback 의 mediaTime(자세 맞추는 동안 증가가 확인될 때만, 아니면 콜백 시각). 얼굴을 놓치면 안내가 노랗게 바뀌고 실시간 bpm 을 숨긴다. ROI 가 화면 밖인 프레임은 버린다
4. 결과: `resultView` 규칙(아래)

## 결과 화면 규칙 (src/ui/view.js, tests/view.test.js · regress.test.js)
| 상태 | 심박 · 맥파 | 박동 간격 | 호흡 | 깜빡임 · 머리 |
|---|---|---|---|---|
| noface (샘플 < 60) | 없음 | 없음 | 없음 | 없음 |
| retry (품질 미달) | '–', 단위 없음 | '–' | '–' | 관측값 표시 |
| ok | 표시, SNR ≥ 10 dB면 '신호 좋음' | hrvReliable 이고 0–200 ms면 '참고' | 두 주기 합의 · 8–30회/분이면 '참고' | 깜빡임은 얼굴 잡힌 시간 ≥ 20초일 때 |

샘플이 8초 분량 미만이면 품질 표는 '얼굴이 잡힌 시간' 한 줄만 보여 준다. faceState 의 시간 · 빈도는 얼굴이 잡혀 있던 시간 기준(0.25초 넘는 구멍 제외).

## 앱이 하려는 말 — 평소와 다른가 (`src/pipeline/baseline.js`)
심박 한 번의 값은 사람마다 달라 그 자체로 아무 말도 못 한다. 그래서 화면의 첫 줄은 숫자가 아니라 **평소 대비**다.

| | |
| --- | --- |
| 왜 심박인가 | WESAD 에서 스트레스 때 심박은 15명 전원 상승(+21 bpm, p=0.0001)했고 가슴 ECG 와 거의 같았다. HRV(RMSSD)는 손목에서 3.6배 부풀려져 실제 변화(−13 ms)가 묻혔다 ([HRV_VERDICT](../research/HRV_VERDICT.md)) |
| 왜 이탈인가 | 공개 데이터로 학습한 위험 모델도 평소 대비 이탈(`night_z`)과 최근 3일 중 이탈일 수(`dev3`)를 쓴다 ([RISK_MODEL](../research/RISK_MODEL.md)) |
| 평소값 | 품질을 통과한 최근 30번의 **중앙값**, 흩어짐은 MAD×1.4826. 5번이 모이기 전에는 말하지 않는다 |
| 다르다고 하는 선 | `max(5 bpm, 2 × 흩어짐)`. 5 bpm 아래는 측정 오차 안이라(POS 평균 오차 3.7–4.5) '평소와 비슷해요' |
| 이유 묻기 | 평소와 다르면 움직임 · 커피 · 잠 · 긴장 · 몸 · **짚이는 게 없어요** 중에서 고른다 (`scan.why`) |
| 쌓이는 것 | `why === 'none'` 인 날만 '설명되지 않은 변화'로 센다. 이어지면 기록 탭 맨 위에 알린다 |

말하지 않는 것: **스트레스 지수 · 안색 · 긴장도.** 근거가 없다 (`webapp/face/CLAUDE.md`).
이번 측정값은 자기 평소값에 넣지 않는다(`finish()`에서 자기 id 를 뺀다).

## 화면
탭은 홈 · 기록 · 내 정보 세 개다. 첫 실행이면 온보딩 5단계(`check.html` 의 컷씬을 그대로 가져옴)가 뜨고,
동의해야 들어간다. 그룹 단계는 `check.py` 서버가 있어야 도는 기능이라 안내만 하고 넘어간다 — 이 앱은 백엔드가 없다.
홈 하단 바 위 손잡이(`.peek`)를 누르거나 홈에서 위로 쓸면 준비 시트가 열린다.

## 품질 기준
4조건은 **밝기 55–225 ≥ 90%, 움직임 < 얼굴폭 5% ≥ 85%, 깜빡임·말하기 < 30%, SNR ≥ -3 dB** 다.
여기에 합성 감사(scripts/robustness)에서 거짓 통과가 나온 경우를 막는 조건을 더했다.

| 조건 | 기준 | 막는 것 |
|---|---|---|
| coverage | 얼굴 잡힌 시간 ≥ 85%, 최대 놓침 ≤ 1.5 s | 얼굴 놓침으로 bpm이 낮게 나오는 것 |
| interference | 머리 위치 · 밝기 스펙트럼에 같은 bpm 피크 없음 | 화면 깜빡임 · 끄덕임에 잠긴 bpm |
| roi | 단일 ROI 3개 중 2개 이상이 ±3 bpm 안 | 한 영역만의 가짜 피크 |
| 구간 선택 | 전체가 떨어지면 15초 구간을 5초 간격으로 훑어, 같은 bpm(±3)을 내는 구간이 2개 이상일 때 그중 SNR 최고를 쓴다 | 중간에 잠깐 흔들려 멀쩡한 나머지까지 버리는 것 |

### 움직임 · SNR 기준을 푼 이유 (scripts/experiments/p3_gate.js)
움직임 3.5% ≥ 90% · SNR ≥ 0 은 발표 슬라이드 11 의 값이었다. 손으로 든 폰은 이 선을 넘기 쉬운데, **넘었다고 bpm 이 틀리지는 않았다.**
합성 280회(obs=hard)에서 bpm 은 100% 가 참값 ±5 안인데, 이전 기준은 그중 21% 를 거부했다. 실패 이유의 대부분이 움직임(14%)이었다.

| 방식 | 통과 | 통과∧±5 | 거짓 통과 |
|---|---|---|---|
| 이전 기준, 전체 30초 | 78% | 78% | 0% |
| 지금 기준, 전체 30초 | 91% | 91% | 0% |
| 지금 기준 + 구간 선택 | 95% | 95% | 0% |

거짓 통과 0% 가 조건이다. 구간 선택은 창을 여러 개 훑어 제일 좋은 것을 고르는 일이라 우연히 걸릴 기회를 준다 —
합의 조건(같은 bpm 구간 2개 이상)이 없으면 **맥박 없는 신호가 7% 통과했다**(합성 100회). 합의 조건과 5초 간격으로 0% 로 돌아왔다.
구간을 쓴 스캔은 `result.window = { startSec, endSec }` 가 차고, 화면 품질 표에 '쓴 구간'이 적히며, 15초라 박동 간격(HRV)은 보류된다.
**발표 자료의 품질 기준 숫자도 같이 고쳐야 한다.**

## 무엇을 어떻게 보여 주나 (근거: src/ui/evidence.js)
| 항목 | 표시 | 이유 |
|---|---|---|
| 심박 · 맥파 | 품질 통과 시 표시 | POS MAE 공개 데이터 3.7–4.5, 휴대폰 데이터 12.4 bpm |
| RMSSD | `hrvReliable`(SNR ≥ 10 dB, 이웃 쌍 ≥ 20)일 때 "참고" | 카메라 박동 간격 오차 ~20 ms, 합성 감사에서 10 dB 이상도 위로 편향 |
| 호흡 | 두 주기 합의 시 "참고" | 카메라 호흡 벤치마크 최고 PCC 0.66 |
| 눈 깜빡임 · 머리 흔들림 | 횟수 · 비율만 | 개인차 분당 3–48회, 상태 해석 근거 없음 |

## 명령
```bash
cd webapp/face
npm ci
npm test
npm run dev          # http://localhost:5173/face/ (?demo 로 합성 신호)
npm run build        # dist/ → python webapp/server.py 가 /face/ 로 내보낸다
npm run deploy       # 단독 Cloud Run (gcloud run deploy, Cloud Build 가 Dockerfile 로 빌드)
```
저장소 루트에서 두 스위트를 한 번에: `python -m pytest -q && npm --prefix webapp/face test`.

## 자주 할 작업
- ROI 바꾸기: `src/capture/roi.js` ROI_INDEX.
- 품질 기준 조정: `src/pipeline/quality.js` QUALITY(4조건) · ROBUST(추가 조건) · `src/pipeline/index.js` WINDOW(구간 선택).
  바꾸면 `N=20 node scripts/experiments/p3_gate.js`(통과율 · 거짓 통과)와 `node scripts/robustness/11_key.js`(맥박 없는 신호가 통과하지 않는지)로 전후 확인.
- 화면에 지표 추가: pipeline 결과 필드 → `evidence.js`에 근거 → `main.js` tile/detail.
- MediaPipe 버전 올리기: `package.json` 의 `@mediapipe/tasks-vision` → `npm install` (wasm 은 `sync-assets.mjs` 가 복사한다), `sw.js` MODEL_CACHE 이름 올리기. 모델을 바꾸면 `sync-assets.mjs` 의 MODEL_URL · MODEL_SHA256 도.

## 다음 단계
1. 아이폰 실측: Polar H10(또는 워치) 동시 기록, 10명 × 조건 4개 × 3회 + 재측정 쌍 → 통과율 · 통과분 MAE · 재측정 MDC. 그 전까지 발표에 이 앱 정확도 숫자를 쓰지 않는다.
2. 실측으로 coverage · interference 임계값과 SNR 기준 다시 보정.
3. iOS Safari에서 `track.getCapabilities().whiteBalanceMode` 지원 여부 기록.
4. 실기기에서 MediaPipe 변환 행렬이 열 우선인지 확인(정면일 때 yaw · pitch ≈ 0). 행 우선이면 `poseFromMatrix` 인덱스를 바꾼다.
