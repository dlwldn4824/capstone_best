"""Homekit2020 로더 — 합성 데이터로 날 경계·기준선·라벨·지속성 연결을 확인한다."""
import numpy as np
import pandas as pd
import pytest

from src.nesy import homekit as H
from src.nesy import homekit_synthetic as S
from src.nesy import persistence as P


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    root = tmp_path_factory.mktemp("homekit")
    truth, events = S.write(root, n_subjects=30, n_days=70, seed=0)
    day = H.load_day(root)
    night = H.load_nocturnal(root, batch_size=50_000)   # 조각 합산 경로를 태운다
    table = H.build_day_table(day, night)
    return dict(root=root, truth=truth, events=events, day=day,
                night=night, table=table)


# --- 날 경계 -------------------------------------------------------------------
def test_night_attaches_to_waking_day():
    """자정을 넘는 밤이 이틀로 갈라지면 안 된다."""
    ts = pd.to_datetime(["2020-03-01 23:30", "2020-03-02 00:30",
                         "2020-03-02 06:00", "2020-03-02 14:00"])
    m = pd.DataFrame({"participant_id": "A", "timestamp": ts,
                      "heart_rate": [60.0, 62.0, 64.0, 90.0],
                      "missing_heart_rate": False,
                      "sleep_classic_1": [1, 1, 1, 0]})
    p = H.nocturnal_partial(m)
    assert len(p) == 1                                   # 한 밤 = 한 날
    assert p["day"].iloc[0] == pd.Timestamp("2020-03-02")
    assert p["hr_sum"].iloc[0] == 186.0                  # 낮(90)은 빠짐


def test_batched_aggregation_equals_whole(synth):
    """조각 크기와 상관없이 같은 밤 심박이 나와야 한다."""
    whole = H.load_nocturnal(synth["root"], batch_size=10_000_000)
    a = synth["night"].set_index(["subject_id", "day"]).sort_index()
    b = whole.set_index(["subject_id", "day"]).sort_index()
    pd.testing.assert_index_equal(a.index, b.index)
    np.testing.assert_allclose(a["night_hr"], b["night_hr"], rtol=1e-9)
    assert (a["night_min"] == b["night_min"]).all()


def test_night_hr_recovers_planted_value(synth):
    t = synth["truth"][~synth["truth"]["missing"]].set_index(["subject_id", "day"])
    n = synth["night"].set_index(["subject_id", "day"])
    j = t.join(n, how="inner")
    assert len(j) == len(t)
    # 잡음 sd 3, 약 450분 평균 -> 표준오차 0.14, 800밤 최댓값도 1 bpm 이내
    assert np.abs(j["night_hr"] - j["night_mean"]).max() < 1.0


# --- 기준선 --------------------------------------------------------------------
def _mk(values, valid=None):
    n = len(values)
    return pd.DataFrame({"subject_id": "A",
                         "day": pd.date_range("2020-01-01", periods=n),
                         "x": np.asarray(values, dtype=float),
                         "valid": np.ones(n, bool) if valid is None else valid})


def test_rolling_z_uses_no_future():
    rng = np.random.default_rng(0)
    v = rng.normal(60, 1, 60)
    z1 = H.rolling_z(_mk(v), "x")
    v2 = v.copy()
    v2[50:] += 30                                          # 미래만 바꾼다
    z2 = H.rolling_z(_mk(v2), "x")
    np.testing.assert_array_equal(z1[:50], z2[:50])


def test_recent_lag_days_are_excluded_from_baseline():
    """잠복기(최근 7일)가 기준선에 섞이면 이탈이 희석된다."""
    rng = np.random.default_rng(1)
    v = rng.normal(60, 1, 60)
    v[52:] += 10                                           # 52일부터 상승
    z = H.rolling_z(_mk(v), "x", lag=7)
    assert z[58] > 5                                       # 상승 7일째도 크게 남는다


def test_rolling_z_is_nan_until_baseline_forms():
    z = H.rolling_z(_mk(np.full(30, 60.0) + np.arange(30) % 3), "x",
                    window=28, lag=7, min_n=14)
    assert np.isnan(z[:21]).all()                          # 7 + 14 일 전에는 판정 안 함
    assert np.isfinite(z[21:]).any()


