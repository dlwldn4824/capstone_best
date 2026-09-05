"""Day 10-12 — Facts -> Rules -> Audit -> Correction -> 최종 비교표.

산출물
    outputs/facts.csv
    outputs/tables/rule_coverage.csv
    outputs/tables/fact_distribution.csv
    outputs/tables/threshold_sweep.csv
    outputs/tables/final_comparison.csv
    outputs/figures/fig4_confusion_nesy.png, fig6_case_study.png
    docs/RULES.md

담당: 역할 C
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from _bootstrap import banner, setup

from nesy import (evaluate, facts as facts_mod, feature_extraction, figures,
                  nesy_audit, nesy_correction, report, rules as rules_mod)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="subject_z",
                    choices=["fixed", "train_z", "subject_z", "subject_pct"])
    ap.add_argument("--z-high", type=float, default=0.5)
    ap.add_argument("--baseline", default="low_activity",
                    choices=["low_activity", "all", "labeled_rest"],
                    help="개인 baseline 참조 윈도 (facts.baseline_mask 참조)")
    ap.add_argument("--split", default="group_kfold")
    ap.add_argument("--fixed-thresholds", action="store_true",
                    help="fold 적합 대신 --z-high 고정값을 쓴다 (비교용, 누수 있음)")
    args = ap.parse_args()

    cfg, _ = setup()
    banner("NEURO-SYMBOLIC  (threshold={}, baseline={}, z_high={})".format(
        args.strategy, args.baseline, args.z_high))

    df = feature_extraction.load_features(cfg).reset_index(drop=True)
    out = Path(cfg["paths"]["outputs"])
    writer = evaluate.ResultsWriter(out / "results.csv")

    pred_path = out / "predictions_neural.csv"
    if not pred_path.exists():
        raise SystemExit("먼저 scripts/06_neural.py 를 실행하세요.")
    preds = pd.read_csv(pred_path)
    # features 와 predictions 를 sample_id 로 정렬 일치시킨다.
    df = df.set_index("sample_id").loc[preds["sample_id"]].reset_index()

    # --- 1. Facts --------------------------------------------------------
    # 임계는 각 fold 의 train 구간에서만 정한다. 전체 데이터를 보고 정하면
    # "테스트 데이터로 하이퍼파라미터를 튜닝했다"는 지적을 피할 수 없다.
    if args.fixed_thresholds or "fold" not in preds.columns:
        if "fold" not in preds.columns:
            print("[경고] predictions 에 fold 컬럼이 없어 고정 임계를 씁니다.")
        facts = facts_mod.build_facts(df, strategy=args.strategy,
                                      z_high=args.z_high, z_low=-args.z_high,
                                      baseline=args.baseline)
        cuts_tbl = None
    else:
        facts, cuts_tbl = facts_mod.build_facts_cv(
            df, preds["fold"].to_numpy(), strategy=args.strategy,
            baseline=args.baseline)
        cuts_tbl.to_csv(out / "tables" / "fitted_thresholds.csv", index=False)
        print("\n[fold 별 적합된 임계] — 변동이 크면 그 임계는 불안정함")
        print(cuts_tbl.round(3).to_string(index=False))
        spread = cuts_tbl.drop(columns=["fold"]).agg(["min", "max"]).T
        spread["range"] = spread["max"] - spread["min"]
        print("  폭:", ", ".join("{}={:.3g}".format(k, v)
                                 for k, v in spread["range"].items()))
    facts.to_csv(out / "facts.csv", index=False)

    dist = facts_mod.fact_distribution(facts)
    dist.to_csv(out / "tables" / "fact_distribution.csv")
    print("\n[상태별 fact 발생률] — 규칙이 데이터와 맞는지 먼저 확인")
    print(dist.round(3).to_string())

    sweep = facts_mod.threshold_sweep(df)
    sweep.to_csv(out / "tables" / "threshold_sweep.csv", index=False)

    # --- 2. Rule coverage ------------------------------------------------
    cov = rules_mod.coverage(facts, df["label"].to_numpy())
    cov.to_csv(out / "tables" / "rule_coverage.csv", index=False)
    print("\n[규칙별 발화율 / 정밀도]")
    print(cov.round(3).to_string(index=False))

    # --- 3. Audit + Correction ------------------------------------------
    res = nesy_correction.run(preds, facts, writer, experiment="nesy",
                              split=args.split, feature_set="HR+HRV+EDA")
    audited, corrected = res["audited"], res["corrected"]
    audited.to_csv(out / "tables" / "audited.csv", index=False)

    print("\n[Audit 판정 x 정오]")
    bd = nesy_audit.audit_breakdown(audited)
    print(bd.to_string())
    bd.to_csv(out / "tables" / "audit_breakdown.csv")

    print("\n[오류 탐지] flag_precision={:.3f}  flag_recall={:.3f}".format(
        res["metrics_audit"]["flag_precision"],
        res["metrics_audit"]["flag_recall"]))
    print("[CONFLICT 만]    precision={:.3f}  recall={:.3f}".format(
        res["conflict_only"]["flag_precision"],
        res["conflict_only"]["flag_recall"]))
    print("\n[Correction 장부] {}".format(res["ledger"]))

    # --- 4. 최종 비교표 ---------------------------------------------------
    writer.flush()          # nesy 행을 먼저 기록해야 아래에서 읽힌다
    results = pd.read_csv(out / "results.csv")
    keep = results[
        ((results["experiment"] == "subject_independent")
         & (results["model"] == "xgboost") & (results["split"] == args.split))
        | (results["experiment"] == "neural")
        | (results["experiment"].astype(str).str.startswith("nesy"))
    ].copy()
    final = keep[["model", "split", "feature_set", "macro_f1",
                  "balanced_accuracy", "stress_to_exercise",
                  "exercise_to_stress", "flag_precision", "flag_recall",
                  "notes"]].reset_index(drop=True)
    final.to_csv(out / "tables" / "final_comparison.csv", index=False)
    print("\n[최종 비교]")
    print(final.to_string(index=False))

    # --- 4b. 피험자 단위 유의성 검정 --------------------------------------
    # 표본은 윈도가 아니라 사람이다. 14-36명뿐이므로 Macro F1 차이가
    # 0.01 수준이면 우연과 구분되지 않는다.
    ctx_path = out / "predictions_neural_context.csv"
    to_compare = {"neural": preds[["subject_id", "true_label", "pred_label"]]}
    if ctx_path.exists():
        ctx = pd.read_csv(ctx_path)
        to_compare["neural_context"] = ctx[["subject_id", "true_label",
                                            "pred_label"]]
    to_compare["nesy_correction"] = (
        corrected[["subject_id", "true_label", "corrected_label"]]
        .rename(columns={"corrected_label": "pred_label"}))

    sig_rows = []
    for metric in ("macro_f1", "stress_to_exercise", "exercise_to_stress"):
        tbl, per = evaluate.compare_models(to_compare, metric=metric,
                                           reference="neural")
        sig_rows.append(tbl)
    sig = pd.concat(sig_rows, ignore_index=True)
    sig.to_csv(out / "tables" / "significance.csv", index=False)
    print("\n[피험자 단위 짝지은 검정 — 기준: neural]")
    print(sig[["model", "metric", "n", "median_a", "median_b", "median_diff",
               "p_value", "effect_size"]].round(4).to_string(index=False))
    print("  (median_a = 해당 모델, median_b = neural. "
          "stress_to_exercise 는 낮을수록 좋다)")

    per_subj = evaluate.per_subject_metrics(
        corrected.rename(columns={"corrected_label": "pred_label_nesy"}))
    per_subj.to_csv(out / "tables" / "per_subject_nesy.csv", index=False)

    # --- 5. 그림 ----------------------------------------------------------
    cm_neural = evaluate.confusion(audited["true_label"], audited["pred_label"])
    cm_nesy = evaluate.confusion(corrected["true_label"],
                                 corrected["corrected_label"])
    print("\n  fig -> {}".format(figures.fig4_confusion(
        [cm_neural, cm_nesy], ["Neural-only", "NeSy correction"],
        out / "figures", "fig4_confusion_nesy.png")))

    # case study: Neural 이 STRESS 라 했는데 CONFLICT 로 잡힌 샘플
    cand = audited[(audited["pred_label"] == "STRESS")
                   & (audited["audit"] == nesy_audit.CONFLICT)]
    if cand.empty:
        cand = audited[audited["audit"] == nesy_audit.CONFLICT]
    if not cand.empty:
        row = cand.iloc[0]
        f_row = facts[facts["sample_id"] == row["sample_id"]].iloc[0]
        merged = {**row.to_dict(), **f_row.to_dict()}
        print("  fig -> {}".format(figures.fig6_case_study(
            merged, out / "figures")))

    # --- 6. RULES.md ------------------------------------------------------
    report.write_md(
        Path(__file__).resolve().parents[1] / "docs" / "RULES.md",
        [("# Symbolic Rules", ""),
         ("## 규칙 정의", rules_mod.rules_markdown()),
         ("## Fact 정의",
          report.md_table(pd.DataFrame(
              [{"fact": k, "feature": v[0],
                "direction": "높을수록 참" if v[1] > 0 else "낮을수록 참"}
               for k, v in facts_mod.FACT_DEFS.items()]))),
         ("## Threshold 전략",
          "현재: `{}` (z_high={}).\n\n".format(args.strategy, args.z_high)
          + "`subject_z` 는 피험자 자신의 윈도 분포로 표준화한다. 라벨을 쓰지\n"
            "않으므로 정보 누수는 아니지만 '그 사람의 여러 상태를 이미 관측했다'는\n"
            "가정이 들어간다. 논문에 반드시 명시할 것."),
         ("## 규칙 coverage (현재 데이터)", report.md_table(cov)),
         ("## 피험자 단위 유의성 검정 (기준: neural)",
          report.md_table(sig[["model", "metric", "n", "median_diff",
                               "p_value", "effect_size", "note"]])
          + "\n\n표본은 피험자다. n 이 작으므로 p 값만으로 결론 내리지 말고\n"
            "median_diff 의 크기와 n_better 를 함께 볼 것."),
         ("## 상태별 fact 발생률", report.md_table(dist.reset_index()))])
    print("\n-> outputs/facts.csv, outputs/tables/final_comparison.csv, docs/RULES.md")


if __name__ == "__main__":
    main()
