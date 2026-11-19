"""보고서 '성능' 절 그림 — 30초를 통째로 버리지 않고 깨끗한 구간만 살린다 (MCD-rPPG 실측).

    python3 docs/presentation/report/make_fig_window.py

research/scripts/31_find_window_case.py 가 찾은 실제 사례 하나를 그린다.
전체 30초로 보면 품질 기준에 떨어져 값을 못 내지만, 15초 구간을 5초 간격으로 훑으면
통과하는 구간이 있고 그중 서로 합의하는 것을 골라 값을 살린다 (webapp/face bestWindow).
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
import numpy as np                       # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "research" / "src"))
from nesy import rppg as R               # noqa: E402

OUT = HERE / "fig"
TR = REPO / "research/data/raw/mcd_rppg/traces"
FACE = REPO / "webapp" / "face"

PICK = dict(sid="1259", state="after", start=15.0, length=30.0)

INK, BLUE, GRAY, LINE, RED = "#0B0F17", "#1D4ED8", "#5B6472", "#D9DEE7", "#D2452F"
for fam in ("AppleGothic", "Apple SD Gothic Neo", "Malgun Gothic", "NanumGothic"):
    try:
        matplotlib.font_manager.findfont(fam, fallback_to_default=False); FONT = fam; break
    except Exception:
        continue
else:
    FONT = "DejaVu Sans"
plt.rcParams.update({
    "font.family": FONT, "font.size": 14, "axes.edgecolor": INK, "axes.labelcolor": INK,
    "xtick.color": INK, "ytick.color": INK, "axes.spines.top": False, "axes.spines.right": False,
    "axes.linewidth": 1.1, "savefig.dpi": 200, "axes.unicode_minus": False,
})

REASON = {"snr": "맥박 신호가 약함", "motion": "머리 이동", "blink": "깜빡임·말하기",
          "brightness": "밝기", "coverage": "얼굴 놓침", "interference": "간섭",
          "roi": "세 영역 불일치", "short": "길이 부족"}


def load():
    d = np.load(TR / f"{PICK['sid']}_{PICK['state']}.npz")
    ok = d["face_ok"] & np.isfinite(d["rgb"]).all(1) & np.isfinite(d["roi"]).all((1, 2))
    t, roi, ppg = d["t"][ok], d["roi"][ok], d["ppg"][ok]
    a, L = PICK["start"], PICK["length"]
    m = (t >= a) & (t < a + L)
    return t[m], roi[m], ppg[m]


def engine(t, roi, retry):
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "w.json"
        p.write_text(json.dumps({"key": "fig", "t": np.round(t - t[0], 4).tolist(),
                                 "roi": np.round(roi, 3).tolist()}))
        env = {**os.environ}
        if not retry:
            env["RETRY"] = "off"
        r = subprocess.run(["node", "scripts/eval/dump_window.mjs", str(p)],
                           cwd=FACE, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        sys.exit(f"node 실패:\n{r.stderr[-1500:]}")
    return json.loads(r.stdout)


def main():
    t, roi, ppg = load()
    whole = engine(t, roi, retry=False)     # 구간 선택을 끈 '전체' 판정
    saved = engine(t, roi, retry=True)      # 앱이 실제로 내는 값
    truth, _ = R.ppg_hr_v2(t, ppg)
    fs = whole["fs"]
    pulse = np.asarray(whole["pulse"], float)
    tt = np.arange(len(pulse)) / fs
    wins = whole["windows"]
    sel = saved.get("window") or {}
    s0, s1 = sel.get("startSec"), sel.get("endSec")

    fig = plt.figure(figsize=(10.4, 7.6))
    gs = fig.add_gridspec(2, 1, height_ratios=[1.25, 1], hspace=0.70,
                          top=0.885, bottom=0.235, left=0.105, right=0.975)

    # 위 — 30초 맥파와 고른 구간
    ax = fig.add_subplot(gs[0])
    if s0 is not None:
        ax.axvspan(s0, s1, color=BLUE, alpha=0.12, lw=0, zorder=0)
    ax.plot(tt, pulse, color=GRAY, lw=1.4, alpha=0.65)
    if s0 is not None:
        m = (tt >= s0) & (tt <= s1)
        ax.plot(tt[m], pulse[m], color=BLUE, lw=2.0)
        ax.annotate(f"살린 구간  {s0:.0f}–{s1:.0f}초", xy=((s0 + s1) / 2, ax.get_ylim()[1] * 0.86),
                    ha="center", fontsize=13, weight="bold", color=BLUE)
    ax.set_xlim(0, tt[-1]); ax.set_yticks([]); ax.spines["left"].set_visible(False)
    ax.set_xlabel("시간 (초)", labelpad=2)
    ax.set_title("30초 전체를 버리지 않고, 깨끗한 구간만 살린다", fontsize=16, loc="left", pad=10)

    # 아래 — 구간별 신호 세기
    ax2 = fig.add_subplot(gs[1])
    xs = [(w["start"] + w["end"]) / 2 for w in wins]
    ys = [w["snr"] for w in wins]
    chosen = [s0 is not None and abs(w["start"] - s0) < 0.51 for w in wins]
    cols = [BLUE if ch else (BLUE if w["pass"] else LINE) for ch, w in zip(chosen, wins)]
    alphas = [1.0 if ch else (0.38 if w["pass"] else 1.0) for ch, w in zip(chosen, wins)]
    for x, y, c, al in zip(xs, ys, cols, alphas):
        ax2.bar([x], [y], width=3.6, color=c, alpha=al, edgecolor=INK, linewidth=0.8)
    lo, hi = min(ys + [-3.6]) - 1.6, max(ys) + 2.0
    ax2.set_ylim(lo, hi)
    ax2.axhline(-3, color=RED, lw=1.2, ls="--")
    ax2.annotate("품질 기준 -3 dB", xy=(tt[-1] * 0.985, -3), ha="right", va="bottom",
                 fontsize=11.5, color=RED)
    for w, x, y in zip(wins, xs, ys):
        ax2.annotate(f"{w['bpm']:.0f} bpm", xy=(x, y + 0.35), ha="center", va="bottom",
                     fontsize=12, weight="bold" if w["pass"] else "normal",
                     color=INK if w["pass"] else GRAY)
    ax2.set_xlim(-1.5, tt[-1] + 1.5); ax2.set_xlabel("구간의 가운데 시각 (초)", labelpad=2)
    ax2.set_ylabel("신호 세기 (dB)", labelpad=4)
    ax2.set_title("15초 구간을 5초 간격으로 훑어 본 결과 · 숫자는 그 구간이 낸 심박",
                  fontsize=14, loc="left", pad=8)

    wr = REASON.get(whole.get("reason"), whole.get("reason") or "품질 미달")
    fig.text(0.105, 0.145,
             f"전체 30초로 보면 품질에 떨어진다 — 이유: {wr}, 신호 세기 {whole['snrDb']:.1f} dB.\n"
             f"예전에는 여기서 값을 버리고 처음부터 다시 재게 했다. 뒤 절반이 망가지면 앞 15초도 같이 버려졌다.\n"
             f"지금은 통과한 구간 중 서로 ±3 bpm 안에서 합의하는 것을 골라 {saved['bpm']:.1f} bpm 을 낸다.\n"
             f"같은 시각 손끝 센서는 {truth:.1f} bpm 이었다 (오차 {abs(saved['bpm']-truth):.2f} bpm).",
             fontsize=12.5, color=GRAY, va="top", linespacing=1.75)

    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / "perf_window.png"); plt.close(fig)
    print(f"전체: {whole['bpm']:.2f} bpm · pass={whole['pass']} · 이유={whole.get('reason')} · SNR {whole['snrDb']:.2f}")
    print(f"구간 선택: {saved['bpm']:.2f} bpm · 고른 구간 {s0}–{s1} · 정답 {truth:.2f} bpm")
    print(f"구간 {len(wins)}개: " + ", ".join(f"{w['start']:.0f}-{w['end']:.0f}s {w['bpm']:.1f}bpm "
          f"{w['snr']:.1f}dB {'통과' if w['pass'] else (w['reason'] or '미달')}" for w in wins))
    print("→", OUT / "perf_window.png")


main()
