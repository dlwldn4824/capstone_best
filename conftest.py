"""pytest 진입 시 src/ 를 import 경로에 넣는다.

Exp 0(`wesad_phase1`)은 원래 `pip install -e .` 를 전제로 하고,
Exp 1(`nesy`)은 테스트 파일이 직접 경로를 넣는다. 두 스위트를 한 저장소에서
같이 돌리려면 진입점이 하나 필요하다.

    python -m pytest tests -q     # 둘 다 실행됨
"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
