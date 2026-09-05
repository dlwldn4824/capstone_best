"""Exp 1b/1c — 개인 baseline 이탈 -> 설명 판정 -> 맥락 은닉 실험.

    python scripts/09_deviation.py

원래 연구 질문의 출력 형태를 만든다.

    평소와 다른가?  ->  다르다면 무엇으로 설명되는가?
                        운동 / 스트레스 / **설명 안 됨**

Exp 1c(맥락 은닉)가 핵심이다. 운동 규칙을 통째로 지우고 운동 구간을 넣으면
분류기는 셋 중 하나를 강제로 골라야 하지만 이 구조는 "설명 안 됨"을 낼 수 있다.
그것이 규칙이 필요한 이유이자 최종 시스템(설명되지 않는 변화 탐지)의 축소판이다.

담당: 역할 C
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from _bootstrap import banner, setup

from nesy import (deviation as DV, facts as F, feature_extraction as FE,
                  report, rules as R)


def evidence_for(facts, drop=()):
    """지정한 규칙을 뺀 상태의 evidence. drop 이 맥락 은닉 실험의 손잡이다."""
    keep = [r for r in R.RULES if r.name not in drop]
    return R.apply_rules(facts, keep)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="low_activity",
                    choices=["low_activity", "labeled_rest", "temporal"])
    ap.add_argument("--agg", default="mean", choices=["mean", "max"])
    args = ap.parse_args()

    cfg, _ = setup()
    out = Path(cfg["paths"]["outputs"])
    banner("개인 baseline 이탈 (baseline={}, agg={})".format(args.baseline, args.agg))

    df = FE.load_features(cfg).reset_index(drop=True)
    preds = pd.read_csv(out / "predictions_neural_context.csv")
    df = df.set_index("sample_id").loc[preds["sample_id"]].reset_index()
    folds = preds["fold"].to_numpy()

    # --- 1. 이탈 점수 ------------------------------------------------------
    sc = DV.score(df, mode=args.baseline, agg=args.agg)
    df = pd.concat([df, sc], axis=1)

    print("\n[상태별 이탈 점수 중앙값]")
    print(df.groupby("label")["deviation"].describe()[["count", "50%", "75%"]]
          .round(2).to_string())

    det = DV.detection_auc(df["deviation"], df["label"],
                           subjects=df["subject_id"])
    print("\n[이탈 탐지 AUC]  통합 {:.3f} | 피험자 평균 {:.3f}".format(
        det["pooled_auc"], det["mean_subject_auc"]))
    print("  (통합 < 피험자평균 이면 개인차가 절대값 비교를 방해한다는 뜻)")
    if det["per_subject"] is not None:
        det["per_subject"].to_csv(out / "tables" / "deviation_auc_subject.csv",
                                  index=False)

    # 세 가지 baseline 방식 비교
    print("\n[baseline 선택 방식 비교]")
    rows = []
    for mode in ("low_activity", "labeled_rest", "temporal"):
        s = DV.score(df, mode=mode, agg=args.agg)["deviation"]
        d = DV.detection_auc(s, df["label"], subjects=df["subject_id"])
        rows.append({"baseline": mode, "pooled_auc": d["pooled_auc"],
                     "mean_subject_auc": d["mean_subject_auc"]})
        print("  {:14s} 통합 {:.3f} | 피험자평균 {:.3f}{}".format(
            mode, d["pooled_auc"], d["mean_subject_auc"],
            "   <- 라벨 사용(oracle)" if mode == "labeled_rest" else ""))
    pd.DataFrame(rows).to_csv(out / "tables" / "deviation_baselines.csv",
                              index=False)

    # --- 2. facts + 이탈 임계 (fold train 에서만) ---------------------------
    facts, cuts = F.build_facts_cv(df, folds)
    dev_thr = {}
    for f in pd.unique(folds):
        tr = folds != f
        dev_thr[f] = DV.fit_dev_threshold(df["deviation"], df["label"], tr)
    print("\n[fold 별 이탈 임계] " + ", ".join(
        "{}={:.2f}".format(k, v) for k, v in dev_thr.items()))
    thr_vec = np.array([dev_thr[f] for f in folds])

    # --- 3. 설명 판정 (전체 규칙) -----------------------------------------
    ev_full = evidence_for(facts)
    verdict = DV.explain(df["deviation"], ev_full, thr_vec)
    df["verdict"] = verdict

    print("\n[설명 판정 x 실제 상태]")
    tab = pd.crosstab(df["label"], df["verdict"])
    print(tab.to_string())
    tab.to_csv(out / "tables" / "explanation_full.csv")

    dev_only = df[df["verdict"] != DV.NOT_DEVIATING]
    print("\n이탈로 판정된 {}건 중 설명 성공률".format(len(dev_only)))
    for lab, want in (("EXERCISE", DV.EXPLAINED_EXERCISE),
                      ("STRESS", DV.EXPLAINED_STRESS)):
        s = dev_only[dev_only["label"] == lab]
        if len(s):
            print("  {:8s} -> {:22s} {:.3f}  (설명 안 됨 {:.3f})".format(
                lab, want, (s["verdict"] == want).mean(),
                (s["verdict"] == DV.UNEXPLAINED).mean()))

    # --- 4. Exp 1c 맥락 은닉 ----------------------------------------------
    banner("Exp 1c — 맥락 은닉: 운동 규칙을 제거하면?")
    ev_hidden = evidence_for(facts, drop=("R1_exercise_hr_activity",
                                          "R2_exercise_activity_only",
                                          "R2b_exercise_vigorous_movement"))
    v_hidden = DV.explain(df["deviation"], ev_hidden, thr_vec)
    df["verdict_hidden"] = v_hidden

    ex = df["label"] == "EXERCISE"
    ex_dev = ex & (df["verdict_hidden"] != DV.NOT_DEVIATING)
    print("\n운동 구간 {}개 중 이탈로 잡힌 것 {}개".format(int(ex.sum()), int(ex_dev.sum())))
    print("\n[운동 구간에 대한 판정 — 운동 규칙이 없는 상태]")
    hv = df.loc[ex_dev, "verdict_hidden"].value_counts()
    for k, n in hv.items():
        print("  {:22s} {:4d}  ({:.3f})".format(k, n, n / max(1, ex_dev.sum())))

    # 비교군은 반드시 **같은 정보를 박탈한** 분류기여야 한다.
    # 운동을 학습한 분류기와 비교하면 불공정하다. REST/STRESS 두 클래스만으로
    # 학습해 운동을 한 번도 본 적 없게 만든 뒤, 운동 구간을 넣는다.
    # 분류기는 기권할 수 없으므로 반드시 REST 나 STRESS 중 하나를 답한다.
    from nesy import baseline_ml, subject_split

    tr = df["label"].isin(["REST", "STRESS"]).to_numpy()
    feat = [c for c in FE.ALL_FEATURES if c in df.columns]
    tr_df = df[tr].reset_index(drop=True)

    cls_pred = np.empty(int(ex_dev.sum()), dtype=object)
    ex_idx = np.where(ex_dev.to_numpy())[0]
    votes = []
    for a, b, _ in subject_split.make_splits(tr_df, "group_kfold", 5):
        model = baseline_ml.make_model("xgboost", 42, n_classes=2)
        classes = sorted(tr_df["label"].unique())
        ymap = {c: i for i, c in enumerate(classes)}
        model.fit(tr_df.iloc[a][feat].to_numpy(dtype=float),
                  np.array([ymap[v] for v in tr_df.iloc[a]["label"]]))
        pr = model.predict_proba(df.iloc[ex_idx][feat].to_numpy(dtype=float))
        votes.append(np.asarray(classes)[np.argmax(pr, axis=1)])
    # fold 다수결
    votes = np.array(votes)
    for i in range(len(ex_idx)):
        v, c = np.unique(votes[:, i], return_counts=True)
        cls_pred[i] = v[np.argmax(c)]

    print("\n[같은 구간에 대한 분류기 예측 — 운동을 학습하지 않음, 기권 불가]")
    cv = pd.Series(cls_pred).value_counts()
    for k, n in cv.items():
        print("  {:22s} {:4d}  ({:.3f})".format(k, n, n / max(1, len(cls_pred))))

    unexp = float((df.loc[ex_dev, "verdict_hidden"] == DV.UNEXPLAINED).mean())
    wrong_stress = float((pd.Series(cls_pred) == "STRESS").mean())
    print("\n  우리 구조: '설명 안 됨' {:.1%}".format(unexp))
    print("  분류기   : '스트레스'라고 단정 {:.1%}".format(wrong_stress))
    print("  (둘 다 운동을 모르는 상태. 분류기는 기권 선택지가 없다)")

    df[["sample_id", "subject_id", "label", "deviation", "verdict",
        "verdict_hidden"]].to_csv(out / "deviation.csv", index=False)

    # --- 5. 문서 ----------------------------------------------------------
    report.write_md(
        Path(__file__).resolve().parents[1] / "docs" / "DEVIATION_RESULTS.md",
        [("# 개인 baseline 이탈 + 설명 판정", ""),
         ("## baseline 선택 방식", report.md_table(pd.DataFrame(rows))),
         ("## 설명 판정 x 실제 상태", report.md_table(tab.reset_index())),
         ("## Exp 1c 맥락 은닉 (운동 규칙 제거)",
          "운동 구간 {}개 중 이탈로 잡힌 {}개에 대해\n\n".format(
              int(ex.sum()), int(ex_dev.sum()))
          + "- 우리 구조: `UNEXPLAINED` {:.1%}\n".format(unexp)
          + "- 분류기: `STRESS` 로 단정 {:.1%}\n\n".format(wrong_stress)
          + "분류기는 기권할 수 없으므로 모르는 맥락을 아는 것 중 하나로 "
            "밀어넣는다. 이 차이가 규칙을 두는 이유다.")])
    print("\n-> outputs/deviation.csv, docs/DEVIATION_RESULTS.md")


if __name__ == "__main__":
    main()
