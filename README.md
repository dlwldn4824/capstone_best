# Wearable NeSy — Stress vs Exercise

웨어러블 생체신호에서 **Stress / Exercise / Rest** 를 구분할 때, Neural 모델의
출력을 생리학적 규칙으로 감사(audit)하면 **운동에 의한 생리 변화를 스트레스로
오인하는 비율이 줄어드는가**를 확인한다.

2주 1차 실험 범위. 최종 시스템(개인 baseline anomaly detection → 설명되지 않는
변화 → 질병 검증)은 이후 단계다.

---

## 빠른 시작

```bash
pip install -r requirements.txt
```

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

합성 데이터는 코드 검증 전용이다. 성능 수치는 연구 결과가 아니다
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

| 역할 | 책임 | 주 파일 |
| --- | --- | --- |
| **A** 데이터 파이프라인 | 데이터가 맞는지 책임진다 | `io_e4.py`, `protocol.py`, `preprocess_{bvp,eda,acc}.py`, `feature_extraction.py` |
| **B** 예측 | 성능과 평가를 책임진다 | `subject_split.py`, `evaluate.py`, `baseline_ml.py`, `neural_model.py` |
| **C** 추론 | NeSy 가 왜 그렇게 판단했는지와 연구 논리를 책임진다 | `facts.py`, `rules.py`, `nesy_audit.py`, `nesy_correction.py` |

셋은 서로를 기다리지 않는다. `docs/SCHEMAS.md` 의 CSV 인터페이스에서만 만난다.
합성 데이터 생성기가 있으므로 B 와 C 는 A 의 전처리 완료 전에도 전체 코드를
돌릴 수 있다.

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

NeSy 가 `neural` 만 이기고 `neural_context` 를 못 이기면, 이득은 "ACC 정보
추가"이지 "symbolic reasoning" 이 아니다. 이 구분을 흐리면 결과를 주장할 수 없다.

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

---

## 이미 발견된 설계 함정

첫 실행에서 실제로 밟은 것들이다. 실데이터에서도 그대로 나타난다.

1. **개인 baseline 을 모든 윈도로 만들면 안 된다.**
   운동 세션(HR 130–170)이 분포를 지배해 스트레스 HR(86)이 개인 평균 *아래*로
   내려간다. `HR_HIGH` 가 스트레스에서 한 번도 참이 되지 않아 규칙이 발화하지
   못한다. → `facts.baseline_mask(mode="low_activity")` 로 저활동 윈도만
   참조한다.

2. **활동량은 개인 z-score 로 판정하면 안 된다.**
   참조 윈도가 거의 정지 상태라 분산이 0 에 가깝고, 미세한 움직임도 z 가
   폭발해 `ACTIVITY_HIGH` 가 항상 참이 된다. 그러면 `ACTIVITY_LOW` 를 요구하는
   스트레스 규칙이 영원히 못 쓰인다. → 가속도는 물리량이므로 절대 임계(g)를
   쓰고 민감도를 함께 보고한다.

3. **분포 백분위(global_pct)도 답이 아니다.**
   클래스 균형이 바뀌면 같은 움직임이 데이터셋 구성에 따라 HIGH 가 되기도
   안 되기도 한다.

---

## 문서

| 파일 | 내용 |
| --- | --- |
| `docs/SCHEMAS.md` | **CSV 인터페이스 (Day 1 합의)** — 먼저 읽을 것 |
| `docs/DATA_AUDIT.md` | 데이터 감사 결과 (01 실행 시 생성) |
| `docs/RULES.md` | 규칙 정의 + 생리학적 근거 + coverage (07 실행 시 생성) |
| `docs/EXPERIMENT_LOG.md` | 전체 결과 색인 (08 실행 시 생성) |
| `docs/LITERATURE_VERIFICATION.md` | 선행연구 수치 검증 결과 |
| `configs/protocol.yaml` | tags→라벨 매핑 — **실데이터로 검증 필요** |
