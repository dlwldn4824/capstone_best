"""파이프라인 단위 테스트.

    python -m pytest tests -q
    (pytest 가 없으면) python tests/test_pipeline.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nesy import (evaluate, facts as facts_mod, preprocess_acc, preprocess_bvp,
                  preprocess_eda, protocol, rules as rules_mod, subject_split)


# --- 전처리 ---------------------------------------------------------------

def test_peak_detection_recovers_known_hr():
    """정확히 75 bpm 인 합성 맥파에서 HR 을 되찾는가."""
    fs, dur, bpm = 64.0, 60.0, 75.0
    t = np.arange(int(fs * dur)) / fs
    x = np.zeros_like(t)
    for k in range(int(dur * bpm / 60)):
        x += np.exp(-((t - k * 60.0 / bpm) ** 2) / (2 * 0.04 ** 2))
    filt = preprocess_bvp.bandpass(x, fs)
    peaks = preprocess_bvp.detect_peaks(filt, fs)
    ibi, _ = preprocess_bvp.peaks_to_ibi(peaks, fs)
    hr = 60.0 / np.mean(ibi)
    assert abs(hr - bpm) < 2.0, "HR 오차 {:.1f} bpm".format(abs(hr - bpm))


def test_ibi_artefact_rejection():
    """peak 하나를 빼먹으면 생기는 2배 IBI 가 제거되는가."""
    fs = 64.0
    peaks = np.arange(0, 60 * fs, fs * 0.8).astype(int)
    peaks = np.delete(peaks, 20)          # 20번째 박동 누락
    ibi, _ = preprocess_bvp.peaks_to_ibi(peaks, fs, rel_thresh=0.30)
    assert np.max(ibi) < 1.2, "2배 IBI 가 남아있다: {:.2f}".format(np.max(ibi))


def test_eda_decomposition_separates_bands():
    """느린 drift 는 tonic 으로, 빠른 SCR 은 phasic 으로 가는가."""
    fs, n = 4.0, 4 * 300
    t = np.arange(n) / fs
    drift = 2.0 + 0.5 * np.sin(2 * np.pi * 0.002 * t)
    scr = np.zeros(n)
    scr[400:440] = np.linspace(0, 0.4, 40)
    tonic, phasic = preprocess_eda.decompose(drift + scr, fs)
    assert np.std(tonic - drift) < 0.15
    assert np.max(phasic) > 0.1


def test_scr_events_detected():
    fs, n = 4.0, 4 * 120
    t = np.arange(n) / fs
    phasic = np.zeros(n)
    for onset in (20, 60, 90):
        r = 0.3 * (np.exp(-(t - onset) / 4.0) - np.exp(-(t - onset) / 0.7))
        r[t < onset] = 0
        phasic += np.clip(r, 0, None)
    ev = preprocess_eda.scr_events(phasic, fs, min_amplitude=0.02)
    assert len(ev) == 3, "SCR {}개 검출 (기대 3)".format(len(ev))


def test_acc_magnitude_gravity():
    """정지 상태 손목은 magnitude 약 1 g, dynamic 은 0 에 가까워야 한다."""
    acc = np.tile(np.array([0.0, 0.0, 1.0]) * 64.0, (100, 1))
    r = preprocess_acc.process(acc, 32.0)
    assert abs(r["features"]["acc_mean"] - 1.0) < 0.01
    assert r["features"]["acc_dyn_mean"] < 0.01


# --- 프로토콜 -------------------------------------------------------------

PROTO = {
    "version_by_prefix": {"S": "v1", "f": "v2"},
    "STRESS": {"v1": {"expected_segments": 3,
                      "labels": ["REST", "STRESS", None],
                      "portions": ["second_half", "all", "all"],
                      "names": ["baseline", "task", "cool"]}},
}


def test_segment_count_mismatch_is_rejected():
    """태그 수가 다르면 조용히 오라벨하지 않고 problem 을 낸다."""
    segs, problem = protocol.segment_session("S01", "STRESS",
                                             np.array([0., 10., 20.]), PROTO)
    assert problem is not None and segs == []


def test_segment_portions_applied():
    tags = np.array([0., 100., 200., 300.])
    segs, problem = protocol.segment_session("S01", "STRESS", tags, PROTO)
    assert problem is None
    assert len(segs) == 2                      # None 라벨은 빠진다
    assert segs[0].start == 50.0               # second_half
    assert (segs[1].start, segs[1].end) == (100.0, 200.0)


def test_windows_short_segment_kept_whole():
    seg = protocol.Segment("S01", "ANAEROBIC", "v1", 1, "sprint1", "SPRINT",
                           0.0, 30.0, "all")
    w = protocol.windows(seg, 60.0, 30.0)
    assert w == [(0.0, 30.0)]


# --- 평가 -----------------------------------------------------------------

def test_directional_error():
    y = np.array(["STRESS"] * 4 + ["EXERCISE"] * 4)
    p = np.array(["EXERCISE", "STRESS", "STRESS", "STRESS",
                  "EXERCISE", "EXERCISE", "EXERCISE", "STRESS"])
    assert evaluate.directional_error(y, p, "STRESS", "EXERCISE") == 0.25
    assert evaluate.directional_error(y, p, "EXERCISE", "STRESS") == 0.25


def test_abstain_counted_as_wrong():
    """UNCERTAIN 을 정답으로 세지 않는지 확인 (관대한 평가 방지)."""
    y = np.array(["REST", "STRESS", "EXERCISE"])
    p = np.array(["REST", "UNCERTAIN", "EXERCISE"])
    m = evaluate.compute_metrics(y, p)
    assert abs(m["accuracy"] - 2 / 3) < 1e-9
    assert abs(m["abstain_rate"] - 1 / 3) < 1e-9


def test_flag_metrics():
    y = np.array(["REST", "REST", "STRESS", "STRESS"])
    pred = np.array(["REST", "STRESS", "STRESS", "REST"])   # 오류 2개
    flags = np.array([False, True, False, False])           # 1개만 표시
    m = evaluate.flag_metrics(y, pred, flags)
    assert m["flag_precision"] == 1.0
    assert m["flag_recall"] == 0.5


# --- 분할 -----------------------------------------------------------------

def _toy_df(n_subj=6, n_per=10):
    rows = []
    for s in range(n_subj):
        for i in range(n_per):
            rows.append({"sample_id": "s{}_{}".format(s, i),
                         "subject_id": "S{:02d}".format(s),
                         "label": ["REST", "STRESS", "EXERCISE"][i % 3],
                         "hr_mean": 70 + 10 * (i % 3) + s,
                         "rmssd": 50 - 10 * (i % 3),
                         "mean_tonic_eda": 2 + (i % 3),
                         "peaks_density": 1 + 2 * (i % 3),
                         "acc_dyn_mean": [0.005, 0.02, 0.4][i % 3]})
    return pd.DataFrame(rows)


def test_group_split_has_no_subject_leak():
    df = _toy_df()
    for tr, te, _ in subject_split.make_splits(df, "group_kfold", 3):
        assert not (set(df.iloc[tr]["subject_id"]) & set(df.iloc[te]["subject_id"]))


def test_random_split_does_leak():
    """대조군이 실제로 누수를 갖는지 확인 (이 대비가 결과의 근거다)."""
    df = _toy_df()
    leaked = any(set(df.iloc[tr]["subject_id"]) & set(df.iloc[te]["subject_id"])
                 for tr, te, _ in subject_split.make_splits(df, "random", 3))
    assert leaked


# --- Fact / Rule ----------------------------------------------------------

def test_activity_fact_is_absolute_not_personal():
    """활동량은 개인 z-score 가 아니라 절대 임계로 판정되어야 한다.

    개인 z 였다면 정지만 하는 피험자에서도 미세한 움직임이 HIGH 가 된다.
    """
    df = _toy_df()
    df.loc[df["label"] != "EXERCISE", "acc_dyn_mean"] = 0.004
    f = facts_mod.build_facts(df, strategy="subject_z")
    assert f.loc[df["label"] == "REST", "ACTIVITY_HIGH"].mean() == 0.0
    assert f.loc[df["label"] == "EXERCISE", "ACTIVITY_HIGH"].mean() == 1.0


def test_baseline_mask_modes():
    df = _toy_df()
    m_all = facts_mod.baseline_mask(df, "all")
    m_low = facts_mod.baseline_mask(df, "low_activity")
    assert m_all.all()
    assert m_low.sum() < len(df)
    # 운동 윈도는 baseline 참조에서 빠져야 한다
    assert not m_low[(df["label"] == "EXERCISE").to_numpy()].any()


def test_rules_produce_expected_evidence():
    df = _toy_df()
    f = facts_mod.build_facts(df, strategy="subject_z")
    ev = rules_mod.apply_rules(f)
    for col in ("STRESS_EVIDENCE", "EXERCISE_EVIDENCE", "REST_EVIDENCE"):
        assert col in ev
        assert ev[col].between(0, 1).all()
    # 운동 윈도에서는 운동 근거가 스트레스 근거보다 커야 한다
    ex = (df["label"] == "EXERCISE").to_numpy()
    assert (ev.loc[ex, "EXERCISE_EVIDENCE"].mean()
            > ev.loc[ex, "STRESS_EVIDENCE"].mean())


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS  {}".format(name))
            except AssertionError as e:
                fails += 1
                print("FAIL  {}: {}".format(name, e))
            except Exception as e:
                fails += 1
                print("ERROR {}: {!r}".format(name, e))
    print("\n{} 실패".format(fails))
    sys.exit(1 if fails else 0)
