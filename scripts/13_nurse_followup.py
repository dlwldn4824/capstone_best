"""Nurse 이식 실패에 대한 후속 확인 5가지.

    python scripts/13_nurse_followup.py

NURSE_TRANSFER.md 7절의 항목들. 이식 실패가 '방법의 문제'인지 '라벨의 문제'인지
가르는 것이 목적임.

  1. 활동량 임계를 Nurse 분포에서 재적합
  2. 대조군을 REPORTED_CALM 대신 같은 세션의 다른 구간으로 교체
  3. 사건 시각 오차(중앙값 16분)를 감안해 사건 단위로 집계
  4. 사건 원인 범주별 분리
  5. 주간/야간 교대 구분

담당: 역할 C
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import roc_auc_score
from _bootstrap import banner, setup

from nesy import deviation as DV, nurse, report

ROOT = Path(__file__).resolve().parents[1]
FEATS = ["hr_mean", "rmssd", "mean_tonic_eda", "peaks_density", "acc_dyn_mean"]


def paired(df, col, a="STRESS_EVENT", b="CONTROL", group="subject_id"):
    """피험자별 중앙값 짝지은 비교."""
    piv = df.pivot_table(index=group, columns="grp", values=col, aggfunc="median")
    if not {a, b} <= set(piv.columns):
        return None
    piv = piv.dropna(subset=[a, b])
    if len(piv) < 3:
        return None
    d = piv[a] - piv[b]
    try:
        _, p = stats.wilcoxon(piv[a], piv[b])
    except ValueError:
        p = np.nan
    return {"feature": col, "n": len(d), "control": round(float(piv[b].median()), 3),
            "stress": round(float(piv[a].median()), 3),
            "diff": round(float(d.median()), 3), "n_up": int((d > 0).sum()),
            "p": round(float(p), 4)}


def auc_of(df, score_col, group="subject_id"):
    """STRESS_EVENT vs CONTROL 판별 AUC (통합 / 피험자평균)."""
    m = df["grp"].isin(["STRESS_EVENT", "CONTROL"]) & np.isfinite(df[score_col])
    d = df[m]
    if d["grp"].nunique() < 2:
        return np.nan, np.nan, 0
    y = (d["grp"] == "STRESS_EVENT").astype(int)
    pooled = roc_auc_score(y, d[score_col])
    per = []
    for _, g in d.groupby(group):
        yy = (g["grp"] == "STRESS_EVENT").astype(int)
        if yy.nunique() > 1 and len(g) >= 20:
            per.append(roc_auc_score(yy, g[score_col]))
    return pooled, (np.mean(per) if per else np.nan), len(per)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gap-min", type=float, default=30.0,
                    help="대조군은 어떤 사건에서도 이만큼 떨어진 윈도")
    args = ap.parse_args()

    cfg, _ = setup()
    out = Path(cfg["paths"]["outputs"])
    banner("NURSE 후속 확인 5가지")

    df = pd.read_csv(out / "nurse_features.csv")
    ev = nurse.load_events(ROOT / "data/raw/nurse_stress/SurveyResults.xlsx")
    print("윈도 {:,} / 사건 {}".format(len(df), len(ev)))

    # 사건까지의 거리 (분) — 대조군 정의에 쓴다
    dist = np.full(len(df), np.inf)
    for subj, g in df.groupby("subject_id"):
        e = ev[ev["subject_id"] == subj]
        if e.empty:
            continue
        t = g["t_start"].to_numpy()
        d = np.full(len(t), np.inf)
        for _, r in e.iterrows():
            d = np.minimum(d, np.maximum(0, np.maximum(r["start"] - t,
                                                       t - r["end"])) / 60.0)
        dist[g.index.to_numpy()] = d
    df["min_to_event"] = dist

    # --- 1. 활동량 임계 재적합 -------------------------------------------
    banner("1. 활동량 임계 재적합")
    print("Hongn 임계 0.020 g -> Nurse 윈도의 {:.1%} 가 초과".format(
        (df["acc_dyn_mean"] > 0.020).mean()))
    print("\n임계별 초과 비율")
    rows = []
    for t in (0.020, 0.040, 0.060, 0.081, 0.100, 0.132, 0.200):
        s = df[df.label == "STRESS_EVENT"]["acc_dyn_mean"] > t
        c = df[df.label == "REPORTED_CALM"]["acc_dyn_mean"] > t
        a = df["acc_dyn_mean"] > t
        rows.append({"thresh_g": t, "전체": round(a.mean(), 3),
                     "스트레스": round(s.mean(), 3), "평온": round(c.mean(), 3)})
        print("  {:.3f} g : 전체 {:.1%} | 스트레스 {:.1%} | 평온 {:.1%}".format(
            t, a.mean(), s.mean(), c.mean()))
    pd.DataFrame(rows).to_csv(out / "tables" / "nurse_activity_thresh.csv", index=False)
    print("\n  -> 어떤 임계에서도 스트레스와 평온이 갈리지 않으면 활동량은")
    print("     실환경에서 스트레스의 맥락 설명 변수로 쓸 수 없다는 뜻이다.")

    # --- 2. 대조군 교체 ---------------------------------------------------
    banner("2. 대조군 교체")
    variants = {}
    base = df[df.label == "STRESS_EVENT"].copy(); base["grp"] = "STRESS_EVENT"

    c1 = df[df.label == "REPORTED_CALM"].copy(); c1["grp"] = "CONTROL"
    variants["A. REPORTED_CALM (기존)"] = pd.concat([base, c1])

    c2 = df[(df.label.isna()) & (df.min_to_event >= args.gap_min)].copy()
    c2["grp"] = "CONTROL"
    variants["B. 사건에서 {:.0f}분 이상 떨어진 무라벨".format(args.gap_min)] = \
        pd.concat([base, c2])

    # 같은 세션 안의 저활동 구간
    c3_idx = []
    for _, g in df[df.label.isna()].groupby("session_id"):
        if len(g) < 10:
            continue
        thr = g["acc_dyn_mean"].quantile(0.25)
        c3_idx += g.index[g["acc_dyn_mean"] <= thr].tolist()
    c3 = df.loc[c3_idx].copy(); c3["grp"] = "CONTROL"
    variants["C. 같은 세션 저활동 하위25%"] = pd.concat([base, c3])

    summary = []
    for name, v in variants.items():
        print("\n--- {} (대조 {:,} / 스트레스 {:,}) ---".format(
            name, (v.grp == "CONTROL").sum(), (v.grp == "STRESS_EVENT").sum()))
        res = [paired(v, c) for c in FEATS]
        res = pd.DataFrame([r for r in res if r])
        if len(res):
            print(res.to_string(index=False))
            sig = res[res.p < 0.05]
            print("  유의(p<0.05): {}/{}".format(len(sig), len(res)))
            summary.append({"control": name, "n_sig": len(sig), "n_feat": len(res)})
    pd.DataFrame(summary).to_csv(out / "tables" / "nurse_control_variants.csv",
                                 index=False)

    # --- 3. 사건 단위 집계 -------------------------------------------------
    banner("3. 사건 단위 집계 (시각 오차 완화)")
    rows = []
    for _, e in ev.iterrows():
        if not np.isfinite(e["start"]):
            continue
        g = df[(df.subject_id == e["subject_id"]) &
               (df.t_start >= e["start"] - 300) & (df.t_end <= e["end"] + 300)]
        if len(g) < 3:
            continue
        rows.append({"subject_id": e["subject_id"], "level": e["level"],
                     "causes": e["causes"], "n_win": len(g),
                     **{c: g[c].median() for c in FEATS}})
    evf = pd.DataFrame(rows)
    print("집계된 사건 {}건 (윈도 3개 이상)".format(len(evf)))
    if len(evf):
        evf["grp"] = np.where(evf["level"] >= 1, "STRESS_EVENT",
                              np.where(evf["level"] == 0, "CONTROL", None))
        sub = evf[evf.grp.notna()]
        res = pd.DataFrame([r for r in (paired(sub, c) for c in FEATS) if r])
        if len(res):
            print(res.to_string(index=False))
            print("  유의(p<0.05): {}/{}".format((res.p < 0.05).sum(), len(res)))
        evf.to_csv(out / "tables" / "nurse_event_level.csv", index=False)

    # --- 4. 원인 범주별 ---------------------------------------------------
    banner("4. 사건 원인 범주별")
    if len(evf):
        s = evf[evf.level >= 1].copy()
        cats = {}
        for _, r in s.iterrows():
            for c in str(r["causes"]).split("|"):
                c = c.strip()
                if c:
                    cats.setdefault(c, []).append(r)
        rows = []
        for c, items in sorted(cats.items(), key=lambda kv: -len(kv[1])):
            if len(items) < 5:
                continue
            t = pd.DataFrame(items)
            rows.append({"원인": c[:34], "n": len(t),
                         **{f: round(float(t[f].median()), 3) for f in FEATS}})
        cat = pd.DataFrame(rows)
        if len(cat):
            print(cat.to_string(index=False))
            cat.to_csv(out / "tables" / "nurse_causes.csv", index=False)
            print("\n  원인에 따라 생리 반응이 다르면 하나의 STRESS 라벨로 묶는 것 자체가")
            print("  문제라는 뜻이다.")

    # --- 5. 주간/야간 -----------------------------------------------------
    banner("5. 주간 / 야간 교대")
    local = pd.to_datetime(df["t_start"], unit="s", utc=True).dt.tz_convert(
        nurse.LOCAL_TZ)
    df["hour"] = local.dt.hour
    df["shift"] = np.where((df.hour >= 7) & (df.hour < 19), "주간", "야간")
    print(df.groupby("shift")[FEATS].median().round(3).to_string())
    print("\n윈도 수:", df["shift"].value_counts().to_dict())
    lab = df[df.label.notna()]
    if len(lab):
        print("\n라벨된 윈도의 교대 분포:")
        print(pd.crosstab(lab["shift"], lab["label"]).to_string())
    # 교대별 이탈 AUC
    if "dev_low_activity" not in df.columns:
        df["dev_low_activity"] = DV.score(df, mode="low_activity",
                                          scope="subject_session")["deviation"].to_numpy()
    for sh in ("주간", "야간"):
        v = df[(df["shift"] == sh) & df["label"].notna()].copy()
        v["grp"] = np.where(v.label == "STRESS_EVENT", "STRESS_EVENT", "CONTROL")
        a, b, n = auc_of(v, "dev_low_activity")
        print("  {} 이탈 AUC 통합 {:.3f} | 피험자평균 {:.3f} (n={})".format(sh, a, b, n))

    print("\n-> outputs/tables/nurse_*.csv")


if __name__ == "__main__":
    main()
