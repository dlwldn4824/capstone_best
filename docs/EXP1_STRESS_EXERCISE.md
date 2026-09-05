# Experiment 1 — Stress vs Exercise, Neuro-Symbolic

`src/nesy/` · PhysioNet Wearable Stress & Exercise (Hongn 2025)

Exp 0(`src/wesad_phase1/`)이 WESAD 손목 데이터로 REST vs STRESS 파이프라인이
도는지 확인했다면, Exp 1 은 **운동이 들어왔을 때** 무슨 일이 생기는지를 본다.

> Neural 모델만 쓸 때 발생하는 **Stress ↔ Exercise 오분류**가, 생리적 fact 와
> 활동 맥락을 규칙으로 결합했을 때 줄어드는가. 줄지 않는다면, 규칙이 최소한
> **틀릴 예측을 미리 표시**할 수 있는가.

2주 1차 실험 범위. 개인 baseline anomaly detection → 설명되지 않는 변화 →
질병 검증(CovIdentify)은 이후 단계다.

---

## Exp 0 과의 관계

| | Exp 0 (`wesad_phase1`) | Exp 1 (`nesy`) |
| --- | --- | --- |
| 데이터 | WESAD 손목 15명 | Stress & Exercise 36명 |
| 상태 | REST / STRESS | REST / STRESS / **EXERCISE** |
| 목적 | 전처리·window·fact 스키마 확인 | NeSy 효과 검증 |
| Symbolic | fact 컬럼까지 | rule engine + audit + correction |

두 패키지는 독립적으로 돈다. Exp 0 의 fact 스키마(`hr_state`, `hrv_state`,
`eda_state`, `activity_state`)를 Exp 1 이 `HR_HIGH` / `HRV_LOW` / `EDA_HIGH` /
`ACTIVITY_HIGH` 로 이어받는다. Day 13 의 WESAD 이식성 검증에서 Exp 0 의
loader 를 재사용한다.

---

## 빠른 시작

### 실데이터 없이 지금 바로 (권장 — 첫 실행)

```bash
python scripts/00_make_synthetic.py
python scripts/01_audit.py --raw data/raw/SYNTHETIC
python scripts/02_build_features.py --raw data/raw/SYNTHETIC
python scripts/03_baseline_ml.py
python scripts/04_stress_vs_exercise.py
python scripts/05_subject_independent.py
python scripts/06_neural.py
python scripts/07_nesy.py
python scripts/08_report.py
```

합성 데이터는 **코드 검증 전용**이다. 생리 파라미터를 우리가 직접 심어
넣었으므로 분류가 쉬운 것이 당연하고, 성능 수치는 연구 결과가 아니다
(`src/nesy/synthetic.py` 상단 설명 참조).

### 실데이터

```bash
python scripts/00_download.py
```

받은 뒤 `configs/config.yaml` 의 `paths.raw` 를 `STRESS/`, `AEROBIC/`,
`ANAEROBIC/` 폴더가 있는 디렉터리로 맞춘다. 그다음 `01_audit.py` 부터
`--raw` 없이 다시 돌린다.

> **`01_audit.py` 의 출력을 반드시 눈으로 확인할 것.**
> `configs/protocol.yaml` 의 tags→라벨 매핑은 논문 본문 서술로부터 재구성한
> 것이며 실제 `tags.csv` 로 검증되지 않았다. 태그 개수가 기대와 다른 세션은
> 자동으로 제외되므로, 대부분의 세션이 제외된다면 매핑을 고쳐야 한다.

### 테스트

```bash
python -m pytest tests -q
```

---

## 역할 분담

| 역할 | 책임 | 주 파일 (`src/nesy/`) |
| --- | --- | --- |
| **A** 데이터 파이프라인 | 데이터가 맞는지 책임진다 | `io_e4.py`, `protocol.py`, `preprocess_{bvp,eda,acc}.py`, `feature_extraction.py` |
| **B** 예측 | 성능과 평가를 책임진다 | `subject_split.py`, `evaluate.py`, `baseline_ml.py`, `neural_model.py` |
| **C** 추론 | NeSy 가 왜 그렇게 판단했는지와 연구 논리를 책임진다 | `facts.py`, `rules.py`, `nesy_audit.py`, `nesy_correction.py` |

셋은 서로를 기다리지 않는다. [`SCHEMAS.md`](SCHEMAS.md) 의 CSV 인터페이스에서만
만난다. 합성 데이터 생성기가 있으므로 B 와 C 는 A 의 전처리 완료 전에도 전체
코드를 돌릴 수 있다.

---

## 파이프라인

```
E4 raw (BVP 64Hz / ACC 32Hz / EDA·TEMP 4Hz / HR 1Hz)
        │
        │  tags.csv → 프로토콜 구간 분할 (protocol.yaml)
        │  60초 윈도 / 30초 step
        ▼
   [A] 전처리 + 51 feature ──────────► outputs/features.csv
        │
        ├─► [B] XGBoost / LR / RF        ──► results.csv
        │       subject-independent 평가
        │
        └─► [B] MLP  (HR+HRV+EDA)        ──► predictions_neural.csv
                MLP  (+ACC = Neural+Context)
                     │
                     ▼
            [C] facts.py  →  rules.py  →  audit / correction
                     │
                     ▼
              최종 비교표 + Fig 4/6
```

