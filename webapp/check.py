"""대학생 헬스체크 엔진 — 30초 얼굴 스캔 결과를 받아 점수 · 평소 대비 · 추천을 만들고 저장한다.

참고한 서비스 (기사): 삼성화재 'AI 건강관상'(30초, 심박 · 호흡 · HRV · 스트레스 · 종합점수),
롯데건설 안면인식 건강측정(15초), 유니온커뮤니티 × 딥메디 HealthID(얼굴인증 + 맥박 · 스트레스).
여기서는 공개 데이터로 검증한 것만 숫자로 보여준다 (docs/CHECK_DESIGN.md):
    심박 · HRV(RMSSD · SDNN) · 스트레스 지수 · 불규칙 여부 · 호흡(참고) · BMI(입력)
혈압 · 산소포화도 · 체온 · 피부나이는 일반 카메라로 검증할 수 없어 재지 않는다.

계산 자체(박동 · HRV · 스트레스)는 브라우저 vitals.js 가 하고, 같은 계산이 src/nesy/vitals.py 에 있다.
이 파일은 점수(vitals.health_score) · 평소 대비 · 추천 문장 · 저장만 맡는다. 영상은 오지 않는다.
"""
from __future__ import annotations

import datetime as dt
import json
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nesy import vitals as V  # noqa: E402

DB_PATH = ROOT / "data" / "app" / "check.db"
BASE_DAYS, BASE_MIN = 14, 3
KINDS = ("normal", "before_breath", "after_breath")

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, day TEXT, kind TEXT, pair INT,
  hr REAL, snr REAL, signal TEXT, rmssd REAL, sdnn REAL, pnn50 REAL, si REAL, stress REAL, hrv_conf TEXT,
  irregular INT, rr REAL, rr_conf TEXT, sleep_h REAL, caffeine INT, mood INT, score INT, parts TEXT, mid TEXT);
