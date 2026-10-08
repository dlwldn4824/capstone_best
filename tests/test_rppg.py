"""얼굴 심박(rPPG) — 브라우저 rppg.js 와 같은 값을 내는가, 앱 멈춤 규칙이 도는가."""
import numpy as np
import pytest

from src.nesy import rppg as R


def synth(bpm, secs=30, noise=0.3, fps=30, seed=1):
    rng = np.random.default_rng(seed)
    n = int(secs * fps)
    t = np.arange(n) / fps
    p = np.sin(2 * np.pi * bpm / 60 * t)
    d = 3 * np.sin(2 * np.pi * 0.1 * t)
    u = lambda: noise * rng.uniform(-0.5, 0.5, n)  # noqa: E731
    rgb = np.stack([150 + 0.15 * p + d + u(), 110 + 0.5 * p + d + u(), 90 + 0.1 * p + d + u()], 1)
    return t, rgb


@pytest.mark.parametrize("bpm,fps,expect", [(72, 30, 72.0), (58, 30, 58.2), (95, 24, 94.8)])
def test_matches_browser_values(bpm, fps, expect):
    """브라우저 rppg.js 로 같은 합성 신호를 돌린 값과 같아야 한다."""
    t, rgb = synth(bpm, fps=fps, noise=0.5 if bpm != 72 else 0.3)
    assert R.estimate(t, rgb)[0] == pytest.approx(expect, abs=0.05)


def test_short_record_is_refused():
    t, rgb = synth(72, secs=5)
    assert R.estimate(t, rgb) is None


def test_lab_matches_browser():
    L, a, b = R.to_lab(np.array([200.0, 150.0, 130.0]))
    assert (round(float(L), 1), round(float(a), 1), round(float(b), 1)) == (66.3, 16.1, 17.9)


def test_app_scan_stops_early_on_clean_signal():
    t, rgb = synth(66, secs=40, noise=0.2)
    bpm, snr, secs, early = R.app_scan(t, rgb, 0.0)
    assert early and secs <= 12 and bpm == pytest.approx(66, abs=1)


def test_app_scan_refuses_noise():
    rng = np.random.default_rng(0)
    t = np.arange(900) / 30
    rgb = 120 + rng.normal(0, 3, (900, 3))
    *_, early = R.app_scan(t, rgb, 0.0)
    assert not early                                   # 안정되지 않으면 앱은 값을 저장하지 않는다
