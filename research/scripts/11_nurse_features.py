"""Nurse Stress Dataset -> outputs/nurse_features.csv

Hongn 과 달리 프로토콜 구간이 없다. 세션 전체를 고정 윈도로 자르고, 설문에
보고된 스트레스 사건 시각으로 라벨을 붙인다.

**라벨 없음은 스트레스 없음이 아니다.** 설문은 교대당 가장 길었던 사건 최대
6개만 표시하므로 1,252시간 중 일부만 덮는다. `label` 이 비어 있는 윈도를 음성으로
세면 안 된다.

담당: 역할 A
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from _bootstrap import banner, setup

from nesy import feature_extraction as FE, io_e4, nurse

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", default=str(ROOT / "data/raw/nurse_stress/sessions"))
    ap.add_argument("--survey", default=str(ROOT / "data/raw/nurse_stress/SurveyResults.xlsx"))
    ap.add_argument("--min-dur-min", type=float, default=8.0,
                    help="이보다 짧은 세션은 개인 baseline 을 만들 수 없어 제외")
    args = ap.parse_args()

    cfg, _ = setup()
    out = Path(cfg["paths"]["outputs"])
    wl, ws = cfg["window"]["length_sec"], cfg["window"]["step_sec"]
    banner("NURSE FEATURES (window={}s, step={}s)".format(wl, ws))

    sess = nurse.discover_sessions(args.sessions)
    ev = nurse.load_events(args.survey)
    ev_by = {k: v for k, v in ev.groupby("subject_id")}

    rows, skipped = [], 0
    for i, (_, s) in enumerate(sess.iterrows(), 1):
        p = Path(s["path"])
        t0, t1, dur = nurse.session_span(p, io_e4)
        if t0 is None or dur < args.min_dur_min * 60:
            skipped += 1
            continue
        sig = io_e4.read_session(p)
        subj_ev = ev_by.get(s["subject_id"])

        t = t0
        while t + wl <= t1:
            feats = FE._window_features(sig, t, t + wl, cfg)
            label, level, causes = nurse.label_window(t, t + wl, subj_ev)
            rows.append({
                "sample_id": "{}|{:.0f}".format(s["session_id"], t),
                "subject_id": s["subject_id"],
                "session_id": s["session_id"],
                "session_type": "SHIFT",
                "t_start": t, "t_end": t + wl,
                "t_rel_min": (t - t0) / 60.0,
                "label": label, "level": level, "causes": causes,
                **feats,
            })
            t += ws
        if i % 100 == 0:
            print("  {}/{} 세션, 윈도 {}개".format(i, len(sess), len(rows)))

    df = pd.DataFrame(rows)
    meta = ["sample_id", "subject_id", "session_id", "session_type",
            "t_start", "t_end", "t_rel_min", "label", "level", "causes"]
    cols = meta + [c for c in FE.ALL_FEATURES if c in df.columns]
    df = df[cols + [c for c in df.columns if c not in cols]]
    dest = out / "nurse_features.csv"
    df.to_csv(dest, index=False)

    print("\n윈도 {:,}개 / 세션 {}개 (짧아서 제외 {}개)".format(
        len(df), df["session_id"].nunique(), skipped))
    print("총 {:.0f}시간".format(len(df) * ws / 3600))
    print("\n[라벨 분포] — 라벨 없음이 '스트레스 없음' 이 아니다")
    vc = df["label"].value_counts(dropna=False)
    for k, v in vc.items():
        print("  {:>14s} {:7,d}  ({:.1%})".format(str(k), v, v / len(df)))
    print("\n[수준별] {}".format(df["level"].value_counts(dropna=False).to_dict()))

    print("\n[신호 품질]")
    print("  유효 박동 20개 미만 윈도: {:.1%}".format((df["n_beats"] < 20).mean()))
    print("  hr_mean 중앙값 {:.1f} / acc_dyn_mean 중앙값 {:.4f}".format(
        df["hr_mean"].median(), df["acc_dyn_mean"].median()))

    lab = df[df["label"].notna()]
    if len(lab):
        print("\n[라벨된 윈도의 상태별 중앙값]")
        print(lab.groupby("label")[["hr_mean", "rmssd", "mean_tonic_eda",
                                    "peaks_density", "acc_dyn_mean"]]
              .median().round(3).to_string())
    print("\n-> {}".format(dest))


if __name__ == "__main__":
    main()
