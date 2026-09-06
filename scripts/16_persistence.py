"""지속성 계층 — 창 판정을 알림으로 바꾸고 경보율·탐지율을 쌍으로 낸다.

    python scripts/16_persistence.py

**왜 필요한가.** 앞 단계까지는 창 하나하나를 판정했다. 그대로 알리면 하루에도
수십 번 울린다. 실제 서비스는 하루를 하나로 접고, 며칠 이어질 때만 알린다.

**왜 두 숫자를 같이 내는가.** 경보율만 보면 아무것도 안 하는 시스템이 1등이다.
탐지율만 보면 매일 울리는 시스템이 1등이다. 둘을 함께 볼 때만 의미가 있다.

⚠ **이 데이터로 감염 탐지를 평가하는 것이 아니다.** Nurse 의 사건은 자기보고
스트레스이지 질병이 아니다. 여기서 재는 것은 **누적 기계장치가 의도대로 도는가**
이며, 사건 대조는 그 기계가 사람이 실제로 힘들었다고 적은 날과 얼마나 겹치는지를
보는 대리 지표다.

담당: 역할 C
"""
from pathlib import Path

import numpy as np
import pandas as pd
from _bootstrap import banner, setup

from nesy import deviation as DV, facts as F, persistence as P, report, rules as R

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
TZ = "America/Chicago"


def load():
    feat = pd.read_csv(OUT / "nurse_features.csv")
    dev = pd.read_csv(OUT / "nurse_deviation.csv",
                      usecols=["sample_id", "dev_low_activity"])
    df = feat.merge(dev, on="sample_id", how="inner").reset_index(drop=True)
    df["day"] = P.day_index(df["t_start"], tz=TZ)
    return df


