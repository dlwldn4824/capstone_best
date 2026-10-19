"""대학생 헬스체크 지표 검증 — MCD-rPPG 100명 (운동 전 · 후 영상, 손끝 PPG 정답).

    python scripts/27_vitals.py

30초 창(앱 스캔 길이)마다 얼굴 rPPG 와 손끝 PPG 에 **같은 박동 · HRV · 스트레스 · 호흡 계산**을 돌려 비교한다.
  심박        얼굴 vs 손끝 (bpm 오차)
  HRV         RMSSD · SDNN — 상관 · 오차 (rPPG 30 Hz 의 한계가 그대로 드러나는 곳)
  스트레스     Baevsky SI 점수 — 상관 · 같은 구간(편안/보통/높음) 비율
  호흡        정답 호흡 신호가 없다 → 손끝 PPG 에서 같은 방법으로 뽑은 호흡과의 일치만 본다
  운동 효과    운동 후 > 전 (심박 ↑ · RMSSD ↓ · 스트레스 ↑) 인 사람 비율 — 앱이 '달라진 몸'을 잡는가
"""
from pathlib import Path

import numpy as np
import pandas as pd
from _bootstrap import banner, setup
from scipy.stats import spearmanr

from nesy import rppg as R
from nesy import vitals as V

ROOT = Path(__file__).resolve().parents[1]
TR = ROOT / "data/raw/mcd_rppg/traces"
OUT = ROOT / "outputs"
WIN = 30


def ppg_metrics(t, ppg, fs=30.0):
    """손끝 PPG 에 앱과 같은 박동 · HRV · 호흡 계산."""
    x = R.resample(t, ppg, fs)
    x = x - x.mean()
    hr, _ = R.hr_snr_v2(x, fs)
    y = R.bandpass(R.detrend_sp(x), fs, *R.V2_BAND_EVAL)
    y = (y - y.mean()) / (y.std() or 1)
    bt, ba = V.find_beats(y, fs, hr)
    h = V.hrv(bt)
    ok = V.clean_ibi(np.diff(bt))
    rr = V.respiration(t, np.stack([x + 100] * 3, 1), bt, ba, ok, fs)     # RIIV 자리에 PPG 기저선
    return {"hr": hr, **{k: h[k] for k in ("rmssd", "sdnn", "si")}, "stress": V.stress_score(h["si"]), "rr": rr["rr"], "ok_ratio": h["ok_ratio"]}


def main():
    setup()
    banner("헬스체크 지표 검증 (MCD-rPPG, 30초 창)")
    rows = []
    for f in sorted(TR.glob("*.npz")):
        sid, state = f.stem.split("_")
        d = np.load(f)
        ok = d["face_ok"] & np.isfinite(d["rgb"]).all(1)
        t, rgb, ppg = d["t"][ok], d["rgb"][ok], d["ppg"][ok]
        for a in range(0, int(t[-1]) - WIN + 1, WIN):
            m = (t >= a) & (t < a + WIN)
            if m.sum() < WIN * 25:
                continue
            tt = t[m] - a
            try:
                fm = V.analyze(tt, rgb[m])
                gm = ppg_metrics(tt, ppg[m])
            except Exception as e:  # noqa: BLE001
                print("건너뜀", f.stem, a, e)
                continue
            rows.append({"sid": int(sid), "state": state, "win": a, **{"f_" + k: v for k, v in fm.items()}, **{"g_" + k: v for k, v in gm.items()}})
    w = pd.DataFrame(rows)
    OUT.mkdir(exist_ok=True)
    w.to_csv(OUT / "vitals_windows.csv", index=False)
    print(f"창 {len(w)}개 · {w.sid.nunique()}명")

    res = []

    def agree(name, fcol, gcol, sub):
        s = sub[[fcol, gcol]].dropna()
        if len(s) < 10:
            return
        err = (s[fcol] - s[gcol]).abs()
        res.append({"지표": name, "창": len(s), "보고율": round(len(s) / len(sub), 2), "MAE": round(err.median() if name.startswith("RMSSD") or name.startswith("SDNN") else err.mean(), 2),
                    "Spearman": round(spearmanr(s[fcol], s[gcol])[0], 2)})

    for sig in ("all", "high"):
        sub = w if sig == "all" else w[w.f_signal == "high"]
        tag = "" if sig == "all" else " (신호 좋음)"
        agree("심박 bpm" + tag, "f_hr", "g_hr", sub)
        agree("RMSSD ms" + tag, "f_rmssd", "g_rmssd", sub)
        agree("SDNN ms" + tag, "f_sdnn", "g_sdnn", sub)
        agree("스트레스 0–100" + tag, "f_stress", "g_stress", sub)
        agree("호흡 회/분" + tag, "f_rr", "g_rr", sub)
    tab = pd.DataFrame(res)
    print(tab.to_string(index=False))

    s = w.dropna(subset=["f_stress", "g_stress"])
    zone = (s.f_stress.map(V.stress_zone) == s.g_stress.map(V.stress_zone)).mean()
    print(f"\n스트레스 구간 일치 (편안/보통/높음/매우 높음): {zone:.0%}  ({len(s)}창)")

    per = w.groupby(["sid", "state"]).agg(f_hr=("f_hr", "median"), g_hr=("g_hr", "median"), f_rmssd=("f_rmssd", "median"), g_rmssd=("g_rmssd", "median"),
                                          f_stress=("f_stress", "median"), g_stress=("g_stress", "median")).reset_index()
    pv = per.pivot(index="sid", columns="state")
    eff = []
    for k, sign, name in (("hr", 1, "심박 ↑"), ("rmssd", -1, "RMSSD ↓"), ("stress", 1, "스트레스 ↑")):
        for src, lab in (("f", "얼굴"), ("g", "손끝")):
            dd = (pv[(src + "_" + k, "after")] - pv[(src + "_" + k, "before")]).dropna()
            eff.append({"운동 후": name, "측정": lab, "사람": len(dd), "예상 방향 비율": round(float((np.sign(dd) == sign).mean()), 2), "중앙 변화": round(float(dd.median()), 1)})
    ef = pd.DataFrame(eff)
    print("\n" + ef.to_string(index=False))
    tab.to_csv(OUT / "vitals_agreement.csv", index=False)
    ef.to_csv(OUT / "vitals_exercise.csv", index=False)
    print("\n저장: outputs/vitals_*.csv")


if __name__ == "__main__":
    main()
