"""안색이 무엇을 가리키는가 — MCD-rPPG 594명.

    python3 research/scripts/30_complexion_594.py

docs/research/COMPLEXION.md 의 실험 A. 20명으로는 답이 안 나왔던 질문을 594명으로 다시 묻는다.

재는 것
  1. 같은 영상 안 흔들림 — 보정이 측정 잡음을 얼마나 지우나
  2. 운동 전후 개인 짝 비교 — 24번 · 29번 스크립트와 같은 질문, 표본만 큼
  3. 혈액 지표와의 상관 — 얼굴 색이 몸 안의 무엇을 담고 있나
  4. 빈혈 판별 — 헤모글로빈이 기준 아래인 사람을 얼굴 색으로 가릴 수 있나 (AUC)
  5. 피부톤을 뺀 뒤에도 남나 — 멜라닌(L*)을 통제한 편상관

색 지표 네 개
  a_raw  얼굴 평균 RGB → a*            (24번이 쓴 값)
  a_cor  볼 a* − 이마 a*               (같은 프레임 안 보정; 기기·조명이 상쇄된다)
  b_raw  얼굴 평균 b* (노란 기)         (수면 부족 문헌이 가리키는 축)
  L_raw  얼굴 평균 L* (밝기)            (피부톤 대리값)
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nesy import rppg as R          # noqa: E402

TR = ROOT / "data/raw/mcd_rppg/traces"
OUT = ROOT / "outputs"
WIN, STEP = 20.0, 10.0
MIN_FRAMES = WIN * 25


def lab(rgb):
    L, a, b = R.to_lab(np.asarray(rgb, float))
    return float(L), float(a), float(b)


def features(path):
    """영상 하나 → 20초 구간마다 (a_raw, a_cor, b_raw, L_raw)."""
    d = np.load(path)
    ok = d["face_ok"] & np.isfinite(d["rgb"]).all(1) & np.isfinite(d["roi"]).all((1, 2))
    t, rgb, roi = d["t"][ok], d["rgb"][ok], d["roi"][ok]
    if len(t) < MIN_FRAMES:
        return np.empty((0, 4))
    out = []
    for s in np.arange(0, t[-1] - WIN + 1e-9, STEP):
        m = (t >= s) & (t < s + WIN)
        if m.sum() < MIN_FRAMES:
            continue
        L, a, b = lab(rgb[m].mean(0))
        _, a_fh, _ = lab(roi[m, 0].mean(0))
        _, a_ck, _ = lab(roi[m, 1:].mean(1).mean(0))
        out.append((a, a_ck - a_fh, b, L))
    return np.array(out)


# ---------- 통계 (표본이 커서 정규 근사로 충분하다) ----------
def rank(x):
    return np.argsort(np.argsort(np.asarray(x, float))) + 1.0


def spearman(x, y):
    rx, ry = rank(x), rank(y)
    r = float(np.corrcoef(rx, ry)[0, 1])
    n = len(x)
    return r, p_from_r(r, n)


def p_from_r(r, n, k=0):
    """상관계수 → 양측 p (Fisher z). k = 통제한 변수 개수."""
    from math import atanh, erfc, sqrt
    if n - k - 3 <= 0 or abs(r) >= 1:
        return float("nan")
    z = atanh(r) * sqrt(n - k - 3)
    return float(erfc(abs(z) / sqrt(2)))


def partial(x, y, covs):
    """covs 를 선형으로 뺀 뒤의 순위상관."""
    X = np.column_stack([np.ones(len(x))] + [rank(c) for c in covs])
    rx, ry = rank(x), rank(y)
    ex = rx - X @ np.linalg.lstsq(X, rx, rcond=None)[0]
    ey = ry - X @ np.linalg.lstsq(X, ry, rcond=None)[0]
    r = float(np.corrcoef(ex, ey)[0, 1])
    return r, p_from_r(r, len(x), k=len(covs))


def auc(score, label):
    """label=1 인 쪽의 score 가 큰 정도. Mann-Whitney U / (n1·n0)."""
    score, label = np.asarray(score, float), np.asarray(label, bool)
    r = rank(score)
    n1, n0 = label.sum(), (~label).sum()
    if n1 == 0 or n0 == 0:
        return float("nan"), float("nan")
    a = (r[label].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)
    # 정규 근사 (동점 무시)
    from math import erfc, sqrt
    sd = sqrt(n1 * n0 * (n1 + n0 + 1) / 12)
    z = (a * n1 * n0 - n1 * n0 / 2) / sd
    return float(a), float(erfc(abs(z) / sqrt(2)))


NAMES = ["원 a* (얼굴 평균)", "보정 a* (볼−이마)", "b* (노란 기)", "L* (밝기)"]
KEYS = ["a_raw", "a_cor", "b_raw", "L_raw"]


def main():
    files = sorted(TR.glob("*.npz"))
    if not files:
        sys.exit(f"트레이스가 없다: {TR}")

    per = {}          # sid -> {state -> [구간, 4]}
    for i, f in enumerate(files):
        sid, state = f.stem.split("_")
        w = features(f)
        if len(w):
            per.setdefault(sid, {})[state] = w
        if (i + 1) % 200 == 0:
            print(f"  …{i + 1}/{len(files)}", flush=True)

    lab_rows = {r["patient_id"]: r for r in csv.DictReader(open(ROOT / "data/raw/mcd_rppg/db.csv"))}
    pairs = {s: v for s, v in per.items() if "before" in v and "after" in v}
    rest = {s: v["before"] for s, v in per.items() if "before" in v}
    print(f"\n사람 {len(per)}명 · 안정 영상 {len(rest)}개 · 운동 전후 짝 {len(pairs)}명")
    print(f"구간 {sum(len(w) for v in per.values() for w in v.values())}개 "
          f"(창 {WIN:.0f}초, {STEP:.0f}초 간격)\n")

    # ---------- 1. 같은 영상 안 흔들림 ----------
    print("## 1. 같은 영상 안, 20초 구간끼리 흔들림 (sd 중앙값 — 작을수록 좋다)")
    for j, name in enumerate(NAMES):
        sds = [w[:, j].std(ddof=1) for v in per.values() for w in v.values() if len(w) > 1]
        print(f"   {name:20s} {np.median(sds):6.3f}   (n={len(sds)} 영상)")

    # ---------- 2. 운동 전후 ----------
    print("\n## 2. 같은 사람 before ↔ after — 운동 후에 오르나")
    from math import comb
    for j, name in enumerate(NAMES):
        d = np.array([np.median(v["after"][:, j]) - np.median(v["before"][:, j]) for v in pairs.values()])
        up, n = int((d > 0).sum()), len(d)
        tail = sum(comb(n, i) for i in range(0, min(up, n - up) + 1)) / 2 ** n
        print(f"   {name:20s} {up}/{n}명 상승 ({up / n * 100:4.1f}%) · 중앙 Δ {np.median(d):+6.3f} · p = {min(1, 2 * tail):.3f}")

    # ---------- 3·4·5. 혈액 지표 ----------
    ids = sorted(i for i in rest if i in lab_rows)
    F = {k: np.array([np.median(rest[i][:, j]) for i in ids]) for j, k in enumerate(KEYS)}
    TARGETS = ["hemoglobin", "glycated_hemoglobin", "cholesterol", "saturation",
               "temperature", "upper_ap", "lower_ap", "bmi", "age", "stress", "pulse"]

    print(f"\n## 3. 혈액·신체 지표와의 순위상관 (안정 영상, n={len(ids)})")
    header = f"   {'지표':22s}" + "".join(f"{n:>22s}" for n in NAMES)
    print(header)
    rows = {}
    for tname in TARGETS:
        y = np.array([float(lab_rows[i][tname]) for i in ids])
        cells, rows[tname] = [], {}
        for k in KEYS:
            r, p = spearman(F[k], y)
            rows[tname][k] = (r, p)
            star = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
            cells.append(f"{r:+.3f}{star:<3s} (p={p:.3f})".rjust(22))
        print(f"   {tname:22s}" + "".join(cells))

    sex = np.array([1.0 if lab_rows[i]["sex"] == "M" else 0.0 for i in ids])
    hb = np.array([float(lab_rows[i]["hemoglobin"]) for i in ids])
    anemic = np.array([hb[n] < (13 if sex[n] else 12) for n in range(len(ids))])

    print(f"\n## 4. 빈혈 판별 (남 <13, 여 <12 g/dL) — 빈혈 {int(anemic.sum())}명 / {len(ids)}명")
    print(f"   {'색 지표':22s}{'AUC':>10s}{'p':>10s}   (0.5 = 동전, 낮으면 창백 쪽이 빈혈)")
    for j, (k, name) in enumerate(zip(KEYS, NAMES)):
        a, p = auc(F[k], anemic)
        print(f"   {name:22s}{a:10.3f}{p:10.3f}")

    print(f"\n## 5. 피부톤(L*)과 성별·나이를 뺀 뒤 헤모글로빈과의 편상관 (n={len(ids)})")
    age = np.array([float(lab_rows[i]["age"]) for i in ids])
    for k, name in zip(KEYS[:3], NAMES[:3]):
        r, p = partial(F[k], hb, [F["L_raw"], sex, age])
        print(f"   {name:22s} ρ = {r:+.3f}  p = {p:.3f}")

    OUT.mkdir(exist_ok=True)
    (OUT / "complexion_594.json").write_text(json.dumps({
        "n_people": len(per), "n_rest": len(ids), "n_pairs": len(pairs),
        "n_anemic": int(anemic.sum()),
        "spearman": {t: {k: rows[t][k] for k in KEYS} for t in TARGETS},
        "auc_anemia": {k: auc(F[k], anemic) for k in KEYS},
        "partial_hb": {k: partial(F[k], hb, [F["L_raw"], sex, age]) for k in KEYS[:3]},
    }, ensure_ascii=False, indent=1))
    np.savez(OUT / "complexion_594_features.npz", ids=np.array(ids), hb=hb, sex=sex, age=age,
             **{k: F[k] for k in KEYS})
    print(f"\n→ {OUT / 'complexion_594.json'}")


main()
