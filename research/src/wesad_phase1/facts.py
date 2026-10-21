"""Map window features to discrete physiological facts for the symbolic layer.

Phase 1 does not train a neural fact generator yet. Facts are produced by
comparing each window to that subject's REST (BASELINE) median.
"""

from __future__ import annotations

import pandas as pd

from wesad_phase1.config import Phase1Config, load_config
from wesad_phase1.constants import FACT_COLUMNS, REST


def add_facts(df: pd.DataFrame, cfg: Phase1Config | None = None) -> pd.DataFrame:
    cfg = cfg or load_config()
    parts: list[pd.DataFrame] = []
    for _, group in df.groupby("subject_id", sort=True):
        parts.append(_facts_for_subject(group.copy(), cfg))
    out = pd.concat(parts, ignore_index=True)
    return out


def _facts_for_subject(df: pd.DataFrame, cfg: Phase1Config) -> pd.DataFrame:
    rest = df[df["y"] == REST]
    if rest.empty:
        for col in FACT_COLUMNS:
            df[col] = pd.NA
        return df

    hr0 = rest["HR_mean"].median()
    hrv0 = rest["RMSSD"].median()
    eda0 = rest["EDA_mean"].median()
    temp0 = rest["TEMP_mean"].median()
    acc0 = rest["ACC_energy"].median()

    hr_state = []
    hrv_state = []
    eda_state = []
    temp_state = []
    activity_state = []
    hr_up = []
    hrv_down = []
    eda_on = []
    act_low = []

    for row in df.itertuples(index=False):
        hr = _state_by_ratio(row.HR_mean, hr0, cfg.hr_high_ratio, high="HIGH", low="LOW")
        if pd.notna(row.RMSSD) and pd.notna(hrv0) and hrv0 > 0:
            if row.RMSSD < hrv0 * cfg.hrv_low_ratio:
                hrv = "LOW"
            elif row.RMSSD > hrv0 / cfg.hrv_low_ratio:
                hrv = "HIGH"
            else:
                hrv = "NORMAL"
        else:
            hrv = pd.NA
        eda = _state_by_ratio(row.EDA_mean, eda0, cfg.eda_high_ratio, high="HIGH", low="LOW")
        if pd.notna(row.TEMP_mean) and pd.notna(temp0):
            delta = row.TEMP_mean - temp0
            if delta >= cfg.temp_delta_c:
                temp = "HIGH"
            elif delta <= -cfg.temp_delta_c:
                temp = "LOW"
            else:
                temp = "NORMAL"
        else:
            temp = pd.NA
        # WESAD lab stress is seated. ACTIVITY_LOW means "not elevated vs REST",
        # which later becomes the stress vs exercise discriminator.
        if pd.isna(row.ACC_energy) or pd.isna(acc0) or acc0 == 0:
            act = pd.NA
        elif row.ACC_energy >= acc0 * cfg.activity_high_ratio:
            act = "HIGH"
        else:
            act = "LOW"

        hr_state.append(hr)
        hrv_state.append(hrv)
        eda_state.append(eda)
        temp_state.append(temp)
        activity_state.append(act)
        hr_up.append(bool(pd.notna(hr) and hr == "HIGH"))
        hrv_down.append(bool(pd.notna(hrv) and hrv == "LOW"))
        eda_on.append(bool(pd.notna(eda) and eda == "HIGH"))
        act_low.append(bool(pd.notna(act) and act == "LOW"))

    df["hr_state"] = hr_state
    df["hrv_state"] = hrv_state
    df["eda_state"] = eda_state
    df["temp_state"] = temp_state
    df["activity_state"] = activity_state
    df["HR_INCREASED"] = hr_up
    df["HRV_DECREASED"] = hrv_down
    df["EDA_ACTIVATED"] = eda_on
    df["ACTIVITY_LOW"] = act_low
    df["stress_rule_hit"] = (
        df["HR_INCREASED"]
        & df["HRV_DECREASED"]
        & df["EDA_ACTIVATED"]
        & df["ACTIVITY_LOW"]
    )
    return df


def _state_by_ratio(
    value: float,
    baseline: float,
    high_ratio: float,
    high: str,
    low: str,
) -> str:
    if pd.isna(value) or pd.isna(baseline) or baseline == 0:
        return pd.NA
    low_ratio = 1.0 / high_ratio
    if value >= baseline * high_ratio:
        return high
    if value <= baseline * low_ratio:
        return low
    return "NORMAL"
