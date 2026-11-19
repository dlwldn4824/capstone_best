"""구간 선택이 실제로 값을 살린 사례 찾기 — 포스터·보고서 그림용.

    python3 research/scripts/31_find_window_case.py

30초 구간을 잘라 face 엔진(analyze)에 그대로 넘기고, 전체로는 품질에 떨어졌지만
깨끗한 구간을 골라 값을 살린 경우(result.window 가 채워진 경우)를 모은다.
그중 정답(손끝 PPG)과 가장 잘 맞는 것을 그림에 쓴다.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nesy import rppg as R          # noqa: E402

TR = ROOT / "data/raw/mcd_rppg/traces"
FACE = ROOT.parent / "webapp" / "face"
SPAN, STEP = 30.0, 15.0
MIN_FRAMES = SPAN * 25


def spans(limit):
    for f in sorted(TR.glob("*.npz"))[:limit]:
        sid, state = f.stem.split("_")
        d = np.load(f)
        ok = d["face_ok"] & np.isfinite(d["rgb"]).all(1) & np.isfinite(d["roi"]).all((1, 2))
        t, roi, ppg = d["t"][ok], d["roi"][ok], d["ppg"][ok]
        if len(t) < MIN_FRAMES:
            continue
        for a in np.arange(0, t[-1] - SPAN + 1e-9, STEP):
            m = (t >= a) & (t < a + SPAN)
            if m.sum() < MIN_FRAMES:
                continue
            yield dict(key=f"{sid}_{state}@{a:.0f}", sid=sid, state=state, start=float(a),
                       t=t[m], roi=roi[m], ppg=ppg[m])


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 160
    ws = list(spans(limit))
    print(f"30초 구간 {len(ws)}개 · 트레이스 {limit}개까지", flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "spans.jsonl"
        with src.open("w") as fh:
            for w in ws:
                fh.write(json.dumps({"key": w["key"],
                                     "t": np.round(w["t"] - w["t"][0], 4).tolist(),
                                     "roi": np.round(w["roi"], 3).tolist()}) + "\n")
        p = subprocess.run(["node", "scripts/eval/mcd_windows.mjs", str(src)],
                           cwd=FACE, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"node 실패:\n{p.stderr[-1500:]}")

    res = {}
    for line in p.stdout.splitlines():
        if line.strip():
            r = json.loads(line)
            res[r["key"]] = r

    rows = []
    for w in ws:
        r = res.get(w["key"])
        if not r or r.get("error") or not r.get("windowed") or not r.get("pass"):
            continue
        truth, tsnr = R.ppg_hr_v2(w["t"], w["ppg"])
        rows.append((abs(r["bpm"] - truth), w["key"], r["bpm"], truth, r["snr"], tsnr))

    rows.sort()
    print(f"\n전체로는 떨어졌지만 구간을 골라 살린 경우: {len(rows)}개 / {len(ws)}\n")
    print(f"{'구간':22s}{'얼굴':>8s}{'정답':>8s}{'오차':>7s}{'SNR':>7s}{'정답SNR':>8s}")
    for e, k, b, t, s, ts in rows[:12]:
        print(f"{k:22s}{b:8.2f}{t:8.2f}{e:7.2f}{s:7.2f}{ts:8.2f}")
    if rows:
        print(f"\n→ 그림에 쓸 것: {rows[0][1]}")


main()
