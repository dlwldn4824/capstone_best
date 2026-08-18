from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from wesad_phase1.constants import CONFIG_PATH, ROOT


@dataclass(frozen=True)
class Phase1Config:
    raw_dir: Path
    cache_dir: Path
    processed_dir: Path
    zip_path: Path
    window_sec: float
    hop_sec: float
    min_purity: float
    hr_high_ratio: float
    hrv_low_ratio: float
    eda_high_ratio: float
    temp_delta_c: float
    activity_high_ratio: float


def load_config(path: Path | None = None) -> Phase1Config:
    cfg_path = path or CONFIG_PATH
    with cfg_path.open("r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f)

    data = raw["data"]
    window = raw["window"]
    facts = raw["facts"]
    raw_dir = ROOT / data["raw_dir"]
    cache_dir = ROOT / data["cache_dir"]
    processed_dir = ROOT / data["processed_dir"]
    return Phase1Config(
        raw_dir=raw_dir,
        cache_dir=cache_dir,
        processed_dir=processed_dir,
        zip_path=raw_dir / data["zip_name"],
        window_sec=float(window["length_sec"]),
        hop_sec=float(window["hop_sec"]),
        min_purity=float(window["min_purity"]),
        hr_high_ratio=float(facts["hr_high_ratio"]),
        hrv_low_ratio=float(facts["hrv_low_ratio"]),
        eda_high_ratio=float(facts["eda_high_ratio"]),
        temp_delta_c=float(facts["temp_delta_c"]),
        activity_high_ratio=float(facts["activity_high_ratio"]),
    )