### 왜 `neural` 이 ACC 를 안 보는가

세 조건을 갈라야 질문에 답할 수 있다.

| 모델 | 활동 맥락을 |
| --- | --- |
| `neural` | 전혀 안 본다 → NeSy 가 개선할 수 있는 상한 |
| `neural_context` | **숫자로** 본다 (ACC feature) |
| `nesy_audit` / `nesy_correction` | **규칙으로** 본다 |

NeSy 가 `neural` 만 이기고 `neural_context` 를 못 이기면, 그 이득은
"ACC 정보 추가"이지 symbolic reasoning 이 아니다. 이 구분을 흐리면 결과를
주장할 수 없다.

---

## 핵심 지표

정확도보다 **방향성 있는 오분류**가 연구 질문에 직접 답한다.

```
stress_to_exercise = P(pred=EXERCISE | true=STRESS)
exercise_to_stress = P(pred=STRESS   | true=EXERCISE)
```

Audit 은 라벨을 바꾸지 않으므로 분류 지표가 Neural 과 동일하다. Audit 의
가치는 **오류 탐지**로만 평가한다.

```
flag_precision = 표시한 것 중 실제 오류 비율
flag_recall    = 실제 오류 중 표시한 비율
```

Correction 은 반드시 장부와 함께 보고한다: `fixed`(고침) / `broken`(망침) /
`net_gain`. `net_gain` 이 음수인데 Macro F1 만 보고하면 결과를 왜곡하는 것이다.

표본은 윈도가 아니라 **사람**이다. 피험자 단위 Wilcoxon signed-rank +
효과 크기를 `outputs/tables/significance.csv` 로 낸다.

---

## 이미 발견된 설계 함정

첫 실행에서 실제로 밟은 것들이다. 실데이터에서도 그대로 나타난다.

1. **개인 baseline 을 모든 윈도로 만들면 안 된다.**
   운동 세션(HR 130–170)이 분포를 지배해 스트레스 HR(86)이 개인 평균 *아래*로
   내려간다. `HR_HIGH` 가 스트레스에서 한 번도 참이 되지 않아 stress 규칙이
   발화하지 못한다. → `facts.baseline_mask(mode="low_activity")` 로 저활동
   윈도만 참조한다.

2. **활동량은 개인 z-score 로 판정하면 안 된다.**
   참조 윈도가 거의 정지 상태라 분산이 0 에 가깝고, 미세한 움직임도 z 가
   폭발해 `ACTIVITY_HIGH` 가 항상 참이 된다. 그러면 `ACTIVITY_LOW` 를 요구하는
   스트레스 규칙이 영원히 못 쓰인다. → 가속도는 물리량이므로 절대 임계(g)를
   쓰고 민감도를 함께 보고한다.

3. **분포 백분위(`global_pct`)도 답이 아니다.**
   클래스 균형이 바뀌면 같은 움직임이 데이터셋 구성에 따라 HIGH 가 되기도
   안 되기도 한다.

세 단계 모두 `outputs/tables/threshold_sweep.csv` 에 남아 논문 부록의 민감도
분석이 된다.

---

## 원문에서 확인한 사항 (계획서에 없던 것)

**Hongn 2025 의 프로토콜은 두 버전이다.** v1(S 코호트)에는 Stroop 이 있고
v2(f 코호트)에는 없다. 휴식 위치도 다르고, 무산소는 v1 이 30초 스프린트 3회 /
v2 가 45초 4회다. 하나의 태그 매핑으로 전체를 처리할 수 없다.
`configs/protocol.yaml` 이 `version_by_prefix` 로 처리한다.

원 논문은 `f07`·`f13` 두 명을 착용 불량으로 제외했고, 8개 세션에 품질 이슈를
기록해 두었다. `configs/config.yaml` 의 `exclude` 에 반영했다.

---

## 문서

| 파일 | 내용 |
| --- | --- |
| [`SCHEMAS.md`](SCHEMAS.md) | **CSV 인터페이스 (Day 1 합의)** — 먼저 읽을 것 |
| [`RESEARCH_REVIEW.md`](RESEARCH_REVIEW.md) | 심사자 관점 비판적 리뷰 + 일정 수정안 |
| [`LITERATURE_VERIFICATION.md`](LITERATURE_VERIFICATION.md) | 선행연구 인용 수치 검증 |
| `DATA_AUDIT.md` | 데이터 감사 (01 실행 시 생성, 미추적) |
| `RULES.md` | 규칙 + 근거 + coverage (07 실행 시 생성, 미추적) |
| `EXPERIMENT_LOG.md` | 전체 결과 색인 (08 실행 시 생성, 미추적) |
