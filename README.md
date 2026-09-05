# 캡스톤 — Wearable Neuro-Symbolic

연구 질문·선행연구·실험 단계(Exp 0–3)는 [`docs/연구설계.md`](docs/연구설계.md)에 논문 형식으로 정리했다.  
핵심 3편 번역본은 [`docs/papers/`](docs/papers/)에 있다.

현재 두 실험이 나란히 들어 있다.

| | 패키지 | 데이터 | 상태 | 문서 |
|---|---|---|---|---|
| **Exp 0** | `src/wesad_phase1/` | WESAD 손목 15명 | REST / STRESS | 아래 |
| **Exp 1** | `src/nesy/` | Stress & Exercise 36명 | REST / STRESS / **EXERCISE** | [`docs/EXP1_STRESS_EXERCISE.md`](docs/EXP1_STRESS_EXERCISE.md) |

---

# Experiment 0 — WESAD REST vs STRESS fact extractor

`src/wesad_phase1/` 의 코드는 WESAD 손목 데이터로 전처리·window·feature pipeline이 도는지 확인하는 단계다. REST vs STRESS 분류 자체가 졸프 주장이 아니다.

```text
WESAD wrist (E4)
BVP / EDA / TEMP / ACC
        ↓
BASELINE vs STRESS only
        ↓
60s window / 30s overlap
        ↓
HR · HRV · EDA · TEMP · Activity features
        ↓
stress probability 준비
+ HR↑ / HRV↓ / EDA↑ / TEMP / Activity facts
```

Amusement, exercise, sleep, 질병 라벨은 넣지 않는다. 하드웨어 연동도 이 단계의 범위가 아니다.

## 왜 WESAD인가

최종 프로토타입 센서와 손목 E4 구성이 같다.

| Proto | WESAD wrist |
|---|---|
| PPG | BVP 64 Hz |
| EDA | EDA 4 Hz |
| TEMP | TEMP 4 Hz |
| ACC | ACC 32 Hz |

