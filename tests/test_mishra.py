"""Mishra 로더 — 안정시 정의, 밤 배정, 라벨 파싱."""
import numpy as np
import pandas as pd

from src.nesy import mishra as M


def _night(start, hours, hr=60.0, steps=0, every_s=5):
    t = pd.date_range(start, periods=int(hours * 3600 / every_s), freq="{}s".format(every_s))
    hr_df = pd.DataFrame({"datetime": t, "heartrate": hr})
    m = pd.date_range(t[0].floor("min"), t[-1].floor("min"), freq="min")
    st_df = pd.DataFrame({"datetime": m, "steps": steps})
    return hr_df, st_df


def test_resting_needs_twelve_quiet_minutes():
    """걸음이 멈춘 직후 12분은 안정으로 세지 않는다."""
    hr, st = _night("2023-01-02 00:00", 2)
    st.loc[st["datetime"] < "2023-01-02 00:30", "steps"] = 50   # 0:00~0:29 걷는 중
    _, night = M.subject_tables(hr, st, subject="A")
    # 0:30 부터 조용 -> 0:41 부터 안정 -> 2:00 까지 79분
    assert night["night_min"].iloc[0] == 79


def test_missing_steps_are_not_treated_as_zero():
    hr, st = _night("2023-01-02 00:00", 3)
    st = st[st["datetime"] >= "2023-01-02 01:00"]               # 0~1시 걸음 기록 없음
    _, night = M.subject_tables(hr, st, subject="A")
    assert night["night_min"].iloc[0] == 120 - 11               # 1:11 ~ 2:59


def test_only_night_hours_count_and_attach_to_waking_day():
    hr, st = _night("2023-01-01 20:00", 14)                     # 20시 ~ 다음 날 10시
    _, night = M.subject_tables(hr, st, subject="A")
    assert len(night) == 1
    assert night["day"].iloc[0] == pd.Timestamp("2023-01-02")
    assert night["night_min"].iloc[0] == 360                    # 0~6시만


def test_vigorous_minutes_and_sleep_by_waking_day():
    hr, st = _night("2023-01-02 00:00", 24)
    st.loc[st["datetime"].dt.hour == 18, "steps"] = 120         # 18시 한 시간 고강도
    sleep = pd.DataFrame({
        "datetime": pd.to_datetime(["2023-01-01 23:00", "2023-01-02 03:00", "2023-01-02 03:30"]),
        "stage_duration": [4 * 3600, 1800, 3 * 3600],
        "stage": ["light", "wake", "deep"],
    })
    day, _ = M.subject_tables(hr, st, sleep, subject="A")
    d = day.set_index("day")
    assert d.loc["2023-01-02", "very_active_min"] == 60
    assert d.loc["2023-01-02", "asleep_min"] == 7 * 60            # wake 30분 제외


def test_label_cell_parsing():
    cell = "[Timestamp('2023-08-29 00:00:00'), Timestamp('2022-11-14 00:00:00')]"
    assert M._dates(cell) == [pd.Timestamp("2023-08-29"), pd.Timestamp("2022-11-14")]
    assert M._dates("[NaT]") == []


def test_covid_event_is_last_symptom_before_diagnosis(tmp_path, monkeypatch):
    lab = pd.DataFrame({
        "subject_id": ["A", "B", "C"],
        "category": ["COVID-19", "COVID-19", "Other Illness"],
        # A: 다른 시기 증상(작년) 섞임 / B: 증상일 없음
        "symptom": [[pd.Timestamp("2022-11-14"), pd.Timestamp("2023-08-29")], [],
                    [pd.Timestamp("2023-01-05")]],
        "diagnosis": [[pd.Timestamp("2023-09-03")], [pd.Timestamp("2023-02-01")], []],
        "recovery": [[], [], []],
    })
    monkeypatch.setattr(M, "load_labels", lambda root: lab)
    assert M.load_events(tmp_path) == {("A", pd.Timestamp("2023-08-29")),
                                        ("B", pd.Timestamp("2023-02-01"))}
    assert M.load_events(tmp_path, "Other") == {("C", pd.Timestamp("2023-01-05"))}


def test_file_name_pattern_handles_multi_device_and_longterm(tmp_path):
    d = tmp_path / M.DATA_DIR
    d.mkdir()
    for n in ["AA0HAI1_1_hr.csv", "AA0HAI1_2_hr.csv", "AJWW3IY_hr_longterm.csv",
              "AJWW3IY_steps.csv", "X_notes.txt"]:
        (d / n).write_text("")
    f = M.list_files(tmp_path)
    assert len(f["AA0HAI1"]["hr"]) == 2
    assert len(f["AJWW3IY"]["hr"]) == 1 and len(f["AJWW3IY"]["steps"]) == 1
