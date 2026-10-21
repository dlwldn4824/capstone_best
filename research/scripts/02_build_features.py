"""Day 2-3 — 전처리 + feature 추출 -> outputs/features.csv (+ Fig 1, Fig 2)

담당: 역할 A
"""
import argparse
from pathlib import Path

import numpy as np
from _bootstrap import banner, setup

from nesy import (feature_extraction, figures, io_e4, preprocess_bvp,
                  preprocess_eda, protocol)


def make_preprocessing_figures(cfg, proto, idx, outdir):
    """첫 STRESS 세션의 baseline 구간으로 Fig 1 / Fig 2 를 만든다."""
    stress = idx[idx["session_type"] == "STRESS"]
    if stress.empty:
        return []
    sess = io_e4.read_session(stress.iloc[0]["path"])
    subj = stress.iloc[0]["subject"]
    segs, problem = protocol.segment_session(subj, "STRESS", sess["tags"], proto)
    if problem or not segs:
        return []
    seg = segs[0]
    t0, t1 = seg.start, min(seg.end, seg.start + 60)

    paths = []
    bvp = sess.get("BVP")
    if bvp is not None:
        w = bvp.slice_time(t0, t1)
        r = preprocess_bvp.process(w.values, w.fs, cfg)
        paths.append(figures.fig1_bvp_pipeline(
            w.values, r["filtered"], r["peaks"], w.fs, outdir))

    eda = sess.get("EDA")
    if eda is not None:
        w = eda.slice_time(t0, t1)
        r = preprocess_eda.process(w.values, w.fs, cfg)
        paths.append(figures.fig2_eda_decomposition(
            r["clean"], r["tonic"], r["phasic"], r["events"], w.fs, outdir))
    return paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=None)
    ap.add_argument("--no-figures", action="store_true")
    args = ap.parse_args()

    cfg, proto = setup()
    if args.raw:
        cfg["paths"]["raw"] = str(Path(__file__).resolve().parents[1] / args.raw)

    banner("FEATURE EXTRACTION  (window={}s, step={}s)".format(
        cfg["window"]["length_sec"], cfg["window"]["step_sec"]))

    idx = io_e4.discover_sessions(cfg["paths"]["raw"])
    df, audit = feature_extraction.build(cfg, proto, idx)

    out = Path(cfg["paths"]["features_csv"])
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    audit.to_csv(Path(cfg["paths"]["outputs"]) / "tables" / "build_audit.csv",
                 index=False)

    print("\nfeatures.csv: {} 행 x {} 열".format(len(df), df.shape[1]))
    print("\n[3-class] 분포")
    print(df["label"].value_counts().to_string())
    print("\n[4-class] 분포")
    print(df["condition"].value_counts().to_string())
    print("\n피험자별 윈도 수")
    print(df.groupby("subject_id").size().to_string())

    feats = [c for c in feature_extraction.ALL_FEATURES if c in df.columns]
    nan_rate = df[feats].isna().mean().sort_values(ascending=False)
    print("\n결측률 상위 10개 feature")
    print((nan_rate.head(10) * 100).round(1).to_string())
    print("\nfeature 개수: {} (기대 49 + 품질지표 2)".format(len(feats)))

    if not args.no_figures:
        outdir = Path(cfg["paths"]["outputs"]) / "figures"
        for p in make_preprocessing_figures(cfg, proto, idx, outdir):
            print("  fig -> {}".format(p))
        core = ["hr_mean", "rmssd", "sdnn", "mean_tonic_eda", "peaks_density",
                "acc_dyn_mean", "acc_std", "LF_HF_ratio"]
        print("  fig -> {}".format(
            figures.fig3_feature_distributions(df, core, outdir)))

    print("\n-> {}".format(out))


if __name__ == "__main__":
    main()
