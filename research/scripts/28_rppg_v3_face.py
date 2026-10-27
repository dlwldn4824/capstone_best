"""얼굴 심박 v1(옛 앱) vs v2(rPPG-Toolbox 순서) vs v3(지금 앱의 face 엔진) — MCD-rPPG.

    python scripts/28_rppg_v3_face.py

25_rppg_v1_v2.py 와 같은 창(20초, 10초 간격) · 같은 정답(ppg_hr_v2)을 쓴다.
다른 점은 v3 뿐이다: webapp/face/src/pipeline 의 analyze() 를 Node 로 돌려 받는다.
그래야 '포스터에 쓰는 숫자'가 실제로 앱이 돌리는 코드의 숫자가 된다.

한계: 이 데이터에는 얼굴 랜드마크가 없다(23_mcd_extract.py 가 고정 상자로 영역을 뽑는다).
      그래서 v3 의 품질 4조건 중 '머리 이동'은 늘 통과하고 움직임 간섭도 잡히지 않는다.
      밝기 · SNR · 얼굴 잡힌 시간 · 조명 간섭 · ROI 일치는 그대로 판정된다.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from _bootstrap import banner, setup

from nesy import rppg as R

ROOT = Path(__file__).resolve().parents[1]
TR = ROOT / "data/raw/mcd_rppg/traces"
OUT = ROOT / "outputs"
FACE = ROOT.parent / "webapp" / "face"
L, STEP = 20, 10


def windows():
    """25번과 같은 방식으로 창을 자르고, 정답 · v1 · v2 와 v3 에 보낼 ROI 를 같이 낸다."""
    for f in sorted(TR.glob("*.npz")):
        sid, state = f.stem.split("_")
        d = np.load(f)
        if "roi" not in d:
            raise SystemExit(f"{f.name} 에 영역별 RGB(roi)가 없다. "
                             "scripts/23_mcd_extract.py 로 다시 뽑아야 한다.")
        ok = d["face_ok"] & np.isfinite(d["rgb"]).all(1) & np.isfinite(d["roi"]).all((1, 2))
        t, rgb, roi, ppg = d["t"][ok], d["rgb"][ok], d["roi"][ok], d["ppg"][ok]
        if len(t) < L * 25:
            continue
        for a in np.arange(0, t[-1] - L + 1e-9, STEP):
            m = (t >= a) & (t < a + L)
            if m.sum() < L * 25:
                continue
            yield dict(key=f"{sid}_{state}@{a:.0f}", sid=int(sid), state=state, start=float(a),
                       t=t[m], rgb=rgb[m], roi=roi[m], ppg=ppg[m])


def run_face(ws, tmpdir):
    """창들을 JSONL 로 적어 Node 에 넘기고 결과를 받는다."""
    src = Path(tmpdir) / "windows.jsonl"
    with src.open("w") as fh:
        for w in ws:
            fh.write(json.dumps({"key": w["key"],
                                 "t": np.round(w["t"] - w["t"][0], 4).tolist(),
                                 "roi": np.round(w["roi"], 3).tolist()}) + "\n")
    print(f"  창 {len(ws)}개 → Node (face analyze)", flush=True)
    p = subprocess.run([ "node", "scripts/eval/mcd_windows.mjs", str(src) ],
                       cwd=FACE, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"node 실패:\n{p.stderr[-2000:]}")
    out = {}
    for line in p.stdout.splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["key"]] = r
    return out


def main():
    setup()
    if not TR.exists() or not any(TR.glob("*.npz")):
        sys.exit(f"트레이스가 없다: {TR}\n먼저  python scripts/23_mcd_extract.py --n 20  을 돌린다.")
    banner("얼굴 심박 v1 vs v2 vs v3(face 엔진) — 20초 창, 10초 간격")

    ws = list(windows())
    print(f"창 {len(ws)}개 · 사람 {len({w['sid'] for w in ws})}명", flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        face = run_face(ws, tmp)

    rows = []
    for w in ws:
        g = R.ppg_hr_v2(w["t"], w["ppg"])
        e1, e2 = R.estimate(w["t"], w["rgb"]), R.estimate_v2(w["t"], w["rgb"])
        f = face.get(w["key"])
        if not (g and e1 and e2 and f) or f.get("error"):
            continue
        rows.append(dict(sid=w["sid"], state=w["state"], start=w["start"],
                         truth=g[0], truth_snr=g[1],
                         v1=e1[0], v1_snr=e1[1], v2=e2[0], v2_snr=e2[1],
                         v3=f["bpm"], v3_snr=f["snr"], v3_pass=f["pass"],
                         v3_reason=f["reason"], v3_windowed=f["windowed"],
                         v3_hrv_ok=f["hrv_ok"], v3_rmssd=f["rmssd"]))
    w = pd.DataFrame(rows)
    if w.empty:
        sys.exit("쓸 수 있는 창이 없다.")
    for v in ("v1", "v2", "v3"):
        w[v + "_err"] = (w[v] - w["truth"]).abs()

    def summ(err):
        return pd.Series(dict(MAE=err.mean(), RMSE=np.sqrt((err ** 2).mean()), within5=(err <= 5).mean()))

    tab = pd.DataFrame({v: summ(w[v + "_err"]) for v in ("v1", "v2", "v3")}).T
    tab.insert(0, "n", len(w))
    print(tab.round(3).to_string())

    banner("품질 기준을 통과한 창만 쓸 때 — 통과율과 정확도")
    rows = []
    for v in ("v1", "v2"):
        for thr in (-99, 0, 2, 4, 6):
            m = w[v + "_snr"] >= thr
            e = w.loc[m, v + "_err"]
            rows.append(dict(method=v, gate=f"SNR≥{thr}", pass_rate=m.mean(),
                             MAE=e.mean(), within5=(e <= 5).mean()))
    m = w["v3_pass"]
    rows.append(dict(method="v3", gate="품질 4조건", pass_rate=m.mean(),
                     MAE=w.loc[m, "v3_err"].mean(), within5=(w.loc[m, "v3_err"] <= 5).mean()))
    for thr in (-99, 0, 2, 4, 6):
        m3 = w["v3_snr"] >= thr
        rows.append(dict(method="v3", gate=f"SNR≥{thr}", pass_rate=m3.mean(),
                         MAE=w.loc[m3, "v3_err"].mean(), within5=(w.loc[m3, "v3_err"] <= 5).mean()))
    gate = pd.DataFrame(rows)
    print(gate.round(3).to_string(index=False))

    banner("v3 가 창을 거부한 이유 · 구간 선택 · HRV")
    print(w["v3_reason"].fillna("통과").value_counts().to_string())
    print(f"\n구간 선택을 쓴 창: {w['v3_windowed'].mean():.1%}")
    print(f"HRV 를 낸 창: {w['v3_hrv_ok'].mean():.1%}  (통과한 창 중 {w.loc[w['v3_pass'],'v3_hrv_ok'].mean():.1%})")

    OUT.mkdir(exist_ok=True)
    tab.to_csv(OUT / "rppg_v1_v2_v3.csv")
    gate.to_csv(OUT / "rppg_v1_v2_v3_gate.csv", index=False)
    w.to_csv(OUT / "rppg_v1_v2_v3_windows.csv", index=False)
    print("\n저장: outputs/rppg_v1_v2_v3*.csv")


if __name__ == "__main__":
    main()
