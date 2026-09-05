"""모든 스크립트 공통: src 를 import 경로에 추가하고 설정을 읽는다."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nesy.config import load_config, load_protocol  # noqa: E402


def setup(config="configs/config.yaml"):
    cfg = load_config(config)
    proto = load_protocol()
    return cfg, proto


def banner(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)
