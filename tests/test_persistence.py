"""지속성 계층 — 하루로 접고, 며칠 이어질 때만 알린다."""
import numpy as np
import pandas as pd
import pytest

from src.nesy import persistence as P


def mkday(days, fracs, n=20, subject="A"):
    days = pd.to_datetime(list(days))
    fr = np.asarray(fracs, dtype=float)
    return pd.DataFrame({
        "subject_id": [subject] * len(days),
        "day": days,
        "n_windows": [n] * len(days),
        "n_carried": (fr * n).round().astype(int),
        "carried_frac": fr,
        "valid": [True] * len(days),
    })


def test_daily_folds_windows_by_ratio_not_count():
    """창 수가 사람마다 다르므로 개수가 아니라 비율로 접어야 한다."""
    df = pd.DataFrame({
        "subject_id": ["A"] * 10 + ["B"] * 100,
        "day": [pd.Timestamp("2020-01-01")] * 110,
    })
    carried = [True] * 5 + [False] * 5 + [True] * 50 + [False] * 50
    out = P.daily(df, carried, min_windows=10)
    assert len(out) == 2
    # 넘어간 창은 5개 vs 50개로 10배 차이인데 비율은 같아야 한다
    assert out["n_carried"].tolist() == [5, 50]
    assert out["carried_frac"].round(6).tolist() == [0.5, 0.5]


def test_short_wear_days_are_marked_invalid_not_dropped():
    """착용이 짧은 날을 그냥 버리면 인·월 분모가 틀어진다."""
    df = pd.DataFrame({"subject_id": ["A"] * 12,
                       "day": [pd.Timestamp("2020-01-01")] * 3
                              + [pd.Timestamp("2020-01-02")] * 9})
    out = P.daily(df, [True] * 12, min_windows=5)
    assert len(out) == 2                      # 두 날 다 남아 있고
    assert out["valid"].tolist() == [False, True]   # 짧은 날만 무효 표시


def test_alert_fires_only_after_k_consecutive_days():
    d = mkday(["2020-01-01", "2020-01-02", "2020-01-03"], [0.9, 0.9, 0.9])
    assert P.alerts(d, 0.5, k=3)["alert"].tolist() == [False, False, True]
    assert P.alerts(d, 0.5, k=4)["alert"].sum() == 0     # 하루 모자라면 안 울림


def test_calendar_gap_breaks_the_run():
    """밴드를 2주 벗었다가 다시 찬 이틀을 '3일 연속' 으로 세면 안 된다."""
    d = mkday(["2020-01-01", "2020-01-15", "2020-01-16"], [0.9, 0.9, 0.9])
    assert P.alerts(d, 0.5, k=3, max_gap_days=2)["alert"].sum() == 0
    # 공백을 허용하면 이어지는지도 확인 (동작 자체는 정상)
    assert P.alerts(d, 0.5, k=3, max_gap_days=30)["alert"].sum() == 1


def test_resolved_day_resets_the_run():
    d = mkday(["2020-01-0" + str(i) for i in range(1, 6)],
              [0.9, 0.9, 0.1, 0.9, 0.9])
    assert P.alerts(d, 0.5, k=3)["alert"].sum() == 0


def test_refractory_prevents_one_long_streak_from_alerting_daily():
    """불응기가 없으면 긴 이탈 하나가 매일 울려 경보율이 부풀려진다."""
    days = pd.date_range("2020-01-01", periods=10).strftime("%Y-%m-%d")
    d = mkday(days, [0.9] * 10)
    assert P.alerts(d, 0.5, k=3, refractory_days=7)["alert"].sum() == 2
    assert P.alerts(d, 0.5, k=3, refractory_days=0)["alert"].sum() == 8


def test_subjects_do_not_bleed_into_each_other():
    a = mkday(["2020-01-01", "2020-01-02"], [0.9, 0.9], subject="A")
    b = mkday(["2020-01-03", "2020-01-04"], [0.9, 0.9], subject="B")
    d = pd.concat([a, b], ignore_index=True)
    # 합치면 4일 연속처럼 보이지만 사람이 다르므로 울리면 안 된다
    assert P.alerts(d, 0.5, k=3)["alert"].sum() == 0


