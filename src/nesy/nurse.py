"""Nurse Stress Dataset 로더.

Hosseini et al., Sci Data 9 (2022). Dryad doi:10.5061/dryad.5hqbzkh6f (CC-BY 4.0).
간호사 15명이 실제 병원 근무 중 착용한 Empatica E4 기록.

Hongn 과 다른 점 (구조 감사 결과는 docs/NURSE_DATASET_AUDIT.md)
    세션    E4 녹화 단위로 zip 이 나뉜다. 파일명 epoch 가 시작 시각.
            609개 세션 / 15명 (1인당 9~90개)
    라벨    tags.csv 가 비어 있다. 설문(SurveyResults.xlsx)의 사건 시각으로 붙인다.
    시각    설문은 **현지 시각**, 신호는 epoch(UTC).
            반드시 America/Chicago 로 변환해야 한다 (4~12월이라 DST 경계를 넘는다).
    운동    운동 라벨이 없다. 다만 간호사는 근무 중 계속 걷는다.

신호 포맷은 Hongn 과 같아 io_e4 를 그대로 쓴다 (타임스탬프만 epoch 실수).
"""
from __future__ import annotations

import datetime
import zipfile
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

# 연구 기관이 University of Louisiana at Lafayette 이므로 미국 중부시간.
# 고정 오프셋을 쓰면 안 된다 — 서머타임 경계에서 1시간 어긋난다.
# 검정 결과: UTC 그대로 19.6% / UTC-5 74.0% / UTC-6 75.7% / America/Chicago 78.5%
LOCAL_TZ = ZoneInfo("America/Chicago")

SIGNAL_FILES = ("ACC", "BVP", "EDA", "HR", "TEMP", "IBI")


def extract_sessions(zip_path, out_dir, overwrite=False):
    """중첩 zip 을 풀어 sessions/{subject}/{session_id}/ 구조로 만든다."""
    zip_path, out_dir = Path(zip_path), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    outer = zipfile.ZipFile(zip_path)
    inner_names = [n for n in outer.namelist() if n.endswith(".zip")]

    made = []
    for name in inner_names:
        subject = name.split("/")[0]
        session_id = Path(name).stem                     # 예: 15_1594140175
        dest = out_dir / subject / session_id
        if dest.exists() and not overwrite:
            made.append(str(dest))
            continue
        dest.mkdir(parents=True, exist_ok=True)
        import io
        with zipfile.ZipFile(io.BytesIO(outer.read(name))) as iz:
            iz.extractall(dest)
        made.append(str(dest))
    return made


def session_start(session_id):
    """세션 id 에서 시작 epoch 를 뽑는다. '15_1594140175' -> 1594140175."""
    return float(str(session_id).split("_")[-1])


def discover_sessions(sessions_root):
    """(subject, session_id, path) 목록."""
    root = Path(sessions_root)
    rows = []
    for subj in sorted(p for p in root.iterdir() if p.is_dir()):
        for sess in sorted(p for p in subj.iterdir() if p.is_dir()):
            rows.append({"subject_id": subj.name, "session_id": sess.name,
                         "session_type": "SHIFT", "path": str(sess),
                         "t0": session_start(sess.name)})
    return pd.DataFrame(rows)


def session_span(path, io_e4):
    """세션의 실제 (시작, 종료) epoch. BVP 를 기준으로 한다."""
    sig = io_e4.read_signal(Path(path) / "BVP.csv")
    if sig is None or len(sig) == 0:
        return None, None, 0.0
    t0 = sig.t0
    dur = len(sig) / sig.fs
    return t0, t0 + dur, dur


# --- 라벨 ------------------------------------------------------------------

def load_events(survey_path):
    """SurveyResults.xlsx -> 스트레스 사건 테이블 (epoch 변환 포함).

    돌려주는 열: subject_id, start, end, level, causes, description
    level 은 0/1/2 또는 NaN('na').
    """
    d = pd.read_excel(survey_path)
    d = d.dropna(subset=["ID"]).copy()
    d["subject_id"] = d["ID"].astype(str).str.strip()

    def to_epoch(row, col):
        try:
            day = pd.to_datetime(row["date"]).date()
            tod = pd.to_datetime(str(row[col])).time()
        except Exception:
            return np.nan
        return (datetime.datetime.combine(day, tod)
                .replace(tzinfo=LOCAL_TZ).timestamp())

    d["start"] = d.apply(lambda r: to_epoch(r, "Start time"), axis=1)
    d["end"] = d.apply(lambda r: to_epoch(r, "End time"), axis=1)
    # 자정을 넘긴 교대: 종료가 시작보다 앞이면 하루 더한다
    flip = d["end"] < d["start"]
    d.loc[flip, "end"] = d.loc[flip, "end"] + 24 * 3600

    d["level"] = pd.to_numeric(d["Stress level"], errors="coerce")

    cause_cols = [c for c in d.columns if c not in (
        "ID", "subject_id", "Start time", "End time", "duration", "date",
        "Stress level", "level", "start", "end", "Description")]
    d["causes"] = d[cause_cols].apply(
        lambda r: "|".join(c.strip() for c in cause_cols
                           if pd.to_numeric(r[c], errors="coerce") == 1), axis=1)
    d["description"] = d.get("Description", "")
    return d[["subject_id", "start", "end", "level", "causes",
              "description"]].reset_index(drop=True)


def label_window(t0, t1, events_for_subject, min_overlap=0.5):
    """윈도 [t0, t1) 에 겹치는 사건을 찾아 라벨을 준다.

    반환 (label, level, causes)
      label: 'STRESS_EVENT'  겹침 비율이 min_overlap 이상이고 level >= 1
             'REPORTED_CALM' 겹치는 사건의 level == 0
             None            겹치는 사건 없음  <- '스트레스 없음' 이 아니다
    """
    if events_for_subject is None or len(events_for_subject) == 0:
        return None, np.nan, ""
    w = t1 - t0
    best, best_ov = None, 0.0
    for _, e in events_for_subject.iterrows():
        ov = min(t1, e["end"]) - max(t0, e["start"])
        if ov > best_ov:
            best, best_ov = e, ov
    if best is None or best_ov / max(w, 1e-9) < min_overlap:
        return None, np.nan, ""
    lvl = best["level"]
    if pd.notna(lvl) and lvl == 0:
        return "REPORTED_CALM", lvl, best["causes"]
    if pd.notna(lvl) and lvl >= 1:
        return "STRESS_EVENT", lvl, best["causes"]
    return None, lvl, best["causes"]        # 'na' 는 라벨 없음으로 둔다


def coverage_report(sessions, events, io_e4):
    """세션 시간 범위와 사건 매칭 현황. 붙이기 전 감사용."""
    rows = []
    for _, s in sessions.iterrows():
        t0, t1, dur = session_span(s["path"], io_e4)
        if t0 is None:
            rows.append({**s, "dur_h": 0.0, "n_events": 0, "problem": "BVP 없음"})
            continue
        ev = events[events["subject_id"] == s["subject_id"]]
        n = int(((ev["start"] < t1) & (ev["end"] > t0)).sum())
        rows.append({"subject_id": s["subject_id"], "session_id": s["session_id"],
                     "t_start": t0, "t_end": t1, "dur_h": dur / 3600.0,
                     "n_events": n, "problem": ""})
    return pd.DataFrame(rows)
