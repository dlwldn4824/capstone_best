"""웹앱 판정 엔진 — 저장된 하루 기록을 src/nesy 로 판정한다.

연구 코드와 **같은 함수**를 쓴다 (homekit.rolling_z · apply_explanation,
persistence.alerts). 웹앱용으로 따로 만든 판정 로직은 없다.

하루 = 깨어난 날. 아침에 묻는 "어제 이런 일 있었나요?" 는 그 밤을 설명한다.

저장소는 SQLite 한 파일 (data/app/app.db, git 제외).
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nesy import homekit as H, persistence as P  # noqa: E402

DB_PATH = ROOT / "data" / "app" / "app.db"
MODEL_PATH = Path(__file__).resolve().parent / "model" / "risk_v1.json"

Z_THRESH = 2.0
K_DAYS = 3
MIN_NIGHT_MIN = 60          # 밴드 밤 기록은 연구(180분)보다 짧게 허용한다
# 표준 기준선 (연구와 같음) / 기록이 3주 안 되면 짧은 기준선 — 화면에 표시한다
STANDARD = dict(window=28, lag=7, min_n=14)
SHORT = dict(window=7, lag=0, min_n=4)
STANDARD_MIN_DAYS = 21

CAUSES = ("alcohol", "exercise", "sleep_debt", "tense")
CAUSE_KO = {"alcohol": "술", "exercise": "운동", "sleep_debt": "짧은 잠", "tense": "긴장"}
# 원인별 설명 상한 (밤 심박 z). 연구에서는 train 에서 정한다 (fit_cause_ceiling).
# 웹앱은 아직 사용자 데이터가 없어 잠정값을 쓴다 — PMData 효과 크기 순서를 따랐다.
CAPS = {"alcohol": 4.0, "exercise": 3.0, "sleep_debt": 3.0, "tense": 2.5}

SCHEMA = """
CREATE TABLE IF NOT EXISTS nights (
  day TEXT PRIMARY KEY, night_hr REAL, night_min REAL,
  very_active_min REAL, asleep_min REAL, source TEXT);
CREATE TABLE IF NOT EXISTS contexts (
  day TEXT PRIMARY KEY, alcohol INT, sleep INT, exercise INT, tense INT, no_reason INT,
  updated TEXT);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, kind TEXT, title TEXT, body TEXT,
  created TEXT, acked INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS faces (
  day TEXT PRIMARY KEY, face_hr REAL, quality REAL, L REAL, a REAL, b REAL);
