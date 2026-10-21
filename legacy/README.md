# legacy

2026-10-19 기획을 바꾸기 전(워치 없이 전면 카메라만 쓰기로 하기 전)에 만든 것들이다. 발표 · 비교용으로 남겨 두고, 새 기능은 [`webapp/`](../webapp/)에 넣는다.

| 폴더 | 내용 | 여는 법 |
| --- | --- | --- |
| `webapp_v1/` | 폰 · 워치 연동 웹앱 v1 (밤 심박 판정 · 위험 알람 모델 · 실시간 동기화). `engine.py` · `model/risk_v1.json` · `static/` (phone · watch · app.js · ble.js · guide.js · rppg.js v1 · sw.js) | 보관만 한다. 지금 서버는 `/v1` · `/watch`와 그 API를 내보내지 않는다 |
| `watch_app/ExcuseGauge/` | Apple Watch SwiftUI 앱 소스 (Xcode 필요) | Xcode에서 열기 |
| `watch_app/web/` | Xcode 없이 브라우저로 여는 워치 데모 한 장 | `index.html`을 브라우저로 |

v1 엔진 테스트는 `webapp_v1/tests/`에 있고 기본 pytest 수집에서는 빠진다. 돌리려면 `python -m pytest legacy/webapp_v1/tests`.
