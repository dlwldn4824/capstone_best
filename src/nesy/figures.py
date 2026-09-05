"""보고용 그림 생성. 2주 계획 6절의 6개 그림을 모두 담당한다.

담당: 역할 A(Fig 1-2) / B(Fig 4-5) / C(Fig 3, 6)
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams.update({"figure.dpi": 130, "savefig.bbox": "tight",
                     "axes.grid": True, "grid.alpha": 0.3, "font.size": 9})

STATE_COLORS = {"REST": "#4C78A8", "STRESS": "#E45756", "EXERCISE": "#F58518",
                "AEROBIC": "#F58518", "SPRINT": "#B279A2"}


def _save(fig, outdir, name):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    p = outdir / name
    fig.savefig(p)
    plt.close(fig)
    return str(p)


def fig1_bvp_pipeline(raw, filtered, peaks, fs, outdir, name="fig1_bvp_pipeline.png"):
    """Raw BVP -> Filtered -> Peak detection."""
    n = min(len(raw), int(fs * 15))
    t = np.arange(n) / fs
    fig, ax = plt.subplots(3, 1, figsize=(8, 5.5), sharex=True)
    ax[0].plot(t, raw[:n], lw=0.8, color="#888")
    ax[0].set_ylabel("Raw BVP")
    ax[1].plot(t, filtered[:n], lw=0.8, color="#4C78A8")
    ax[1].set_ylabel("0.5-10 Hz")
    ax[2].plot(t, filtered[:n], lw=0.8, color="#4C78A8")
    pk = peaks[peaks < n]
    ax[2].plot(pk / fs, filtered[pk], "v", ms=5, color="#E45756")
    ax[2].set_ylabel("Peaks")
    ax[2].set_xlabel("time (s)")
    fig.suptitle("Fig 1. BVP preprocessing (15 s excerpt)")
    return _save(fig, outdir, name)


def fig2_eda_decomposition(raw, tonic, phasic, events, fs, outdir,
                           name="fig2_eda_decomposition.png"):
    """Raw EDA -> Tonic / Phasic + SCR."""
    t = np.arange(len(raw)) / fs
    fig, ax = plt.subplots(2, 1, figsize=(8, 4.2), sharex=True)
    ax[0].plot(t, raw, lw=0.9, color="#888", label="raw")
    ax[0].plot(t, tonic, lw=1.4, color="#4C78A8", label="tonic (SCL)")
    ax[0].legend(loc="upper right", fontsize=8)
    ax[0].set_ylabel("EDA (uS)")
    ax[1].plot(t, phasic, lw=0.9, color="#54A24B", label="phasic (SCR)")
    if events:
        pk = [e["peak_sample"] for e in events if e["peak_sample"] < len(phasic)]
        ax[1].plot(np.asarray(pk) / fs, phasic[pk], "o", ms=4, color="#E45756",
                   label="SCR peak")
    ax[1].legend(loc="upper right", fontsize=8)
    ax[1].set_ylabel("phasic")
    ax[1].set_xlabel("time (s)")
    fig.suptitle("Fig 2. EDA tonic / phasic decomposition")
    return _save(fig, outdir, name)


def fig3_feature_distributions(df, features, outdir,
                               name="fig3_feature_distributions.png"):
    """상태별 핵심 feature 분포. Stress 와 Exercise 가 어디서 겹치는지 보여준다."""
    features = [f for f in features if f in df.columns]
    ncol = min(4, len(features))
    nrow = int(np.ceil(len(features) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(3.1 * ncol, 2.6 * nrow))
    axes = np.atleast_1d(axes).ravel()
    labels = [l for l in ("REST", "STRESS", "EXERCISE") if l in set(df["label"])]
    for ax, f in zip(axes, features):
        data = [df.loc[df["label"] == l, f].dropna().to_numpy() for l in labels]
        try:
            bp = ax.boxplot(data, tick_labels=labels, patch_artist=True,
                            widths=0.6, showfliers=False)
        except TypeError:   # matplotlib < 3.9
            bp = ax.boxplot(data, labels=labels, patch_artist=True,
                            widths=0.6, showfliers=False)
        for patch, l in zip(bp["boxes"], labels):
            patch.set_facecolor(STATE_COLORS.get(l, "#999"))
            patch.set_alpha(0.65)
        ax.set_title(f, fontsize=9)
        ax.tick_params(axis="x", labelsize=8)
    for ax in axes[len(features):]:
        ax.axis("off")
    fig.suptitle("Fig 3. State-wise feature distributions", y=1.0)
    fig.tight_layout()
    return _save(fig, outdir, name)


def fig4_confusion(cms, titles, outdir, name="fig4_confusion.png"):
    """여러 모델의 confusion matrix 를 나란히. Neural vs NeSy 대비가 핵심."""
    n = len(cms)
    fig, axes = plt.subplots(1, n, figsize=(3.4 * n, 3.2))
    axes = np.atleast_1d(axes)
    for ax, cm, title in zip(axes, cms, titles):
        norm = cm.to_numpy(dtype=float)
        norm = norm / np.maximum(norm.sum(axis=1, keepdims=True), 1)
        im = ax.imshow(norm, cmap="Blues", vmin=0, vmax=1)
        ax.set_xticks(range(len(cm.columns)))
        ax.set_xticklabels(cm.columns, rotation=45, ha="right", fontsize=8)
        ax.set_yticks(range(len(cm.index)))
        ax.set_yticklabels(cm.index, fontsize=8)
        for i in range(norm.shape[0]):
            for j in range(norm.shape[1]):
                ax.text(j, i, "{:.2f}".format(norm[i, j]), ha="center",
                        va="center", fontsize=8,
                        color="white" if norm[i, j] > 0.55 else "black")
        ax.set_title(title, fontsize=9)
        ax.set_ylabel("true" if ax is axes[0] else "")
        ax.set_xlabel("predicted")
        ax.grid(False)
    fig.suptitle("Fig 4. Confusion matrices (row-normalised)")
    fig.tight_layout()
    return _save(fig, outdir, name)


def fig5_ablation(results, outdir, name="fig5_ablation.png"):
    """feature 를 HR -> +HRV -> +EDA -> +ACC 로 늘릴 때의 변화."""
    order = ["HR", "HR+HRV", "HR+HRV+EDA", "HR+HRV+EDA+ACC"]
    d = results[results["feature_set"].isin(order)].copy()
    d["feature_set"] = pd.Categorical(d["feature_set"], order, ordered=True)
    d = d.sort_values("feature_set")
    fig, ax = plt.subplots(1, 2, figsize=(9, 3.4))
    for model, sub in d.groupby("model"):
        ax[0].plot(sub["feature_set"].astype(str), sub["macro_f1"], "o-",
                   label=model)
        ax[1].plot(sub["feature_set"].astype(str), sub["stress_to_exercise"],
                   "o-", label=model)
    ax[0].set_ylabel("Macro F1")
    ax[1].set_ylabel("P(pred=EXERCISE | true=STRESS)")
    for a in ax:
        a.tick_params(axis="x", rotation=25, labelsize=8)
        a.legend(fontsize=8)
    fig.suptitle("Fig 5. Feature ablation")
    fig.tight_layout()
    return _save(fig, outdir, name)


def fig6_case_study(row, outdir, name="fig6_case_study.png"):
    """한 샘플의 Neural 확률 + fact + evidence + audit 판정."""
    fig, ax = plt.subplots(1, 3, figsize=(10, 3.0))

    probs = {k[2:]: v for k, v in row.items()
             if isinstance(k, str) and k.startswith("p_")}
    ax[0].barh(list(probs), list(probs.values()),
               color=[STATE_COLORS.get(k, "#999") for k in probs])
    ax[0].set_xlim(0, 1)
    ax[0].set_title("Neural prediction", fontsize=9)

    facts = {k: bool(v) for k, v in row.items()
             if isinstance(k, str) and (k.endswith("_HIGH") or k == "ACTIVITY_LOW")}
    ax[1].barh(list(facts), [1 if v else 0 for v in facts.values()],
               color=["#54A24B" if v else "#DDD" for v in facts.values()])
    ax[1].set_xlim(0, 1.1)
    ax[1].set_xticks([])
    ax[1].set_title("Physiological facts", fontsize=9)

    ev = {k.replace("_EVIDENCE", ""): row.get(k, 0.0)
          for k in ("REST_EVIDENCE", "STRESS_EVIDENCE", "EXERCISE_EVIDENCE")}
    ax[2].barh(list(ev), list(ev.values()),
               color=[STATE_COLORS.get(k, "#999") for k in ev])
    ax[2].set_xlim(0, 1)
    ax[2].set_title("Symbolic evidence", fontsize=9)

    fig.suptitle("Fig 6. Case study — true={} | neural={} | audit={}".format(
        row.get("true_label"), row.get("pred_label"), row.get("audit")))
    fig.tight_layout()
    return _save(fig, outdir, name)
