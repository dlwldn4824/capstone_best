# legacy — 수정 전 버전 (참고용)

2026-10-19 기획 변경(워치 없이 전면 카메라만) 전에 만든 것들이다. 지우지 않고 발표 · 비교용으로 남겨 둔다.
새 기능은 여기에 넣지 않는다 — 지금 웹은 [`webapp/`](../webapp/) 이다.

| 폴더 | 무엇 | 여는 법 |
| --- | --- | --- |
| `webapp_v1/` | 폰 · 워치 연동 웹앱 v1 (밤 심박 판정 · 위험 알람 모델 · 실시간 동기화). `engine.py` · `model/risk_v1.json` · `static/` (phone · watch · app.js · ble.js · guide.js · rppg.js v1 · sw.js) | 보관만 한다 — 서버가 `/v1` · `/watch` 를 내보내지 않는다 |
| `watch_app/ExcuseGauge/` | Apple Watch SwiftUI 앱 소스 (Xcode 필요) | Xcode 에서 열기 |
| `watch_app/web/` | Xcode 없이 브라우저로 여는 워치 데모 한 장 | `index.html` 을 브라우저로 |

`webapp/server.py` 는 `webapp_v1/engine.py` 를 부르지 않고 `/v1` · `/watch` 와 그 API 도 내보내지 않는다. 테스트는 `webapp_v1/tests/test_webapp_engine.py` (기본 pytest 수집에서 빠진다 — `python -m pytest legacy/webapp_v1/tests`).
