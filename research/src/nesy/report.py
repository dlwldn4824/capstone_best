"""마크다운 표/보고서 헬퍼 (tabulate 의존성 없이)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _fmt(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "-"
    if isinstance(v, (bool, np.bool_)):
        return "O" if v else ""
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        return "{:.3f}".format(float(v)).rstrip("0").rstrip(".")
    return str(v)


def md_table(df, index=False, max_rows=None):
    """DataFrame -> GitHub 마크다운 표."""
    d = df.reset_index() if index else df
    if max_rows is not None and len(d) > max_rows:
        d = d.head(max_rows)
    cols = [str(c) for c in d.columns]
    lines = ["| " + " | ".join(cols) + " |",
             "| " + " | ".join("---" for _ in cols) + " |"]
    for _, r in d.iterrows():
        lines.append("| " + " | ".join(_fmt(r[c]) for c in d.columns) + " |")
    return "\n".join(lines)


def write_md(path, sections):
    """sections = [(제목 또는 None, 본문 문자열), ...] -> 파일."""
    parts = []
    for title, body in sections:
        if title:
            parts.append(title)
        parts.append(body)
        parts.append("")
    from pathlib import Path
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(parts), encoding="utf-8")
    return str(p)
