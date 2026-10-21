"""합성 E4 세션 생성기.

목적: PhysioNet 다운로드를 기다리지 않고 역할 B/C 가 Day 1 부터 전체
파이프라인을 돌릴 수 있게 한다. 실제 데이터가 들어오면 같은 코드 경로를
그대로 쓰므로 교체 비용이 없다.

!! 중요 !!
합성 데이터로 얻은 성능 수치는 연구 결과가 아니다. 생리 파라미터를 우리가
직접 심어 넣었으므로 분류가 쉬운 것이 당연하다. 이 데이터의 용도는 오직
  (1) 코드가 끝까지 도는지
  (2) CSV 인터페이스가 맞는지
  (3) 지표/그림 생성이 정상인지
확인하는 것이다. 실제 결과는 반드시 PhysioNet 데이터로 다시 만들 것.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

# 상태별 생리 파라미터: (HR bpm, HRV SDNN 초, EDA tonic uS, SCR/분, ACC 활동량 g)
STATE_PARAMS = {
    "REST":    dict(hr=70,  sdnn=0.055, eda=2.0, scr=1.0,  acc=0.02, acc_hz=0.0),
    "STRESS":  dict(hr=86,  sdnn=0.030, eda=4.5, scr=8.0,  acc=0.04, acc_hz=0.0),
    "AEROBIC": dict(hr=132, sdnn=0.018, eda=3.2, scr=3.0,  acc=0.45, acc_hz=1.3),
    "SPRINT":  dict(hr=168, sdnn=0.012, eda=5.5, scr=6.0,  acc=0.95, acc_hz=2.4),
}

FS = {"BVP": 64, "ACC": 32, "EDA": 4, "TEMP": 4, "HR": 1}


def _pulse_wave(ibi_series, fs, n_samples, rng):
    """IBI 열로부터 BVP 유사 파형을 합성한다 (peak detection 이 동작하도록)."""
    x = np.zeros(n_samples)
    t = np.arange(n_samples) / fs
    beat_t, acc_t = [], 0.0
    for ibi in ibi_series:
        acc_t += ibi
        if acc_t >= n_samples / fs:
            break
        beat_t.append(acc_t)
    for bt in beat_t:
        # 주 박동 + dicrotic notch
        x += np.exp(-((t - bt) ** 2) / (2 * 0.045 ** 2))
        x += 0.35 * np.exp(-((t - bt - 0.22) ** 2) / (2 * 0.05 ** 2))
    x = x * 60.0 + rng.normal(0, 2.0, n_samples)
    x += 8.0 * np.sin(2 * np.pi * 0.25 * t)      # 호흡성 기저 변동
    return x


def _make_state(state, dur, rng, subj_offset):
    """한 상태 구간의 모든 센서 신호를 만든다."""
    p = STATE_PARAMS[state]
    hr = p["hr"] + subj_offset["hr"]
    sdnn = max(0.006, p["sdnn"] * subj_offset["hrv_scale"])

    # --- IBI -> BVP -------------------------------------------------------
    mean_ibi = 60.0 / hr
    n_beats = int(dur / mean_ibi) + 8
    ibi = rng.normal(mean_ibi, sdnn, n_beats)
    ibi = np.clip(ibi, 0.30, 1.5)
    n_bvp = int(dur * FS["BVP"])
    bvp = _pulse_wave(ibi, FS["BVP"], n_bvp, rng)

    # --- HR (E4 는 BVP 로부터 1 Hz 로 계산) --------------------------------
    n_hr = int(dur * FS["HR"])
    hr_series = hr + rng.normal(0, 2.0, n_hr) + np.linspace(0, 3.0, n_hr)

    # --- EDA: tonic drift + SCR ------------------------------------------
    n_eda = int(dur * FS["EDA"])
    t_eda = np.arange(n_eda) / FS["EDA"]
    tonic = (p["eda"] + subj_offset["eda"]) + 0.15 * np.sin(2 * np.pi * 0.004 * t_eda)
    phasic = np.zeros(n_eda)
    n_scr = rng.poisson(p["scr"] * dur / 60.0)
    for _ in range(n_scr):
        onset = rng.uniform(0, max(0.1, dur - 6))
        amp = rng.uniform(0.08, 0.5)
        # Bateman 함수 근사: 빠른 상승, 느린 회복
        resp = amp * (np.exp(-(t_eda - onset) / 4.0) - np.exp(-(t_eda - onset) / 0.7))
        resp[t_eda < onset] = 0
        phasic += np.clip(resp, 0, None)
    eda = tonic + phasic + rng.normal(0, 0.006, n_eda)

    # --- ACC: 중력 + 주기적 운동 성분 -------------------------------------
    n_acc = int(dur * FS["ACC"])
    t_acc = np.arange(n_acc) / FS["ACC"]
    amp = p["acc"] * subj_offset["acc_scale"]
    move = amp * np.sin(2 * np.pi * p["acc_hz"] * t_acc) if p["acc_hz"] > 0 else 0.0
    ax = move + rng.normal(0, amp * 0.35 + 0.006, n_acc)
    ay = 0.6 * move + rng.normal(0, amp * 0.35 + 0.006, n_acc)
    az = 1.0 + 0.4 * move + rng.normal(0, amp * 0.35 + 0.006, n_acc)  # 중력
    acc = np.stack([ax, ay, az], axis=1) * 64.0   # E4 raw 단위(1/64 g)

    # --- TEMP -------------------------------------------------------------
    temp = 32.5 + subj_offset["temp"] + rng.normal(0, 0.05, int(dur * FS["TEMP"]))

    return {"BVP": bvp, "HR": hr_series, "EDA": eda, "ACC": acc, "TEMP": temp}


def _write_csv(path, arr, t0, fs):
    arr = np.asarray(arr, dtype=float)
    if arr.ndim == 1:
        arr = arr[:, None]
    ncol = arr.shape[1]
    header = np.array([[t0] * ncol, [fs] * ncol], dtype=float)
    np.savetxt(path, np.vstack([header, arr]), delimiter=",", fmt="%.6f")


def make_session(out_dir, subject, session_type, proto, rng, t0=1.7e9):
    """protocol.yaml 의 정의와 정확히 일치하는 태그/구간을 가진 세션을 만든다."""
    from . import protocol as P

    version = P.subject_version(subject, proto)
    spec = proto[session_type][version]
    labels, names = spec["labels"], spec["names"]

    # 세그먼트 길이: rest/baseline 은 길게, sprint 는 짧게
    durs = []
    for lab, nm in zip(labels, names):
        if "sprint" in nm:
            durs.append(45.0)
        elif lab is None:
            durs.append(120.0)
        elif lab == "REST":
            durs.append(240.0)
        else:
            durs.append(180.0)

    subj_offset = {
        "hr": rng.normal(0, 7.0), "hrv_scale": np.exp(rng.normal(0, 0.28)),
        "eda": rng.normal(0, 1.6), "acc_scale": np.exp(rng.normal(0, 0.18)),
        "temp": rng.normal(0, 0.6),
    }

    chunks = {k: [] for k in FS}
    tags = [t0]
    for lab, nm, dur in zip(labels, names, durs):
        state = lab if lab is not None else ("AEROBIC" if "cool" in nm or "warm" in nm else "REST")
        piece = _make_state(state, dur, rng, subj_offset)
        for k in FS:
            chunks[k].append(piece[k])
        tags.append(tags[-1] + dur)

    d = Path(out_dir) / session_type / subject
    d.mkdir(parents=True, exist_ok=True)
    for k in FS:
        _write_csv(d / "{}.csv".format(k), np.concatenate(chunks[k], axis=0),
                   t0, FS[k])
    np.savetxt(d / "tags.csv", np.asarray(tags), fmt="%.6f")
    # IBI.csv 는 의도적으로 비워둔다 (실데이터의 운동 세션 결측을 모사)
    (d / "IBI.csv").write_text("{:.6f}\n".format(t0), encoding="utf-8")
    return d


def make_dataset(out_dir, proto, n_v1=8, n_v2=6, seed=42):
    """S01.. (v1) 와 f01.. (v2) 피험자를 만들어 전체 데이터셋을 구성한다."""
    rng = np.random.default_rng(seed)
    subjects = (["S{:02d}".format(i + 1) for i in range(n_v1)]
                + ["f{:02d}".format(i + 1) for i in range(n_v2)])
    made = []
    for s in subjects:
        for stype in ("STRESS", "AEROBIC", "ANAEROBIC"):
            made.append(str(make_session(out_dir, s, stype, proto, rng)))
    return subjects, made
