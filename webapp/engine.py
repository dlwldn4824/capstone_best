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
# 개인화는 기록과 함께 올라간다. 긴 개인 기준선이 없을 때 "평소와 다르다"고 말하지 않는다.
# early      유효한 밤이 거의 없음 — 오늘 안정 상태(실시간 심박)와 비교
# adapting   이틀 이상·21일 미만 — 최근 같은 밤(짧은 기준선)
# personal   21일 이상 — 연구와 같은 rolling z, 설명 상한, 3일 알림
STANDARD = dict(window=28, lag=7, min_n=14)
SHORT = dict(window=7, lag=0, min_n=4)
ADAPT = dict(window=7, lag=0, min_n=1)
STANDARD_MIN_DAYS = 21
ADAPT_MIN_DAYS = 2
ADAPT_MAD_FLOOR = 1.0          # 비교 밤이 거의 같을 때, 1 bpm 을 흩어짐으로 본다
EARLY_RISE = 8.0               # 오늘 안정 상태보다 이만큼 높고
EARLY_HOLD = 6.0               # 최근 샘플이 이 선 위에 유지되면 변화
EARLY_STABLE_N = 6
EARLY_RECENT_N = 4
MAX_LIVE = 240
SOFT_NOTES = {"카페인", "감기 기운", "약 복용"}   # 메모일 뿐, 밤을 끝까지 설명하지는 않는다

# 얼굴 심박 — 밤 심박의 교차 확인 신호 (docs/FACE_RPPG.md)
# 공개 데이터 100명: 품질을 통과한 측정은 87% 가 ±5 bpm 안, 그래도 밤 심박보다 덜 정확하다.
# 그래서 얼굴 혼자서는 더 큰 이탈을 요구하고, 밤 심박이 애매할 때 같은 쪽을 가리키면 보탠다.
FACE_MIN_SNR = 0.0            # 앱의 멈춤 기준과 같다 — 이보다 낮은 측정은 기준선에도 판정에도 안 쓴다
FACE_Z_ALONE = 2.5            # 밤 기록이 없을 때 얼굴만으로 이탈이라 보는 기준
FACE_Z_CONFIRM = 2.0          # 밤 심박이 애매할 때 얼굴이 보태는 기준
NIGHT_Z_BORDER = 1.5          # '애매한' 밤 심박의 아래쪽
FACE_STANDARD = dict(window=28, lag=7, min_n=7)
FACE_SHORT = dict(window=7, lag=0, min_n=4)
FACE_STANDARD_MIN = 14

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
CREATE TABLE IF NOT EXISTS samples (
  id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, bpm REAL, at REAL);
