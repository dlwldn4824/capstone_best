"""Day 1 — PhysioNet 데이터 다운로드.

Wearable Device Dataset from Induced Stress and Structured Exercise Sessions
v1.0.1 (Hongn et al., Sci Data 2025). Open Access — 계정 불필요.
압축 약 70 MB / 압축 해제 약 247 MB.

    python scripts/00_download.py

wget 이 있으면 그것을 쓰고, 없으면 urllib 로 ZIP 을 받는다.
"""
import argparse
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from _bootstrap import banner, setup

SLUG = "wearable-device-dataset"
VERSION = "1.0.1"
ZIP_URL = ("https://physionet.org/static/published-projects/{s}/"
           "wearable-device-dataset-from-induced-stress-and-structured-"
           "exercise-sessions-{v}.zip".format(s=SLUG, v=VERSION))
WGET_BASE = "https://physionet.org/files/{s}/{v}/".format(s=SLUG, v=VERSION)


def _progress(count, block, total):
    if total > 0:
        pct = min(100.0, count * block * 100.0 / total)
        sys.stdout.write("\r  {:5.1f}%  ({:.1f} MB)".format(
            pct, count * block / 1e6))
        sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default="data/raw")
    ap.add_argument("--method", default="auto", choices=["auto", "zip", "wget"])
    args = ap.parse_args()

    cfg, _ = setup()
    root = Path(__file__).resolve().parents[1]
    dest = root / args.dest
    dest.mkdir(parents=True, exist_ok=True)

    banner("PhysioNet 다운로드 -> {}".format(dest))

    use_wget = (args.method == "wget"
                or (args.method == "auto" and shutil.which("wget")))
    if use_wget:
        cmd = ["wget", "-r", "-N", "-c", "-np", "-nH", "--cut-dirs=1",
               "-P", str(dest), WGET_BASE]
        print("  $ " + " ".join(cmd))
        subprocess.run(cmd, check=True)
    else:
        zpath = dest / "wearable-device-dataset.zip"
        if not zpath.exists():
            print("  ZIP 다운로드: {}".format(ZIP_URL))
            urllib.request.urlretrieve(ZIP_URL, zpath, _progress)
            print()
        print("  압축 해제 중...")
        with zipfile.ZipFile(zpath) as z:
            z.extractall(dest)

    print("\n받은 경로를 확인하고 configs/config.yaml 의 paths.raw 를 맞추세요.")
    print("현재 설정: {}".format(cfg["paths"]["raw"]))
    print("\n하위에 STRESS / AEROBIC / ANAEROBIC 폴더가 보이는 디렉터리여야 합니다:")
    for p in sorted(dest.rglob("STRESS"))[:3]:
        print("  후보: {}".format(p.parent))
    print("\n다음: python scripts/01_audit.py")


if __name__ == "__main__":
    main()
