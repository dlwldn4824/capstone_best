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
    "ACTIVITY_HIGH": ("acc_dyn_mean", +1,
                      {"strategy": "absolute", "high": 0.05, "low": 0.02}),
}

# Day 10 민감도 분석에서 훑을 절대 임계 후보 (g)
ACTIVITY_ABS_SWEEP = (0.02, 0.035, 0.05, 0.08, 0.12)

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
    abs_overrides = abs_overrides or {}
    ref = baseline_mask(df, baseline)
    out = pd.DataFrame({
        "sample_id": df["sample_id"].to_numpy(),
        "subject_id": df["subject_id"].to_numpy(),
    })
    if "label" in df.columns:
        out["true_label"] = df["label"].to_numpy()
    else:
        out["true_label"] = np.nan

    for fact, (feature, direction, override) in FACT_DEFS.items():
        if feature not in df.columns:
            out[fact] = False
            out[fact + "_LOW"] = False
            out["z_" + fact] = np.nan
            continue

        if isinstance(override, dict) and override.get("strategy") == "absolute":
            # 절대 임계: 개인 분포와 무관하게 물리량으로 판정한다.
            hi = abs_overrides.get(fact, override["high"])
            lo = abs_overrides.get(fact + "_LOW", override["low"])
            x = df[feature].to_numpy(dtype=float)
            out["z_" + fact] = x
            out[fact] = (x > hi) if direction > 0 else (x < hi)
            out[fact + "_LOW"] = (x < lo) if direction > 0 else (x > lo)
            continue

        strat = override if isinstance(override, str) else (override or strategy)
        z = _scores(df, feature, strat, train_mask, ref) * direction
        out["z_" + fact] = z
        out[fact] = z > z_high
        out[fact + "_LOW"] = z < z_low

    # ACTIVITY_LOW 는 규칙에서 자주 쓰므로 별칭을 만든다.
    out["ACTIVITY_LOW"] = out["ACTIVITY_HIGH_LOW"]
    return out


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
