"""지속성 계층 — 창(window) 판정을 사람이 받는 알림으로 바꾼다.

앞 단계까지는 창 하나하나에 대해 "설명되나?" 를 답했다. 그것을 그대로
알리면 하루에도 수십 번 울린다. 실제 서비스는 **하루를 하나로 접고,
그것이 며칠 이어질 때만** 알린다.

설계에서 지킨 것 네 가지.

1. **하루 단위로 접는다.** 창 수가 사람마다 크게 다르므로 개수가 아니라
   비율(carried_frac)로 접는다.
2. **연속은 관측일 기준이되 달력 공백에 한도를 둔다.** 밴드를 2주 벗었다가
   다시 찬 이틀을 "3일 연속" 으로 세면 안 된다.
3. **경보 뒤 불응기를 둔다.** 없으면 긴 이탈 구간 하나가 매일 경보를 내서
   경보율이 부풀려진다.
4. **경보율과 탐지율을 반드시 함께 낸다.** 경보율만 보면 아무것도 안 하는
   시스템이 1등이다. 기준율 없는 경보율은 의미가 없다.

담당: 역할 C
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DAYS_PER_MONTH = 30.4375


def day_index(t_start, tz="America/Chicago"):
    """epoch 초 -> 현지 날짜. 하루 경계는 현지 기준이어야 한다."""
    ts = pd.to_datetime(pd.Series(t_start), unit="s", utc=True)
    return ts.dt.tz_convert(tz).dt.normalize().dt.tz_localize(None)


def daily(df, carried, subject_col="subject_id", day_col="day",
          min_windows=10):
    """창 판정을 (사람, 날) 단위로 접는다.

    carried    창별 bool — 설명으로 닫히지 않고 넘어가는 창
               (deviation.carried_forward() 출력)
    min_windows 그날 창이 이보다 적으면 판정하지 않는다 (착용이 너무 짧음).
               버리지 않고 valid=False 로 남긴다 — 분모에서 빼야 하기 때문이다.
    """
    d = pd.DataFrame({
        subject_col: np.asarray(df[subject_col]),
        day_col: np.asarray(df[day_col]),
        "carried": np.asarray(carried, dtype=bool),
    })
    g = d.groupby([subject_col, day_col], as_index=False).agg(
        n_windows=("carried", "size"),
        n_carried=("carried", "sum"),
    )
    g["carried_frac"] = g["n_carried"] / g["n_windows"]
    g["valid"] = g["n_windows"] >= min_windows
    return g.sort_values([subject_col, day_col]).reset_index(drop=True)


def fit_day_thresh(day_df, positive, train_mask=None, q=0.90):
    """'그날은 미해결이다' 로 볼 carried_frac 임계.

    라벨이 없으면(positive=None) 학습 구간 분위수로 정한다 — 상위 (1-q) 만
    미해결로 본다. 라벨이 있으면 Youden J 로 정한다.
    어느 쪽이든 **train_mask 안에서만** 본다. 임계값 누수는 이미 한 번 밟았다.
    """
    frac = day_df["carried_frac"].to_numpy(dtype=float)
    ok = day_df["valid"].to_numpy(dtype=bool)
    if train_mask is None:
        train_mask = np.ones(len(day_df), dtype=bool)
    sel = np.asarray(train_mask, dtype=bool) & ok & np.isfinite(frac)
    if sel.sum() < 10:
        return float("nan")
    if positive is None:
        return float(np.quantile(frac[sel], q))

    pos = np.asarray(positive, dtype=bool)[sel]
    x = frac[sel]
    if pos.all() or not pos.any():
        return float(np.quantile(x, q))
    best, best_j = float(np.quantile(x, q)), -np.inf
    for thr in np.unique(x):
        tpr = (x[pos] >= thr).mean()
        fpr = (x[~pos] >= thr).mean()
        if tpr - fpr > best_j:
            best_j, best = tpr - fpr, float(thr)
    return best


def alerts(day_df, thresh, k=3, max_gap_days=2, refractory_days=7,
           subject_col="subject_id", day_col="day"):
    """K일 연속 미해결이면 경보. 사람별로 독립 실행한다.

    반환: day_df 사본 + unresolved / run_len / alert 열.

    max_gap_days   이 날짜 이상 벌어지면 연속이 끊긴다 (미착용 구간)
    refractory_days 경보 뒤 이 기간 동안은 다시 울리지 않는다
    """
    d = day_df.copy().sort_values([subject_col, day_col]).reset_index(drop=True)
    d["unresolved"] = d["valid"] & (d["carried_frac"] >= thresh)
    d["run_len"] = 0
    d["alert"] = False

    for _, idx in d.groupby(subject_col).groups.items():
        idx = list(idx)
        run = 0
        prev_day = None
        last_alert = None
        for i in idx:
            day = d.at[i, day_col]
            gap = None if prev_day is None else (day - prev_day).days
            # 관측 공백이 크면 이전 기록과 이어붙이지 않는다
            if gap is not None and gap > max_gap_days:
                run = 0
            if not d.at[i, "valid"]:
                # 착용이 짧은 날은 끊지도 잇지도 않는다. 판단을 보류한다.
                prev_day = day
                continue
            run = run + 1 if d.at[i, "unresolved"] else 0
            d.at[i, "run_len"] = run
            if run >= k:
                fresh = last_alert is None or (day - last_alert).days >= refractory_days
                if fresh:
                    d.at[i, "alert"] = True
                    last_alert = day
            prev_day = day
    return d


def evaluate(day_df, event_days=None, match_before=1, match_after=1,
             subject_col="subject_id", day_col="day"):
    """경보율과 탐지율을 **쌍으로** 낸다. 하나만 보면 반드시 오독된다.

    event_days  (subject, day) 튜플 집합 — 실제로 있었던 사건.
                None 이면 탐지율은 계산하지 않고 경보율만 낸다.
    match_before/after  경보가 사건보다 며칠 앞/뒤까지 맞은 것으로 볼지.
                조기 탐지가 목적이므로 앞쪽을 넉넉히 잡는 것이 보통이다.
    """
    valid = day_df[day_df["valid"]]
    n_days = len(valid)
    n_alert = int(valid["alert"].sum())
    out = {
        "observed_days": n_days,
        "person_months": n_days / DAYS_PER_MONTH,
        "n_alerts": n_alert,
        "alerts_per_person_month": n_alert / (n_days / DAYS_PER_MONTH) if n_days else float("nan"),
    }
    if event_days is None:
        return out

    ev = set(event_days)
    alert_set = {(r[subject_col], r[day_col])
                 for _, r in valid[valid["alert"]].iterrows()}
    hit = 0
    for subj, eday in ev:
        for off in range(-match_before, match_after + 1):
            if (subj, eday + pd.Timedelta(days=off)) in alert_set:
                hit += 1
                break
    matched = 0
    for subj, aday in alert_set:
        for off in range(-match_after, match_before + 1):
            if (subj, aday + pd.Timedelta(days=off)) in ev:
                matched += 1
                break
    out.update({
        "n_events": len(ev),
        "n_detected": hit,
        "detection_rate": hit / len(ev) if ev else float("nan"),
        "alert_precision": matched / n_alert if n_alert else float("nan"),
    })
    return out


def sweep(day_df, thresh, ks=(1, 2, 3, 4, 5), event_days=None, **kw):
    """K 를 바꿔가며 (경보율, 탐지율) 곡선을 낸다.

    K 를 키우면 경보는 줄고 탐지도 준다. **어느 쪽으로도 공짜가 없다**는 것을
    보여주는 표이며, 이것이 지속성 계층의 유일한 정직한 보고 형태다.
    """
    ev_kw = {k: kw.pop(k) for k in ("match_before", "match_after") if k in kw}
    rows = []
    for k in ks:
        d = alerts(day_df, thresh, k=k, **kw)
        r = evaluate(d, event_days=event_days, **ev_kw)
        r["k"] = k
        rows.append(r)
    cols = ["k"] + [c for c in rows[0] if c != "k"]
    return pd.DataFrame(rows)[cols]


def chance_baseline(day_df, event_days, n_perm=2000, seed=0,
                    subject_col="subject_id", day_col="day", **ev_kw):
    """경보일을 사람 안에서 섞어 **우연 수준**을 잰다.

    사건 기준율이 높으면(Nurse 는 관측일의 40%가 사건일이다) 아무 날에나
    울려도 정밀도가 높게 나온다. 그 수준을 넘는지 보지 않으면
    "정밀도 1.0" 같은 숫자를 그대로 믿게 된다.

    사람별 경보 개수를 보존한 채 날짜만 섞으므로, 귀무가설은
    "이 사람이 이만큼 울리기는 하는데 날짜는 무작위" 이다.
    """
    rng = np.random.default_rng(seed)
    valid = day_df[day_df["valid"]].reset_index(drop=True)
    if not valid["alert"].any():
        return {"chance_detection_rate": float("nan"),
                "chance_alert_precision": float("nan"), "p_detection": float("nan")}

    obs = evaluate(valid, event_days=event_days, subject_col=subject_col,
                   day_col=day_col, **ev_kw)
    det, prec = [], []
    idx_by_subj = {s: g.index.to_numpy() for s, g in valid.groupby(subject_col)}
    n_by_subj = valid.groupby(subject_col)["alert"].sum().to_dict()

    for _ in range(n_perm):
        shuffled = valid.copy()
        shuffled["alert"] = False
        for s, idx in idx_by_subj.items():
            k = int(n_by_subj.get(s, 0))
            if k:
                shuffled.loc[rng.choice(idx, size=k, replace=False), "alert"] = True
        r = evaluate(shuffled, event_days=event_days, subject_col=subject_col,
                     day_col=day_col, **ev_kw)
        det.append(r["detection_rate"])
        prec.append(r["alert_precision"])

    det = np.array(det, dtype=float)
    prec = np.array(prec, dtype=float)
    return {
        "chance_detection_rate": float(np.nanmean(det)),
        "chance_alert_precision": float(np.nanmean(prec)),
        "p_detection": float((det >= obs["detection_rate"]).mean()),
        "p_precision": float((prec >= obs["alert_precision"]).mean()),
    }
