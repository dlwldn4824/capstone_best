from __future__ import annotations

import numpy as np

from wesad_phase1.constants import LABEL_FS, REST, STRESS, WESAD_BASELINE, WESAD_STRESS
from wesad_phase1.features import extract_features
from wesad_phase1.loader import WristRecording
from wesad_phase1.windows import iter_windows


def _synthetic_recording() -> WristRecording:
    duration = 180.0
    t_bvp = np.arange(0, duration, 1 / 64)
    hr_rest = 70 / 60
    hr_stress = 95 / 60
    bvp = np.sin(2 * np.pi * hr_rest * t_bvp)
    bvp[t_bvp >= 90] = np.sin(2 * np.pi * hr_stress * t_bvp[t_bvp >= 90])
    t_eda = np.arange(0, duration, 1 / 4)
    eda = np.ones_like(t_eda) * 0.4
    eda[t_eda >= 90] = 1.2
    t_temp = np.arange(0, duration, 1 / 4)
    temp = np.linspace(32.5, 32.4, t_temp.size)
    t_acc = np.arange(0, duration, 1 / 32)
    acc = np.column_stack(
        [
            np.ones_like(t_acc),
            np.zeros_like(t_acc),
            np.zeros_like(t_acc),
        ]
    )
    labels = np.full(int(duration * LABEL_FS), WESAD_BASELINE, dtype=np.int16)
    labels[int(90 * LABEL_FS) :] = WESAD_STRESS
    return WristRecording(
        subject_id="S2",
        bvp=bvp.astype(np.float32),
        eda=eda.astype(np.float32),
        temp=temp.astype(np.float32),
        acc=acc.astype(np.float32),
        label=labels,
    )


def test_windows_are_pure_rest_or_stress():
    rec = _synthetic_recording()
    metas = list(iter_windows(rec, window_sec=60, hop_sec=30, min_purity=1.0))
    assert metas, "expected at least one window"
    ys = {meta.y for meta, _ in metas}
    assert ys <= {REST, STRESS}
    for meta, window in metas:
        uniq = set(np.unique(window["label"]).tolist())
        assert uniq <= {WESAD_BASELINE, WESAD_STRESS}
        assert meta.purity == 1.0


def test_feature_names_and_hr_direction():
    rec = _synthetic_recording()
    rest = rec.slice_window(10, 60)
    stress = rec.slice_window(110, 60)
    rest_f = extract_features(rest)
    stress_f = extract_features(stress)
    assert rest_f["HR_mean"] < stress_f["HR_mean"]
    assert stress_f["EDA_mean"] > rest_f["EDA_mean"]
    for key in (
        "HR_mean",
        "RMSSD",
        "EDA_mean",
        "SCL_mean",
        "SCR_count",
        "TEMP_mean",
        "TEMP_slope",
        "ACC_magnitude_mean",
        "ACC_energy",
    ):
        assert key in rest_f
