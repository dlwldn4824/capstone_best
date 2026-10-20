# vity-face-test — 사양서

Vity(캡스톤, Team 삼삼오오)의 얼굴 카메라 부분 시연 PWA. 아이폰 Safari 전면 카메라로 30초 얼굴을 찍어 **심박 · 맥파 · 박동 간격(RMSSD) · 호흡 · 눈 깜빡임 · 머리 흔들림**을 기기 안에서 계산해 보여 준다. 화면 톤은 `../capstone_best/webapp/static/check.html`(목업)을 따른다. 배포는 Cloud Run(`vity-face-kw2026`, 서울).

## 절대 규칙
- 카메라 프레임, ROI 픽셀, 얼굴 랜드마크는 **메모리에서만** 쓰고 저장하지 않는다. 서버로 보내지 않는다.
- 외부 호스트에 요청하지 않는다. MediaPipe wasm · 모델은 `public/mediapipe/`에서 서빙한다.
- `src/pipeline/`은 UI를 모른다. 공개 인터페이스는 `analyze(samples) → Result`, `quickBpm(samples)`, `faceState(samples)`. 타입을 바꾸면 `tests/`도 바꾼다.
- 수정 후 `npm test`가 통과해야 한다.
- 화면에 보여 주는 숫자는 `src/ui/evidence.js`에 근거(열어 본 출처)가 있어야 한다. 스트레스 지수(Baevsky SI), 피부색, SpO2, 혈압, 표정→기분은 근거가 없어 보여 주지 않는다.
- 문구: 토스 톤. 짧게, 존댓말 "~해요". 면책 나열·"~하지 않는 것" 목록·placeholder 문구를 쓰지 않는다.

## 구조
```
src/main.js              홈 → 준비 시트 → 촬영(자세 맞추기 → 30초) → 결과 → 상세 시트, 기록 탭. ?demo 는 합성 신호(개발 확인용)
src/ui/view.js           resultView(scan): 결과 화면에 무엇을 보여 줄지 정하는 순수 함수
src/ui/overlay.js        촬영 오버레이(타원 안쪽만): 자세 맞추기엔 메시가 0.3초 퍼짐, 측정 중엔 메시 유지 + 빛 띠 · 박동마다 이마 · 볼 선 밝아짐 · 측정점 깜빡임
src/capture/framing.js   framingIssue(): 거리 · 위치 · 각도 · 밝기 · 흔들림 · 입 → 안내 한 줄
src/ui/evidence.js       지표별 설명 · 연구 수치 · 출처
src/ui/icons.js          Lucide 아이콘
src/capture/camera.js    getUserMedia 640×480 30fps 전면
src/capture/facemesh.js  MediaPipe FaceLandmarker 478점 + blendshapes, TESSELATION
src/capture/roi.js       ROI_INDEX(이마 · 양 볼), 160×120 캔버스 폴리곤 평균 RGB
src/pipeline/resample.js 타임스탬프 → 30Hz 균일 격자, coverage(얼굴 잡힌 비율 · 최대 구멍)
src/pipeline/pos.js      POS (Wang 2017)
src/pipeline/filter.js   Butterworth biquad + filtfilt
src/pipeline/spectrum.js FFT, 피크 bpm, SNR(1–3차 고조파), 서맥 f/2 보정
src/pipeline/hrv.js      협대역 → 250Hz 보간 → 피크 → RR → RMSSD(살아남은 이웃 쌍만) · SDNN
src/pipeline/resp.js     호흡: 머리 움직임 · 밝기 두 주기가 ±2회/분 안에서 맞을 때만
src/pipeline/face.js     깜빡임 횟수 · 눈 감긴 비율 · 하품 후보 · 머리 흔들림
src/pipeline/quality.js  발표 4조건 + 견고성 조건(coverage · interference · roi), 사용자 문구
src/pipeline/index.js    analyze(), quickBpm()
src/store/db.js          IndexedDB(scans, kv)
src/debug/synth.js       합성 Sample[] (간섭 · 구멍 · 고조파 옵션)
scripts/robustness/      합성 견고성 감사 스크립트와 결과(results_before.md / results_after.md)
public/sw.js             앱 network-first, /mediapipe cache-first
Dockerfile, nginx.conf   Cloud Run 정적 서빙(포트 8080)
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

## 품질 기준
발표 슬라이드 11의 4조건(밝기 55–225 ≥ 90%, 움직임 < 얼굴폭 3.5% ≥ 90%, 깜빡임·말하기 < 30%, SNR ≥ 0 dB)은 그대로 두고, 합성 감사(scripts/robustness)에서 거짓 통과가 나온 경우를 막는 조건을 더했다.
| 조건 | 기준 | 막는 것 |
|---|---|---|
| coverage | 얼굴 잡힌 시간 ≥ 85%, 최대 놓침 ≤ 1.5 s | 얼굴 놓침으로 bpm이 낮게 나오는 것 |
| interference | 머리 위치 · 밝기 스펙트럼에 같은 bpm 피크 없음 | 화면 깜빡임 · 끄덕임에 잠긴 bpm |
| roi | 단일 ROI 3개 중 2개 이상이 ±3 bpm 안 | 한 영역만의 가짜 피크 |

## 무엇을 어떻게 보여 주나 (근거: src/ui/evidence.js)
| 항목 | 표시 | 이유 |
|---|---|---|
| 심박 · 맥파 | 품질 통과 시 표시 | POS MAE 공개 데이터 3.7–4.5, 휴대폰 데이터 12.4 bpm |
| RMSSD | `hrvReliable`(SNR ≥ 10 dB, 이웃 쌍 ≥ 20)일 때 "참고" | 카메라 박동 간격 오차 ~20 ms, 합성 감사에서 10 dB 이상도 위로 편향 |
| 호흡 | 두 주기 합의 시 "참고" | 카메라 호흡 벤치마크 최고 PCC 0.66 |
| 눈 깜빡임 · 머리 흔들림 | 횟수 · 비율만 | 개인차 분당 3–48회, 상태 해석 근거 없음 |

## 명령
```
npm install
npm run dev          # http://localhost:5173 (?demo 로 합성 신호)
npm test
npm run build
npm run deploy       # gcloud run deploy (Cloud Build가 Dockerfile로 빌드)
```

## 자주 할 작업
- ROI 바꾸기: `src/capture/roi.js` ROI_INDEX.
- 품질 기준 조정: `src/pipeline/quality.js` QUALITY(발표 4조건) · ROBUST(추가 조건). 바꾸면 `node scripts/robustness/11_key.js`로 전후 확인.
- 화면에 지표 추가: pipeline 결과 필드 → `evidence.js`에 근거 → `main.js` tile/detail.
- MediaPipe 버전 올리기: `package.json` → `node_modules/@mediapipe/tasks-vision/wasm/*`를 `public/mediapipe/`로 복사, `sw.js` MODEL_CACHE 이름 올리기.

## 다음 단계
1. 아이폰 실측: Polar H10(또는 워치) 동시 기록, 10명 × 조건 4개 × 3회 + 재측정 쌍 → 통과율 · 통과분 MAE · 재측정 MDC. 그 전까지 발표에 이 앱 정확도 숫자를 쓰지 않는다.
2. 실측으로 coverage · interference 임계값과 SNR 기준 다시 보정.
3. iOS Safari에서 `track.getCapabilities().whiteBalanceMode` 지원 여부 기록.
4. 실기기에서 MediaPipe 변환 행렬이 열 우선인지 확인(정면일 때 yaw · pitch ≈ 0). 행 우선이면 `poseFromMatrix` 인덱스를 바꾼다.
