"""30초 얼굴 스캔 → 심박 · 호흡 · 심박변이도(HRV) · 스트레스 지수 · 불규칙 여부 (대학생 헬스체크).

브라우저 webapp/static/vitals.js 와 **같은 계산**이다. 한쪽을 고치면 다른 쪽도 고칠 것
(tests/test_vitals.py 의 기준값이 둘을 묶는다). 공개 데이터 검증: scripts/27_vitals.py.

    맥파       rPPG POS (rppg.pos_v2 — rPPG-Toolbox 처리 순서)
    박동       내 심박 ±0.4 Hz 로 좁힌 맥파의 극대점 + 3점 포물선 보간(1/30초보다 촘촘하게) + 최소 간격
    박동 간격  0.33–1.5초 밖 · 전체 중앙값 ±30% · 이웃 5개 중앙값 ±20% 밖은 버린다
    HRV       RMSSD · SDNN · pNN50 (Task Force 1996), 인접한 두 간격이 모두 살아 있을 때만 차분
    스트레스   Baevsky 스트레스 지수 SI = AMo / (2·Mo·MxDMn), 50 ms 구간 히스토그램
    호흡      맥파의 기저선(RIIV) · 진폭(RIAV) · 간격(RIFV) 변조를 각각 0.1–0.5 Hz 스펙트럼 최고점으로,
              품질 좋은 것끼리 맞으면 평균 (Karlen 2013 'smart fusion' 방식)

진단 기기가 아니다. 혈압 · 산소포화도 · 체온 · 피부나이는 일부러 재지 않는다 (docs/app/CHECK_DESIGN.md).
"""
from __future__ import annotations

import math

import numpy as np

from . import rppg as R

FS = 30.0
IBI_MIN, IBI_MAX = 0.33, 1.5          # 40–180 bpm
GLOBAL_DEV, LOCAL_DEV = 0.30, 0.20
RESP_FS = 4.0
RESP_BAND = (0.1, 0.5)                # 6–30 회/분
SI_LO, SI_HI = 50.0, 1000.0           # 스트레스 점수 0 · 100 이 되는 SI (Baevsky: 안정 50–150, 긴장 >500)


# --- 박동 찾기 -------------------------------------------------------------------
BEAT_BW, BEAT_PASSES = 0.4, 2         # 심박 주파수 ±0.4 Hz 를 1차 Butterworth 로 두 번 (MCD-rPPG 에서 고름, 27_vitals.py)


def beat_signal(bvp, fs, hr_bpm):
    """박동 시각용 맥파: 추세 제거 → 내 심박 주변만 남긴다. 넓은 대역 그대로면 박동 시각이 ±40 ms 흔들려 RMSSD 가 2.7배로 부푼다."""
    f0 = hr_bpm / 60
    y = R.detrend_sp(bvp)
    for _ in range(BEAT_PASSES):
        y = R.bandpass(y, fs, max(0.5, f0 - BEAT_BW), f0 + BEAT_BW)
    return (y - y.mean()) / (y.std() or 1)

def find_beats(x, fs, hr_bpm):
    """극대점 → 높은 것부터 최소 간격(0.5 주기) 지키며 채택 → 포물선 보간한 시각(초) · 높이."""
    x = np.asarray(x, float)
    n = len(x)
    thr = 0.0
    cand = [i for i in range(1, n - 1) if x[i] > x[i - 1] and x[i] >= x[i + 1] and x[i] > thr]
    d = 0.5 * 60.0 / max(hr_bpm, 40.0) * fs
    cand.sort(key=lambda i: -x[i])
    keep = []
    for i in cand:
        if all(abs(i - j) >= d for j in keep):
            keep.append(i)
    keep.sort()
    t, a = [], []
    for i in keep:
        y0, y1, y2 = x[i - 1], x[i], x[i + 1]
        den = y0 - 2 * y1 + y2
        off = 0.5 * (y0 - y2) / den if den != 0 else 0.0
        off = max(-0.5, min(0.5, off))
        t.append((i + off) / fs)
        a.append(y1 - 0.25 * (y0 - y2) * off)
    return np.array(t), np.array(a)


