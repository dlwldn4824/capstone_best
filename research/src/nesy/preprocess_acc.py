"""ACC -> magnitude -> 움직임 feature (10개) + HR feature (4개).

E4 ACC 는 1/64 g 단위 정수로 저장된다. 64 로 나눠 g 단위로 바꾼다.
magnitude 는 중력 성분을 포함하므로 정지 시 약 1 g 이다. 활동량 지표로는
중력을 뺀 dynamic magnitude 를 함께 만든다 (acc_dyn_mean).

담당: 역할 A (데이터/전처리)
"""
from __future__ import annotations

import numpy as np

NAN = float("nan")
G_SCALE = 64.0   # E4 raw 정수 -> g

FEATURE_KEYS = ("x_mean", "y_mean", "z_mean", "x_std", "y_std", "z_std",
                "acc_mean", "acc_std", "acc_ratio_up", "acc_ratio_down",
                "acc_dyn_mean")

HR_FEATURE_KEYS = ("hr_mean", "hr_std", "hr_ratio_up", "hr_ratio_down")


def to_g(acc):
    """(n, 3) raw -> g 단위."""
    return np.asarray(acc, dtype=float) / G_SCALE


def magnitude(acc_g):
    """유클리드 크기 (중력 포함)."""
    return np.sqrt(np.sum(np.asarray(acc_g, dtype=float) ** 2, axis=1))


def _ratio_up_down(x, fs):
    if len(x) < 2:
        return NAN, NAN
    d = np.diff(x) * fs
    up, down = d[d > 0], d[d < 0]
    return (float(np.mean(up)) if len(up) else 0.0,
            float(np.mean(down)) if len(down) else 0.0)


def process(acc_raw, fs, cfg=None):
    """ACC 한 윈도 -> 중간 산출물 + feature dict."""
    acc_raw = np.asarray(acc_raw, dtype=float)
    if acc_raw.ndim != 2 or acc_raw.shape[0] == 0:
        return {"g": acc_raw, "mag": np.array([]),
                "features": {k: NAN for k in FEATURE_KEYS}}

    g = to_g(acc_raw)
    mag = magnitude(g)
    up, down = _ratio_up_down(mag, fs)

    def std(v):
        return float(np.std(v, ddof=1)) if len(v) > 1 else NAN

    feats = {
        "x_mean": float(np.mean(g[:, 0])), "y_mean": float(np.mean(g[:, 1])),
        "z_mean": float(np.mean(g[:, 2])),
        "x_std": std(g[:, 0]), "y_std": std(g[:, 1]), "z_std": std(g[:, 2]),
        "acc_mean": float(np.mean(mag)),
        "acc_std": std(mag),
        "acc_ratio_up": up,
        "acc_ratio_down": down,
        # 중력을 뺀 순수 움직임. NeSy 의 ACTIVITY_HIGH fact 가 이걸 쓴다.
        "acc_dyn_mean": float(np.mean(np.abs(mag - np.median(mag)))),
    }
    return {"g": g, "mag": mag, "features": feats}


def hr_features(hr, fs):
    """E4 가 계산한 HR.csv (1 Hz) 로부터 4개 feature."""
    hr = np.asarray(hr, dtype=float)
    if len(hr) == 0:
        return {k: NAN for k in HR_FEATURE_KEYS}
    up, down = _ratio_up_down(hr, fs)
    return {
        "hr_mean": float(np.mean(hr)),
        "hr_std": float(np.std(hr, ddof=1)) if len(hr) > 1 else NAN,
        "hr_ratio_up": up,
        "hr_ratio_down": down,
    }
