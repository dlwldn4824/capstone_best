"""얼굴 영상 → 심박 · 상태 분류 검증 (MCD-rPPG, 정면 웹캠).

    python scripts/23_mcd_extract.py --n 100     # 먼저
    python scripts/24_mcd_analysis.py

과제명 "Face ID 영상을 이용하여 건강상태를 분류" 의 근거 실험이다.
얼굴 심박은 webapp/static/rppg.js 와 같은 계산(src/nesy/rppg.py)으로 낸다.

1. 얼굴 심박 정확도 — 10 · 20 · 30초 창, 5초 간격, 정답 = 프레임 동기 PPG
2. 앱 얼굴 체크 그대로 — 8초 뒤 3번 연속 ±3 bpm 이면 멈춤, 최대 20초
3. 신호 품질(SNR)이 오차를 예측하나 — 앱이 SNR ≥ 0 을 요구하는 근거
4. 얼굴로 상태 분류 (안정 vs 운동 후)
     a. 사람끼리 비교 (기준선 없음) — 사람 단위 5-fold 로지스틱 회귀
     b. 같은 사람의 두 영상 비교 (개인 기준선) — 운동 후 영상을 맞히는 비율
     c. 안색(a*, 붉은 기)이 운동 후 오르나 — 사람별 짝 비교
"""
from pathlib import Path

import numpy as np
import pandas as pd
from _bootstrap import banner, setup
from scipy.stats import pearsonr, wilcoxon
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

from nesy import rppg as R

ROOT = Path(__file__).resolve().parents[1]
TR = ROOT / "data/raw/mcd_rppg/traces"
OUT = ROOT / "outputs"
SCAN_START = 0.0          # 상태 분류는 녹화 시작(=운동 직후) 20초로 본다 — 앱이 아침에 재는 길이


def load():
    vids = {}
    for f in sorted(TR.glob("*.npz")):
        sid, state = f.stem.split("_")
        d = np.load(f)
        ok = d["face_ok"] & np.isfinite(d["rgb"]).all(1)
        vids[(int(sid), state)] = (d["t"][ok], d["rgb"][ok], d["ppg"][ok], ok.mean())
    return vids


def windows(vids, lengths=(10, 20, 30), step=5):
    rows = []
    for (sid, state), (t, rgb, ppg, _) in vids.items():
        for L in lengths:
            for a in np.arange(0, t[-1] - L + 1e-9, step):
                m = (t >= a) & (t < a + L)
                if m.sum() < L * 25:
                    continue
                e, g = R.estimate(t[m], rgb[m]), R.ppg_hr(t[m], ppg[m])
                if e and g:
                    rows.append(dict(sid=sid, state=state, L=L, start=a, face=e[0], snr=e[1], truth=g[0], truth_snr=g[1]))
    w = pd.DataFrame(rows)
    w["err"] = (w["face"] - w["truth"]).abs()
    return w


def metrics(d):
    return pd.Series(dict(n=len(d), MAE=d["err"].mean(), RMSE=np.sqrt((d["err"] ** 2).mean()),
                          r=pearsonr(d["face"], d["truth"])[0] if len(d) > 2 else np.nan,
                          within5=(d["err"] <= 5).mean(), within10=(d["err"] <= 10).mean()))


def app_trials(vids, starts=(0, 30, 60, 90, 120)):
    rows = []
    for (sid, state), (t, rgb, ppg, _) in vids.items():
        for a in starts:
            if t[-1] < a + 20:
                continue
            bpm, snr, secs, early = R.app_scan(t, rgb, float(a))
            m = (t >= a) & (t < a + secs)
            g = R.ppg_hr(t[m], ppg[m])[0]
            rows.append(dict(sid=sid, state=state, start=a, face=bpm, snr=snr, secs=secs, early=early,
                             truth=g, err=abs(bpm - g)))
    return pd.DataFrame(rows)


def per_video(vids):
    rows = []
    for (sid, state), (t, rgb, ppg, okf) in vids.items():
        m = (t >= SCAN_START) & (t < SCAN_START + 20)
        e, g = R.estimate(t[m], rgb[m]), R.ppg_hr(t[m], ppg[m])
        L, a, b = R.to_lab(rgb[m].mean(0))
        rows.append(dict(sid=sid, state=state, after=int(state == "after"), face_hr=e[0], snr=e[1],
                         truth_hr=g[0], L=float(L), a=float(a), b=float(b), face_ok=okf))
    return pd.DataFrame(rows)


