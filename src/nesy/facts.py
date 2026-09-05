"""연속 feature -> 이산 생리 fact.

fact 는 NeSy 의 입력 어휘다. 무엇을 fact 로 삼는지가 곧 "우리가 어떤 생리
지식을 명시적으로 쓰는가" 이므로, 근거는 docs/RULES.md 에 정리한다.

threshold 전략 (세 방식을 반드시 비교할 것 - 2주 계획 Day 10/11)
  fixed        : train fold 의 전역 분포로 임계 결정. 개인차를 무시한다.
  train_z      : train fold 의 전역 mean/std 로 z-score. fixed 와 거의 같다.
  subject_z    : 피험자 '자신의' 윈도 분포로 z-score. = 개인 baseline.
  subject_pct  : 피험자 내 백분위.

!! 공정성 주의 !!
subject_z / subject_pct 는 테스트 피험자의 데이터 분포를 쓴다. 라벨은 쓰지
않으므로 정보 누수는 아니지만, "그 사람의 여러 상태를 이미 관측했다"는
가정이 들어간다. 이는 Mishra 2020 / Quer 2021 의 personal baseline 과 같은
가정이며, 논문에 반드시 명시해야 한다. 실시간 시나리오에서는 과거 REST
구간만으로 baseline 을 만들어야 한다.

담당: 역할 C (NeSy/Rule)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# fact 이름 -> (feature, 방향, 전략 override).
# 방향 +1 = 값이 크면 fact 참. 전략 override 가 None 이면 전역 전략을 쓴다.
#
# ACTIVITY_HIGH 만 "global_pct" 로 고정하는 이유 (설계상 중요):
#   HR / HRV / EDA 는 개인차가 매우 커서 개인 baseline 대비로 봐야 한다.
#   반면 손목 가속도 크기는 물리량이라 사람 간 비교가 가능하다. 이것을 개인
#   z-score 로 바꾸면, 정지 상태로만 이루어진 baseline 의 분산이 거의 0 이라
#   미세한 움직임도 z 가 폭발해 ACTIVITY_HIGH 가 항상 참이 된다. 그러면
#   ACTIVITY_LOW 를 요구하는 스트레스 규칙이 영원히 발화하지 못한다.
#   (이 현상은 실제로 관측됐고 outputs/tables/threshold_sweep.csv 에 남는다.)
#
#   분포 기반(global_pct)도 답이 아니다. 클래스 균형이 바뀌면 백분위가 흔들려
#   같은 움직임이 데이터셋 구성에 따라 HIGH 가 되기도 안 되기도 한다.
#   그래서 ACTIVITY 만 절대 임계(g)를 쓴다. 매직 넘버지만 물리량이고,
#   ACTIVITY_ABS_SWEEP 로 민감도를 함께 보고한다.
FACT_DEFS = {
    "HR_HIGH":       ("hr_mean", +1, None),
    "HRV_LOW":       ("rmssd", -1, None),
    "EDA_HIGH":      ("mean_tonic_eda", +1, None),
    "SCR_HIGH":      ("peaks_density", +1, None),
    # 임계 0.020 g 는 실데이터에서 정했다 (합성 데이터 기준 0.05 는 2.5배 높아
    # 운동 윈도의 40% 밖에 못 잡았다). 실측 판정률:
    #     0.010 g -> EXERCISE 0.99 / REST 0.28 / STRESS 0.30   (거짓양성 과다)
    #     0.020 g -> EXERCISE 0.89 / REST 0.07 / STRESS 0.09   <- 채택
    #     0.030 g -> EXERCISE 0.71 / REST 0.02 / STRESS 0.04   (운동 놓침)
    # high 와 low 를 같은 값으로 두어 "움직인다/안 움직인다"의 단일 경계로 쓴다.
    "ACTIVITY_HIGH": ("acc_dyn_mean", +1,
                      {"strategy": "absolute", "high": 0.020, "low": 0.020}),
    # 2단계 활동량. acc_dyn_mean 은 문헌의 MAD(mean amplitude deviation)와
    # 같은 양이며, 가속도 강도 구간을 나누는 것은 신체활동 연구의 표준 방식이다
    # (Vähä-Ypyä 2015: MAD 91 mg = 3 MET, 414 mg = 6 MET / Hildebrand 2014 ENMO
    #  손목 50·110·440 mg). 다만 그 기준값들은 보행·달리기를 전제로 유도된 것이라
    # 손잡이를 잡고 하는 고정식 자전거에는 그대로 쓸 수 없다 — 실제로 본 데이터의
    # 운동 윈도 중앙값은 42 mg 로 문헌의 '가벼움' 경계에도 못 미친다.
    # 따라서 구간을 나눈다는 개념만 가져오고 값은 fold 안에서 정한다.
    "ACTIVITY_VERY_HIGH": ("acc_dyn_mean", +1,
                           {"strategy": "absolute", "high": 0.045, "low": 0.045}),
}

# Day 10 민감도 분석에서 훑을 절대 임계 후보 (g)
ACTIVITY_ABS_SWEEP = (0.010, 0.015, 0.020, 0.030, 0.050)
ACTIVITY_VH_SWEEP = (0.030, 0.035, 0.040, 0.045, 0.050, 0.060, 0.070)

FACT_NAMES = list(FACT_DEFS)

# 3단계(LOW/NORMAL/HIGH) 상태도 함께 낸다. audit 에서 'ACTIVITY_LOW' 가 필요하다.
STATE_SUFFIXES = ("_HIGH", "_NORMAL", "_LOW")

FACTS_COLS = (["sample_id", "subject_id", "true_label"]
              + FACT_NAMES
              + [f + "_LOW" for f in FACT_NAMES]
              + ["STRESS_EVIDENCE", "EXERCISE_EVIDENCE"])


def baseline_mask(df, mode="low_activity", activity_col="acc_dyn_mean",
                  pct=0.5):
    """개인 baseline 을 계산할 참조 윈도를 고른다.

    !! 이 함수가 NeSy 전체에서 가장 중요한 설계 결정이다 !!

    피험자의 '모든' 윈도로 z-score 를 내면 운동 세션이 분포를 지배한다.
    운동 HR(130-170)이 평균을 끌어올려 스트레스 HR(86)이 개인 평균 아래로
    내려가고, HR_HIGH 가 스트레스에서 한 번도 참이 되지 않는다. 규칙이
    발화하지 않으므로 NeSy 는 아무것도 못 한다.

    mode
      all           모든 윈도 (비교용. 위 문제가 그대로 나타난다)
      low_activity  피험자 내 활동량 하위 pct 윈도. 라벨을 쓰지 않는
                    안정 구간 대용이며 Mishra 2020 의 resting baseline 과
                    같은 취지다. **기본값**
      labeled_rest  라벨이 REST 인 윈도. 라벨을 쓰므로 oracle 이며,
                    low_activity 의 상한을 보는 용도로만 쓴다.
    """
    n = len(df)
    if mode == "all":
        return np.ones(n, dtype=bool)
    if mode == "labeled_rest":
        if "label" not in df.columns:
            return np.ones(n, dtype=bool)
        return (df["label"] == "REST").to_numpy()
    if mode == "low_activity":
        if activity_col not in df.columns:
            return np.ones(n, dtype=bool)
        m = np.zeros(n, dtype=bool)
        a = df[activity_col].to_numpy(dtype=float)
        for _, idx in df.groupby("subject_id").indices.items():
            v = a[idx]
            thr = np.nanpercentile(v, pct * 100)
            sel = v <= thr
            if sel.sum() < 3:      # 참조가 너무 적으면 전체를 쓴다
                sel = np.ones(len(v), dtype=bool)
            m[np.asarray(idx)[sel]] = True
        return m
    raise ValueError("알 수 없는 baseline mode: {}".format(mode))


def _scores(df, feature, strategy, train_mask=None, ref_mask=None):
    """feature -> 부호 있는 표준화 점수 (클수록 '높다').

    ref_mask 가 주어지면 피험자별 평균/표준편차를 그 윈도들에서만 구한다
    (= personal baseline). 점수는 전체 윈도에 대해 계산된다.
    """
    x = df[feature].to_numpy(dtype=float)

    if strategy in ("fixed", "train_z"):
        ref = x[train_mask] if train_mask is not None else x
        mu = np.nanmean(ref)
        sd = np.nanstd(ref)
        sd = sd if np.isfinite(sd) and sd > 0 else 1.0
        return (x - mu) / sd

    if strategy == "global_pct":
        # 전체 피험자 분포에서의 백분위 -> z 스케일. 개인차를 쓰지 않는다.
        ref = x[train_mask] if train_mask is not None else x
        ref = np.sort(ref[np.isfinite(ref)])
        if len(ref) == 0:
            return np.full(len(x), np.nan)
        pct = np.searchsorted(ref, x) / len(ref)
        return (pct - 0.5) * 4.0

    if ref_mask is None:
        ref_mask = np.ones(len(x), dtype=bool)

    if strategy == "subject_z":
        out = np.full(len(x), np.nan)
        for s, idx in df.groupby("subject_id").indices.items():
            idx = np.asarray(idx)
            ref = x[idx[ref_mask[idx]]]
            if len(ref) < 3 or not np.isfinite(np.nanstd(ref)):
                ref = x[idx]
            mu, sd = np.nanmean(ref), np.nanstd(ref)
            sd = sd if np.isfinite(sd) and sd > 0 else 1.0
            out[idx] = (x[idx] - mu) / sd
        return out

    if strategy == "subject_pct":
        out = np.full(len(x), np.nan)
        for s, idx in df.groupby("subject_id").indices.items():
            idx = np.asarray(idx)
            ref = x[idx[ref_mask[idx]]]
            if len(ref) < 3:
                ref = x[idx]
            ref = ref[np.isfinite(ref)]
            if len(ref) == 0:
                out[idx] = np.nan
                continue
            # baseline 대비 백분위(0-1) -> 대략적인 z 스케일
            pct = np.searchsorted(np.sort(ref), x[idx]) / len(ref)
            out[idx] = (pct - 0.5) * 4.0
        return out

    raise ValueError("알 수 없는 threshold 전략: {}".format(strategy))


def build_facts(df, strategy="subject_z", z_high=0.5, z_low=-0.5,
                train_mask=None, baseline="low_activity", abs_overrides=None):
    """features DataFrame -> facts DataFrame.

    z_high / z_low / baseline / abs_overrides 는 모두 sensitivity analysis
    대상이다 (Day 10). baseline 의 의미는 baseline_mask() 설명을 볼 것.
    abs_overrides 예: {"ACTIVITY_HIGH": 0.08, "ACTIVITY_HIGH_LOW": 0.03}
    """
    scores = compute_scores(df, strategy, baseline, train_mask)
    cuts = {}
    for fact, (_, _, override) in FACT_DEFS.items():
        if isinstance(override, dict) and override.get("strategy") == "absolute":
            cuts[fact] = ((abs_overrides or {}).get(fact, override["high"]),
                          (abs_overrides or {}).get(fact + "_LOW", override["low"]))
        else:
            cuts[fact] = (z_high, z_low)
    return apply_thresholds(df, scores, cuts)


# --- 점수 / 임계 분리 -------------------------------------------------------
# 누수를 막으려면 "점수 계산"과 "임계 결정"을 갈라야 한다.
#   점수  : 라벨을 쓰지 않는다. 전체 데이터로 계산해도 무방하다.
#           (subject_z 는 테스트 피험자 자신의 윈도 분포를 쓰지만 라벨은
#            보지 않는다 = 개인화이지 누수가 아니다. 논문에 명시할 것.)
#   임계  : 라벨을 쓴다. 반드시 train fold 에서만 정해야 한다.

def is_absolute(fact):
    override = FACT_DEFS[fact][2]
    return isinstance(override, dict) and override.get("strategy") == "absolute"


def compute_scores(df, strategy="subject_z", baseline="low_activity",
                   train_mask=None):
    """fact 별 점수 (라벨 미사용). 절대 임계 fact 는 원값을 그대로 쓴다."""
    ref = baseline_mask(df, baseline)
    out = pd.DataFrame(index=range(len(df)))
    for fact, (feature, direction, override) in FACT_DEFS.items():
        if feature not in df.columns:
            out[fact] = np.nan
            continue
        if is_absolute(fact):
            out[fact] = df[feature].to_numpy(dtype=float) * direction
            continue
        strat = override if isinstance(override, str) else (override or strategy)
        out[fact] = _scores(df, feature, strat, train_mask, ref) * direction
    return out


# fact 가 물리적으로 겨냥하는 상태. 임계 적합의 기준이며 규칙 구조와는 무관하다.
FACT_TARGET = {
    "HR_HIGH":            lambda y: y != "REST",   # 각성 (스트레스든 운동이든)
    "HRV_LOW":            lambda y: y == "STRESS",
    "EDA_HIGH":           lambda y: y != "REST",
    "SCR_HIGH":           lambda y: y != "REST",
    "ACTIVITY_HIGH":      lambda y: y == "EXERCISE",
    "ACTIVITY_VERY_HIGH": lambda y: y == "EXERCISE",
}

# 임계 선택 기준.
#   youden    : TPR - FPR 최대. 균형 잡힌 경계용.
#   precision : train 정밀도가 min_precision 이상인 것 중 가장 낮은 임계.
#               ACTIVITY_VERY_HIGH 처럼 "이 정도 움직이면 운동이 확실하다"는
#               고정밀 fact 에 쓴다. ACTIVITY_HIGH 와 같은 목표를 두고 Youden 을
#               쓰면 둘이 같은 값으로 붕괴하므로 기준을 달리해야 한다.
FACT_CRITERION = {"ACTIVITY_VERY_HIGH": ("precision", 0.85)}

# fact 별 절대 임계 후보. 없으면 ACTIVITY_ABS_SWEEP 를 쓴다.
FACT_ABS_GRID = {"ACTIVITY_VERY_HIGH": ACTIVITY_VH_SWEEP}

Z_GRID = tuple(np.round(np.arange(0.0, 2.01, 0.25), 2))


def fit_thresholds(scores, labels, train_mask=None, z_grid=Z_GRID,
                   abs_grid=None):
    """**train 구간에서만** fact 별 cut point 를 고른다.

    기준은 Youden J = TPR - FPR. fact 가 겨냥하는 상태(FACT_TARGET)를 양성으로
    두고 J 가 최대인 임계를 고른다. 조정하는 것은 스칼라 절단점 하나뿐이며
    규칙 구조나 fact 정의는 건드리지 않는다 (= 보정이지 학습이 아니다).

    돌려주는 값: {fact: (hi, lo)}. z 기반 fact 는 lo = -hi 로 대칭이고,
    절대 임계 fact 는 hi = lo (움직인다/안 움직인다의 단일 경계).
    """
    y = np.asarray(labels, dtype=object)
    m = np.ones(len(y), dtype=bool) if train_mask is None else np.asarray(train_mask, dtype=bool)

    cuts = {}
    for fact in FACT_DEFS:
        s = scores[fact].to_numpy(dtype=float)
        target = FACT_TARGET[fact](y)
        if is_absolute(fact):
            grid = FACT_ABS_GRID.get(fact, abs_grid or ACTIVITY_ABS_SWEEP)
        else:
            grid = z_grid
        criterion, arg = FACT_CRITERION.get(fact, ("youden", None))

        ok = m & np.isfinite(s)
        if ok.sum() < 10 or target[ok].sum() == 0 or (~target[ok]).sum() == 0:
            # train 에 한쪽 클래스가 없으면 기본값을 쓴다.
            d = FACT_DEFS[fact][2]
            cuts[fact] = ((d["high"], d["low"]) if is_absolute(fact) else (0.5, -0.5))
            continue

        if criterion == "precision":
            # 정밀도 조건을 만족하는 가장 낮은(=재현율이 가장 큰) 임계
            best = None
            for t in sorted(grid):
                pred = s[ok] > t
                if pred.sum() >= 5 and target[ok][pred].mean() >= arg:
                    best = t
                    break
            if best is None:
                best = max(grid)
        else:
            best, best_j = grid[0], -np.inf
            for t in grid:
                pred = s[ok] > t
                j = pred[target[ok]].mean() - pred[~target[ok]].mean()
                if j > best_j:
                    best, best_j = t, j
        cuts[fact] = (float(best), float(best) if is_absolute(fact) else -float(best))
    return cuts


def apply_thresholds(df, scores, cuts):
    """점수 + cut point -> facts DataFrame."""
    out = pd.DataFrame({
        "sample_id": df["sample_id"].to_numpy(),
        "subject_id": df["subject_id"].to_numpy(),
    })
    out["true_label"] = (df["label"].to_numpy() if "label" in df.columns
                         else np.nan)
    for fact in FACT_DEFS:
        s = scores[fact].to_numpy(dtype=float)
        hi, lo = cuts[fact]
        out["z_" + fact] = s
        out[fact] = s > hi
        out[fact + "_LOW"] = s < lo
    out["ACTIVITY_LOW"] = out["ACTIVITY_HIGH_LOW"]
    return out


def build_facts_cv(df, folds, strategy="subject_z", baseline="low_activity"):
    """fold 별로 train 에서 임계를 적합해 test 에 적용한다 (누수 없음).

    folds : df 각 행의 fold 라벨. 테스트 fold 가 곧 평가 대상이다.
    반환  : (facts, cuts_table)
            cuts_table 은 fold 별로 고른 임계값. 폴드 간 변동이 크면 그
            임계는 불안정하다는 뜻이므로 반드시 함께 보고할 것.
    """
    folds = np.asarray(folds, dtype=object)
    scores = compute_scores(df, strategy, baseline)   # 라벨 미사용
    labels = df["label"].to_numpy()

    facts = None
    rows = []
    for f in pd.unique(folds):
        te = folds == f
        tr = ~te
        cuts = fit_thresholds(scores, labels, train_mask=tr)
        part = apply_thresholds(df, scores, cuts)
        facts = part if facts is None else facts
        # 테스트 fold 행만 이번 cut 으로 덮어쓴다
        for col in part.columns:
            if col.startswith("z_") or col in ("sample_id", "subject_id",
                                               "true_label"):
                continue
            facts.loc[te, col] = part.loc[te, col]
        rows.append({"fold": f, **{k: v[0] for k, v in cuts.items()}})
    return facts, pd.DataFrame(rows)


def fact_distribution(facts, by="true_label"):
    """상태별 fact 발생률. Day 3 의 '규칙이 데이터와 맞는가' 점검용.

    예: STRESS 에서 EDA_HIGH 비율이 EXERCISE 보다 높지 않으면 R2 는 못 쓴다.
    """
    cols = [c for c in facts.columns
            if c in FACT_NAMES or c.endswith("_LOW")
            or c in ("STRESS_EVIDENCE", "EXERCISE_EVIDENCE")]
    g = facts.groupby(by)[cols].mean()
    g["n"] = facts.groupby(by).size()
    return g


def threshold_sweep(df, strategies=("subject_z", "subject_pct", "fixed"),
                    baselines=("low_activity", "all", "labeled_rest"),
                    zs=(0.25, 0.5, 0.75, 1.0, 1.5)):
    """(전략 x baseline x 임계) 별 fact 발생률. Day 10 sensitivity analysis.

    STRESS 행의 HR_HIGH / EDA_HIGH 가 0 에 가까우면 그 조합에서는 stress
    규칙이 발화할 수 없다. 규칙을 고치기 전에 이 표를 먼저 볼 것.
    """
    if isinstance(strategies, str):
        strategies = (strategies,)
    rows = []
    for strategy in strategies:
        for base in baselines:
            for z in zs:
                for a in ACTIVITY_ABS_SWEEP:
                    f = build_facts(df, strategy=strategy, z_high=z, z_low=-z,
                                    baseline=base,
                                    abs_overrides={"ACTIVITY_HIGH": a,
                                                   "ACTIVITY_HIGH_LOW": a * 0.4})
                    for lab, sub in f.groupby("true_label"):
                        row = {"strategy": strategy, "baseline": base, "z": z,
                               "acc_thresh_g": a, "label": lab, "n": len(sub)}
                        for name in FACT_NAMES:
                            row[name] = float(sub[name].mean())
                        rows.append(row)
    return pd.DataFrame(rows)
