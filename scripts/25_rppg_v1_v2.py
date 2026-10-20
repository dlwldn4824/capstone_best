"""얼굴 심박 계산 v1(지금 앱) vs v2(rPPG-Toolbox 와 같은 처리 순서) — MCD-rPPG 100명.

    python scripts/25_rppg_v1_v2.py

같은 얼굴 색 신호(scripts/23 으로 뽑은 것)에 두 계산을 돌려 정답 PPG 와 비교한다.
정답 심박은 두 경우 모두 같은 v2 평가 단계로 낸다 (rPPG-Toolbox 가 정답 신호에 하는 그대로).
"""
from pathlib import Path

import numpy as np
import pandas as pd
from _bootstrap import banner, setup

from nesy import rppg as R

ROOT = Path(__file__).resolve().parents[1]
TR = ROOT / "data/raw/mcd_rppg/traces"
OUT = ROOT / "outputs"
L, STEP = 20, 10


def main():
    setup()
    banner("얼굴 심박 v1 vs v2 (20초 창, 10초 간격)")
    rows = []
    for f in sorted(TR.glob("*.npz")):
        sid, state = f.stem.split("_")
        d = np.load(f)
        ok = d["face_ok"] & np.isfinite(d["rgb"]).all(1)
        t, rgb, ppg = d["t"][ok], d["rgb"][ok], d["ppg"][ok]
        for a in np.arange(0, t[-1] - L + 1e-9, STEP):
            m = (t >= a) & (t < a + L)
            if m.sum() < L * 25:
                continue
            g = R.ppg_hr_v2(t[m], ppg[m])
            e1, e2 = R.estimate(t[m], rgb[m]), R.estimate_v2(t[m], rgb[m])
            if g and e1 and e2:
                rows.append(dict(sid=int(sid), state=state, start=a, truth=g[0], truth_snr=g[1],
                                 v1=e1[0], v1_snr=e1[1], v2=e2[0], v2_snr=e2[1]))
    w = pd.DataFrame(rows)
    for v in ("v1", "v2"):
        w[v + "_err"] = (w[v] - w["truth"]).abs()

    def summ(err):
        return pd.Series(dict(MAE=err.mean(), RMSE=np.sqrt((err ** 2).mean()), within5=(err <= 5).mean()))

    tab = pd.DataFrame({v: summ(w[v + "_err"]) for v in ("v1", "v2")}).T
    tab.insert(0, "n", len(w))
    print(tab.round(3).to_string())

    banner("품질(SNR) 기준을 통과한 창만 쓸 때 — 통과율과 정확도")
    rows = []
    for v in ("v1", "v2"):
        for thr in (-99, 0, 2, 4, 6):
            m = w[v + "_snr"] >= thr
            e = w.loc[m, v + "_err"]
            rows.append(dict(method=v, snr_min=thr, pass_rate=m.mean(), MAE=e.mean(), within5=(e <= 5).mean()))
    gate = pd.DataFrame(rows)
    print(gate.round(3).to_string(index=False))

    OUT.mkdir(exist_ok=True)
    tab.to_csv(OUT / "rppg_v1_v2.csv")
    gate.to_csv(OUT / "rppg_v1_v2_gate.csv", index=False)
    w.to_csv(OUT / "rppg_v1_v2_windows.csv", index=False)
    print("\n저장: outputs/rppg_v1_v2*.csv")


if __name__ == "__main__":
    main()
