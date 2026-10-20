"""PMData 로더 — 날짜 형식, 잠든 구간, 전날 음주 정렬."""
import numpy as np
import pandas as pd

from src.nesy import pmdata as PM


def test_reporting_date_is_day_month_year(tmp_path):
    p = tmp_path / "reporting.csv"
    p.write_text("date,timestamp,meals,weight,glasses_of_fluid,alcohol_consumed\n"
                 "06/11/2019,06/12/2019 21:58:30,x,100,7,Yes\n"
                 "07/11/2019,07/12/2019 21:58:30,x,100,7,Do not want to provide this information\n"
                 "07/11/2019,07/12/2019 22:58:30,x,100,7,No\n")
    a = PM.read_alcohol(p).set_index("day")["drank"]
    assert a[pd.Timestamp("2019-11-06")] == True        # 6월 11일이 아니라 11월 6일
    assert a[pd.Timestamp("2019-11-07")] == False       # 거부 + No -> No


def test_stress_uses_local_date_and_worst_score(tmp_path):
    p = tmp_path / "wellness.csv"
    p.write_text("effective_time_frame,stress\n"
                 "2019-11-01T23:30:00.000Z,4\n"         # 오슬로 11-02 00:30
                 "2019-11-02T08:00:00.000Z,2\n")
    s = PM.read_stress(p).set_index("day")["stress_score"]
    assert list(s.index) == [pd.Timestamp("2019-11-02")]
    assert s.iloc[0] == 2


def test_asleep_mask_uses_half_open_spans():
    spans = pd.DataFrame({"start": pd.to_datetime(["2020-01-01 23:00", "2020-01-02 02:00"]),
                          "end": pd.to_datetime(["2020-01-02 01:00", "2020-01-02 06:00"])})
    t = pd.to_datetime(["2020-01-01 22:59", "2020-01-01 23:00", "2020-01-02 01:00",
                        "2020-01-02 03:00", "2020-01-02 06:00"])
    assert PM.asleep_mask(t, spans).tolist() == [False, True, False, True, False]


def test_night_hr_counts_only_asleep_minutes():
    t = pd.date_range("2020-01-01 22:00", "2020-01-02 08:00", freq="5s", inclusive="left")
    inside = (t >= "2020-01-01 23:00") & (t < "2020-01-02 06:00")
    hr = pd.DataFrame({"datetime": t, "heartrate": np.where(inside, 50.0, 80.0)})
    spans = pd.DataFrame({"start": [pd.Timestamp("2020-01-01 23:00")],
                          "end": [pd.Timestamp("2020-01-02 06:00")]})
    n = PM.night_table(hr, spans, "p99")
    assert len(n) == 1 and n["day"].iloc[0] == pd.Timestamp("2020-01-02")
    assert n["night_min"].iloc[0] == 7 * 60
    assert n["night_hr"].iloc[0] == 50.0


def test_alcohol_explains_the_following_night_only():
    t = pd.DataFrame({
        "subject_id": "A",
        "day": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-05", "2020-01-06"]),
        "drank": [True, np.nan, True, False, False],
        "stress_score": [5, 2, np.nan, 3, 1],
    })
    c = PM.add_context(t)
    # 1일 음주 -> 2일 밤 / 3일 음주 -> 4일이 없어 5일로 이어지면 안 된다
    assert c["alcohol"].tolist() == [False, True, False, False, False]
    assert c["stress"].tolist() == [False, True, False, False, True]