def cv_auc(df, feats):
    X, y, g = df[feats].to_numpy(), df["after"].to_numpy(), df["sid"].to_numpy()
    p = np.zeros(len(df))
    for tr, te in GroupKFold(5).split(X, y, g):
        m = LogisticRegression(max_iter=1000).fit(X[tr], y[tr])
        p[te] = m.predict_proba(X[te])[:, 1]
    return roc_auc_score(y, p)


def paired(df, col):
    w = df.pivot(index="sid", columns="state", values=col).dropna()
    diff = w["after"] - w["before"]
    acc = (diff > 0).mean() + 0.5 * (diff == 0).mean()
    p = wilcoxon(diff).pvalue if len(diff) > 5 else np.nan
    return dict(n=len(diff), correct=float(acc), median_diff=float(diff.median()), p=float(p))


def main():
    setup()
    banner("얼굴 영상 → 심박 · 상태 분류 (MCD-rPPG 정면 웹캠)")
    vids = load()
    n_sub = len({k[0] for k in vids})
    print(f"영상 {len(vids)}개 · {n_sub}명 · 얼굴 검출률 중앙 {np.median([v[3] for v in vids.values()]):.1%}")

    # 1. 정확도
    banner("1. 얼굴 심박 정확도 (정답: 프레임 동기 PPG)")
    w = windows(vids)
    acc = w.groupby(["L", "state"]).apply(metrics).round(3)
    print(acc.to_string())
    allL = w.groupby("L").apply(metrics).round(3)
    print("\n전체:\n" + allL.to_string())

    # 3. SNR
    banner("3. 신호 품질(SNR)이 오차를 예측하나 — 20초 창")
    w20 = w[w["L"] == 20].copy()
    w20["snr_band"] = pd.cut(w20["snr"], [-99, -2, 0, 2, 4, 99], labels=["<-2", "-2~0", "0~2", "2~4", "≥4"])
    snr_tab = w20.groupby("snr_band", observed=True).apply(metrics)[["n", "MAE", "within5"]].round(3)
    print(snr_tab.to_string())

    # 2. 앱 그대로
    banner("2. 앱 얼굴 체크 그대로 (8초 뒤 ±3 bpm 3번 연속이면 멈춤, 최대 20초)")
    app = app_trials(vids)
    summ = pd.Series(dict(trials=len(app), early_stop=app["early"].mean(), median_secs=app["secs"].median(),
                          MAE_all=app["err"].mean(), within5_all=(app["err"] <= 5).mean(),
                          MAE_early=app.loc[app["early"], "err"].mean(),
                          within5_early=(app.loc[app["early"], "err"] <= 5).mean(),
                          MAE_not_early=app.loc[~app["early"], "err"].mean()))
    print(summ.round(3).to_string())

    # 4. 상태 분류
    banner("4. 얼굴로 안정 vs 운동 후 분류 (녹화 시작 20초)")
    pv = per_video(vids)
    pv = pv[pv.groupby("sid")["state"].transform("nunique") == 2]
    rows = []
    for name, feats in [("얼굴 심박", ["face_hr"]), ("안색 a*", ["a"]), ("얼굴 심박 + 안색", ["face_hr", "a", "L"]),
                        ("(정답 PPG 심박)", ["truth_hr"])]:
        rows.append(dict(model=name, population_auc=cv_auc(pv, feats)))
    cls = pd.DataFrame(rows)
    cls["personal_correct"] = [paired(pv, "face_hr")["correct"], paired(pv, "a")["correct"], np.nan,
                               paired(pv, "truth_hr")["correct"]]
    print(cls.round(3).to_string(index=False))
    print("\n  population = 사람끼리 비교 (사람 단위 5-fold AUC)")
    print("  personal   = 같은 사람의 두 영상 중 운동 후를 맞힌 비율 (개인 기준선)")
    pa = {c: paired(pv, c) for c in ["face_hr", "truth_hr", "a", "L"]}
    print("\n  짝 비교:", {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in pa.items()})

    OUT.mkdir(exist_ok=True)
    acc.to_csv(OUT / "mcd_accuracy.csv")
    snr_tab.to_csv(OUT / "mcd_snr.csv")
    app.to_csv(OUT / "mcd_app_scan.csv", index=False)
    cls.to_csv(OUT / "mcd_state.csv", index=False)
    pv.to_csv(OUT / "mcd_per_video.csv", index=False)
    print("\n저장: outputs/mcd_*.csv")


if __name__ == "__main__":
    main()
