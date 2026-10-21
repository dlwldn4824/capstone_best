"""Locked Phase-1 constants. Do not expand labels or sensors here."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs" / "phase1.yaml"

# WESAD subjects: S1 and S12 are absent in the official release.
SUBJECTS: tuple[str, ...] = tuple(f"S{i}" for i in range(2, 18) if i != 12)

WRIST_FS: dict[str, int] = {
    "BVP": 64,
    "EDA": 4,
    "TEMP": 4,
    "ACC": 32,
}
LABEL_FS = 700

# Official WESAD protocol IDs (sampled at 700 Hz).
WESAD_BASELINE = 1
WESAD_STRESS = 2
WESAD_AMUSEMENT = 3

# Phase-1 binary labels.
REST = 0
STRESS = 1

SUBJECT_SPLIT: dict[str, tuple[str, ...]] = {
    "train": ("S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11"),
    "val": ("S13", "S14"),
    "test": ("S15", "S16", "S17"),
}

FEATURE_COLUMNS: tuple[str, ...] = (
    "HR_mean",
    "HR_std",
    "HR_min",
    "HR_max",
    "RMSSD",
    "SDNN",
    "mean_IBI",
    "EDA_mean",
    "EDA_std",
    "SCL_mean",
    "SCR_count",
    "SCR_mean_amplitude",
    "TEMP_mean",
    "TEMP_std",
    "TEMP_slope",
    "ACC_magnitude_mean",
    "ACC_magnitude_std",
    "ACC_energy",
)

FACT_COLUMNS: tuple[str, ...] = (
    "hr_state",
    "hrv_state",
    "eda_state",
    "temp_state",
    "activity_state",
    "HR_INCREASED",
    "HRV_DECREASED",
    "EDA_ACTIVATED",
    "ACTIVITY_LOW",
)

# Official mirrors. UCI only hosts a tiny pointer file.
WESAD_URLS: tuple[str, ...] = (
    "https://uni-siegen.sciebo.de/s/HGdUkoNlW1Ub0Gx/download",
    "https://uni-siegen.sciebo.de/public.php/dav/files/HGdUkoNlW1Ub0Gx",
    "https://uni-siegen.sciebo.de/s/pYjSgfOVs6Ntahr/download",
)
WESAD_ZIP_MIN_BYTES = 2_000_000_000
