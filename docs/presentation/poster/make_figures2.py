"""포스터 추가 그림 — 공개 데이터셋 없이, 저장소 안의 실험 결과만으로 그린다.

    python docs/presentation/poster/make_figures2.py

출처
  f6  docs/research/HRV_VERDICT.md            WESAD 15명, 가슴 ECG vs 손목 PPG 동시 기록
  f7  webapp/face/scripts/experiments/p3_gate.js        합성 280회 (obs=hard)
  f8  webapp/face/scripts/robustness/12_hrv_gate.js     합성 480회
"""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402
import numpy as np                # noqa: E402

OUT = Path(__file__).resolve().parent / "fig"
INK, BLUE, BLUE_L, GREY, LINE, RED = "#0B0F17", "#1D4ED8", "#9DB4F0", "#5B6472", "#D9DEE7", "#D2452F"
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
    "axes.linewidth": 1.2, "savefig.dpi": 220, "savefig.bbox": "tight", "axes.unicode_minus": False,
})


def fig_wearable():
    """왜 손목이 아니라 얼굴인가 — HRV 는 손목에서 갈리고, 심박은 어디서나 잡힌다."""
    fig, ax = plt.subplots(1, 2, figsize=(10.2, 4.0))
    x = np.arange(2); w = 0.34

    # 왼쪽: RMSSD (HRV)
    ax[0].bar(x - w / 2, [48.6, 154.0], w, label="평상시", color=BLUE_L, edgecolor=INK, linewidth=1.1)
    ax[0].bar(x + w / 2, [32.0, 133.2], w, label="스트레스", color=BLUE, edgecolor=INK, linewidth=1.1)
    ax[0].set_xticks(x); ax[0].set_xticklabels(["가슴 ECG", "손목 PPG"])
    ax[0].set_ylabel("RMSSD (ms)"); ax[0].set_title("HRV — 손목은 방향조차 반대", fontsize=15, pad=12)
    ax[0].annotate("-27%  10/15명 감소", (0, 56), ha="center", fontsize=12.5, color=BLUE, weight="bold")
    ax[0].annotate("+3%  7/15명", (1, 162), ha="center", fontsize=12.5, color=RED, weight="bold")
    ax[0].legend(frameon=False, fontsize=12.5, loc="upper left", bbox_to_anchor=(0, 0.88))
    ax[0].set_ylim(0, 210)

    # 오른쪽: 심박 상승폭
    ax[1].bar(x, [21.2, 24.4], 0.5, color=[BLUE, BLUE], edgecolor=INK, linewidth=1.1)
    ax[1].set_xticks(x); ax[1].set_xticklabels(["가슴 ECG", "손목 PPG"])
    ax[1].set_ylabel("심박 상승 (bpm)", labelpad=6)
    ax[1].set_title("심박 — 둘 다 15/15명 상승", fontsize=15, pad=12)
    for i, v in enumerate([21.2, 24.4]):
        ax[1].text(i, v + 0.8, f"+{v}", ha="center", fontsize=13.5, weight="bold", color=INK)
    ax[1].set_ylim(0, 30)
    fig.text(0.5, -0.04, "WESAD 15명 · 같은 사람 · 같은 시각 동시 기록 (docs/research/HRV_VERDICT.md)",
             ha="center", fontsize=12, color=GREY)
    fig.tight_layout(); fig.savefig(OUT / "f6_wearable.png"); plt.close(fig)


