"""Build 60s REST/STRESS windows without resampling all channels to one rate."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
import pandas as pd

from wesad_phase1.config import Phase1Config, load_config
from wesad_phase1.constants import (
    FEATURE_COLUMNS,
    LABEL_FS,
    REST,
    STRESS,
    SUBJECTS,
    SUBJECT_SPLIT,
    WESAD_BASELINE,
    WESAD_STRESS,
)
from wesad_phase1.features import extract_features
from wesad_phase1.loader import WristRecording, load_wrist


@dataclass(frozen=True)
class WindowMeta:
    subject_id: str
    start_sec: float
    end_sec: float
    wesad_label: int
    y: int
    purity: float
    split: str


def iter_windows(
    rec: WristRecording,
    window_sec: float = 60.0,
    hop_sec: float = 30.0,
    min_purity: float = 1.0,
) -> Iterator[tuple[WindowMeta, dict[str, np.ndarray]]]:
    split = _split_of(rec.subject_id)
    for start, end, wesad_label, purity in _pure_segments(
        rec.label, window_sec, hop_sec, min_purity
    ):
        y = REST if wesad_label == WESAD_BASELINE else STRESS
        meta = WindowMeta(
            subject_id=rec.subject_id,
            start_sec=start,
            end_sec=end,
            wesad_label=wesad_label,
            y=y,
            purity=purity,
            split=split,
        )
        yield meta, rec.slice_window(start, window_sec)


def build_feature_table(cfg: Phase1Config | None = None) -> pd.DataFrame:
    cfg = cfg or load_config()
    rows: list[dict] = []
    for sid in SUBJECTS:
        rec = load_wrist(sid, cfg)
        for meta, window in iter_windows(
            rec, cfg.window_sec, cfg.hop_sec, cfg.min_purity
        ):
            feats = extract_features(window)
            rows.append(
                {
                    "subject_id": meta.subject_id,
                    "split": meta.split,
                    "start_sec": meta.start_sec,
                    "end_sec": meta.end_sec,
                    "wesad_label": meta.wesad_label,
                    "label_name": "REST" if meta.y == REST else "STRESS",
                    "y": meta.y,
                    "purity": meta.purity,
                    **feats,
                }
            )
    df = pd.DataFrame(rows)
    ordered = [
        "subject_id",
        "split",
        "start_sec",
        "end_sec",
        "wesad_label",
        "label_name",
        "y",
        "purity",
        *FEATURE_COLUMNS,
        "n_ibi",
        "bvp_quality",
    ]
    return df[ordered]


def _pure_segments(
    labels: np.ndarray,
    window_sec: float,
    hop_sec: float,
    min_purity: float,
) -> Iterator[tuple[float, float, int, float]]:
    n = len(labels)
    window_n = int(round(window_sec * LABEL_FS))
    hop_n = int(round(hop_sec * LABEL_FS))
    if window_n <= 0 or hop_n <= 0 or n < window_n:
        return
    allowed = {WESAD_BASELINE, WESAD_STRESS}
    start = 0
    while start + window_n <= n:
        chunk = labels[start : start + window_n]
        values, counts = np.unique(chunk, return_counts=True)
        majority = int(values[int(np.argmax(counts))])
        purity = float(counts.max() / chunk.size)
        if majority in allowed and purity >= min_purity:
            t0 = start / LABEL_FS
            yield t0, t0 + window_sec, majority, purity
        start += hop_n


def _split_of(subject_id: str) -> str:
    for name, members in SUBJECT_SPLIT.items():
        if subject_id in members:
            return name
    raise KeyError(f"Subject {subject_id} is not in the Phase-1 split")
