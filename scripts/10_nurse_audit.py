"""Nurse Stress Dataset 감사 — 붙이기 전에 실제 상태를 확인한다.

    python scripts/10_nurse_audit.py

확인 항목
  - 세션 실제 길이 (zip 이름은 시작 시각만 준다)
  - 신호 결측 (논문에 PPG 잡음으로 IBI/HR 통째 누락 사례가 기록돼 있다)
  - 설문 사건이 세션 시간 범위에 들어오는 비율
  - 개인 baseline 조건(착용 1회당 안정 윈도 8개 이상) 충족 여부

담당: 역할 A
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from _bootstrap import banner, setup

from nesy import io_e4, nurse, report

ROOT = Path(__file__).resolve().parents[1]
SESSIONS = ROOT / "data/raw/nurse_stress/sessions"
SURVEY = ROOT / "data/raw/nurse_stress/SurveyResults.xlsx"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", default=str(SESSIONS))
    ap.add_argument("--survey", default=str(SURVEY))
    args = ap.parse_args()

    cfg, _ = setup()
    out = Path(cfg["paths"]["outputs"])
    (out / "tables").mkdir(parents=True, exist_ok=True)
    banner("NURSE STRESS DATASET 감사")

    sess = nurse.discover_sessions(args.sessions)
    print("세션 {}개 / 피험자 {}명".format(len(sess), sess["subject_id"].nunique()))

    ev = nurse.load_events(args.survey)
    print("설문 사건 {}건 / 피험자 {}명".format(len(ev), ev["subject_id"].nunique()))
    print("  수준별:", ev["level"].value_counts(dropna=False).to_dict())

    # --- 세션별 실제 범위와 신호 존재 여부 -------------------------------
    rows = []
    for _, s in sess.iterrows():
        p = Path(s["path"])
        present, fs_seen = {}, {}
        for name in nurse.SIGNAL_FILES:
            f = p / (name + ".csv")
            present[name] = f.exists() and f.stat().st_size > 40
        t0, t1, dur = nurse.session_span(p, io_e4)
        n_ev = 0
        if t0 is not None:
            e = ev[ev["subject_id"] == s["subject_id"]]
            n_ev = int(((e["start"] < t1) & (e["end"] > t0)).sum())
        rows.append({
            "subject_id": s["subject_id"], "session_id": s["session_id"],
            "t_start": t0, "t_end": t1, "dur_h": (dur or 0) / 3600.0,
            "n_events": n_ev,
            **{"has_" + k: v for k, v in present.items()},
        })
    aud = pd.DataFrame(rows)
    aud.to_csv(out / "tables" / "nurse_session_audit.csv", index=False)

    print("\n[세션 길이(시간)]")
    print(aud["dur_h"].describe()[["count", "mean", "50%", "min", "max"]]
          .round(2).to_string())
    print("  총 {:.0f}시간".format(aud["dur_h"].sum()))

    print("\n[신호 존재율]")
    for k in nurse.SIGNAL_FILES:
        print("  {:5s} {:.1%}".format(k, aud["has_" + k].mean()))

    short = aud[aud["dur_h"] < 0.5]
    print("\n30분 미만 세션: {}개 ({:.1%})".format(len(short), len(short) / len(aud)))

    # --- 사건 매칭 --------------------------------------------------------
    matched = int((aud["n_events"] > 0).sum())
    print("\n[사건 매칭] 사건이 하나 이상 걸린 세션 {}/{} ({:.1%})".format(
        matched, len(aud), matched / len(aud)))
    tot_ev = 0
    for _, e in ev.iterrows():
        a = aud[aud["subject_id"] == e["subject_id"]]
        if ((a["t_start"] < e["end"]) & (a["t_end"] > e["start"])).any():
            tot_ev += 1
    print("  세션 시간 범위에 들어온 사건 {}/{} ({:.1%})".format(
        tot_ev, len(ev), tot_ev / len(ev)))

    # --- 개인 baseline 조건 -----------------------------------------------
    # 60초 윈도 / 30초 이동 기준으로 세션당 윈도 수
    aud["n_windows"] = np.maximum(0, (aud["dur_h"] * 3600 - 60) // 30 + 1)
    ok = aud[aud["n_windows"] >= 16]      # 안정 윈도 8개 이상을 기대하려면 충분한 길이
    print("\n[개인 baseline 조건] 윈도 16개(=8분) 이상인 세션 {}/{} ({:.1%})".format(
        len(ok), len(aud), len(ok) / len(aud)))
    print("  Hongn 은 자극 전 baseline 이 윈도 1개뿐이었다.")

    per_subj = (aud.groupby("subject_id")
                .agg(세션=("session_id", "size"), 총시간=("dur_h", "sum"),
                     사건=("n_events", "sum"))
                .round(1).reset_index())
    print("\n[피험자별]")
    print(per_subj.to_string(index=False))

    report.write_md(ROOT / "docs" / "NURSE_AUDIT.md", [
        ("# Nurse Stress Dataset 세션 감사", ""),
        ("생성: `python scripts/10_nurse_audit.py`", ""),
        ("## 피험자별", report.md_table(per_subj)),
        ("## 세션 길이", report.md_table(
            aud["dur_h"].describe().round(2).reset_index())),
        ("## 신호 존재율", report.md_table(pd.DataFrame(
            [{"signal": k, "존재율": round(aud["has_" + k].mean(), 3)}
             for k in nurse.SIGNAL_FILES]))),
    ])
    print("\n-> outputs/tables/nurse_session_audit.csv, docs/NURSE_AUDIT.md")


if __name__ == "__main__":
    main()
