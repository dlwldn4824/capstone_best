"""Handcrafted Phase-1 features. Each signal stays at its native sampling rate.

BVP-derived IBI/HRV is a pulse-interval estimate, not an ECG RR interval.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.signal import butter, filtfilt, find_peaks
from scipy.stats import linregress

from wesad_phase1.constants import WRIST_FS

MIN_HR_BPM = 40.0
MAX_HR_BPM = 180.0
MIN_IBI_COUNT = 20


def extract_features(window: dict[str, np.ndarray]) -> dict[str, Any]:
    bvp = np.asarray(window["bvp"], dtype=np.float64).reshape(-1)
    eda = np.asarray(window["eda"], dtype=np.float64).reshape(-1)
    temp = np.asarray(window["temp"], dtype=np.float64).reshape(-1)
    acc = np.asarray(window["acc"], dtype=np.float64)
    hr = _bvp_hr_hrv(bvp, WRIST_FS["BVP"])
    eda_feats = _eda_features(eda, WRIST_FS["EDA"])
    temp_feats = _temp_features(temp, WRIST_FS["TEMP"])
    acc_feats = _acc_features(acc)
    return {**hr, **eda_feats, **temp_feats, **acc_feats}


def _bvp_hr_hrv(bvp: np.ndarray, fs: int) -> dict[str, float]:
    nan_hr = {
        "HR_mean": np.nan,
        "HR_std": np.nan,
        "HR_min": np.nan,
        "HR_max": np.nan,
        "RMSSD": np.nan,
        "SDNN": np.nan,
        "mean_IBI": np.nan,
        "n_ibi": 0,
        "bvp_quality": 0,
    }
    if bvp.size < fs * 10:
        return nan_hr
    filtered = _bandpass(bvp, fs, 0.5, 8.0, order=2)
    min_dist = int(fs * 60.0 / MAX_HR_BPM)
    prominence = max(float(np.std(filtered) * 0.4), 1e-6)
    peaks, _ = find_peaks(filtered, distance=min_dist, prominence=prominence)
    if peaks.size < 3:
        return nan_hr
    ibi_ms = np.diff(peaks.astype(np.float64)) / fs * 1000.0
    ibi_ms = ibi_ms[(ibi_ms >= 60_000 / MAX_HR_BPM) & (ibi_ms <= 60_000 / MIN_HR_BPM)]
    ibi_ms = _reject_ibi_outliers(ibi_ms)
    if ibi_ms.size < 3:
        return nan_hr
    hr_series = 60_000.0 / ibi_ms
    success = int(ibi_ms.size >= MIN_IBI_COUNT)
    return {
        "HR_mean": float(np.mean(hr_series)),
        "HR_std": float(np.std(hr_series, ddof=1)) if hr_series.size > 1 else 0.0,
        "HR_min": float(np.min(hr_series)),
        "HR_max": float(np.max(hr_series)),
        "RMSSD": float(np.sqrt(np.mean(np.diff(ibi_ms) ** 2))) if ibi_ms.size > 1 else np.nan,
        "SDNN": float(np.std(ibi_ms, ddof=1)) if ibi_ms.size > 1 else np.nan,
        "mean_IBI": float(np.mean(ibi_ms)),
        "n_ibi": int(ibi_ms.size),
        "bvp_quality": success,
    }


def _reject_ibi_outliers(ibi_ms: np.ndarray, rel_thresh: float = 0.20) -> np.ndarray:
    """Drop pulse intervals that jump more than 20% from the previous interval.

    Wrist BVP peaks jitter more than ECG R-peaks; unfiltered RMSSD is often
    inflated and should not be treated as an ECG HRV equivalent.
    """
    if ibi_ms.size < 3:
        return ibi_ms
    keep = np.ones(ibi_ms.size, dtype=bool)
    prev = ibi_ms[0]
    for i in range(1, ibi_ms.size):
        if abs(ibi_ms[i] - prev) / prev > rel_thresh:
            keep[i] = False
        else:
            prev = ibi_ms[i]
    return ibi_ms[keep]


def _eda_features(eda: np.ndarray, fs: int) -> dict[str, float]:
    if eda.size < fs * 5:
        return {
            "EDA_mean": np.nan,
            "EDA_std": np.nan,
            "SCL_mean": np.nan,
            "SCR_count": np.nan,
            "SCR_mean_amplitude": np.nan,
        }
    # Light denoising; keep native 4 Hz grid.
    clean = _lowpass(eda, fs, cutoff=1.0, order=2)
    scl = _lowpass(clean, fs, cutoff=0.05, order=2)
    phasic = clean - scl
    min_dist = max(int(fs * 1.0), 1)
    height = max(float(np.std(phasic) * 0.5), 0.02)
    peaks, props = find_peaks(phasic, distance=min_dist, height=height)
    amplitudes = props.get("peak_heights", np.array([]))
    return {
        "EDA_mean": float(np.mean(clean)),
        "EDA_std": float(np.std(clean, ddof=1)) if clean.size > 1 else 0.0,
        "SCL_mean": float(np.mean(scl)),
        "SCR_count": int(peaks.size),
        "SCR_mean_amplitude": float(np.mean(amplitudes)) if amplitudes.size else 0.0,
    }


def _temp_features(temp: np.ndarray, fs: int) -> dict[str, float]:
    if temp.size < 4:
        return {"TEMP_mean": np.nan, "TEMP_std": np.nan, "TEMP_slope": np.nan}
    t = np.arange(temp.size, dtype=np.float64) / fs
    slope = float(linregress(t, temp).slope)
    return {
        "TEMP_mean": float(np.mean(temp)),
        "TEMP_std": float(np.std(temp, ddof=1)) if temp.size > 1 else 0.0,
        "TEMP_slope": slope,
    }


def _acc_features(acc: np.ndarray) -> dict[str, float]:
    if acc.ndim != 2 or acc.shape[1] != 3 or acc.shape[0] < 8:
        return {
            "ACC_magnitude_mean": np.nan,
            "ACC_magnitude_std": np.nan,
            "ACC_energy": np.nan,
        }
    mag = np.sqrt(np.sum(acc ** 2, axis=1))
    return {
        "ACC_magnitude_mean": float(np.mean(mag)),
        "ACC_magnitude_std": float(np.std(mag, ddof=1)) if mag.size > 1 else 0.0,
        "ACC_energy": float(np.mean(mag ** 2)),
    }


def _bandpass(x: np.ndarray, fs: int, low: float, high: float, order: int = 2) -> np.ndarray:
    nyq = 0.5 * fs
    b, a = butter(order, [low / nyq, high / nyq], btype="band")
    return filtfilt(b, a, x)


def _lowpass(x: np.ndarray, fs: int, cutoff: float, order: int = 2) -> np.ndarray:
    nyq = 0.5 * fs
    wn = min(cutoff / nyq, 0.99)
    b, a = butter(order, wn, btype="low")
    return filtfilt(b, a, x)
