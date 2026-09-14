#!/usr/bin/env python3
"""설치 없이 바로 실행할 수 있는 진입 스크립트.

    python run.py run --dry-run
    python run.py validate

'pip install -e .' 로 설치했다면 'intranet-bot' 명령을 대신 써도 됩니다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from intranet_bot.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
