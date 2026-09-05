"""개인 baseline 이탈 점수.

원래 연구 질문의 출발점이다.

    이 사람의 평소와 다른가?  ->  다르다면 무엇으로 설명되는가?

왜 필요한가 (본 데이터 실측 근거)
    휴식 시 HR 이 사람마다 53-101 bpm (SD 10.0).
    한 사람이 스트레스를 받으면 +7.7 bpm (34명 중 30명에서 상승).
    반응은 일관되게 존재하지만 개인차가 그보다 1.3배 크다.
    피부전도는 41배다. 즉 절대값만 보는 모델은 이 신호를 쓸 수 없다.
    "68 bpm 이 스트레스인가" 는 누구인지 모르면 답할 수 없는 질문이다.

설계 결정 — 이탈은 생리 신호로만 계산한다
    ACC(움직임)는 이탈 계산에 넣지 않는다. 움직임은 '이상'이 아니라 그 이상을
    '설명하는' 맥락이기 때문이다. 움직임을 이탈에 넣으면 운동이 곧 이상이
    되어버려 연구 질문이 무너진다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# 이탈을 계산할 생리 채널. 활동량(acc_*)은 의도적으로 뺀다.
DEVIATION_FEATURES = ["hr_mean", "rmssd", "mean_tonic_eda", "peaks_density"]

MAD_SCALE = 1.4826   # 정규분포에서 MAD -> 표준편차


# 개인 기준을 어느 단위로 잡을 것인가.
#
# !! 이 데이터에서 가장 중요한 제약 !!
#   세 세션(STRESS/AEROBIC/ANAEROBIC)은 서로 다른 날 녹화됐다. 34명 중 27명이
#   2-3개의 다른 날짜이고 간격은 중앙값 4일, 최대 32일이다. 밴드를 다시
#   착용했으므로 전극 접촉·피부 상태·실온이 달라진다. 실측한 세션 간
#   '조용한 상태' 값의 차이는
#       HR    19.4 bpm  (스트레스 반응 7.7 의 2.5배)
#       EDA    2.01 uS  (스트레스 반응 0.14 의 14배)
#   즉 세션을 합쳐 개인 기준을 만들면 그 기준은 생리가 아니라 "어느 날
#   녹화분인가" 를 재게 된다. 이탈 점수가 상태가 아니라 세션을 맞히게 된다.
#
#   scope="subject_session" 이 기본값인 이유다. 같은 착용 구간 안에서만
#   비교한다. 대신 "며칠 전 대비" 는 이 데이터로 볼 수 없다.
SCOPE_KEYS = {
    "subject_session": ["subject_id", "session_id"],   # 기본. 같은 착용 구간
    "subject": ["subject_id"],                         # 세션 혼합. 비교용
}


def baseline_windows(df, mode="low_activity", pct=0.4, min_n=5,
                     activity_col="acc_dyn_mean", scope="subject_session"):
    """개인 baseline 을 만들 참조 윈도 선택.

    mode
      labeled_rest  라벨이 REST 인 윈도. 라벨을 쓰므로 **oracle** 이며 상한
                    확인용으로만 쓴다.
      low_activity  피험자 내 활동량 하위 pct. 라벨을 쓰지 않는다. **기본값**
      temporal      피험자의 시간상 가장 이른 윈도 pct. 실제 운용에 가장 가깝다
                    (착용 직후 일정 시간을 기준으로 삼는 상황).
    """
    n = len(df)
    m = np.zeros(n, dtype=bool)
    keys = SCOPE_KEYS[scope]

    for _, idx in df.groupby(keys).indices.items():
        idx = np.asarray(idx)
        if mode == "labeled_rest":
            sel = (df["label"].to_numpy()[idx] == "REST")
        elif mode == "temporal":
            t = df["t_start"].to_numpy()[idx]
            k = max(min_n, int(len(idx) * pct))
            sel = np.zeros(len(idx), dtype=bool)
            sel[np.argsort(t)[:k]] = True
        elif mode == "low_activity":
            a = df[activity_col].to_numpy(dtype=float)[idx]
            sel = a <= np.nanpercentile(a, pct * 100)
        else:
            raise ValueError("알 수 없는 baseline mode: {}".format(mode))

        if sel.sum() < min_n:                  # 참조가 너무 적으면 전체를 쓴다
            sel = np.ones(len(idx), dtype=bool)
        m[idx[sel]] = True
    return m


def robust_z(df, features=None, ref_mask=None, mode="low_activity",
             scope="subject_session"):
    """(피험자, 세션)별 median/MAD 로 표준화한 robust z. (n, k) DataFrame."""
    features = [f for f in (features or DEVIATION_FEATURES) if f in df.columns]
    if ref_mask is None:
        ref_mask = baseline_windows(df, mode, scope=scope)

    out = pd.DataFrame(index=range(len(df)), columns=features, dtype=float)
    for _, idx in df.groupby(SCOPE_KEYS[scope]).indices.items():
        idx = np.asarray(idx)
        ref = idx[ref_mask[idx]]
        for f in features:
            x = df[f].to_numpy(dtype=float)
            r = x[ref]
            r = r[np.isfinite(r)]
            if len(r) < 3:
                out.loc[idx, f] = np.nan
                continue
            med = np.median(r)
            mad = np.median(np.abs(r - med)) * MAD_SCALE
            if not np.isfinite(mad) or mad <= 0:
                mad = np.nanstd(r) or 1.0
            out.loc[idx, f] = (x[idx] - med) / mad
    return out


def score(df, features=None, mode="low_activity", agg="mean",
          scope="subject_session", ref_mask=None):
    """개인 baseline 이탈 점수 (클수록 평소와 다름).

    agg
      mean  채널별 |z| 의 평균. 여러 채널이 함께 움직일 때 커진다. **기본값**
      max   가장 크게 벗어난 채널 하나. 단일 채널 이상에 민감하다.
    """
    z = robust_z(df, features, ref_mask=ref_mask, mode=mode, scope=scope)
    a = z.abs()
    s = a.mean(axis=1) if agg == "mean" else a.max(axis=1)
    return pd.DataFrame({
        "deviation": s.to_numpy(),
        **{"z_" + c: z[c].to_numpy() for c in z.columns},
    })


# --- 설명 판정 -------------------------------------------------------------
EXPLAINED_EXERCISE = "EXPLAINED_EXERCISE"
EXPLAINED_STRESS = "EXPLAINED_STRESS"
UNEXPLAINED = "UNEXPLAINED"
NOT_DEVIATING = "NOT_DEVIATING"


def explain(dev, evidence, dev_thresh, min_evidence=0.5, margin=0.15):
    """이탈 -> 설명 판정.

    dev       deviation 점수 배열
    evidence  rules.apply_rules() 출력 (EXERCISE_EVIDENCE / STRESS_EVIDENCE)
    dev_thresh 이탈로 볼 임계 (train 에서 정할 것)

    이탈하지 않았으면 NOT_DEVIATING.
    이탈했는데 어느 근거도 약하면 **UNEXPLAINED** — 이것이 최종 산출물이다.
    분류기는 반드시 셋 중 하나를 골라야 하지만 이 구조는 '모른다'고 답할 수 있다.
    """
    dev = np.asarray(dev, dtype=float)
    ex = evidence.get("EXERCISE_EVIDENCE", pd.Series(0.0, index=range(len(dev)))).to_numpy()
    st = evidence.get("STRESS_EVIDENCE", pd.Series(0.0, index=range(len(dev)))).to_numpy()

    out = np.full(len(dev), NOT_DEVIATING, dtype=object)
    dv = dev > dev_thresh

    best_ex = dv & (ex >= min_evidence) & (ex - st > margin)
    best_st = dv & (st >= min_evidence) & (st - ex > margin)
    out[dv] = UNEXPLAINED
    out[best_ex] = EXPLAINED_EXERCISE
    out[best_st] = EXPLAINED_STRESS
    return out


def fit_dev_threshold(dev, labels, train_mask=None, grid=None):
    """이탈 임계를 train 에서 정한다 (REST 를 음성, 나머지를 양성으로 Youden J)."""
    dev = np.asarray(dev, dtype=float)
    y = np.asarray(labels, dtype=object) != "REST"
    m = np.ones(len(dev), dtype=bool) if train_mask is None else np.asarray(train_mask, bool)
    ok = m & np.isfinite(dev)
    if ok.sum() < 10 or y[ok].sum() == 0 or (~y[ok]).sum() == 0:
        return float(np.nanmedian(dev))
    grid = grid if grid is not None else np.quantile(dev[ok], np.linspace(0.05, 0.95, 37))
    best, best_j = grid[0], -np.inf
    for t in grid:
        p = dev[ok] > t
        j = p[y[ok]].mean() - p[~y[ok]].mean()
        if j > best_j:
            best, best_j = t, j
    return float(best)


def detection_auc(dev, labels, by_subject=True, subjects=None):
    """이탈 점수가 REST 와 나머지를 가르는가. 피험자별 AUC 와 통합 AUC."""
    from sklearn.metrics import roc_auc_score

    dev = np.asarray(dev, dtype=float)
    y = (np.asarray(labels, dtype=object) != "REST").astype(int)
    ok = np.isfinite(dev)
    pooled = (roc_auc_score(y[ok], dev[ok])
              if len(np.unique(y[ok])) > 1 else np.nan)
    if not by_subject or subjects is None:
        return {"pooled_auc": pooled, "per_subject": None}

    rows = []
    s = np.asarray(subjects, dtype=object)
    for u in pd.unique(s):
        m = ok & (s == u)
        if m.sum() < 5 or len(np.unique(y[m])) < 2:
            continue
        rows.append({"subject_id": u, "n": int(m.sum()),
                     "auc": float(roc_auc_score(y[m], dev[m]))})
    per = pd.DataFrame(rows)
    return {"pooled_auc": pooled, "per_subject": per,
            "mean_subject_auc": float(per["auc"].mean()) if len(per) else np.nan}
