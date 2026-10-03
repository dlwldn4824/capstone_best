"""위험 알람 모델 v1 — 공개 데이터(Mishra 2020)로 학습하고 웹앱에 넣는다.

    python scripts/22_risk_model.py        # 20_mishra_persistence.py 가 만든 캐시를 쓴다

질문: "이 사람이 며칠 안에 아프기 시작할 확률" 을 하루 단위로 낸다.

    양성  COVID 양성자의 증상 시작 5일 전 ~ 2일 후 (조기 탐지 창)
    음성  건강군의 모든 날
    제외  COVID 양성자의 그 밖의 날 (회복기 등 애매), 기타 질병군 (라벨이 다른 병)

특징 (하루):
    서비스 모델  night_z · 최근 3일 평균 z · 최근 3일 중 이탈일 수  — 밤 심박만으로 계산된다.
                 웹앱이 지금 받는 것만 쓴다.
    비교 모델    + 걸음 z · 최근 3일 걸음 z  — Mishra 가 '걸음이 줄어든다' 고 보고한 신호

평가 (전부 사람 단위 5-fold, out-of-fold 예측):
    1. 하루 단위 AUC
    2. **건강군 경보 수를 규칙과 같게 맞췄을 때** COVID 탐지율 — 같은 경보로 더 잡는가

⚠ 사건 32건. 탐지 1건 = 0.031. 모든 차이에 신뢰구간을 붙인다.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from _bootstrap import banner, setup
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

from nesy import homekit as H, mishra as M, persistence as P

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data/cache"
OUT = ROOT / "outputs"
MODEL_OUT = ROOT / "webapp/model/risk_v1.json"
EV_KW = dict(match_before=7, match_after=3)
POS_WIN = (-5, 2)          # 증상 시작 기준 양성 창
EXCL_WIN = (-21, 28)       # 이 안의 나머지 날은 학습에서 뺀다

SERVICE = ["night_z", "z3", "dev3"]
FULL = SERVICE + ["steps_z", "steps_z3"]


def features(root):
    day = pd.read_parquet(CACHE / "mishra_day.parquet")
    night = pd.read_parquet(CACHE / "mishra_night.parquet")
    t = H.build_day_table(day, night, min_night_min=120)
    t = t.sort_values(["subject_id", "day"]).reset_index(drop=True)
    t["night_z"] = t["night_z"].clip(-5, 10)
    t["steps_valid"] = t["steps"].fillna(0) > 500
    t["steps_z"] = H.rolling_z(t, "steps", valid_col="steps_valid")
    t["steps_z"] = t["steps_z"].clip(-6, 6)
    g = t.groupby("subject_id")
    t["z3"] = g["night_z"].transform(lambda s: s.rolling(3, min_periods=1).mean())
    t["dev3"] = g["night_z"].transform(lambda s: (s >= 2).astype(float).rolling(3, min_periods=1).sum())
    t["steps_z3"] = g["steps_z"].transform(lambda s: s.rolling(3, min_periods=1).mean())
    t["category"] = t["subject_id"].map(M.load_categories(root)).fillna("unknown")
    return t


def label(t, events):
    onset = {}
    for s, d in events:
        onset.setdefault(s, []).append(d)
    y = np.full(len(t), np.nan)
    for i, r in enumerate(t.itertuples()):
        if r.category == "potential.healthy":
            y[i] = 0
        elif r.category == "COVID positive" and r.subject_id in onset:
            offs = [(r.day - e).days for e in onset[r.subject_id]]
            if any(POS_WIN[0] <= o <= POS_WIN[1] for o in offs):
                y[i] = 1
            elif not any(EXCL_WIN[0] <= o <= EXCL_WIN[1] for o in offs):
                y[i] = 0
    return y


def oof(t, feats, y, n_folds=5):
    """사람 단위 k-fold 바깥 예측. 결측 특징이 있는 날은 예측하지 않는다."""
    ok = t[feats].notna().all(axis=1).to_numpy() & t["valid"].to_numpy()
    p = np.full(len(t), np.nan)
    train = ok & np.isfinite(y)
    groups = t["subject_id"].to_numpy()
    for tr, te in GroupKFold(n_splits=n_folds).split(t, groups=groups):
        trm = np.zeros(len(t), bool); trm[tr] = True
        tem = np.zeros(len(t), bool); tem[te] = True
        fit = trm & train
        m = LogisticRegression(class_weight="balanced", max_iter=1000)
        m.fit(t.loc[fit, feats].to_numpy(), y[fit])
        pr = tem & ok
        p[pr] = m.predict_proba(t.loc[pr, feats].to_numpy())[:, 1]
    return p


def wilson(k, n, z=1.96):
    if n == 0:
        return (np.nan, np.nan)
    ph = k / n
    d = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / d
    h = z * np.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def evaluate(t, flag, events, healthy, covid, k=1, hold=None):
    """flag(하루 bool) → 경보 → 건강군 경보율 · COVID 탐지율."""
    d = t.assign(carried_frac=np.asarray(flag, float))
    a = P.alerts(d, 0.5, k=k, hold_col=hold)
    h = P.evaluate(a[a["subject_id"].isin(healthy)])
    c = P.evaluate(a[a["subject_id"].isin(covid)], event_days=events, **EV_KW)
    lo, hi = wilson(c["n_detected"], c["n_events"])
    return dict(healthy_alerts=h["n_alerts"], healthy_ppm=h["alerts_per_person_month"],
                detected=c["n_detected"], events=c["n_events"], detection=c["detection_rate"],
                ci_lo=lo, ci_hi=hi)


def match_threshold(t, p, target, events, healthy, covid, k=1):
    """건강군 경보 수가 target 에 가장 가까운 확률 임계."""
    best = None
    for thr in np.unique(np.round(np.nanquantile(p[np.isfinite(p)], np.linspace(0.80, 0.999, 200)), 4)):
        r = evaluate(t, np.nan_to_num(p) >= thr, events, healthy, covid, k=k)
        gap = abs(r["healthy_alerts"] - target)
        if best is None or gap < best[0] or (gap == best[0] and r["detection"] > best[2]["detection"]):
            best = (gap, thr, r)
    return best[1], best[2]


def main():
    setup()
    root = ROOT / "data/raw/mishra"
    banner("위험 알람 모델 v1 — Mishra 2020 으로 학습")
    t = features(root)
    events = M.load_events(root, "COVID-19")
    healthy = set(t.loc[t["category"] == "potential.healthy", "subject_id"])
    covid = set(t.loc[t["category"] == "COVID positive", "subject_id"])
    events = {e for e in events if e[0] in covid}
    y = label(t, events)
    print("학습 라벨: 양성 {} 일 / 음성 {} 일 / 사건 {} 건".format(
        int(np.nansum(y == 1)), int(np.nansum(y == 0)), len(events)))

    # --- 1. 하루 단위 AUC --------------------------------------------------------
    banner("1. 하루 단위 AUC (사람 단위 5-fold 바깥 예측)")
    p_srv = oof(t, SERVICE, y)
    p_full = oof(t, FULL, y)
    rows = []
    for name, score in [("night_z 하나 (규칙의 재료)", t["night_z"].to_numpy()),
                        ("서비스 모델 (밤 심박 3특징)", p_srv),
                        ("비교 모델 (+ 걸음)", p_full)]:
        m = np.isfinite(y) & np.isfinite(score)
        rows.append(dict(model=name, auc=roc_auc_score(y[m], score[m]), n_days=int(m.sum())))
    auc = pd.DataFrame(rows)
    print(auc.round(3).to_string(index=False))

    # --- 2. 경보 수를 맞춘 탐지율 ----------------------------------------------------
    banner("2. 건강군 경보 수를 규칙과 같게 맞췄을 때 COVID 탐지율")
    rule_t = H.crossfit_explanation(t, 2.0, H.CAUSES)
    rule = evaluate(rule_t, rule_t["carried_frac"] > 0, events, healthy, covid, k=2, hold="held")
    target = rule["healthy_alerts"]
    thr_s, srv = match_threshold(t, p_srv, target, events, healthy, covid)
    thr_f, full = match_threshold(t, p_full, target, events, healthy, covid)
    comp = pd.DataFrame([
        dict(model="규칙 (이탈·설명·2일 누적)", **rule),
        dict(model="서비스 모델 (임계 {:.3f})".format(thr_s), **srv),
        dict(model="비교 모델 + 걸음 (임계 {:.3f})".format(thr_f), **full),
    ])
    cols = ["model", "healthy_alerts", "healthy_ppm", "detected", "events", "detection", "ci_lo", "ci_hi"]
    print(comp[cols].round(3).to_string(index=False))
    print("\n  사건 {}건 — 탐지 1건 = {:.3f}. 신뢰구간이 겹치면 '차이 있다' 고 말하지 않는다.".format(
        len(events), 1 / len(events)))

    # --- 3. 서비스용 최종 모델: 전부로 학습해 웹앱에 넣는다 -------------------------------
    ok = t[SERVICE].notna().all(axis=1).to_numpy() & t["valid"].to_numpy() & np.isfinite(y)
    m = LogisticRegression(class_weight="balanced", max_iter=1000).fit(t.loc[ok, SERVICE].to_numpy(), y[ok])
    # 위험도 단계: 건강군 하루 확률 분포의 분위수로 자른다 (경보율을 직접 고르는 손잡이)
    ph = m.predict_proba(t.loc[ok & (y == 0), SERVICE].to_numpy())[:, 1]
    levels = {"watch": float(np.quantile(ph, 0.90)), "check": float(np.quantile(ph, 0.97)),
              "alert": float(thr_s)}
    model = {
        "version": "risk_v1", "trained": date.today().isoformat(),
        "data": "Mishra et al. 2020 (Nat Biomed Eng) COVID-19 Wearables — 공개",
        "features": SERVICE, "coef": m.coef_[0].tolist(), "intercept": float(m.intercept_[0]),
        "levels": levels,
        "label": "COVID 증상 시작 {}~{}일".format(*POS_WIN),
        "metrics": {
            "auc_oof": float(auc.loc[1, "auc"]), "auc_night_z": float(auc.loc[0, "auc"]),
            "detection_at_matched_alerts": float(srv["detection"]),
            "detection_ci": [float(srv["ci_lo"]), float(srv["ci_hi"])],
            "rule_detection": float(rule["detection"]),
            "healthy_alerts_per_person_month": float(srv["healthy_ppm"]),
            "events": len(events),
        },
        "caution": "사건 32건으로 학습한 시연용 모델. 진단 모델이 아니다.",
    }
    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    MODEL_OUT.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    banner("3. 서비스 모델")
    for f, c in zip(SERVICE, model["coef"]):
        print("  {:8s} 계수 {:+.3f}".format(f, c))
    print("  절편 {:+.3f}".format(model["intercept"]))
    print("  위험도 단계 (확률):", {k: round(v, 3) for k, v in levels.items()})
    print("  저장:", MODEL_OUT.relative_to(ROOT))

    OUT.mkdir(exist_ok=True)
    auc.to_csv(OUT / "risk_auc.csv", index=False)
    comp.to_csv(OUT / "risk_matched.csv", index=False)


if __name__ == "__main__":
    main()
