"""거울 기록 엔진 — 기획 변경 보고서(2026-10-19) '설명되는 변화와 설명되지 않는 변화의 기록'.

워치 없이 전면 카메라 하나로, 아침 거울 · 공부 시작 · 밤 세안 세 루틴에서 15초씩
얼굴 심박(rPPG, POS)과 안색(볼 붉은기, 이마 대비)을 기록한다. 평소와 다르면 이유를
한 번 묻고, 설명되는 변화와 설명되지 않는 변화를 나눠 쌓아 시험기간 리포트로 정리한다.

    판정은 규칙이 한다     루틴별 베이스라인(중앙값 · MAD) 대비 k × MAD
    이유는 사람이 안다     음주 · 카페인 · 운동 · 수면부족 · 해당 없음
    리포트는 문장만 쓴다   수치 요약을 받아 문장으로 (진단 · 조언 없음)

보고서 기능 번호(FR-xx)를 함수 설명에 적었다. 워치 버전 엔진은 engine.py 에 그대로 있다.
저장: data/app/mirror.db (git 제외). 얼굴 영상은 브라우저 밖으로 나오지 않는다 — 숫자만 온다.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "app" / "mirror.db"

ROUTINES = ("morning", "desk", "night")
ROUTINE_KO = {"morning": "아침 거울", "desk": "공부 시작", "night": "밤 세안"}
QUESTION = {"morning": "어젯밤 뭐 했어요?", "desk": "방금 뭐 마셨어요?", "night": "오늘 하루 어땠어요?"}
REASONS = ("alcohol", "caffeine", "exercise", "sleep", "none")
REASON_KO = {"alcohol": "음주", "caffeine": "카페인", "exercise": "운동", "sleep": "수면부족", "none": "해당 없음"}
CAFFEINE_SUB = {"coffee": "커피", "energy": "에너지드링크", "other": "기타"}

# FR-09 · 7.2 — 정해진 값과 아직 정할 값
BASELINE_DAYS = 7          # 준비 주간 7일
MIN_SAMPLES = 4            # 루틴당 최소 4회
K_DEFAULT = 2.5            # 보고서 후보 2 / 2.5 / 3 — 팀원 2주 시험 운용으로 확정 (10장)
K_CHOICES = (2.0, 2.5, 3.0)
MAD_FLOOR_BPM = 1.0        # 준비 주간 값이 거의 같을 때 흩어짐 0 으로 나누지 않게 (문턱값 아님)
MAD_FLOOR_A = 0.3          # 안색 지표의 같은 용도
MAD_SCALE = 1.4826         # 정규분포에서 MAD → 표준편차

# 내 스케줄 — 루틴마다 하는 시각. 그 시각부터 DUE_MIN 분 동안 아직 안 했으면 배너로 스캔을 권한다.
SCHEDULE_DEFAULT = {"morning": {"at": "07:30", "on": True}, "desk": {"at": "14:00", "on": True},
                    "night": {"at": "23:00", "on": True}}
DUE_MIN = 120
CRLF = "\r\n"              # iCalendar 줄바꿈

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, day TEXT, routine TEXT, phase TEXT,
  bpm REAL, snr REAL, bright REAL, motion REAL, quality_ok INT, retry INT DEFAULT 0,
  a_rel REAL, a_cheek REAL, makeup INT DEFAULT 0,
  judgement TEXT, delta REAL, ref_med REAL, ref_mad REAL, ref_n INT,
  a_judgement TEXT, a_delta REAL,
  reason TEXT, reason_sub TEXT, answered_at TEXT, trigger TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""


def connect(path=DB_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def now():
    return dt.datetime.now()


# --- 설정 ----------------------------------------------------------------------
def get_setting(con, key, default=None):
    r = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def set_setting(con, key, value):
    con.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))
    con.commit()


def settings(con):
    return {
        "consent": get_setting(con, "consent", False),
        "k": float(get_setting(con, "k", K_DEFAULT)),
        "exam_start": get_setting(con, "exam_start"),
        "exam_end": get_setting(con, "exam_end"),
        "schedule": get_setting(con, "schedule", SCHEDULE_DEFAULT),
    }


def clean_schedule(v):
    """{"morning": {"at": "07:30", "on": true}, …} 만 받는다."""
    out = {}
    for r in ROUTINES:
        x = v.get(r, SCHEDULE_DEFAULT[r]) if isinstance(v, dict) else None
        if not isinstance(x, dict):
            raise ValueError("스케줄 형식이 맞지 않아요")
        at = str(x.get("at", ""))
        try:
            hh, mm = (int(p) for p in at.split(":"))
            assert 0 <= hh < 24 and 0 <= mm < 60
        except (ValueError, AssertionError):
            raise ValueError("시각은 HH:MM 으로 적어 주세요")
        out[r] = {"at": "{:02d}:{:02d}".format(hh, mm), "on": bool(x.get("on", True))}
    return out


def _sched_dt(day, hhmm):
    hh, mm = (int(p) for p in hhmm.split(":"))
    return dt.datetime.combine(day, dt.time(hh, mm))


def schedule_status(sched, done, at):
    """지금 해야 할 루틴(due)과 다음 예정(next). done = 오늘 품질 통과 기록이 있는 루틴."""
    due, nxt = None, None
    for r in ROUTINES:
        x = sched[r]
        if not x["on"]:
            continue
        t = _sched_dt(at.date(), x["at"])
        if r not in done and t <= at < t + dt.timedelta(minutes=DUE_MIN):
            if due is None or t > _sched_dt(at.date(), sched[due]["at"]):
                due = r                                   # 겹치면 더 최근 것
        cand = t if t > at else t + dt.timedelta(days=1)
        if nxt is None or cand < nxt[1]:
            nxt = (r, cand)
    return {"due": due, "due_since": sched[due]["at"] if due else None,
            "next": {"routine": nxt[0], "at": nxt[1].isoformat(timespec="minutes")} if nxt else None}


def schedule_ics(sched, origin):
    """캘린더 앱용 — 매일 반복 일정 + 그 시각 알림. 일정 링크가 바로 15초 스캔을 연다."""
    stamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    start = dt.date.today().strftime("%Y%m%d")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Vity//Mirror//KO", "CALSCALE:GREGORIAN"]
    for r in ROUTINES:
        x = sched[r]
        if not x["on"]:
            continue
        hhmm = x["at"].replace(":", "")
        url = "{}/?routine={}&go=1&t=calendar".format(origin.rstrip("/"), r)
        lines += ["BEGIN:VEVENT", "UID:vity-{}@mirror".format(r), "DTSTAMP:" + stamp,
                  "DTSTART:{}T{}00".format(start, hhmm), "DURATION:PT5M", "RRULE:FREQ=DAILY",
                  "SUMMARY:Vity · {} 15초 스캔".format(ROUTINE_KO[r]), "URL:" + url,
                  "DESCRIPTION:" + url, "BEGIN:VALARM", "ACTION:DISPLAY",
                  "DESCRIPTION:{} 15초 스캔할 시간이에요".format(ROUTINE_KO[r]), "TRIGGER:PT0M",
                  "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return CRLF.join(lines) + CRLF


# --- FR-02 루틴 식별 · ExamPeriod ---------------------------------------------------
def routine_for(at, hint=None):
    """호출한 자동화가 루틴을 알려주면 그것을, 아니면 시각으로 (사용자가 나중에 고칠 수 있다)."""
    if hint in ROUTINES:
        return hint
    h = at.hour
    if 4 <= h < 11:
        return "morning"
    if 11 <= h < 20:
        return "desk"
    return "night"


def phase_for(day, s):
    """준비(시험 1주 전) · 시험 · 회복(시험 직후 1주) · 평소."""
    if not s.get("exam_start") or not s.get("exam_end"):
        return "none"
    d = dt.date.fromisoformat(day)
    st, en = dt.date.fromisoformat(s["exam_start"]), dt.date.fromisoformat(s["exam_end"])
    if st - dt.timedelta(days=BASELINE_DAYS) <= d < st:
        return "prep"
    if st <= d <= en:
        return "exam"
    if en < d <= en + dt.timedelta(days=7):
        return "recovery"
    return "none"


# --- FR-09 루틴별 베이스라인 ------------------------------------------------------
def _ref_rows(con, routine, before_day, s):
    """베이스라인에 들어갈 기록: 같은 루틴 · 품질 통과 · 시험/회복 주간 제외.

    시험기간이 정해져 있으면 준비 주간 기록만, 아니면 직전 7일(오늘 제외).
    """
    if s.get("exam_start"):
        rows = con.execute(
            "SELECT * FROM records WHERE routine=? AND quality_ok=1 AND phase='prep' AND day<? ORDER BY at",
            (routine, before_day)).fetchall()
        if len(rows) >= MIN_SAMPLES:
            return rows
    lo = (dt.date.fromisoformat(before_day) - dt.timedelta(days=BASELINE_DAYS)).isoformat()
    return con.execute(
        "SELECT * FROM records WHERE routine=? AND quality_ok=1 AND phase IN ('none','prep') "
        "AND day>=? AND day<? ORDER BY at", (routine, lo, before_day)).fetchall()


def _med_mad(values, floor):
    v = np.asarray([x for x in values if x is not None and np.isfinite(x)], float)
    if len(v) == 0:
        return None, None, 0
    med = float(np.median(v))
    mad = max(float(MAD_SCALE * np.median(np.abs(v - med))), floor)
    return med, mad, len(v)


def baseline(con, routine, day, s=None):
    s = s or settings(con)
    rows = _ref_rows(con, routine, day, s)
    med, mad, n = _med_mad([r["bpm"] for r in rows], MAD_FLOOR_BPM)
    amed, amad, an = _med_mad([r["a_rel"] for r in rows if not r["makeup"]], MAD_FLOOR_A)
    return {"routine": routine, "med": med, "mad": mad, "n": n, "ready": n >= MIN_SAMPLES,
            "a_med": amed, "a_mad": amad, "a_n": an, "a_ready": an >= MIN_SAMPLES}


# --- FR-10 변화 판정 ------------------------------------------------------------
def judge(bpm, quality_ok, bl, k):
    """품질 미달 → 'low' · 기준 쌓는 중 → 'building' · k×MAD 이상 → 'diff' · 아니면 'same'."""
    if not quality_ok or bpm is None:
        return "low", None
    if not bl["ready"]:
        return "building", None
    delta = bpm - bl["med"]
    return ("diff" if abs(delta) >= k * bl["mad"] else "same"), delta


def judge_complexion(a_rel, makeup, bl, k):
    """FR-07 · FR-12 — 안색은 보조 신호. 화장 · 선크림이면 제외. 판정을 바꾸지 않는다."""
    if makeup or a_rel is None or not bl["a_ready"]:
        return ("excluded" if makeup else "building"), None
    d = a_rel - bl["a_med"]
    return ("diff" if abs(d) >= k * bl["a_mad"] else "same"), d


def add_record(con, bpm, snr, bright, motion, quality_ok, a_rel=None, a_cheek=None,
               makeup=False, routine=None, at=None, trigger=None, retry=0):
    """한 번의 기록을 판정해 저장하고 돌려준다. 평소와 다르면 이유를 기다린다 (FR-11)."""
    at = at or now()
    s = settings(con)
    day = at.date().isoformat()
    routine = routine_for(at, routine)
    bl = baseline(con, routine, day, s)
    j, delta = judge(bpm, bool(quality_ok), bl, s["k"])
    aj, ad = judge_complexion(a_rel, makeup, bl, s["k"])
    cur = con.execute(
        "INSERT INTO records (at,day,routine,phase,bpm,snr,bright,motion,quality_ok,retry,a_rel,a_cheek,makeup,"
        "judgement,delta,ref_med,ref_mad,ref_n,a_judgement,a_delta,trigger) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (at.isoformat(timespec="seconds"), day, routine, phase_for(day, s), bpm, snr, bright, motion,
         int(bool(quality_ok)), retry, a_rel, a_cheek, int(bool(makeup)), j, delta, bl["med"], bl["mad"], bl["n"],
         aj, ad, trigger))
    con.commit()
    return record(con, cur.lastrowid)


def answer(con, rid, reason, sub=None):
    """FR-11 — 이유 한 번. '해당 없음' 은 설명되지 않는 변화로 따로 보관된다."""
    if reason not in REASONS:
        raise ValueError("모르는 이유: {}".format(reason))
    if reason != "caffeine":
        sub = None
    con.execute("UPDATE records SET reason=?, reason_sub=?, answered_at=? WHERE id=?",
                (reason, sub, now().isoformat(timespec="seconds"), rid))
    con.commit()
    return record(con, rid)


def set_routine(con, rid, routine):
    """FR-02 — 사용자가 루틴을 고치면 그 루틴의 베이스라인으로 다시 판정한다."""
    r = con.execute("SELECT * FROM records WHERE id=?", (rid,)).fetchone()
    if r is None or routine not in ROUTINES:
        raise ValueError("고칠 수 없다")
    s = settings(con)
    bl = baseline(con, routine, r["day"], s)
    j, delta = judge(r["bpm"], bool(r["quality_ok"]), bl, s["k"])
    aj, ad = judge_complexion(r["a_rel"], r["makeup"], bl, s["k"])
    con.execute("UPDATE records SET routine=?, judgement=?, delta=?, ref_med=?, ref_mad=?, ref_n=?, "
                "a_judgement=?, a_delta=? WHERE id=?",
                (routine, j, delta, bl["med"], bl["mad"], bl["n"], aj, ad, rid))
    con.commit()
    return record(con, rid)


def status_of(r):
    """FR-13 — 기록 목록의 구분."""
    if r["judgement"] == "low":
        return "low"
    if r["judgement"] == "building":
        return "building"
    if r["judgement"] == "same":
        return "same"
    if r["reason"] is None:
        return "ask"
    return "unexplained" if r["reason"] == "none" else "explained"


def _num(x, nd=1):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def record(con, rid):
    r = con.execute("SELECT * FROM records WHERE id=?", (rid,)).fetchone()
    return _row(r) if r else None


def _row(r):
    reason = r["reason"]
    return {
        "id": r["id"], "at": r["at"], "day": r["day"], "routine": r["routine"],
        "routine_ko": ROUTINE_KO[r["routine"]], "phase": r["phase"],
        "bpm": _num(r["bpm"]), "snr": _num(r["snr"], 2), "quality_ok": bool(r["quality_ok"]),
        "bright": _num(r["bright"]), "motion": _num(r["motion"], 3),
        "a_rel": _num(r["a_rel"], 2), "makeup": bool(r["makeup"]),
        "judgement": r["judgement"], "delta": _num(r["delta"]),
        "ref": _num(r["ref_med"]), "ref_mad": _num(r["ref_mad"]), "ref_n": r["ref_n"],
        "a_judgement": r["a_judgement"], "a_delta": _num(r["a_delta"], 2),
        "reason": reason, "reason_ko": REASON_KO.get(reason, ""),
        "reason_sub": r["reason_sub"], "reason_sub_ko": CAFFEINE_SUB.get(r["reason_sub"] or "", ""),
        "status": status_of(r), "question": QUESTION[r["routine"]],
    }


def records(con, limit=200):
    rows = con.execute("SELECT * FROM records ORDER BY at DESC LIMIT ?", (limit,)).fetchall()
    return [_row(r) for r in rows]


# --- 상태 (홈 화면) ----------------------------------------------------------------
def state(con, at=None):
    at = at or now()
    s = settings(con)
    day = at.date().isoformat()
    today = [_row(r) for r in con.execute("SELECT * FROM records WHERE day=? ORDER BY at", (day,)).fetchall()]
    bls = {r: baseline(con, r, day, s) for r in ROUTINES}
    phase = phase_for(day, s)
    prep_days = None
    if s.get("exam_start"):
        st = dt.date.fromisoformat(s["exam_start"])
        prep_days = {"day": max(0, min(BASELINE_DAYS, (at.date() - (st - dt.timedelta(days=BASELINE_DAYS))).days + 1)),
                     "of": BASELINE_DAYS, "exam_in": (st - at.date()).days}
    pending = [r for r in today if r["status"] == "ask"]
    done = {r["routine"] for r in today if r["quality_ok"]}
    return {
        "today": day, "now_routine": routine_for(at), "phase": phase, "prep": prep_days,
        "settings": s, "baselines": {r: {k: (_num(v) if isinstance(v, float) else v) for k, v in b.items()}
                                     for r, b in bls.items()},
        "today_records": today, "pending": pending[-1] if pending else None,
        "labels": {"routine": ROUTINE_KO, "reason": REASON_KO, "caffeine": CAFFEINE_SUB, "question": QUESTION},
        "schedule": schedule_status(s["schedule"], done, at),
        "report_ready": phase == "recovery" or (s.get("exam_end") is not None and day > s["exam_end"]),
    }


# --- FR-14 시험기간 리포트 ------------------------------------------------------------
def report(con, s=None):
    """수치 요약 → 문장. 진단 · 조언 표현을 쓰지 않는다 (6.5 · 6.6)."""
    s = s or settings(con)
    if not s.get("exam_start") or not s.get("exam_end"):
        return {"ready": False, "reason": "시험기간을 먼저 정해주세요"}
    rows = [_row(r) for r in con.execute(
        "SELECT * FROM records WHERE day>=? AND day<=? ORDER BY at", (s["exam_start"], s["exam_end"])).fetchall()]
    ok = [r for r in rows if r["status"] not in ("low",)]
    diff = [r for r in ok if r["judgement"] == "diff"]
    explained = [r for r in diff if r["status"] == "explained"]
    unexplained = [r for r in diff if r["status"] == "unexplained"]

    by_reason = []
    for reason in ("caffeine", "alcohol", "sleep", "exercise"):
        rs = [r for r in explained if r["reason"] == reason]
        if not rs:
            continue
        routines = {}
        for r in rs:
            routines.setdefault(r["routine"], []).append(r["delta"])
        top = max(routines.items(), key=lambda kv: len(kv[1]))
        subs = sorted({r["reason_sub_ko"] for r in rs if r["reason_sub_ko"]})
        by_reason.append({"reason": reason, "reason_ko": REASON_KO[reason], "n": len(rs), "subs": subs,
                          "routine": top[0], "routine_ko": ROUTINE_KO[top[0]],
                          "median_delta": _num(float(np.median(top[1])))})

    # 회복: 시험 끝난 뒤 아침 거울 기록이 평소 범위로 돌아온 첫 날
    rec = [_row(r) for r in con.execute(
        "SELECT * FROM records WHERE day>? AND routine='morning' AND quality_ok=1 ORDER BY at",
        (s["exam_end"],)).fetchall()]
    recovery_day = next((r["day"] for r in rec if r["judgement"] == "same"), None)
    alcohol_red = sum(1 for r in explained if r["reason"] == "alcohol" and r["a_judgement"] == "diff"
                      and (r["a_delta"] or 0) > 0)

    summary = {
        "records": len(rows), "quality_ok": len(ok), "changed": len(diff),
        "with_reason": len(explained), "unexplained": len(unexplained),
        "by_reason": by_reason, "unexplained_days": [{"day": r["day"], "routine_ko": r["routine_ko"],
                                                      "delta": r["delta"]} for r in unexplained],
        "recovery_day": recovery_day, "alcohol_with_redness": alcohol_red,
    }
    return {"ready": True, "period": [s["exam_start"], s["exam_end"]], "summary": summary,
            "sentences": report_sentences(summary)}


def josa(word, with_final, without_final):
    """받침에 맞는 조사. josa('카페인', '이', '가') → '카페인이'."""
    ch = word.rstrip(")")[-1:] if word else ""
    c = ord(ch) - 0xAC00 if ch else -1
    if word.endswith(")"):
        c = ord(word.split("(")[0][-1]) - 0xAC00
    if c < 0 or c > 11171:
        return word + without_final
    return word + (with_final if c % 28 else without_final)


def report_sentences(sm):
    """AI 리포트 자리 (FR-14). 지금은 같은 규칙으로 문장을 만든다 — 입력은 수치 요약뿐.

    LLM 으로 바꿀 때도 이 summary dict 만 넘긴다. 얼굴 이미지는 넘기지 않는다 (7.4).
    """
    out = ["시험기간 기록 {}회, 그중 평소와 달랐던 기록 {}회에 이유가 붙었어요.".format(
        sm["records"], sm["with_reason"])]
    for b in sm["by_reason"]:
        what = b["reason_ko"] + ("(" + "·".join(b["subs"]) + ")" if b["subs"] else "")
        out.append("{} 있던 날 {} 심박이 평소보다 {:+.0f} bpm 높게 기록됐어요 ({}회).".format(
            josa(what, "이", "가"), b["routine_ko"], b["median_delta"] or 0, b["n"]))
    if sm["alcohol_with_redness"]:
        out.append("음주 기록 중 {}회는 볼 붉은기도 평소보다 높았어요.".format(sm["alcohol_with_redness"]))
    if sm["unexplained"]:
        days = ", ".join(sorted({u["day"][5:].replace("-", "/") for u in sm["unexplained_days"]}))
        out.append("이유 없이 평소와 달랐던 기록 {}회는 날짜와 함께 따로 보관했어요 ({}).".format(sm["unexplained"], days))
    else:
        out.append("이유 없이 평소와 달랐던 기록은 없어요.")
    if sm["recovery_day"]:
        out.append("시험이 끝난 뒤 아침 심박은 {}에 평소 범위로 돌아왔어요.".format(sm["recovery_day"][5:].replace("-", "/")))
    else:
        out.append("시험이 끝난 뒤 아침 심박이 평소 범위로 돌아온 기록은 아직 없어요.")
    return out


# --- FR-16 삭제 · 시연 -------------------------------------------------------------
def reset(con, keep_settings=True):
    con.execute("DELETE FROM records")
    if not keep_settings:
        con.execute("DELETE FROM settings")
    con.commit()


ROUTINE_BASE = {"morning": (62.0, 1.6), "desk": (72.0, 2.0), "night": (66.0, 1.8)}
TIMES = {"morning": (7, 40), "desk": (14, 10), "night": (23, 20)}


def seed_demo(con, at=None, seed=3):
    """시연용: 준비 주간 7일 → 시험 2주(카페인 · 밤샘 · 음주 · 이유 없는 날 섞임) → 회복 주간 진행 중."""
    rng = np.random.default_rng(seed)
    at = at or now()
    today = at.date()
    reset(con)
    start = today - dt.timedelta(days=20)
    end = today - dt.timedelta(days=7)
    set_setting(con, "exam_start", start.isoformat())
    set_setting(con, "exam_end", end.isoformat())
    set_setting(con, "consent", True)

    def put(day, routine, bump=0.0, a_bump=0.0, reason=None, sub=None, makeup=False):
        hh, mm = TIMES[routine]
        t = dt.datetime.combine(day, dt.time(hh, mm)) + dt.timedelta(minutes=int(rng.integers(-20, 20)))
        if t > at:
            return
        mu, sd = ROUTINE_BASE[routine]
        bpm = round(mu + rng.normal(0, sd * 0.45) + bump, 1)
        a_rel = round(1.8 + rng.normal(0, 0.25) + a_bump, 2)
        r = add_record(con, bpm, float(rng.uniform(1, 6)), float(rng.uniform(90, 170)), float(rng.uniform(0.005, 0.02)),
                       True, a_rel, a_rel + 12, makeup, routine, t, "demo")
        if r["judgement"] == "diff" and reason:
            answer(con, r["id"], reason, sub)

    for i in range(BASELINE_DAYS):                      # 준비 주간
        d = start - dt.timedelta(days=BASELINE_DAYS - i)
        for rt in ROUTINES:
            put(d, rt)
    plan = {2: ("desk", 9, 0, "caffeine", "energy"), 3: ("morning", 7, 0, "sleep", None),
            4: ("desk", 8, 0, "caffeine", "coffee"), 6: ("night", 6, 1.6, "alcohol", None),
            7: ("morning", 6, 1.2, "alcohol", None), 8: ("desk", 10, 0, "caffeine", "energy"),
            9: ("morning", 8, 0, "none", None), 10: ("desk", 9, 0, "caffeine", "coffee"),
            11: ("morning", 7, 0, "sleep", None), 12: ("night", 7, 0, "none", None),
            13: ("desk", 8, 0, "exercise", None)}
    for i in range((end - start).days + 1):             # 시험 주간
        d = start + dt.timedelta(days=i)
        for rt in ROUTINES:
            p = plan.get(i)
            if p and p[0] == rt:
                put(d, rt, p[1], p[2], p[3], p[4])
            else:
                put(d, rt, makeup=(rt == "desk" and i % 4 == 0))
    for i in range(1, 8):                               # 회복 주간 (진행 중)
        d = end + dt.timedelta(days=i)
        for rt in ROUTINES:
            late = i <= 2 and rt == "morning"                 # 시험 직후 이틀은 아침이 아직 높다
            put(d, rt, bump=6 if late else 0.0, reason="sleep" if late else None)
