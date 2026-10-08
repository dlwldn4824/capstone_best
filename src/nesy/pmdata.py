"""PMData 로더 — '어제 술을 마셔서 그런 건데요' 를 실제 기록으로 잰다.

Thambawita et al., MMSys 2020. Simula, CC BY 4.0.
    datasets.simula.no/downloads/pmdata.zip (공개, 1.4 GB — 음식 사진이 대부분)
노르웨이 16명, 2019-11 ~ 2020-03, Fitbit Versa 2 + 매일 설문.

Mishra 에서 설명 계층이 일하지 않은 이유는 걸음·수면만으로는 '평소와 다른 날' 의
원인 대부분이 기록되지 않았기 때문이었다 (docs/MISHRA.md). 이 데이터에는
**음주 여부와 스트레스가 매일** 기록되어 있다. 감염 라벨은 없다 — 여기서는
헛경보를 얼마나 걷어내는지만 잰다.

구조 감사 결과 (2026-10-03)
    pXX/fitbit/heart_rate.json   [{"dateTime": "2019-11-01 00:00:05", "value": {"bpm": 54, ...}}]
                                 5초 간격, 1인당 ~120 MB. json.load 대신 정규식으로 읽는다.
    pXX/fitbit/sleep.json        세션별 dateOfSleep(깨어난 날) · minutesAsleep · levels.data 단계 구간
    pXX/fitbit/very_active_minutes.json   하루 값
    pXX/googledocs/reporting.csv date(**일/월/년**) · alcohol_consumed (Yes/No/Maybe/거부)
                                 p01 은 0회, p15 는 파일 없음
    pXX/pmsys/wellness.csv       effective_time_frame(UTC) · stress 등 1~5
                                 **5 가 좋은 쪽이다** (stress 는 기분·수면의 질과 양의 상관
                                 ρ=0.41, 0.30). 즉 stress <= 2 가 '스트레스 받음'.
    시각    Fitbit 은 현지 시각, 설문은 UTC → Europe/Oslo 로 바꾼다.

설명 원인 (homekit 의 exercise · sleep_debt 에 더한다)
    alcohol   **전날** 음주 — 술 마신 밤은 깨어난 날에 붙는다
    stress    그날 아침 설문에서 stress <= 2

출력은 homekit.build_day_table() 이 받는 (day, night) 두 표 + 원인 열.

담당: 역할 C
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import homekit as H

LOCAL_TZ = "Europe/Oslo"
ASLEEP_LEVELS = {"light", "deep", "rem", "asleep", "restless"}
STRESSED_MAX = 2
CAUSES = ("exercise", "alcohol", "stress", "sleep_debt")

_HR_RE = re.compile(rb'"dateTime": "([0-9\- :]+)", "value": \{"bpm": (\d+)')


def subjects(root):
    return sorted(p.name for p in Path(root).glob("p[0-9][0-9]") if p.is_dir())


# --- Fitbit -------------------------------------------------------------------
def read_hr(path):
    """5초 심박 JSON 을 정규식으로 읽는다 (json.load 면 1인당 수 GB 메모리)."""
    raw = Path(path).read_bytes()
    m = _HR_RE.findall(raw)
    if not m:
        return pd.DataFrame(columns=["datetime", "heartrate"])
    t, b = zip(*m)
    return pd.DataFrame({"datetime": pd.to_datetime(pd.Series(t).str.decode("ascii")),
                         "heartrate": np.asarray(b, dtype=float)})


def read_sleep(path):
    """sleep.json -> (세션 표, 잠든 구간 표).

    세션: wake_day(dateOfSleep), asleep_min, is_main
    구간: start, end — 잠든 단계(light/deep/rem/asleep/restless)만
    """
    sessions, spans = [], []
    for s in json.loads(Path(path).read_text()):
        sessions.append(dict(day=pd.Timestamp(s["dateOfSleep"]),
                             asleep_min=s.get("minutesAsleep", np.nan),
                             is_main=s.get("mainSleep", True)))
        for seg in (s.get("levels") or {}).get("data", []):
            if seg.get("level") in ASLEEP_LEVELS:
                t0 = pd.Timestamp(seg["dateTime"])
                spans.append((t0, t0 + pd.Timedelta(seconds=seg["seconds"])))
    ses = pd.DataFrame(sessions, columns=["day", "asleep_min", "is_main"])
    sp = pd.DataFrame(spans, columns=["start", "end"]).sort_values("start")
    return ses, sp


def read_daily_value(path, name):
    rows = json.loads(Path(path).read_text())
    df = pd.DataFrame({"day": pd.to_datetime([r["dateTime"] for r in rows]).normalize(),
                       name: pd.to_numeric([r["value"] for r in rows], errors="coerce")})
    return df.groupby("day", as_index=False)[name].sum()


def asleep_mask(times, spans):
    """각 시각이 잠든 구간 안인가. 구간은 겹치지 않는다고 본다."""
    if len(spans) == 0:
        return np.zeros(len(times), dtype=bool)
    starts = spans["start"].to_numpy()
    ends = spans["end"].to_numpy()
    t = pd.to_datetime(times).to_numpy()
    i = np.searchsorted(starts, t, side="right") - 1
    ok = i >= 0
    out = np.zeros(len(t), dtype=bool)
    out[ok] = t[ok] < ends[i[ok]]
    return out


def night_table(hr, spans, subject):
    """잠든 동안의 심박 -> 깨어난 날별 평균 (homekit.nocturnal_partial 재사용)."""
    m = pd.DataFrame({
        "participant_id": subject,
        "timestamp": hr["datetime"],
        "heart_rate": hr["heartrate"],
        "sleep_classic_1": asleep_mask(hr["datetime"], spans).astype(int),
    })
    # 5초 샘플을 분으로 접어 '잠든 분' 단위로 센다
    m["timestamp"] = m["timestamp"].dt.floor("min")
    m = m.groupby(["participant_id", "timestamp"], as_index=False).agg(
        heart_rate=("heart_rate", "mean"), sleep_classic_1=("sleep_classic_1", "max"))
    p = H.nocturnal_partial(m)
    p["night_hr"] = p["hr_sum"] / p["hr_n"]
    return p.rename(columns={"hr_n": "night_min"})[["subject_id", "day", "night_hr", "night_min"]]


# --- 설문 ---------------------------------------------------------------------
def read_alcohol(path):
    """reporting.csv -> 그날 마셨는가 (Yes=True, No=False, 그 외=NaN)."""
    r = pd.read_csv(path)
    day = pd.to_datetime(r["date"], format="%d/%m/%Y", errors="coerce")
    v = r["alcohol_consumed"].map({"Yes": True, "No": False})
    out = pd.DataFrame({"day": day, "drank": v}).dropna(subset=["day"])
    # 하루에 여러 번 적었으면 한 번이라도 Yes 면 Yes
    return out.groupby("day", as_index=False)["drank"].agg(
        lambda s: bool(s.max()) if s.notna().any() else np.nan)


def read_stress(path):
    w = pd.read_csv(path)
    t = pd.to_datetime(w["effective_time_frame"], utc=True).dt.tz_convert(LOCAL_TZ)
    out = pd.DataFrame({"day": t.dt.tz_localize(None).dt.normalize(),
                        "stress_score": pd.to_numeric(w["stress"], errors="coerce")})
    return out.groupby("day", as_index=False)["stress_score"].min()


# --- 한 사람 / 전원 -------------------------------------------------------------
def load_subject(root, sid):
    base = Path(root) / sid
    fb = base / "fitbit"
    hr = read_hr(fb / "heart_rate.json")
    ses, spans = read_sleep(fb / "sleep.json")
    night = night_table(hr, spans, sid)

    day = read_daily_value(fb / "very_active_minutes.json", "very_active_min")
    asleep = ses.groupby("day", as_index=False)["asleep_min"].sum()
    day = day.merge(asleep, on="day", how="outer")

    rep = base / "googledocs" / "reporting.csv"
    alc = read_alcohol(rep) if rep.exists() else pd.DataFrame(columns=["day", "drank"])
    day = day.merge(alc, on="day", how="left")
    wel = base / "pmsys" / "wellness.csv"
    st = read_stress(wel) if wel.exists() else pd.DataFrame(columns=["day", "stress_score"])
    day = day.merge(st, on="day", how="left")

    day["subject_id"] = sid
    return day.sort_values("day").reset_index(drop=True), night


def load(root, verbose=False):
    days, nights = [], []
    for sid in subjects(root):
        d, n = load_subject(root, sid)
        days.append(d)
        nights.append(n)
        if verbose:
            print("  {} 날 {} / 밤 {} / 음주 {}".format(
                sid, len(d), len(n), int(d["drank"].fillna(False).astype(bool).sum())))
    day = pd.concat(days, ignore_index=True)
    night = pd.concat(nights, ignore_index=True)
    for t in (day, night):
        t["day"] = pd.to_datetime(t["day"]).astype("datetime64[ns]")
    night["night_min"] = night["night_min"].astype(float)
    return day, night


def add_context(table, stressed_max=STRESSED_MAX):
    """build_day_table 결과에 alcohol · stress 원인 열을 붙인다.

    alcohol  **전날** 마셨다 (밤을 깨어난 날에 붙였으므로 d 의 밤 = d-1 저녁 직후)
    stress   그날 아침 stress 점수 <= stressed_max (5 가 편안한 쪽)
    기록이 없는 날은 False — '모른다' 를 '아니다' 로 세는 셈이므로, 기록률을 같이 보고한다.
    """
    d = table.sort_values(["subject_id", "day"]).copy()
    prev = d.groupby("subject_id")[["day", "drank"]].shift(1)
    yesterday = (d["day"] - prev["day"]).dt.days.eq(1)
    d["alcohol"] = (yesterday & prev["drank"].eq(True)).to_numpy()
    d["stress"] = (d["stress_score"] <= stressed_max).fillna(False).to_numpy(dtype=bool)
    return d.sort_index()
