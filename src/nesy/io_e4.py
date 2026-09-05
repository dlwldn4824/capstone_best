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


def parse_time(v):
    """E4 시각 필드 -> epoch seconds.

    실데이터는 '2013-02-20 17:55:19' 같은 날짜 문자열을 쓰고, E4 원본 export 나
    우리 합성 데이터는 epoch 실수를 쓴다. 둘 다 받는다.
    (PhysioNet 문서에는 'UTC' 라고만 되어 있어 숫자를 기대했는데 아니었다.
     날짜 자체는 비식별화 과정에서 옮겨졌으므로 절대 시각은 의미가 없다.
     우리는 세션 내 상대 시각만 쓰므로 상관없다.)
    """
    try:
        return float(v)
    except (TypeError, ValueError):
        return pd.Timestamp(str(v).strip()).value / 1e9


def base_subject(folder_name):
    """'S11_a' -> 'S11'.

    한 세션이 두 파일 세트로 쪼개진 피험자가 있다 (S11 aerobic, S16 anaerobic,
    f14 stress). 폴더는 둘이지만 사람은 하나이므로, 피험자 단위 분할에서
    반드시 같은 그룹으로 묶어야 한다. 안 그러면 같은 사람이 train 과 test 에
    동시에 들어간다.
    """
    name = str(folder_name)
    if len(name) > 2 and name[-2] == "_" and name[-1].isalpha():
        return name[:-2]
    return name


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
    # 머리 2행은 문자열일 수 있으므로 따로 읽는다 (BVP 는 수십만 행이라
    # 전체를 문자열로 읽으면 느리다).
    head = pd.read_csv(path, header=None, nrows=2, dtype=str)
    if head.shape[0] < 2:
        return None
    t0 = parse_time(head.iloc[0, 0])
    fs = float(head.iloc[1, 0])

    body = pd.read_csv(path, header=None, skiprows=2)
    if body.empty:
        return None
    vals = body.to_numpy(dtype=float)
    if vals.shape[1] == 1:
        vals = vals[:, 0]
    return Signal(path.stem, vals, fs, t0)


def read_ibi(path: str | Path) -> pd.DataFrame | None:
    """E4 가 자체 계산한 IBI. 참고용이며 feature 계산에는 쓰지 않는다.

    실데이터에서 이 파일은 포맷이 일정하지 않다. 헤더 두 번째 칸이 날짜인
    세션도 있고 문자열 ' IBI' 인 세션도 있으며, 운동 세션에는 빈 파일도 있다
    (ANAEROBIC/S01). 우리는 BVP 에서 직접 peak 를 잡으므로 여기서 실패해도
    파이프라인은 영향을 받지 않는다. 조용히 None 을 돌려준다.
    """
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        head = pd.read_csv(path, header=None, nrows=1, dtype=str)
        if head.empty:
            return None
        t0 = parse_time(head.iloc[0, 0])
        body = pd.read_csv(path, header=None, skiprows=1)
        if body.empty or body.shape[1] < 2:
            return None
        arr = body.to_numpy(dtype=float)
    except (ValueError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return None
    return pd.DataFrame({"t": t0 + arr[:, 0], "ibi": arr[:, 1]})


def read_tags(path: str | Path) -> np.ndarray:
    """tags.csv -> 정렬된 UTC epoch 배열. 없거나 비면 빈 배열."""
    path = Path(path)
    if not path.exists():
        return np.array([], dtype=float)
    try:
        raw = pd.read_csv(path, header=None, dtype=str)
    except pd.errors.EmptyDataError:
        return np.array([], dtype=float)
    if raw.empty:
        return np.array([], dtype=float)
    vals = [parse_time(v) for v in raw.iloc[:, 0] if str(v).strip()]
    return np.sort(np.asarray(vals, dtype=float))


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
            rows.append({"session_type": stype,
                         "subject": base_subject(sub.name),  # 분할 파트 통합
                         "folder": sub.name,
                         "part": sub.name[-1] if base_subject(sub.name) != sub.name else "",
                         "path": str(sub)})
    return pd.DataFrame(rows)
