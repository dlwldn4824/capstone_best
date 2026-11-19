"""포스터 그림 — 얼굴로 잰 맥박이 손끝 센서와 같다 (MCD-rPPG 실측).

    python3 docs/presentation/poster/make_fig_match.py

얼굴 쪽 곡선과 스펙트럼은 합성이 아니라 **앱이 실제로 돌리는 엔진**이 낸 값이다.
webapp/face/src/pipeline/analyze() 를 Node 로 불러(scripts/eval/dump_window.mjs)
맥파(result.debug.pulse)와 스펙트럼(result.debug.spectrum)을 그대로 받아 그린다.
손끝 센서는 같은 프레임에 동기된 MCD-rPPG 의 정답 PPG 를 같은 대역(0.5–4 Hz,
forward-backward)으로만 거른 것이다.

창은 research/outputs/rppg_v1_v2_v3_windows.csv 에서 고른 한 개다 (아래 PICK).
전체 성적이 아니라 보기 하나라는 점은 캡션에 적는다.
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

PICK = dict(sid="1217", state="before", start=60.0, length=20.0)   # 엔진 통과 · SNR 10.9 dB
SHOW = (4.0, 14.0)        # 창 안에서 그려 보일 10초

INK, BLUE, GREY, LINE = "#0B0F17", "#1D4ED8", "#5B6472", "#D9DEE7"
TRUTH = "#B9C0CC"
for fam in ("AppleGothic", "Apple SD Gothic Neo", "Malgun Gothic", "NanumGothic"):
    try:
        matplotlib.font_manager.findfont(fam, fallback_to_default=False); FONT = fam; break
    except Exception:
        continue
else:
    FONT = "DejaVu Sans"
plt.rcParams.update({
    "font.family": FONT, "font.size": 15, "axes.edgecolor": INK, "axes.labelcolor": INK,
    "xtick.color": INK, "ytick.color": INK, "axes.spines.top": False, "axes.spines.right": False,
    "axes.linewidth": 1.2, "savefig.dpi": 220,  "axes.unicode_minus": False,
})


def load_window():
    d = np.load(TR / f"{PICK['sid']}_{PICK['state']}.npz")
    ok = d["face_ok"] & np.isfinite(d["rgb"]).all(1) & np.isfinite(d["roi"]).all((1, 2))
    t, roi, ppg = d["t"][ok], d["roi"][ok], d["ppg"][ok]
    a, L = PICK["start"], PICK["length"]
    m = (t >= a) & (t < a + L)
    return t[m], roi[m], ppg[m]


def run_engine(t, roi):
    """앱 엔진(analyze)에 그대로 넘기고 맥파·스펙트럼을 받는다."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "w.json"
        p.write_text(json.dumps({"key": f"{PICK['sid']}_{PICK['state']}@{PICK['start']:.0f}",
                                 "t": np.round(t - t[0], 4).tolist(),
                                 "roi": np.round(roi, 3).tolist()}))
        r = subprocess.run(["node", "scripts/eval/dump_window.mjs", str(p)],
                           cwd=FACE, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"node 실패:\n{r.stderr[-2000:]}")
    return json.loads(r.stdout)


def z(x):
    x = np.asarray(x, float)
    return (x - x.mean()) / (x.std() or 1.0)


