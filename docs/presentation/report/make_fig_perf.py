"""보고서 '성능' 절 그림 — 전처리 4단계와 접촉 센서 대조 (MCD-rPPG 실측).

    python3 docs/presentation/report/make_fig_perf.py

얼굴 쪽 곡선과 스펙트럼은 합성이 아니라 **앱이 실제로 돌리는 엔진**이 낸 값이다.
webapp/face/src/pipeline/analyze() 를 Node 로 불러(scripts/eval/dump_window.mjs)
맥파(result.debug.pulse)와 스펙트럼(result.debug.spectrum)을 그대로 받아 그린다.
정답은 같은 프레임에 동기된 손끝 PPG 센서다.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
import numpy as np                       # noqa: E402
from scipy import signal                 # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "research" / "src"))
from nesy import rppg as R               # noqa: E402

OUT = HERE / "fig"
TR = REPO / "research/data/raw/mcd_rppg/traces"
FACE = REPO / "webapp" / "face"

PICK = dict(sid="1217", state="before", start=60.0, length=20.0)
SHOW = (4.0, 14.0)        # 겹쳐 보기에 쓸 10초

INK, BLUE, GRAY, TRUTH = "#0B0F17", "#1D4ED8", "#5B6472", "#B9C0CC"
RED = "#D2452F"
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


def load():
    d = np.load(TR / f"{PICK['sid']}_{PICK['state']}.npz")
    ok = d["face_ok"] & np.isfinite(d["rgb"]).all(1) & np.isfinite(d["roi"]).all((1, 2))
    t, rgb, roi, ppg = d["t"][ok], d["rgb"][ok], d["roi"][ok], d["ppg"][ok]
    a, L = PICK["start"], PICK["length"]
    m = (t >= a) & (t < a + L)
    return t[m], rgb[m], roi[m], ppg[m]


def engine(t, roi):
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "w.json"
        p.write_text(json.dumps({"key": "fig",
                                 "t": np.round(t - t[0], 4).tolist(),
                                 "roi": np.round(roi, 3).tolist()}))
        r = subprocess.run(["node", "scripts/eval/dump_window.mjs", str(p)],
                           cwd=FACE, capture_output=True, text=True,
                           env={**__import__("os").environ, "WINDOWS": "off"})
    if r.returncode != 0:
        sys.exit(f"node 실패:\n{r.stderr[-1500:]}")
    return json.loads(r.stdout)


z = lambda x: (np.asarray(x, float) - np.mean(x)) / (np.std(x) or 1.0)


def main():
    t, rgb, roi, ppg = load()
    eng = engine(t, roi)
    fs = eng["fs"]
    pulse = np.asarray(eng["pulse"], float)
    tt = np.arange(len(pulse)) / fs
    truth_bpm, _ = R.ppg_hr_v2(t, ppg)

    # 원시 — 세 영역 평균 RGB 의 G 채널
    g_raw = np.interp(tt, t - t[0], rgb[:, 1])
    b, a = signal.butter(2, [0.5 / (fs / 2), 4.0 / (fs / 2)], btype="bandpass")
    g_band = signal.filtfilt(b, a, g_raw - g_raw.mean())
    share = g_band.std() / (g_raw - g_raw.mean()).std()

    # 정답 PPG 도 같은 격자 · 같은 대역으로
    gt = signal.filtfilt(b, a, np.interp(tt, t - t[0], ppg) - np.mean(ppg))

    s = (tt >= SHOW[0]) & (tt <= SHOW[1])
    x = tt[s] - SHOW[0]

    fig = plt.figure(figsize=(10.4, 12.2))
    gs = fig.add_gridspec(4, 1, height_ratios=[1, 1, 1.15, 1], hspace=0.95,
                          top=0.935, bottom=0.115, left=0.065, right=0.975)

    # ① 원시
    ax = fig.add_subplot(gs[0])
    ax.plot(tt, g_raw, color=GRAY, lw=1.6)
    ax.set_xlim(0, tt[-1]); ax.set_yticks([]); ax.spines["left"].set_visible(False)
    ax.set_title("① 원시 — 세 영역 평균 초록 채널", fontsize=15, loc="left", pad=30)
    ax.set_xlabel("시간 (초)", labelpad=2)
    ax.annotate(f"맥박이 만드는 변화는 전체 흔들림의 {share*100:.0f}% 뿐이다. 그대로 보면 주기가 보이지 않는다.",
                xy=(0, 1.04), xycoords="axes fraction", fontsize=12.5, color=GRAY, va="bottom")

    # ② 잡음 제거
    ax = fig.add_subplot(gs[1])
    ax.plot(tt, pulse, color=BLUE, lw=1.8)
    ax.set_xlim(0, tt[-1]); ax.set_yticks([]); ax.spines["left"].set_visible(False)
    ax.set_title("② 주기만 남기기 — 1.6초 창 평균으로 조명 제거(POS) 뒤 0.5–4 Hz 만 통과",
                 fontsize=15, loc="left", pad=8)
    ax.set_xlabel("시간 (초)", labelpad=2)

    # ③ 접촉 센서와 겹쳐 보기
    ax = fig.add_subplot(gs[2])
    ax.plot(x, z(gt[s]), color=TRUTH, lw=5.0, solid_capstyle="round", label="손끝 PPG 센서 (정답)")
    ax.plot(x, z(pulse[s]), color=BLUE, lw=2.2, label="얼굴 (앱 엔진)")
    pk, _ = signal.find_peaks(z(gt[s]), distance=fs * 60 / truth_bpm * 0.6, prominence=0.4)
    for i in pk:
        ax.axvline(x[i], color=GRAY, lw=0.9, ls=(0, (2, 3)), alpha=0.5, zorder=0)
    ax.set_xlim(0, SHOW[1] - SHOW[0]); ax.set_yticks([]); ax.spines["left"].set_visible(False)
    ax.set_title("③ 같은 시각에 잰 접촉 센서와 겹쳐 보기", fontsize=15, loc="left", pad=26)
    ax.set_xlabel("시간 (초)", labelpad=2)
    ax.legend(frameon=False, fontsize=13, ncol=2, loc="upper left", bbox_to_anchor=(-0.012, 1.20))
    lag = (np.argmax(np.correlate(z(pulse[s]), z(gt[s]), "full")) - (len(x) - 1)) / fs
    ax.annotate(f"박동 {len(pk)}번이 같은 자리에서 뛴다 · 시간차 {abs(lag)*1000:.0f} ms",
                xy=(1.0, 1.20), xycoords="axes fraction", ha="right", va="bottom",
                fontsize=12.5, color=GRAY)

    # ④ 주기 뽑기
    ax = fig.add_subplot(gs[3])
    f = np.asarray(eng["spec"]["f"], float)
    p = np.asarray(eng["spec"]["p"], float)
    ax.fill_between(f, 0, p, color=BLUE, alpha=0.18, lw=0)
    ax.plot(f, p, color=BLUE, lw=2.0)
    ax.axvline(eng["bpm"], color=INK, lw=1.3, ls="--")
    ax.set_xlim(40, 140); ax.set_ylim(0, 1.16); ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    ax.set_xlabel("심박 (bpm)", labelpad=2)
    ax.set_title("④ 가장 센 주기 = 심박", fontsize=15, loc="left", pad=8)
    ax.annotate(f"얼굴 {eng['bpm']:.1f} bpm   ·   손끝 센서 {truth_bpm:.1f} bpm   "
                f"(오차 {abs(eng['bpm']-truth_bpm):.2f} bpm)",
                xy=(eng["bpm"] + 3, 0.88), fontsize=14, weight="bold", color=INK)

    fig.text(0.065, 0.062,
             f"MCD-rPPG {PICK['sid']}번 · {int(PICK['start'])}–{int(PICK['start']+PICK['length'])}초 한 구간 "
             f"(신호 세기 {eng['snrDb']:.1f} dB). 얼굴 곡선과 스펙트럼은 앱이 돌리는 엔진이 낸 값 그대로다.\n"
             f"20명 · 20초 창 597개 전체로는 품질을 통과한 창의 평균 오차가 2.62 bpm 이다.",
             fontsize=12, color=GRAY, va="top", linespacing=1.7)

    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / "perf_pipeline.png"); plt.close(fig)
    print(f"맥박 비중 {share*100:.1f}% · 얼굴 {eng['bpm']:.2f} · 손끝 {truth_bpm:.2f} · "
          f"오차 {abs(eng['bpm']-truth_bpm):.2f} bpm · SNR {eng['snrDb']:.2f} dB")
    print("→", OUT / "perf_pipeline.png")


main()
