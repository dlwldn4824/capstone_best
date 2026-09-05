"""세션 폴더 -> features.csv.

features.csv 는 A/B/C 세 역할이 공유하는 고정 인터페이스다.
컬럼 구조는 docs/SCHEMAS.md 에 정의되어 있고 여기서만 바뀐다.

메타 컬럼
    sample_id, subject_id, session_type, session_id, version,
    segment_name, seg_index, condition, label, t_start, t_end,
    needs_review, ml_excluded, flagged
feature 컬럼
    FEATURE_GROUPS 참조 (총 49개 + 품질 지표 n_beats, acc_dyn_mean)

담당: 역할 A (데이터/전처리)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import (io_e4, preprocess_acc, preprocess_bvp, preprocess_eda, protocol,
               selfreport)

# --- feature 그룹 (역할 B 의 ablation 이 이 정의를 그대로 쓴다) -------------
FEATURE_GROUPS = {
    "BVP": ["bvp_mean", "bvp_std"],
    "HR": list(preprocess_acc.HR_FEATURE_KEYS),
    "HRV": list(preprocess_bvp.TIME_HRV_KEYS) + list(preprocess_bvp.FREQ_HRV_KEYS),
    "EDA": list(preprocess_eda.FEATURE_KEYS),
    "ACC": list(preprocess_acc.FEATURE_KEYS),
}

ALL_FEATURES = [f for g in ("BVP", "HR", "HRV", "EDA", "ACC")
                for f in FEATURE_GROUPS[g]]

# ablation 순서: HR -> +HRV -> +EDA -> +ACC (2주 계획 Day 5)
ABLATION_SETS = {
    "HR": FEATURE_GROUPS["HR"],
    "HR+HRV": FEATURE_GROUPS["HR"] + FEATURE_GROUPS["HRV"],
    "HR+HRV+EDA": (FEATURE_GROUPS["HR"] + FEATURE_GROUPS["HRV"]
                   + FEATURE_GROUPS["EDA"]),
    "HR+HRV+EDA+ACC": ALL_FEATURES,
}

META_COLS = ["sample_id", "subject_id", "session_type", "session_id", "version",
             "segment_name", "seg_index", "condition", "label",
             "t_start", "t_end", "needs_review", "ml_excluded", "flagged",
             "self_report", "self_report_delta", "self_report_approx"]


def _window_features(sess, t0, t1, cfg):
    """한 시간 윈도에서 모든 신호의 feature 를 뽑는다."""
    feats = {}

    bvp = sess.get("BVP")
    if bvp is not None:
        w = bvp.slice_time(t0, t1)
        feats.update(preprocess_bvp.process(w.values, w.fs, cfg)["features"])
    else:
        feats.update({k: np.nan for k in preprocess_bvp.FEATURE_KEYS})

    eda = sess.get("EDA")
    if eda is not None:
        w = eda.slice_time(t0, t1)
        feats.update(preprocess_eda.process(w.values, w.fs, cfg)["features"])
    else:
        feats.update({k: np.nan for k in preprocess_eda.FEATURE_KEYS})

    acc = sess.get("ACC")
    if acc is not None:
        w = acc.slice_time(t0, t1)
        feats.update(preprocess_acc.process(w.values, w.fs, cfg)["features"])
    else:
        feats.update({k: np.nan for k in preprocess_acc.FEATURE_KEYS})

    hr = sess.get("HR")
    if hr is not None:
        w = hr.slice_time(t0, t1)
        feats.update(preprocess_acc.hr_features(w.values, w.fs))
    else:
        feats.update({k: np.nan for k in preprocess_acc.HR_FEATURE_KEYS})

    return feats


def build(cfg, proto, session_index=None, verbose=True):
    """전체 데이터셋 -> (features_df, audit_df)."""
    raw_root = cfg["paths"]["raw"]
    if session_index is None:
        session_index = io_e4.discover_sessions(raw_root)
    if session_index.empty:
        raise FileNotFoundError(
            "세션을 찾지 못했습니다: {}\n"
            "scripts/00_download.py 를 먼저 실행하거나 "
            "scripts/00_make_synthetic.py 로 합성 데이터를 만드세요.".format(raw_root))

    wl = cfg["window"]["length_sec"]
    ws = cfg["window"]["step_sec"]
    three = cfg["labels"]["three_class"]
    excluded = set(cfg["exclude"]["ml_excluded_subjects"])
    flagged_map = cfg["exclude"]["flagged"] or {}

    rows, audit = [], []
    for _, r in session_index.iterrows():
        subj, stype, path = r["subject"], r["session_type"], r["path"]
        sess = io_e4.read_session(path)
        tags = sess["tags"]
        segs, problem = protocol.segment_session(subj, stype, tags, proto)

        is_flagged = stype in (flagged_map.get(subj) or [])
        audit.append({
            "subject_id": subj, "session_type": stype, "path": path,
            "n_tags": int(len(tags)), "n_segments_observed": max(0, len(tags) - 1),
            "version": protocol.subject_version(subj, proto),
            "problem": problem or "",
            "needs_review": problem is not None,
            "ml_excluded": subj in excluded,
            "flagged": is_flagged,
            **{"has_" + s: sess.get(s) is not None for s in io_e4.SIGNALS},
        })
        if problem is not None:
            if verbose:
                print("  [skip] {} / {}: {}".format(subj, stype, problem))
            continue

        for seg in segs:
            for (t0, t1) in protocol.windows(seg, wl, ws):
                feats = _window_features(sess, t0, t1, cfg)
                rows.append({
                    "sample_id": "{}|{}|{}|{:.0f}".format(subj, stype, seg.name, t0),
                    "subject_id": subj,
                    "session_type": stype,
                    "session_id": "{}|{}".format(subj, stype),
                    "version": seg.version,
                    "segment_name": seg.name,
                    "seg_index": seg.seg_index,
                    "condition": seg.label,             # 4-class
                    "label": three.get(seg.label, seg.label),   # 3-class
                    "t_start": t0, "t_end": t1,
                    "needs_review": False,
                    "ml_excluded": subj in excluded,
                    "flagged": is_flagged,
                    **feats,
                })
        if verbose:
            print("  [ok]   {} / {}: {} segments".format(subj, stype, len(segs)))

    df = pd.DataFrame(rows)
    if not df.empty:
        # 자기보고 스트레스 점수(1-10) 연결. 없으면 NaN 컬럼만 생긴다.
        df = selfreport.attach(df, raw_root)
        cols = META_COLS + [c for c in ALL_FEATURES if c in df.columns]
        extra = [c for c in df.columns if c not in cols]
        df = df[cols + extra]
    return df, pd.DataFrame(audit)


def load_features(cfg, drop_excluded=True, drop_flagged=False):
    """features.csv 를 읽는다. 역할 B/C 의 공통 진입점."""
    path = Path(cfg["paths"]["features_csv"])
    if not path.exists():
        raise FileNotFoundError(
            "{} 이 없습니다. scripts/02_build_features.py 를 먼저 실행하세요.".format(path))
    df = pd.read_csv(path)
    if drop_excluded and "ml_excluded" in df.columns:
        df = df[~df["ml_excluded"].astype(bool)]
    if drop_flagged and "flagged" in df.columns:
        df = df[~df["flagged"].astype(bool)]
    return df.reset_index(drop=True)
