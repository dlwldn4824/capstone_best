"""Empatica E4 CSV 리더.

E4 포맷
    1행 = 세션 시작 시각 (UTC epoch seconds)
    2행 = sampling rate (Hz)
    3행~ = 샘플
    ACC 는 열이 3개(x, y, z), 나머지는 1개.
    IBI 는 예외: 1행만 시작 시각이고 이후 (경과시간, IBI초) 2열.
    tags 는 헤더 없이 UTC epoch 한 열.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

SIGNALS = ("BVP", "EDA", "ACC", "HR", "TEMP")


@dataclass
class Signal:
    """등간격 샘플링된 신호 한 개."""

    name: str
    values: np.ndarray      # (n,) 또는 ACC 의 경우 (n, 3)
    fs: float               # Hz
    t0: float               # UTC epoch seconds

    @property
    def t(self) -> np.ndarray:
        """샘플별 절대 시각(UTC epoch seconds)."""
        return self.t0 + np.arange(len(self.values)) / self.fs

    def slice_time(self, start: float, end: float) -> "Signal":
        """[start, end) 구간을 잘라 새 Signal 로 돌려준다."""
        i0 = max(0, int(np.ceil((start - self.t0) * self.fs)))
        i1 = min(len(self.values), int(np.floor((end - self.t0) * self.fs)))
        if i1 <= i0:
            return Signal(self.name, self.values[:0], self.fs, start)
        return Signal(self.name, self.values[i0:i1], self.fs,
                      self.t0 + i0 / self.fs)

    def __len__(self) -> int:
        return len(self.values)


def read_signal(path: str | Path) -> Signal | None:
    """BVP/EDA/ACC/HR/TEMP CSV 하나를 읽는다. 없으면 None."""
    path = Path(path)
    if not path.exists():
        return None
    raw = pd.read_csv(path, header=None).to_numpy(dtype=float)
    if raw.shape[0] < 3:
        return None
    t0 = float(raw[0, 0])
    fs = float(raw[1, 0])
    vals = raw[2:]
    if vals.shape[1] == 1:
        vals = vals[:, 0]
    return Signal(path.stem, vals, fs, t0)


def read_ibi(path: str | Path) -> pd.DataFrame | None:
    """E4 가 자체 계산한 IBI. 운동 세션에서 결측이 많아 참고용으로만 쓴다."""
    path = Path(path)
    if not path.exists():
        return None
    raw = pd.read_csv(path, header=None)
    if raw.shape[0] < 2:
        return None
    t0 = float(raw.iloc[0, 0])
    body = raw.iloc[1:].to_numpy(dtype=float)
    return pd.DataFrame({"t": t0 + body[:, 0], "ibi": body[:, 1]})


def read_tags(path: str | Path) -> np.ndarray:
    """tags.csv -> 정렬된 UTC epoch 배열. 없거나 비면 빈 배열."""
    path = Path(path)
    if not path.exists():
        return np.array([], dtype=float)
    try:
        raw = pd.read_csv(path, header=None)
    except pd.errors.EmptyDataError:
        return np.array([], dtype=float)
    if raw.empty:
        return np.array([], dtype=float)
    return np.sort(raw.iloc[:, 0].to_numpy(dtype=float))


def read_session(session_dir: str | Path) -> dict:
    """한 세션 폴더의 모든 신호를 읽는다."""
    d = Path(session_dir)
    out: dict = {s: read_signal(d / f"{s}.csv") for s in SIGNALS}
    out["IBI"] = read_ibi(d / "IBI.csv")
    out["tags"] = read_tags(d / "tags.csv")
    return out


def discover_sessions(raw_root: str | Path) -> pd.DataFrame:
    """raw 루트를 훑어 (session_type, subject, path) 목록을 만든다."""
    root = Path(raw_root)
    rows = []
    for stype in ("STRESS", "AEROBIC", "ANAEROBIC"):
        sdir = root / stype
        if not sdir.is_dir():
            continue
        for sub in sorted(p for p in sdir.iterdir() if p.is_dir()):
            rows.append({"session_type": stype, "subject": sub.name,
                         "path": str(sub)})
    return pd.DataFrame(rows)
