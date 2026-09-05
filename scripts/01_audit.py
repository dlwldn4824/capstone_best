"""Day 1 — 데이터 구조 감사 -> docs/DATA_AUDIT.md

확인 항목
  - 세션/피험자 목록
  - 센서 파일 존재 여부
  - sampling rate 가 문서값과 일치하는지
  - tags 개수 -> protocol.yaml 의 expected_segments 와 맞는지
  - 손상/제외 대상 목록

담당: 역할 A
"""
import argparse
from pathlib import Path

import pandas as pd
from _bootstrap import banner, setup

from nesy import io_e4, protocol, report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=None, help="paths.raw 덮어쓰기")
    args = ap.parse_args()

    cfg, proto = setup()
    raw = args.raw or cfg["paths"]["raw"]
    banner("DATA AUDIT: {}".format(raw))

    idx = io_e4.discover_sessions(raw)
    if idx.empty:
        print("세션을 찾지 못했습니다. 경로를 확인하세요.")
        print("합성 데이터로 시작하려면: python scripts/00_make_synthetic.py")
        return

    expected_fs = cfg["sampling_rate"]
    excluded = set(cfg["exclude"]["ml_excluded_subjects"])
    flagged = cfg["exclude"]["flagged"] or {}

    rows = []
    for _, r in idx.iterrows():
        subj, stype, path = r["subject"], r["session_type"], r["path"]
        sess = io_e4.read_session(path)
        tags = sess["tags"]
        segs, problem = protocol.segment_session(subj, stype, tags, proto)

        fs_ok, missing = [], []
        for s in io_e4.SIGNALS:
            sig = sess.get(s)
            if sig is None:
                missing.append(s)
            elif s in expected_fs and abs(sig.fs - expected_fs[s]) > 1e-6:
                fs_ok.append("{}={}Hz(기대 {})".format(s, sig.fs, expected_fs[s]))

        bvp = sess.get("BVP")
        dur = len(bvp) / bvp.fs / 60.0 if bvp is not None and len(bvp) else 0.0

        rows.append({
            "subject": subj, "folder": r.get("folder", subj), "session": stype,
            "version": protocol.subject_version(subj, proto),
            "dur_min": round(dur, 1),
            "n_tags": len(tags),
            "n_seg_obs": max(0, len(tags) - 1),
            "n_seg_exp": proto.get(stype, {}).get(
                protocol.subject_version(subj, proto), {}).get("expected_segments"),
            "n_labeled_seg": len(segs),
            "missing_signals": ",".join(missing),
            "fs_mismatch": ";".join(fs_ok),
            "problem": problem or "",
            "ml_excluded": subj in excluded,
            "flagged": stype in (flagged.get(subj) or []),
        })

    audit = pd.DataFrame(rows).sort_values(["session", "subject"])
    out_dir = Path(cfg["paths"]["outputs"])
    (out_dir / "tables").mkdir(parents=True, exist_ok=True)
    audit.to_csv(out_dir / "tables" / "data_audit.csv", index=False)

    n_bad = int((audit["problem"] != "").sum())
    print(audit.to_string(index=False))
    print("\n피험자 {}명 / 세션 {}개".format(audit["subject"].nunique(), len(audit)))
    print("프로토콜 불일치 세션: {} (feature 추출에서 자동 제외됨)".format(n_bad))

    # --- docs/DATA_AUDIT.md -------------------------------------------------
    docs = Path(__file__).resolve().parents[1] / "docs"
    docs.mkdir(exist_ok=True)
    lines = [
        "# DATA AUDIT",
        "",
        "생성: `python scripts/01_audit.py`  ·  원본: `{}`".format(raw),
        "",
        "## 요약",
        "",
        "- 피험자: {}명".format(audit["subject"].nunique()),
        "- 세션: {}개".format(len(audit)),
        "- 프로토콜 불일치(사용 불가): {}개".format(n_bad),
        "- 원 논문 제외 피험자: {}".format(sorted(excluded)),
        "",
        "## 세션별",
        "",
        report.md_table(audit),
        "",
        "## 다음 할 일",
        "",
        "1. `problem` 이 비어있지 않은 세션은 `tags.csv` 를 직접 열어 태그 수를 확인한다.",
        "2. `configs/protocol.yaml` 의 `expected_segments` / `labels` 를 실제에 맞게 고친다.",
        "3. 고친 뒤 이 스크립트를 다시 돌려 `problem` 이 비는지 확인한다.",
        "4. 그 다음에만 `02_build_features.py` 로 넘어간다.",
    ]
    (docs / "DATA_AUDIT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n-> docs/DATA_AUDIT.md, outputs/tables/data_audit.csv")


if __name__ == "__main__":
    main()