def main():
    t, roi, ppg = load_window()
    eng = run_engine(t, roi)
    fs = eng["fs"]
    pulse = np.asarray(eng["pulse"], float)
    tt = np.arange(len(pulse)) / fs                      # 엔진 격자 (창 시작이 0초)

    truth_bpm, truth_snr = R.ppg_hr_v2(t, ppg)
    # 정답 PPG 도 같은 격자 · 같은 대역으로만 거른다 (둘 다 위상 지연 없음)
    g = np.interp(tt, t - t[0], ppg)
    b, a = signal.butter(2, [0.5 / (fs / 2), 4.0 / (fs / 2)], btype="bandpass")
    gt = signal.filtfilt(b, a, g - g.mean())

    s = (tt >= SHOW[0]) & (tt <= SHOW[1])
    x = tt[s] - SHOW[0]
    face_z, true_z = z(pulse[s]), z(gt[s])
    lag = (np.argmax(np.correlate(face_z, true_z, "full")) - (len(true_z) - 1)) / fs

    fig = plt.figure(figsize=(10.0, 7.6))
    gs = fig.add_gridspec(2, 1, height_ratios=[1.45, 0.95], hspace=0.62,
                          top=0.855, bottom=0.205, left=0.055, right=0.98)
    fig.text(0.055, 0.945, "얼굴 색으로 잰 맥박이 손끝 센서와 같았다",
             fontsize=19, weight="bold", color=INK, ha="left", va="center")

    ax = fig.add_subplot(gs[0])
    ax.plot(x, true_z, color=TRUTH, lw=5.0, solid_capstyle="round", label="손끝 센서 (정답)")
    ax.plot(x, face_z, color=BLUE, lw=2.3, label="얼굴 (앱 엔진)")
    pk, _ = signal.find_peaks(true_z, distance=fs * 60 / truth_bpm * 0.6, prominence=0.4)
    for i in pk:
        ax.axvline(x[i], color=GREY, lw=0.9, ls=(0, (2, 3)), alpha=0.55, zorder=0)
    ax.set_xlim(0, SHOW[1] - SHOW[0]); ax.set_xlabel("시간 (초)", labelpad=4)
    ax.set_yticks([]); ax.spines["left"].set_visible(False)
    ax.legend(frameon=False, fontsize=13.5, ncol=2, loc="upper left", bbox_to_anchor=(-0.01, 1.17))
    ax.annotate(f"박동 {len(pk)}번이 같은 자리에서 뛴다 · 시간차 {abs(lag)*1000:.0f} ms",
                xy=(0.5, -0.33), xycoords="axes fraction", ha="center", fontsize=12.5, color=GREY)

    ax2 = fig.add_subplot(gs[1])
    f = np.asarray(eng["spec"]["f"], float)          # bpm 단위
    p = np.asarray(eng["spec"]["p"], float)
    ax2.fill_between(f, 0, p, color=BLUE, alpha=0.18, lw=0)
    ax2.plot(f, p, color=BLUE, lw=2.0)
    ax2.axvline(eng["bpm"], color=INK, lw=1.4, ls="--")
    ax2.set_xlim(40, 140); ax2.set_ylim(0, 1.12)
    ax2.set_xlabel("심박 (bpm)", labelpad=4); ax2.set_yticks([])
    ax2.spines["left"].set_visible(False)
    ax2.set_title("가장 센 박자 = 심박", fontsize=15, loc="left", pad=10)
    ax2.annotate(f"얼굴 {eng['bpm']:.1f} bpm   ·   손끝 {truth_bpm:.1f} bpm",
                 xy=(eng["bpm"] + 3, 0.86), fontsize=14, weight="bold", color=INK)

    fig.text(0.5, 0.095,
             f"MCD-rPPG {PICK['sid']}번 · {int(PICK['start'])}–{int(PICK['start'] + PICK['length'])}초 한 구간 "
             f"(신호 세기 {eng['snrDb']:.1f} dB). 얼굴 곡선은 앱이 돌리는 엔진이 낸 값 그대로다.\n"
             f"20명 · 20초 창 597개 전체로는 품질 기준을 통과한 창의 평균 오차가 2.6 bpm 이다.",
             ha="center", va="top", fontsize=11.5, color=GREY, linespacing=1.5)

    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / "f11_match.png"); plt.close(fig)
    print(f"얼굴 {eng['bpm']:.2f} · 손끝 {truth_bpm:.2f} · 오차 {abs(eng['bpm']-truth_bpm):.2f} bpm · "
          f"SNR {eng['snrDb']:.2f} dB · 정답 SNR {truth_snr:.2f} dB · 시간차 {lag*1000:.0f} ms · "
          f"통과 {eng['pass']} · 박동 {len(pk)}")
    print("→", OUT / "f11_match.png")


main()