def fig_gate():
    """품질 기준을 풀고 구간을 고르면, 틀린 값을 받지 않고도 통과가 는다."""
    labels = ["이전 기준\n(전체 30초)", "기준 완화\n(전체 30초)", "기준 완화\n+ 구간 선택"]
    passed = [78, 91, 95]
    rejected_ok = [21, 9, 5]      # bpm 은 맞는데 거부
    fig, ax = plt.subplots(figsize=(9.6, 3.9))
    x = np.arange(3)
    ax.bar(x, passed, 0.46, color=BLUE, edgecolor=INK, linewidth=1.1, label="통과 (전부 ±5 bpm 안)")
    ax.bar(x, rejected_ok, 0.46, bottom=passed, color=LINE, edgecolor=INK, linewidth=1.1,
           label="맞는데 거부")
    for i, (p, r) in enumerate(zip(passed, rejected_ok)):
        ax.text(i, p / 2, f"{p}%", ha="center", va="center", fontsize=17, weight="bold", color="white")
        ax.text(i, p + r / 2, f"{r}%", ha="center", va="center", fontsize=12.5, color=GREY)
    ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=12.5)
    ax.set_ylabel("합성 280회 중 비율"); ax.set_ylim(0, 108)
    ax.legend(frameon=False, fontsize=12.5, loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=2)
    ax.set_title("틀린 값 통과는 세 조건 모두 0%", fontsize=14.5, pad=14, color=GREY)
    fig.text(0.5, -0.30, "흔들림 7종 × 강도 2 × 시드 20 (webapp/face/scripts/experiments/p3_gate.js)",
             ha="center", fontsize=12, color=GREY)
    fig.tight_layout(); fig.savefig(OUT / "f7_gate.png"); plt.close(fig)


def fig_hrv_gate():
    """HRV 를 아무 때나 보여 주면 안 되는 이유 — 신호가 약하면 없는 변동이 생긴다."""
    bands = ["3–6", "6–8", "8–10", "10–12", "12–14", "14+"]
    err = [32.2, 27.9, 18.7, 16.9, 14.4, 9.6]
    false_pos = [100, 100, 100, 100, 87, 18]
    fig, ax = plt.subplots(figsize=(8.6, 4.2))
    x = np.arange(len(bands))
    ax.bar(x, err, 0.5, color=BLUE_L, edgecolor=INK, linewidth=1.1)
    ax.set_ylabel("RMSSD 오차 중앙값 (ms)", color=INK)
    ax.set_xticks(x); ax.set_xticklabels(bands)
    ax.set_xlabel("맥박 신호 세기 SNR (dB)")
    ax2 = ax.twinx()
    ax2.plot(x, false_pos, "o-", color=RED, linewidth=2.4, markersize=7)
    ax2.set_ylabel("없는 HRV 가 생기는 비율 (%)", color=RED, labelpad=8)
    ax2.tick_params(axis="y", colors=RED); ax2.set_ylim(0, 108); ax2.spines["top"].set_visible(False)
    ax.axvline(2.5, color=INK, linestyle="--", linewidth=1.4)
    ax.annotate("우리 문턱\n10 dB", (2.62, 23.5), fontsize=12.5, color=INK, ha="left", weight="bold")
    fig.text(0.5, -0.06, "합성 480회 · 진폭 · 잡음 · 지터 혼합 (webapp/face/scripts/robustness/12_hrv_gate.js)",
             ha="center", fontsize=12, color=GREY)
    fig.tight_layout(); fig.savefig(OUT / "f8_hrv_gate.png"); plt.close(fig)


def fig_earlystop():
    """측정 시간을 줄이되, 줄였다고 틀리지는 않는다."""
    rules = ["고정 30초", "참고 앱 방식", "우리 규칙"]
    median = [30.0, 8.0, 10.0]
    mean = [30.0, 8.2, 12.8]
    passed = [99, 89, 100]
    fig, ax = plt.subplots(1, 2, figsize=(11.2, 3.6))
    x = np.arange(3); w = 0.34
    ax[0].bar(x - w / 2, median, w, color=BLUE, edgecolor=INK, linewidth=1.1, label="중앙값")
    ax[0].bar(x + w / 2, mean, w, color=BLUE_L, edgecolor=INK, linewidth=1.1, label="평균")
    for i, (m, a) in enumerate(zip(median, mean)):
        ax[0].text(i - w / 2, m + 0.7, f"{m:.0f}s", ha="center", fontsize=12.5, weight="bold", color=INK)
        ax[0].text(i + w / 2, a + 0.7, f"{a:.1f}s", ha="center", fontsize=12, color=GREY)
    ax[0].set_xticks(x); ax[0].set_xticklabels(rules, fontsize=12.5)
    ax[0].set_ylabel("측정에 걸린 시간 (초)"); ax[0].set_ylim(0, 36)
    ax[0].legend(frameon=False, fontsize=12, loc="upper right")
    ax[0].set_title("걸린 시간", fontsize=14.5, pad=10)

    ax[1].bar(x, passed, 0.5, color=[GREY, RED, BLUE], edgecolor=INK, linewidth=1.1)
    for i, v in enumerate(passed):
        ax[1].text(i, v + 1.5, f"{v}%", ha="center", fontsize=14, weight="bold",
                   color=(RED if v < 95 else INK))
    ax[1].set_xticks(x); ax[1].set_xticklabels(rules, fontsize=12.5)
    ax[1].set_ylabel("품질 통과율"); ax[1].set_ylim(0, 115)
    ax[1].set_title("일찍 끝내도 결과는 그대로", fontsize=14.5, pad=10)
    fig.text(0.5, -0.13, "참고 앱 방식 = 3연속 ±3 · 최소 8초 / 우리 규칙 = 3연속 ±2 + SNR ≥ 3 + 품질 통과 · 최소 10초\n"
             "합성 100회 · 멈춘 시점의 bpm 은 세 방식 모두 참값 ±5 안 · 조기 거짓 수락 0% (p2_earlystop.js)", ha="center", fontsize=11.5, color=GREY)
    fig.tight_layout(); fig.savefig(OUT / "f9_earlystop.png"); plt.close(fig)