# --- 설명 ----------------------------------------------------------------------
def test_exercise_explains_the_following_night(synth):
    t = synth["table"].merge(
        synth["truth"][["subject_id", "day", "exercise_prev", "short_sleep"]],
        on=["subject_id", "day"])
    # 전날 운동한 밤을 대부분 잡고, 아닌 밤은 거의 안 잡는다
    assert t.loc[t["exercise_prev"], "exercise"].mean() > 0.8
    assert t.loc[~t["exercise_prev"], "exercise"].mean() < 0.1
    assert t.loc[t["short_sleep"], "sleep_debt"].mean() > 0.9


# --- 라벨 ----------------------------------------------------------------------
def test_events_keep_only_flu_positive_trigger_days(synth):
    ev = H.load_events(synth["root"])
    assert ev == synth["events"]                           # 음성·RSV 는 빠진다
    assert all(d == d.normalize() for _, d in ev)


# --- persistence 연결 ----------------------------------------------------------
def test_table_matches_persistence_contract(synth):
    t = synth["table"]
    for c in ("subject_id", "day", "carried_frac", "valid"):
        assert c in t.columns
    assert set(np.unique(t["carried_frac"])) <= {0.0, 1.0}
    # 판정 불가한 날(기준선 미형성·안 찬 밤)은 valid=False 로 남아 있어야 한다
    assert (~t["valid"]).sum() > 0
    assert len(t) == len(synth["truth"])


def test_explanation_trades_little_detection_for_many_fewer_alerts(synth):
    """합성 데이터에서 설명 계층이 의도대로 동작하는지 (연구 결과 아님).

    탐지를 '잃지 않는다' 고 쓰지 않는다. 감염 중 운동한 날은 운동으로
    설명되어 가려질 수 있다 — 실제 데이터에서도 이 손실을 같이 보고해야 한다.
    """
    t = synth["table"]
    ev = synth["events"]
    kw = dict(match_before=3, match_after=1)
    t2 = H.apply_explanation(t, ceiling=H.fit_cause_ceiling(t))

    ours = P.evaluate(P.alerts(t2, 0.5, k=2, hold_col="held"), event_days=ev, **kw)
    raw = P.evaluate(P.alerts(t.assign(carried_frac=t["carried_raw"]), 0.5, k=2),
                     event_days=ev, **kw)

    assert ours["n_alerts"] * 2 < raw["n_alerts"]
    assert ours["alert_precision"] > raw["alert_precision"] + 0.3
    assert ours["detection_rate"] >= raw["detection_rate"] - 0.2


def test_ceiling_keeps_large_deviation_open(synth):
    """운동한 다음 날이라도 운동이 보통 만드는 크기를 넘으면 닫지 않는다."""
    t = synth["table"].copy()
    i = t.index[t["valid"] & t["exercise"]][0]
    t.loc[i, "night_z"] = 50.0
    cap = H.fit_cause_ceiling(t)
    assert cap["exercise"] is not None and cap["exercise"] < 50
    no_cap = H.apply_explanation(t)
    with_cap = H.apply_explanation(t, ceiling=cap)
    assert no_cap.loc[i, "held"] and no_cap.loc[i, "carried_frac"] == 0
    assert not with_cap.loc[i, "held"] and with_cap.loc[i, "carried_frac"] == 1


def test_random_filter_drops_same_count(synth):
    t = synth["table"]
    drop = (t["carried_raw"] - t["carried_frac"]).groupby(t["subject_id"]).sum()
    carried, held = H.random_filter(t, drop.to_dict(), seed=0)
    assert carried.sum() == t["carried_frac"].sum()
    assert held.sum() == t["held"].sum()           # 걷어낸 날은 보류로 남는다
    assert not (held & (carried > 0)).any()


def test_subject_split_is_disjoint():
    tr, te = H.subject_split(["a", "b", "c", "d", "e", "a"], test_frac=0.4)
    assert tr.isdisjoint(te) and tr | te == {"a", "b", "c", "d", "e"}