def main():
    setup()
    banner("지속성 계층 — Nurse 실환경 1,241시간")
    df = load()
    print("창 {:,}개 / 사람 {}명 / 관측일 {}일".format(
        len(df), df["subject_id"].nunique(),
        df.groupby("subject_id")["day"].nunique().sum()))

    # --- 1. 창 판정: 이탈했는데 설명이 안 붙는가 -------------------------
    facts = F.build_facts(df, strategy="subject_z", baseline="low_activity")
    ev = R.apply_rules(facts)
    dev = df["dev_low_activity"].to_numpy(dtype=float)

    # 임계는 사람의 앞 절반 날짜에서만 정한다 (train). 뒤 절반이 test.
    cut = df.groupby("subject_id")["day"].transform(
        lambda s: s <= s.drop_duplicates().sort_values().iloc[len(s.drop_duplicates()) // 2])
    train = cut.to_numpy(dtype=bool)
    dev_thresh = float(np.nanquantile(dev[train], 0.80))
    tag0 = DV.explain(dev, ev, dev_thresh)
    ceil = DV.fit_cause_ceiling(dev, tag0, train_mask=train, q=0.95)
    tag = DV.explain(dev, ev, dev_thresh, ceiling=ceil)
    carried = DV.carried_forward(tag)

    print("\n[창 판정] 이탈 임계 {:.3f} (train 80분위)".format(dev_thresh))
    print(pd.Series(tag).value_counts().to_string())
    print("설명 상한:", {k: (round(v, 3) if v else None) for k, v in ceil.items()})
    print("넘어가는 창 {:,}개 ({:.1%})".format(carried.sum(), carried.mean()))

    # --- 2. 하루로 접기 ---------------------------------------------------
    day = P.daily(df, carried, min_windows=10)
    print("\n[하루로 접기] {}일 (유효 {}일)".format(len(day), int(day["valid"].sum())))
    print(day["carried_frac"].describe()[["mean", "50%", "max"]].round(3).to_string())

    day_train = day.merge(
        df.groupby(["subject_id", "day"])["subject_id"].size().rename("_n"),
        on=["subject_id", "day"], how="left")
    tr_days = set(map(tuple, df.loc[train, ["subject_id", "day"]].drop_duplicates().values))
    dmask = np.array([(r.subject_id, r.day) in tr_days for r in day.itertuples()])
    thr = P.fit_day_thresh(day, positive=None, train_mask=dmask, q=0.80)
    print("미해결일 임계 carried_frac >= {:.3f} (train 80분위)".format(thr))

    # --- 3. 사건 = 스트레스가 보고된 날 -----------------------------------
    evd = df[df["label"] == "STRESS_EVENT"][["subject_id", "day"]].drop_duplicates()
    event_days = set(map(tuple, evd.values))
    print("보고된 스트레스 날 {}일 / 유효 {}일 = 기준율 {:.1%}".format(
        len(event_days), int(day["valid"].sum()),
        len(event_days) / max(int(day["valid"].sum()), 1)))

    # --- 4. K 를 바꿔가며 경보율·탐지율 쌍 --------------------------------
    banner("K일 연속 -> 경보 : 어느 쪽으로도 공짜가 없다")
    sw = P.sweep(day, thr, ks=(1, 2, 3, 4, 5), event_days=event_days,
                 max_gap_days=2, refractory_days=7,
                 match_before=1, match_after=1)
    sw = sw.rename(columns={
        "k": "K일 연속", "n_alerts": "경보수",
        "alerts_per_person_month": "경보/인·월",
        "n_detected": "탐지", "detection_rate": "탐지율",
        "alert_precision": "경보정밀도"})
    show = sw[["K일 연속", "경보수", "경보/인·월", "탐지", "탐지율", "경보정밀도"]].round(3)
    print(show.to_string(index=False))
    print("\n관측 {:.2f} 인·월 / 사건 {}건 — 분모가 작다. 구간추정으로 읽을 것.".format(
        sw["person_months"].iloc[0], sw["n_events"].iloc[0]))

    # --- 5. 우연 수준 ------------------------------------------------------
    banner("우연 수준 대비 — 기준율 39.8% 에서 정밀도 숫자는 그냥은 못 믿는다")
    rows = []
    for k in (1, 2, 3):
        a = P.alerts(day, thr, k=k, max_gap_days=2, refractory_days=7)
        o = P.evaluate(a, event_days=event_days, match_before=1, match_after=1)
        c = P.chance_baseline(a, event_days, n_perm=2000,
                              match_before=1, match_after=1)
        rows.append({
            "K": k, "경보수": o["n_alerts"],
            "관측 정밀도": o["alert_precision"],
            "우연 정밀도": c["chance_alert_precision"],
            "p": c.get("p_precision", float("nan")),
        })
    chance = pd.DataFrame(rows).round(3)
    print(chance.to_string(index=False))
    print()
    print("우연 정밀도와 관측 정밀도가 겹치면 그 경보는 사건을 맞춘 것이 아니라")
    print("사건이 흔해서 맞은 것이다. 이 데이터에서는 그 구별이 서지 않는다.")

    # --- 6. 맥락 설명 on/off ----------------------------------------------
    banner("맥락 설명을 껐을 때와 비교 — 이것이 소거 구조의 값이다")
    naive = P.daily(df, dev > dev_thresh, min_windows=10)
    thr_n = P.fit_day_thresh(naive, positive=None, train_mask=dmask, q=0.80)
    sw_n = P.sweep(naive, thr_n, ks=(1, 2, 3), event_days=event_days,
                   max_gap_days=2, refractory_days=7,
                   match_before=1, match_after=1)
    cmp = pd.DataFrame({
        "K": [1, 2, 3],
        "끔 경보/인·월": sw_n["alerts_per_person_month"].values,
        "끔 탐지율": sw_n["detection_rate"].values,
        "켬 경보/인·월": sw["경보/인·월"].values[:3],
        "켬 탐지율": sw["탐지율"].values[:3],
    }).round(3)
    print(cmp.to_string(index=False))
    print()
    print("두 줄을 쌍으로 읽어야 한다. 경보만 줄면 성공이 아니다.")
    chance.to_csv(OUT / "tables" / "persistence_chance.csv", index=False)

    (OUT / "tables").mkdir(parents=True, exist_ok=True)
    sw.to_csv(OUT / "tables" / "persistence_sweep.csv", index=False)
    cmp.to_csv(OUT / "tables" / "persistence_context.csv", index=False)
    P.alerts(day, thr, k=3, max_gap_days=2, refractory_days=7).to_csv(
        OUT / "persistence_days.csv", index=False)
    print("\n저장: outputs/tables/persistence_sweep.csv, persistence_context.csv")


if __name__ == "__main__":
    main()
