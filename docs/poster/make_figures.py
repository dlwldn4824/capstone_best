"""포스터 그림 — 전부 우리 실험 결과(outputs/, data/raw/mcd_rppg)에서 그린다.

    python docs/poster/make_figures.py
"""
import datetime as dt
import sys
import tempfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "webapp"))
from nesy import rppg as R  # noqa: E402

OUT = Path(__file__).resolve().parent / "fig"
INK, BLUE, BLUE_L, GREY, LINE = "#0B0F17", "#1D4ED8", "#9DB4F0", "#5B6472", "#D9DEE7"
plt.rcParams.update({
    "font.family": "Malgun Gothic", "font.size": 15, "axes.edgecolor": INK, "axes.labelcolor": INK,
    "xtick.color": INK, "ytick.color": INK, "axes.spines.top": False, "axes.spines.right": False,
    "axes.linewidth": 1.2, "savefig.dpi": 220, "savefig.bbox": "tight", "axes.unicode_minus": False,
})


def fig_pipeline():
    """한 사람 20초: 얼굴 G 채널 → POS 맥파(정답 PPG 와 겹침) → 스펙트럼 최고점."""
    d = np.load(ROOT / "data/raw/mcd_rppg/traces/1020_before.npz")
    ok = d["face_ok"] & np.isfinite(d["rgb"]).all(1)
    t, rgb, ppg = d["t"][ok], d["rgb"][ok], d["ppg"][ok]
    m = (t >= 60) & (t < 80)
    t, rgb, ppg = t[m] - 60, rgb[m], ppg[m]
    fs = 30
    r = R.resample(t, rgb, fs)
    bvp = R.pos_v2(r, fs)
    x = R.bandpass(R.detrend_sp(bvp), fs, *R.V2_BAND_EVAL)
    g = R.resample(t, ppg, fs)
    g = R.bandpass(R.detrend_sp(g - g.mean()), fs, *R.V2_BAND_EVAL)
    hr, snr = R.hr_snr_v2(bvp, fs)
    truth, _ = R.ppg_hr_v2(t, ppg, fs)
    tt = np.arange(len(x)) / fs
    f, p = R._periodogram(x, fs)

    fig, ax = plt.subplots(3, 1, figsize=(9, 8.6), gridspec_kw={"height_ratios": [1, 1.15, 1.1], "hspace": 0.62})
    raw = r[:, 1][:len(tt)]
    smooth = np.convolve(raw, np.ones(5) / 5, mode="same")
    ax[0].plot(tt, raw, color=LINE, lw=0.8)
    ax[0].plot(tt[3:-3], smooth[3:-3], color=GREY, lw=1.8)
    ax[0].set_title("① 얼굴 세 영역 평균 G 값 (원신호 · 회색 굵은 선 = 0.17초 평균)", loc="left", fontsize=15, fontweight="bold")
    ax[0].set_ylabel("G")
    z = lambda v: (v - v.mean()) / v.std()  # noqa: E731
    ax[1].plot(tt, z(g[:len(tt)]), color=LINE, lw=3.2, label="손끝 PPG (정답)")
    ax[1].plot(tt, z(x), color=BLUE, lw=1.8, label="얼굴 rPPG (POS)")
    ax[1].set_title("② POS → 추세 제거 → 대역 통과 = 맥파", loc="left", fontsize=16, fontweight="bold")
    ax[1].legend(frameon=False, loc="upper right", ncol=2, fontsize=13)
    ax[1].set_xlabel("시간 (초)")
    band = (f >= 0.6) & (f <= 3.3)
    ax[2].fill_between(f[band] * 60, p[band] / p[band].max(), color=BLUE_L, lw=0)
    ax[2].plot(f[band] * 60, p[band] / p[band].max(), color=BLUE, lw=1.8)
    ax[2].axvline(truth, color=INK, lw=1.4, ls="--")
    ax[2].text(hr + 14, 0.42, f"얼굴 {hr:.1f} bpm\n정답 {truth:.1f} bpm (점선)\nSNR {snr:.1f} dB", fontsize=13, color=INK)
    ax[2].set_title("③ 주파수 최고점 = 심박", loc="left", fontsize=16, fontweight="bold")
    ax[2].set_xlabel("심박 (bpm)")
    ax[2].set_yticks([])
    fig.savefig(OUT / "f1_pipeline.png")
    plt.close(fig)


def fig_gate():
    gt = pd.read_csv(ROOT / "outputs/rppg_v1_v2_gate.csv")
    gt = gt[gt.snr_min.isin([-99, 0, 2, 4])]
    lab = {-99: "전체", 0: "≥0", 2: "≥2", 4: "≥4"}
    fig, ax = plt.subplots(1, 2, figsize=(10, 4.3), gridspec_kw={"wspace": 0.35})
    xs = np.arange(4)
    for i, (v, c) in enumerate((("v1", BLUE_L), ("v2", BLUE))):
        g = gt[gt.method == v]
        ax[0].bar(xs + (i - 0.5) * 0.38, g.pass_rate * 100, 0.36, color=c, label={"v1": "이전 앱", "v2": "rPPG-Toolbox 방식"}[v])
        ax[1].bar(xs + (i - 0.5) * 0.38, g.MAE, 0.36, color=c)
        for x, y in zip(xs + (i - 0.5) * 0.38, g.MAE):
            ax[1].text(x, y + 0.25, f"{y:.1f}", ha="center", fontsize=11)
    for a, t in zip(ax, ("통과율 (%)", "통과한 측정 오차 (bpm)")):
        a.set_xticks(xs, [lab[s] for s in (-99, 0, 2, 4)])
        a.set_xlabel("SNR 기준 (dB)")
        a.set_title(t, loc="left", fontsize=15, fontweight="bold")
    ax[0].legend(frameon=False, fontsize=12, loc="upper right")
    fig.savefig(OUT / "f2_gate.png")
    plt.close(fig)


