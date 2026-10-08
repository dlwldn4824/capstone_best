"""지속성 계층 검증 — PCR 독감 라벨로 '설명 계층이 일을 하는가' 를 잰다.

    python scripts/19_homekit_persistence.py              # 실제 데이터
    python scripts/19_homekit_persistence.py --synthetic  # 승인 전 리허설

16_persistence.py (Nurse) 가 답하지 못한 질문에 답한다. Nurse 의 사건은
자기보고 스트레스였고 근무 중에만 쟀다. 여기는 **잘 때 쟀고 PCR 로 확인된 독감**이다.

비교 셋 (모두 test 사람에게서만 잰다):
  raw      이탈만 본다 (Mishra 방식)
  ours     이탈 - 설명(운동·수면 부족). 설명된 날은 보류(hold)
  random   ours 와 **같은 개수**의 이탈일을 무작위로 걷어낸다

그리고 핵심 비교: raw 의 z 임계를 올려 **ours 와 같은 경보 수**로 맞췄을 때
탐지율. 경보율을 맞추지 않은 탐지율 비교는 의미가 없다.

⚠ --synthetic 의 수치는 연구 결과가 아니다 (효과를 직접 심었다).
⚠ 2020-03 중순부터 봉쇄로 걸음·수면이 모두에게서 동시에 바뀐다. 결과를
  봉쇄 전/후로 나눠 같이 볼 것 (--split-date).

담당: 역할 C
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from _bootstrap import banner, setup

from nesy import homekit as H, persistence as P

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
EV_KW = dict(match_before=3, match_after=1)
KS = (1, 2, 3, 4)


def matched_raw(table, target_alerts, k, z_grid):
    """raw 의 z 임계를 올려 경보 수를 target 에 가장 가깝게 맞춘다."""
    best = None
    for z in z_grid:
        t = H.apply_explanation(table, z_thresh=z)
        r = P.evaluate(P.alerts(t.assign(carried_frac=t["carried_raw"]), 0.5, k=k),
                       event_days=EVENTS, **EV_KW)
        gap = abs(r["n_alerts"] - target_alerts)
        if best is None or gap < best[0]:
            best = (gap, z, r)
    return best[1], best[2]


def main():
    global EVENTS
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/raw/homekit2020")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--z", type=float, default=2.0, help="이탈 z 임계")
    ap.add_argument("--test-frac", type=float, default=0.3)
    ap.add_argument("--split-date", default="2020-03-15", help="봉쇄 전/후 경계")
    ap.add_argument("--n-perm", type=int, default=2000)
    args = ap.parse_args()
    setup()

    root = ROOT / args.root
    tag = "homekit"
    if args.synthetic:
        from nesy import homekit_synthetic as S
        root = ROOT / "data/cache/homekit_synth"
        S.write(root, n_subjects=30, n_days=70)
        tag = "homekit_synth"
        print("!! 합성 데이터 - 수치는 연구 결과가 아니다")

    banner("Homekit2020 지속성 계층")
    day = H.load_day(root)
    night = H.load_nocturnal(root)
    EVENTS = H.load_events(root)
    table = H.build_day_table(day, night, z_thresh=args.z)

    train_s, test_s = H.subject_split(table["subject_id"], test_frac=args.test_frac)
    tr = table["subject_id"].isin(train_s).to_numpy()
    cap = H.fit_cause_ceiling(table, train_mask=tr)
    table = H.apply_explanation(table, z_thresh=args.z, ceiling=cap)
    test = table[~tr].reset_index(drop=True)
    EVENTS = {e for e in EVENTS if e[0] in test_s}

    print("사람 {}명 (train {} / test {}) / 유효일 {:,}".format(
        table["subject_id"].nunique(), len(train_s), len(test_s), int(table["valid"].sum())))
    print("test 독감 사건 {}건".format(len(EVENTS)))
    print("설명 상한 (train):", {k: (round(v, 2) if v else None) for k, v in cap.items()})
    dv = test[test["deviated"]]
    print("test 이탈일 {}일 -> 설명됨 {} ({:.0%}) / 미설명 {}".format(
        len(dv), int(dv["held"].sum()), dv["held"].mean() if len(dv) else 0,
        int(test["carried_frac"].sum())))
    print(dv["explained_by"].replace("", "unexplained").value_counts().to_string())

    # --- K 스윕: 세 조건 ------------------------------------------------------
    drop = (test["carried_raw"] - test["carried_frac"]).groupby(test["subject_id"]).sum()
    rnd_carried, rnd_held = H.random_filter(test, drop.to_dict())
    conds = {
        "raw": (test.assign(carried_frac=test["carried_raw"]), None),
        "ours": (test, "held"),
        "random": (test.assign(carried_frac=rnd_carried, held=rnd_held), "held"),
    }
    rows = []
    for name, (t, hold) in conds.items():
        s = P.sweep(t, 0.5, ks=KS, event_days=EVENTS, hold_col=hold, **EV_KW)
        s.insert(0, "condition", name)
        rows.append(s)
    sweep = pd.concat(rows, ignore_index=True)
    banner("K 스윕 (test 사람)")
    cols = ["condition", "k", "n_alerts", "alerts_per_person_month",
            "detection_rate", "alert_precision"]
    print(sweep[cols].round(3).to_string(index=False))

    # --- 경보 수를 맞춘 비교 -------------------------------------------------
    banner("경보 수를 맞춘 비교 — raw 의 z 임계를 올려서 ours 와 같게")
    z_grid = np.round(np.arange(args.z, args.z + 6.01, 0.25), 2)
    mrows = []
    for k in KS:
        ours = sweep[(sweep.condition == "ours") & (sweep.k == k)].iloc[0]
        z, r = matched_raw(test, ours["n_alerts"], k, z_grid)
        mrows.append(dict(k=k, ours_alerts=int(ours["n_alerts"]),
                          ours_detection=ours["detection_rate"],
                          raw_z=z, raw_alerts=r["n_alerts"],
                          raw_detection=r["detection_rate"]))
    matched = pd.DataFrame(mrows)
    print(matched.round(3).to_string(index=False))
    print("\n  ours_detection > raw_detection 이어야 '설명 계층이 일을 한다' 고 말할 수 있다.")

    # --- 우연 수준 -------------------------------------------------------------
    banner("우연 수준 (ours, 사람별 경보 수 보존 · 날짜만 섞음)")
    crow = []
    for k in KS:
        a = P.alerts(test, 0.5, k=k, hold_col="held")
        c = P.chance_baseline(a, EVENTS, n_perm=args.n_perm, **EV_KW)
        c["k"] = k
        crow.append(c)
    chance = pd.DataFrame(crow)
    print(chance.round(3).to_string(index=False))

    # --- 봉쇄 전/후 -------------------------------------------------------------
    cut = pd.Timestamp(args.split_date)
    banner("봉쇄 전/후 (ours, K=2) — 경계 {}".format(cut.date()))
    a = P.alerts(test, 0.5, k=2, hold_col="held")
    for name, m in (("before", a["day"] < cut), ("after", a["day"] >= cut)):
        ev = {e for e in EVENTS if (e[1] < cut) == (name == "before")}
        r = P.evaluate(a[m], event_days=ev, **EV_KW)
        print("  {:6s} 관측일 {:5d}  경보/인·월 {:.3f}  사건 {:3d}  탐지율 {}".format(
            name, r["observed_days"], r["alerts_per_person_month"], len(ev),
            "{:.3f}".format(r["detection_rate"]) if ev else "—"))

    OUT.mkdir(exist_ok=True)
    sweep.to_csv(OUT / "{}_sweep.csv".format(tag), index=False)
    matched.to_csv(OUT / "{}_matched.csv".format(tag), index=False)
    chance.to_csv(OUT / "{}_chance.csv".format(tag), index=False)
    print("\n저장: outputs/{0}_sweep.csv, {0}_matched.csv, {0}_chance.csv".format(tag))


if __name__ == "__main__":
    main()