데이터: [WESAD (UCI)](https://archive.ics.uci.edu/dataset/465/wesad+wearable+stress+and+affect+detection), [원 배포 페이지](https://ubi29.informatik.uni-siegen.de/usi/data_wesad.html).  
비영리 연구 목적이고, 사용 시 Schmidt et al., ICMI 2018을 인용한다.

## 환경

```bash
cd "/Users/LEEJIWOO/Desktop/캡스톤"
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

디스크가 빠듯하면 zip을 풀지 않는다. pickle에서 **손목 채널만** `data/cache/SX_wrist.npz`로 저장한다.

## 첫 작업 3개

```bash
# 1) WESAD 다운로드 + wrist cache
python -m wesad_phase1.cli download

# 2–3) REST/STRESS window + feature + fact table
python -m wesad_phase1.cli windows
```

결과:

- `data/cache/S2_wrist.npz` … `S17_wrist.npz` (15명, 손목만 ~19 MB)
- `data/processed/wesad_wrist_rest_stress_windows.parquet`
- `data/processed/wesad_wrist_rest_stress_windows.csv`

현재 빌드: **859 windows** (train 569 / val 116 / test 174). REST 557, STRESS 302. 신호는 채널별 native rate로 feature를 계산하며, 전체를 한 주파수로 resampling하지 않는다.

zip(`data/raw/WESAD.zip`, 2.25 GB)은 cache가 생긴 뒤 지워도 된다.

## 입력 / 라벨

```text
BVP, EDA, TEMP, ACC_x, ACC_y, ACC_z

0 = BASELINE (REST)
1 = STRESS
```

WESAD raw ID `3=amusement`, `4=meditation`, `0/5/6/7` 는 window에 넣지 않는다.  
window는 **해당 구간이 전부 BASELINE이거나 전부 STRESS**일 때만 채택한다 (`min_purity=1.0`).

## Feature (18 + quality)

| 그룹 | feature | 주의 |
|---|---|---|
| BVP / HR | `HR_mean`, `HR_std`, `HR_min`, `HR_max` | BVP peak 기반 |
| HRV | `RMSSD`, `SDNN`, `mean_IBI` | pulse interval ≠ ECG RR. 20% IBI jump는 제거 |

손목 BVP HRV는 ECG보다 노이즈가 크다. 1차에서는 **방향성 확인용**이지 clinical HRV가 아니다.
| EDA | `EDA_mean`, `EDA_std`, `SCL_mean`, `SCR_count`, `SCR_mean_amplitude` | 4 Hz 유지 |
| TEMP | `TEMP_mean`, `TEMP_std`, `TEMP_slope` | slope는 °C/s |
| ACC | `ACC_magnitude_mean`, `ACC_magnitude_std`, `ACC_energy` | 운동 구분용 씨앗 |

## Subject split

랜덤 row split 금지. 같은 사람이 train/test에 동시에 들어가면 사람 특성을 외운다.

```text
Train  S2 S3 S4 S5 S6 S7 S8 S9 S10 S11
Val    S13 S14
Test   S15 S16 S17
```

다음 실험에서 LOSO를 추가한다.

## Fact 출력 구조

window feature를 그 사람의 REST median과 비교한다. Neural이 아직 없어도 symbolic 입력 스키마는 고정한다.

```text
hr_state        HIGH | NORMAL | LOW
hrv_state       HIGH | NORMAL | LOW
eda_state       HIGH | NORMAL | LOW
temp_state      HIGH | NORMAL | LOW
activity_state  HIGH | NORMAL | LOW

HR_INCREASED
HRV_DECREASED
EDA_ACTIVATED
ACTIVITY_LOW
stress_rule_hit   # 위 네 fact가 동시에 참
```

1차 symbolic rule (아직 엔진 연결 전):

```text
IF HR_INCREASED AND HRV_DECREASED AND EDA_ACTIVATED AND ACTIVITY_LOW
THEN STRESS_EXPLANATION
```

## 1차 성공 기준

**데이터**

- [x] WESAD wrist loader
- [x] subject별 REST/STRESS window
- [x] 공통 feature dataset

**모델 (아직 안 함)**

- [ ] Logistic / RF / XGBoost subject-independent baseline
- [ ] MLP vs 1D-CNN 비교

**NeSy 준비**

- [x] `HR↑ / HRV↓ / EDA↑ / Activity` fact 컬럼
- [ ] rule engine 입력 연결

## 다음 단계

전체 설계는 [`docs/연구설계.md`](docs/연구설계.md).

1. WESAD feature table로 Logistic / RF / XGBoost (subject-independent) — pipeline sanity
2. ~~PhysioNet Stress & Exercise (Hongn 2025) 4-class~~ → **Exp 1 에서 구현됨**
3. ~~Neural vs Neural+Symbolic에서 stress ↔ exercise 혼동 비교~~ → **Exp 1 에서 구현됨**

---

# Experiment 1 — Stress vs Exercise, Neuro-Symbolic

`src/nesy/` · PhysioNet Wearable Stress & Exercise (Hongn 2025) · 2주 1차 실험

> Neural 모델만 쓸 때 발생하는 **Stress ↔ Exercise 오분류**가, 생리적 fact 와
> 활동 맥락을 규칙으로 결합했을 때 줄어드는가. 줄지 않는다면, 규칙이 최소한
> **틀릴 예측을 미리 표시**할 수 있는가.

Exp 0 이 만든 fact 스키마(`hr_state` / `hrv_state` / `eda_state` /
`activity_state`)를 `HR_HIGH` / `HRV_LOW` / `EDA_HIGH` / `ACTIVITY_HIGH` 로
이어받고, 그 위에 rule engine · evidence audit · correction 을 얹었다.

PhysioNet 다운로드를 기다리지 않고 지금 전 구간을 돌릴 수 있다. 실제 프로토콜과
동일한 태그 구조로 합성 E4 세션을 만드는 생성기가 들어 있다.

```bash
python scripts/00_make_synthetic.py
python scripts/02_build_features.py --raw data/raw/SYNTHETIC
python scripts/07_nesy.py
```

합성 데이터의 성능 수치는 **연구 결과가 아니다** — 코드 검증 전용이다.

실행 순서, 역할 분담(A/B/C), CSV 인터페이스, 이미 발견된 설계 함정 세 개는
[`docs/EXP1_STRESS_EXERCISE.md`](docs/EXP1_STRESS_EXERCISE.md) 에 있다.

| 문서 | 내용 |
|---|---|
| [`docs/SCHEMAS.md`](docs/SCHEMAS.md) | A/B/C 공통 CSV 인터페이스 — 먼저 읽을 것 |
| [`docs/RESEARCH_REVIEW.md`](docs/RESEARCH_REVIEW.md) | 심사자 관점 비판적 리뷰 + 일정 수정안 |
| [`docs/LITERATURE_VERIFICATION.md`](docs/LITERATURE_VERIFICATION.md) | 선행연구 인용 수치 검증 (**Li 2026 은 인용 보류**) |

---

## 테스트

```bash
python -m pytest tests -q
```

Exp 0 + Exp 1 합쳐 19개. 루트 `conftest.py` 가 `src/` 를 경로에 넣으므로
`pip install -e .` 없이도 돈다.
