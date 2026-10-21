"""합성 Homekit2020 — 승인 전에 로더와 지속성 계층을 끝까지 돌려보기 위한 것.

실제 데이터와 **같은 파일 배치·열 이름**으로 쓴다. 승인이 나면 경로만 바꾸면 된다.

!! 중요 !!
여기서 나오는 탐지율·경보율은 연구 결과가 아니다. 감염 효과(+6 bpm)와
운동·수면 효과(+4 bpm)를 우리가 직접 심었으므로 설명 계층이 이기는 것이
당연하다. 용도는 (1) 코드가 끝까지 도는지 (2) 날 경계·기준선·라벨 정렬이
의도대로인지 확인하는 것뿐이다.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import homekit as H

NIGHT_START_H = 23          # 23:00 잠듦
NIGHT_END_H = 6.5           # 06:30 깸
WINDOW_START_H = 20         # 분 단위는 20:00 ~ 다음 날 10:00 만 만든다 (용량)
WINDOW_HOURS = 14


def simulate(n_subjects=12, n_days=70, flu_frac=0.4, seed=0,
             start="2020-02-01", missing_frac=0.05):
    """하루 단위 '진실' 표를 만든다. 반환: (truth, events)

    truth 열: subject_id, day, base_hr, exercise_prev, short_sleep, flu, missing
    밤 d 는 깨어난 날 d 에 붙는다 (homekit.DAY_SHIFT 와 같은 규약).
    """
    rng = np.random.default_rng(seed)
    days = pd.date_range(start, periods=n_days, freq="D")
    rows, events = [], set()
    for s in range(n_subjects):
        sid = "P{:03d}".format(s)
        base = rng.normal(60, 7)
        active = rng.random(n_days) < 0.2          # 그날 고강도 운동
        short = rng.random(n_days) < 0.1           # 그날 밤 잠 부족
        missing = rng.random(n_days) < missing_frac
        flu = np.zeros(n_days, dtype=bool)
        if rng.random() < flu_frac:
            onset = int(rng.integers(45, n_days - 5))   # 기준선(28+7일)이 쌓인 뒤
            flu[max(0, onset - 2): onset + 4] = True     # 증상 이틀 전부터 상승
            events.add((sid, days[onset]))
        for i, d in enumerate(days):
            rows.append(dict(
                subject_id=sid, day=d, base_hr=base,
                active=bool(active[i]),
                exercise_prev=bool(i > 0 and active[i - 1]),
                short_sleep=bool(short[i]), flu=bool(flu[i]),
                missing=bool(missing[i]),
            ))
    return pd.DataFrame(rows), events


def night_hr_mean(truth, rng):
    """그날 밤 평균 심박 = 개인 기준 + 잡음 + 심은 효과."""
    return (truth["base_hr"]
            + rng.normal(0, 1.0, len(truth))
            + 4.0 * truth["exercise_prev"]
            + 4.0 * truth["short_sleep"]
            + 6.0 * truth["flu"])


def write(root, n_subjects=12, n_days=70, seed=0, **kw):
    """실제 v1.0 과 같은 이름으로 root 아래에 쓴다. 반환: (truth, events)"""
    root = Path(root)
    proc = root / "processed"
    proc.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed + 1)
    truth, events = simulate(n_subjects, n_days, seed=seed, **kw)
    truth["night_mean"] = night_hr_mean(truth, rng)

    # 하루 요약
    asleep = np.where(truth["short_sleep"], rng.normal(300, 20, len(truth)),
                      rng.normal(450, 25, len(truth)))
    very_active = np.where(truth["active"], rng.normal(60, 10, len(truth)),
                           rng.uniform(0, 10, len(truth)))
    day = pd.DataFrame({
        "participant_id": truth["subject_id"],
        "date": truth["day"].dt.strftime("%Y-%m-%d"),
        "resting_heart_rate": truth["night_mean"] + 2,
        "total_asleep_minutes": asleep.round(),
        "main_efficiency": rng.normal(92, 3, len(truth)).round(),
        "veryActiveMinutes": very_active.round(),
        "sedentaryMinutes": rng.normal(700, 60, len(truth)).round(),
        "missing_hr": truth["missing"].astype(int),
        "missing_sleep": truth["missing"].astype(int),
        "missing_steps": 0,
    })
    day.to_csv(proc / (H.DAY_TABLE + ".csv"), index=False)

    # PCR — 양성(증상 신고일) + 음성 대조 + 독감 아닌 양성(RSV) 하나씩 섞는다
    lab = [dict(participant_id=s, trigger_datetime=d + pd.Timedelta(hours=9),
                test_name="Influenza A (Flu A)", result="Detected")
           for s, d in sorted(events)]
    lab.append(dict(participant_id="P000", trigger_datetime=pd.Timestamp("2020-03-20 10:00"),
                    test_name="Influenza B (Flu B)", result="Not Detected"))
    lab.append(dict(participant_id="P001", trigger_datetime=pd.Timestamp("2020-03-21 10:00"),
                    test_name="Respiratory Syncytial Virus", result="Detected"))
    pd.DataFrame(lab).to_csv(proc / (H.LAB_TABLE + ".csv"), index=False)

    _write_minutes(proc / H.MINUTE_TABLE, truth, rng)
    return truth, events


def _write_minutes(path, truth, rng):
    """분 단위 parquet. 밤 d 는 (d-1) 23:00 ~ d 06:30 에 놓인다."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.mkdir(parents=True, exist_ok=True)
    n_min = WINDOW_HOURS * 60
    for sid, g in truth.groupby("subject_id"):
        frames = []
        for r in g.itertuples():
            t0 = r.day - pd.Timedelta(days=1) + pd.Timedelta(hours=WINDOW_START_H)
            ts = t0 + pd.to_timedelta(np.arange(n_min), unit="min")
            h = (ts.hour + ts.minute / 60.0).to_numpy()
            asleep = (h >= NIGHT_START_H) | (h < NIGHT_END_H)
            if r.missing:
                asleep[:] = False                 # 안 찬 밤
            hr = np.where(asleep, r.night_mean, r.night_mean + 15) \
                + rng.normal(0, 3, n_min)
            frames.append(pd.DataFrame({
                "participant_id": sid,
                "timestamp": ts,
                "heart_rate": hr.round(1),
                "missing_heart_rate": r.missing,
                "steps": np.where(asleep, 0, rng.poisson(5, n_min)),
                "sleep_classic_0": (~asleep).astype(int),
                "sleep_classic_1": asleep.astype(int),
                "sleep_classic_2": 0,
                "sleep_classic_3": 0,
            }))
        pq.write_table(pa.Table.from_pandas(pd.concat(frames), preserve_index=False),
                       path / "{}.parquet".format(sid))
