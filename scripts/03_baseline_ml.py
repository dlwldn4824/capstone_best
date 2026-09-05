"""Day 4 — 논문 baseline 재현: Stress vs Rest (+ 4-class).

원 논문 결과 (Hongn 2025, XGBoost)
    Stress / Rest        Acc 93%  F1 92%
    Aerobic / Sprint     Acc 91%  F1 91%
    4-class              Acc 84%  F1 84%
단, 원 논문은 80/20 + 10-fold 로 피험자를 분리하지 않았다. 우리는 두 방식을
모두 돌려 그 차이 자체를 결과로 보고한다.

담당: 역할 B
"""
import argparse
from pathlib import Path

import pandas as pd
from _bootstrap import banner, setup

from nesy import baseline_ml, evaluate, feature_extraction, report

MODELS = ["logreg", "rf", "xgboost"]


def run_task(df, name, label_col, features, writer, splits, seed):
    print("\n--- {} ({}행, 클래스 {}) ---".format(
        name, len(df), sorted(df[label_col].unique())))
    rows = []
    for scheme in splits:
        for m in MODELS:
            met, preds, per_fold = baseline_ml.run_cv(
                df, features, m, scheme=scheme, label_col=label_col, seed=seed,
                experiment=name, feature_set="ALL")
            writer.add(name, m, scheme, "ALL", met, task=name)
            rows.append({"task": name, "model": m, "split": scheme,
                         "accuracy": met["accuracy"], "macro_f1": met["macro_f1"],
                         "balanced_accuracy": met["balanced_accuracy"]})
            print("  {:8s} {:14s} acc={:.3f}  macroF1={:.3f}".format(
                m, scheme, met["accuracy"], met["macro_f1"]))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    cfg, _ = setup()
    banner("BASELINE ML  (논문 재현 + subject-independent 재평가)")

    df = feature_extraction.load_features(cfg)
    features = [c for c in feature_extraction.ALL_FEATURES if c in df.columns]
    out = Path(cfg["paths"]["outputs"])
    writer = evaluate.ResultsWriter(out / "results.csv")
    splits = ["random", "group_kfold"]

    all_rows = []

    # 1) Stress vs Rest (원 논문 주 실험)
    sr = df[df["condition"].isin(["REST", "STRESS"])].reset_index(drop=True)
    sr = sr.assign(label=sr["condition"])
    all_rows.append(run_task(sr, "stress_vs_rest", "label", features, writer,
                             splits, args.seed))

    # 2) Aerobic vs Sprint
    ae = df[df["condition"].isin(["AEROBIC", "SPRINT"])].reset_index(drop=True)
    if ae["condition"].nunique() == 2:
        ae = ae.assign(label=ae["condition"])
        all_rows.append(run_task(ae, "aerobic_vs_sprint", "label", features,
                                 writer, splits, args.seed))

    # 3) 4-class
    fc = df.assign(label=df["condition"]).reset_index(drop=True)
    all_rows.append(run_task(fc, "four_class", "label", features, writer,
                             splits, args.seed))

    # 4) 3-class (우리 연구의 주 과제)
    all_rows.append(run_task(df.reset_index(drop=True), "three_class", "label",
                             features, writer, splits, args.seed))

    writer.flush()
    summary = pd.concat(all_rows, ignore_index=True)
    summary.to_csv(out / "tables" / "baseline_summary.csv", index=False)

    imp = baseline_ml.feature_importance(df, features, "xgboost", seed=args.seed)
    imp.to_csv(out / "tables" / "feature_importance.csv", index=False)
    print("\nXGBoost feature importance (3-class, 상위 10)")
    print(imp.head(10).to_string(index=False))

    report.write_md(
        Path(__file__).resolve().parents[1] / "docs" / "BASELINE_RESULTS.md",
        [("# Baseline ML 결과", ""),
         ("## 과제별 성능", report.md_table(summary)),
         ("## Feature importance (XGBoost, 3-class)", report.md_table(imp.head(20))),
         ("## 읽는 법",
          "`random` 은 같은 피험자의 겹치는 윈도가 train/test 에 함께 들어간다.\n"
          "`group_kfold` 와의 차이가 그 누수의 크기다. 논문 수치(93/91/84%)와\n"
          "직접 비교할 수 있는 것은 `random` 쪽이며, 우리가 보고할 값은\n"
          "`group_kfold` 다.")])
    print("\n-> outputs/results.csv, docs/BASELINE_RESULTS.md")


if __name__ == "__main__":
    main()