def fig_scatter():
    w = pd.read_csv(ROOT / "outputs/rppg_v1_v2_windows.csv")
    fig, ax = plt.subplots(1, 2, figsize=(10, 4.8), gridspec_kw={"wspace": 0.28}, sharey=True)
    for a, (v, title) in zip(ax, (("v1", "이전 앱 (MAE 12.5)"), ("v2", "rPPG-Toolbox 방식 (MAE 3.6)"))):
        okm = w[v + "_snr"] >= 0
        a.scatter(w.loc[~okm, "truth"], w.loc[~okm, v], s=5, color=LINE, alpha=0.6, label="SNR < 0", rasterized=True)
        a.scatter(w.loc[okm, "truth"], w.loc[okm, v], s=6, color=BLUE, alpha=0.7, label="SNR ≥ 0 (통과)", rasterized=True)
        a.plot([40, 200], [40, 200], color=INK, lw=1)
        a.set_xlim(40, 160); a.set_ylim(40, 200)
        a.set_title(title, loc="left", fontsize=15, fontweight="bold")
        a.set_xlabel("정답 심박 (bpm)")
    ax[0].set_ylabel("얼굴 심박 (bpm)")
    ax[1].legend(frameon=False, fontsize=12, loc="upper left", markerscale=3)
    fig.savefig(OUT / "f3_scatter.png")
    plt.close(fig)


def fig_complexion():
    c = pd.read_csv(ROOT / "outputs/complexion_indices.csv").set_index("index")
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    vals = [c.loc["a_cheek", "within_sd"], c.loc["a_rel", "within_sd"]]
    ax.barh([1, 0], vals, color=[BLUE_L, BLUE], height=0.55)
    ax.set_yticks([1, 0], ["볼 a* 절대값", "볼 a* - 이마 a*"])
    for y, v in zip([1, 0], vals):
        ax.text(v + 0.03, y, f"{v:.2f}", va="center", fontsize=14, fontweight="bold")
    ax.set_xlim(0, 1.9)
    ax.set_xlabel("같은 영상 안 20초 구간 흔들림 (sd, a* 단위)")
    fig.savefig(OUT / "f4_complexion.png")
    plt.close(fig)


def fig_baseline():
    """시연 기록: 공부 시작 루틴의 준비 주간 기준선과 시험기간 판정."""
    import mirror as M
    con = M.connect(Path(tempfile.mkdtemp()) / "p.db")
    M.seed_demo(con, at=dt.datetime(2026, 10, 19, 22, 0))
    s = M.settings(con)
    rs = [r for r in M.records(con, 500) if r["routine"] == "desk" and r["quality_ok"]]
    rs.sort(key=lambda r: r["at"])
    bl = M.baseline(con, "desk", s["exam_start"], s)
    k = s["k"]
    day0 = dt.date.fromisoformat(rs[0]["day"])
    x = [(dt.date.fromisoformat(r["day"]) - day0).days for r in rs]
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.axhspan(bl["med"] - k * bl["mad"], bl["med"] + k * bl["mad"], color="#E8EEFB", lw=0)
    ax.axhline(bl["med"], color=BLUE, lw=1.2)
    st = (dt.date.fromisoformat(s["exam_start"]) - day0).days
    en = (dt.date.fromisoformat(s["exam_end"]) - day0).days
    for a, b, t in ((0, st, "준비 주간 (기준선)"), (st, en + 1, "시험 주간"), (en + 1, max(x) + 1, "회복")):
        ax.text((a + b) / 2 - 0.5, max(r["bpm"] for r in rs) + 2.2, t, ha="center", fontsize=13, color=GREY)
    ax.axvline(st - 0.5, color=LINE, lw=1); ax.axvline(en + 0.5, color=LINE, lw=1)
    lab = {"caffeine": "카페인", "exercise": "운동", "none": "해당 없음", "sleep": "수면부족", "alcohol": "음주"}
    nd = 0
    for xi, r in zip(x, rs):
        diff = r["judgement"] == "diff"
        ax.scatter(xi, r["bpm"], s=70 if diff else 34, color=(INK if r["status"] == "unexplained" else BLUE) if diff else "#9AA3B2",
                   zorder=3, edgecolor="white", lw=0.8)
        if diff and r["reason"]:
            ax.text(xi, r["bpm"] + (0.9 if nd % 2 == 0 else -1.9), r["reason_sub_ko"] or lab[r["reason"]],
                    ha="center", fontsize=11, color=INK)
            nd += 1
    ax.set_ylabel("공부 시작 심박 (bpm)")
    ax.set_xticks([])
    ax.set_ylim(min(r["bpm"] for r in rs) - 2, max(r["bpm"] for r in rs) + 4)
    ax.text(0, bl["med"] + k * bl["mad"] + 0.35, f"중앙값 ± {k:g}×MAD", fontsize=12, color=BLUE)
    fig.savefig(OUT / "f5_baseline.png")
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    fig_pipeline(); fig_gate(); fig_scatter(); fig_complexion(); fig_baseline()
    print("완료:", sorted(p.name for p in OUT.glob("*.png")))
