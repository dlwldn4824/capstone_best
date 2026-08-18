"""Download WESAD and cache wrist-only arrays.

The official zip is ~2.5 GB and includes 700 Hz chest data we do not use
in Phase 1. Pickles are read from the zip in memory and only Empatica E4
channels + 700 Hz labels are written to compact .npz files.
"""

from __future__ import annotations

import pickle
import shutil
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
from tqdm import tqdm

from wesad_phase1.config import Phase1Config, load_config
from wesad_phase1.constants import SUBJECTS, WESAD_URLS, WESAD_ZIP_MIN_BYTES


def download_wesad(cfg: Phase1Config | None = None, force: bool = False) -> Path:
    cfg = cfg or load_config()
    cfg.raw_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cfg.zip_path
    if zip_path.exists() and zip_path.stat().st_size > 1_000_000 and not force:
        print(f"WESAD zip already present: {zip_path}")
        return zip_path

    last_error: Exception | None = None
    for url in WESAD_URLS:
        try:
            print(f"Downloading WESAD from {url}")
            _download_with_resume(url, zip_path)
            size = zip_path.stat().st_size
            if size >= WESAD_ZIP_MIN_BYTES:
                print(f"Downloaded {size / 1e9:.2f} GB → {zip_path}")
                return zip_path
            print(f"File too small ({size} bytes), trying next URL")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(f"Download failed from {url}: {exc}")
    raise RuntimeError(f"Could not download WESAD. Last error: {last_error}")


def cache_wrist_from_zip(cfg: Phase1Config | None = None, force: bool = False) -> list[Path]:
    cfg = cfg or load_config()
    zip_path = download_wesad(cfg)
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with zipfile.ZipFile(zip_path) as zf:
        pkl_map = _subject_pkl_members(zf)
        missing = [sid for sid in SUBJECTS if sid not in pkl_map]
        if missing:
            raise FileNotFoundError(f"Missing subject pickles in zip: {missing}")
        for sid in SUBJECTS:
            out = cfg.cache_dir / f"{sid}_wrist.npz"
            if out.exists() and not force:
                written.append(out)
                continue
            print(f"Extracting wrist cache for {sid}")
            with zf.open(pkl_map[sid]) as handle:
                data = pickle.load(handle, encoding="latin1")
            wrist = data["signal"]["wrist"]
            payload = {
                "subject": np.asarray(sid),
                "bvp": _as1d(wrist["BVP"]),
                "eda": _as1d(wrist["EDA"]),
                "temp": _as1d(wrist["TEMP"]),
                "acc": _as_acc(wrist["ACC"]),
                "label": np.asarray(data["label"], dtype=np.int16).reshape(-1),
            }
            del data
            np.savez_compressed(out, **payload)
            written.append(out)
    return written


def _subject_pkl_members(zf: zipfile.ZipFile) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for name in zf.namelist():
        if not name.endswith(".pkl"):
            continue
        for sid in SUBJECTS:
            if name.endswith(f"{sid}/{sid}.pkl") or name.endswith(f"{sid}.pkl"):
                mapping[sid] = name
                break
    return mapping


def _as1d(arr: np.ndarray) -> np.ndarray:
    return np.asarray(arr, dtype=np.float32).reshape(-1)


def _as_acc(arr: np.ndarray) -> np.ndarray:
    acc = np.asarray(arr, dtype=np.float32)
    if acc.ndim != 2:
        raise ValueError(f"ACC must be 2D, got {acc.shape}")
    if acc.shape[0] == 3 and acc.shape[1] != 3:
        acc = acc.T
    if acc.shape[1] != 3:
        raise ValueError(f"ACC must have 3 axes, got {acc.shape}")
    return acc


def _download_with_resume(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    existing = tmp.stat().st_size if tmp.exists() else 0
    headers = {"User-Agent": "wesad-phase1/0.1"}
    if existing:
        headers["Range"] = f"bytes={existing}-"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=300) as response:
        total = response.headers.get("Content-Length")
        total_bytes = int(total) + existing if total else None
        mode = "ab" if existing and response.status == 206 else "wb"
        if mode == "wb":
            existing = 0
        with tmp.open(mode) as out, tqdm(
            total=total_bytes,
            initial=existing,
            unit="B",
            unit_scale=True,
            desc=dest.name,
        ) as bar:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                bar.update(len(chunk))
    shutil.move(tmp, dest)
