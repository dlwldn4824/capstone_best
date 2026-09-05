"""NeSy Correction: symbolic evidence 로 Neural 라벨을 실제로 바꾼다.

Audit 과 반드시 분리해서 보고한다. Correction 은 성능을 올릴 수도 있지만
"Neural 이 맞았는데 규칙이 망친" 경우를 만들 수 있고, 그 수를 함께 보고하지
않으면 결과가 과장된다.

수정 조건 (셋 다 만족할 때만)
  1. Neural confidence 가 낮다            (모델 스스로 확신이 없다)
  2. 다른 클래스의 evidence 가 뚜렷이 강하다
  3. 그 evidence 가 절대 기준도 넘는다     (약한 근거로 뒤집지 않는다)

담당: 역할 C (NeSy/Rule)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import evaluate, nesy_audit


def correct(audited, conf_thresh=0.75, margin=0.3, min_rival=0.5):
    """audit 결과 -> 수정된 예측.

    돌려주는 DataFrame 에 corrected_label / was_corrected 가 추가된다.
    """
    df = audited.copy()
    cond = (
        (df["confidence"].to_numpy(dtype=float) < conf_thresh)
        & ((df["rival_evidence"] - df["own_evidence"]).to_numpy(dtype=float) > margin)
        & (df["rival_evidence"].to_numpy(dtype=float) >= min_rival)
        & df["rival_label"].notna().to_numpy()
    )
    df["corrected_label"] = np.where(cond, df["rival_label"], df["pred_label"])
    df["was_corrected"] = cond
    return df


def correction_ledger(corrected):
    """수정이 도움이 됐는지 해가 됐는지 정직하게 센다.

    fixed  : 틀린 예측 -> 맞음   (이득)
    broken : 맞은 예측 -> 틀림   (손해)
    moved  : 틀린 예측 -> 여전히 틀림
    """
    d = corrected[corrected["was_corrected"]]
    y = d["true_label"].to_numpy(dtype=object)
    before = d["pred_label"].to_numpy(dtype=object)
    after = d["corrected_label"].to_numpy(dtype=object)
    fixed = int(np.sum((before != y) & (after == y)))
    broken = int(np.sum((before == y) & (after != y)))
    moved = int(np.sum((before != y) & (after != y)))
    return {"n_corrected": int(len(d)), "fixed": fixed, "broken": broken,
            "moved_still_wrong": moved,
            "net_gain": fixed - broken,
            "correction_precision": float(fixed / len(d)) if len(d) else np.nan}


def run(predictions, facts, results_writer=None, experiment="nesy",
        split="group_kfold", feature_set="", **kw):
    """audit -> correction -> 지표까지 한 번에. 07_nesy.py 가 쓴다."""
    audited = nesy_audit.audit(predictions, facts,
                               support_thresh=kw.get("support_thresh", 0.5),
                               conflict_margin=kw.get("conflict_margin", 0.3))
    corrected = correct(audited, kw.get("conf_thresh", 0.75),
                        kw.get("margin", 0.3), kw.get("min_rival", 0.5))

    y = corrected["true_label"].to_numpy(dtype=object)
    m_audit, conflict_only = nesy_audit.evaluate_audit(
        audited, results_writer, experiment + "_audit", split, feature_set)
    m_corr = evaluate.compute_metrics(
        y, corrected["corrected_label"].to_numpy(dtype=object))
    ledger = correction_ledger(corrected)

    if results_writer is not None:
        results_writer.add(
            experiment + "_correction", "nesy_correction", split, feature_set,
            m_corr,
            notes="corrected={n_corrected} fixed={fixed} broken={broken} net={net_gain}"
                  .format(**ledger))
    return {"audited": audited, "corrected": corrected,
            "metrics_audit": m_audit, "metrics_correction": m_corr,
            "ledger": ledger, "conflict_only": conflict_only}
