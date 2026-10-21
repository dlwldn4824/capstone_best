"""설정 로딩 + 경로 헬퍼."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load_config(path: str | Path = "configs/config.yaml") -> dict:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    with p.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    # 상대 경로를 프로젝트 루트 기준 절대 경로로 바꾼다.
    for key, val in cfg["paths"].items():
        cfg["paths"][key] = str((ROOT / val).resolve())
    return cfg


def load_protocol(path: str | Path = "configs/protocol.yaml") -> dict:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    with p.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)
