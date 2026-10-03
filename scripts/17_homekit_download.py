"""Homekit2020 다운로드 (Synapse 통제 접근 — 승인 후에만 된다).

    pip install synapseclient
    set SYNAPSE_AUTH_TOKEN=...        # Synapse > Account Settings > Personal Access Token
    python scripts/17_homekit_download.py

신청 절차는 docs/HOMEKIT.md. 토큰은 **환경변수로만** 받는다. 파일에 쓰지 말 것.
데이터 이용 조건상 원자료·중간 산출물을 저장소에 올리면 안 된다
(data/raw/* 와 outputs/ 는 .gitignore 에 있다).
"""
import argparse
import os
import sys
import zipfile
from pathlib import Path

from _bootstrap import banner, setup

ZIP_ID = "syn51476306"              # homekit2020-1.0.zip
PROJECT_ID = "syn22803188"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default="data/raw/homekit2020")
    args = ap.parse_args()

    setup()
    root = Path(__file__).resolve().parents[1]
    dest = root / args.dest
    dest.mkdir(parents=True, exist_ok=True)
    banner("Homekit2020 다운로드 -> {}".format(dest))

    token = os.environ.get("SYNAPSE_AUTH_TOKEN")
    if not token:
        sys.exit("SYNAPSE_AUTH_TOKEN 환경변수가 없다. docs/HOMEKIT.md 참고.")
    try:
        import synapseclient
    except ImportError:
        sys.exit("pip install synapseclient")

    syn = synapseclient.Synapse()
    syn.login(authToken=token, silent=True)
    ent = syn.get(ZIP_ID, downloadLocation=str(dest))
    zpath = Path(ent.path)
    print("  받음: {} ({:.1f} MB)".format(zpath.name, zpath.stat().st_size / 1e6))

    with zipfile.ZipFile(zpath) as z:
        z.extractall(dest)
    print("  압축 해제 완료. 다음: python scripts/18_homekit_audit.py")
    print("  인용: doi.org/10.7303/{}".format(PROJECT_ID))


if __name__ == "__main__":
    main()
