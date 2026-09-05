"""EDA -> low-pass -> tonic/phasic 분해 -> SCR event.

cvxEDA 대신 필터 기반 분해를 쓴다. 이유
  - 의존성이 scipy 하나로 끝나 재현이 쉽다.
  - 4 Hz E4 EDA 에서 cvxEDA 의 이점이 크지 않다.
  - 분해 방법 자체가 연구 질문이 아니다.
한계로 보고서에 적을 것: tonic/phasic 분리가 cutoff(0.05 Hz)에 의존한다.

담당: 역할 A (데이터/전처리)
"""
from __future__ import annotations

import numpy as np
from scipy import signal as sps

NAN = float("nan")


def lowpass(x, fs, cutoff=1.0, order=4):
    x = np.asarray(x, dtype=float)
    nyq = fs / 2.0
    if len(x) < 3 * order * 2 or cutoff >= nyq:
        return x
    b, a = sps.butter(order, cutoff / nyq, btype="low")
    return sps.filtfilt(b, a, x)


def decompose(x, fs, tonic_cutoff=0.05, order=2):
    """(tonic, phasic) 분해.

    tonic  = 0.05 Hz 이하 저역 성분 (skin conductance level)
    phasic = 나머지 (skin conductance response)
    """
    x = np.asarray(x, dtype=float)
    nyq = fs / 2.0
    if len(x) < 3 * order * 2 or tonic_cutoff >= nyq:
        return x, np.zeros_like(x)
    b, a = sps.butter(order, tonic_cutoff / nyq, btype="low")
    tonic = sps.filtfilt(b, a, x)
    return tonic, x - tonic


def scr_events(phasic, fs, min_amplitude=0.01, min_distance_sec=1.0):
    """phasic 성분에서 SCR peak 를 찾아 이벤트 특성을 계산한다.

    rise time    = onset(직전 국소최소) -> peak 까지 시간
    recovery time= peak -> 진폭이 50% 로 떨어질 때까지 시간 (half recovery)
    """
    phasic = np.asarray(phasic, dtype=float)
    n = len(phasic)
    if n < int(fs * 2):
        return []
    dist = max(1, int(fs * min_distance_sec))
    peaks, _ = sps.find_peaks(phasic, distance=dist, prominence=min_amplitude)

    events = []
    for p in peaks:
        # onset: peak 왼쪽으로 가면서 값이 다시 올라가기 시작하는 지점
        i = p
        while i > 0 and phasic[i - 1] <= phasic[i]:
            i -= 1
        onset = i
        amp = float(phasic[p] - phasic[onset])
        if amp < min_amplitude:
            continue
        half = phasic[onset] + amp / 2.0
        j = p
        while j < n - 1 and phasic[j] > half:
            j += 1
        events.append({
            "onset_sample": int(onset),
            "peak_sample": int(p),
            "amplitude": amp,
            "rise_time": float((p - onset) / fs),
            "recovery_time": float((j - p) / fs),
        })
    return events


def _ratio_up_down(x, fs):
    """단조 증가/감소 구간의 평균 변화율 (원 논문 change-ratio feature)."""
    if len(x) < 2:
        return NAN, NAN
    d = np.diff(x) * fs
    up = d[d > 0]
    down = d[d < 0]
    return (float(np.mean(up)) if len(up) else 0.0,
            float(np.mean(down)) if len(down) else 0.0)


FEATURE_KEYS = (
    "mean_raw_eda", "std_raw_eda",
    "mean_tonic_eda", "std_tonic_eda",
    "mean_phasic_eda", "std_phasic_eda",
    "tonic_ratio_up", "tonic_ratio_down",
    "peaks_density", "mean_amplitude", "mean_onset_sample",
    "mean_peak_sample", "mean_risetime", "mean_recoverytime",
)


def process(eda, fs, cfg):
    """EDA 한 윈도 -> 중간 산출물 + feature dict (13개 + std_raw)."""
    e = cfg["eda"]
    eda = np.asarray(eda, dtype=float)
    if len(eda) == 0:
        return {"clean": eda, "tonic": eda, "phasic": eda, "events": [],
                "features": {k: NAN for k in FEATURE_KEYS}}

    clean = lowpass(eda, fs, e["lowpass_hz"])
    tonic, phasic = decompose(clean, fs, e["tonic_cutoff_hz"])
    events = scr_events(phasic, fs, e["scr_min_amplitude"],
                        e["scr_min_distance_sec"])

    dur = len(eda) / fs
    up, down = _ratio_up_down(tonic, fs)

    def mean_of(key):
        return float(np.mean([ev[key] for ev in events])) if events else 0.0

    feats = {
        "mean_raw_eda": float(np.mean(clean)),
        "std_raw_eda": float(np.std(clean, ddof=1)) if len(clean) > 1 else NAN,
        "mean_tonic_eda": float(np.mean(tonic)),
        "std_tonic_eda": float(np.std(tonic, ddof=1)) if len(tonic) > 1 else NAN,
        "mean_phasic_eda": float(np.mean(phasic)),
        "std_phasic_eda": float(np.std(phasic, ddof=1)) if len(phasic) > 1 else NAN,
        "tonic_ratio_up": up,
        "tonic_ratio_down": down,
        "peaks_density": float(len(events) / dur * 60.0) if dur > 0 else NAN,
        "mean_amplitude": mean_of("amplitude"),
        "mean_onset_sample": mean_of("onset_sample"),
        "mean_peak_sample": mean_of("peak_sample"),
        "mean_risetime": mean_of("rise_time"),
        "mean_recoverytime": mean_of("recovery_time"),
    }
    return {"clean": clean, "tonic": tonic, "phasic": phasic,
            "events": events, "features": feats}