def clean_ibi(ibi, local=True):
    """쓸 수 있는 간격이면 True. local=False 면 범위 · 전체 중앙값 ±30% 만 (불규칙 판단용 — 이웃 기준은 불규칙을 지워 버린다)."""
    ibi = np.asarray(ibi, float)
    ok = (ibi >= IBI_MIN) & (ibi <= IBI_MAX)
    if ok.sum() < 3:
        return ok
    med = float(np.median(ibi[ok]))
    ok &= np.abs(ibi - med) <= GLOBAL_DEV * med
    if not local:
        return ok
    out = ok.copy()
    for i in range(len(ibi)):
        if not ok[i]:
            continue
        lo, hi = max(0, i - 2), min(len(ibi), i + 3)
        nb = [ibi[j] for j in range(lo, hi) if ok[j] and j != i]
        if len(nb) >= 2:
            m = float(np.median(nb))
            if abs(ibi[i] - m) > LOCAL_DEV * m:
                out[i] = False
    return out


# --- HRV · 스트레스 ----------------------------------------------------------------
def baevsky_si(ibi_s):
    """ibi 초 단위. 50 ms 구간: Mo = 최빈 구간 중앙(초), AMo = 그 구간 비율(%), MxDMn = 최대 − 최소(초)."""
    ms = np.asarray(ibi_s, float) * 1000
    if len(ms) < 10:
        return None
    k = np.floor(ms / 50).astype(int)
    vals, cnt = np.unique(k, return_counts=True)
    kb = int(vals[int(np.argmax(cnt))])                       # 동률이면 짧은 쪽 구간
    mo = (kb * 50 + 25) / 1000
    amo = cnt.max() / len(ms) * 100
    mxdmn = max((ms.max() - ms.min()) / 1000, 0.05)          # 한 구간 폭보다 작게 두지 않는다
    return float(amo / (2 * mo * mxdmn))


def stress_score(si):
    if si is None:
        return None
    z = (math.log(si) - math.log(SI_LO)) / (math.log(SI_HI) - math.log(SI_LO))
    return float(round(max(0.0, min(1.0, z)) * 100, 1))


def stress_zone(score):
    if score is None:
        return None
    return "편안" if score < 30 else "보통" if score < 60 else "높음" if score < 80 else "매우 높음"


def hrv(beat_t):
    ibi = np.diff(np.asarray(beat_t, float))
    ok = clean_ibi(ibi)
    good = ibi[ok]
    pairs = [(ibi[i], ibi[i + 1]) for i in range(len(ibi) - 1) if ok[i] and ok[i + 1]]
    d = np.array([b - a for a, b in pairs]) * 1000
    okg = clean_ibi(ibi, local=False) if len(ibi) else np.array([], bool)
    dg = np.array([ibi[i + 1] - ibi[i] for i in range(len(ibi) - 1) if okg[i] and okg[i + 1]])
    gm = float(ibi[okg].mean()) if okg.any() else None
    big = float(np.mean(np.abs(dg) > 0.2 * gm)) if len(dg) >= 8 else None
    out = {"beats": int(len(beat_t)), "ibi_n": int(len(ibi)), "ibi_ok": int(ok.sum()),
           "ok_ratio": float(ok.mean()) if len(ibi) else 0.0, "okg_ratio": float(okg.mean()) if len(ibi) else 0.0, "big_jump": big}
    if len(good) < 10 or len(d) < 8:
        return {**out, "hr": None, "rmssd": None, "sdnn": None, "pnn50": None, "si": None}
    rmssd = float(np.sqrt(np.mean(d ** 2)))
    return {**out, "hr": float(60 / good.mean()), "rmssd": rmssd, "sdnn": float(good.std(ddof=1) * 1000),
            "pnn50": float(np.mean(np.abs(d) > 50) * 100), "si": baevsky_si(good)}


