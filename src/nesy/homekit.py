"""Homekit2020 로더 — 지속성 계층을 실제 감염 라벨로 검증하기 위한 데이터.

Merrill et al., CHIL 2023. Evidation Health, 2020-02 ~ 2020-05.
Synapse syn22803188 (통제 접근 — docs/HOMEKIT.md 신청 절차 참고).
Fitbit 분 단위 기록(심박·걸음·수면) + 매일 증상 설문 + PCR 독감 결과.

왜 이 데이터인가
    Nurse 는 근무 중에만 쟀고 사건이 자기보고 스트레스라서 지속성 계층을
    검증할 수 없었다 (docs/PERSISTENCE.md). Homekit 은 **잘 때도 쟀고**
    **PCR 로 확인된 독감**이 있다.

Hongn / Nurse 와 다른 점
    신호    EDA·ACC 원신호가 없다. 심박·걸음·수면 단계뿐이다.
            → 스트레스 규칙은 쓸 수 없다. 설명은 운동·수면 부족 두 가지.
    단위    하루 단위 표가 이미 있다. 창을 하루로 접는 단계가 필요 없다.
    시각    Fitbit 은 보통 **현지 시각**으로 저장한다. 참가자가 미국 전역이라
            persistence.day_index() (UTC epoch → Chicago) 를 쓰면 안 된다.

⚠ 아래 열 이름은 공개 코드(behavioral-data/Homekit2020)에서 확인한 것이다.
  v1.0 zip 의 실제 배치와 수면 단계 코드의 의미는 **받은 뒤
  scripts/18_homekit_audit.py 로 먼저 확인**하고 여기 상수를 고친다.

출력은 persistence.py 가 받는 하루 표 (subject_id, day, carried_frac, valid)
이므로 fit_day_thresh / alerts / sweep / chance_baseline 을 그대로 쓴다.

담당: 역할 C
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# --- 원본 이름 ---------------------------------------------------------------
DAY_TABLE = "fitbit_day_level_activity"
LAB_TABLE = "lab_results_with_triggerdate"
SURVEY_TABLE = "daily_surveys_onehot"
MINUTE_TABLE = "processed_fitbit_minute_level_activity"

# 원본 열 -> 우리 열
DAY_COLS = {
    "participant_id": "subject_id",
    "date": "day",
    "resting_heart_rate": "rhr",
    "total_asleep_minutes": "asleep_min",
    "main_efficiency": "sleep_eff",
    "veryActiveMinutes": "very_active_min",
    "sedentaryMinutes": "sedentary_min",
    "missing_hr": "missing_hr",
    "missing_sleep": "missing_sleep",
    "missing_steps": "missing_steps",
}

MINUTE_COLS = ["participant_id", "timestamp", "heart_rate", "missing_heart_rate",
               "steps", "sleep_classic_0", "sleep_classic_1",
               "sleep_classic_2", "sleep_classic_3"]

# Fitbit classic 수면은 asleep / restless / awake 세 단계다.
# 0 번이 '수면 기록 없음' 인지는 감사로 확인해야 한다. 확인 전까지는 1 만 쓴다.
ASLEEP_COLS = ("sleep_classic_1",)

# 날 경계: 정오~다음 날 정오. 밤은 **깨어난 날**에 붙는다.
# 22:00 (1일) + 12h = 10:00 (2일) / 07:00 (2일) + 12h = 19:00 (2일) → 둘 다 2일.
DAY_SHIFT = pd.Timedelta(hours=12)


# --- 파일 찾기 -----------------------------------------------------------------
def find_tables(root):
    """root 아래에서 표를 찾는다. zip 배치가 확정되기 전이라 재귀로 찾는다.

    반환: {이름: 경로}. CSV 표는 파일, 분 단위는 parquet 디렉터리.
    """
    root = Path(root)
    found = {}
    for name in (DAY_TABLE, LAB_TABLE, SURVEY_TABLE):
        hits = sorted(root.rglob(name + ".csv"))
        if hits:
            found[name] = hits[0]
    hits = sorted(p for p in root.rglob(MINUTE_TABLE) if p.is_dir())
    if hits:
        found[MINUTE_TABLE] = hits[0]
    return found


def _require(tables, name):
    if name not in tables:
        raise FileNotFoundError(
            "{} 를 찾지 못했다. scripts/18_homekit_audit.py 로 배치를 확인할 것."
            .format(name))
    return tables[name]


# --- 하루 단위 표 -------------------------------------------------------------
def load_day(root):
    """하루 단위 Fitbit 요약. 열 이름을 우리 규약으로 바꾸고 날을 정규화한다."""
    path = _require(find_tables(root), DAY_TABLE)
    df = pd.read_csv(path, dtype={"participant_id": str})
    keep = [c for c in DAY_COLS if c in df.columns]
    df = df[keep].rename(columns=DAY_COLS)
    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    return df.sort_values(["subject_id", "day"]).reset_index(drop=True)


# --- 분 단위 -> 수면 중 심박 ----------------------------------------------------
def nocturnal_partial(minute_df, asleep_cols=ASLEEP_COLS):
    """분 단위 조각 하나를 (사람, 날) 별 합·개수로 접는다.

    합과 개수로 내는 이유: 분 단위는 수억 행이라 조각(batch)으로만 읽을 수
    있다. 합·개수는 조각끼리 그냥 더하면 되지만 중앙값은 그렇지 않다.
    """
    m = minute_df
    asleep = np.zeros(len(m), dtype=bool)
    for c in asleep_cols:
        asleep |= m[c].to_numpy() > 0
    hr = pd.to_numeric(m["heart_rate"], errors="coerce").to_numpy(dtype=float)
    ok = asleep & np.isfinite(hr) & (hr > 0)
    if "missing_heart_rate" in m.columns:
        ok &= ~m["missing_heart_rate"].astype(bool).to_numpy()
    if not ok.any():
        return pd.DataFrame(columns=["subject_id", "day", "hr_sum", "hr_n"])

    ts = pd.to_datetime(m["timestamp"].to_numpy()[ok])
    day = (ts + DAY_SHIFT).normalize()
    part = pd.DataFrame({
        "subject_id": m["participant_id"].astype(str).to_numpy()[ok],
        "day": day,
        "hr_sum": hr[ok],
        "hr_n": 1,
    })
    return part.groupby(["subject_id", "day"], as_index=False)[["hr_sum", "hr_n"]].sum()


def load_nocturnal(root, asleep_cols=ASLEEP_COLS, batch_size=1_000_000):
    """분 단위 parquet 를 조각으로 읽어 (사람, 날) 수면 중 평균 심박을 낸다.

    전체를 pandas 로 올리지 않는다 (1,400만 시간 ≈ 수억 행).
    """
    import pyarrow.dataset as ds

    path = _require(find_tables(root), MINUTE_TABLE)
    dset = ds.dataset(str(path), format="parquet", partitioning="hive")
    cols = [c for c in MINUTE_COLS if c in dset.schema.names]
    parts = []
    for batch in dset.to_batches(columns=cols, batch_size=batch_size):
        p = nocturnal_partial(batch.to_pandas(), asleep_cols=asleep_cols)
        if len(p):
            parts.append(p)
    if not parts:
        return pd.DataFrame(columns=["subject_id", "day", "night_hr", "night_min"])
    g = pd.concat(parts).groupby(["subject_id", "day"], as_index=False).sum()
    g["night_hr"] = g["hr_sum"] / g["hr_n"]
    g = g.rename(columns={"hr_n": "night_min"})
    return g[["subject_id", "day", "night_hr", "night_min"]]


# --- 사건 라벨 ------------------------------------------------------------------
def load_events(root):
    """PCR 독감 양성의 증상 신고일 집합 {(subject_id, day)}.

    결과 통보일이 아니라 trigger_datetime(증상 신고로 검사가 시작된 날)을 쓴다.
    통보일은 며칠 늦어 조기 탐지 평가를 망친다.
    """
    path = _require(find_tables(root), LAB_TABLE)
    lab = pd.read_csv(path, dtype={"participant_id": str})
    res = lab["result"].astype(str).str.lower()
    pos = res.str.contains("detected") & ~res.str.contains("not")
    if "test_name" in lab.columns:
        pos &= lab["test_name"].astype(str).str.lower().str.contains("flu")
    lab = lab[pos]
    days = pd.to_datetime(lab["trigger_datetime"]).dt.normalize()
    return set(zip(lab["participant_id"].astype(str), days))


# --- 개인 기준선 ----------------------------------------------------------------
def _past_ref(days, values, valid, window, lag, min_n):
    """각 날에 대해 [d - lag - window, d - lag) 의 유효 값 배열을 돌려준다.

    **과거만** 본다. 최근 lag 일을 빼는 이유는 잠복기를 기준선에 섞지 않기 위해서다.
    """
    days = pd.to_datetime(pd.Series(days)).to_numpy()
    out = []
    lo_off = np.timedelta64(lag + window, "D")
    hi_off = np.timedelta64(lag, "D")
    for d in days:
        sel = valid & (days >= d - lo_off) & (days < d - hi_off)
        v = values[sel]
        out.append(v if len(v) >= min_n else None)
    return out


def rolling_z(day_df, col, window=28, lag=7, min_n=14, valid_col="valid",
              subject_col="subject_id"):
    """사람별 과거 기준선 대비 robust z (중앙값·MAD).

    기준선이 아직 안 쌓인 앞쪽 날은 NaN — 판정하지 않는다.
    """
    z = np.full(len(day_df), np.nan)
    for _, idx in day_df.groupby(subject_col).groups.items():
        sub = day_df.loc[idx].sort_values("day")
        x = sub[col].to_numpy(dtype=float)
        ok = sub[valid_col].to_numpy(dtype=bool) & np.isfinite(x)
        refs = _past_ref(sub["day"], x, ok, window, lag, min_n)
        for pos, (i, ref) in enumerate(zip(sub.index, refs)):
            if ref is None or not ok[pos]:
                continue
            med = np.median(ref)
            mad = 1.4826 * np.median(np.abs(ref - med))
            if mad > 0:
                z[day_df.index.get_loc(i)] = (x[pos] - med) / mad
    return z


def rolling_quantile(day_df, col, q, window=28, lag=0, min_n=14,
                     subject_col="subject_id"):
    """사람별 과거 분위수. 설명 규칙의 '이 사람치고 많이 / 적게' 기준."""
    out = np.full(len(day_df), np.nan)
    for _, idx in day_df.groupby(subject_col).groups.items():
        sub = day_df.loc[idx].sort_values("day")
        x = sub[col].to_numpy(dtype=float)
        ok = np.isfinite(x)
        refs = _past_ref(sub["day"], x, ok, window, lag, min_n)
        for i, ref in zip(sub.index, refs):
            if ref is not None:
                out[day_df.index.get_loc(i)] = np.quantile(ref, q)
    return out


# --- 설명 ---------------------------------------------------------------------
def explain_day(day_df, active_q=0.90, active_min_abs=30, sleep_q=0.10,
                short_sleep_min=360):
    """생활 맥락으로 설명되는 날을 표시한다. 피부전도가 없어 스트레스는 못 본다.

    exercise     **전날** 고강도 활동이 그 사람 상위 10% 이거나 30분 이상.
                 밤 심박은 전날 운동을 탄다. 밤을 깨어난 날에 붙였으므로
                 d 의 밤 = d-1 의 활동 직후다. 절대 기준을 같이 두는 이유:
                 운동을 자주 하는 사람은 상위 10% 만으로는 대부분 놓친다.
    sleep_debt   그날 밤 수면이 그 사람 하위 10% 이거나 6시간 미만.
    """
    d = day_df.sort_values(["subject_id", "day"]).copy()
    act_hi = rolling_quantile(d, "very_active_min", active_q)
    slp_lo = rolling_quantile(d, "asleep_min", sleep_q)

    va = d["very_active_min"].to_numpy(dtype=float)
    active = ((va >= act_hi) | (va >= active_min_abs)) & (va > 0)
    d["_active"] = active
    prev = d.groupby("subject_id")[["day", "_active"]].shift(1)
    yesterday = (d["day"] - prev["day"]).dt.days.eq(1).to_numpy()
    d["exercise"] = yesterday & prev["_active"].eq(True).to_numpy()

    asleep = d["asleep_min"].to_numpy(dtype=float)
    d["sleep_debt"] = np.isfinite(asleep) & ((asleep <= slp_lo) | (asleep < short_sleep_min))
    return d.drop(columns="_active").sort_index()


# --- 하루 표 조립 ---------------------------------------------------------------
def build_day_table(day, night, min_night_min=180, z_thresh=2.0, ceiling=None,
                    **z_kw):
    """하루 요약 + 수면 중 심박 -> persistence 가 받는 하루 표.

    carried_frac   1.0 = 이탈했는데 설명 안 됨 / 0.0 = 아님. 이 데이터는 처음부터
                   하루 단위라 비율이 아닌 0/1 이다. persistence 임계 0.5 로 쓴다.
    carried_raw    설명 계층 없이 이탈만 본 경우 (Mishra 방식 비교군)
    held           이탈했지만 설명된 날. persistence.alerts(hold_col="held") 로
                   넘겨 연속을 끊지도 잇지도 않게 한다.
    valid          수면 중 심박이 min_night_min 분 이상이고 기준선이 선 날.
                   짧은 날은 버리지 않고 판정만 보류한다 (인·월 분모 때문).
    ceiling        fit_cause_ceiling() 결과. 처음엔 None 으로 만들고, train 에서
                   상한을 정한 뒤 apply_explanation() 으로 다시 판정한다.
    """
    d = day.merge(night, on=["subject_id", "day"], how="left")
    d["night_min"] = d["night_min"].fillna(0)
    d["valid"] = d["night_min"] >= min_night_min
    d = d.sort_values(["subject_id", "day"]).reset_index(drop=True)

    d["night_z"] = rolling_z(d, "night_hr", **z_kw)
    d = explain_day(d)
    # 판정 불가(기준선 미형성)인 날도 valid 에서 뺀다
    d["valid"] = d["valid"] & np.isfinite(d["night_z"])
    return apply_explanation(d, z_thresh=z_thresh, ceiling=ceiling)


CAUSES = ("exercise", "sleep_debt")


def fit_cause_ceiling(table, train_mask=None, q=0.95, min_n=20):
    """원인별 '이 설명으로 감당되는 밤 심박 z' 의 상한을 train 에서만 정한다.

    deviation.fit_cause_ceiling 과 같은 생각이다. 운동한 다음 날에도 아플 수
    있다. 운동이 보통 만드는 크기를 넘는 이탈은 운동으로 닫지 않는다.
    표본이 min_n 보다 적으면 그 원인은 상한을 두지 않는다.
    """
    z = table["night_z"].to_numpy(dtype=float)
    ok = table["valid"].to_numpy(dtype=bool) & np.isfinite(z)
    if train_mask is not None:
        ok &= np.asarray(train_mask, dtype=bool)
    out = {}
    for cause in CAUSES:
        sel = ok & table[cause].to_numpy(dtype=bool)
        out[cause] = float(np.quantile(z[sel], q)) if sel.sum() >= min_n else None
    return out


def apply_explanation(table, z_thresh=2.0, ceiling=None):
    """이탈 판정과 설명을 (다시) 붙인다. 상한을 바꿔 재판정할 때도 쓴다."""
    d = table.copy()
    z = d["night_z"].to_numpy(dtype=float)
    deviated = d["valid"].to_numpy(dtype=bool) & (z >= z_thresh)   # NaN 은 False
    ceiling = ceiling or {}
    by = {}
    for cause in CAUSES:
        has = d[cause].to_numpy(dtype=bool)
        cap = ceiling.get(cause)
        if cap is not None and np.isfinite(cap):
            has = has & (z <= cap)
        by[cause] = has
    explained = by["exercise"] | by["sleep_debt"]

    d["deviated"] = deviated
    d["explained_by"] = np.where(~deviated, "",
                         np.where(by["exercise"], "exercise",
                         np.where(by["sleep_debt"], "sleep_debt", "")))
    d["carried_frac"] = (deviated & ~explained).astype(float)
    d["carried_raw"] = deviated.astype(float)
    d["held"] = deviated & explained
    return d


def random_filter(day_df, n_drop_by_subject, seed=0, col="carried_raw"):
    """설명 계층과 **같은 개수**의 이탈일을 무작위로 걷어낸 대조군.

    설명 계층이 경보를 줄이는 것이 '아무거나 걷어내도 줄어서' 인지 가르려면
    필요하다. 걷어낸 날은 ours 와 똑같이 '보류' 로 둔다 — 해결로 세면
    연속이 끊겨 대조군만 불리해진다.

    n_drop_by_subject: {subject: 걷어낼 이탈일 수}
    반환: (carried, held) 두 배열
    """
    rng = np.random.default_rng(seed)
    carried = day_df[col].to_numpy(dtype=float).copy()
    held = np.zeros(len(day_df), dtype=bool)
    pos = {i: k for k, i in enumerate(day_df.index)}
    for s, idx in day_df.groupby("subject_id").groups.items():
        cand = [i for i in idx if carried[pos[i]] > 0]
        k = min(int(n_drop_by_subject.get(s, 0)), len(cand))
        if k:
            for i in rng.choice(cand, size=k, replace=False):
                carried[pos[i]] = 0.0
                held[pos[i]] = True
    return carried, held


def subject_split(subjects, test_frac=0.3, seed=0):
    """사람 단위 분할. 임계는 train 사람에게서만 정한다."""
    s = np.array(sorted(set(subjects)))
    rng = np.random.default_rng(seed)
    rng.shuffle(s)
    n_test = max(1, int(round(len(s) * test_frac)))
    return set(s[n_test:]), set(s[:n_test])
