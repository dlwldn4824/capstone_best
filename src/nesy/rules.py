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
    active: bool = True           # False = evidence 계산에서 제외, 보고에는 남김

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
        produces="EXERCISE_EVIDENCE", weight=0.6, active=False,
        condition=lambda f: _c(f, "ACTIVITY_HIGH") & ~_c(f, "HR_HIGH"),
        rationale=("**폐기.** 원래 근거는 '움직임은 크지만 HR 이 아직 오르지 않은 "
                   "운동 초기 구간'이었으나 두 가지로 기각됐다. (1) 문헌: 운동 개시 "
                   "시 HR 은 미주신경 위축으로 시상수 약 6.2초 만에 반응한다. "
                   "60초 윈도 안에서 '움직이는데 HR 은 그대로'인 구간은 존재하기 "
                   "어렵다. (2) 데이터: 이 규칙의 오탐 27건 중 23건이 v2 의 "
                   "13-14분짜리 영상 시청 휴식 구간이었다. 운동 개시가 아니라 "
                   "앉아서 몸을 뒤척인 것이다. 정밀도 0.519 로 무작위 수준. "
                   "적중과 오탐을 가르는 것은 HR 동태가 아니라 움직임의 크기였다 "
                   "(중앙값 42 mg vs 27 mg). -> R2b 로 대체."),
        citation="기각 근거: Fontolliet 2021 (phase I HR kinetics); 본 데이터 실측"),
    Rule(
        name="R2b_exercise_vigorous_movement",
        produces="EXERCISE_EVIDENCE", weight=0.6,
        condition=lambda f: _c(f, "ACTIVITY_VERY_HIGH"),
        rationale=("HR 조건 없이 움직임의 크기만으로 판정한다. 가속도 크기로 활동 "
                   "강도 구간을 나누는 것은 신체활동 연구의 표준이며 VO2 로 검증된 "
                   "기준값이 있다(MAD 91 mg = 3 MET, 414 mg = 6 MET). 즉 '이 정도 "
                   "움직이면 대사 요구가 올라간 것'이라는 판단은 심박수를 보지 않고도 "
                   "성립한다. 30초 스프린트처럼 HR 이 윈도 안에서 미처 따라오지 못한 "
                   "구간도 이 규칙이 잡는다. "
                   "주의: 문헌의 기준값은 보행·달리기를 전제로 유도된 것이라 손잡이를 "
                   "잡는 고정식 자전거에는 그대로 쓸 수 없다(본 데이터 운동 윈도 "
                   "중앙값 42 mg). 구간을 나눈다는 개념만 가져오고 값은 fold 안에서 "
                   "정밀도 0.85 기준으로 정한다."),
        citation=("Vähä-Ypyä 2015 PLOS ONE (MAD cut-points, VO2 검증); "
                  "Hildebrand 2014 (wrist ENMO 50/110/440 mg)")),
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
        name="R3b_stress_no_hrv",
        produces="STRESS_EVIDENCE", weight=1.0,
        condition=lambda f: (_c(f, "HR_HIGH") & _c(f, "EDA_HIGH")
                             & _c(f, "ACTIVITY_LOW")),
        rationale=("R3 에서 HRV_LOW 조건만 뺀 것. 실데이터에서 손목 PPG 기반 "
                   "RMSSD 는 스트레스에서 낮아지지 않았다 — 36명 중 18명만 "
                   "감소했고(정확히 우연 수준) 중앙값 차이는 -0.8 ms 였다. "
                   "교과서적 '스트레스 -> HRV 감소'가 이 측정 방식(손목 PPG, "
                   "60초 윈도)에서는 성립하지 않는다. R3 와 나란히 두고 "
                   "coverage 를 비교해 보고한다. R3 를 조용히 이것으로 "
                   "바꿔치기하지 않는다."),
        citation="본 데이터 실측 (outputs/tables/rule_coverage.csv)"),
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
            "active": r.active,
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
    lines = ["| Rule | 사용 | Produces | Weight | 근거 | 인용 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for r in rules:
        lines.append("| `{}` | {} | {} | {} | {} | {} |".format(
            r.name, "O" if r.active else "보고전용", r.produces, r.weight,
            r.rationale.replace("\n", " "), r.citation))
    return "\n".join(lines)