"""


def _migrate(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(contexts)")}
    if "note" not in cols:
        con.execute("ALTER TABLE contexts ADD COLUMN note TEXT DEFAULT ''")
    con.commit()


def connect(path=DB_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), check_same_thread=False)
    con.executescript(SCHEMA)
    _migrate(con)
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
    # 모델은 밤 심박으로만 학습했다 — 얼굴만으로 판정한 날에는 쓰지 않는다
    if "source" in d:
        p[(d["source"] != "night").to_numpy()] = np.nan
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
    note_set = "note" in flags
    note_in = flags.pop("note", None)
    cur = dict(alcohol=0, sleep=0, exercise=0, tense=0, nothing=0)
    note = ""
    row = con.execute(
        "SELECT alcohol,sleep,exercise,tense,no_reason,note FROM contexts WHERE day=?",
        (day,)).fetchone()
    if row:
        cur.update(zip(cur.keys(), row[:5]))
        note = _note_text(row[5])
    for k, v in flags.items():
        if k in cur:
            cur[k] = int(bool(v))
    # 버튼을 하나만 고르면 그 원인만 남긴다. 한 호출에 여러 원인을 주면 그대로 둔다.
    turned = [k for k in ("alcohol", "sleep", "exercise", "tense") if k in flags and cur[k]]
    if len(turned) == 1 and not flags.get("nothing"):
        for k in ("alcohol", "sleep", "exercise", "tense"):
            if k != turned[0]:
                cur[k] = 0
    if any(cur[k] for k in ("alcohol", "sleep", "exercise", "tense")) and "nothing" not in flags:
        cur["nothing"] = 0
    if flags.get("nothing"):
        cur.update(alcohol=0, sleep=0, exercise=0, tense=0, nothing=1)
    if note_set:
        note = "" if note_in is None else str(note_in).strip()
    con.execute(
        "INSERT OR REPLACE INTO contexts "
        "(day,alcohol,sleep,exercise,tense,no_reason,updated,note) VALUES (?,?,?,?,?,?,?,?)",
        (day, cur["alcohol"], cur["sleep"], cur["exercise"], cur["tense"],
         cur["nothing"], dt.datetime.now().isoformat(timespec="seconds"), note))
    con.commit()
    return cur


def put_face(con, day, face_hr, quality, L, a, b):
    con.execute("INSERT OR REPLACE INTO faces VALUES (?,?,?,?,?,?)",
                (day, face_hr, quality, L, a, b))
    con.commit()


def reset(con):
    con.executescript("DELETE FROM nights; DELETE FROM contexts; DELETE FROM faces; "
                      "DELETE FROM notifications; DELETE FROM samples;")
    con.commit()


def add_sample(con, day, bpm, at=None):
    """오늘 심박의 짧은 시계열. 이른 날의 비교 대상은 이 안정 구간이다."""
    try:
        bpm = float(bpm)
    except (TypeError, ValueError):
        return
    if not (30 < bpm < 220):
        return
    if at is None:
        at = dt.datetime.now().timestamp()
    con.execute("INSERT INTO samples (day,bpm,at) VALUES (?,?,?)", (day, bpm, float(at)))
    con.execute(
        "DELETE FROM samples WHERE day=? AND id NOT IN "
        "(SELECT id FROM samples WHERE day=? ORDER BY id DESC LIMIT ?)",
        (day, day, MAX_LIVE))
    con.commit()


# --- 알림 ---------------------------------------------------------------------
# 폰·워치에 동시에 띄우는 팝업. 같은 날 같은 종류는 한 번만 만든다.
NOTICE = {
    "ALERT": ("{k}일째 이유가 남지 않아요",
              "최근 {k}일간 평소와 다른 변화가 생활 기록으로 설명되지 않습니다."),
    "ASK": ("심박이 평소보다 높아요",
            "이미 잡힌 기록 중에서, 겹칠 수 있는 것만 확인할게요."),
}


def _notice_row(r):
    return {"id": r[0], "day": r[1], "kind": r[2], "title": r[3], "body": r[4],
            "created": r[5], "acked": bool(r[6])}


def _notice_text(state):
    kind = state.get("status")
    mode = (state.get("baseline") or {}).get("mode")
    if kind == "ASK" and mode == "early":
        return "심박 변화가 감지됐어요", "최근 안정 상태보다 심박이 높게 유지되고 있어요."
    if kind == "ASK" and mode == "adapting":
        return "최근 같은 기록보다 심박이 높아요", "겹칠 수 있는 이유만 확인할게요."
    if kind not in NOTICE:
        return None
    k = (state.get("streak") or {}).get("k", K_DAYS)
    title, body = NOTICE[kind]
    return title.format(k=k), body.format(k=k)


def maybe_notify(con, state):
    """상태를 보고 새 알림이 필요하면 만든다. 새로 만든 알림 dict 또는 None."""
    kind = state.get("status")
    text = _notice_text(state)
    if text is None:
        return None
    day = state["today"]
    if con.execute("SELECT 1 FROM notifications WHERE day=? AND kind=?", (day, kind)).fetchone():
        return None
    title, body = text
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
    if nights.empty and faces.empty:
        return None, ctx, faces
    first = pd.Timestamp(min(list(nights["day"]) + list(faces["day"])))
    days = pd.date_range(first, pd.Timestamp(until), freq="D")
    d = pd.DataFrame({"day": days})
    d["subject_id"] = "me"
    for t in (nights, ctx, faces):
        if not t.empty:
            t["day"] = pd.to_datetime(t["day"])
    d = d.merge(nights, on="day", how="left").merge(ctx, on="day", how="left")
    if not faces.empty:
        d = d.merge(faces[["day", "face_hr", "quality"]], on="day", how="left")
    else:
        d["face_hr"], d["quality"] = np.nan, np.nan
    d["night_min"] = d["night_min"].fillna(0)
    d["valid"] = (d["night_min"] >= MIN_NIGHT_MIN) & d["night_hr"].notna()
    d["face_valid"] = d["face_hr"].notna() & (d["quality"].astype(float) >= FACE_MIN_SNR)
    return d, ctx, faces


def _ref_median(d, params, col="night_hr", valid_col="valid"):
    """그날의 기준선 중앙값 (화면에 '평소 58 bpm' 으로 보여줄 값)."""
    x = d[col].to_numpy(dtype=float)
    ok = d[valid_col].to_numpy(dtype=bool) & np.isfinite(x)
    refs = H._past_ref(d["day"], x, ok, params["window"], params["lag"], params["min_n"])
    med = [float(np.median(r)) if r is not None else np.nan for r in refs]
    mad = [float(1.4826 * np.median(np.abs(r - np.median(r)))) if r is not None else np.nan
           for r in refs]
    n_ref = [int(len(r)) if r is not None else 0 for r in refs]
    return med, mad, n_ref


def fuse(d):
    """밤 심박 z 와 얼굴 심박 z 를 하나의 판정용 z 로 합친다.

    night_z_raw / face_z 는 그대로 두고, 판정은 night_z(=합친 값) 와 valid 로 한다.
      밤 z ≥ 2                       → 밤 z 그대로 (얼굴은 일치 여부만 표시)
      1.5 ≤ 밤 z < 2  그리고 얼굴 z ≥ 2 → 2 로 올린다 (약한 두 신호가 같은 쪽)
      밤 기록 없음, 얼굴 z 있음          → 얼굴 z × 2/2.5 (얼굴만으로는 2.5 를 넘어야 이탈)
      밤 z < 2, 얼굴만 높음             → 이탈 아님 (얼굴 단독으로 뒤집지 않는다)
    """
    nz = d["night_z"].to_numpy(dtype=float)
    fz = d["face_z"].to_numpy(dtype=float)
    nv = d["valid"].to_numpy(dtype=bool) & np.isfinite(nz)
    fv = d["face_valid"].to_numpy(dtype=bool) & np.isfinite(fz)

    eff = np.where(nv, nz, np.nan)
    border = nv & (nz >= NIGHT_Z_BORDER) & (nz < Z_THRESH) & fv & (fz >= FACE_Z_CONFIRM)
    eff[border] = Z_THRESH
    alone = ~nv & fv
    eff[alone] = fz[alone] * Z_THRESH / FACE_Z_ALONE

    agree = np.full(len(d), "", dtype=object)
    both = nv & fv
    agree[both & (nz >= Z_THRESH) & (fz >= FACE_Z_CONFIRM)] = "both"
    agree[both & (nz >= Z_THRESH) & (fz < FACE_Z_CONFIRM)] = "night_only"
    agree[both & (nz < NIGHT_Z_BORDER) & (fz >= FACE_Z_CONFIRM)] = "face_only"
    agree[border] = "border"
    agree[both & (nz < Z_THRESH) & (fz < FACE_Z_CONFIRM) & ~border] = "calm"
    agree[alone] = "face_alone"

    d["night_z_raw"] = nz
    d["night_z"] = eff
    d["valid"] = nv | alone
    d["source"] = np.where(nv, "night", np.where(alone, "face", ""))
    d["agree"] = agree
    return d


def _mode_name(n_valid):
    if n_valid >= STANDARD_MIN_DAYS:
        return "personal"
    if n_valid >= ADAPT_MIN_DAYS:
        return "adapting"
    return "early"


def _compare_z(d, params, mad_floor=0.0):
    """밤 심박 z. mad_floor 가 있으면, 흩어짐이 0 인 짧은 구간도 bpm 차이로 본다."""
    z = np.asarray(H.rolling_z(d, "night_hr", **params), dtype=float)
    if mad_floor <= 0:
        return z
    med, mad, nref = _ref_median(d, params)
    hr = d["night_hr"].to_numpy(dtype=float)
    ok = d["valid"].to_numpy(dtype=bool)
    for i in range(len(d)):
        if not ok[i] or np.isfinite(z[i]):
            continue
        if nref[i] < 1 or not np.isfinite(med[i]) or not np.isfinite(hr[i]):
            continue
        scale = mad[i] if np.isfinite(mad[i]) and mad[i] > 0 else mad_floor
        z[i] = (hr[i] - med[i]) / scale
    return z


def compute(con, now=None):
    """오늘 판정 + 기록. 화면 두 개(폰·워치)가 같은 값을 받는다."""
    day = today(now)
    samples = _samples(con, day)
    d, ctx, faces = _frame(con, day)
    if d is None:
        return _empty_state(con, day, samples)

    n_valid = int(d["valid"].sum())
    mode = _mode_name(n_valid)
    if mode == "personal":
        params = STANDARD
        d["night_z"] = _compare_z(d, params, 0)
        d["ref_med"], d["ref_mad"], d["ref_n"] = _ref_median(d, params)
    elif mode == "adapting":
        params = ADAPT
        d["night_z"] = _compare_z(d, params, ADAPT_MAD_FLOOR)
        d["ref_med"], d["ref_mad"], d["ref_n"] = _ref_median(d, params)
    else:
        # 이른 날의 z 는 긴 개인 기준선이 아니다. 숫자는 오늘 안정 상태에서만 만든다.
        params = SHORT
        d["night_z"] = np.full(len(d), np.nan)
        d["ref_med"] = np.nan
        d["ref_mad"] = np.nan
        d["ref_n"] = 0

    # 얼굴 심박: 밤 심박과 같은 방식의 개인 기준선 (품질 통과한 측정만)
    n_face = int(d["face_valid"].sum())
    fparams = FACE_STANDARD if n_face >= FACE_STANDARD_MIN else FACE_SHORT
    d["face_z"] = H.rolling_z(d, "face_hr", valid_col="face_valid", **fparams)
    d["face_ref"], d["face_mad"], _ = _ref_median(d, fparams, "face_hr", "face_valid")
    d = fuse(d)

    f = lambda c: d[c].fillna(0).astype(int).astype(bool) if c in d else False  # noqa: E731
    va = d["very_active_min"].astype(float) if "very_active_min" in d else np.nan
    sl = d["asleep_min"].astype(float) if "asleep_min" in d else np.nan
    d["alcohol"] = f("alcohol")
    d["tense"] = f("tense")
    d["exercise"] = f("exercise") | (pd.Series(va).fillna(0) >= 30).to_numpy()
    d["sleep_debt"] = f("sleep") | ((pd.Series(sl) < 360) & pd.Series(sl).notna()).to_numpy()
    d = H.apply_explanation(d, z_thresh=Z_THRESH, ceiling=CAPS, causes=CAUSES)
    d = risk(d)

    # 이탈했는데 아직 맥락을 안 물어본 날: 설명 여부를 모른다 → 판정 보류(질문)
    d["answered"] = d["updated"].notna() if "updated" in d else False
    d["pending"] = d["deviated"] & ~d["held"] & ~d["answered"].to_numpy(dtype=bool)
    # 질문 전 날은 연속 계산에서 보류 (끊지도 잇지도 않음)
    d["hold"] = d["held"] | d["pending"]
    a = P.alerts(d, 0.5, k=K_DAYS, hold_col="hold")

    # 3일 알림은 개인 패턴이 생긴 뒤에만. 그 전에는 이유를 묻거나 약하게 남긴다.
    if mode != "personal":
        a["alert"] = False

    rows = [_row(r) for r in a.itertuples()]
    t = rows[-1]
    t_face = _face_today(faces, day)
    status = _status(t, n_valid, params)
    flags = _today_flags(con, day)
    change = None
    if mode == "early":
        decided, by, change = _early_decision(
            samples, t.get("night_hr"), flags, _active_min(con, day))
        if decided:
            status = decided
            t = _paint(t, status, by, change)
        elif status == "BASELINE":
            status = "RECORDING"
            t = _paint(t, status, "", None)
    elif status == "BASELINE":
        status = "RECORDING"
        t = _paint(t, status, "", None)
    rows[-1] = t
    return {
        "today": day, "status": status, "night": t, "face": t_face,
        "baseline": _bl(n_valid, mode, signal=bool(samples) or t.get("night_hr") is not None),
        "streak": _streak(a), "history": rows[-28:],
        "caps": CAPS, "k_days": K_DAYS,
        "change": change, "note": flags["note"], "choice": _choice(flags),
        "model": _model_meta(),
    }


LABELS = {
    "early": "최근 데이터 기준 분석",
    "adapting": "최근 같은 기록 기준 분석",
    "personal": "개인 패턴 기준 분석",
}


def _choice(flags):
    """오늘 고른 버튼. 자동으로 붙은 짧은 잠·운동과는 따로, 화면 얼굴이 이 값을 따른다."""
    note = flags.get("note") or ""
    if note in SOFT_NOTES:
        return note
    if flags.get("alcohol"):
        return "alcohol"
    if flags.get("exercise"):
        return "exercise"
    if flags.get("sleep"):
        return "sleep_debt"
    if flags.get("tense"):
        return "tense"
    return ""


def _bl(n_valid, mode, signal=False):
    pct = int(min(100, round(100 * n_valid / float(STANDARD_MIN_DAYS))))
    if mode == "early" and signal and pct < 8:
        pct = 8
    return {"mode": mode, "valid_days": int(n_valid), "personalization": pct,
            "label": LABELS[mode], "standard_after": STANDARD_MIN_DAYS}


def _model_meta():
    if not MODEL:
        return None
    return {"version": MODEL["version"], "data": MODEL["data"], "metrics": MODEL["metrics"]}


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
        state = "learning" if (has_night or bool(r.face_valid)) else "none"
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
        "night_z": _num(r.night_z_raw, 2),
        "delta": _num(r.night_hr - r.ref_med) if np.isfinite(r.ref_med) else None,
        "face_hr": _num(r.face_hr) if bool(r.face_valid) else None,
        "face_z": _num(r.face_z, 2), "face_ref": _num(r.face_ref), "face_spread": _num(r.face_mad),
        "face_delta": (_num(r.face_hr - r.face_ref) if bool(r.face_valid) and np.isfinite(r.face_ref) else None),
        "source": r.source, "agree": r.agree,
        "explained_by": by, "explained_ko": CAUSE_KO.get(by, ""),
        "causes": causes, "run": int(r.run_len), "alert": bool(r.alert),
        "answered": bool(r.answered),
        "nothing": bool(getattr(r, "no_reason", 0) == 1),
        "note": _note_text(getattr(r, "note", "")),
        "risk_p": _num(r.risk_p, 3), "risk_level": r.risk_level,
    }


def _status(t, n_valid, params):
    if t["night_hr"] is None and t["source"] != "face":
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


def _note_text(v):
    if v is None:
        return ""
    try:
        if v != v:  # NaN
            return ""
    except Exception:
        return ""
    text = str(v).strip()
    return "" if text.lower() == "nan" else text


def _samples(con, day):
    rows = con.execute("SELECT bpm FROM samples WHERE day=? ORDER BY id", (day,)).fetchall()
    return [float(r[0]) for r in rows]


def _today_flags(con, day):
    row = con.execute(
        "SELECT alcohol,sleep,exercise,tense,no_reason,note FROM contexts WHERE day=?",
        (day,)).fetchone()
    if not row:
        return dict(alcohol=0, sleep=0, exercise=0, tense=0, nothing=0, note="")
    return dict(alcohol=int(row[0] or 0), sleep=int(row[1] or 0), exercise=int(row[2] or 0),
                tense=int(row[3] or 0), nothing=int(row[4] or 0), note=_note_text(row[5]))


def _active_min(con, day):
    row = con.execute("SELECT very_active_min FROM nights WHERE day=?", (day,)).fetchone()
    if not row or row[0] is None:
        return 0.0
    try:
        return float(row[0])
    except (TypeError, ValueError):
        return 0.0


def _stable_of(values):
    arr = np.asarray(list(values), dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) < EARLY_STABLE_N:
        return None
    low = np.sort(arr)[:max(EARLY_STABLE_N, len(arr) // 2)]
    return float(np.median(low))


def _pack_change(kind, stable, recent):
    return {"kind": kind, "stable": round(float(stable), 1), "recent": round(float(recent), 1),
            "delta": round(float(recent) - float(stable), 1)}


def _intraday(samples):
    """오늘 앞부분의 안정 심박보다 최근 심박이 높게 유지되면 변화."""
    if len(samples) < EARLY_STABLE_N + EARLY_RECENT_N:
        return None
    recent = np.asarray(samples[-EARLY_RECENT_N:], dtype=float)
    stable = _stable_of(samples[:-EARLY_RECENT_N])
    if stable is None:
        return None
    recent_med = float(np.median(recent))
    if recent_med < stable + EARLY_RISE:
        return None
    if float(np.mean(recent >= stable + EARLY_HOLD)) < 0.75:
        return None
    return _pack_change("intraday", stable, recent_med)


def _night_vs_stable(night_hr, samples):
    try:
        night_hr = float(night_hr)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(night_hr):
        return None
    stable = _stable_of(samples)
    if stable is None or night_hr < stable + EARLY_RISE:
        return None
    return _pack_change("night", stable, night_hr)


def _over_cap(cause, change):
    """설명 상한은 밤 심박 z 단위다. 이른 날의 밤 기록에만, 1 bpm 을 흩어짐으로 가늠한다."""
    cap = CAPS.get(cause)
    if change is None or change.get("kind") != "night" or cap is None:
        return False
    return (change["delta"] / ADAPT_MAD_FLOOR) > cap


def _classify_early(flags, active_min, change):
    picked = None
    if flags["alcohol"]:
        picked = "alcohol"
    elif flags["exercise"] or active_min >= 30:
        picked = "exercise"
    elif flags["sleep"]:
        picked = "sleep_debt"
    elif flags["tense"]:
        picked = "tense"
    if picked:
        if _over_cap(picked, change):
            return "WATCH", ""
        return "EXPLAINED", picked
    if flags["note"] in SOFT_NOTES or flags["nothing"]:
        return "WATCH", ""
    return "ASK", ""


def _early_decision(samples, night_hr, flags, active_min):
    change = _intraday(samples)
    if change is None and night_hr is not None:
        change = _night_vs_stable(night_hr, samples)
    if change is None:
        return None, "", None
    status, by = _classify_early(flags, active_min, change)
    return status, by, change


_EARLY_STATE = {
    "ASK": "ask", "EXPLAINED": "explained", "WATCH": "left", "RECORDING": "recording",
    "CALM": "calm", "ALERT": "alert", "NO_NIGHT": "none", "NO_DATA": "none",
}


def _paint(t, status, explained_by, change):
    state = _EARLY_STATE.get(status)
    if state:
        t["state"] = state
    if explained_by:
        t["explained_by"] = explained_by
        t["explained_ko"] = CAUSE_KO.get(explained_by, "")
        causes = list(t.get("causes") or [])
        if explained_by not in causes:
            causes.append(explained_by)
        t["causes"] = causes
    if status != "ALERT":
        t["alert"] = False
    if change:
        if t.get("ref") is None:
            t["ref"] = change["stable"]
        if t.get("delta") is None:
            t["delta"] = change["delta"]
    return t


def _shell_night(day, status, explained_by, change):
    t = {
        "day": day, "state": "none",
        "night_hr": None, "night_min": None,
        "ref": None, "spread": None, "z": None, "night_z": None, "delta": None,
        "face_hr": None, "face_z": None, "face_ref": None, "face_spread": None, "face_delta": None,
        "source": "", "agree": "",
        "explained_by": "", "explained_ko": "", "causes": [],
        "run": 0, "alert": False, "answered": False, "nothing": False, "note": "",
        "risk_p": None, "risk_level": "",
    }
    return _paint(t, status, explained_by, change)


def _empty_state(con, day, samples):
    flags = _today_flags(con, day)
    decided, by, change = _early_decision(samples, None, flags, _active_min(con, day))
    if decided:
        status, explained_by = decided, by
    elif samples:
        status, explained_by, change = "RECORDING", "", None
    else:
        status, explained_by, change = "NO_DATA", "", None
    night = None if status == "NO_DATA" else _shell_night(day, status, explained_by, change)
    if night is not None:
        night["note"] = flags["note"]
    return {
        "today": day, "status": status, "night": night, "face": None,
        "baseline": _bl(0, "early", signal=bool(samples)),
        "streak": {"run": 0, "k": K_DAYS}, "history": [night] if night else [],
        "caps": CAPS, "k_days": K_DAYS,
        "change": change, "note": flags["note"], "choice": _choice(flags),
        "model": _model_meta(),
    }


# --- 데모 -----------------------------------------------------------------------
def seed_demo(con, days=35, seed=10, now=None):
    """시연용 지난 기록. 마지막 이틀은 이유 없이 높아 오늘 밤이 사흘째가 될 수 있다."""
    reset(con)
    rng = np.random.default_rng(seed)
    frng = np.random.default_rng(seed + 100)       # 얼굴은 따로 — 밤 기록의 난수 순서를 바꾸지 않는다
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
        # 아침 얼굴 심박: 깨어 있어 밤보다 높고, 측정 잡음이 크다 (공개 데이터 품질 통과 측정 수준)
        if frng.random() < 0.85:
            put_face(con, d, round(hr + 7 + frng.normal(0, 1.2), 1), 2.0, 62.0, 14.0, 16.0)
        if ctx:
            put_context(con, d, **ctx)


DEMO_NIGHTS = {
    "calm": dict(delta=0.3, face=0.5, label="평소 같은 밤"),
    "drink": dict(delta=3.5, face=3.0, label="술 마신 밤 (+3.5)"),
    "unexplained": dict(delta=6.0, face=5.0, label="이유 없이 높은 밤 (+6)"),
    "border": dict(delta=1.6, face=4.0, label="애매한 밤 + 얼굴도 높음"),
    "face_only": dict(delta=None, face=5.5, label="밴드 없이 얼굴만 (+5.5)"),
}


def demo_night(con, kind, now=None):
    """오늘 밤 기록과 아침 얼굴 체크를 시연용으로 넣는다. 오늘 것은 먼저 지운다."""
    day = today(now)
    con.execute("DELETE FROM nights WHERE day=?", (day,))
    con.execute("DELETE FROM faces WHERE day=?", (day,))
    con.execute("DELETE FROM contexts WHERE day=?", (day,))
    con.execute("DELETE FROM notifications WHERE day=?", (day,))
    con.commit()
    st = compute(con, now)
    hist = st.get("history") or []
    ref = next((h["ref"] for h in reversed(hist) if h.get("ref") is not None), None) or 58.0
    fref = next((h["face_ref"] for h in reversed(hist) if h.get("face_ref") is not None), None) or ref + 7
    k = DEMO_NIGHTS[kind]
    if k["delta"] is not None:
        put_night(con, day, round(ref + k["delta"], 1), 405, source="demo")
    put_face(con, day, round(fref + k["face"] * 1.2, 1), 2.0, 62.0, 14.0, 16.0)


_DATE_COLS = {"date", "day", "날짜", "일자"}
_HR_COLS = {"nighthr", "hr", "bpm", "heartrate", "심박", "밤심박", "수면심박", "평균심박"}
_SLEEP_COLS = {"asleepmin", "sleepmin", "sleep", "수면", "수면분", "수면시간"}
_ACTIVE_COLS = {"veryactivemin", "exercisemin", "운동", "운동분", "활동분"}


def _col_key(cell):
    return cell.strip().strip('"').strip("'").lower().replace(" ", "").replace("_", "")


def _col_role(cell):
    key = _col_key(cell)
    if key in _DATE_COLS:
        return "date"
    if key in _HR_COLS:
        return "hr"
    if key in _SLEEP_COLS:
        return "sleep"
    if key in _ACTIVE_COLS:
        return "active"
    return None


def _parse_day(cell):
    s = cell.strip().strip('"').replace(".", "-").replace("/", "-")
    head = s.split()[0]
    parts = head.split("-")
    if len(parts) != 3 or len(parts[0]) != 4:
        return None
    try:
        return dt.date(int(parts[0]), int(parts[1]), int(parts[2])).isoformat()
    except ValueError:
        return None


def _parse_num(cell):
    s = cell.strip().strip('"').replace(",", "")
    if not s:
        return None
    return float(s)


def _sleep_minutes(value):
    """6시간 이하는 시간, 그보다 크면 분. 7.4 와 440 을 같은 칸에 받는다."""
    if value is None:
        return None
    if value <= 16:
        return round(value * 60, 1)
    return value


def import_nights(con, text, now=None):
    """헬스 앱에서 받은 표를 밤 기록으로 넣는다.

    첫 줄이 제목이면 날짜·심박·수면(시간 또는 분)·운동분을 알아본다.
    제목이 없으면 날짜, 심박, 수면 순서다. 이미 있는 날은 밤 심박만 바꾼다.
    """
    raw = (text or "").lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.strip() for ln in raw.split("\n") if ln.strip() and not ln.strip().startswith("#")]
    if not lines:
        raise ValueError("표가 비어 있어요")
    sep = max([",", "\t", ";"], key=lambda s: lines[0].count(s))
    if lines[0].count(sep) == 0:
        sep = ","
    rows = [[c.strip() for c in ln.split(sep)] for ln in lines]
    roles = {i: _col_role(c) for i, c in enumerate(rows[0])}
    if any(roles.values()):
        data = rows[1:]
    else:
        data = rows
        roles = {0: "date", 1: "hr"}
        width = max(len(r) for r in data)
        if width >= 3:
            roles[2] = "sleep"
        if width >= 4:
            roles[3] = "active"
    if "date" not in roles.values() or "hr" not in roles.values():
        raise ValueError("날짜와 심박 칸이 필요해요")
    today_s = today(now)
    saved = []
    skipped = 0
    for row in data:
        got = {}
        for i, role in roles.items():
            if role and i < len(row):
                got[role] = row[i]
        day = _parse_day(got.get("date", ""))
        try:
            hr = _parse_num(got.get("hr", ""))
        except ValueError:
            hr = None
        if day is None or hr is None or not (30 < hr < 140) or day > today_s:
            skipped += 1
            continue
        try:
            sleep = _sleep_minutes(_parse_num(got.get("sleep", "")))
        except ValueError:
            sleep = None
        try:
            active = _parse_num(got.get("active", ""))
        except ValueError:
            active = None
        night_min = sleep if sleep is not None else 420
        put_night(con, day, round(hr, 1), night_min, active, sleep, source="import")
        saved.append(day)
    if not saved:
        raise ValueError("넣을 수 있는 밤 기록이 없어요. 날짜,심박,수면 순서를 확인해 주세요")
    if today_s in saved:
        con.execute("DELETE FROM notifications WHERE day=?", (today_s,))
        con.commit()
    saved.sort()
    return {"n": len(saved), "skipped": skipped, "first": saved[0], "last": saved[-1]}


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, default=str)
