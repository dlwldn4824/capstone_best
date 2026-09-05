"""Day 5 — 핵심 실험: Stress vs Exercise + feature ablation.

연구 질문의 출발점.
    HR only            -> Stress 와 Exercise 가 얼마나 섞이는가?
    + HRV              -> 나아지는가?
    + EDA              -> Stress 근거가 생기는가?
    + ACC              -> Exercise 오분류가 줄어드는가?

담당: 역할 B (실행) / 역할 C (오류 해석)
"""
import argparse
from pathlib import Path

import pandas as pd
from _bootstrap import banner, setup

from nesy import baseline_ml, evaluate, feature_extraction, figures, report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="xgboost")
    ap.add_argument("--split", default="group_kfold")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    cfg, _ = setup()
    banner("STRESS vs EXERCISE  ·  feature ablation ({})".format(args.model))

    df = feature_extraction.load_features(cfg)
    out = Path(cfg["paths"]["outputs"])
    writer = evaluate.ResultsWriter(out / "results.csv")

    # (a) 2-class: STRESS vs EXERCISE — 혼동의 크기를 직접 본다
    se = df[df["label"].isin(["STRESS", "EXERCISE"])].reset_index(drop=True)
    # (b) 3-class: REST 포함 — 실제 운용 상황
    tc = df.reset_index(drop=True)

    rows, preds_store = [], {}
    for task_name, data in (("stress_vs_exercise", se), ("three_class", tc)):
        print("\n--- {} ({}행) ---".format(task_name, len(data)))
        for fs_name, fs_cols in feature_extraction.ABLATION_SETS.items():
            cols = [c for c in fs_cols if c in data.columns]
            met, pred, _ = baseline_ml.run_cv(
                data, cols, args.model, scheme=args.split, seed=args.seed,
                experiment=task_name, feature_set=fs_name)
            writer.add(task_name, args.model, args.split, fs_name, met,
                       task=task_name)
            rows.append({"task": task_name, "model": args.model,
                         "feature_set": fs_name, "n_features": len(cols),
                         **{k: met[k] for k in
                            ("accuracy", "macro_f1", "balanced_accuracy",
                             "stress_to_exercise", "exercise_to_stress")}})
            preds_store[(task_name, fs_name)] = pred
            print("  {:16s} ({:2d} feat)  macroF1={:.3f}  S->E={:.3f}  E->S={:.3f}"
                  .format(fs_name, len(cols), met["macro_f1"],
                          met["stress_to_exercise"], met["exercise_to_stress"]))

    writer.flush()
    summary = pd.DataFrame(rows)
    summary.to_csv(out / "tables" / "ablation.csv", index=False)

    # Fig 5: ablation 곡선 (3-class 기준)
    ab = summary[summary["task"] == "three_class"].copy()
    print("\n  fig -> {}".format(
        figures.fig5_ablation(ab, out / "figures")))

    # Fig 4: 최소 feature vs 전체 feature confusion matrix
    cms, titles = [], []
    for fs_name in ("HR", "HR+HRV+EDA", "HR+HRV+EDA+ACC"):
        p = preds_store.get(("three_class", fs_name))
        if p is not None:
            cms.append(evaluate.confusion(p["true_label"], p["pred_label"]))
            titles.append("{}\n{}".format(args.model, fs_name))
    if cms:
        print("  fig -> {}".format(figures.fig4_confusion(
            cms, titles, out / "figures", "fig4_confusion_ablation.png")))

    # 오분류 샘플 export — 역할 C 가 "규칙으로 잡히는가"를 본다
    full = preds_store[("three_class", "HR+HRV+EDA+ACC")]
    errors = full[full["true_label"] != full["pred_label"]]
    errors.to_csv(out / "tables" / "errors_baseline.csv", index=False)
    print("\n오분류 {}/{} ({:.1%})".format(len(errors), len(full),
                                          len(errors) / max(1, len(full))))
    if len(errors):
        print(pd.crosstab(errors["true_label"], errors["pred_label"]).to_string())

    report.write_md(
        Path(__file__).resolve().parents[1] / "docs" / "ABLATION_RESULTS.md",
        [("# Feature ablation: Stress vs Exercise", ""),
         ("## 결과", report.md_table(summary)),
         ("## 핵심으로 볼 것",
          "- `stress_to_exercise` = P(pred=EXERCISE | true=STRESS)\n"
          "- `exercise_to_stress` = P(pred=STRESS | true=EXERCISE)\n\n"
          "ACC 를 넣었을 때 이 두 값이 떨어지지 않으면, NeSy 의 activity rule 도\n"
          "같은 이유로 효과가 없을 가능성이 높다. 그 경우 Day 12 이후의 실패\n"
          "분석(결과 D)으로 바로 넘어간다.")])
    print("\n-> outputs/tables/ablation.csv, docs/ABLATION_RESULTS.md")


if __name__ == "__main__":
    main()
