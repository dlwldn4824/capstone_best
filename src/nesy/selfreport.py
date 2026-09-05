"""자기보고 스트레스 점수(1-10) 연결.

데이터셋 루트의 Stress_Level_v1.csv / Stress_Level_v2.csv 는 프로토콜 단계마다
참가자가 스스로 매긴 스트레스 점수를 담고 있다. 지금까지 쓰지 않던 자료인데,
휴식↔스트레스 오분류 85% 를 해석하는 데 결정적이다.

    v1  baseline 3.4 -> 과제 4.4   (차이 1.0)
    v2  baseline 3.3 -> 과제 4.7   (휴식 2.5 대비 2.2)

v1 에서는 참가자 본인이 baseline 과 과제의 차이를 10점 척도에서 1점밖에
느끼지 못했다. 모델이 못 맞히는 것이 아니라 스트레스가 잘 유발되지 않은 것이다.

--- 단계명 대응 ---------------------------------------------------------
공식 단계 수와 우리가 태그에서 얻은 구간 수가 다르다. 확실한 것만 잇고
불확실한 것은 NaN 으로 둔다 (억지로 매칭해 잘못된 값을 넣지 않는다).

v2 (공식 7단계 / 관측 8구간) — 깔끔하게 대응됨
    opinion2 는 26초로 앞뒤(38초)보다 짧고, HR 상승도 opinion3 이 더 크다
    (+2.8 vs +3.8). 자기보고에서도 Opposite Opinion(4.2) > Real Opinion(3.6)
    이므로 opinion1=Real, opinion3=Opposite, opinion2=전이 구간으로 본다.

v1 (공식 8단계 / 관측 12구간) — 짧은 블록의 정체가 불확실
    baseline / stroop / rest1 / tmct / rest2 는 확실하다.
    뒤쪽 32초 블록 6개가 Real Opinion, Opposite Opinion, Subtract 세 단계에
    대응하는데 1:1 이 아니다. 개별 대응을 단정하지 않고, 세 단계의 평균을
    approximate 값으로 붙이되 approx 플래그를 세운다. wrap1/wrap2 는 HR 상승이
    없어(+0.3, -0.2) 과제가 아니므로 NaN.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# 구간명 -> 공식 단계명. None = 대응 불가(NaN).
# 리스트면 그 단계들의 평균을 쓰고 approx=True 로 표시한다.
STAGE_MAP = {
    "v1": {
        "baseline": "Baseline",
        "stroop_a": "Stroop",
        "stroop_b": "Stroop",
        "rest1":    "First Rest",
        "tmct":     "TMCT",
        "rest2":    "Second Rest",
        "task1":    ["Real Opinion", "Opposite Opinion", "Subtract"],
        "task2":    ["Real Opinion", "Opposite Opinion", "Subtract"],
        "task3":    ["Real Opinion", "Opposite Opinion", "Subtract"],
        "task4":    ["Real Opinion", "Opposite Opinion", "Subtract"],
        "wrap1":    None,
        "wrap2":    None,
    },
    "v2": {
        "baseline":    "Baseline",
        "tmct":        "TMCT",
        "rest_video1": "First Rest",
        "opinion1":    "Real Opinion",
        "opinion2":    None,            # 26초 전이 구간
        "opinion3":    "Opposite Opinion",
        "rest_video2": "Second Rest",
        "subtract":    "Subtract",
    },
}

BASELINE_STAGE = "Baseline"


def load_tables(raw_root):
    """Stress_Level_v1/v2.csv 를 읽는다. 데이터셋 루트는 Wearable_Dataset 의 부모."""
    root = Path(raw_root)
    if root.name == "Wearable_Dataset":
        root = root.parent
    out = {}
    for v, name in (("v1", "Stress_Level_v1.csv"), ("v2", "Stress_Level_v2.csv")):
        p = root / name
        if not p.exists():
            continue
        d = pd.read_csv(p, index_col=0)
        d.index = [str(i).strip() for i in d.index]
        d.columns = [str(c).strip() for c in d.columns]
        out[v] = d.apply(lambda s: pd.to_numeric(s, errors="coerce"))
    return out


def build_table(raw_root):
    """(subject_id, version, segment_name) -> 자기보고 점수 테이블."""
    tables = load_tables(raw_root)
    rows = []
    for v, d in tables.items():
        smap = STAGE_MAP.get(v, {})
        for subj in d.index:
            base = d.loc[subj].get(BASELINE_STAGE, np.nan)
            for seg, stage in smap.items():
                if stage is None:
                    val, approx = np.nan, False
                elif isinstance(stage, list):
                    have = [s for s in stage if s in d.columns]
                    val = float(d.loc[subj, have].mean()) if have else np.nan
                    approx = True
                else:
                    val = float(d.loc[subj, stage]) if stage in d.columns else np.nan
                    approx = False
                rows.append({
                    "subject_id": subj, "version": v, "segment_name": seg,
                    "self_report": val,
                    "self_report_delta": (val - base) if np.isfinite(val)
                                          and np.isfinite(base) else np.nan,
                    "self_report_approx": approx,
                })
    return pd.DataFrame(rows)


def attach(df, raw_root):
    """features DataFrame 에 자기보고 컬럼 3개를 붙인다."""
    tbl = build_table(raw_root)
    if tbl.empty:
        for c in ("self_report", "self_report_delta", "self_report_approx"):
            df[c] = np.nan
        return df
    return df.merge(tbl, on=["subject_id", "version", "segment_name"], how="left")


def coverage_summary(df):
    """어느 구간이 점수를 받았고 어디가 비었는지."""
    g = (df.groupby(["version", "segment_name", "condition"])
           .agg(n=("sample_id", "size"),
                self_report=("self_report", "mean"),
                delta=("self_report_delta", "mean"),
                approx=("self_report_approx", "max"))
           .reset_index())
    return g.sort_values(["version", "segment_name"])
