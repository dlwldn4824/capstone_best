"""생활 맥락이 헛경보를 얼마나 걷어내는가 — PMData (음주·스트레스 일지).

    python scripts/21_pmdata_context.py      # 처음엔 원자료를 읽어 캐시 (1~2분)

데이터: data/raw/pmdata/pXX/ (docs/PMDATA.md)

README 첫 문장 — "어제 술을 마셔서 그런 건데요" — 을 실제 기록으로 잰다.
Mishra 에서는 걸음·수면만으로 설명된 이탈일이 16% 뿐이었다 (docs/MISHRA.md).

1. 효과 크기: 그 원인이 있던 밤과 없던 밤의 밤 심박 차이, **사람별로** 짝지어 본다.
   규칙을 쓰기 전에 그 원인이 실제로 밤 심박을 올리는지부터 확인한다.
2. 설명 원인을 하나씩 더할 때 이탈일 중 설명되는 비율과 경보율.
   감염 라벨이 없으므로 **모든 경보가 헛경보**다 — 경보율이 곧 헛경보율이다.
3. 대조군: 'all' 과 같은 개수를 무작위로 보류.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from _bootstrap import banner, setup
from scipy.stats import wilcoxon

from nesy import homekit as H, persistence as P, pmdata as PM

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
CACHE = ROOT / "data/cache"
KS = (1, 2, 3)


def load_tables(root, refresh=False):
    dp, np_ = CACHE / "pmdata_day.parquet", CACHE / "pmdata_night.parquet"
    if dp.exists() and np_.exists() and not refresh:
        return pd.read_parquet(dp), pd.read_parquet(np_)
    print("원자료 읽는 중 (16명)...")
    day, night = PM.load(root, verbose=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    day.to_parquet(dp, index=False)
    night.to_parquet(np_, index=False)
    return day, night


def effect(table, cause, min_each=3):
    """사람별 (원인 있던 밤 평균 - 없던 밤 평균). 양쪽 다 min_each 밤 이상인 사람만."""
    v = table[table["night_min"] > 0]
    rows = []
    for s, g in v.groupby("subject_id"):
        a = g.loc[g[cause], "night_hr"]
        b = g.loc[~g[cause], "night_hr"]
        if len(a) >= min_each and len(b) >= min_each:
            rows.append((s, a.mean() - b.mean(), len(a)))
    if not rows:
        return dict(cause=cause, n_people=0)
    diff = np.array([r[1] for r in rows])
    p = wilcoxon(diff).pvalue if len(diff) >= 5 else float("nan")
    return dict(cause=cause, n_people=len(diff), n_nights=int(sum(r[2] for r in rows)),
                median_bpm=float(np.median(diff)), n_up=int((diff > 0).sum()), p=float(p))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/raw/pmdata")
    ap.add_argument("--z", type=float, default=2.0)
    ap.add_argument("--min-night-min", type=int, default=180)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    setup()

    banner("PMData — 생활 맥락이 헛경보를 얼마나 걷어내는가")
    day, night = load_tables(ROOT / args.root, args.refresh)
    base = H.build_day_table(day, night, min_night_min=args.min_night_min, z_thresh=args.z)
    base = PM.add_context(base)
    v = base[base["valid"]]
    print("사람 {}명 / 유효일 {:,} / 음주 기록률 {:.0%} / 스트레스 기록률 {:.0%}".format(
        v["subject_id"].nunique(), len(v), v["drank"].notna().mean(),
        v["stress_score"].notna().mean()))

    # --- 1. 효과 크기 -----------------------------------------------------------
    banner("1. 그 원인이 있던 밤, 밤 심박이 오르는가 (사람별 짝 비교)")
    eff_src = base.copy()
    eff_src = eff_src[eff_src["night_min"] >= args.min_night_min]
    eff = pd.DataFrame([effect(eff_src, c) for c in PM.CAUSES])
    print(eff.round(3).to_string(index=False))

    # --- 2. 원인을 하나씩 더하며 -------------------------------------------------
    banner("2. 설명 원인을 더할수록 — 이탈일 설명 비율과 경보율 (모든 경보 = 헛경보)")
    ladders = {
        "raw": (),
        "sensor (운동·수면)": ("exercise", "sleep_debt"),
        "+ alcohol": ("exercise", "sleep_debt", "alcohol"),
        "+ stress": ("exercise", "sleep_debt", "alcohol", "stress"),
        "context only (음주·스트레스)": ("alcohol", "stress"),
    }
    tables, rows = {}, []
    for name, causes in ladders.items():
        t = (H.crossfit_explanation(base, args.z, causes) if causes
             else H.apply_explanation(base, z_thresh=args.z, causes=()))
        tables[name] = t
        dv = t[t["deviated"]]
        r = dict(condition=name, deviated_days=len(dv),
                 explained_frac=float(dv["held"].mean()) if len(dv) else 0.0)
        for k in KS:
            e = P.evaluate(P.alerts(t, 0.5, k=k, hold_col="held"))
            r["alerts_ppm_k{}".format(k)] = e["alerts_per_person_month"]
        rows.append(r)

    full = tables["+ stress"]
    drop = (full["carried_raw"] - full["carried_frac"]).groupby(full["subject_id"]).sum()
    rc, rh = H.random_filter(full, drop.to_dict())
    rnd = full.assign(carried_frac=rc, held=rh)
    r = dict(condition="random (같은 개수)", deviated_days=int(rnd["deviated"].sum()),
             explained_frac=float(rh[rnd["deviated"].to_numpy()].mean()))
    for k in KS:
        e = P.evaluate(P.alerts(rnd, 0.5, k=k, hold_col="held"))
        r["alerts_ppm_k{}".format(k)] = e["alerts_per_person_month"]
    rows.append(r)
    ladder = pd.DataFrame(rows)
    print(ladder.round(3).to_string(index=False))

    dv = full[full["deviated"]]
    print("\n이탈일 원인 분포 (+ stress):",
          dv["explained_by"].replace("", "unexplained").value_counts().to_dict())

    OUT.mkdir(exist_ok=True)
    eff.to_csv(OUT / "pmdata_effects.csv", index=False)
    ladder.to_csv(OUT / "pmdata_ladder.csv", index=False)
    print("\n저장: outputs/pmdata_effects.csv, pmdata_ladder.csv")


if __name__ == "__main__":
    main()
