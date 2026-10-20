# 공통 파일 인터페이스 (Day 1 합의 사항)

A / B / C 세 역할은 **이 파일들로만** 소통한다. 여기 정의된 컬럼은 합의 없이
바꾸지 않는다. 컬럼을 **추가**하는 것은 자유지만 **이름 변경·삭제**는 셋이
합의해야 한다.

---

## 1. `outputs/features.csv` — 역할 A 가 생산

한 행 = 한 시간 윈도.

### 메타 컬럼

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| `sample_id` | str | `{subject}|{session}|{segment}|{t_start}` — 전역 유일 키 |
| `subject_id` | str | `S01`…`S18`, `f01`…`f18` |
| `session_type` | str | `STRESS` / `AEROBIC` / `ANAEROBIC` |
| `session_id` | str | `{subject}|{session_type}` |
| `version` | str | `v1`(S 코호트) / `v2`(f 코호트) — 프로토콜이 다르다 |
| `segment_name` | str | `baseline`, `tmct`, `rpm85`, `sprint2` … |
| `seg_index` | int | 세션 내 구간 순번 |
| `condition` | str | **4-class**: `REST` / `STRESS` / `AEROBIC` / `SPRINT` |
| `label` | str | **3-class**: `REST` / `STRESS` / `EXERCISE` ← 기본 학습 타깃 |
| `t_start`, `t_end` | float | UTC epoch seconds |
| `needs_review` | bool | 프로토콜 불일치. `True` 면 이 행은 생성되지 않는다 |
| `ml_excluded` | bool | 원 논문이 제외한 피험자 (`f07`, `f13`) |
| `flagged` | bool | `data_constraints.txt` 에 품질 이슈가 기록된 세션 |

### Feature 컬럼 (총 51 = 논문 49 + 품질지표 2)

| 그룹 | 개수 | 컬럼 |
| --- | --- | --- |
| BVP | 2 | `bvp_mean`, `bvp_std` |
| HR | 4 | `hr_mean`, `hr_std`, `hr_ratio_up`, `hr_ratio_down` |
| HRV 시간 | 8 | `ibi_mean/max/min`, `hr_from_ibi`, `rmssd`, `sdnn`, `pnn20`, `pnn50` |
| HRV 주파수 | 12 | `{VLF,LF,HF,VHF}_{power,peak}`, `total_power`, `LF_n`, `HF_n`, `LF_HF_ratio` |
| EDA | 14 | `mean/std_raw_eda`, `mean/std_tonic_eda`, `mean/std_phasic_eda`, `tonic_ratio_up/down`, `peaks_density`, `mean_amplitude`, `mean_onset_sample`, `mean_peak_sample`, `mean_risetime`, `mean_recoverytime` |
| ACC | 11 | `{x,y,z}_{mean,std}`, `acc_mean`, `acc_std`, `acc_ratio_up/down`, `acc_dyn_mean` |
| 품질 | 1 | `n_beats` — 이 윈도에서 검출된 유효 박동 수 |

> **`acc_dyn_mean`** 은 중력을 뺀 순수 움직임(g). NeSy 의 `ACTIVITY_HIGH` 가
> 이것을 쓴다. `acc_mean` 은 중력을 포함해 정지 시 약 1 g 이므로 활동 지표로
> 쓰면 안 된다.
>
> **주파수영역 HRV 는 60초 윈도에서 신뢰할 수 없다.** VLF 는 한 주기도
> 들어가지 않고 LF 도 두 주기 남짓이다. 학습에는 넣되 생리학적 해석은 붙이지
> 않는다. sprint 윈도(45초, 박동 30개 미만)에서는 전부 NaN 이다.

읽는 법:
```python
from nesy import feature_extraction
df = feature_extraction.load_features(cfg)          # ml_excluded 자동 제외
cols = feature_extraction.ALL_FEATURES              # ablation 은 ABLATION_SETS
```

---

## 2. `outputs/predictions_{model}.csv` — 역할 B 가 생산

| 컬럼 | 설명 |
| --- | --- |
| `experiment`, `model`, `split`, `feature_set`, `fold` | 실행 식별자 |
| `sample_id` | features.csv 와 조인하는 키 |
| `subject_id` | |
| `true_label`, `pred_label` | 3-class |
| `confidence` | 예측 클래스의 확률 (max softmax) |
| `p_REST`, `p_STRESS`, `p_EXERCISE` | 클래스별 확률 — 역할 C 가 쓴다 |

행 순서는 `features.csv` 와 같지 않아도 된다. 역할 C 는 `sample_id` 로 정렬을
맞춘다.

---

## 3. `outputs/facts.csv` — 역할 C 가 생산

| 컬럼 | 설명 |
| --- | --- |
| `sample_id`, `subject_id`, `true_label` | 키 |
| `HR_HIGH`, `HRV_LOW`, `EDA_HIGH`, `SCR_HIGH`, `ACTIVITY_HIGH` | bool |
| `{fact}_LOW` | 반대 방향 상태 |
| `ACTIVITY_LOW` | `ACTIVITY_HIGH_LOW` 의 별칭 (규칙 가독성) |
| `z_{fact}` | 판정에 쓰인 점수 (절대 임계 fact 는 원값) |

---

## 4. `outputs/results.csv` — 세 역할이 공유 (append)

| 컬럼 | 설명 |
| --- | --- |
| `experiment`, `model`, `split`, `feature_set`, `task` | 식별자 (이 5개가 유일키) |
| `n_test` | 평가 샘플 수 |
| `accuracy`, `macro_f1`, `balanced_accuracy` | 표준 지표 |
| `rest_f1`, `stress_f1`, `exercise_f1` | 클래스별 |
| `stress_to_exercise` | **P(pred=EXERCISE \| true=STRESS)** ← 핵심 지표 |
| `exercise_to_stress` | **P(pred=STRESS \| true=EXERCISE)** ← 핵심 지표 |
| `abstain_rate` | `UNCERTAIN` 비율 |
| `flag_precision`, `flag_recall` | audit 이 Neural 오류를 잡는 능력 |
| `notes` | 자유 기술 |

```python
from nesy.evaluate import ResultsWriter
w = ResultsWriter(out / "results.csv")
w.add("three_class", "xgboost", "group_kfold", "ALL", metrics)
w.flush()     # 같은 유일키는 최신 것만 남는다
```

---

## 5. 라벨 정의 (합의)

```
4-class  REST / STRESS / AEROBIC / SPRINT      (condition)
3-class  REST / STRESS / EXERCISE              (label)  ← 기본
         AEROBIC, SPRINT -> EXERCISE
```

`REST` 는 다음을 모두 포함한다: 스트레스 세션의 baseline·휴식 블록,
운동 세션의 baseline·종료 후 휴식 블록. 원 논문을 따라 휴식 블록은
**후반부만** 사용한다 (잔여 각성 효과 배제).

## 6. 분할 방식 (합의)

| 이름 | 용도 |
| --- | --- |
| `group_kfold` | **기본 보고값**. subject 단위 5-fold |
| `loso` | 피험자별 오류 분석용 |
| `random` | **대조군 전용**. 논문 수치와 비교할 때만. 누수가 있다 |

`random` 을 주 결과로 보고하지 않는다.
