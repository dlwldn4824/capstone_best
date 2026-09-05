"""Load WESAD Empatica E4 wrist recordings at native sampling rates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from wesad_phase1.config import Phase1Config, load_config
from wesad_phase1.constants import LABEL_FS, WRIST_FS


@dataclass
class WristRecording:
    subject_id: str
    bvp: np.ndarray
    eda: np.ndarray
    temp: np.ndarray
    acc: np.ndarray
    label: np.ndarray

    @property
    def duration_sec(self) -> float:
        return float(len(self.label) / LABEL_FS)

    def slice_window(self, start_sec: float, length_sec: float) -> dict[str, np.ndarray]:
        end_sec = start_sec + length_sec
        return {
            "bvp": _slice(self.bvp, WRIST_FS["BVP"], start_sec, end_sec),
            "eda": _slice(self.eda, WRIST_FS["EDA"], start_sec, end_sec),
            "temp": _slice(self.temp, WRIST_FS["TEMP"], start_sec, end_sec),
            "acc": _slice(self.acc, WRIST_FS["ACC"], start_sec, end_sec),
            "label": _slice(self.label, LABEL_FS, start_sec, end_sec),
        }


def load_wrist(subject_id: str, cfg: Phase1Config | None = None) -> WristRecording:
    cfg = cfg or load_config()
    path = cfg.cache_dir / f"{subject_id}_wrist.npz"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Run: python -m wesad_phase1.cli download"
        )
    with np.load(path, allow_pickle=False) as data:
        sid = str(np.asarray(data["subject"]).item()) if "subject" in data.files else subject_id
        return WristRecording(
            subject_id=sid,
            bvp=np.asarray(data["bvp"], dtype=np.float32).reshape(-1),
            eda=np.asarray(data["eda"], dtype=np.float32).reshape(-1),
            temp=np.asarray(data["temp"], dtype=np.float32).reshape(-1),
            acc=np.asarray(data["acc"], dtype=np.float32),
            label=np.asarray(data["label"], dtype=np.int16).reshape(-1),
        )


def _slice(arr: np.ndarray, fs: int, start_sec: float, end_sec: float) -> np.ndarray:
    start = int(round(start_sec * fs))
    end = int(round(end_sec * fs))
    start = max(0, start)
    end = min(arr.shape[0], end)
    return arr[start:end]
