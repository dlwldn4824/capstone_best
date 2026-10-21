# Vity 얼굴 체크 (`/face`)

전면 카메라로 30초 얼굴을 찍어 심박 · 맥파 · 박동 간격 · 호흡 · 눈 깜빡임 · 머리 흔들림을 읽어 보여 주는 PWA. 계산은 전부 휴대폰 브라우저 안에서 하고, 카메라 영상은 저장하지도 보내지도 않는다. 얼굴 인식 모델도 앱과 같은 서버에서 받는다.

## 실행
```bash
cd webapp/face
npm ci
npm test
npm run build                 # dist/ 를 만든다 (처음 한 번 얼굴 모델을 받는다)
cd ../.. && python webapp/server.py   # http://localhost:8000/face/
```
개발 중에는 `npm run dev` → `http://localhost:5173/face/` (카메라 없이 흐름만 볼 때는 `/face/?demo`).
아이폰 카메라는 HTTPS에서만 열린다. `python webapp/server.py --https` 로 켜고 `https://<PC IP>:8000/face/` 를 연다.

## 단독 배포 (Cloud Run)
```bash
gcloud auth login                 # 처음 한 번
npm run deploy                    # 프로젝트 vity-face-kw2026, asia-northeast3
```
`predeploy` 가 `shared-assets/`(캐릭터 · 글꼴 사본) · `public/mediapipe/` 를 채운 뒤 올린다. `Dockerfile`이 앱을 `/face/`, 에셋을 `/assets/` 에 두고 nginx(포트 8080)로 서빙한다. `/` 는 `/face/` 로 보낸다.

## 아이폰에서
1. Safari로 주소 열기 → 시작하기 → 카메라 허용
2. 휴대폰을 세워 두고, 밝은 곳에서 화면 정면을 30초 보기 (얼굴이 자리 잡고 1초 지나면 자동 시작)
3. 결과의 각 타일을 누르면 계산 방법과 연구 수치 · 출처가 나온다
4. 공유 → 홈 화면에 추가하면 두 번째부터 오프라인으로 열린다

## 구조와 근거
[`docs/app/FACE_DESIGN.md`](../../docs/app/FACE_DESIGN.md)가 정본이다. 견고성 감사 결과는 `scripts/robustness/results_after.md`.
