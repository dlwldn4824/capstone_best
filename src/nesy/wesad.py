"""WESAD 로더 — 가슴 ECG 와 손목 PPG 를 **동시에** 잰 유일한 공개 데이터.

Schmidt et al., *Introducing WESAD: A Multimodal Dataset for Wearable Stress
and Affect Detection*, ICMI 2018. UCI 공개, 비영리 연구 목적.

왜 이 데이터가 필요한가
    우리는 두 데이터(Hongn 실험실 / Nurse 실환경)에서 **HRV 가 스트레스를
    반영하지 않는다**는 것을 확인했다. 36명 중 18명, 15명 중 7명 — 두 번 다
    정확히 우연 수준이었다.

    그런데 그것이
      (a) 생리적 사실       — 스트레스가 정말 HRV 를 안 바꾼다
      (b) 손목 PPG 의 한계  — 신호가 나빠서 못 잡는다
    중 어느 쪽인지 가르지 못했다. 둘 다 손목 PPG 로만 쟀기 때문이다.

    WESAD 는 **같은 사람, 같은 시각에** 가슴 ECG(700 Hz)와 손목 PPG(64 Hz)를
    동시에 기록한다. ECG 로 잰 HRV 가 스트레스에 반응하면 (b), 반응하지 않으면
    (a) 다. 우리 논문의 유일한 빈 구멍이 이것으로 메워진다.

구조
    WESAD/
      S2/  S2.pkl        <- 피험자당 pickle 하나
           S2_readme.txt
           S2_quest.csv  <- 설문 및 구간 시각
           S2_respiban.txt / S2_E4_Data.zip (원시)
      S3/ ...            (S1, S12 는 없다. 총 15명)

pickle 내용
    {'signal': {'chest': {'ACC','ECG','EMG','EDA','Temp','Resp'},   # 700 Hz
                'wrist': {'ACC','BVP','EDA','TEMP'}},               # 32/64/4/4
     'label': ndarray(700Hz),   # 0 미정의 1 baseline 2 stress 3 amusement
                                # 4 meditation 5,6,7 무시
     'subject': 'S2'}

라벨은 700 Hz 로 샘플마다 붙어 있다. 프로토콜 태그가 아니라 배열이므로
protocol.py 대신 라벨 배열에서 직접 구간을 잘라낸다.
"""
from __future__ import annotations

import pickle
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

CHEST_FS = 700.0
WRIST_FS = {"ACC": 32.0, "BVP": 64.0, "EDA": 4.0, "TEMP": 4.0}

# 라벨 코드 -> 우리 이름. 4(meditation) 은 REST 로 쓰지 않는다.
# 명상은 '평소' 가 아니라 적극적으로 이완시킨 상태라 baseline 과 다르다.
LABEL_MAP = {1: "REST", 2: "STRESS", 3: "AMUSEMENT"}
USE_LABELS = ("REST", "STRESS")      # 우리 비교에 쓰는 것만


def find_root(raw_dir):
    """WESAD 폴더를 찾는다. 압축 구조가 판본마다 달라 탐색한다."""
    p = Path(raw_dir)
    for cand in [p, p / "WESAD", *p.glob("*/WESAD"), *p.glob("*")]:
        if cand.is_dir() and list(cand.glob("S*/S*.pkl")):
            return cand
    return None


def discover_subjects(root):
    """(subject, pkl 경로) 목록."""
    root = Path(root)
    rows = []
    for d in sorted(root.glob("S*")):
        if not d.is_dir():
            continue
        pkl = d / (d.name + ".pkl")
        if pkl.exists():
            rows.append({"subject_id": d.name, "path": str(pkl)})
    return pd.DataFrame(rows)


def load_subject(pkl_path):
    """pickle 하나를 읽는다. latin1 인코딩이어야 한다 (Python 2 로 저장됨)."""
    with open(pkl_path, "rb") as fh:
        d = pickle.load(fh, encoding="latin1")
    return d


def _flat(x):
    """(N, 1) 로 저장된 단일 채널을 (N,) 으로 편다. ACC 같은 (N, 3) 은 그대로 둔다."""
    a = np.asarray(x, dtype=float)
    if a.ndim > 1 and a.shape[1] == 1:
        return a.ravel()
    return a


