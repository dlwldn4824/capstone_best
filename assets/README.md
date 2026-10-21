# assets

웹앱이 쓰는 공용 에셋 원본이다. 서버가 폴더와 같은 주소 `/assets/characters/…` · `/assets/fonts/…` 로 내보낸다 (`webapp/server.py` 의 `STATIC_ROOTS`).

| 폴더 | 파일 | 쓰는 곳 |
| --- | --- | --- |
| `characters/` | `calm` · `idle` · `coffee` · `sleep` · `move` · `drink` · `cold` · `med` · `alert` (640px) · `ask` · `left` · `tense` (약 120px) | 인트로 · 홈 · 결과 · 그룹 캐릭터 · 이유 고르기 |
| `fonts/` | `PretendardVariable.woff2` (앱 글꼴) · `Dunggeunmiso-Bold.otf` (예전 제목 글꼴, 지금은 안 씀) | `webapp/static/app.css` |

`calm.png` 과 `idle.png` 은 같은 그림이다. `ask` · `left` · `tense` 는 해상도가 낮아 작게만 쓴다.
