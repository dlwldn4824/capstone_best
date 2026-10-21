"""대학생 헬스체크 — 지표 계산(research/src/nesy/vitals.py)과 점수 · 추천 · 저장(webapp/check.py)."""
import datetime as dt
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check as CK  # noqa: E402

from nesy import vitals as V  # noqa: E402


def synth(n=900, fs=30.0):
    """심박 75 bpm(1.25 Hz) · 호흡 15회/분(0.25 Hz) 로 심박이 출렁이는(RSA) 얼굴 RGB. 브라우저 쪽 기준값도 같은 식."""
    t = np.arange(n) / fs
    w = 2 * math.pi * 0.25
    phi = 2 * math.pi * 1.25 * (t - 0.06 / w * np.cos(w * t) + 0.06 / w)
    p = np.sin(phi) + 0.3 * np.sin(2 * phi - 0.5)
    amp = 1 + 0.15 * np.sin(w * t)
    d = 2 * np.sin(2 * math.pi * 0.05 * t)
    b = np.sin(w * t)
    rgb = np.stack([150 + 0.15 * amp * p + d + 0.3 * b, 110 + 0.5 * amp * p + d + 0.3 * b, 90 + 0.1 * amp * p + d + 0.3 * b], 1)
    return t, rgb


def test_synthetic_heart_breath_and_hrv():
    t, rgb = synth()
    m = V.analyze(t, rgb)
    assert m["signal"] == "high"
    assert abs(m["hr"] - 75) < 1.5
    assert m["rr"] is not None and abs(m["rr"] - 15) <= 2          # 심박이 숨 따라 출렁이는 주기
    assert m["rmssd"] is not None and m["rmssd"] > 5                # 출렁임이 있으니 0 이 아니다 (좁은 대역이라 실제보다 작게 잡힌다)
    assert m["irregular"] is False                                  # 규칙적인 신호를 불규칙이라 하지 않는다
    assert 0 <= m["stress"] <= 100


def test_browser_vitals_match():
    """브라우저 vitals.js 로 같은 synth() 를 돌린 값 (in-app 브라우저에서 확인)."""
    t, rgb = synth()
    m = V.analyze(t, rgb)
    ref = {"hr": 75.6, "rmssd": 21.3, "sdnn": 18.1, "si": 682.6, "stress": 87.3, "rr": 14.8, "beats": 38}
    for k, v in ref.items():
        assert m[k] == pytest.approx(v, abs=0.15), k


def test_irregular_beats_are_flagged_and_cleaning():
    rng = np.random.default_rng(1)
    ibi = 0.8 + rng.choice([-0.22, 0.0, 0.22], size=40)            # 들쭉날쭉한 간격
    h = V.hrv(np.concatenate([[0], np.cumsum(ibi)]))
    assert h["big_jump"] > 0.3
    ibi2 = np.r_[np.full(20, 0.8), 2.0, np.full(20, 0.8)]           # 박동 하나 놓침 → 버린다
    ok = V.clean_ibi(ibi2)
    assert not ok[20] and ok.sum() == 40


def test_baevsky_and_stress_scale():
    calm = 0.9 + 0.12 * np.sin(np.arange(40) / 2)                  # 넓게 흔들림 → SI 낮음
    tense = 0.62 + 0.004 * np.sin(np.arange(40) / 2)               # 빠르고 거의 안 흔들림 → SI 높음
    a, b = V.baevsky_si(calm), V.baevsky_si(tense)
    assert a < b and V.stress_score(a) < 30 and V.stress_score(b) > 80
    assert V.stress_score(50) == 0 and V.stress_score(1000) == 100


def test_health_score_reweights_missing_and_ignores_rr():
    m = {"hr": 70, "signal": "high", "stress": 20, "rmssd": 40, "rr": 40}
    a = V.health_score(m, 8, 0, 5)
    b = V.health_score({**m, "rr": 14}, 8, 0, 5)
    assert a["score"] == b["score"]                                 # 호흡은 점수에 안 들어간다 (검증 약함)
    c = V.health_score({**m, "rmssd": None, "stress": None}, 8, 0, 5)
    assert c["score"] is not None and "hrv" not in c["used"]
    assert V.health_score({"hr": 70, "signal": "high"}, 4, 3, 1)["score"] < a["score"]


def test_bmi_korean_cutoffs():
    assert V.bmi(170, 70)["zone"] == "과체중" and V.bmi(170, 60)["zone"] == "정상" and V.bmi(170, 74)["zone"] == "비만"


# --- check.py ----------------------------------------------------------------
@pytest.fixture()
def con(tmp_path):
    return CK.connect(tmp_path / "c.db")


