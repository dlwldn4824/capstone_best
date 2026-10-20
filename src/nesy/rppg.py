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


# =============================================================================
# v2 — rPPG-Toolbox (Liu et al., NeurIPS 2023 Datasets & Benchmarks) 와 같은 처리 순서
# =============================================================================
# rPPG-Toolbox 의 라이선스는 Responsible AI License 라서 코드를 복사하지 않고
# 같은 단계 · 같은 값으로 새로 썼다. webapp/static/rppg.js 의 v2 와 한 줄씩 대응한다.
#   1. POS (Wang 2017): 1.6초 창, 창 평균으로 나눈 RGB 를 [0,1,-1] · [-2,1,1] 평면에 투영
#   2. smoothness-priors 추세 제거 (Tarvainen 2002), λ = 100
#   3. 1차 버터워스 대역 통과 0.75–3 Hz, 앞뒤 양방향(filtfilt)
#   4. 평가 단계와 같이 한 번 더: 추세 제거 λ=100 → 대역 통과 0.6–3.3 Hz
#   5. 2의 거듭제곱 길이로 0을 채운 주기도(periodogram) → 0.6–3.3 Hz 최고점 = 심박
#   6. SNR: 1·2차 고조파 ±6 bpm 안 에너지 / 나머지 (0.6–3.3 Hz)
V2_WIN = 1.6
V2_BAND_POS = (0.75, 3.0)
V2_BAND_EVAL = (0.6, 3.3)
V2_LAMBDA = 100.0
V2_SNR_DEV = 6 / 60


def detrend_sp(x, lam=V2_LAMBDA):
    """smoothness-priors 추세 제거: x − (I + λ² DᵀD)⁻¹ x  (D = 2차 차분)."""
    from scipy import sparse
    from scipy.sparse.linalg import spsolve
    x = np.asarray(x, float)
    n = len(x)
    if n < 3:
        return x - x.mean()
    D = sparse.diags([np.ones(n - 2), -2 * np.ones(n - 2), np.ones(n - 2)], [0, 1, 2], shape=(n - 2, n))
    A = sparse.identity(n) + lam ** 2 * (D.T @ D)
    return x - spsolve(A.tocsc(), x)


def bandpass(x, fs, lo, hi):
    from scipy import signal
    b, a = signal.butter(1, [lo / fs * 2, hi / fs * 2], btype="bandpass")
    return signal.filtfilt(b, a, np.asarray(x, float))


def pos_v2(rgb, fs=FS):
    """POS 원 논문 · rPPG-Toolbox 와 같은 창 처리 (창은 [n-l, n), l = ceil(1.6·fs))."""
    rgb = np.asarray(rgb, float)
    N, l = len(rgb), int(np.ceil(V2_WIN * fs))
    H = np.zeros(N)
    P = np.array([[0, 1, -1], [-2, 1, 1]], float)
    for n in range(l, N):
        m = n - l
        cn = (rgb[m:n] / rgb[m:n].mean(axis=0)).T
        S = P @ cn
        s1sd = S[1].std()
        h = S[0] + (S[0].std() / s1sd if s1sd > 0 else 0.0) * S[1]
        H[m:n] += h - h.mean()
    bvp = detrend_sp(H)
    return bandpass(bvp, fs, *V2_BAND_POS)


def _periodogram(x, fs):
    from scipy import signal
    n = 1 if len(x) == 0 else 2 ** int(np.ceil(np.log2(len(x))))
    return signal.periodogram(x, fs=fs, nfft=n, detrend=False)


def hr_snr_v2(bvp, fs=FS, lo=V2_BAND_EVAL[0], hi=V2_BAND_EVAL[1]):
    """평가 단계 그대로: 추세 제거 → 대역 통과 → 주기도 최고점. SNR 은 추정 심박의 고조파로."""
    x = bandpass(detrend_sp(bvp), fs, lo, hi)
    f, p = _periodogram(x, fs)
    band = (f >= lo) & (f <= hi)
    hr = float(f[band][np.argmax(p[band])] * 60)
    f1, f2 = hr / 60, 2 * hr / 60
    sig = band & ((np.abs(f - f1) <= V2_SNR_DEV) | (np.abs(f - f2) <= V2_SNR_DEV))
    rest = band & ~sig
    snr = 10 * np.log10(p[sig].sum() / max(p[rest].sum(), 1e-12))
    return hr, float(snr)


def estimate_v2(t, rgb, fs=FS):
    """프레임 시각 t(초) · 평균 RGB → (bpm, snr). 8초 미만이면 None."""
    if len(t) < 2 or t[-1] - t[0] < 8:
        return None
    r = resample(t, rgb, fs)
    return hr_snr_v2(pos_v2(r, fs), fs)


def ppg_hr_v2(t, ppg, fs=FS):
    """정답 PPG 도 같은 평가 단계로 (rPPG-Toolbox 가 정답 신호에 하는 그대로)."""
    x = resample(t, ppg, fs)
    return hr_snr_v2(x - x.mean(), fs)


# =============================================================================
# 안색 — 볼 붉은기(Lab a*)를 이마 대비 상대값으로 (기획 변경 보고서 FR-07)
# =============================================================================
def complexion(forehead_rgb, cheeks_rgb):
    """영역별 프레임 평균 RGB(N×3) → 안색 지표.

    a_rel   볼 a* − 이마 a*  — 같은 프레임 안의 차이라 조명 세기 · 자동 화이트밸런스가 크게 상쇄된다 (주 지표)
    a_cheek 볼 a* 절대값      — 비교용 (조명에 그대로 흔들린다)
    s_rel   HSV 채도 볼 − 이마 — 보고서의 대안 지표
    rg_rel  (R/G) 볼 − 이마    — 보고서의 대안 지표
    """
    f = np.asarray(forehead_rgb, float)
    c = np.asarray(cheeks_rgb, float)
    ok = np.isfinite(f).all(1) & np.isfinite(c).all(1)
    f, c = f[ok], c[ok]
    if len(f) == 0:
        return None
    _, af, _ = to_lab(f)
    _, ac, _ = to_lab(c)

    def sat(x):
        mx, mn = x.max(1), x.min(1)
        return np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-9), 0)

    return {
        "a_rel": float(np.median(ac - af)),
        "a_cheek": float(np.median(ac)),
        "s_rel": float(np.median(sat(c) - sat(f))),
        "rg_rel": float(np.median(c[:, 0] / c[:, 1] - f[:, 0] / f[:, 1])),
    }