CREATE TABLE IF NOT EXISTS profile (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS groups (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, name TEXT, start TEXT, end TEXT,
  rule TEXT, owner TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS members (gid INT, mid TEXT, nick TEXT, joined TEXT, PRIMARY KEY (gid, mid));
CREATE TABLE IF NOT EXISTS checkins (gid INT, mid TEXT, day TEXT, at TEXT, PRIMARY KEY (gid, mid, day));
"""
GROUP_MAX, WINDOW_MIN, GROUP_PER_USER = 10, 60, 5   # 그룹 인원 · 인증 시간대 최소 길이(분) · 한 사람이 들어갈 수 있는 그룹 수
CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
GROUP_ICONS = ("sleep", "coffee", "move", "calm")      # 그룹 성격별 캐릭터 (기존 에셋): 기상 · 공부 · 운동 · 기본   # 헷갈리는 0 O 1 I 는 뺀다
METRIC_KEYS = ("hr", "snr", "signal", "rmssd", "sdnn", "pnn50", "si", "stress", "hrv_conf", "irregular", "rr", "rr_conf")


def connect(path=DB_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    if "mid" not in [r[1] for r in con.execute("PRAGMA table_info(scans)")]:      # 예전 DB: 기기(사람) 구분 칸 추가
        con.execute("ALTER TABLE scans ADD COLUMN mid TEXT")
        con.commit()
    if "icon" not in [r[1] for r in con.execute("PRAGMA table_info(groups)")]:
        con.execute("ALTER TABLE groups ADD COLUMN icon TEXT")
        con.commit()
    return con


def now():
    return dt.datetime.now()


# --- 내 정보 ---------------------------------------------------------------------
def _pk(mid, k):
    return k if not mid else mid + ":" + k


def profile(con, mid=None):
    pre = (mid + ":") if mid else ""
    p = {}
    for r in con.execute("SELECT * FROM profile"):
        k = r["key"]
        if pre and k.startswith(pre):
            p[k[len(pre):]] = json.loads(r["value"])
        elif not pre and ":" not in k:
            p[k] = json.loads(r["value"])
    p.setdefault("consent", False)
    p["bmi"] = V.bmi(p.get("height"), p.get("weight"))
    return p


def set_profile(con, mid=None, **kw):
    for k, v in kw.items():
        if k not in ("height", "weight", "birth_year", "consent"):
            raise ValueError("모르는 항목: " + k)
        if k == "height" and v is not None and not 120 <= float(v) <= 220:
            raise ValueError("키는 120–220 cm 로 적어 주세요")
        if k == "weight" and v is not None and not 30 <= float(v) <= 200:
            raise ValueError("몸무게는 30–200 kg 로 적어 주세요")
        con.execute("INSERT OR REPLACE INTO profile VALUES (?,?)", (_pk(mid, k), json.dumps(v)))
    con.commit()


# --- 평소 (최근 14일, 신호 괜찮은 일반 측정 3회 이상) -----------------------------------------
def _median(v):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2


def baseline(con, at=None, exclude=None, mid=None):
    at = at or now()
    since = (at - dt.timedelta(days=BASE_DAYS)).isoformat(timespec="seconds")
    rows = con.execute("SELECT * FROM scans WHERE kind!='after_breath' AND signal!='low' AND at>=? AND at<? AND id IS NOT ? AND mid IS ?",
                       (since, at.isoformat(timespec="seconds"), exclude, mid)).fetchall()
    out = {"n": len(rows)}
    for k in ("hr", "rmssd", "stress", "score"):
        vals = [r[k] for r in rows if r[k] is not None]
        out[k] = round(_median(vals), 1) if len(vals) >= BASE_MIN else None
    return out


# --- 추천 (대학생 상황, 진단 아님) ------------------------------------------------------
def tips(m, life, base, hour):
    """우선순위 순서대로 최대 3개. action: breath(1분 호흡) · retry(다시 재기)."""
    out = []
    add = lambda i, title, body, action=None: out.append({"id": i, "title": title, "body": body, "action": action})  # noqa: E731
    sleep_h, caffeine, mood = life.get("sleep_h"), life.get("caffeine"), life.get("mood")
    hr, st, rm = m.get("hr") if m.get("signal") != "low" else None, m.get("stress"), m.get("rmssd")
    if m.get("signal") == "low":
        add("retry", "신호가 약했어요", "밝은 곳에서 화면을 정면으로 보고, 30초 동안 말하지 말고 다시 재 주세요.", "retry")
    if m.get("irregular"):
        add("irregular", "박동 간격이 고르지 않게 잡혔어요",
            "자세를 고정하고 한 번 더 재 보세요. 며칠 동안 반복되면 학교 보건실이나 병원에서 심전도로 확인해 보세요.", "retry")
    if hr is not None and hr > 100:
        add("hr_high", "심박이 빠른 편이에요", "방금 계단을 오르거나 뛰었다면 3분 앉아 쉬고 다시 재 보세요.", "retry")
    if st is not None and st >= 60:
        add("stress", "긴장도가 높아요", "1분만 4초 들이쉬고 6초 내쉬어 볼까요? 끝나고 다시 재서 전후를 비교해 드려요.", "breath")
    elif m.get("rr") and m.get("rr_conf") != "low" and m["rr"] > 20:
        add("rr", "숨이 빠른 편이에요", "천천히 내쉬는 1분 호흡을 해 보세요.", "breath")
    if caffeine is not None and caffeine >= 2 and hr is not None and (hr > 90 or (base.get("hr") and hr > base["hr"] + 8)):
        add("caffeine", "카페인이 심박을 올렸을 수 있어요", "오늘 커피는 여기까지, 대신 물 한 컵. 오후 3시 이후 카페인은 잠드는 걸 늦춰요.")
    if sleep_h is not None and sleep_h < 6:
        add("sleep", "잠이 부족했어요", "집중 시간을 짧게 끊는 게 좋아요 (오늘의 공부 모드 참고). 낮잠은 20분 안으로, 밤엔 12시 전에.")
    if rm is not None and base.get("rmssd") and rm < 0.7 * base["rmssd"]:
        add("recovery", "평소보다 회복이 덜 됐어요", "HRV 가 내 평소의 70% 아래예요. 오늘 밤은 밤샘보다 12시 전에 자는 쪽을 권해요.")
    if mood is not None and mood <= 2:
        add("mood", "기분이 가라앉아 있어요", "혼자 버거우면 학생상담센터에 이야기해 보세요. 가까운 사람에게 연락하는 것도 좋아요.")
    if hour >= 23 and st is not None and st >= 45:
        add("late", "늦은 시간이에요", "화면 밝기를 낮추고 10분 안에 잠자리 준비를 시작해 보세요.")
    if not out:
        add("good", "집중하기 좋은 상태예요", "지금 제일 어려운 과목부터 시작해 보세요. 90분마다 한 번 일어나서 몸을 풀어 주고요.")
    return out[:3]


# --- 오늘의 공부 모드 (규칙, 진단 아님) ------------------------------------------------
STUDY_MODES = {
    "deep": {"title": "깊게 집중", "focus": 50, "rest": 10, "body": "제일 어려운 과목 · 새 개념부터 시작해요. 50분마다 일어나서 몸을 풀어 주세요."},
    "split": {"title": "나눠서 집중", "focus": 25, "rest": 5, "body": "문제 풀이 · 정리 위주로 25분씩 끊어 가요. 어려운 단원은 컨디션 좋은 시간으로 미뤄요."},
    "light": {"title": "가볍게 복습", "focus": 15, "rest": 5, "body": "암기 카드 · 오답 정리처럼 가벼운 것부터. 오늘은 밤샘보다 일찍 자는 게 내일에 유리해요."},
    "wrap": {"title": "마무리", "focus": 15, "rest": 5, "body": "새로 시작하기보다 내일 할 것만 정리하고 잠자리 준비를 해요."},
}


def study_mode(score, stress, sleep_h, hour):
    """컨디션 점수 · 긴장도 · 수면 · 시각으로 오늘의 공부 방식을 고른다."""
    if hour >= 23 or hour < 4:
        k, why = "wrap", "늦은 시간"
    elif score is not None and score < 55:
        k, why = "light", "컨디션 낮음"
    elif stress is not None and stress >= 70:
        k, why = "light", "긴장도 매우 높음"
    elif sleep_h is not None and sleep_h < 5:
        k, why = "light", "잠 5시간 미만"
    elif score is not None and score >= 75 and (stress is None or stress < 50):
        k, why = "deep", "컨디션 좋음"
    else:
        k, why = "split", "보통 컨디션"
    return {"id": k, "why": why, **STUDY_MODES[k]}


# --- 인증 그룹 (기상 · 공부 시작 인증). 그룹엔 인증 시각과 연속 일수만, 수치는 공유하지 않는다 ---------
def _hm(t):
    try:
        h, m = (int(x) for x in str(t).split(":"))
        assert 0 <= h < 24 and 0 <= m < 60
    except (ValueError, AssertionError):
        raise ValueError("시각은 HH:MM 으로 적어 주세요")
    return h * 60 + m


def _code(con):
    while True:
        c = "".join(random.choice(CODE_CHARS) for _ in range(6))
        if not con.execute("SELECT 1 FROM groups WHERE code=?", (c,)).fetchone():
            return c


def _nick(nick):
    nick = (nick or "").strip()
    if not 1 <= len(nick) <= 12:
        raise ValueError("이름은 1–12자로 적어 주세요")
    return nick


def my_groups(con, mid):
    return [dict(r) for r in con.execute("SELECT g.* FROM groups g JOIN members m ON m.gid=g.id WHERE m.mid=? ORDER BY m.joined", (mid,))]


def _find(con, mid, code=None):
    """내가 속한 그룹 하나 — 코드가 없으면 첫 그룹."""
    gs = my_groups(con, mid)
    if code:
        gs = [g for g in gs if g["code"] == (code or "").strip().upper()]
    return gs[0] if gs else None


def my_group(con, mid):
    return _find(con, mid)


def _room_for_one_more(con, mid):
    if len(my_groups(con, mid)) >= GROUP_PER_USER:
        raise ValueError("그룹은 %d개까지 들어갈 수 있어요" % GROUP_PER_USER)


def create_group(con, mid, nick, name, start="07:00", end="09:00", rule="", at=None, icon="sleep"):
    at = at or now()
    name = (name or "").strip()
    if not 1 <= len(name) <= 20:
        raise ValueError("그룹 이름은 1–20자로 적어 주세요")
    if _hm(end) - _hm(start) < WINDOW_MIN:
        raise ValueError("인증 시간대는 1시간 이상이어야 해요")
    _room_for_one_more(con, mid)
    nick = _nick(nick)
    icon = icon if icon in GROUP_ICONS else "calm"
    code = _code(con)
    cur = con.execute("INSERT INTO groups (code, name, start, end, rule, owner, created, icon) VALUES (?,?,?,?,?,?,?,?)",
                      (code, name, start, end, (rule or "")[:40], mid, at.isoformat(timespec="seconds"), icon))
    con.execute("INSERT INTO members VALUES (?,?,?,?)", (cur.lastrowid, mid, nick, at.isoformat(timespec="seconds")))
    con.commit()
    return group_state(con, mid, at, code)


def join_group(con, mid, nick, code, at=None):
    at = at or now()
    g = con.execute("SELECT * FROM groups WHERE code=?", ((code or "").strip().upper(),)).fetchone()
    if not g:
        raise ValueError("없는 초대 코드예요")
    if con.execute("SELECT 1 FROM members WHERE gid=? AND mid=?", (g["id"], mid)).fetchone():
        raise ValueError("이미 들어가 있는 그룹이에요")
    _room_for_one_more(con, mid)
    if con.execute("SELECT COUNT(*) c FROM members WHERE gid=?", (g["id"],)).fetchone()["c"] >= GROUP_MAX:
        raise ValueError("그룹이 가득 찼어요 (최대 %d명)" % GROUP_MAX)
    con.execute("INSERT INTO members VALUES (?,?,?,?)", (g["id"], mid, _nick(nick), at.isoformat(timespec="seconds")))
    con.commit()
    return group_state(con, mid, at, g["code"])


def leave_group(con, mid, code=None):
    g = _find(con, mid, code)
    if not g:
        return None
    con.execute("DELETE FROM members WHERE gid=? AND mid=?", (g["id"], mid))
    con.execute("DELETE FROM checkins WHERE gid=? AND mid=?", (g["id"], mid))
    left = con.execute("SELECT mid FROM members WHERE gid=? ORDER BY joined", (g["id"],)).fetchall()
    if not left:                                            # 마지막 사람이 나가면 그룹을 지운다
        con.execute("DELETE FROM groups WHERE id=?", (g["id"],))
    elif g["owner"] == mid:                                 # 방장이 나가면 가장 먼저 들어온 사람에게
        con.execute("UPDATE groups SET owner=? WHERE id=?", (left[0]["mid"], g["id"]))
    con.commit()
    return None


def _streak(con, gid, mid, day):
    days = {r["day"] for r in con.execute("SELECT day FROM checkins WHERE gid=? AND mid=?", (gid, mid))}
    d = dt.date.fromisoformat(day)
    if d.isoformat() not in days:
        d -= dt.timedelta(days=1)                            # 오늘 아직이면 어제부터 센다
    n = 0
    while d.isoformat() in days:
        n += 1
        d -= dt.timedelta(days=1)
    return n


def try_checkin(con, mid, scan, at=None):
    """측정 하나로 내 모든 그룹에 인증 시도. 시간대 안 + 맥박이 잡힘(신호 보통 이상) = 인증. 그룹마다 하루 한 번."""
    at = at or now()
    day, mins = at.date().isoformat(), at.hour * 60 + at.minute
    out = []
    for g in my_groups(con, mid):
        r = {"group": g["name"], "code": g["code"], "window": g["start"] + "–" + g["end"], "start": g["start"]}
        done = con.execute("SELECT at FROM checkins WHERE gid=? AND mid=? AND day=?", (g["id"], mid, day)).fetchone()
        if done:
            r.update(status="already", at=done["at"][11:16])
        elif mins < _hm(g["start"]):
            r.update(status="before")
        elif mins > _hm(g["end"]):
            r.update(status="closed")
        elif scan.get("kind") == "after_breath":
            r.update(status="not_counted")
        elif scan.get("signal") == "low":
            r.update(status="no_pulse")
        else:
            con.execute("INSERT INTO checkins VALUES (?,?,?,?)", (g["id"], mid, day, at.isoformat(timespec="seconds")))
            con.commit()
            r.update(status="ok", at=at.strftime("%H:%M"), streak=_streak(con, g["id"], mid, day))
        out.append(r)
    rank = {"ok": 0, "no_pulse": 1, "not_counted": 2, "already": 3, "before": 4, "closed": 5}
    return sorted(out, key=lambda r: rank[r["status"]])


def _state_of(con, mid, g, at):
    day, mins = at.date().isoformat(), at.hour * 60 + at.minute
    rows = con.execute("SELECT m.mid, m.nick, c.at FROM members m LEFT JOIN checkins c ON c.gid=m.gid AND c.mid=m.mid AND c.day=? "
                       "WHERE m.gid=? ORDER BY (c.at IS NULL), c.at, m.joined", (day, g["id"])).fetchall()
    members = [{"nick": r["nick"], "me": r["mid"] == mid, "owner": r["mid"] == g["owner"], "at": r["at"][11:16] if r["at"] else None,
                "streak": _streak(con, g["id"], r["mid"], day)} for r in rows]
    s, e = _hm(g["start"]), _hm(g["end"])
    phase = "before" if mins < s else "open" if mins <= e else "closed"
    me = next((x for x in members if x["me"]), None)
    return {"name": g["name"], "code": g["code"], "start": g["start"], "end": g["end"], "rule": g["rule"], "owner_me": g["owner"] == mid,
            "icon": g.get("icon") or "calm", "my_streak": me["streak"] if me else 0, "my_nick": me["nick"] if me else None,
            "phase": phase, "left_min": (e - mins) if phase == "open" else (s - mins) if phase == "before" else None,
            "members": members, "done": sum(1 for x in members if x["at"]), "total": len(members),
            "me_done": any(x["me"] and x["at"] for x in members)}


def _urgency(st):
    """지금 인증해야 하는 그룹부터: 열림 · 미인증(마감 임박 순) → 곧 열림 → 인증 끝냄 → 오늘 끝남."""
    if st["phase"] == "open" and not st["me_done"]:
        return (0, st["left_min"])
    if st["phase"] == "before":
        return (1, st["left_min"])
    if st["me_done"]:
        return (2, 0)
    return (3, 0)


def groups_state(con, mid, at=None):
    at = at or now()
    return sorted((_state_of(con, mid, g, at) for g in my_groups(con, mid)), key=_urgency)


def group_state(con, mid, at=None, code=None):
    """그룹 하나 — 코드가 없으면 가장 급한 그룹."""
    at = at or now()
    if code:
        g = _find(con, mid, code)
        return _state_of(con, mid, g, at) if g else None
    gs = groups_state(con, mid, at)
    return gs[0] if gs else None


# --- 측정 저장 -------------------------------------------------------------------
def _row(r):
    d = dict(r)
    d["parts"] = json.loads(d["parts"]) if d.get("parts") else {}
    d["irregular"] = None if d["irregular"] is None else bool(d["irregular"])
    return d


def add_scan(con, metrics, sleep_h=None, caffeine=None, mood=None, kind="normal", pair=None, at=None, member=None, _checkin=True):
    if kind not in KINDS:
        raise ValueError("kind")
    at = at or now()
    m = {k: metrics.get(k) for k in METRIC_KEYS}
    if m["hr"] is None:
        raise ValueError("심박이 없어요")
    life = {"sleep_h": sleep_h, "caffeine": caffeine, "mood": mood}
    hs = V.health_score(m, sleep_h, caffeine, mood)
    cur = con.execute(
        "INSERT INTO scans (at, day, kind, pair, hr, snr, signal, rmssd, sdnn, pnn50, si, stress, hrv_conf, irregular, rr, rr_conf, "
        "sleep_h, caffeine, mood, score, parts, mid) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (at.isoformat(timespec="seconds"), at.date().isoformat(), kind, pair, m["hr"], m["snr"], m["signal"], m["rmssd"], m["sdnn"], m["pnn50"],
         m["si"], m["stress"], m["hrv_conf"], None if m["irregular"] is None else int(m["irregular"]), m["rr"], m["rr_conf"],
         sleep_h, caffeine, mood, hs["score"], json.dumps(hs["parts"]), member))
    con.commit()
    out = result(con, cur.lastrowid)
    if member and _checkin:
        out["checkins"] = try_checkin(con, member, {"signal": m["signal"], "kind": kind}, at)
    return out


def result(con, sid, mid=False):
    r = con.execute("SELECT * FROM scans WHERE id=?", (sid,)).fetchone()
    if r and mid is not False and r["mid"] != mid:            # 다른 사람 측정은 열어 주지 않는다
        r = None
    if not r:
        raise KeyError(sid)
    d = _row(r)
    at = dt.datetime.fromisoformat(d["at"])
    base = baseline(con, at, exclude=sid, mid=d.get("mid"))
    d["baseline"] = base
    d["vs"] = {k: (round(d[k] - base[k], 1) if d.get(k) is not None and base.get(k) is not None else None) for k in ("hr", "rmssd", "stress", "score")}
    d["tips"] = tips(d, {"sleep_h": d["sleep_h"], "caffeine": d["caffeine"], "mood": d["mood"]}, base, at.hour)
    d["zone"] = V.stress_zone(d["stress"])
    d["study"] = study_mode(d["score"], d["stress"], d["sleep_h"], at.hour)
    if d["kind"] == "after_breath" and d["pair"]:
        b = con.execute("SELECT * FROM scans WHERE id=?", (d["pair"],)).fetchone()
        if b:
            d["before"] = {k: b[k] for k in ("hr", "rmssd", "stress", "score")}
    return d


def history(con, n=60, mid=None):
    return [_row(r) for r in con.execute("SELECT * FROM scans WHERE mid IS ? ORDER BY at DESC LIMIT ?", (mid, n)).fetchall()]


def state(con, at=None, mid=None):
    at = at or now()
    last = con.execute("SELECT id FROM scans WHERE kind!='after_breath' AND mid IS ? ORDER BY at DESC LIMIT 1", (mid,)).fetchone()
    days = []
    for i in range(6, -1, -1):
        d = (at.date() - dt.timedelta(days=i)).isoformat()
        rs = con.execute("SELECT score, stress FROM scans WHERE day=? AND kind!='after_breath' AND signal!='low' AND mid IS ?", (d, mid)).fetchall()
        days.append({"day": d, "n": len(rs), "score": _median([r["score"] for r in rs]), "stress": _median([r["stress"] for r in rs])})
    return {"today": at.date().isoformat(), "profile": profile(con, mid), "last": result(con, last["id"]) if last else None,
            "baseline": baseline(con, at, mid=mid), "week": days,
            "count": con.execute("SELECT COUNT(*) c FROM scans WHERE mid IS ?", (mid,)).fetchone()["c"]}


def reset(con, mid=None):
    con.execute("DELETE FROM scans WHERE mid IS ?", (mid,))
    con.commit()


def seed_group_demo(con, mid, nick, at=None, seed=3):
    """발표용 그룹: 기기 사용자 + 가상 멤버 4명, 지난 2주 인증 (기기 사용자는 오늘 아직)."""
    rnd = random.Random(seed)
    at = at or now()
    while my_groups(con, mid):
        leave_group(con, mid)
    for fake in ("demo-1", "demo-2", "demo-3", "demo-4"):
        while my_groups(con, fake):
            leave_group(con, fake)
    create_group(con, "demo-1", "준호", "중간고사 기상 인증방", "07:00", "09:00", "벌금 1,000원 (앱 밖에서)", at - dt.timedelta(days=15), icon="sleep")
    code = my_group(con, "demo-1")["code"]
    for fake, name in (("demo-2", "서연"), ("demo-3", "민수"), ("demo-4", "지민")):
        join_group(con, fake, name, code, at - dt.timedelta(days=15))
    join_group(con, mid, nick, code, at - dt.timedelta(days=15))
    gid = _find(con, mid, code)["id"]
    rate = {"demo-1": 1.0, "demo-2": 0.9, "demo-3": 0.75, "demo-4": 0.55, mid: 0.85}
    for i in range(14, -1, -1):
        day = at.date() - dt.timedelta(days=i)
        for who, p in rate.items():
            if i == 0 and who in (mid, "demo-4"):
                continue
            if rnd.random() < p or (i <= 6 and who in ("demo-1", "demo-2", mid)):
                t = dt.datetime.combine(day, dt.time(7, rnd.randint(0, 50)))
                if t <= at:
                    con.execute("INSERT OR IGNORE INTO checkins VALUES (?,?,?,?)", (gid, who, day.isoformat(), t.isoformat(timespec="seconds")))
    code2 = create_group(con, "demo-2", "서연", "저녁 공부 시작방", "19:00", "21:00", "지각하면 커피 사기", at - dt.timedelta(days=10), icon="coffee")["code"]
    join_group(con, "demo-3", "민수", code2, at - dt.timedelta(days=10))
    join_group(con, mid, nick, code2, at - dt.timedelta(days=10))
    gid2 = _find(con, mid, code2)["id"]
    for i in range(9, 0, -1):
        day = at.date() - dt.timedelta(days=i)
        for who, p in (("demo-2", 0.95), ("demo-3", 0.7), (mid, 0.8)):
            if rnd.random() < p:
                t = dt.datetime.combine(day, dt.time(19, rnd.randint(0, 55)))
                con.execute("INSERT OR IGNORE INTO checkins VALUES (?,?,?,?)", (gid2, who, day.isoformat(), t.isoformat(timespec="seconds")))
    con.commit()
    return group_state(con, mid, at)


def seed_demo(con, at=None, seed=7, mid=None):
    """발표용 2주: 평일 아침 · 오후 측정, 시험 주간에 스트레스 ↑ · 수면 ↓, 호흡 전후 한 쌍."""
    rnd = random.Random(seed)
    at = at or now()
    reset(con, mid)
    set_profile(con, mid, height=168, weight=60, birth_year=2004, consent=True)
    for i in range(13, -1, -1):
        day = at.date() - dt.timedelta(days=i)
        exam = 3 <= i <= 7
        for hh in (9, 16) if i % 3 else (21,):
            t = dt.datetime.combine(day, dt.time(hh, rnd.randint(0, 50)))
            if t > at:
                continue
            sleep = round(rnd.uniform(4.5, 6) if exam else rnd.uniform(6.5, 8), 1)
            caf = rnd.choice([2, 3]) if exam else rnd.choice([0, 1, 1])
            hr = rnd.gauss(80 if exam else 71, 3)
            rm = max(12, rnd.gauss(24 if exam else 38, 5))
            st = max(5, min(95, rnd.gauss(62 if exam else 33, 8)))
            m = {"hr": round(hr, 1), "snr": 4.2, "signal": "high", "rmssd": round(rm, 1), "sdnn": round(rm * 0.95, 1), "pnn50": round(rm / 4, 1),
                 "si": None, "stress": round(st, 1), "hrv_conf": "high", "irregular": False, "rr": round(rnd.gauss(16, 1.5), 1), "rr_conf": "mid"}
            add_scan(con, m, sleep, caf, rnd.choice([2, 3]) if exam else rnd.choice([3, 4, 4, 5]), at=t, member=mid, _checkin=False)
    b = add_scan(con, {"hr": 84.0, "snr": 4.0, "signal": "high", "rmssd": 21.0, "sdnn": 22.0, "pnn50": 4.0, "si": None, "stress": 68.0,
                       "hrv_conf": "high", "irregular": False, "rr": 19.0, "rr_conf": "mid"}, 5.5, 2, 2, kind="before_breath", at=at - dt.timedelta(minutes=5),
                member=mid, _checkin=False)
    add_scan(con, {"hr": 76.0, "snr": 4.4, "signal": "high", "rmssd": 31.0, "sdnn": 30.0, "pnn50": 9.0, "si": None, "stress": 49.0,
                   "hrv_conf": "high", "irregular": False, "rr": 12.5, "rr_conf": "mid"}, 5.5, 2, 3, kind="after_breath", pair=b["id"],
             at=at - dt.timedelta(minutes=2), member=mid, _checkin=False)
