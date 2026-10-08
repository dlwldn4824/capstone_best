"""MCD-rPPG 얼굴 영상 → 프레임별 얼굴 색 신호 (영상은 처리 후 지운다).

    python scripts/23_mcd_extract.py --n 100        # 100명 × (안정, 운동 후) 정면 웹캠

데이터: MCD-rPPG (Egorov et al., ACM MM 2025) · CC BY 4.0
        huggingface.co/datasets/Bgeorge/mcd_rppg (원 저장소 kyegorov/mcd_rppg 미러)
        600명 × 안정/운동 후 × 카메라 3대, 프레임 동기 PPG, 건강 지표 13개

영상 1개 ≈ 80 MB (3분, 640×480, 30 fps). 100명이면 16 GB 라서 저장하지 않는다.
받는 즉시 얼굴을 찾아 웹앱과 **같은 세 영역**(이마 · 양 볼)의 평균 RGB 만 남기고 지운다.
남는 것: data/raw/mcd_rppg/traces/<id>_<state>.npz  (t, rgb, ppg, face_ok)

얼굴 영상은 개인 식별 정보다. 원본도, 얼굴 사진도 저장소에 남기지 않는다.
"""
import argparse
import concurrent.futures as cf
import io
import os
import tempfile
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

BASE = "https://huggingface.co/datasets/Bgeorge/mcd_rppg/resolve/main/"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/raw/mcd_rppg"
CAMERA = "FullHDwebcam"          # 정면

# 얼굴 상자 안에서의 비율 (x0, y0, x1, y1) — webapp/static/rppg.js 의 이마·볼과 같은 자리
ROIS = [(0.32, 0.06, 0.68, 0.22), (0.14, 0.50, 0.38, 0.72), (0.62, 0.50, 0.86, 0.72)]
DETECT_EVERY = 15


def fetch(rel, dest=None, tries=4):
    for k in range(tries):
        try:
            with urllib.request.urlopen(BASE + rel, timeout=120) as r:
                if dest is None:
                    return r.read()
                with open(dest, "wb") as f:
                    while True:
                        b = r.read(1 << 20)
                        if not b:
                            break
                        f.write(b)
                return dest
        except Exception as e:  # noqa: BLE001 — 네트워크는 다시 시도
            if k == tries - 1:
                raise
            time.sleep(3 * (k + 1))


def face_traces(video_path):
    import cv2
    cas = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cap = cv2.VideoCapture(str(video_path))
    box, rgb, ok_flags = None, [], []
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % DETECT_EVERY == 0 or box is None:
            g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cas.detectMultiScale(g, 1.2, 5, minSize=(80, 80))
            if len(faces):
                f = max(faces, key=lambda b: b[2] * b[3]).astype(float)
                box = f if box is None else 0.7 * box + 0.3 * f     # 흔들림 줄이기
        if box is None:
            rgb.append([np.nan] * 3)
            ok_flags.append(False)
        else:
            x, y, w, h = box
            acc, n = np.zeros(3), 0
            for x0, y0, x1, y1 in ROIS:
                a = frame[int(y + y0 * h):int(y + y1 * h), int(x + x0 * w):int(x + x1 * w)]
                if a.size:
                    acc += a.reshape(-1, 3).sum(0)
                    n += a.shape[0] * a.shape[1]
            rgb.append((acc / max(n, 1))[::-1].tolist())             # BGR → RGB
            ok_flags.append(n > 0)
        i += 1
    cap.release()
    return np.asarray(rgb, float), np.asarray(ok_flags, bool)


def read_meta(txt):
    """meta: '프레임번호  2023-11-13 14:10:51.684465' → 초 단위 시각."""
    rows = [ln.split(None, 1) for ln in txt.decode("utf-8", "ignore").splitlines() if ln.strip()]
    ts = pd.to_datetime([r[1] for r in rows if len(r) == 2], errors="coerce")
    t = (ts - ts[0]).total_seconds().to_numpy()
    return t


def read_ppg_sync(txt):
    """ppg_sync: 프레임마다 'PPG값  간격(초)'."""
    arr = np.loadtxt(io.BytesIO(txt))
    return arr[:, 0] if arr.ndim == 2 else arr


def process(row, tmpdir):
    sid, state = int(row.patient_id), row.step
    dest = OUT / "traces" / f"{sid}_{state}.npz"
    if dest.exists():
        return f"{sid}_{state} 있음"
    vid = Path(tmpdir) / f"{sid}_{state}.avi"
    fetch(row.video, vid)
    try:
        rgb, ok = face_traces(vid)
    finally:
        vid.unlink(missing_ok=True)                                 # 영상은 남기지 않는다
    t = read_meta(fetch(row.meta))
    ppg = read_ppg_sync(fetch(row.ppg_sync))
    n = min(len(rgb), len(t), len(ppg))
    np.savez_compressed(dest, t=t[:n], rgb=rgb[:n], ppg=ppg[:n], face_ok=ok[:n])
    return f"{sid}_{state} 프레임 {n} 얼굴 {ok[:n].mean():.0%}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()
    (OUT / "traces").mkdir(parents=True, exist_ok=True)

    db = pd.read_csv(io.BytesIO(fetch("db.csv")))
    db.to_csv(OUT / "db.csv", index=False)
    front = db[db["camera"] == CAMERA]
    both = front.groupby("patient_id")["step"].nunique()
    ids = sorted(both[both == 2].index)[: args.n]                  # 앞에서부터 n명 (결정적)
    rows = front[front["patient_id"].isin(ids)].sort_values(["patient_id", "step"])
    print(f"{len(ids)}명 · 영상 {len(rows)}개 · 정면 {CAMERA}", flush=True)

    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp, cf.ThreadPoolExecutor(args.workers) as ex:
        futs = [ex.submit(process, r, tmp) for r in rows.itertuples()]
        for k, f in enumerate(cf.as_completed(futs), 1):
            try:
                msg = f.result()
            except Exception as e:  # noqa: BLE001
                msg = f"실패: {e}"
            print(f"[{k}/{len(futs)} · {time.time() - t0:.0f}s] {msg}", flush=True)


if __name__ == "__main__":
    main()