M0 = {"hr": 72.0, "snr": 4.0, "signal": "high", "rmssd": 40.0, "sdnn": 38.0, "pnn50": 12.0, "si": 90.0, "stress": 20.0,
      "hrv_conf": "high", "irregular": False, "rr": 15.0, "rr_conf": "mid"}


def at(d, h):
    return dt.datetime(2026, 10, d, h)


def test_baseline_needs_three_and_vs(con):
    for d in (1, 2):
        CK.add_scan(con, M0, 7, 0, 4, at=at(d, 10))
    r = CK.add_scan(con, M0, 7, 0, 4, at=at(3, 10))
    assert r["baseline"]["hr"] is None                              # 앞선 2번뿐
    r = CK.add_scan(con, {**M0, "hr": 80.0}, 7, 0, 4, at=at(4, 10))
    assert r["baseline"]["hr"] == 72.0 and r["vs"]["hr"] == 8.0


def test_tips_for_students(con):
    r = CK.add_scan(con, {**M0, "stress": 72.0, "hr": 95.0}, 5, 3, 2, at=at(5, 14))
    ids = [t["id"] for t in r["tips"]]
    assert ids[0] == "stress" and r["tips"][0]["action"] == "breath" and len(ids) <= 3
    assert "caffeine" in ids and "sleep" in ids
    good = CK.add_scan(con, M0, 8, 0, 4, at=at(6, 10))
    assert [t["id"] for t in good["tips"]] == ["good"]
    low = CK.add_scan(con, {**M0, "signal": "low"}, 8, 0, 4, at=at(6, 11))
    assert low["tips"][0]["action"] == "retry"
    irr = CK.add_scan(con, {**M0, "irregular": True}, 8, 0, 4, at=at(6, 12))
    assert irr["tips"][0]["id"] == "irregular" and "진단" not in irr["tips"][0]["body"]


def test_breath_pair_shows_before(con):
    b = CK.add_scan(con, {**M0, "stress": 70.0}, 6, 1, 3, kind="before_breath", at=at(7, 15))
    a = CK.add_scan(con, {**M0, "stress": 50.0}, 6, 1, 3, kind="after_breath", pair=b["id"], at=at(7, 15).replace(minute=3))
    assert a["before"]["stress"] == 70.0
    assert CK.state(con, at(7, 16))["last"]["id"] == b["id"]        # 호흡 뒤 측정은 '오늘 컨디션' 이 아니다


def test_demo_and_profile_validation(con):
    CK.seed_demo(con, at=at(19, 22))
    s = CK.state(con, at(19, 22))
    assert s["profile"]["bmi"]["zone"] == "정상" and s["count"] > 15 and s["baseline"]["hr"] is not None
    with pytest.raises(ValueError):
        CK.set_profile(con, height=300)
    with pytest.raises(ValueError):
        CK.add_scan(con, {**M0, "hr": None})


# --- 오늘의 공부 모드 · 인증 그룹 ----------------------------------------------------
def test_study_mode_rules():
    assert CK.study_mode(80, 30, 8, 10)["id"] == "deep"
    assert CK.study_mode(65, 55, 7, 10)["id"] == "split"
    assert CK.study_mode(50, 40, 7, 10)["id"] == "light"
    assert CK.study_mode(80, 30, 4.5, 10)["id"] == "light"          # 잠 5시간 미만이면 점수 좋아도 가볍게
    assert CK.study_mode(80, 30, 8, 23)["id"] == "wrap"
    r = CK.study_mode(65, 55, 7, 10)
    assert r["focus"] == 25 and r["rest"] == 5


def test_group_create_join_and_checkin_rules(con):
    t = dt.datetime(2026, 10, 20, 7, 30)
    g = CK.create_group(con, "a", "준호", "기상 인증방", "07:00", "09:00", at=t)
    assert g["total"] == 1 and g["owner_me"] and len(g["code"]) == 6
    with pytest.raises(ValueError):
        CK.create_group(con, "b", "x", "짧은방", "07:00", "07:30", at=t)          # 1시간 미만
    with pytest.raises(ValueError):
        CK.join_group(con, "b", "서연", "ZZZZZZ", at=t)
    g = CK.join_group(con, "b", "서연", g["code"].lower(), at=t)               # 소문자도 받는다
    assert g["total"] == 2
    ok = CK.add_scan(con, M0, 7, 0, 4, at=t, member="b")
    assert ok["checkins"][0]["status"] == "ok" and ok["checkins"][0]["streak"] == 1
    assert CK.add_scan(con, M0, 7, 0, 4, at=t.replace(minute=40), member="b")["checkins"][0]["status"] == "already"
    assert CK.add_scan(con, {**M0, "signal": "low"}, 7, 0, 4, at=t, member="a")["checkins"][0]["status"] == "no_pulse"
    assert CK.add_scan(con, M0, 7, 0, 4, at=t.replace(hour=10), member="a")["checkins"][0]["status"] == "closed"
    st = CK.group_state(con, "a", t)
    assert st["done"] == 1 and [m["nick"] for m in st["members"]][0] == "서연"
    assert set(st["members"][0]) == {"nick", "me", "owner", "at", "streak"}       # 건강 수치는 그룹에 없다


