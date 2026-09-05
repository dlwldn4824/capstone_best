"""Day 7 / Day 14 — 산출물 전체를 하나의 보고서로 묶는다.

    python scripts/08_report.py

docs/EXPERIMENT_LOG.md 를 생성한다. 교수님 보고용 초안이자
outputs/ 아래 모든 표를 한 곳에서 볼 수 있는 색인이다.
"""
import argparse
from pathlib import Path

import pandas as pd
from _bootstrap import banner, setup

from nesy import report


def _try(path, reader=pd.read_csv):
    p = Path(path)
    return reader(p) if p.exists() else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--note", default="", help="이번 실행에 대한 메모")
    args = ap.parse_args()

    cfg, _ = setup()
    out = Path(cfg["paths"]["outputs"])
    tables = out / "tables"
    banner("EXPERIMENT LOG 생성")

    sections = [
        ("# 실험 로그", ""),
        ("데이터 원본: `{}`\n".format(cfg["paths"]["raw"])
         + "윈도: {}s / step {}s  ·  평가: {}\n".format(
             cfg["window"]["length_sec"], cfg["window"]["step_sec"],
             cfg["eval"]["scheme"])
         + ("\n> {}\n".format(args.note) if args.note else ""), ""),
    ]

    if "SYNTHETIC" in cfg["paths"]["raw"]:
        sections.append((
            "> **경고 — 합성 데이터**\n>\n"
            "> 아래 수치는 `src/nesy/synthetic.py` 가 만든 가짜 신호에서 나온 것이다.\n"
            "> 생리 파라미터를 우리가 직접 심었으므로 분류가 쉬운 것이 당연하다.\n"
            "> 코드 검증용이며 연구 결과가 아니다. PhysioNet 데이터로 다시 돌릴 것.", ""))

    blocks = [
        ("## 1. 데이터 감사", tables / "data_audit.csv", 60),
        ("## 2. Baseline ML (논문 재현)", tables / "baseline_summary.csv", None),
        ("## 3. Feature ablation", tables / "ablation.csv", None),
        ("## 4. 분할 방식 비교", tables / "split_comparison.csv", None),
        ("## 5. Neural baseline", tables / "neural_summary.csv", None),
        ("## 6. 규칙 coverage", tables / "rule_coverage.csv", None),
        ("## 7. 상태별 fact 발생률", tables / "fact_distribution.csv", None),
        ("## 8. Audit 판정 x 정오", tables / "audit_breakdown.csv", None),
        ("## 9. 최종 비교", tables / "final_comparison.csv", None),
        ("## 10. 피험자별 정확도 (LOSO)", tables / "per_subject_loso.csv", None),
    ]
    for title, path, maxrows in blocks:
        df = _try(path)
        if df is None:
            sections.append((title, "_아직 생성되지 않음: `{}`_".format(path.name)))
            continue
        sections.append((title, report.md_table(df, max_rows=maxrows)))
        if maxrows and len(df) > maxrows:
            sections.append((None, "_({}행 중 {}행만 표시)_".format(len(df), maxrows)))

    figs = sorted((out / "figures").glob("*.png"))
    sections.append(("## 그림", "\n".join(
        "- `outputs/figures/{}`".format(f.name) for f in figs) or "_없음_"))

    sections.append(("## 다음 할 일", "\n".join([
        "- [ ] PhysioNet 실데이터로 `01_audit.py` 재실행, `protocol.yaml` 검증",
        "- [ ] `threshold_sweep.csv` 로 fact 임계 민감도 확정",
        "- [ ] precision 이 낮은 규칙 제거 또는 근거 재검토",
        "- [ ] WESAD 이식성 확인 (Day 13)",
        "- [ ] 실패 시나리오(결과 D) 분석 항목 채우기",
    ])))

    p = report.write_md(
        Path(__file__).resolve().parents[1] / "docs" / "EXPERIMENT_LOG.md",
        sections)
    print("-> {}".format(p))


if __name__ == "__main__":
    main()
