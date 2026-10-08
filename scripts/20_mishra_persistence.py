"""지속성 계층 검증 (공개 데이터) — Mishra 2020 COVID-19 Wearables.

    python scripts/20_mishra_persistence.py          # 처음엔 원자료를 읽어 캐시를 만든다 (수 분)

데이터: data/raw/mishra/COVID-19-Wearables/ + mishra_supp_tables.xlsx (docs/MISHRA.md)

README 의 출발점인 '건강한 사람 월 0.66회 헛경보' 를 **같은 데이터**에서 다시 잰다.

비교 (모두 사람 단위 5-fold 로 설명 상한을 정하고, 각 fold 의 test 사람만 모아 평가):
  raw          이탈만 본다 (Mishra 방식에 가까운 비교군)
  ours         이탈 - 설명(운동·수면 부족). 설명된 날은 보류
  ours_nosleep 수면 부족 설명을 뺀 것 — 아파서 잠을 설친 날을 '잠 부족' 으로
               닫아버리는 역인과를 확인하려고
  random       ours 와 같은 개수를 무작위로 보류
그리고 raw 의 z 임계를 올려 ours 와 **경보 수를 맞춘** 탐지율.

경보율은 **건강군(potential.healthy)** 에서, 탐지율은 **COVID 양성군**에서 잰다.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from _bootstrap import banner, setup

from nesy import homekit as H, mishra as M, persistence as P

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
CACHE = ROOT / "data/cache"
EV_KW = dict(match_before=7, match_after=3)     # 증상 7일 전 ~ 3일 후 경보를 맞은 것으로
KS = (1, 2, 3)


def load_tables(root, refresh=False):
    dp, np_ = CACHE / "mishra_day.parquet", CACHE / "mishra_night.parquet"
    if dp.exists() and np_.exists() and not refresh:
        return pd.read_parquet(dp), pd.read_parquet(np_)
    print("원자료 읽는 중 (118명, 수 분)...")
    day, night = M.load(root)
    CACHE.mkdir(parents=True, exist_ok=True)
    day.to_parquet(dp, index=False)
    night.to_parquet(np_, index=False)
    return day, night


def rates(t, hold, events, healthy, covid):
    """건강군 경보율 + COVID 군 탐지율."""
    a = P.alerts(t, 0.5, k=K, hold_col=hold)
    h = P.evaluate(a[a["subject_id"].isin(healthy)])
    c = P.evaluate(a[a["subject_id"].isin(covid)], event_days=events, **EV_KW)
    return dict(healthy_alerts_ppm=h["alerts_per_person_month"],
                healthy_alerts=h["n_alerts"],
                covid_detection=c["detection_rate"], covid_detected=c["n_detected"],
                covid_events=c["n_events"])


def main():
    global K
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/raw/mishra")
    ap.add_argument("--z", type=float, default=2.0)
    ap.add_argument("--min-night-min", type=int, default=120)
    ap.add_argument("--refresh", action="store_true", help="캐시 무시하고 원자료를 다시 읽음")
    args = ap.parse_args()
    setup()
    root = ROOT / args.root

    banner("Mishra 2020 — 공개 데이터로 지속성 계층 검증")
    day, night = load_tables(root, args.refresh)
    cat = M.load_categories(root)
    events = M.load_events(root, "COVID-19")
    base = H.build_day_table(day, night, min_night_min=args.min_night_min, z_thresh=args.z)
    base["category"] = base["subject_id"].map(cat).fillna("unknown")

    healthy = set(base.loc[base["category"] == "potential.healthy", "subject_id"])
    covid = set(base.loc[base["category"] == "COVID positive", "subject_id"])
    events = {e for e in events if e[0] in covid}
    per = base[base["valid"]].groupby("category")["subject_id"].agg(["nunique", "size"])
    print(per.rename(columns={"nunique": "사람", "size": "유효일"}).to_string())
    print("COVID 사건(증상 시작일) {}건".format(len(events)))

    ours = H.crossfit_explanation(base, args.z, H.CAUSES)
    nosleep = H.crossfit_explanation(base, args.z, ("exercise",))
    dv = ours[ours["deviated"]]
    print("\n이탈일 {}일 -> 설명 {}".format(
        len(dv), dv["explained_by"].replace("", "unexplained").value_counts().to_dict()))

    drop = (ours["carried_raw"] - ours["carried_frac"]).groupby(ours["subject_id"]).sum()
    rc, rh = H.random_filter(ours, drop.to_dict())
    conds = {
        "raw": (ours.assign(carried_frac=ours["carried_raw"]), None),
        "ours": (ours, "held"),
        "ours_nosleep": (nosleep, "held"),
        "random": (ours.assign(carried_frac=rc, held=rh), "held"),
    }

    banner("K 스윕 — 건강군 경보율 vs COVID 탐지율")
    rows = []
    for K in KS:
        for name, (t, hold) in conds.items():
            r = rates(t, hold, events, healthy, covid)
            rows.append(dict(k=K, condition=name, **r))
    sweep = pd.DataFrame(rows)
    print(sweep.round(3).to_string(index=False))

    banner("건강군 경보 수를 맞춘 비교 — raw 의 z 를 올려 ours 와 같게")
    mrows = []
    for K in KS:
        target = sweep[(sweep.k == K) & (sweep.condition == "ours")].iloc[0]
        best = None
        for z in np.arange(args.z, args.z + 4.01, 0.1):
            t = H.apply_explanation(base, z_thresh=z)
            r = rates(t.assign(carried_frac=t["carried_raw"]), None, events, healthy, covid)
            gap = abs(r["healthy_alerts"] - target["healthy_alerts"])
            if best is None or gap < best[0]:
                best = (gap, z, r)
        _, z, r = best
        mrows.append(dict(k=K, ours_healthy_alerts=int(target["healthy_alerts"]),
                          ours_detection=target["covid_detection"],
                          raw_z=round(z, 2), raw_healthy_alerts=r["healthy_alerts"],
                          raw_detection=r["covid_detection"]))
    matched = pd.DataFrame(mrows)
    print(matched.round(3).to_string(index=False))
    print("\n  ours_detection > raw_detection 이어야 '설명 계층이 일을 한다' 고 말할 수 있다.")
    print("  COVID 사건이 {}건뿐이다. 탐지 1건 = {:.3f} 이다.".format(len(events), 1 / max(1, len(events))))

    banner("참고: 논문이 보고한 경보 빈도 (Supp. Table 29, 30일당)")
    t29 = pd.read_excel(root / M.SUPP_XLSX, sheet_name=M.CATEGORY_SHEET, header=2).iloc[:, :3]
    print(t29.groupby("caseCategory")["alarmCount"].agg(["count", "mean", "median"]).round(2).to_string())

    OUT.mkdir(exist_ok=True)
    sweep.to_csv(OUT / "mishra_sweep.csv", index=False)
    matched.to_csv(OUT / "mishra_matched.csv", index=False)
    print("\n저장: outputs/mishra_sweep.csv, mishra_matched.csv")


if __name__ == "__main__":
    main()
