"""안색 다시 재기 — 보정 안 한 a* vs 볼−이마 보정 a* (MCD-rPPG).

    python3 research/scripts/29_complexion_corrected.py

24_mcd_analysis.py 는 얼굴 전체 평균 RGB 를 그대로 Lab 으로 바꿔 a* 를 썼다(86줄).
그 값으로는 운동 전후를 52% 밖에 못 맞혔다 (p = 0.71).

여기서는 같은 데이터에 **같은 프레임 안 보정**을 걸고 다시 본다.
    corrected a* = 볼 a* − 이마 a*
두 영역은 같은 렌즈 · 같은 ISP · 같은 프레임을 지나므로 기기가 입히는 색 변환과
그 순간의 조명 · 화이트밸런스가 뺄셈에서 상쇄된다 (legacy/webapp_v1 의 rppg2.js complexion 과 같은 식).

재는 것
  1. 같은 영상 안 흔들림 — 20초 구간끼리 a* 의 sd (작을수록 좋다)
  2. 운동 전후 개인 짝 비교 — 같은 사람의 before ↔ after, 이항검정
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nesy import rppg as R          # noqa: E402

TR = ROOT / "data/raw/mcd_rppg/traces"
WIN = 20.0          # 구간 길이 (초)
STEP = 10.0


def a_star(rgb):
    """rgb[..., 3] → a* (붉은 기)."""
    _, a, _ = R.to_lab(np.asarray(rgb, float))
    return a


def windows_of(d):
    """한 영상 → 구간마다 (원 a*, 보정 a*)."""
    ok = d["face_ok"] & np.isfinite(d["rgb"]).all(1) & np.isfinite(d["roi"]).all((1, 2))
    t, rgb, roi = d["t"][ok], d["rgb"][ok], d["roi"][ok]
    if len(t) < WIN * 25:
        return []
    out = []
    for s in np.arange(0, t[-1] - WIN + 1e-9, STEP):
        m = (t >= s) & (t < s + WIN)
        if m.sum() < WIN * 25:
            continue
        raw = a_star(rgb[m].mean(0))
        fh = a_star(roi[m, 0].mean(0))                     # 이마
        ck = a_star(roi[m, 1:].mean(1).mean(0))            # 양 볼 평균
        out.append((float(raw), float(ck - fh)))
    return out


def binom_p(k, n):
    """양측 이항검정 p (p0 = 0.5)."""
    from math import comb
    tail = sum(comb(n, i) for i in range(0, min(k, n - k) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def main():
    subj = {}
    for f in sorted(TR.glob("*.npz")):
        sid, state = f.stem.split("_")
        w = windows_of(np.load(f))
        if w:
            subj.setdefault(sid, {})[state] = np.array(w)      # [구간, (원, 보정)]

    pairs = {s: v for s, v in subj.items() if "before" in v and "after" in v}
    print(f"사람 {len(pairs)}명 · 구간 {sum(len(v['before']) + len(v['after']) for v in pairs.values())}개 "
          f"(창 {WIN:.0f}초, {STEP:.0f}초 간격)\n")

    # 1. 같은 영상 안 흔들림
    print("1. 같은 영상 안, 20초 구간끼리 흔들림 (sd 중앙값)")
    for j, name in [(0, "원 a* (얼굴 평균)"), (1, "보정 a* (볼 − 이마)")]:
        sds = [v[st][:, j].std(ddof=1) for v in pairs.values() for st in ("before", "after")
               if len(v[st]) > 1]
        print(f"   {name:22s} {np.median(sds):.3f}")

    # 2. 운동 전후 개인 짝 비교
    print("\n2. 같은 사람 before ↔ after — 운동 후 a* 가 올랐나")
    for j, name in [(0, "원 a* (얼굴 평균)"), (1, "보정 a* (볼 − 이마)")]:
        diffs, up = [], 0
        for v in pairs.values():
            d = np.median(v["after"][:, j]) - np.median(v["before"][:, j])
            diffs.append(d)
            up += d > 0
        n = len(diffs)
        print(f"   {name:22s} {up}/{n}명 상승 ({up / n * 100:.0f}%) · "
              f"중앙 Δ {np.median(diffs):+.3f} · p = {binom_p(up, n):.3f}")

    print("\n(참고) 24_mcd_analysis.py 의 100명 결과: 원 a* 52% · p = 0.71")


main()
