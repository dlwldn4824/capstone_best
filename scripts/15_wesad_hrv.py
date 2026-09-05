"""WESAD — 손목 PPG HRV 가 못 잡는 것인가, 원래 안 변하는 것인가.

    python scripts/15_wesad_hrv.py

우리는 두 데이터에서 HRV 가 스트레스에 반응하지 않는 것을 확인했다.
  Hongn (실험실)  36명 중 18명만 RMSSD 감소 — 우연
  Nurse (실환경)  15명 중 7명          — 우연
둘 다 손목 PPG 로 쟀으므로 **측정 한계인지 생리적 사실인지** 가를 수 없었다.

WESAD 는 같은 사람 같은 시각에 가슴 ECG(700 Hz)와 손목 PPG(64 Hz)를 동시에
기록한다. 두 방식으로 같은 함수를 써서 HRV 를 내고 비교한다.

    ECG HRV 가 스트레스에 반응한다  ->  손목 PPG 의 **측정 한계**
    ECG HRV 도 반응하지 않는다      ->  **생리적 사실**

담당: 역할 C
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from _bootstrap import banner, setup

from nesy import preprocess_bvp, report, wesad

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/wesad"


def build(root, win=60.0, step=30.0, verbose=True):
    """피험자별로 REST / STRESS 구간을 윈도로 잘라 두 HRV 를 모두 계산한다."""
    subs = wesad.discover_subjects(root)
    rows = []
    for _, s in subs.iterrows():
        d = wesad.load_subject(s["path"])
        chest = d["signal"]["chest"]
        wrist = d["signal"]["wrist"]
        segs = wesad.label_segments(d["label"])

        n = 0
        for name, t0, t1 in segs:
            if name not in wesad.USE_LABELS:
                continue
            for (a, b) in wesad.windows(t0, t1, win, step):
                ecg = wesad.slice_signal(chest["ECG"], wesad.CHEST_FS, a, b)
                bvp = wesad.slice_signal(wrist["BVP"], wesad.WRIST_FS["BVP"], a, b)
                if len(ecg) < wesad.CHEST_FS * 30 or len(bvp) < 64 * 30:
                    continue

                r = {"subject_id": s["subject_id"], "label": name,
                     "t_start": a, "t_end": b}
                r.update(wesad.hrv_from_ecg(ecg))
                # 손목은 우리 기존 파이프라인 그대로
                w = preprocess_bvp.process(bvp, wesad.WRIST_FS["BVP"],
                                           {"hrv": {"bandpass": [0.5, 10.0],
                                                    "min_bpm": 40, "max_bpm": 200,
                                                    "ibi_rel_thresh": 0.30,
                                                    "min_beats_for_freq": 30}})
                r.update({"ppg_" + k: v for k, v in w["features"].items()})
                rows.append(r)
                n += 1
        if verbose:
            print("  {}: 윈도 {}개".format(s["subject_id"], n))
    return pd.DataFrame(rows)


def paired(df, col, group="subject_id"):
    """피험자별 중앙값을 짝지어 STRESS - REST 를 검정한다."""
    piv = df.pivot_table(index=group, columns="label", values=col,
                         aggfunc="median")
    if not {"REST", "STRESS"} <= set(piv.columns):
        return None
    piv = piv.dropna(subset=["REST", "STRESS"])
    if len(piv) < 3:
        return None
    d = piv["STRESS"] - piv["REST"]
    try:
        _, p = stats.wilcoxon(piv["STRESS"], piv["REST"])
    except ValueError:
        p = np.nan
    return {"n": len(d), "rest": round(float(piv["REST"].median()), 2),
            "stress": round(float(piv["STRESS"].median()), 2),
            "diff": round(float(d.median()), 2),
            "n_down": int((d < 0).sum()), "p": round(float(p), 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None)
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()

    cfg, _ = setup()
    out = Path(cfg["paths"]["outputs"])
    cache = out / "wesad_hrv.csv"
    banner("WESAD — 가슴 ECG vs 손목 PPG 로 잰 HRV")

    if cache.exists() and not args.rebuild:
        df = pd.read_csv(cache)
        print("캐시 사용: {} ({:,}행)".format(cache.name, len(df)))
    else:
        root = args.root or wesad.find_root(RAW)
        if root is None:
            raise SystemExit(
                "WESAD 폴더를 찾지 못했습니다. 압축을 풀었는지 확인하세요:\n"
                "  python -c \"import sys;sys.path.insert(0,'src');"
                "from nesy import wesad;print(wesad.extract_zip("
                "'data/raw/wesad/WESAD.zip','data/raw/wesad'))\"")
        print("경로: {}".format(root))
        df = build(root)
        df.to_csv(cache, index=False)

    print("\n윈도 {:,}개 / 피험자 {}명".format(len(df), df["subject_id"].nunique()))
    print(df["label"].value_counts().to_string())

    # --- 1. 신호 품질 ------------------------------------------------------
    banner("1. 검출된 박동 수 — 신호 품질")
    q = df.groupby("label")[["ecg_n_beats", "ppg_n_beats"]].median().round(1)
    print(q.to_string())
    print("\n박동 30개 미만 비율 (주파수 HRV 산출 불가)")
    for c, nm in (("ecg_n_beats", "가슴 ECG"), ("ppg_n_beats", "손목 PPG")):
        print("  {:9s} {:.1%}".format(nm, (df[c] < 30).mean()))

    # --- 2. 두 방식의 일치도 ----------------------------------------------
    banner("2. 같은 윈도에서 두 방식이 얼마나 일치하는가")
    rows = []
    for m in ("rmssd", "sdnn", "ibi_mean"):
        a, b = df["ecg_" + m], df["ppg_" + m]
        ok = np.isfinite(a) & np.isfinite(b)
        if ok.sum() < 10:
            continue
        r, p = stats.pearsonr(a[ok], b[ok])
        rho, _ = stats.spearmanr(a[ok], b[ok])
        rows.append({"지표": m, "n": int(ok.sum()),
                     "ECG 중앙값": round(float(a[ok].median()), 1),
                     "PPG 중앙값": round(float(b[ok].median()), 1),
                     "Pearson r": round(float(r), 3),
                     "Spearman": round(float(rho), 3)})
    agree = pd.DataFrame(rows)
    print(agree.to_string(index=False))
    print("\n  r 이 낮으면 손목 PPG 가 ECG 와 다른 값을 재고 있다는 뜻이다.")

    # --- 3. ⚠ 핵심 — 스트레스에 반응하는가 --------------------------------
    banner("3. 스트레스에 반응하는가 (피험자 내 짝지은 비교)")
    rows = []
    for m in ("rmssd", "sdnn", "hr_from_ibi", "pnn50"):
        for src, pre in (("가슴 ECG", "ecg_"), ("손목 PPG", "ppg_")):
            r = paired(df, pre + m)
            if r:
                rows.append({"측정": src, "지표": m, **r})
    resp = pd.DataFrame(rows)
    print(resp.to_string(index=False))
    print("\n  diff = STRESS - REST (피험자별 중앙값의 중앙값)")
    print("  n_down = 감소한 피험자 수. HRV 는 각성 시 감소가 정설이다.")

    # --- 4. 판정 -----------------------------------------------------------
    banner("4. 판정")
    ecg_r = resp[(resp["측정"] == "가슴 ECG") & (resp["지표"] == "rmssd")]
    ppg_r = resp[(resp["측정"] == "손목 PPG") & (resp["지표"] == "rmssd")]
    if len(ecg_r) and len(ppg_r):
        e, w = ecg_r.iloc[0], ppg_r.iloc[0]
        print("  RMSSD  가슴 ECG  {:+.2f} ms, {}/{}명 감소, p={:.4f}".format(
            e["diff"], e["n_down"], e["n"], e["p"]))
        print("  RMSSD  손목 PPG  {:+.2f} ms, {}/{}명 감소, p={:.4f}".format(
            w["diff"], w["n_down"], w["n"], w["p"]))
        print()
        if e["p"] < 0.05 and w["p"] >= 0.05:
            print("  => ECG 는 반응하고 손목은 못 잡는다. **측정 한계**다.")
            print("     우리 두 데이터의 HRV 음성 결과는 기기 한계로 설명된다.")
        elif e["p"] >= 0.05 and w["p"] >= 0.05:
            print("  => 둘 다 반응하지 않는다. **생리적 사실**에 가깝다.")
            print("     60초 윈도에서 HRV 로 스트레스를 잡는다는 전제 자체를")
            print("     재검토해야 한다.")
        elif e["p"] < 0.05 and w["p"] < 0.05:
            print("  => 둘 다 반응한다. 우리 두 데이터의 음성 결과는")
            print("     WESAD 와 다른 조건(윈도 길이, 자극 강도) 탓일 수 있다.")
        else:
            print("  => 손목만 반응한다. 예상 밖이므로 신호 품질을 재확인할 것.")

    print("\n[대조] 우리 기존 결과")
    print("  Hongn (실험실, 손목)  36명 중 18명 감소 — 우연")
    print("  Nurse (실환경, 손목)  15명 중  7명 감소 — 우연")

    report.write_md(ROOT / "docs" / "WESAD_HRV.md", [
        ("# WESAD — 손목 PPG HRV 는 측정 한계인가 생리적 사실인가", ""),
        ("## 1. 신호 품질", report.md_table(q.reset_index())),
        ("## 2. 두 방식의 일치도", report.md_table(agree)),
        ("## 3. 스트레스 반응", report.md_table(resp)),
    ])
    print("\n-> outputs/wesad_hrv.csv, docs/WESAD_HRV.md")


if __name__ == "__main__":
    main()
