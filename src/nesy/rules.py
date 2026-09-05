"""Symbolic rule 정의 + coverage 측정.

규칙은 데이터로 학습하지 않고 생리학적 근거로 고정한다. 근거는
docs/RULES.md 에 논문 인용과 함께 적는다. 규칙을 데이터에 맞춰 튜닝하기
시작하면 그건 그냥 또 하나의 (성능 나쁜) 분류기이지 지식이 아니다.

담당: 역할 C (NeSy/Rule)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd


@dataclass
class Rule:
    name: str
    produces: str                 # EXERCISE_EVIDENCE / STRESS_EVIDENCE / ...
    weight: float
    condition: Callable[[pd.DataFrame], np.ndarray]
    rationale: str = ""
    citation: str = ""

    def fire(self, facts: pd.DataFrame) -> np.ndarray:
        return np.asarray(self.condition(facts), dtype=bool)


def _c(f, name):
    """facts 에서 불리언 컬럼을 안전하게 꺼낸다."""
    if name not in f.columns:
        return np.zeros(len(f), dtype=bool)
    return f[name].to_numpy(dtype=bool)


RULES = [
    Rule(
        name="R1_exercise_hr_activity",
        produces="EXERCISE_EVIDENCE", weight=1.0,
        condition=lambda f: _c(f, "HR_HIGH") & _c(f, "ACTIVITY_HIGH"),
        rationale=("심박수 상승이 큰 신체 움직임과 동반되면 그 상승은 운동에 의한 "
                   "대사 요구 증가로 설명된다. 활동량을 보지 않고 HR 상승만으로 "
                   "각성을 판정하면 안 된다는 것이 Mishra 2020 의 HROS 및 "
                   "Norman 2026 의 핵심 지적이다."),
        citation="Mishra 2020 (HROS); Norman 2026 (context-sensitive interpretation)"),
    Rule(
        name="R2_exercise_activity_only",
        produces="EXERCISE_EVIDENCE", weight=0.6,
        condition=lambda f: _c(f, "ACTIVITY_HIGH") & ~_c(f, "HR_HIGH"),
        rationale=("움직임은 크지만 HR 이 아직 오르지 않은 운동 초기/저강도 구간. "
                   "약한 운동 근거로만 취급한다."),
        citation="Hongn 2025 (aerobic 저rpm 블록)"),
    Rule(
        name="R3_stress_sympathetic",
        produces="STRESS_EVIDENCE", weight=1.0,
        condition=lambda f: (_c(f, "HR_HIGH") & _c(f, "HRV_LOW")
                             & _c(f, "EDA_HIGH") & _c(f, "ACTIVITY_LOW")),
        rationale=("교감신경 활성의 고전적 조합: HR 상승 + 미주신경 위축(RMSSD 감소) "
                   "+ 피부전도 상승. 결정적으로 '움직임이 없을 것'을 요구한다. "
                   "이 조건이 운동과 스트레스를 가르는 축이다."),
        citation="Hongn 2025 (stress/rest 13 features); Norman 2026"),
    Rule(
        name="R4_stress_electrodermal",
        produces="STRESS_EVIDENCE", weight=0.6,
        condition=lambda f: (_c(f, "SCR_HIGH") & _c(f, "ACTIVITY_LOW")
                             & ~_c(f, "HR_HIGH")),
        rationale=("EDA 는 순수 교감신경 지배라 심혈관 반응보다 먼저/독립적으로 "
                   "나타날 수 있다. HR 이 아직 안 올랐어도 정지 상태의 SCR 폭증은 "
                   "스트레스 근거가 된다."),
        citation="Norman 2026 (EDA = sympathetic-only)"),
    Rule(
        name="R5_rest",
        produces="REST_EVIDENCE", weight=1.0,
        condition=lambda f: (~_c(f, "HR_HIGH") & ~_c(f, "ACTIVITY_HIGH")
                             & ~_c(f, "EDA_HIGH")),
        rationale="세 축이 모두 개인 baseline 근처면 평상 상태 근거.",
        citation="Mishra 2020 (personal baseline)"),
]


def apply_rules(facts, rules=None):
    """facts -> evidence score DataFrame.

    같은 evidence 를 만드는 규칙들의 weight 를 더해 [0, 1] 로 정규화한다.
    (LTN 같은 미분가능 논리는 2차 확장으로 남긴다.)
    """
    rules = rules or RULES
    out = pd.DataFrame(index=facts.index)
    fired = {}
    for r in rules:
        f = r.fire(facts)
        fired[r.name] = f
        col = r.produces
        if col not in out:
            out[col] = 0.0
        out[col] = out[col] + f.astype(float) * r.weight

    for kind in ("EXERCISE_EVIDENCE", "STRESS_EVIDENCE", "REST_EVIDENCE"):
        if kind not in out:
            out[kind] = 0.0
        cap = sum(r.weight for r in rules if r.produces == kind) or 1.0
        out[kind] = (out[kind] / cap).clip(0.0, 1.0)

    for name, f in fired.items():
        out["fired_" + name] = f
    return out


def coverage(facts, labels, rules=None):
    """규칙별 발화율과 정밀도. Day 4 산출물.

    precision = 규칙이 발화한 샘플 중 의도한 클래스인 비율.
    낮으면 그 규칙은 지식이 아니라 잡음이다.
    """
    rules = rules or RULES
    target = {"EXERCISE_EVIDENCE": "EXERCISE", "STRESS_EVIDENCE": "STRESS",
              "REST_EVIDENCE": "REST"}
    labels = np.asarray(labels, dtype=object)
    rows = []
    for r in rules:
        f = r.fire(facts)
        tgt = target.get(r.produces)
        rows.append({
            "rule": r.name, "produces": r.produces, "weight": r.weight,
            "fire_rate": float(np.mean(f)),
            "n_fired": int(f.sum()),
            "precision": float(np.mean(labels[f] == tgt)) if f.sum() else np.nan,
            "recall": (float(np.mean(f[labels == tgt]))
                       if (labels == tgt).sum() else np.nan),
        })
    return pd.DataFrame(rows)


def rules_markdown(rules=None):
    """docs/RULES.md 의 규칙 표를 자동 생성한다 (코드와 문서 동기화)."""
    rules = rules or RULES
    lines = ["| Rule | Produces | Weight | 근거 | 인용 |",
             "| --- | --- | --- | --- | --- |"]
    for r in rules:
        lines.append("| `{}` | {} | {} | {} | {} |".format(
            r.name, r.produces, r.weight,
            r.rationale.replace("\n", " "), r.citation))
    return "\n".join(lines)