def test_evaluate_reports_rate_and_detection_together():
    """경보율만 보면 아무것도 안 하는 시스템이 1등이 된다."""
    days = pd.date_range("2020-01-01", periods=30).strftime("%Y-%m-%d")
    d = mkday(days, [0.9] * 5 + [0.1] * 25)
    d = P.alerts(d, 0.5, k=3, refractory_days=7)
    ev = {("A", pd.Timestamp("2020-01-03"))}
    r = P.evaluate(d, event_days=ev, match_before=1, match_after=1)
    assert r["observed_days"] == 30
    assert r["n_alerts"] == 1
    assert r["detection_rate"] == 1.0          # 1/3 경보가 1/3 사건과 맞음
    assert "alerts_per_person_month" in r and "detection_rate" in r

    silent = P.alerts(mkday(days, [0.0] * 30), 0.5, k=3)
    rs = P.evaluate(silent, event_days=ev)
    assert rs["alerts_per_person_month"] == 0.0   # 경보율은 완벽하지만
    assert rs["detection_rate"] == 0.0            # 아무것도 못 잡는다


def test_fit_day_thresh_uses_train_only():
    """임계값 누수는 이미 한 번 밟았다. 여기서도 막는다."""
    rng = np.random.default_rng(0)
    frac = np.concatenate([rng.uniform(0, 0.5, 50), rng.uniform(0.9, 1.0, 50)])
    d = pd.DataFrame({"carried_frac": frac, "valid": [True] * 100})
    train = np.zeros(100, dtype=bool)
    train[:50] = True
    t1 = P.fit_day_thresh(d, positive=None, train_mask=train, q=0.9)

    d2 = d.copy()
    d2.loc[50:, "carried_frac"] = 999.0        # test fold 오염
    t2 = P.fit_day_thresh(d2, positive=None, train_mask=train, q=0.9)
    assert t1 == t2
    assert t1 < 0.6                             # 뒤쪽 0.9~1.0 을 못 봤어야 한다


def test_sweep_shows_no_free_lunch():
    """K 를 키우면 경보는 줄지만 탐지도 준다 — 어느 쪽도 공짜가 아니다."""
    days = pd.date_range("2020-01-01", periods=40).strftime("%Y-%m-%d")
    fr = np.where(np.arange(40) % 7 < 3, 0.9, 0.1)      # 3일씩 반복 이탈
    d = mkday(days, fr)
    ev = {("A", pd.Timestamp(days[i])) for i in range(40) if i % 7 == 2}
    s = P.sweep(d, 0.5, ks=(2, 3, 4), event_days=ev, refractory_days=1)
    assert list(s["k"]) == [2, 3, 4]
    assert s["alerts_per_person_month"].is_monotonic_decreasing
    assert s.loc[s.k == 4, "n_alerts"].iloc[0] == 0     # 4일 연속은 없다


def test_chance_baseline_flags_a_high_base_rate_as_unremarkable():
    """사건이 흔하면 아무 날에나 울려도 정밀도가 높다. 그걸 잡아내야 한다."""
    days = pd.date_range("2020-01-01", periods=30).strftime("%Y-%m-%d")
    d = mkday(days, [0.9] * 3 + [0.1] * 27)
    d = P.alerts(d, 0.5, k=3, refractory_days=7)
    # 관측일 30일 중 24일이 사건일 — 아무렇게나 울려도 거의 맞는다
    ev = {("A", pd.Timestamp(x)) for x in days[:24]}
    c = P.chance_baseline(d, ev, n_perm=300, match_before=1, match_after=1)
    assert c["chance_alert_precision"] > 0.7      # 우연만으로도 이만큼 나온다
    assert c["p_precision"] > 0.05               # 관측치가 우연을 못 넘는다


def test_chance_baseline_detects_real_alignment():
    """진짜로 사건에 붙어 우는 경보는 우연 수준을 넘어야 한다."""
    days = pd.date_range("2020-01-01", periods=60).strftime("%Y-%m-%d")
    fr = np.where(np.isin(np.arange(60) % 20, [0, 1, 2]), 0.9, 0.1)
    d = P.alerts(mkday(days, fr), 0.5, k=3, refractory_days=5)
    ev = {("A", pd.Timestamp(days[i])) for i in range(60) if i % 20 == 2}
    c = P.chance_baseline(d, ev, n_perm=500, match_before=1, match_after=1)
    assert c["p_detection"] < 0.05               # 우연으로는 안 나온다
