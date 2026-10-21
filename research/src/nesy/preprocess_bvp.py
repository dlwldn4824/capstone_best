"""BVP -> band-pass -> peak detection -> IBI -> HRV.

E4 의 IBI.csv 는 운동 세션에서 결측이 커서 쓰지 않고 BVP 에서 직접 검출한다
(원 논문 Hongn et al. 2025 와 동일한 결정).

담당: 역할 A (데이터/전처리)
"""
from __future__ import annotations

import numpy as np
from scipy import signal as sps

NAN = float("nan")


def bandpass(x, fs, lo=0.5, hi=10.0, order=4):
    """0.5-10 Hz zero-phase Butterworth."""
    x = np.asarray(x, dtype=float)
    if len(x) < 3 * order * 2:
        return x
    nyq = fs / 2.0
    hi = min(hi, nyq * 0.99)
    b, a = sps.butter(order, [lo / nyq, hi / nyq], btype="band")
    return sps.filtfilt(b, a, x)


def detect_peaks(x, fs, min_bpm=40, max_bpm=200):
    """맥박 peak 인덱스.

    prominence 를 신호 진폭에 맞춰 적응적으로 잡는다. 운동 중에는 BVP 진폭이
    크게 변하므로 고정 임계를 쓰면 sprint 구간에서 검출이 무너진다.
    """
    x = np.asarray(x, dtype=float)
    if len(x) < int(fs):
        return np.array([], dtype=int)
    min_dist = int(fs * 60.0 / max_bpm)
    prom = 0.3 * np.percentile(np.abs(x), 75)
    if not np.isfinite(prom) or prom <= 0:
        prom = None
    peaks, _ = sps.find_peaks(x, distance=max(1, min_dist), prominence=prom)
    return peaks


def peaks_to_ibi(peaks, fs, min_bpm=40, max_bpm=200, rel_thresh=0.30):
    """peak 인덱스 -> (IBI 초 배열, IBI 시각 배열).

    2단계 artefact 제거
      1) 생리적 범위(60/max_bpm ~ 60/min_bpm 초) 밖 제거
      2) **윈도 중앙값** 대비 변화율이 rel_thresh 를 넘으면 제거
         (ectopic beat, dicrotic notch 오검출, peak 누락)

    기준을 '직전 채택 IBI' 가 아니라 '중앙값' 으로 두는 것이 중요하다.
    직전 값을 기준으로 하면 첫 IBI 하나가 어긋났을 때 그 뒤가 연쇄로 무너진다.
    WESAD 손목 BVP 에서 실제로 그 일이 일어났다 — peak 은 96개(≈98 bpm, ECG 와
    일치)로 제대로 잡혔는데 채택된 IBI 가 5개뿐이었다. 중앙값 기준은 국소 오류가
    전체로 번지지 않는다.
    """
    peaks = np.asarray(peaks)
    if len(peaks) < 2:
        return np.array([]), np.array([])
    t = peaks / fs
    ibi = np.diff(t)
    tm = t[1:]

    lo, hi = 60.0 / max_bpm, 60.0 / min_bpm
    keep = (ibi >= lo) & (ibi <= hi)
    ibi, tm = ibi[keep], tm[keep]
    if len(ibi) < 2:
        return ibi, tm

    med = np.median(ibi)
    if not np.isfinite(med) or med <= 0:
        return ibi, tm
    keep2 = np.abs(ibi - med) / med <= rel_thresh
    return ibi[keep2], tm[keep2]


TIME_HRV_KEYS = ("ibi_mean", "ibi_max", "ibi_min", "hr_from_ibi",
                 "rmssd", "sdnn", "pnn20", "pnn50")


def time_domain_hrv(ibi):
    """시간영역 HRV 8개 (원 논문 구성)."""
    if len(ibi) < 2:
        return {k: NAN for k in TIME_HRV_KEYS}
    d = np.diff(ibi) * 1000.0   # ms
    return {
        "ibi_mean": float(np.mean(ibi)),
        "ibi_max": float(np.max(ibi)),
        "ibi_min": float(np.min(ibi)),
        "hr_from_ibi": float(60.0 / np.mean(ibi)),
        "rmssd": float(np.sqrt(np.mean(d ** 2))),
        "sdnn": float(np.std(ibi * 1000.0, ddof=1)),
        "pnn20": float(np.mean(np.abs(d) > 20.0) * 100.0),
        "pnn50": float(np.mean(np.abs(d) > 50.0) * 100.0),
    }