def test_group_streak_leave_and_owner_handover(con):
    t = dt.datetime(2026, 10, 20, 7, 30)
    code = CK.create_group(con, "a", "준호", "방", at=t)["code"]
    CK.join_group(con, "b", "서연", code, at=t)
    for d in (17, 18, 19):
        CK.add_scan(con, M0, 7, 0, 4, at=dt.datetime(2026, 10, d, 7, 10), member="b")
    assert next(m for m in CK.group_state(con, "b", t)["members"] if m["me"])["streak"] == 3   # 오늘 아직 → 어제까지 3일
    CK.leave_group(con, "a")
    assert CK.group_state(con, "b", t)["owner_me"]                           # 방장이 나가면 넘어간다
    CK.leave_group(con, "b")
    assert con.execute("SELECT COUNT(*) c FROM groups").fetchone()["c"] == 0    # 마지막 사람이 나가면 그룹 삭제


def test_group_demo_includes_device_user(con):
    g = CK.seed_group_demo(con, "me", "하린", at=dt.datetime(2026, 10, 20, 7, 30))
    assert g["total"] == 5 and not g["me_done"] and any(m["me"] for m in g["members"])


def test_each_person_sees_only_own_scans(con):
    t = dt.datetime(2026, 10, 20, 7, 30)
    CK.add_scan(con, M0, 7, 0, 4, at=t, member="a")
    b = CK.add_scan(con, {**M0, "hr": 90.0}, 5, 3, 2, at=t, member="b")
    CK.set_profile(con, "a", height=170, weight=60)
    assert [h["hr"] for h in CK.history(con, mid="a")] == [72.0]
    assert CK.state(con, t, mid="b")["last"]["hr"] == 90.0
    assert CK.state(con, t, mid="b")["profile"].get("height") is None      # 키 · 몸무게도 사람마다
    with pytest.raises(KeyError):
        CK.result(con, b["id"], mid="a")                                    # 남의 측정은 못 연다


def test_group_icon_and_my_streak(con):
    t = dt.datetime(2026, 10, 20, 7, 30)
    g = CK.create_group(con, "a", "준호", "공부방", "07:00", "09:00", icon="coffee", at=t)
    assert g["icon"] == "coffee" and g["my_nick"] == "준호" and g["my_streak"] == 0
    CK.add_scan(con, M0, 7, 0, 4, at=t, member="a")
    assert CK.group_state(con, "a", t)["my_streak"] == 1
    assert CK.create_group(con, "b", "서연", "방2", icon="unknown", at=t)["icon"] == "calm"   # 없는 캐릭터는 기본


def test_multiple_groups_checkin_and_leave(con):
    t = dt.datetime(2026, 10, 20, 7, 30)
    wake = CK.create_group(con, "a", "하린", "기상방", "07:00", "09:00", at=t)["code"]
    study = CK.create_group(con, "a", "하린", "공부방", "19:00", "21:00", at=t)["code"]
    r = CK.add_scan(con, M0, 7, 0, 4, at=t, member="a")
    st = {c["group"]: c["status"] for c in r["checkins"]}
    assert st == {"기상방": "ok", "공부방": "before"}                           # 측정 한 번 → 열린 그룹만 인증
    assert r["checkins"][0]["group"] == "기상방"                              # 인증된 것부터
    r2 = CK.add_scan(con, M0, 7, 0, 4, at=t.replace(hour=19, minute=10), member="a")
    assert {c["group"]: c["status"] for c in r2["checkins"]} == {"기상방": "already", "공부방": "ok"}
    order = [g["name"] for g in CK.groups_state(con, "a", t.replace(hour=18))]
    assert order == ["공부방", "기상방"]                                        # 곧 열리는 그룹이 먼저
    for i in range(3):
        CK.create_group(con, "a", "하린", "방%d" % i, at=t)
    with pytest.raises(ValueError):
        CK.create_group(con, "a", "하린", "여섯째", at=t)                        # 5개까지
    with pytest.raises(ValueError):
        CK.join_group(con, "a", "하린", wake, at=t)                             # 이미 들어간 그룹
    CK.leave_group(con, "a", study)
    assert "공부방" not in [g["name"] for g in CK.groups_state(con, "a", t)] and len(CK.my_groups(con, "a")) == 4
