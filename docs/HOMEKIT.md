# Homekit2020 — 지속성 계층을 실제 감염 라벨로 검증한다

[`PERSISTENCE.md`](PERSISTENCE.md) 의 결론은 "만들었고, 이 데이터로는 검증 안 됨" 이었다.
Nurse 는 근무 중에만 쟀고, 사건이 자기보고 스트레스였기 때문이다.
Homekit2020 은 **잘 때도 쟀고, PCR 로 확인된 독감**이 있다.

| | |
| --- | --- |
| 출처 | Merrill et al., CHIL 2023 · Evidation Health · 2020-02 ~ 2020-05 |
| 위치 | Synapse [`syn22803188`](https://www.synapse.org/#!Synapse:syn22803188/wiki/609492) (통제 접근) |
| 신호 | Fitbit 분 단위 심박 · 걸음 · 수면 단계 / 하루 요약 |
| 라벨 | 매일 증상 설문 · PCR (Flu A/B, RSV) |
| **없는 것** | **EDA · ACC 원신호.** 스트레스 규칙은 쓸 수 없다. 설명은 운동·수면 부족 둘뿐이다. |

## 신청 절차

| 단계 | 할 일 | 주의 |
| --- | --- | --- |
| 1 | Synapse 가입 | 데이터를 만지는 **팀원 전원이 각자** |
| 2 | Certified User 퀴즈 | 15문항, 약 20분 |
| 3 | 프로필 검증 | 이름·소속·도시 / ORCID 연결(공개, 항목 1개 이상) / Synapse Pledge / **신원 증빙** |
| 4 | [`homekit2020_access`](https://www.synapse.org/#!Team:3434178) 팀 가입 요청 + Intended Data Use 제출 | 계획서는 **공개 게시**된다 |
| 5 | Conditions for Use 동의 | 재식별 금지 · 재배포 금지 · 감사문 · `syn22803188` 인용 · 발표자료 공유 |
| 6 | 다운로드 | `python scripts/17_homekit_download.py` |

**3단계 신원 증빙에서 학생증·졸업장은 안 된다.** 지도교수(본인 불가)가 학교 레터헤드에
**영문**으로 서명한 신원 확인서(최근 1개월 이내)가 현실적이다. 템플릿은 Synapse 도움말에 있다.

발표·보고서에 들어갈 문구:

> These data were contributed by participants as part of the Home Testing of Respiratory
> Illness Study developed by Evidation Health and described in Synapse (doi.org/10.7303/syn22803188).

**원자료와 참가자 ID 가 든 중간 산출물은 커밋하지 않는다.** `data/raw/*`, `data/cache/*`,
`outputs/` 는 이미 `.gitignore` 에 있다.

## 실행

```bash
pip install synapseclient
python scripts/17_homekit_download.py        # SYNAPSE_AUTH_TOKEN 환경변수 필요
python scripts/18_homekit_audit.py           # 로더 상수를 믿기 전에 먼저
python scripts/19_homekit_persistence.py
```

승인 전에는 `--synthetic` 으로 같은 경로를 끝까지 돌릴 수 있다. **합성 수치는 결과가 아니다.**

## 설계 (`src/nesy/homekit.py`)

출력은 `persistence.py` 가 받는 하루 표(`subject_id, day, carried_frac, valid`)다.
`fit_day_thresh / alerts / sweep / chance_baseline` 을 고치지 않고 그대로 쓴다.

| 결정 | 이유 |
| --- | --- |
| 날 경계는 정오~정오, 밤은 **깨어난 날**에 붙인다 | 자정 기준이면 하룻밤이 이틀로 갈라진다 |
| `day_index()` 를 쓰지 않는다 | 그 함수는 UTC epoch → Chicago 가정이다. Fitbit 은 현지 시각 저장이 보통이고 참가자는 미국 전역이다 |
| 분 단위는 조각(batch)으로 읽어 합·개수로 접는다 | 1,400만 시간 ≈ 수억 행. pandas 로 한 번에 못 올린다 |
| 기준선: 과거 28일, **최근 7일 제외**, 중앙값·MAD, 최소 14일 | 잠복기를 기준선에 섞지 않는다. 미래는 보지 않는다 |
| 운동: **전날** 고강도 활동이 개인 상위 10% 또는 30분 이상 | 밤 심박은 전날 운동을 탄다 |
| 수면 부족: 그날 밤 수면이 개인 하위 10% 또는 6시간 미만 | |
| **설명 상한**: 원인별 밤 심박 z 의 train 95분위를 넘으면 설명으로 닫지 않는다 | 운동한 다음 날에도 아플 수 있다 (`deviation.fit_cause_ceiling` 과 같은 생각) |
| **설명된 날은 '해결' 이 아니라 '보류'** (`persistence.alerts(hold_col=...)`) | 해결로 세면 감염 중 하루 운동으로 누적이 0 으로 돌아간다 |
| 사건일 = `trigger_datetime` (증상 신고로 검사가 시작된 날) | 결과 통보일은 며칠 늦다 |
| 사람 단위 분할, 상한·임계는 train 사람에게서만 | 결과 1번의 누수를 반복하지 않는다 |

### 핵심 비교

1. **raw** — 이탈만 본다 (Mishra 방식)
2. **ours** — 이탈 − 설명. 설명된 날은 보류
3. **random** — ours 와 같은 개수의 이탈일을 무작위로 보류
4. **경보 수를 맞춘 raw** — raw 의 z 임계를 올려 ours 와 경보 수를 같게

ours 가 4 보다 탐지율이 높아야 "설명 계층이 일을 한다" 고 말할 수 있다.
경보율을 맞추지 않은 탐지율 비교는 의미가 없다.

### 합성 데이터에서 이미 보인 것 (코드 동작 확인일 뿐, 결과 아님)

- 설명 계층은 경보를 크게 줄이지만 **탐지도 일부 잃는다.** 감염 기간에 운동한 날이
  끼면 그날은 운동으로 설명된다. 실제 데이터에서도 이 손실을 같이 보고해야 한다.
- **보류는 연속을 잇지 않는다.** 그래서 K 가 크면 ours 가 불리해진다
  (6일 감염 중 이틀이 설명되면 3일 연속을 못 채운다). K=1~2 에서 이기고
  K≥3 에서 지는 패턴이 실제로도 나오면, 보류일을 연속에 포함하는 변형을 비교할 것.

## 받은 뒤 먼저 확인할 것 (`18_homekit_audit.py`)

1. 표 위치 — 공개 코드의 경로와 v1.0 zip 배치가 같은가
2. 분 단위가 긴 형식(1행=1분)인가, petastorm 배열 형식인가
3. `sleep_classic_0~3` 의 의미 → `ASLEEP_COLS` 결정
4. timestamp 가 현지 시각인가 (잠든 분이 0~6시에 몰리는가)
5. PCR 독감 양성 수 — 30건 미만이면 탐지율 신뢰구간이 ±0.15 이상

## 미리 짚어둘 함정

- **2020-03 중순부터 봉쇄.** 걸음·수면이 모두에게서 동시에 바뀐다. 기준선이 이것을
  이탈로 잡을 수 있다. `--split-date` 로 봉쇄 전/후를 나눠 같이 보고한다.
- **검사 안 받은 사람 ≠ 건강.** Nurse 의 라벨 없는 92% 와 같은 논리다.
  음성 대조는 '증상 있었으나 PCR 음성' 으로 잡는 것이 깨끗하다.
- 검사는 증상이 있어야 시작됐다. "증상 전 탐지" 는 trigger 일 기준 상대적으로만 말할 수 있다.