# VLF/LF/HF/VHF 대역 (Hz).
BANDS = {"VLF": (0.0033, 0.04), "LF": (0.04, 0.15),
         "HF": (0.15, 0.40), "VHF": (0.40, 0.50)}

FREQ_HRV_KEYS = tuple(
    ["{}_{}".format(b, s) for b in BANDS for s in ("power", "peak")]
    + ["total_power", "LF_n", "HF_n", "LF_HF_ratio"]
)


def freq_domain_hrv(ibi, tm, min_beats=30):
    """주파수영역 HRV 12개. 4 Hz 균등 재표본 + Welch PSD.

    한계 (보고서에 반드시 적을 것): 60초 윈도에서 VLF(0.0033-0.04 Hz)는 한
    주기도 담기지 않고 LF(0.04 Hz = 25초 주기)도 두 주기 남짓이다. 값은
    계산되지만 표준적인 HRV 해석을 붙이면 안 된다.
    """
    nan_out = {k: NAN for k in FREQ_HRV_KEYS}
    if len(ibi) < min_beats:
        return nan_out

    fs_i = 4.0
    t_uniform = np.arange(tm[0], tm[-1], 1.0 / fs_i)
    if len(t_uniform) < 16:
        return nan_out
    x = np.interp(t_uniform, tm, ibi)
    x = x - np.mean(x)
    nperseg = min(len(x), int(fs_i * 60))
    f, pxx = sps.welch(x, fs=fs_i, nperseg=nperseg)

    out, powers = {}, {}
    trapz = getattr(np, "trapezoid", None) or np.trapz
    for name, (lo, hi) in BANDS.items():
        m = (f >= lo) & (f < hi)
        p = float(trapz(pxx[m], f[m])) if m.sum() > 1 else 0.0
        powers[name] = p
        out[name + "_power"] = p
        out[name + "_peak"] = float(f[m][np.argmax(pxx[m])]) if m.sum() else NAN

    out["total_power"] = sum(powers.values())
    lf, hf = powers["LF"], powers["HF"]
    out["LF_n"] = float(lf / (lf + hf)) if (lf + hf) > 0 else NAN
    out["HF_n"] = float(hf / (lf + hf)) if (lf + hf) > 0 else NAN
    out["LF_HF_ratio"] = float(lf / hf) if hf > 0 else NAN
    return out


def process(bvp, fs, cfg):
    """BVP 한 윈도를 처리해 중간 산출물 + feature dict 를 돌려준다."""
    h = cfg["hrv"]
    bvp = np.asarray(bvp, dtype=float)
    filt = bandpass(bvp, fs, h["bandpass"][0], h["bandpass"][1])
    peaks = detect_peaks(filt, fs, h["min_bpm"], h["max_bpm"])
    ibi, tm = peaks_to_ibi(peaks, fs, h["min_bpm"], h["max_bpm"],
                           h["ibi_rel_thresh"])

    feats = {
        "bvp_mean": float(np.mean(bvp)) if len(bvp) else NAN,
        "bvp_std": float(np.std(bvp, ddof=1)) if len(bvp) > 1 else NAN,
    }
    feats.update(time_domain_hrv(ibi))
    feats.update(freq_domain_hrv(ibi, tm, h["min_beats_for_freq"]))
    feats["n_beats"] = float(len(ibi))
    return {"filtered": filt, "peaks": peaks, "ibi": ibi, "ibi_t": tm,
            "features": feats}


# feature_extraction 이 컬럼 순서를 고정하는 데 쓴다.
FEATURE_KEYS = (("bvp_mean", "bvp_std") + TIME_HRV_KEYS + FREQ_HRV_KEYS
                + ("n_beats",))
