"""거울 기록 엔진 — 기획 변경 보고서의 판단 규칙(7.2)을 그대로 지키는가."""
import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "webapp"))
import mirror as M  # noqa: E402

from src.nesy import rppg as R  # noqa: E402


@pytest.fixture()
def con(tmp_path):
    return M.connect(tmp_path / "m.db")


def at(day, hh, mm=0):
    return dt.datetime.combine(dt.date.fromisoformat(day), dt.time(hh, mm))


def put(con, day, routine, bpm, q=True, a_rel=1.8, makeup=False):
    hh = {"morning": 7, "desk": 14, "night": 23}[routine]
    return M.add_record(con, bpm, 3.0, 140, 0.01, q, a_rel, 14, makeup, routine, at(day, hh))


def days(start, n):
    d0 = dt.date.fromisoformat(start)
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range(n)]


# --- FR-02 루틴 식별 ---------------------------------------------------------------
@pytest.mark.parametrize("hh,expect", [(7, "morning"), (14, "desk"), (23, "night"), (2, "night")])
def test_routine_from_time(hh, expect):
    assert M.routine_for(dt.datetime(2026, 10, 1, hh)) == expect


def test_routine_hint_from_shortcut_wins():
    assert M.routine_for(dt.datetime(2026, 10, 1, 23), "morning") == "morning"


# --- FR-09 루틴별 베이스라인 -------------------------------------------------------
def test_needs_four_samples_before_judging(con):
    for i, d in enumerate(days("2026-10-01", 3)):
        assert put(con, d, "morning", 62 + i * 0.3)["judgement"] == "building"
    assert put(con, "2026-10-04", "morning", 62.2)["judgement"] == "building"   # 기준에 3개뿐
    assert put(con, "2026-10-05", "morning", 62.0)["judgement"] == "same"       # 이제 4개


def test_routines_are_not_mixed(con):
    """착석 심박이 높아도 아침 기준과 섞지 않는다 — 섞으면 착석은 매번 '상승'."""
    for d in days("2026-10-01", 5):
        put(con, d, "morning", 62.0 + (hash(d) % 3) * 0.4)
        put(con, d, "desk", 72.0 + (hash(d) % 3) * 0.4)
    assert put(con, "2026-10-06", "desk", 72.5)["judgement"] == "same"
    assert put(con, "2026-10-06", "morning", 62.5)["judgement"] == "same"


def test_k_times_mad_rule(con):
    for i, d in enumerate(days("2026-10-01", 6)):
        put(con, d, "desk", [70, 71, 72, 73, 74, 72][i])
    bl = M.baseline(con, "desk", "2026-10-07")
    k = M.settings(con)["k"]
    edge = bl["med"] + k * bl["mad"]
    assert put(con, "2026-10-07", "desk", edge - 0.1)["judgement"] == "same"
    assert put(con, "2026-10-08", "desk", edge + 0.1)["judgement"] == "diff"


def test_low_quality_is_excluded_from_baseline_and_judgement(con):
    for d in days("2026-10-01", 5):
        put(con, d, "night", 66.0)
        put(con, d, "night", 99.0, q=False)              # 품질 미달은 기준에 안 들어간다
    bl = M.baseline(con, "night", "2026-10-06")
    assert bl["n"] == 5 and bl["med"] == 66.0
    assert put(con, "2026-10-06", "night", 99.0, q=False)["judgement"] == "low"


def test_exam_week_never_enters_baseline(con):
    M.set_setting(con, "exam_start", "2026-10-08")
    M.set_setting(con, "exam_end", "2026-10-21")
    for d in days("2026-10-01", 7):                      # 준비 주간
        put(con, d, "desk", 72.0 + (hash(d) % 3) * 0.3)
    for d in days("2026-10-08", 6):                      # 시험 주간 — 계속 높다
        put(con, d, "desk", 82.0)
    r = put(con, "2026-10-14", "desk", 82.0)
    assert r["phase"] == "exam" and r["judgement"] == "diff"     # 시험 값이 기준이 되면 변화가 묻힌다
    assert M.baseline(con, "desk", "2026-10-14")["med"] < 73


def test_phases(con):
    s = {"exam_start": "2026-10-08", "exam_end": "2026-10-21"}
    assert [M.phase_for(d, s) for d in ("2026-09-30", "2026-10-01", "2026-10-08", "2026-10-22", "2026-10-28", "2026-10-29")] == \
        ["none", "prep", "exam", "recovery", "recovery", "none"]


