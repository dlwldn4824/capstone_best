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
    assert E.compute(c)["status"] == "NO_DATA"


def test_demo_history_waits_for_tonight_with_two_day_streak(con):
    s = E.compute(con)
    assert s["status"] == "NO_NIGHT"
    assert s["baseline"]["mode"] == "standard"
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


def test_short_baseline_when_few_days(tmp_path):
    c = E.connect(tmp_path / "few.db")
    import pandas as pd
    end = pd.Timestamp(E.today())
    for i in range(6, 0, -1):
        E.put_night(c, (end - pd.Timedelta(days=i)).date().isoformat(), 60.0 + (i % 2) * 0.5, 400)
    E.put_night(c, E.today(), 60.2, 400)
    s = E.compute(c)
    assert s["baseline"]["mode"] == "short"
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


def test_night_stays_primary_when_face_disagrees(tmp_path):
    c, n = _baseline(tmp_path)
    _night(c, n, 3.0)
    _face(c, n, 0.0)
    s = E.compute(c)
    assert s["night"]["agree"] == "night_only" and s["status"] == "ASK"
