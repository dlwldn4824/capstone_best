"""안색 지표 비교 — 기획 변경 보고서 FR-07 · 10장 '안색 지표 정의' (MCD-rPPG 60명).

    python scripts/23_mcd_extract.py --n 60 --out traces_roi    # 이마 · 볼을 따로 남긴 추출
    python scripts/26_complexion.py

후보 (src/nesy/rppg.py complexion):
    a_cheek  볼 a* 절대값           — 지금까지 쓴 것 (조명에 그대로 흔들림)
    a_rel    볼 a* − 이마 a*         — 보고서 주 지표 (같은 프레임 안의 차이)
    s_rel    HSV 채도 볼 − 이마      — 보고서 대안
    rg_rel   R/G 볼 − 이마           — 보고서 대안

좋은 지표의 조건:
  1. 같은 영상(3분) 안에서 덜 흔들린다 — 측정 잡음 (20초 구간 중앙값끼리 sd)
  2. 밝기 변화와 따라 움직이지 않는다 — 조명 영향 (같은 영상 안 20초 구간끼리, 지표와 L* 상관)
  3. 운동 전후 차이가 잡음보다 크다   — 신호 대 잡음 (|운동 후 − 안정| 중앙값 / 영상 안 sd)
운동 후 붉어짐은 음주 붉어짐의 대리 신호다 (둘 다 피부 혈관 확장). 음주 자체 데이터는 없다.
"""
from pathlib import Path

import numpy as np
import pandas as pd
from _bootstrap import banner, setup
from scipy.stats import spearmanr, wilcoxon

from nesy import rppg as R

ROOT = Path(__file__).resolve().parents[1]
TR = ROOT / "data/raw/mcd_rppg/traces_roi"
OUT = ROOT / "outputs"
SEG = 20
KEYS = ["a_cheek", "a_rel", "s_rel", "rg_rel"]


def main():
    setup()
    banner("안색 지표 비교 (MCD-rPPG, 이마 · 볼 따로)")
    vids, segs = [], []
    for f in sorted(TR.glob("*.npz")):
        sid, state = f.stem.split("_")
        d = np.load(f)
        roi = d["roi"]                       # (N, 3 영역, RGB) — 이마 · 왼볼 · 오른볼
        ok = d["face_ok"] & np.isfinite(roi).all((1, 2))
        t, roi = d["t"][ok], roi[ok]
        fh, ck = roi[:, 0], roi[:, 1:].mean(1)
        whole = R.complexion(fh, ck)
        L = float(np.median(R.to_lab(np.concatenate([fh, ck]))[0]))
        vids.append(dict(sid=int(sid), state=state, L=L, **whole))
        for a in range(0, int(t[-1]) - SEG + 1, SEG):
            m = (t >= a) & (t < a + SEG)
            if m.sum() < SEG * 20:
                continue
            c = R.complexion(fh[m], ck[m])
            segs.append(dict(sid=int(sid), state=state, seg=a,
                             L=float(np.median(R.to_lab(np.concatenate([fh[m], ck[m]]))[0])), **c))
    v, s = pd.DataFrame(vids), pd.DataFrame(segs)
    print(f"영상 {len(v)}개 · {v.sid.nunique()}명 · 20초 구간 {len(s)}개")

    rows = []
    for k in KEYS:
        within = s.groupby(["sid", "state"])[k].std().median()                     # 1. 영상 안 흔들림
        rho = s.groupby(["sid", "state"]).apply(lambda g: spearmanr(g["L"], g[k])[0]).median()   # 2. 밝기 추종
        w = v.pivot(index="sid", columns="state", values=k).dropna()
        diff = w["after"] - w["before"]
        rows.append(dict(index=k, within_sd=within, light_rho=rho,
                         between_person_sd=v[v.state == "before"][k].std(),
                         effect_median=diff.median(), up_after=(diff > 0).mean(),
                         p=wilcoxon(diff).pvalue, effect_over_noise=diff.abs().median() / within))
    tab = pd.DataFrame(rows)
    print(tab.round(3).to_string(index=False))
    print("\n  within_sd          같은 영상 안 20초 구간끼리 흔들림 (작을수록 좋다) — 지표마다 단위가 달라 비율로 비교")
    print("  light_rho          같은 영상 안에서 밝기(L*)와 지표의 상관 (0 에 가까울수록 조명에 덜 끌려간다)")
    print("  effect_over_noise  |운동 후 − 안정| 중앙값 ÷ 영상 안 흔들림 (1 보다 커야 변화가 잡음 위로 보인다)")

    OUT.mkdir(exist_ok=True)
    tab.to_csv(OUT / "complexion_indices.csv", index=False)
    v.to_csv(OUT / "complexion_per_video.csv", index=False)
    print("\n저장: outputs/complexion_*.csv")


if __name__ == "__main__":
    main()
