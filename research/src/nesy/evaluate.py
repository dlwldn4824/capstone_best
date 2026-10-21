"""공통 평가 지표 + results.csv / predictions.csv 인터페이스.

핵심 연구 질문이 "Stress <-> Exercise 오분류가 줄어드는가" 이므로 Accuracy 나
Macro F1 뿐 아니라 방향성 있는 오분류율을 1급 지표로 만든다.

    stress_to_exercise = P(pred=EXERCISE | true=STRESS)
    exercise_to_stress = P(pred=STRESS   | true=EXERCISE)

담당: 역할 B (모델/평가)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (balanced_accuracy_score, confusion_matrix,
                             f1_score, precision_recall_fscore_support)

LABELS3 = ["REST", "STRESS", "EXERCISE"]

RESULTS_COLS = ["experiment", "model", "split", "feature_set", "task",
                "n_test", "accuracy", "macro_f1", "balanced_accuracy",
                "rest_f1", "stress_f1", "exercise_f1",
                "stress_to_exercise", "exercise_to_stress",
                "abstain_rate", "flag_precision", "flag_recall", "notes"]

PREDICTIONS_COLS = ["experiment", "model", "split", "feature_set", "fold",
                    "sample_id", "subject_id", "true_label", "pred_label",
                    "confidence"]


def directional_error(y_true, y_pred, src, dst):
    """P(pred=dst | true=src). 해당 클래스가 없으면 NaN."""
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    m = y_true == src
    if m.sum() == 0:
        return float("nan")
    return float(np.mean(y_pred[m] == dst))


def compute_metrics(y_true, y_pred, labels=None):
    """단일 지표 dict. abstain(=UNCERTAIN) 은 오답으로 처리한 뒤 별도 보고."""
    y_true = np.asarray(y_true, dtype=object)
    y_pred = np.asarray(y_pred, dtype=object)
    labels = labels or LABELS3

    abstain = np.isin(y_pred, ["UNCERTAIN", None])
    abstain_rate = float(np.mean(abstain)) if len(y_pred) else float("nan")

    # 지표 계산에서는 UNCERTAIN 을 '틀린 것'으로 둔다 (관대한 평가 방지).
    y_eval = np.where(abstain, "__ABSTAIN__", y_pred)

    acc = float(np.mean(y_eval == y_true)) if len(y_true) else float("nan")
    macro = f1_score(y_true, y_eval, labels=labels, average="macro",
                     zero_division=0)
    try:
        bal = balanced_accuracy_score(y_true, y_eval)
    except ValueError:
        bal = float("nan")
    _, _, f1s, _ = precision_recall_fscore_support(
        y_true, y_eval, labels=labels, zero_division=0)

    out = {"n_test": int(len(y_true)), "accuracy": acc,
           "macro_f1": float(macro), "balanced_accuracy": float(bal),
           "abstain_rate": abstain_rate}
    for lab, f in zip(labels, f1s):
        out[lab.lower() + "_f1"] = float(f)
    out["stress_to_exercise"] = directional_error(y_true, y_eval, "STRESS", "EXERCISE")
    out["exercise_to_stress"] = directional_error(y_true, y_eval, "EXERCISE", "STRESS")
    return out


def flag_metrics(y_true, y_pred_neural, flags):
    """Audit 품질: flag 가 Neural 의 실제 오류를 얼마나 잡아내는가.

    flag_precision = flag 중 실제 오류 비율
    flag_recall    = 실제 오류 중 flag 된 비율
    이것이 Li et al. 2026 의 'error detection' 관점과 같은 지표다.
    """
    y_true = np.asarray(y_true, dtype=object)
    y_pred_neural = np.asarray(y_pred_neural, dtype=object)
    flags = np.asarray(flags, dtype=bool)
    errors = y_pred_neural != y_true
    if flags.sum() == 0:
        prec = float("nan")
    else:
        prec = float(np.mean(errors[flags]))
    rec = float(np.mean(flags[errors])) if errors.sum() else float("nan")
    return {"flag_precision": prec, "flag_recall": rec}


def confusion(y_true, y_pred, labels=None):
    labels = labels or LABELS3
    extra = sorted(set(np.asarray(y_pred, dtype=object)) - set(labels))
    cols = labels + extra
    cm = confusion_matrix(y_true, y_pred, labels=cols)
    return pd.DataFrame(cm, index=cols, columns=cols).loc[labels]


def per_subject_metrics(df, true_col="true_label", pred_col="pred_label",
                        subject_col="subject_id", labels=None):
    """피험자별 지표. 유의성 검정의 표본은 윈도가 아니라 '사람'이다.

    윈도 수(수백)를 표본 수로 쓰면 신뢰구간이 터무니없이 좁아진다. 실제
    독립 표본은 피험자 수(14-36명)다.
    """
    rows = []
    for s, sub in df.groupby(subject_col):
        m = compute_metrics(sub[true_col], sub[pred_col], labels)
        rows.append({subject_col: s, **m})
    return pd.DataFrame(rows)


def paired_test(a, b, metric="macro_f1", subject_col="subject_id",
                alternative="two-sided"):
    """두 모델의 피험자별 지표를 짝지어 비교한다 (Wilcoxon signed-rank).

    a, b : per_subject_metrics() 의 출력
    돌려주는 값에 n, median 차이, statistic, p-value, 그리고 효과 크기로
    rank-biserial correlation 을 담는다.

    표본이 작으므로 p 값만으로 결론 내리지 말고 차이의 크기를 함께 볼 것.
    """
    from scipy import stats

    m = a[[subject_col, metric]].merge(
        b[[subject_col, metric]], on=subject_col, suffixes=("_a", "_b"))
    x = m[metric + "_a"].to_numpy(dtype=float)
    y = m[metric + "_b"].to_numpy(dtype=float)
    d = x - y
    nz = d[d != 0]

    out = {"metric": metric, "n": int(len(d)), "n_nonzero": int(len(nz)),
           "median_a": float(np.median(x)), "median_b": float(np.median(y)),
           "median_diff": float(np.median(d)),
           "n_better_a": int(np.sum(d > 0)), "n_better_b": int(np.sum(d < 0))}
    if len(nz) < 3:
        out.update({"statistic": np.nan, "p_value": np.nan,
                    "effect_size": np.nan,
                    "note": "차이가 0이 아닌 피험자가 3명 미만 — 검정 불가"})
        return out

    stat, p = stats.wilcoxon(x, y, alternative=alternative,
                             zero_method="wilcox")
    n = len(nz)
    total = n * (n + 1) / 2.0
    r_plus = float(np.sum(stats.rankdata(np.abs(nz))[nz > 0]))
    out.update({"statistic": float(stat), "p_value": float(p),
                "effect_size": float(2 * r_plus / total - 1),
                "note": ""})
    return out


def compare_models(pred_dfs, metric="macro_f1", reference=None):
    """{이름: predictions_df} -> 기준 모델 대비 짝지은 검정 표.

    pred_label 대신 다른 컬럼(corrected_label 등)을 쓰려면 미리 이름을
    pred_label 로 바꿔서 넣는다.
    """
    per = {k: per_subject_metrics(v) for k, v in pred_dfs.items()}
    ref = reference or next(iter(per))
    rows = []
    for name, d in per.items():
        if name == ref:
            continue
        rows.append({"model": name, "vs": ref,
                     **paired_test(d, per[ref], metric)})
    return pd.DataFrame(rows), per


class ResultsWriter:
    """results.csv 를 append 방식으로 관리한다 (세 역할이 동시에 써도 안전)."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.rows = []

    def add(self, experiment, model, split, feature_set, metrics,
            task="3class", notes=""):
        row = {c: np.nan for c in RESULTS_COLS}
        row.update({"experiment": experiment, "model": model, "split": split,
                    "feature_set": feature_set, "task": task, "notes": notes})
        row.update({k: v for k, v in metrics.items() if k in RESULTS_COLS})
        self.rows.append(row)
        return row

    def flush(self):
        if not self.rows:
            return None
        df = pd.DataFrame(self.rows)[RESULTS_COLS]
        if self.path.exists():
            old = pd.read_csv(self.path)
            df = pd.concat([old, df], ignore_index=True)
            # 같은 (experiment, model, split, feature_set, task) 는 최신만 남긴다.
            df = df.drop_duplicates(
                subset=["experiment", "model", "split", "feature_set", "task"],
                keep="last")
        df.to_csv(self.path, index=False)
        self.rows = []
        return df


def save_predictions(path, df):
    """predictions.csv 인터페이스. 역할 C 가 이 파일을 입력으로 받는다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    missing = [c for c in PREDICTIONS_COLS if c not in df.columns]
    if missing:
        raise ValueError("predictions.csv 필수 컬럼 누락: {}".format(missing))
    df[PREDICTIONS_COLS].to_csv(path, index=False)
    return path
