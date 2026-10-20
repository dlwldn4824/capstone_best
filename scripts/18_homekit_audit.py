"""Homekit2020 구조 감사 — 로더 상수를 믿기 전에 실제 파일을 먼저 본다.

    python scripts/18_homekit_audit.py [--root data/raw/homekit2020] [--synthetic]

src/nesy/homekit.py 의 열 이름은 공개 코드에서 가져온 것이다. 받은 zip 이
그와 다르면 여기서 드러난다. 특히 확인할 것:

  1. 표가 어디 있는가 (find_tables 가 다 찾는가)
  2. 분 단위가 '긴 형식(1행=1분)' 인가, petastorm 배열 형식인가
  3. sleep_classic_0~3 의 의미 — 0 이 '기록 없음' 인가 (ASLEEP_COLS 결정)
  4. timestamp 가 현지 시각인가 (수면 시작 시각 분포가 22~01시에 몰리는가)
  5. PCR 양성 수 — 탐지율 신뢰구간의 크기를 정한다
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from _bootstrap import banner, setup

from nesy import homekit as H

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/raw/homekit2020")
    ap.add_argument("--synthetic", action="store_true",
                    help="data/cache/homekit_synth 에 합성 데이터를 만들어 감사")
    args = ap.parse_args()
    setup()

    root = ROOT / args.root
    if args.synthetic:
        from nesy import homekit_synthetic as S
        root = ROOT / "data/cache/homekit_synth"
        S.write(root, n_subjects=30, n_days=70)
        print("!! 합성 데이터 - 구조 확인용")

    banner("1. 표 위치")
    tables = H.find_tables(root)
    for name in (H.DAY_TABLE, H.LAB_TABLE, H.SURVEY_TABLE, H.MINUTE_TABLE):
        print("  {:42s} {}".format(name, tables.get(name, "!! 없음")))
    print("\n  root 아래 csv / parquet 디렉터리 (상위 30개):")
    for p in sorted(root.rglob("*.csv"))[:30]:
        print("   ", p.relative_to(root))

    if H.DAY_TABLE in tables:
        banner("2. 하루 단위 표")
        raw = pd.read_csv(tables[H.DAY_TABLE], nrows=200_000)
        missing = [c for c in H.DAY_COLS if c not in raw.columns]
        print("  열 {}개, 로더가 기대하는데 없는 열: {}".format(len(raw.columns), missing or "없음"))
        day = H.load_day(root)
        per = day.groupby("subject_id")["day"].agg(["size", "min", "max"])
        print("  사람 {}명 / 사람-날 {:,}개".format(len(per), len(day)))
        print("  1인당 일수: 중앙 {:.0f}, 최소 {}, 최대 {}".format(
            per["size"].median(), per["size"].min(), per["size"].max()))
        print("  기간: {} ~ {}".format(day["day"].min().date(), day["day"].max().date()))
        for c in ("rhr", "asleep_min", "very_active_min"):
            if c in day:
                print("  {:16s} 결측 {:5.1%}  중앙 {:.1f}".format(
                    c, day[c].isna().mean(), day[c].median()))

    if H.MINUTE_TABLE in tables:
        banner("3. 분 단위 (첫 조각만)")
        import pyarrow.dataset as ds
        dset = ds.dataset(str(tables[H.MINUTE_TABLE]), format="parquet", partitioning="hive")
        print("  스키마:")
        for f in dset.schema:
            print("    {:28s} {}".format(f.name, f.type))
        absent = [c for c in H.MINUTE_COLS if c not in dset.schema.names]
        print("  로더가 기대하는데 없는 열:", absent or "없음")
        batch = next(dset.to_batches(batch_size=500_000)).to_pandas()
        sl = [c for c in batch.columns if c.startswith("sleep_classic_")]
        if sl:
            print("\n  수면 단계별 비율 (한 분에 둘 이상 켜지면 형식이 다르다):")
            print(batch[sl].mean().round(3).to_string())
            print("  동시에 켜진 단계 수 분포:",
                  batch[sl].sum(axis=1).value_counts().sort_index().to_dict())
        if "timestamp" in batch and H.ASLEEP_COLS[0] in batch:
            ts = pd.to_datetime(batch["timestamp"])
            asleep = batch[H.ASLEEP_COLS[0]] > 0
            hrs = ts[asleep].dt.hour.value_counts(normalize=True).sort_index()
            print("\n  잠든 분의 시각 분포 (현지 시각이면 0~6시에 몰린다):")
            print("   ", {int(k): round(v, 3) for k, v in hrs.items()})

    if H.LAB_TABLE in tables:
        banner("4. PCR 라벨")
        lab = pd.read_csv(tables[H.LAB_TABLE])
        print("  열:", list(lab.columns))
        for c in ("test_name", "result"):
            if c in lab:
                print("\n  {}:\n{}".format(c, lab[c].value_counts().to_string()))
        ev = H.load_events(root)
        print("\n  독감 양성 사건 {}건 / {}명".format(len(ev), len({s for s, _ in ev})))
        if len(ev) < 30:
            print("  !! 30건 미만 - 탐지율 95% 신뢰구간 폭이 ±0.15 이상이다.")


if __name__ == "__main__":
    main()