# --- 호흡 ------------------------------------------------------------------------
def _resp_peak(series_t, series_v, t0, t1):
    """불규칙 표본 → 4 Hz → 추세 제거 · 대역 통과 → 0.1–0.5 Hz 최고점 (회/분, 품질 0–1)."""
    if len(series_t) < 6:
        return None, 0.0
    n = int(np.floor((t1 - t0) * RESP_FS))
    if n < 32:
        return None, 0.0
    tt = t0 + np.arange(n) / RESP_FS
    v = np.interp(tt, series_t, series_v)
    v = R.bandpass(R.detrend_sp(v - v.mean(), lam=10.0), RESP_FS, *RESP_BAND)
    nfft = 4 * 2 ** int(np.ceil(np.log2(n)))
    spec = np.abs(np.fft.rfft(v * np.hanning(n), nfft)) ** 2
    f = np.fft.rfftfreq(nfft, 1 / RESP_FS)
    band = (f >= RESP_BAND[0]) & (f <= RESP_BAND[1])
    if not band.any() or spec[band].sum() <= 0:
        return None, 0.0
    k = int(np.argmax(np.where(band, spec, -1)))
    near = band & (np.abs(f - f[k]) <= 0.03)
    return float(f[k] * 60), float(spec[near].sum() / spec[band].sum())


def respiration(t, rgb_fs, beat_t, beat_a, ibi_ok_mask, fs=FS):
    """RIIV(초록 기저선) · RIAV(박동 높이) · RIFV(박동 간격) → 품질 0.3 이상끼리 4회/분 안에서 맞으면 평균."""
    T = len(rgb_fs) / fs
    g = rgb_fs[:, 1] / rgb_fs[:, 1].mean()
    tg = np.arange(len(g)) / fs
    est = {"riiv": _resp_peak(tg, g, 0, T)}
    if len(beat_t) >= 6:
        est["riav"] = _resp_peak(beat_t, beat_a, beat_t[0], beat_t[-1])
        ibi = np.diff(beat_t)
        mid = (beat_t[1:] + beat_t[:-1]) / 2
        m = np.asarray(ibi_ok_mask, bool)
        if m.sum() >= 6:
            est["rifv"] = _resp_peak(mid[m], ibi[m], mid[m][0], mid[m][-1])
    good = sorted([(q, r, k) for k, (r, q) in est.items() if r is not None and q >= 0.3], reverse=True)
    if not good:
        return {"rr": None, "conf": "low", "parts": {k: v[0] for k, v in est.items()}}
    best_q, best_r, _ = good[0]
    agree = [r for q, r, k in good if abs(r - best_r) <= 4]
    rr = float(np.mean(agree))
    conf = "high" if len(agree) >= 2 else "mid" if best_q >= 0.5 else "low"
    return {"rr": round(rr, 1), "conf": conf, "parts": {k: (round(v[0], 1) if v[0] else None) for k, v in est.items()}}


