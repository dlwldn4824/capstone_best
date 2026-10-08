"""얼굴 영상 심박 (rPPG, POS) — webapp/static/rppg.js 를 한 줄씩 옮긴 것.

웹앱이 브라우저에서 하는 계산과 **같은 계산**을 공개 데이터에 돌려
앱의 얼굴 체크를 검증하기 위해 있다. 한쪽을 고치면 다른 쪽도 고칠 것.

    Wang et al., "Algorithmic principles of remote PPG", IEEE TBME 2017 (POS)
"""
from __future__ import annotations

import numpy as np

FS = 30.0
F_LO, F_HI, F_STEP = 0.7, 3.0, 0.01        # 42–180 bpm


def resample(t, x, fs=FS):
    """시각이 고르지 않은 표본(t 초, x[N, k])을 fs Hz 로."""
    t = np.asarray(t, float)
    x = np.asarray(x, float)
    n = int(np.floor((t[-1] - t[0]) * fs))
    tt = t[0] + np.arange(n) / fs
    if x.ndim == 1:
        return np.interp(tt, t, x)
    return np.stack([np.interp(tt, t, x[:, j]) for j in range(x.shape[1])], axis=1)


def pos(rgb, fs=FS):
    """rgb[N, 3] (fs Hz) → 맥파 신호."""
    N, l = len(rgb), int(round(1.6 * fs))
    H = np.zeros(N)
    for n in range(0, N - l + 1):
        c = rgb[n:n + l] / rgb[n:n + l].mean(axis=0)
        s1 = c[:, 1] - c[:, 2]
        s2 = c[:, 1] + c[:, 2] - 2 * c[:, 0]
        alpha = s1.std() / (s2.std() or 1.0)
        h = s1 + alpha * s2
        H[n:n + l] += h - h.mean()
    return detrend(H, fs)


def detrend(x, fs=FS):
    """±1초 이동평균을 뺀다 (rppg.js 와 같은 창)."""
    w = int(round(fs))
    k = np.ones(2 * w + 1)
    num = np.convolve(x, k, mode="same")
    den = np.convolve(np.ones_like(x), k, mode="same")
    return x - num / den


_FREQS = np.arange(F_LO, F_HI + 1e-9, F_STEP)


def peak(x, fs=FS):
    """0.7–3.0 Hz 에서 가장 센 주파수 → (bpm, snr dB)."""
    k = np.arange(len(x))
    ph = 2 * np.pi * np.outer(_FREQS, k) / fs
    re = (x * np.cos(ph)).sum(1)
    im = -(x * np.sin(ph)).sum(1)
    p = re * re + im * im
    i = int(np.argmax(p))
    f0 = _FREQS[i]
    sig = p[(np.abs(_FREQS - f0) <= 0.1) | (np.abs(_FREQS - 2 * f0) <= 0.1)].sum()
    snr = 10 * np.log10(sig / max(1e-12, p.sum() - sig))
    return f0 * 60, snr


def estimate(t, rgb, fs=FS):
    """프레임 시각 t(초) · 평균 RGB → (bpm, snr). 8초 미만이면 None."""
    if t[-1] - t[0] < 8:
        return None
    r = resample(t, rgb, fs)
    return peak(pos(r, fs), fs)


def ppg_hr(t, ppg, fs=FS):
    """정답 PPG → 같은 주파수 분석으로 심박 (정답값)."""
    x = resample(t, ppg, fs)
    x = detrend(x - x.mean(), fs)
    return peak(x, fs)


def to_lab(rgb):
    """sRGB 0–255 → CIELAB (D65). rppg.js toLab 과 같다."""
    def lin(c):
        c = c / 255.0
        return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    R, G, B = (lin(np.asarray(rgb[..., i], float)) for i in range(3))
    X = (0.4124 * R + 0.3576 * G + 0.1805 * B) / 0.95047
    Y = 0.2126 * R + 0.7152 * G + 0.0722 * B
    Z = (0.0193 * R + 0.1192 * G + 0.9505 * B) / 1.08883

    def f(v):
        return np.where(v > 0.008856, np.cbrt(v), 7.787 * v + 16 / 116)
    return 116 * f(Y) - 16, 500 * (f(X) - f(Y)), 200 * (f(Y) - f(Z))


def app_scan(t, rgb, t0, min_s=8, max_s=20, stable_bpm=3, stable_n=3, min_snr=0.0):
    """웹앱의 얼굴 체크를 그대로 흉내 낸다: t0 부터 시작해 8초 뒤 1초마다 추정,
    마지막 3번이 ±3 bpm 안이고 SNR ≥ 0 이면 멈춤, 아니면 20초에 멈춤.
    반환 (bpm, snr, 걸린 초, 조기 종료 여부)."""
    ests = []
    s = float(min_s)
    while s <= max_s + 1e-9:
        m = (t >= t0) & (t < t0 + s)
        e = estimate(t[m], rgb[m])
        if e:
            ests.append(e)
        last = ests[-stable_n:]
        if (len(last) == stable_n and max(b for b, _ in last) - min(b for b, _ in last) <= stable_bpm
                and all(q >= min_snr for _, q in last)):
            return last[-1][0], last[-1][1], s, True
        s += 1.0
    final = ests[-1] if ests else (np.nan, np.nan)
    return final[0], final[1], float(max_s), False