def fig_v3_accuracy():
    """지금 앱이 쓰는 엔진(face)의 정확도 — 품질 기준을 통과한 측정만 숫자를 보여 준다."""
    import pandas as pd
    csv = Path(__file__).resolve().parents[3] / "research/outputs/rppg_v1_v2_v3_windows.csv"
    if not csv.exists():
        print("건너뜀 (research/scripts/28_rppg_v3_face.py 를 먼저 돌린다):", csv.name)
        return
    d = pd.read_csv(csv)
    ok, no = d[d["v3_pass"]], d[~d["v3_pass"]]
    fig, ax = plt.subplots(1, 2, figsize=(10.8, 4.2))

    ax[0].plot([40, 140], [40, 140], color=GREY, linewidth=1.2, linestyle="--", zorder=1)
    ax[0].scatter(no["truth"], no["v3"], s=14, color=LINE, edgecolor="none", zorder=2, label=f"기준 미달 ({len(no)})")
    ax[0].scatter(ok["truth"], ok["v3"], s=16, color=BLUE, edgecolor="none", alpha=.75, zorder=3, label=f"통과 ({len(ok)})")
    ax[0].set_xlabel("손끝 PPG 정답 (bpm)"); ax[0].set_ylabel("얼굴에서 잰 심박 (bpm)")
    ax[0].set_xlim(40, 140); ax[0].set_ylim(40, 140)
    ax[0].legend(frameon=False, fontsize=12, loc="upper left")
    ax[0].set_title("통과한 측정만 숫자를 보여 준다", fontsize=14.5, pad=10)

    bins = np.arange(0, 21, 1.5)
    ax[1].hist(np.clip(d["v3_err"], 0, 20), bins=bins, color=LINE, edgecolor=INK, linewidth=.9, label="창 전부")
    ax[1].hist(np.clip(ok["v3_err"], 0, 20), bins=bins, color=BLUE, edgecolor=INK, linewidth=.9, label="통과분")
    ax[1].axvline(5, color=RED, linestyle="--", linewidth=1.6)
    ax[1].annotate("±5 bpm", (5.5, ax[1].get_ylim()[1] * .86), fontsize=12, color=RED, weight="bold")
    ax[1].set_xlabel("정답과의 차이 (bpm)"); ax[1].set_ylabel("창 수")
    ax[1].legend(frameon=False, fontsize=12)
    ax[1].set_title("통과분은 92%가 ±5 bpm 안", fontsize=14.5, pad=10)
    fig.text(0.5, -0.04, "MCD-rPPG 20명 · 20초 창 597개 · 정답은 프레임 동기 손끝 PPG "
             "(research/scripts/28_rppg_v3_face.py)", ha="center", fontsize=11.5, color=GREY)
    fig.tight_layout(); fig.savefig(OUT / "f10_v3_accuracy.png"); plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    fig_wearable(); fig_gate(); fig_hrv_gate(); fig_earlystop(); fig_v3_accuracy()
    print("saved:", ", ".join(p.name for p in sorted(OUT.glob("f[6-9]*.png")) + sorted(OUT.glob("f10*.png"))))