# --- 한 번의 스캔 ------------------------------------------------------------------
def analyze(t, rgb, fs=FS):
    """프레임 시각 t(초) · 얼굴 평균 RGB → 모든 지표 + 지표별 신뢰도."""
    t = np.asarray(t, float)
    r = R.resample(t, rgb, fs)
    bvp = R.pos_v2(r, fs)
    hr_f, snr = R.hr_snr_v2(bvp, fs)
    x = beat_signal(bvp, fs, hr_f)
    bt, ba = find_beats(x, fs, hr_f)
    h = hrv(bt)
    ok = clean_ibi(np.diff(bt)) if len(bt) > 1 else np.array([], bool)
    resp = respiration(t, r, bt, ba, ok, fs)
    sig = "high" if snr >= 3 else "mid" if snr >= 0 else "low"
    hrv_conf = "low" if sig == "low" or h["rmssd"] is None or h["ok_ratio"] < 0.7 else "high" if sig == "high" and h["ok_ratio"] >= 0.85 else "mid"
    irregular = None                     # 신호 좋고 박동이 거의 다 잡혔을 때만 판단 (잡음 박동을 불규칙으로 오인하지 않게)
    if sig == "high" and h["okg_ratio"] >= 0.8 and h["big_jump"] is not None:
        irregular = bool(h["big_jump"] > 0.3)
    si = h["si"] if hrv_conf != "low" else None
    sc = stress_score(si)
    return {
        "hr": round(hr_f, 1), "snr": round(float(snr), 2), "signal": sig,
        "hr_beats": round(h["hr"], 1) if h["hr"] else None,
        "rmssd": round(h["rmssd"], 1) if h["rmssd"] is not None and hrv_conf != "low" else None,
        "sdnn": round(h["sdnn"], 1) if h["sdnn"] is not None and hrv_conf != "low" else None,
        "pnn50": round(h["pnn50"], 1) if h["pnn50"] is not None and hrv_conf != "low" else None,
        "si": round(si, 1) if si is not None else None, "stress": sc, "stress_zone": stress_zone(sc),
        "hrv_conf": hrv_conf, "irregular": irregular,
        "rr": resp["rr"] if sig != "low" else None, "rr_conf": resp["conf"] if sig != "low" else "low",
        "beats": h["beats"], "ibi_ok_ratio": round(h["ok_ratio"], 2),
    }


# --- 종합 점수 (0–100, 계산식 공개) ---------------------------------------------------
# 호흡은 공개 데이터에서 손끝 PPG 호흡과 맞지 않아(Spearman 0.1) 점수에 넣지 않고 참고로만 보여준다.
WEIGHTS = {"stress": 0.35, "hrv": 0.20, "hr": 0.15, "rr": 0.0, "life": 0.30}


def _band_score(v, lo, hi, per):
    if v is None:
        return None
    d = lo - v if v < lo else v - hi if v > hi else 0
    return max(0.0, 100 - per * d)


def life_score(sleep_h, caffeine, mood):
    """수면 7–9시간 · 카페인 0–1잔 · 기분 1–5."""
    parts = []
    if sleep_h is not None:
        parts.append(_band_score(sleep_h, 7, 9, 15))
    if caffeine is not None:
        parts.append(max(0.0, 100 - 20 * max(0, caffeine - 1)))
    if mood is not None:
        parts.append(20 * mood)
    return float(np.mean(parts)) if parts else None


def health_score(m, sleep_h=None, caffeine=None, mood=None):
    comp = {
        "stress": None if m.get("stress") is None else 100 - m["stress"],
        "hrv": None if not m.get("rmssd") else max(0.0, min(100.0, (math.log(m["rmssd"]) - math.log(10)) / (math.log(80) - math.log(10)) * 100)),
        "hr": _band_score(m.get("hr") if m.get("signal") != "low" else None, 55, 85, 2.5),
        "rr": _band_score(m.get("rr"), 12, 20, 8),
        "life": life_score(sleep_h, caffeine, mood),
    }
    have = {k: v for k, v in comp.items() if v is not None and WEIGHTS[k] > 0}
    if not have:
        return {"score": None, "parts": comp}
    w = sum(WEIGHTS[k] for k in have)
    score = sum(WEIGHTS[k] * v for k, v in have.items()) / w
    return {"score": int(round(score)), "parts": {k: (None if v is None else int(round(v))) for k, v in comp.items()},
            "used": sorted(have)}


def bmi(height_cm, weight_kg):
    if not height_cm or not weight_kg:
        return None
    b = weight_kg / (height_cm / 100) ** 2
    zone = "저체중" if b < 18.5 else "정상" if b < 23 else "과체중" if b < 25 else "비만"     # 대한비만학회 기준
    return {"bmi": round(b, 1), "zone": zone}
