import sys
from pathlib import Path

# 설치 없이 저장소에서 바로 테스트할 수 있도록 src 를 경로에 넣는다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
