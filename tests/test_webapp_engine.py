"""웹앱 판정 엔진 — 화면이 보여줄 상태가 연구 규칙과 맞는가."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "webapp"))
import engine as E  # noqa: E402


@pytest.fixture()
def con(tmp_path):
    c = E.connect(tmp_path / "app.db")
    E.seed_demo(c)
    return c


def test_empty_db_says_no_data(tmp_path):
    c = E.connect(tmp_path / "empty.db")
    s = E.compute(c)
    assert s["status"] == "NO_DATA"
    assert s["baseline"]["mode"] == "early"
    assert s["baseline"]["label"] == "최근 데이터 기준 분석"
    assert s["baseline"]["personalization"] == 0
    blob = __import__("json").dumps(s, ensure_ascii=False)
    assert "7일" not in blob
    assert "착용" not in blob


def test_demo_history_waits_for_tonight_with_two_day_streak(con):
    s = E.compute(con)
    assert s["status"] == "NO_NIGHT"
    assert s["baseline"]["mode"] == "personal"
    assert s["baseline"]["label"] == "개인 패턴 기준 분석"
    assert s["baseline"]["personalization"] == 100
    assert s["streak"] == {"run": 2, "k": 3}           # 마지막 이틀이 이유 없이 높았다
    states = [h["state"] for h in s["history"]]
    assert "learning" in states                         # 기준선 쌓던 초반은 '배우는 중'
    assert states.count("explained") >= 3


def test_deviation_asks_before_judging(con):
    E.demo_night(con, "drink")
    s = E.compute(con)
    assert s["status"] == "ASK"                         # 맥락을 묻기 전에는 판정 보류
    assert s["streak"]["run"] == 2                      # 묻는 날은 연속을 끊지도 잇지도 않는다


def test_alcohol_within_cap_is_explained(con):
    E.demo_night(con, "drink")
    E.put_context(con, E.today(), alcohol=1)
    s = E.compute(con)
    assert s["status"] == "EXPLAINED"
    assert s["night"]["explained_by"] == "alcohol"
    assert s["baseline"]["mode"] == "personal"
    assert s["baseline"]["label"] == "개인 패턴 기준 분석"
    assert s["streak"]["run"] == 2                      # 설명된 날은 보류


def test_no_reason_on_third_day_alerts(con):
    E.demo_night(con, "unexplained")
    E.put_context(con, E.today(), nothing=1)
    s = E.compute(con)
    assert s["status"] == "ALERT"
    assert s["night"]["alert"] is True


def test_alcohol_cannot_cover_a_huge_deviation(con):
    """설명 상한: 술이 보통 만드는 크기를 넘으면 술로 덮지 않는다."""
    E.demo_night(con, "unexplained")                   # +6 bpm ≈ z 6 > 술 상한 4
    E.put_context(con, E.today(), alcohol=1)
    s = E.compute(con)
    assert s["status"] == "ALERT"
    assert s["night"]["explained_by"] == ""


def test_calm_night(con):
    E.demo_night(con, "calm")
    assert E.compute(con)["status"] == "CALM"


def test_context_toggle_and_nothing_are_exclusive(con):
    d = E.today()
    c = E.put_context(con, d, alcohol=1, sleep=1)
    assert c["alcohol"] == 1 and c["sleep"] == 1 and c["nothing"] == 0
    c = E.put_context(con, d, nothing=1)
    assert c == dict(alcohol=0, sleep=0, exercise=0, tense=0, nothing=1)
    c = E.put_context(con, d, tense=1)
    assert c["tense"] == 1 and c["nothing"] == 0


def test_one_button_replaces_the_previous_cause(con):
    d = E.today()
    E.put_context(con, d, tense=1)
    c = E.put_context(con, d, alcohol=1)
    assert c["alcohol"] == 1 and c["tense"] == 0
    E.demo_night(con, "calm")
    E.put_context(con, d, alcohol=1)
    s = E.compute(con)
    assert s["status"] == "CALM"
    assert s["choice"] == "alcohol"
    E.put_context(con, d, note="카페인", nothing=1)
    s = E.compute(con)
    assert s["choice"] == "카페인"
    assert s["night"]["explained_by"] == ""


def test_short_baseline_when_few_days(tmp_path):
    c = E.connect(tmp_path / "few.db")
    import pandas as pd
    end = pd.Timestamp(E.today())
    for i in range(6, 0, -1):
        E.put_night(c, (end - pd.Timedelta(days=i)).date().isoformat(), 60.0 + (i % 2) * 0.5, 400)
    E.put_night(c, E.today(), 60.2, 400)
    s = E.compute(c)
    assert s["baseline"]["mode"] == "adapting"
    assert s["baseline"]["label"] == "최근 같은 기록 기준 분석"
    assert 0 < s["baseline"]["personalization"] < 100
    assert s["status"] == "CALM"


# --- 팝업 알림 ---------------------------------------------------------------
def test_ask_and_alert_each_notify_once_per_day(con):
    E.demo_night(con, "unexplained")
    s = E.compute(con)
    n1 = E.maybe_notify(con, s)
    assert n1["kind"] == "ASK"
    assert E.maybe_notify(con, s) is None              # 같은 날 같은 알림은 한 번만
    E.put_context(con, E.today(), nothing=1)
    s = E.compute(con)
    n2 = E.maybe_notify(con, s)
    assert n2["kind"] == "ALERT" and "3일째" in n2["title"]
    assert E.maybe_notify(con, s) is None


def test_pending_until_acked(con):
    E.demo_night(con, "unexplained")
    n = E.maybe_notify(con, E.compute(con))
    assert [x["id"] for x in E.pending_notices(con, E.today())] == [n["id"]]
    E.ack_notice(con, n["id"])
    assert E.pending_notices(con, E.today()) == []


def test_calm_or_explained_days_do_not_notify(con):
    E.demo_night(con, "calm")
    assert E.maybe_notify(con, E.compute(con)) is None


# --- 얼굴 심박을 판정에 넣기 ----------------------------------------------------
def _baseline(tmp_path, days=30, face=True, face_q=2.0):
    """밤 60 · 얼굴 67 근처를 다섯 값으로 돌려 기준선을 만들고, 오늘의 기준선 값을 돌려준다."""
    import pandas as pd
    c = E.connect(tmp_path / "f.db")
    end = pd.Timestamp(E.today())
    cyc = [-1.0, -0.5, 0.0, 0.5, 1.0]
    for i in range(days, 0, -1):
        d = (end - pd.Timedelta(days=i)).date().isoformat()
        E.put_night(c, d, 60.0 + cyc[i % 5], 400)
        if face:
            E.put_face(c, d, 67.0 + 2 * cyc[i % 5], face_q, 60, 14, 16)
    n = E.compute(c)["night"]
    return c, n


def _night(c, n, z):
    E.put_night(c, E.today(), n["ref"] + z * n["spread"], 400)


def _face(c, n, z, q=2.0):
    E.put_face(c, E.today(), n["face_ref"] + z * n["face_spread"], q, 60, 14, 16)


def test_face_confirms_a_borderline_night(tmp_path):
    c, n = _baseline(tmp_path)
    _night(c, n, 1.75)                                      # 밤 z 1.75 (애매)
    _face(c, n, 2.5)                                        # 얼굴 z 2.5
    s = E.compute(c)
    assert s["night"]["agree"] == "border" and s["night"]["z"] == pytest.approx(2.0)
    assert s["status"] == "ASK"


def test_borderline_night_alone_is_calm(tmp_path):
    c, n = _baseline(tmp_path)
    _night(c, n, 1.75)
    assert E.compute(c)["status"] == "CALM"


def test_face_alone_cannot_flip_a_calm_night(tmp_path):
    c, n = _baseline(tmp_path)
    _night(c, n, 0.0)
    _face(c, n, 5.0)
    s = E.compute(c)
    assert s["night"]["agree"] == "face_only" and s["status"] == "CALM"


def test_face_judges_when_no_night_but_needs_more(tmp_path):
    c, n = _baseline(tmp_path)
    _face(c, n, 2.2)                                        # 얼굴만 z 2.2 < 2.5
    s = E.compute(c)
    assert s["night"]["source"] == "face" and s["status"] == "CALM"
    _face(c, n, 3.0)                                        # 얼굴만 z 3.0 ≥ 2.5
    s = E.compute(c)
    assert s["night"]["agree"] == "face_alone" and s["status"] == "ASK"


def test_low_quality_face_is_ignored(tmp_path):
    c, n = _baseline(tmp_path)
    _face(c, n, 5.0, q=-1.0)                                # 품질 미달
    s = E.compute(c)
    assert s["status"] == "NO_NIGHT" and s["night"]["face_hr"] is None


def _night_table(end, days, hr=58.0, sleep="7.3"):
    import datetime as dt
    lines = ["날짜,심박,수면시간"]
    for i in range(days, 0, -1):
        d = (end - dt.timedelta(days=i)).isoformat()
        lines.append("{},{},{}".format(d, round(hr + (i % 3) * 0.3, 1), sleep))
    return lines


def test_import_csv_asks_when_today_is_high(tmp_path):
    import datetime as dt
    c = E.connect(tmp_path / "imp.db")
    end = dt.date.fromisoformat(E.today())
    lines = _night_table(end, 8)
    lines.append("{},64.0,7.4".format(E.today()))
    out = E.import_nights(c, "\n".join(lines))
    assert out["n"] == 9 and out["skipped"] == 0
    s = E.compute(c)
    assert s["status"] == "ASK"
    assert s["night"]["night_hr"] == 64.0
    assert c.execute("SELECT source FROM nights WHERE day=?", (E.today(),)).fetchone()[0] == "import"


def test_import_short_sleep_minutes_are_stored(tmp_path):
    c = E.connect(tmp_path / "sleep.db")
    text = "day,night_hr,asleep_min\n{},61.0,300".format(E.today())
    # 기준선이 없어도 분 단위 수면은 시간으로 오해하지 않는다
    E.import_nights(c, "날짜,심박,수면\n2020-01-01,58,420\n" + text.split("\n", 1)[1])
    row = c.execute("SELECT night_min, asleep_min FROM nights WHERE day=?", (E.today(),)).fetchone()
    assert row[0] == 300 and row[1] == 300


def test_import_hours_and_skips_garbage(tmp_path):
    c = E.connect(tmp_path / "mix.db")
    text = "\n".join([
        "날짜;심박;수면시간",
        "2026-01-01;58.0;7.5",
        "아님;abc;7",
        "2099-01-01;60;7",
    ])
    # 미래 날짜는 건너뛴다. 2026-01-01 은 오늘(2026-10)보다 과거라 남는다.
    out = E.import_nights(c, text)
    assert out["n"] == 1 and out["skipped"] == 2
    row = c.execute("SELECT asleep_min FROM nights").fetchone()
    assert row[0] == 450


def test_import_empty_table_is_rejected(tmp_path):
    c = E.connect(tmp_path / "emptyimp.db")
    with pytest.raises(ValueError):
        E.import_nights(c, "   \n  ")


def _early_samples(c, low, high=None):
    day = E.today()
    for bpm in low:
        E.add_sample(c, day, bpm)
    for bpm in high or []:
        E.add_sample(c, day, bpm)


def test_empty_db_is_not_a_seven_day_block(tmp_path):
    c = E.connect(tmp_path / "block.db")
    s = E.compute(c)
    assert s["status"] == "NO_DATA"
    assert s["baseline"]["mode"] == "early"
    assert s["status"] != "BASELINE"
    assert "7일" not in __import__("json").dumps(s, ensure_ascii=False)


def test_live_deviation_asks_without_personal_baseline(tmp_path):
    c = E.connect(tmp_path / "live.db")
    _early_samples(c, [61, 60, 62, 59, 61, 60, 58, 61], [80, 82, 79, 81])
    s = E.compute(c)
    assert s["status"] == "ASK"
    assert s["baseline"]["mode"] == "early"
    assert s["baseline"]["label"] == "최근 데이터 기준 분석"
    assert s["baseline"]["personalization"] < 100
    assert s["change"]["kind"] == "intraday"
    assert "개인 패턴" not in s["baseline"]["label"]


def test_single_elevated_night_asks_without_personal_baseline(tmp_path):
    c = E.connect(tmp_path / "onenight.db")
    _early_samples(c, [58, 57, 59, 58, 56, 58, 57, 59])
    E.put_night(c, E.today(), 74, 400)
    s = E.compute(c)
    assert s["baseline"]["mode"] == "early"
    assert s["baseline"]["label"] == "최근 데이터 기준 분석"
    assert s["status"] == "ASK"
    assert s["change"]["kind"] == "night"
    assert s["night"]["explained_by"] == ""


def test_quiet_first_night_is_recording(tmp_path):
    c = E.connect(tmp_path / "quiet.db")
    E.put_night(c, E.today(), 60, 400)
    s = E.compute(c)
    assert s["baseline"]["mode"] == "early"
    assert s["status"] == "RECORDING"
    assert "7일" not in __import__("json").dumps(s, ensure_ascii=False)


def test_early_exercise_removes_the_rise(tmp_path):
    c = E.connect(tmp_path / "move.db")
    _early_samples(c, [61, 60, 62, 59, 61, 60, 58, 61], [80, 82, 79, 81])
    E.put_context(c, E.today(), exercise=1)
    s = E.compute(c)
    assert s["status"] == "EXPLAINED"
    assert s["night"]["explained_by"] == "exercise"
    assert s["baseline"]["mode"] == "early"


def test_caffeine_note_does_not_fully_explain(tmp_path):
    c = E.connect(tmp_path / "coffee.db")
    _early_samples(c, [61, 60, 62, 59, 61, 60, 58, 61], [80, 82, 79, 81])
    E.put_context(c, E.today(), note="카페인")
    s = E.compute(c)
    assert s["note"] == "카페인"
    assert s["status"] != "EXPLAINED"
    assert s["status"] == "WATCH"
    assert s["baseline"]["mode"] == "early"


def test_adapting_compares_recent_nights_and_alcohol_explains(tmp_path):
    import pandas as pd
    c = E.connect(tmp_path / "adapt.db")
    end = pd.Timestamp(E.today())
    vals = [57.2, 58.4, 57.8, 58.9, 57.5]
    for i, hr in zip(range(len(vals), 0, -1), vals):
        E.put_night(c, (end - pd.Timedelta(days=i)).date().isoformat(), hr, 400)
    E.put_night(c, E.today(), 61.0, 400)
    s = E.compute(c)
    assert s["baseline"]["mode"] == "adapting"
    assert s["baseline"]["label"] == "최근 같은 기록 기준 분석"
    assert s["status"] == "ASK"
    E.put_context(c, E.today(), alcohol=1)
    s = E.compute(c)
    assert s["status"] == "EXPLAINED"
    assert s["night"]["explained_by"] == "alcohol"


def test_adapting_does_not_escalate_to_three_day_alert(tmp_path):
    import pandas as pd
    c = E.connect(tmp_path / "adapt-alert.db")
    end = pd.Timestamp(E.today())
    for i in range(7, -1, -1):
        hr = 64.0 if i <= 2 else 58.0 + ((i + 1) % 3) * 0.4
        day = (end - pd.Timedelta(days=i)).date().isoformat()
        E.put_night(c, day, hr, 400)
        if i <= 2:
            E.put_context(c, day, nothing=1)
    s = E.compute(c)
    assert s["baseline"]["mode"] == "adapting"
    assert s["status"] != "ALERT"
    assert s["status"] in ("WATCH", "ASK")


def test_night_stays_primary_when_face_disagrees(tmp_path):
    c, n = _baseline(tmp_path)
    _night(c, n, 3.0)
    _face(c, n, 0.0)
    s = E.compute(c)
    assert s["night"]["agree"] == "night_only" and s["status"] == "ASK"
