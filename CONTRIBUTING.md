# 협업 규칙

`main`에는 직접 푸시하지 않고 PR로만 합친다.

## 준비

```bash
pip install -r requirements.txt pytest     # 연구 실험까지 돌리려면 -r research/requirements-ml.txt 추가
npm --prefix webapp/face ci
```

PR을 올리기 전에 CI와 같은 순서로 돌려 본다.

```bash
python -m pytest -q
npm --prefix webapp/face test
npm --prefix webapp/face run build
npm --prefix webapp/face run build:lib
```

## 브랜치

`<type>/<짧은-영문-설명>`으로 만든다.

```
feat/quick-scan    fix/ring-offset    docs/readme-refresh
```

## 커밋 · PR 제목

형식은 `type(scope): 한국어 제목`이다. squash로 합치기 때문에 PR 제목이 main에 남는 커밋 제목이 된다. 브랜치 안의 커밋은 편하게 써도 된다.

| type | 쓰는 때 |
| --- | --- |
| `feat` | 사용자가 보는 기능이 생기거나 바뀔 때 |
| `fix` | 버그를 고칠 때 |
| `docs` | 문서만 바꿀 때 |
| `test` | 테스트나 합성 실험만 바꿀 때 |
| `refactor` | 동작은 그대로 두고 코드를 정리할 때 |
| `chore` | 빌드, CI, 설정, 폴더 정리 |

| scope | 고친 곳 |
| --- | --- |
| `face` | `webapp/face/` (측정 엔진, `/face` 화면) |
| `check` | `/check` 화면, `webapp/check.py` |
| `mirror` | `/` 거울 기록, `webapp/mirror.py` |
| `server` | `webapp/server.py`, 서버 공통 |
| `research` | `research/` |
| `docs` | `docs/`, README |
| `ci` | `.github/` |

여러 곳을 함께 고쳤다면 scope를 뺀다.

- 제목은 50자 안에서 마침표 없이 명사형으로 끝낸다.
- "버그 수정", "로직 개선"처럼 뭉뚱그리지 않고 무엇이 어떻게 바뀌는지 쓴다.
  - ✗ `fix(face): 진행 링 버그 수정`
  - ✓ `fix(face): 진행 링이 12시 방향에서 시작하도록 경로 수정`

이 저장소의 실제 커밋 예:

```
feat(face): 흔들림 보정(G2) · 빠른 측정(조기 종료)
test(face): 흔들림 보정 · 측정 시간 단축 합성 실험
docs(face): G2 흔들림 보정 · 빠른 측정 사양
```

## PR과 머지

- PR 하나에는 목적 하나만 담는다.
- 템플릿의 두 칸(무엇을 · 왜, 어떻게 확인했나)을 채운다. PR 본문은 squash 커밋의 본문으로 main에 남으니, 측정 기준이나 수식을 바꿨거나 우회 구현을 넣었다면 그 이유를 여기에 쓴다.
- 화면을 바꿨다면 휴대폰 폭으로 찍은 캡처를 붙인다.
- CI가 통과해야 머지한다.
- `webapp/`을 바꾼 PR은 팀원 한 명에게 리뷰를 요청한다. 승인을 받았거나, 요청하고 12시간이 지나도록 리뷰가 없으면 작성자가 머지한다. 나머지 PR은 CI가 통과하면 바로 머지한다.
- Squash and merge로 합친다.

## 지킬 것

- 카메라: 카메라 프레임, 얼굴 영역 픽셀, 얼굴 랜드마크는 메모리에서만 쓴다. 저장하지 않고 서버로 보내지 않는다. 서버로는 브라우저가 계산한 숫자만 보낸다. `webapp/tests/test_privacy_guard.py`가 측정 엔진(`webapp/face/src`)과 화면(`webapp/static`)에서 프레임을 파일로 만들거나 밖으로 보낼 수 있는 API(`toDataURL`, `MediaRecorder`, `sendBeacon` 등)를 찾고, 픽셀을 읽는 파일도 정해 둔 곳으로 제한한다. 이 테스트의 허용 목록을 늘려야 한다면 PR 본문에 이유를 쓴다.
- 외부 요청: `/check`와 `/face`는 실행 중 외부 서버에 요청하지 않는다. 라이브러리와 모델 파일도 CDN이 아니라 같은 서버에서 받는다.
- 커밋하지 않는 것: 얼굴 영상, 사진, 생체 원자료, 앱 기록 DB(`webapp/data/`), 빌드 결과(`webapp/face/dist/`, `webapp/static/vity-face.js`).
- 측정 기준과 문서: `QUALITY` · `ROBUST` · `WINDOW` · `FRAMING` · `EARLY_STOP` 상수를 바꾸면 같은 PR에서 [`docs/app/FACE_DESIGN.md`](docs/app/FACE_DESIGN.md)도 고친다. 문서에 적힌 기준값은 `webapp/face/tests/docs_sync.test.js`가 코드와 맞춰 보고, 어긋나면 실패한다. 발표 자료에 같은 숫자가 있으면 PR 본문에 적어 둔다.
- 숫자의 출처: 문서나 발표에 정확도 숫자를 쓸 때는 그 숫자를 만든 스크립트와 데이터를 함께 적는다. 예: `research/scripts/24_mcd_analysis.py`, MCD-rPPG 100명.
- 새 지표: 화면에 지표를 새로 넣을 때는 근거가 된 출처를 [`webapp/face/src/ui/evidence.js`](webapp/face/src/ui/evidence.js)나 설계 문서에 남긴다.
- legacy: `legacy/`의 코드는 고치지 않고, 다른 코드에서 import하지 않는다.

## 저장소 설정 (관리자)

- Settings → Branches → `main` 보호 규칙
  - Require a pull request before merging을 켜고, 그 아래 Require approvals는 끈다.
  - Require status checks to pass를 켜고 `python`, `face`를 등록한다.
  - Allow force pushes는 끈 채로 둔다.
- Settings → General → Pull Requests
  - Allow squash merging만 켜고, 기본 메시지는 "Pull request title and description"
  - Automatically delete head branches를 켠다.