def label_segments(labels, fs=CHEST_FS, min_sec=60.0):
    """라벨 배열 -> [(label, start_sec, end_sec)].

    같은 값이 이어지는 구간을 하나로 묶는다. 짧은 조각은 버린다.
    """
    lab = np.asarray(labels).ravel()
    out = []
    if len(lab) == 0:
        return out
    change = np.flatnonzero(np.diff(lab)) + 1
    bounds = np.concatenate([[0], change, [len(lab)]])
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        code = int(lab[a])
        name = LABEL_MAP.get(code)
        if name is None:
            continue
        dur = (b - a) / fs
        if dur < min_sec:
            continue
        out.append((name, a / fs, b / fs))
    return out


def windows(start, end, length, step):
    """구간을 고정 윈도로 자른다 (초 단위, 세션 시작 기준 상대 시각)."""
    out, t = [], start
    while t + length <= end + 1e-9:
        out.append((t, t + length))
        t += step
    return out


def slice_signal(arr, fs, t0, t1):
    """상대 시각 [t0, t1) 구간을 잘라낸다.

    WESAD 의 단일 채널은 (N, 1) 로 저장되어 있다. 펴 주지 않으면 filtfilt 가
    길이 1인 축을 따라 필터링하려다 실패한다.
    """
    a = _flat(arr)
    i0 = max(0, int(np.ceil(t0 * fs)))
    i1 = min(len(a), int(np.floor(t1 * fs)))
    if i1 <= i0:
        return a[:0]
    return a[i0:i1]


# --- 가슴 ECG 에서 HRV ------------------------------------------------------

def ecg_rpeaks(ecg, fs=CHEST_FS, min_bpm=40, max_bpm=200):
    """ECG R-peak 검출.

    Pan-Tompkins 의 축약판이다. 대역통과 -> 미분 -> 제곱 -> 이동적분 -> peak.
    BVP 와 달리 ECG 는 R 파가 뾰족해 훨씬 안정적으로 잡힌다.
    """
    from scipy import signal as sps

    x = np.asarray(ecg, dtype=float)
    if len(x) < int(fs * 5):
        return np.array([], dtype=int)

    nyq = fs / 2.0
    b, a = sps.butter(3, [5.0 / nyq, 20.0 / nyq], btype="band")
    f = sps.filtfilt(b, a, x)
    d = np.diff(f, prepend=f[0])
    sq = d ** 2
    win = max(1, int(0.12 * fs))
    integ = np.convolve(sq, np.ones(win) / win, mode="same")

    thr = 0.35 * np.percentile(integ, 99)
    dist = int(fs * 60.0 / max_bpm)
    peaks, _ = sps.find_peaks(integ, height=thr, distance=max(1, dist))
    return peaks


def rr_from_peaks(peaks, fs, min_bpm=40, max_bpm=200, rel_thresh=0.30):
    """R-peak -> RR 간격(초). preprocess_bvp 와 같은 artefact 제거를 쓴다."""
    from .preprocess_bvp import peaks_to_ibi
    return peaks_to_ibi(np.asarray(peaks), fs, min_bpm, max_bpm, rel_thresh)


def hrv_from_ecg(ecg, fs=CHEST_FS):
    """가슴 ECG 기반 HRV. 손목 PPG 와 **같은 함수**로 계산해 공정하게 비교한다."""
    from .preprocess_bvp import time_domain_hrv, freq_domain_hrv

    peaks = ecg_rpeaks(ecg, fs)
    ibi, tm = rr_from_peaks(peaks, fs)
    out = {"ecg_n_beats": float(len(ibi))}
    out.update({"ecg_" + k: v for k, v in time_domain_hrv(ibi).items()})
    out.update({"ecg_" + k: v for k, v in freq_domain_hrv(ibi, tm).items()})
    return out


def extract_zip(zip_path, out_dir):
    """WESAD 압축 해제."""
    zip_path, out_dir = Path(zip_path), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(out_dir)
    return find_root(out_dir)
