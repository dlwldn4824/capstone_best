"""Day 6 — Random split vs Subject-independent split, + 피험자별 오류 분석.

이 스크립트가 만드는 표는 논문에서 방법론적 기여로 쓸 수 있다.
"원 논문 수치는 피험자 누수를 포함한다"는 주장을 정량화한다.

담당: 역할 B (실행) / 역할 A(품질) / 역할 C(피험자별 해석)
"""
import argparse
from pathlib import Path

import pandas as pd
from _bootstrap import banner, setup

from nesy import (baseline_ml, evaluate, feature_extraction, report,
                  subject_split)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="xgboost")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    cfg, _ = setup()
    banner("SUBJECT-INDEPENDENT EVALUATION")

    df = feature_extraction.load_features(cfg).reset_index(drop=True)
    features = [c for c in feature_extraction.ALL_FEATURES if c in df.columns]
    out = Path(cfg["paths"]["outputs"])
    writer = evaluate.ResultsWriter(out / "results.csv")

    # 분할 자체가 정상인지 먼저 확인 (테스트 폴드에 클래스가 다 있는가)
    print("\n[분할 점검]")
    for scheme in ("random", "group_kfold", "loso"):
        s = pd.DataFrame(subject_split.split_summary(df, scheme,
                                                     cfg["eval"]["n_splits"]))
        print("  {:12s} folds={:2d}  leak={}  min_test_classes={}".format(
            scheme, len(s), s["leak"].any(), s["test_classes"].min()))

    rows, preds = [], {}
    for scheme in ("random", "group_kfold", "loso"):
        met, pred, per_fold = baseline_ml.run_cv(
            df, features, args.model, scheme=scheme, n_splits=cfg["eval"]["n_splits"],
            seed=args.seed, experiment="subject_independent", feature_set="ALL")
        writer.add("subject_independent", args.model, scheme, "ALL", met)
        rows.append({"split": scheme, **{k: met[k] for k in
                     ("accuracy", "macro_f1", "balanced_accuracy",
                      "stress_to_exercise", "exercise_to_stress")}})
        preds[scheme] = pred
        per_fold.to_csv(out / "tables" / "perfold_{}.csv".format(scheme),
                        index=False)
        print("\n  {:12s} acc={:.3f}  macroF1={:.3f}  S->E={:.3f}  E->S={:.3f}"
              .format(scheme, met["accuracy"], met["macro_f1"],
                      met["stress_to_exercise"], met["exercise_to_stress"]))

    writer.flush()
    summary = pd.DataFrame(rows)
    summary.to_csv(out / "tables" / "split_comparison.csv", index=False)

    gap = (summary.loc[summary["split"] == "random", "macro_f1"].iloc[0]
           - summary.loc[summary["split"] == "loso", "macro_f1"].iloc[0])
    print("\n누수로 인한 Macro F1 과대평가: {:+.3f} (random - loso)".format(gap))

    # 피험자별 성능 — 어떤 사람에서 규칙/모델이 깨지는가
    p = preds["loso"]
    per_subj = (p.assign(correct=p["true_label"] == p["pred_label"])
                  .groupby("subject_id")
                  .agg(n=("correct", "size"), acc=("correct", "mean"))
                  .reset_index().sort_values("acc"))
    per_subj.to_csv(out / "tables" / "per_subject_loso.csv", index=False)
    print("\n[LOSO 피험자별 정확도 하위 5명]")
    print(per_subj.head(5).to_string(index=False))

    err = p[p["true_label"] != p["pred_label"]]
    by_subj_dir = pd.crosstab([err["subject_id"], err["true_label"]],
                              err["pred_label"]) if len(err) else pd.DataFrame()
    if len(by_subj_dir):
        by_subj_dir.to_csv(out / "tables" / "per_subject_errors.csv")

    report.write_md(
        Path(__file__).resolve().parents[1] / "docs" / "SPLIT_RESULTS.md",
        [("# Subject-independent 평가", ""),
         ("## 분할 방식 비교", report.md_table(summary)),
         ("## 해석",
          "random split 은 60초 윈도를 30초 간격으로 겹쳐 뽑은 탓에 거의 동일한\n"
          "신호가 train/test 에 함께 들어간다. LOSO 와의 Macro F1 차이 "
          "**{:+.3f}** 가\n그 누수의 크기다. 우리가 보고하는 값은 LOSO / GroupKFold 다."
          .format(gap)),
         ("## 피험자별 정확도 (LOSO)", report.md_table(per_subj))])
    print("\n-> outputs/tables/split_comparison.csv, docs/SPLIT_RESULTS.md")


if __name__ == "__main__":
    main()
