"""Nurse 실환경에서 개인 baseline 이탈 + 규칙 이식성 검증.

    python scripts/12_nurse_deviation.py

두 가지를 본다.
  1. 실험실에서 만든 규칙(HR↑ ∧ EDA↑ ∧ 활동↓ -> 스트레스)이 실환경에서도 성립하는가
  2. 개인 baseline 이탈이 보고된 스트레스 사건과 맞는가

**평가 주의.** 설문은 교대당 가장 길었던 사건 최대 6개만 표시하므로 92%의 윈도가
라벨 없음이다. 라벨 없음을 음성으로 세면 안 된다. 따라서
  - 이탈 탐지는 STRESS_EVENT vs REPORTED_CALM 만으로 평가한다 (둘 다 보고된 것)
  - 라벨 없는 윈도는 baseline 계산에만 쓴다

담당: 역할 C
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from _bootstrap import banner, setup

from nesy import deviation as DV, facts as F, report, rules as R

ROOT = Path(__file__).resolve().parents[1]


def within_subject(df, cols, group="subject_id"):
    """피험자별 중앙값 차이 (STRESS_EVENT - REPORTED_CALM) + Wilcoxon."""
    rows = []
    for c in cols:
        piv = df.pivot_table(index=group, columns="label", values=c,
                             aggfunc="median")
        if not {"STRESS_EVENT", "REPORTED_CALM"} <= set(piv.columns):
            continue
        piv = piv.dropna(subset=["STRESS_EVENT", "REPORTED_CALM"])
        d = piv["STRESS_EVENT"] - piv["REPORTED_CALM"]
        if len(d) < 3:
            continue
        try:
            _, p = stats.wilcoxon(piv["STRESS_EVENT"], piv["REPORTED_CALM"])
        except ValueError:
            p = np.nan
        rows.append({"feature": c, "n": len(d),
                     "calm": round(float(piv["REPORTED_CALM"].median()), 3),
                     "stress": round(float(piv["STRESS_EVENT"].median()), 3),
                     "diff": round(float(d.median()), 3),
                     "n_up": int((d > 0).sum()), "p": round(float(p), 4)})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", default=None)
    args = ap.parse_args()

    cfg, _ = setup()
    out = Path(cfg["paths"]["outputs"])
    path = Path(args.features) if args.features else out / "nurse_features.csv"
    banner("NURSE — 개인 baseline 이탈 및 규칙 이식성")

    df = pd.read_csv(path).reset_index(drop=True)
    print("윈도 {:,}개 / 피험자 {}명 / 세션 {}개".format(
        len(df), df["subject_id"].nunique(), df["session_id"].nunique()))
    lab = df[df["label"].notna()].copy()
    print("라벨된 윈도 {:,}개 (STRESS_EVENT {:,} / REPORTED_CALM {:,})".format(
        len(lab), (lab.label == "STRESS_EVENT").sum(),
        (lab.label == "REPORTED_CALM").sum()))

    # --- 1. 실험실 결론이 실환경에서도 성립하는가 -------------------------
    banner("1. 생리 반응 — 피험자 내 비교")
    cols = ["hr_mean", "rmssd", "sdnn", "mean_tonic_eda", "peaks_density",
            "std_phasic_eda", "acc_dyn_mean"]
    ws = within_subject(lab, cols)
    print(ws.to_string(index=False))
    print("\n  diff = 보고된 스트레스 - 보고된 평온 (피험자별 중앙값의 중앙값)")
    print("  n_up = 그 방향으로 움직인 피험자 수 / n")
    ws.to_csv(out / "tables" / "nurse_within_subject.csv", index=False)

    print("\n[실험실(Hongn) 결과와 대조]")
    print("  Hongn:  HR +7.7 bpm (34명 중 30명 상승), EDA +0.14 uS")
    hr = ws[ws.feature == "hr_mean"]
    if len(hr):
        r = hr.iloc[0]
        print("  Nurse:  HR {:+.1f} bpm ({}명 중 {}명 상승)".format(
            r["diff"], r["n"], r["n_up"]))

    # --- 2. 활동량 임계 이식성 -------------------------------------------
    banner("2. 활동량 임계 이식성")
    thr = 0.020        # Hongn 에서 fold 전부 동일하게 선택된 값
    print("  Hongn 에서 정한 임계 {:.3f} g".format(thr))
    print("  Nurse 전체 윈도 중 이 임계를 넘는 비율: {:.1%}".format(
        (df["acc_dyn_mean"] > thr).mean()))
    print("  -> 병동을 계속 걷는 간호사에게는 사실상 항상 참이다")
    print("\n  Nurse 분위수(g): " + ", ".join(
        "{}%={:.3f}".format(int(q * 100), df["acc_dyn_mean"].quantile(q))
        for q in (0.1, 0.25, 0.5, 0.75, 0.9)))

    # --- 3. 개인 baseline 이탈 -------------------------------------------
    banner("3. 개인 baseline 이탈 (세션 단위)")
    rows = []
    for mode in ("low_activity", "temporal"):
        sc = DV.score(df, mode=mode, scope="subject_session")["deviation"]
        df["dev_" + mode] = sc.to_numpy()
        m = df["label"].notna()
        y = (df.loc[m, "label"] == "STRESS_EVENT").astype(int)
        s = df.loc[m, "dev_" + mode]
        ok = np.isfinite(s)
        from sklearn.metrics import roc_auc_score
        auc = roc_auc_score(y[ok], s[ok]) if y[ok].nunique() > 1 else np.nan
        # 피험자별
        per = []
        for u, g in df[m].groupby("subject_id"):
            yy = (g["label"] == "STRESS_EVENT").astype(int)
            ss = g["dev_" + mode]
            k = np.isfinite(ss)
            if yy[k].nunique() > 1 and k.sum() >= 20:
                per.append(roc_auc_score(yy[k], ss[k]))
        rows.append({"baseline": mode, "pooled_auc": round(float(auc), 3),
                     "mean_subject_auc": round(float(np.mean(per)), 3) if per else np.nan,
                     "n_subj": len(per)})
        print("  {:14s} 통합 AUC {:.3f} | 피험자평균 {:.3f} (n={})".format(
            mode, auc, np.mean(per) if per else np.nan, len(per)))
    pd.DataFrame(rows).to_csv(out / "tables" / "nurse_deviation_auc.csv", index=False)
    print("\n  평가는 보고된 사건(STRESS_EVENT) vs 보고된 평온(REPORTED_CALM) 만으로 한다.")
    print("  라벨 없는 92% 는 baseline 계산에만 쓰고 음성으로 세지 않는다.")

    # --- 4. 규칙 발화 -----------------------------------------------------
    banner("4. 실험실 규칙의 실환경 발화")
    facts = F.build_facts(df, strategy="subject_z", baseline="low_activity")
    cov = R.coverage(facts[df["label"].notna()].reset_index(drop=True),
                     np.where(lab["label"].to_numpy() == "STRESS_EVENT",
                              "STRESS", "REST"))
    print(cov[["rule", "produces", "active", "fire_rate", "n_fired",
               "precision", "recall"]].round(3).to_string(index=False))
    cov.to_csv(out / "tables" / "nurse_rule_coverage.csv", index=False)

    df[["sample_id", "subject_id", "session_id", "label", "level",
        "dev_low_activity", "dev_temporal"]].to_csv(
        out / "nurse_deviation.csv", index=False)

    report.write_md(ROOT / "docs" / "NURSE_RESULTS.md", [
        ("# Nurse 실환경 검증 결과", ""),
        ("## 1. 피험자 내 생리 반응 (보고된 스트레스 - 보고된 평온)",
         report.md_table(ws)),
        ("## 2. 개인 baseline 이탈 탐지", report.md_table(pd.DataFrame(rows))),
        ("## 3. 실험실 규칙의 실환경 발화", report.md_table(
            cov[["rule", "produces", "active", "fire_rate", "precision", "recall"]])),
    ])
    print("\n-> outputs/nurse_deviation.csv, docs/NURSE_RESULTS.md")


if __name__ == "__main__":
    main()
