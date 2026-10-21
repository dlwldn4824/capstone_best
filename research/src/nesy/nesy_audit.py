"""Evidence Audit: Neural 예측을 생리적 근거와 대조한다.

Li et al. 의 audit 구조를 따른다. Symbolic 은 라벨을 바꾸지 않고
"이 예측을 뒷받침하는 근거가 있는가" 만 판정한다.

    SUPPORTED  Neural 예측에 대응하는 evidence 가 충분
    CONFLICT   Neural 예측과 다른 클래스의 evidence 가 더 강함
    UNCERTAIN  어느 쪽 evidence 도 약함

이 구조의 장점은 분류 성능을 해치지 않으면서 '틀릴 것 같은 예측'을 표시할 수
있다는 것이다. 평가는 정확도가 아니라 flag_precision / flag_recall 로 한다.

담당: 역할 C (NeSy/Rule)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import evaluate, rules as rules_mod

EVIDENCE_OF = {"REST": "REST_EVIDENCE", "STRESS": "STRESS_EVIDENCE",
               "EXERCISE": "EXERCISE_EVIDENCE"}

SUPPORTED, CONFLICT, UNCERTAIN = "SUPPORTED", "CONFLICT", "UNCERTAIN"


def audit(predictions, facts, rules=None, support_thresh=0.5,
          conflict_margin=0.3):
    """predictions + facts -> audit 결과 DataFrame.

    predictions : sample_id, pred_label, confidence (+ p_* 확률)
    facts       : sample_id + fact 컬럼
    """
    ev = rules_mod.apply_rules(facts, rules)
    df = predictions.reset_index(drop=True).copy()
    ev = ev.reset_index(drop=True)
    if len(df) != len(ev):
        raise ValueError("predictions 와 facts 의 행 수가 다릅니다.")
    df = pd.concat([df, ev], axis=1)

    own = np.zeros(len(df))
    best_other = np.zeros(len(df))
    best_other_name = np.empty(len(df), dtype=object)

    ev_cols = {k: df[v].to_numpy() for k, v in EVIDENCE_OF.items()}
    preds = df["pred_label"].to_numpy(dtype=object)

    for i in range(len(df)):
        p = preds[i]
        own[i] = ev_cols.get(p, np.zeros(len(df)))[i] if p in ev_cols else 0.0
        others = [(k, v[i]) for k, v in ev_cols.items() if k != p]
        if others:
            k, val = max(others, key=lambda kv: kv[1])
            best_other[i], best_other_name[i] = val, k
        else:
            best_other[i], best_other_name[i] = 0.0, None

    verdict = np.full(len(df), UNCERTAIN, dtype=object)
    verdict[(best_other - own) > conflict_margin] = CONFLICT
    verdict[(own >= support_thresh) & ((best_other - own) <= conflict_margin)] = SUPPORTED

    df["own_evidence"] = own
    df["rival_evidence"] = best_other
    df["rival_label"] = best_other_name
    df["audit"] = verdict
    df["flag"] = verdict != SUPPORTED       # 사람이 확인할 대상
    return df


def evaluate_audit(audited, results_writer=None, experiment="nesy_audit",
                   split="group_kfold", feature_set=""):
    """Audit 은 라벨을 바꾸지 않는다 -> 분류 지표는 Neural 과 동일하다.

    따라서 audit 의 가치는 오직 오류 탐지 능력으로 평가한다.
    """
    y = audited["true_label"].to_numpy(dtype=object)
    p = audited["pred_label"].to_numpy(dtype=object)
    m = evaluate.compute_metrics(y, p)
    m.update(evaluate.flag_metrics(y, p, audited["flag"].to_numpy()))

    # CONFLICT 만으로 flag 했을 때도 함께 본다 (더 보수적인 운용).
    conflict_only = evaluate.flag_metrics(
        y, p, (audited["audit"] == CONFLICT).to_numpy())

    if results_writer is not None:
        results_writer.add(experiment, "nesy_audit", split, feature_set, m,
                           notes="flag=CONFLICT|UNCERTAIN; conflict_only_prec={:.3f} rec={:.3f}"
                                 .format(conflict_only["flag_precision"],
                                         conflict_only["flag_recall"]))
    return m, conflict_only


def audit_breakdown(audited):
    """verdict x (정답 여부) 교차표. NeSy 가 실제로 뭘 잡는지 보여주는 핵심 표."""
    ok = audited["pred_label"] == audited["true_label"]
    tab = pd.crosstab(audited["audit"], np.where(ok, "correct", "error"))
    for c in ("correct", "error"):
        if c not in tab.columns:
            tab[c] = 0
    tab["error_rate"] = tab["error"] / (tab["correct"] + tab["error"])
    return tab
