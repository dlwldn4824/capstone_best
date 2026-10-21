# webapp/face — Vity 얼굴 체크 (`/face`)

설계 · 데이터 타입 · 화면 규칙 · 품질 기준의 정본은 [`docs/app/FACE_DESIGN.md`](../../docs/app/FACE_DESIGN.md) 다. 고치기 전에 먼저 읽는다.

## 절대 규칙
- 카메라 프레임, ROI 픽셀, 얼굴 랜드마크는 **메모리에서만** 쓰고 저장하지 않는다. 서버로 보내지 않는다.
- 외부 호스트에 요청하지 않는다. MediaPipe wasm · 모델은 같은 서버의 `/face/mediapipe/`에서 받는다 (`scripts/sync-assets.mjs`가 빌드 때 채운다).
- `src/pipeline/`은 UI를 모른다. 공개 인터페이스는 `analyze(samples) → Result`, `quickBpm(samples)`, `faceState(samples)`. 타입을 바꾸면 `tests/`도 바꾼다.
- 수정 후 `npm test`가 통과해야 한다.
- 화면에 보여 주는 숫자는 `src/ui/evidence.js`에 근거(열어 본 출처)가 있어야 한다. 스트레스 지수(Baevsky SI), 피부색, SpO2, 혈압, 표정→기분은 근거가 없어 보여 주지 않는다.
- 문구: 토스 톤. 짧게, 존댓말 "~해요". 면책 나열·"~하지 않는 것" 목록·placeholder 문구를 쓰지 않는다.
- 주소: 앱은 `/face/` 아래(vite `base`), 캐릭터 · 글꼴은 `/assets/…`(저장소 `assets/`). `public/` 에 에셋 사본을 넣지 않는다.

## 명령
```
npm ci && npm test
npm run dev          # http://localhost:5173/face/ (?demo 로 합성 신호)
npm run build        # dist/ → python webapp/server.py 가 /face/ 로 내보낸다
```
