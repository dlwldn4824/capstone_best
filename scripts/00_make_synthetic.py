"""합성 E4 데이터셋 생성 (PhysioNet 다운로드 전 파이프라인 검증용).

    python scripts/00_make_synthetic.py

주의: 여기서 나온 성능 수치는 연구 결과가 아니다. src/nesy/synthetic.py 상단
설명을 반드시 읽을 것.
"""
import argparse
from pathlib import Path

from _bootstrap import banner, setup

from nesy import synthetic


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/raw/SYNTHETIC")
    ap.add_argument("--n-v1", type=int, default=8)
    ap.add_argument("--n-v2", type=int, default=6)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    cfg, proto = setup()
    root = Path(__file__).resolve().parents[1]
    out = root / args.out

    banner("합성 데이터 생성 -> {}".format(out))
    subjects, made = synthetic.make_dataset(out, proto, args.n_v1, args.n_v2,
                                            args.seed)
    print("피험자 {}명, 세션 {}개 생성".format(len(subjects), len(made)))
    print("  v1(S*): {}".format([s for s in subjects if s.startswith("S")]))
    print("  v2(f*): {}".format([s for s in subjects if s.startswith("f")]))
    print("\n다음 단계:")
    print("  configs/config.yaml 의 paths.raw 를 '{}' 로 바꾸고".format(args.out))
    print("  python scripts/01_audit.py")


if __name__ == "__main__":
    main()