"""


def connect(path=DB_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), check_same_thread=False)
    con.executescript(SCHEMA)
    return con


def today(now=None):
    return (now or dt.datetime.now()).date().isoformat()


# --- 위험도 모델 (scripts/22_risk_model.py 가 학습) -------------------------------
# 판정은 규칙이 한다. 모델은 같은 날을 따로 본 '두 번째 의견' 으로만 보여준다.
# 공개 데이터 사건 32건에서 규칙과 탐지율이 같았다 (docs/RISK_MODEL.md).
def _load_model():
    try:
        return json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


MODEL = _load_model()


def risk(d):
    """하루 표에 risk_p (0–1) 와 risk_level 을 붙인다. 모델이 없으면 NaN."""
    d["z3"] = d["night_z"].rolling(3, min_periods=1).mean()
    d["dev3"] = (d["night_z"] >= Z_THRESH).astype(float).rolling(3, min_periods=1).sum()
    if not MODEL:
        d["risk_p"] = np.nan
        d["risk_level"] = ""
        return d
    x = d[MODEL["features"]].to_numpy(dtype=float)
    x[:, 0] = np.clip(x[:, 0], -5, 10)
    lin = x @ np.asarray(MODEL["coef"]) + MODEL["intercept"]
    p = 1 / (1 + np.exp(-lin))
    p[~np.isfinite(d["night_z"].to_numpy(dtype=float))] = np.nan
    lv = MODEL["levels"]
    d["risk_p"] = p
    d["risk_level"] = np.select([p >= lv["alert"], p >= lv["check"], p >= lv["watch"]],
                                ["high", "elevated", "watch"], default="low")
    d.loc[~np.isfinite(p), "risk_level"] = ""
    return d


# --- 쓰기 ---------------------------------------------------------------------
def put_night(con, day, night_hr, night_min, very_active_min=None, asleep_min=None,
              source="manual"):
    con.execute("INSERT OR REPLACE INTO nights VALUES (?,?,?,?,?,?)",
                (day, float(night_hr), float(night_min), very_active_min, asleep_min, source))
    con.commit()


def put_context(con, day, **flags):
    cur = dict(alcohol=0, sleep=0, exercise=0, tense=0, nothing=0)
    row = con.execute("SELECT alcohol,sleep,exercise,tense,no_reason FROM contexts WHERE day=?",
                      (day,)).fetchone()
    if row:
        cur.update(zip(cur.keys(), row))
    for k, v in flags.items():
        if k in cur:
            cur[k] = int(bool(v))
    if any(cur[k] for k in ("alcohol", "sleep", "exercise", "tense")) and "nothing" not in flags:
        cur["nothing"] = 0
    if flags.get("nothing"):
        cur.update(alcohol=0, sleep=0, exercise=0, tense=0, nothing=1)
    con.execute("INSERT OR REPLACE INTO contexts VALUES (?,?,?,?,?,?,?)",
                (day, cur["alcohol"], cur["sleep"], cur["exercise"], cur["tense"],
                 cur["nothing"], dt.datetime.now().isoformat(timespec="seconds")))
    con.commit()
    return cur


def put_face(con, day, face_hr, quality, L, a, b):
    con.execute("INSERT OR REPLACE INTO faces VALUES (?,?,?,?,?,?)",
                (day, face_hr, quality, L, a, b))
    con.commit()


def reset(con):
    con.executescript("DELETE FROM nights; DELETE FROM contexts; DELETE FROM faces; "
                      "DELETE FROM notifications;")
    con.commit()


# --- 알림 ---------------------------------------------------------------------
# 폰·워치에 동시에 띄우는 팝업. 같은 날 같은 종류는 한 번만 만든다.
NOTICE = {
    "ALERT": ("{k}일째 설명되지 않았어요",
              "이유 없이 평소와 다른 상태가 {k}일 이어졌어요. 진단은 아니에요. 몸 상태를 살펴봐 주세요."),
    "ASK": ("어젯밤이 평소와 달랐어요",
            "어제 술·늦잠·운동·긴장 같은 일이 있었나요? 알려주시면 함께 따져볼게요."),
}


def _notice_row(r):
    return {"id": r[0], "day": r[1], "kind": r[2], "title": r[3], "body": r[4],
            "created": r[5], "acked": bool(r[6])}


def maybe_notify(con, state):
    """상태를 보고 새 알림이 필요하면 만든다. 새로 만든 알림 dict 또는 None."""
    kind = state.get("status")
    if kind not in NOTICE:
        return None
    day = state["today"]
    if con.execute("SELECT 1 FROM notifications WHERE day=? AND kind=?", (day, kind)).fetchone():
        return None
    k = (state.get("streak") or {}).get("k", K_DAYS)
    title, body = (t.format(k=k) for t in NOTICE[kind])
    return add_notice(con, day, kind, title, body)


def add_notice(con, day, kind, title, body):
    now = dt.datetime.now().isoformat(timespec="seconds")
    cur = con.execute("INSERT INTO notifications (day,kind,title,body,created) VALUES (?,?,?,?,?)",
                      (day, kind, title, body, now))
    con.commit()
    return _notice_row(con.execute("SELECT * FROM notifications WHERE id=?",
                                   (cur.lastrowid,)).fetchone())


def pending_notices(con, day):
    rows = con.execute("SELECT * FROM notifications WHERE day=? AND acked=0 ORDER BY id",
                       (day,)).fetchall()
    return [_notice_row(r) for r in rows]


def ack_notice(con, nid):
    con.execute("UPDATE notifications SET acked=1 WHERE id=?", (nid,))
    con.commit()


# --- 판정 ---------------------------------------------------------------------
def _frame(con, until):
    nights = pd.read_sql("SELECT * FROM nights", con)
    ctx = pd.read_sql("SELECT * FROM contexts", con)
    faces = pd.read_sql("SELECT * FROM faces", con)
    if nights.empty:
        return None, ctx, faces
    first = pd.Timestamp(min(nights["day"]))
    days = pd.date_range(first, pd.Timestamp(until), freq="D")
    d = pd.DataFrame({"day": days})
    d["subject_id"] = "me"
    for t in (nights, ctx, faces):
        if not t.empty:
            t["day"] = pd.to_datetime(t["day"])
    d = d.merge(nights, on="day", how="left").merge(ctx, on="day", how="left")
    d["night_min"] = d["night_min"].fillna(0)
    d["valid"] = d["night_min"] >= MIN_NIGHT_MIN
    return d, ctx, faces


def _ref_median(d, params):
    """그날의 기준선 중앙값 (화면에 '평소 58 bpm' 으로 보여줄 값)."""
    x = d["night_hr"].to_numpy(dtype=float)
    ok = d["valid"].to_numpy(dtype=bool) & np.isfinite(x)
    refs = H._past_ref(d["day"], x, ok, params["window"], params["lag"], params["min_n"])
    med = [float(np.median(r)) if r is not None else np.nan for r in refs]
    mad = [float(1.4826 * np.median(np.abs(r - np.median(r)))) if r is not None else np.nan
           for r in refs]
    n_ref = [int(len(r)) if r is not None else 0 for r in refs]
    return med, mad, n_ref


def compute(con, now=None):
    """오늘 판정 + 기록. 화면 두 개(폰·워치)가 같은 값을 받는다."""
    day = today(now)
    d, ctx, faces = _frame(con, day)
    if d is None:
        return {"today": day, "status": "NO_DATA", "history": [], "baseline": _bl(0, "short")}

    n_valid = int(d["valid"].sum())
    mode = "standard" if n_valid >= STANDARD_MIN_DAYS else "short"
    params = STANDARD if mode == "standard" else SHORT
    d["night_z"] = H.rolling_z(d, "night_hr", **params)
    d["ref_med"], d["ref_mad"], d["ref_n"] = _ref_median(d, params)

    f = lambda c: d[c].fillna(0).astype(int).astype(bool) if c in d else False  # noqa: E731
    va = d["very_active_min"].astype(float) if "very_active_min" in d else np.nan
    sl = d["asleep_min"].astype(float) if "asleep_min" in d else np.nan
    d["alcohol"] = f("alcohol")
    d["tense"] = f("tense")
    d["exercise"] = f("exercise") | (pd.Series(va).fillna(0) >= 30).to_numpy()
    d["sleep_debt"] = f("sleep") | ((pd.Series(sl) < 360) & pd.Series(sl).notna()).to_numpy()
    d["valid"] = d["valid"] & np.isfinite(d["night_z"])
    d = H.apply_explanation(d, z_thresh=Z_THRESH, ceiling=CAPS, causes=CAUSES)
    d = risk(d)

    # 이탈했는데 아직 맥락을 안 물어본 날: 설명 여부를 모른다 → 판정 보류(질문)
    d["answered"] = d["updated"].notna() if "updated" in d else False
    d["pending"] = d["deviated"] & ~d["held"] & ~d["answered"].to_numpy(dtype=bool)
    # 질문 전 날은 연속 계산에서 보류 (끊지도 잇지도 않음)
    d["hold"] = d["held"] | d["pending"]
    a = P.alerts(d, 0.5, k=K_DAYS, hold_col="hold")

    rows = [_row(r) for r in a.itertuples()]
    t = rows[-1]
    t_face = _face_today(faces, day)
    status = _status(t, n_valid, params)
    return {
        "today": day, "status": status, "night": t, "face": t_face,
        "baseline": _bl(n_valid, mode, params),
        "streak": _streak(a), "history": rows[-28:],
        "caps": CAPS, "k_days": K_DAYS,
        "model": ({"version": MODEL["version"], "data": MODEL["data"], "metrics": MODEL["metrics"]}
                  if MODEL else None),
    }


def _bl(n_valid, mode, params=SHORT):
    need = STANDARD_MIN_DAYS if mode == "standard" else params["min_n"] + params["lag"]
    return {"mode": mode, "valid_days": n_valid, "standard_after": STANDARD_MIN_DAYS,
            "needed": need}


def _num(x, nd=1):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(x) else round(x, nd)


def _row(r):
    by = r.explained_by or ""
    causes = [c for c in CAUSES if bool(getattr(r, c))]
    if not r.valid:
        # 밤 기록은 있는데 기준선이 아직 없으면 '배우는 중'
        has_night = r.night_hr == r.night_hr and r.night_min >= MIN_NIGHT_MIN
        state = "learning" if has_night else "none"
    elif not r.deviated:
        state = "calm"
    elif r.pending:
        state = "ask"
    elif r.held:
        state = "explained"
    elif r.alert:
        state = "alert"
    else:
        state = "left"
    return {
        "day": r.day.date().isoformat(), "state": state,
        "night_hr": _num(r.night_hr), "night_min": _num(r.night_min, 0),
        "ref": _num(r.ref_med), "spread": _num(r.ref_mad), "z": _num(r.night_z, 2),
        "delta": _num(r.night_hr - r.ref_med) if np.isfinite(r.ref_med) else None,
        "explained_by": by, "explained_ko": CAUSE_KO.get(by, ""),
        "causes": causes, "run": int(r.run_len), "alert": bool(r.alert),
        "answered": bool(r.answered),
        "nothing": bool(getattr(r, "no_reason", 0) == 1),
        "risk_p": _num(r.risk_p, 3), "risk_level": r.risk_level,
    }


def _status(t, n_valid, params):
    if t["night_hr"] is None:
        return "NO_NIGHT"
    if t["z"] is None:
        return "BASELINE"
    return {"calm": "CALM", "ask": "ASK", "explained": "EXPLAINED",
            "left": "WATCH", "alert": "ALERT", "none": "NO_NIGHT", "learning": "BASELINE"}[t["state"]]


def _streak(a):
    """설명 안 된 연속이 몇 칸 찼나 — 마지막으로 판정된 날 기준.

    오늘 밤 기록이 아직 없거나, 오늘이 설명·질문 대기(보류)면 그 전날의 연속을 보여준다.
    """
    judged = a[a["valid"] & ~a["hold"]]
    run = int(judged["run_len"].iloc[-1]) if len(judged) else 0
    return {"run": run, "k": K_DAYS}


def _face_today(faces, day):
    if faces is None or faces.empty:
        return None
    faces = faces.sort_values("day")
    cur = faces[faces["day"] == pd.Timestamp(day)]
    if cur.empty:
        return None
    r = cur.iloc[-1]
    prev = faces[faces["day"] < pd.Timestamp(day)].tail(14)
    out = {"face_hr": _num(r.face_hr), "quality": _num(r.quality, 2),
           "L": _num(r.L), "a": _num(r.a), "b": _num(r.b), "a_z": None, "n_ref": len(prev)}
    if len(prev) >= 5:
        med = prev["a"].median()
        mad = 1.4826 * (prev["a"] - med).abs().median()
        if mad > 0:
            out["a_z"] = _num((r.a - med) / mad, 2)
    return out


# --- 데모 -----------------------------------------------------------------------
def seed_demo(con, days=35, seed=10, now=None):
    """시연용 지난 기록. 마지막 이틀은 이유 없이 높아 오늘 밤이 사흘째가 될 수 있다."""
    reset(con)
    rng = np.random.default_rng(seed)
    end = pd.Timestamp(today(now))
    for i in range(days, 0, -1):
        d = (end - pd.Timedelta(days=i)).date().isoformat()
        hr = 58 + rng.normal(0, 0.8)
        ctx = {}
        if i in (30, 23, 16, 9, 5):
            hr += 2.4
            ctx = {"alcohol": 1}
        elif i in (27, 12):
            hr += 1.9
            ctx = {"exercise": 1}
        elif i in (2, 1):
            hr += 4.0
            ctx = {"nothing": 1}
        else:
            ctx = {}
        put_night(con, d, round(hr, 1), int(rng.normal(410, 25)), source="demo")
        if ctx:
            put_context(con, d, **ctx)


DEMO_NIGHTS = {
    "calm": dict(delta=0.3, label="평소 같은 밤"),
    "drink": dict(delta=3.5, label="술 마신 밤 (+3.5)"),
    "unexplained": dict(delta=6.0, label="이유 없이 높은 밤 (+6)"),
}


def demo_night(con, kind, now=None):
    st = compute(con, now)
    ref = (st.get("night") or {}).get("ref") or 58.0
    delta = DEMO_NIGHTS[kind]["delta"]
    put_night(con, today(now), round(ref + delta, 1), 405, source="demo")


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, default=str)
