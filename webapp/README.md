# webapp

Python 서버(`server.py`) 하나가 화면 세 개와 API를 내보낸다. 명령은 저장소 루트에서 실행한다.

```bash
pip install -r requirements.txt
npm --prefix webapp/face ci
npm --prefix webapp/face run build        # /face
npm --prefix webapp/face run build:lib    # /check가 쓰는 측정 엔진 → static/vity-face.js
python webapp/server.py                   # http://localhost:8000
python webapp/server.py --https           # 휴대폰 카메라용. 자체 서명 인증서를 data/에 만든다
```

휴대폰 브라우저는 https(또는 localhost)에서만 카메라를 연다. `--https`로 켜고 같은 와이파이의 휴대폰에서 `https://<노트북 IP>:8000/check`를 연다. 노트북 IP는 서버를 켤 때 터미널에 나온다. 인증서는 openssl로 만들므로 openssl이 있어야 한다(macOS · Linux에는 기본으로 있고, Windows는 Git for Windows에 들어 있다). 휴대폰에 경고가 뜨면 고급 → 계속.

| 주소 | 화면 | 파일 |
| --- | --- | --- |
| `/check` | Vity 체크. 30초 스캔 · 결과 · 공부 모드 · 스터디 그룹 · 기록 | `static/check.html`, API `/api/c/*` → `check.py` |
| `/` | 거울 기록. 루틴별 15초 측정 · 이유 묻기 · 시험기간 리포트 | `static/mirror.html`, API `/api/m/*` → `mirror.py` |
| `/face/` | 얼굴 측정만 떼어 낸 시연 앱 | `face/dist/` (`npm run build`) |
| `/vity-face.js` | `/check`가 불러 쓰는 측정 엔진 | `static/vity-face.js` (`npm run build:lib`) |
| `/assets/…` | 캐릭터 · 글꼴 | 저장소 `assets/` |

`/check`와 `/face`는 같은 측정 엔진(`face/src/`)을 쓴다. 설계와 품질 기준은 [`docs/app/FACE_DESIGN.md`](../docs/app/FACE_DESIGN.md), 화면별 상태는 [`docs/app/STATUS.md`](../docs/app/STATUS.md)에 있다.

## 데이터

서버에는 브라우저가 계산한 숫자만 온다.

| 파일 | 내용 |
| --- | --- |
| `data/check.db` | `/check` 측정 기록 · 프로필 · 그룹 (SQLite) |
| `data/mirror.db` | 거울 기록 (SQLite) |
| `data/dev.crt` · `data/dev.key` | `--https`용 자체 서명 인증서 |

`data/`는 git에서 뺀다. 예전에는 저장소 루트의 `data/app/`에 있었으니, 그 기록을 계속 쓰려면 옮긴다.

```bash
mkdir -p webapp/data && mv data/app/check.db data/app/mirror.db webapp/data/
```

## 폴더

| 폴더 | 내용 |
| --- | --- |
| `static/` | `/check` · `/` 화면. `rppg2.js` · `facemesh.js`는 거울 기록이, `meshdraw.js`는 두 화면이 쓴다. `vitals.js`는 예전 `/check` 엔진으로, 지금은 테스트에서 지난 기록과 같은 값을 내는지 비교할 때만 쓴다 |
| `face/` | 측정 엔진과 `/face` 화면 (Vite · vitest) |
| `tests/` | 서버 · API · 프라이버시 검사 (pytest) |
| `data/` | 기록 DB · 인증서 (git 제외) |

거울 기록의 얼굴 메시 모델은 `python webapp/fetch_vendor.py`로 한 번 받아 `static/vendor/`에 둔다. 받지 않으면 거울 기록 화면이 CDN에서 불러온다.
