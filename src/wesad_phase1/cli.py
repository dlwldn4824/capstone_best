"""CLI: download WESAD, cache wrist signals, build REST/STRESS windows."""

from __future__ import annotations

import argparse
from pathlib import Path

from wesad_phase1.config import load_config
from wesad_phase1.download import cache_wrist_from_zip, download_wesad
from wesad_phase1.facts import add_facts
from wesad_phase1.windows import build_feature_table


def download_main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Download WESAD and cache wrist E4 data")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    cfg = load_config()
    download_wesad(cfg, force=args.force)
    paths = cache_wrist_from_zip(cfg, force=args.force)
    print(f"Wrist cache files: {len(paths)}")
    for path in paths:
        print(f"  {path}")


def windows_main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build REST/STRESS window feature table")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    cfg = load_config()
    cfg.processed_dir.mkdir(parents=True, exist_ok=True)
    df = build_feature_table(cfg)
    df = add_facts(df, cfg)
    out = args.out or (cfg.processed_dir / "wesad_wrist_rest_stress_windows.parquet")
    df.to_parquet(out, index=False)
    csv_out = out.with_suffix(".csv")
    df.to_csv(csv_out, index=False)
    print(df.groupby(["split", "label_name"]).size().unstack(fill_value=0))
    print()
    print(df.groupby("subject_id")["y"].value_counts().unstack(fill_value=0).head(20))
    print(f"\nSaved {len(df)} windows → {out}")
    print(f"CSV copy → {csv_out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="WESAD Phase 1 pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("download")
    sub.add_parser("windows")
    args, rest = parser.parse_known_args()
    if args.cmd == "download":
        download_main(rest)
    elif args.cmd == "windows":
        windows_main(rest)


if __name__ == "__main__":
    main()
