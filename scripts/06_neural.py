"""Day 8-9 — Neural baseline (feature MLP) -> predictions.csv

두 모델을 만든다.
    neural          HR + HRV + EDA        (활동 맥락 없음)
    neural_context  HR + HRV + EDA + ACC  (활동 맥락을 숫자로)

NeSy 는 `neural` 의 출력을 받아 활동 맥락을 규칙으로 넣는다. 두 경로를 갈라
놓아야 "NeSy 의 이득이 단순히 ACC 정보 추가 때문인가"를 답할 수 있다.

담당: 역할 B
"""
import argparse
from pathlib import Path

import pandas as pd
from _bootstrap import banner, setup

from nesy import evaluate, feature_extraction, neural_model, report

VARIANTS = {
    "neural": ["HR", "HRV", "EDA"],
    "neural_context": ["HR", "HRV", "EDA", "ACC"],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="group_kfold")
    ap.add_argument("--epochs", type=int, default=120)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    cfg, _ = setup()
    banner("NEURAL BASELINE (MLP, split={})".format(args.split))

    df = feature_extraction.load_features(cfg).reset_index(drop=True)
    out = Path(cfg["paths"]["outputs"])
    writer = evaluate.ResultsWriter(out / "results.csv")

    rows = []
    for name, groups in VARIANTS.items():
        cols = [c for g in groups
                for c in feature_extraction.FEATURE_GROUPS[g] if c in df.columns]
        met, pred, per_fold = neural_model.run_cv(
            df, cols, scheme=args.split, n_splits=cfg["eval"]["n_splits"],
            seed=args.seed, epochs=args.epochs, experiment="neural",
            feature_set="+".join(groups), model_name=name)
        writer.add("neural", name, args.split, "+".join(groups), met)
        rows.append({"model": name, "n_features": len(cols),
                     **{k: met[k] for k in
                        ("accuracy", "macro_f1", "balanced_accuracy",
                         "stress_to_exercise", "exercise_to_stress")}})
        print("  {:15s} ({:2d} feat)  acc={:.3f} macroF1={:.3f} "
              "S->E={:.3f} E->S={:.3f}".format(
                  name, len(cols), met["accuracy"], met["macro_f1"],
                  met["stress_to_exercise"], met["exercise_to_stress"]))

        # predictions.csv 인터페이스 (+ p_* 확률은 역할 C 가 쓴다)
        pred_path = out / "predictions_{}.csv".format(name)
        pred.to_csv(pred_path, index=False)
        per_fold.to_csv(out / "tables" / "perfold_{}.csv".format(name), index=False)

    writer.flush()
    summary = pd.DataFrame(rows)
    summary.to_csv(out / "tables" / "neural_summary.csv", index=False)

    report.write_md(
        Path(__file__).resolve().parents[1] / "docs" / "NEURAL_RESULTS.md",
        [("# Neural baseline", ""),
         ("## 결과", report.md_table(summary)),
         ("## 설계 메모",
          "`neural` 은 ACC 를 전혀 보지 않는다. 이 모델이 STRESS 와 EXERCISE 를\n"
          "얼마나 혼동하는지가 NeSy 가 개선할 수 있는 상한이다.\n"
          "`neural_context` 는 같은 정보를 숫자로 받은 모델이므로, NeSy 는 이\n"
          "모델을 넘어서야 '규칙으로 넣는 것이 낫다'고 말할 수 있다.")])
    print("\n-> outputs/predictions_neural.csv, docs/NEURAL_RESULTS.md")


if __name__ == "__main__":
    main()