# --- FR-07 · FR-12 안색 ---------------------------------------------------------
def test_makeup_excludes_complexion_but_keeps_heart(con):
    for d in days("2026-10-01", 5):
        put(con, d, "morning", 62.0, a_rel=1.8 + (hash(d) % 3) * 0.1)
    r = put(con, "2026-10-06", "morning", 62.0, a_rel=9.0, makeup=True)
    assert r["a_judgement"] == "excluded" and r["judgement"] == "same"
    r = put(con, "2026-10-07", "morning", 62.0, a_rel=9.0)
    assert r["a_judgement"] == "diff" and r["judgement"] == "same"     # 안색은 판정을 바꾸지 않는다


# --- FR-11 이유 --------------------------------------------------------------------
def test_answer_and_status(con):
    for d in days("2026-10-01", 5):
        put(con, d, "desk", 72.0 + (hash(d) % 3) * 0.3)
    r = put(con, "2026-10-06", "desk", 85.0)
    assert r["status"] == "ask"
    assert M.answer(con, r["id"], "caffeine", "energy")["status"] == "explained"
    r2 = put(con, "2026-10-07", "desk", 85.0)
    assert M.answer(con, r2["id"], "none")["status"] == "unexplained"
    with pytest.raises(ValueError):
        M.answer(con, r2["id"], "headache")


def test_changing_routine_rejudges(con):
    for d in days("2026-10-01", 5):
        put(con, d, "morning", 62.0 + (hash(d) % 3) * 0.3)
        put(con, d, "desk", 72.0 + (hash(d) % 3) * 0.3)
    r = put(con, "2026-10-06", "morning", 72.0)          # 실은 공부 시작이었다
    assert r["judgement"] == "diff"
    assert M.set_routine(con, r["id"], "desk")["judgement"] == "same"


# --- FR-14 리포트 ----------------------------------------------------------------
def test_report_from_demo(con):
    M.seed_demo(con, at=dt.datetime(2026, 10, 19, 22, 0))
    rp = M.report(con)
    sm = rp["summary"]
    assert rp["ready"] and sm["records"] > 0
    assert sm["with_reason"] + sm["unexplained"] <= sm["changed"]
    assert sm["unexplained"] == 2 and sm["recovery_day"] is not None
    text = " ".join(rp["sentences"])
    for banned in ("진단", "위험", "건강하", "무리하지"):              # 6.6 조언 · 진단 금지
        assert banned not in text


def test_report_needs_exam_period(con):
    assert M.report(con)["ready"] is False


# --- 얼굴 심박 v2 · 안색 지표 (브라우저와 같은 계산) -----------------------------------
def test_v2_matches_browser_reference():
    """브라우저 rppg2.js 로 같은 신호를 돌린 값 (소수점 8자리까지 일치 확인함)."""
    fs, n = 30, 600
    t = np.arange(n) / fs
    p = np.sin(2 * np.pi * 1.2 * t) + 0.3 * np.sin(2 * np.pi * 2.4 * t)
    d = 3 * np.sin(2 * np.pi * 0.1 * t) + 0.5 * np.sin(2 * np.pi * 3.7 * t)
    rgb = np.stack([150 + 0.15 * p + d, 110 + 0.5 * p + d, 90 + 0.1 * p + d], 1)
    bvp = R.pos_v2(rgb, fs)
    hr, snr = R.hr_snr_v2(bvp, fs)
    assert [round(float(v), 8) for v in bvp[:3]] == [0.00236807, 0.00792992, 0.0140185]
    assert hr == pytest.approx(72.0703125) and snr == pytest.approx(14.616987, abs=1e-5)


def test_complexion_relative_index_cancels_common_light():
    """이마와 볼이 같이 밝아지면 (조명) 상대 지표는 거의 그대로다."""
    fh = np.tile([135.0, 100.0, 81.0], (100, 1))
    ck = np.tile([143.0, 103.0, 83.0], (100, 1))
    a = R.complexion(fh, ck)
    b = R.complexion(fh * 1.15, ck * 1.15)
    assert abs(b["a_rel"] - a["a_rel"]) < abs(b["a_cheek"] - a["a_cheek"])
