"""Mishra 2020 COVID-19 Wearables 로더 — 공개 데이터로 지속성 계층을 검증한다.

Mishra et al., Nat Biomed Eng 4, 1208 (2020). Stanford (Snyder lab).
README 가 인용하는 '건강한 사람 월 0.66회 헛경보' 논문의 **원자료**다.

    원자료   storage.googleapis.com/gbsc-gcp-project-ipop_public/COVID-19/
             COVID-19-Wearables.zip  (공개, 378 MB)
    라벨     논문 Supplementary Data (41551_2020_640_MOESM3_ESM.xlsx)
             표 3: COVID 증상일·진단일·회복일 / 표 29: 참가자 분류·경보 빈도

구조 감사 결과 (2026-10-03, scripts/18 대신 직접 확인)
    파일     {id}_hr.csv (user, datetime, heartrate) — 초 단위, 중앙 간격 5초
             {id}_steps.csv (user, datetime, steps) — 분 단위
             {id}_sleep.csv (user, datetime, stage_duration, stage) — 32명만
             {id}_hr_longterm.csv 등 — 4명은 장기 기록이 따로 있다
             AA0HAI1 은 기기 3개라 {id}_1_hr.csv 처럼 번호가 붙는다
    날짜     **개인정보 때문에 사람마다 날짜를 옮겼다** (2023~2028년).
             라벨 표도 같은 기준으로 옮겨져 있다 (기간 겹침 확인함).
             요일·계절 효과는 볼 수 없다.
    분류     COVID positive 32 / potential.healthy 73 / Other Illness 15
    밤 기록  0~6시 하루 평균 300분 이상 (40명 표본). 일부 기기는 30분 안팎.

Homekit 과 다른 점
    수면 단계가 32명에게만 있다 → '잠든 분' 대신 Mishra 의 정의를 따른다:
    **앞선 12분 동안 걸음이 0 인 분의 심박** = 안정시 심박. 이것을 밤(0~6시)에만 본다.
    고강도 활동 분은 Fitbit 기준(분당 100보 이상)으로 근사한다.

출력은 homekit.build_day_table() 이 받는 (day, night) 두 표다.
설명·기준선·보류·상한 로직은 homekit 것을 그대로 쓴다.

담당: 역할 C
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import homekit as H

DATA_DIR = "COVID-19-Wearables"
SUPP_XLSX = "mishra_supp_tables.xlsx"
LABEL_SHEET = "SuppTable3_Fig2a_COVID-19"
CATEGORY_SHEET = "SuppTable29_AlarmFreqComparison"

NIGHT_HOURS = (0, 6)        # 밤 = 0시 이상 6시 미만 (현지 시각, 날짜만 옮겨졌다)
REST_WINDOW_MIN = 12        # Mishra RHR 정의: 앞선 12분 걸음 0
VIGOROUS_SPM = 100          # 분당 걸음 >= 100 → 고강도 활동 분으로 근사

_ID_RE = re.compile(r"^(?P<id>[A-Z0-9]+)(?:_\d+)?_(?P<kind>hr|steps|sleep)(?:_longterm)?\.csv$")


# --- 파일 ---------------------------------------------------------------------
def list_files(root):
    """{subject: {"hr": [...], "steps": [...], "sleep": [...]}}"""
    d = Path(root) / DATA_DIR
    if not d.exists():
        d = Path(root)
    out = {}
    for p in sorted(d.glob("*.csv")):
        m = _ID_RE.match(p.name)
        if not m:
            continue
        out.setdefault(m["id"], {"hr": [], "steps": [], "sleep": []})[m["kind"]].append(p)
    return out


def _read(paths, cols):
    frames = [pd.read_csv(p, usecols=cols) for p in paths]
    if not frames:
        return pd.DataFrame(columns=cols)
    df = pd.concat(frames, ignore_index=True)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df


# --- 한 사람 -> 하루 표 ---------------------------------------------------------
def subject_tables(hr, steps, sleep=None, subject=None):
    """한 사람의 원자료 -> (day, night) 행들.

    hr     datetime, heartrate (초 단위)
    steps  datetime, steps (분 단위)
    sleep  datetime, stage_duration(초), stage — 없어도 된다
    """
    # 분 단위로 맞춘다
    hr_min = (hr.assign(minute=hr["datetime"].dt.floor("min"))
                .groupby("minute")["heartrate"].mean())
    st = (steps.assign(minute=steps["datetime"].dt.floor("min"))
               .groupby("minute")["steps"].sum())
    if len(st):
        idx = pd.date_range(st.index.min(), st.index.max(), freq="min")
        st = st.reindex(idx)                      # 기록 없는 분은 NaN (0 아님)
    # 앞선 12분(현재 포함) 걸음 합이 0 이고 12분 모두 기록이 있어야 안정
    known = st.notna().astype(int).rolling(REST_WINDOW_MIN, min_periods=1).sum()
    total = st.fillna(0).rolling(REST_WINDOW_MIN, min_periods=1).sum()
    resting = (known >= REST_WINDOW_MIN) & (total == 0)

    m = pd.DataFrame({"heart_rate": hr_min})
    m["resting"] = resting.reindex(m.index).fillna(False).astype(bool)
    h = m.index.hour
    m["sleep_classic_1"] = (m["resting"] & (h >= NIGHT_HOURS[0]) & (h < NIGHT_HOURS[1])).astype(int)
    m = m.reset_index().rename(columns={"minute": "timestamp", "index": "timestamp"})
    m["participant_id"] = subject
    part = H.nocturnal_partial(m)
    if len(part):
        night = part.assign(night_hr=part["hr_sum"] / part["hr_n"]) \
                    .rename(columns={"hr_n": "night_min"})[["subject_id", "day", "night_hr", "night_min"]]
    else:
        night = pd.DataFrame(columns=["subject_id", "day", "night_hr", "night_min"])

    # 하루 요약: 날 경계는 밤과 같은 정오~정오가 아니라 달력 날짜다.
    # 운동 설명은 '전날 활동' 을 보므로 달력 날짜가 맞다.
    s = st.dropna()
    day = pd.DataFrame({
        "steps": s.groupby(s.index.normalize()).sum(),
        "very_active_min": (s >= VIGOROUS_SPM).groupby(s.index.normalize()).sum(),
    })
    if sleep is not None and len(sleep):
        # 깨어난 날 기준, wake 를 뺀 단계 시간 합
        sl = sleep[sleep["stage"].astype(str).str.lower() != "wake"]
        wake_day = (sl["datetime"] + H.DAY_SHIFT).dt.normalize()
        day["asleep_min"] = (sl["stage_duration"] / 60.0).groupby(wake_day).sum()
    else:
        day["asleep_min"] = np.nan
    day = day.rename_axis("day").reset_index()
    day["subject_id"] = subject
    return day, night


def load(root, subjects=None, verbose=False):
    """전원 -> (day, night). homekit.build_day_table(day, night) 로 넘긴다."""
    files = list_files(root)
    days, nights = [], []
    for sid in sorted(files):
        if subjects is not None and sid not in subjects:
            continue
        f = files[sid]
        if not f["hr"] or not f["steps"]:
            continue
        hr = _read(f["hr"], ["datetime", "heartrate"])
        st = _read(f["steps"], ["datetime", "steps"])
        sl = _read(f["sleep"], ["datetime", "stage_duration", "stage"]) if f["sleep"] else None
        d, n = subject_tables(hr, st, sl, subject=sid)
        days.append(d)
        nights.append(n)
        if verbose:
            print("  {} 날 {} / 밤 {}".format(sid, len(d), len(n)))
    day = pd.concat(days, ignore_index=True)
    night = pd.concat([n for n in nights if len(n)], ignore_index=True)
    # 밤 기록이 없는 사람이 섞이면 날짜 열이 object 로 떨어진다
    for d in (day, night):
        d["day"] = pd.to_datetime(d["day"]).astype("datetime64[ns]")
    night["night_min"] = night["night_min"].astype(float)
    return day, night


# --- 라벨 ---------------------------------------------------------------------
_TS_RE = re.compile(r"Timestamp\('([0-9\-]+)")


def _dates(cell):
    """"[Timestamp('2023-05-22 00:00:00'), ...]" -> [Timestamp, ...] (NaT 은 버린다)"""
    return [pd.Timestamp(x) for x in _TS_RE.findall(str(cell))]


def load_labels(root):
    """표 3 을 사람별 행으로 편다. 반환 열: subject_id, category, symptom, diagnosis, recovery (list)."""
    t = pd.read_excel(Path(root) / SUPP_XLSX, sheet_name=LABEL_SHEET, header=3)
    t = t.dropna(subset=["ParticipantID"])
    return pd.DataFrame({
        "subject_id": t["ParticipantID"].astype(str),
        "category": t["Category"].astype(str),
        "symptom": t["Symptom_dates"].map(_dates),
        "diagnosis": t["covid_diagnosis_dates"].map(_dates),
        "recovery": t["recovery_dates"].map(_dates),
    }).reset_index(drop=True)


def load_categories(root):
    """표 29: {subject: 'COVID positive' | 'potential.healthy' | 'Other Illness'}"""
    t = pd.read_excel(Path(root) / SUPP_XLSX, sheet_name=CATEGORY_SHEET, header=2).iloc[:, :3]
    t = t.dropna(subset=["ParticipantID"])
    return dict(zip(t["ParticipantID"].astype(str), t["caseCategory"].astype(str)))


def load_events(root, category="COVID-19"):
    """사건일 {(subject, day)}.

    COVID-19   진단일 **이전 가장 가까운 증상일** (진단 전 30일 이내).
               표에는 다른 시기의 증상 에피소드도 섞여 있어서, 그대로 다 쓰면
               COVID 가 아닌 날까지 사건이 된다. 증상일이 없으면 진단일.
    Other      그 밖의 질병 — 증상일 전부
    """
    lab = load_labels(root)
    ev = set()
    for r in lab.itertuples():
        if category == "COVID-19" and r.category == "COVID-19":
            for dx in r.diagnosis:
                before = [s for s in r.symptom if pd.Timedelta(0) <= dx - s <= pd.Timedelta(days=30)]
                ev.add((r.subject_id, max(before) if before else dx))
        elif category == "Other" and r.category != "COVID-19":
            ev.update((r.subject_id, s) for s in r.symptom)
    return ev
