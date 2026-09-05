"""이탈 점수 재설계 — 채널 묶음과 집계 방식을 훑는다.

    python scripts/14_deviation_redesign.py

문제: 실환경(Nurse)에서 EDA·SCR 은 유의하게 반응하는데(p=0.001, 0.007)
이탈 탐지 AUC 는 0.475 에 그쳤다. |z| 평균이 무반응 채널(HRV, HR)로 반응
채널을 희석하기 때문으로 보인다.

두 데이터에서 같은 변형을 평가한다. 실환경에서만 좋고 실험실에서 무너지면
과적합이므로 둘 다 봐야 한다.

  Nurse  STRESS_EVENT vs 대조군 B (사건에서 30분 이상 떨어진 무라벨)
         대조군 B 를 쓰는 이유는 NURSE_TRANSFER.md 8.1 참조 (순환논리 없음)
  Hongn  STRESS vs REST, 스트레스 세션 안에서만

담당: 역할 C
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from _bootstrap import banner, setup

from nesy import deviation as DV, feature_extraction as FE, nurse, report

ROOT = Path(__file__).resolve().parents[1]

VARIANTS = [
    ("all4",     "mean",   None),
    ("all4",     "signed", None),
    ("all4",     "max",    None),
    ("eda",      "mean",   None),
    ("eda",      "signed", None),
    ("eda_only", "signed", None),
    ("scr_only", "signed", None),
    ("cardiac",  "signed", None),
    ("eda_hr",   "signed", None),
    ("all4",     "signed", {"mean_tonic_eda": 3, "peaks_density": 3,
                            "hr_mean": 1, "rmssd": 0.5}),
]


def evaluate(df, pos_mask, neg_mask, mode, scope, subj="subject_id"):
    """변형별 AUC (통합 / 피험자평균)."""
    rows = []
    for fs, agg, w in VARIANTS:
        s = DV.score(df, feature_set=fs, agg=agg, weights=w,
                     mode=mode, scope=scope)["deviation"].to_numpy()
        m = (pos_mask | neg_mask) & np.isfinite(s)
        y = pos_mask[m].astype(int)
        if len(np.unique(y)) < 2:
            continue
        pooled = roc_auc_score(y, s[m])
        per = []
        sub = df[subj].to_numpy()
        for u in pd.unique(sub[m]):
            k = m & (sub == u)
            yy = pos_mask[k].astype(int)
            if len(np.unique(yy)) > 1 and k.sum() >= 20:
                per.append(roc_auc_score(yy, s[k]))
        rows.append({"채널": fs, "집계": agg,
                     "가중": "O" if w else "",
                     "통합AUC": round(float(pooled), 3),
                     "피험자평균": round(float(np.mean(per)), 3) if per else np.nan,
                     "n_subj": len(per)})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gap-min", type=float, default=30.0)
    args = ap.parse_args()

    cfg, _ = setup()
    out = Path(cfg["paths"]["outputs"])

    # --- Nurse -------------------------------------------------------------
    banner("Nurse (실환경) — STRESS_EVENT vs 대조군 B")
    nf = pd.read_csv(out / "nurse_features.csv").reset_index(drop=True)
    ev = nurse.load_events(ROOT / "data/raw/nurse_stress/SurveyResults.xlsx")

    dist = np.full(len(nf), np.inf)
    for subj, g in nf.groupby("subject_id"):
        e = ev[ev["subject_id"] == subj]
        if e.empty:
            continue
        t = g["t_start"].to_numpy()
        d = np.full(len(t), np.inf)
        for _, r in e.iterrows():
            d = np.minimum(d, np.maximum(0, np.maximum(r["start"] - t,
                                                       t - r["end"])) / 60.0)
        dist[g.index.to_numpy()] = d
    nf["min_to_event"] = dist

    pos = (nf["label"] == "STRESS_EVENT").to_numpy()
    neg = (nf["label"].isna() & (nf["min_to_event"] >= args.gap_min)).to_numpy()
    print("양성 {:,} / 대조 {:,}".format(pos.sum(), neg.sum()))

    n_res = evaluate(nf, pos, neg, mode="low_activity", scope="subject_session")
    print()
    print(n_res.to_string(index=False))
    n_res.to_csv(out / "tables" / "deviation_variants_nurse.csv", index=False)

    # --- Hongn -------------------------------------------------------------
    banner("Hongn (실험실) — STRESS vs REST, 스트레스 세션 내")
    hf = FE.load_features(cfg)
    hf = hf[hf["session_type"] == "STRESS"].reset_index(drop=True)
    hpos = (hf["label"] == "STRESS").to_numpy()
    hneg = (hf["label"] == "REST").to_numpy()
    print("양성 {:,} / 대조 {:,}".format(hpos.sum(), hneg.sum()))

    h_res = evaluate(hf, hpos, hneg, mode="low_activity", scope="subject_session")
    print()
    print(h_res.to_string(index=False))
    h_res.to_csv(out / "tables" / "deviation_variants_hongn.csv", index=False)

    # --- 종합 --------------------------------------------------------------
    banner("종합 — 두 환경에서 모두 좋은 변형")
    key = ["채널", "집계", "가중"]
    both = n_res.merge(h_res, on=key, suffixes=("_nurse", "_hongn"))
    both["최소"] = both[["통합AUC_nurse", "통합AUC_hongn"]].min(axis=1)
    both = both.sort_values("최소", ascending=False)
    print(both[key + ["통합AUC_nurse", "통합AUC_hongn", "최소"]].to_string(index=False))
    both.to_csv(out / "tables" / "deviation_variants.csv", index=False)

    best = both.iloc[0]
    print("\n[최선] 채널={} 집계={} 가중={}".format(
        best["채널"], best["집계"], best["가중"] or "없음"))
    print("  Nurse {:.3f} / Hongn {:.3f}".format(
        best["통합AUC_nurse"], best["통합AUC_hongn"]))
    print("\n  기존(all4/mean): Nurse {:.3f} / Hongn {:.3f}".format(
        float(n_res.query("채널=='all4' and 집계=='mean'")["통합AUC"].iloc[0]),
        float(h_res.query("채널=='all4' and 집계=='mean'")["통합AUC"].iloc[0])))

    report.write_md(ROOT / "docs" / "DEVIATION_REDESIGN.md", [
        ("# 이탈 점수 재설계", ""),
        ("## Nurse (실환경)", report.md_table(n_res)),
        ("## Hongn (실험실)", report.md_table(h_res)),
        ("## 두 환경 종합", report.md_table(
            both[key + ["통합AUC_nurse", "통합AUC_hongn", "최소"]])),
    ])
    print("\n-> docs/DEVIATION_REDESIGN.md")


if __name__ == "__main__":
    main()
