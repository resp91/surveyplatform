"""아이디/비밀번호 같은 비밀값을 시나리오 밖에서 읽어오고, 로그에서 가린다."""

from __future__ import annotations

import os
from pathlib import Path

from .errors import SecretError


def load_env_file(path: str | Path) -> dict[str, str]:
    """KEY=VALUE 형식의 .env 파일을 읽는다. 없으면 빈 맵.

    따옴표로 감싼 값과 '#' 주석 줄을 지원한다.
    """
    values: dict[str, str] = {}
    p = Path(path).expanduser()
    if not p.is_file():
        return values
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key.strip()] = value
    return values


class SecretStore:
    """.env 파일과 환경변수에서 비밀값을 찾고, 사용된 값을 기억해 로그에서 마스킹한다.

    환경변수가 .env 보다 우선한다(운영 서버에서 파일 없이 주입하는 경우 대비).
    """

    MASK = "********"

    def __init__(self, env_file: str | Path | None = None):
        self._file_values = load_env_file(env_file) if env_file else {}
        self._used: set[str] = set()

    def get(self, key: str) -> str:
        value = os.environ.get(key) or self._file_values.get(key)
        if value is None or value == "":
            raise SecretError(
                f"비밀값 '{key}' 를 찾을 수 없습니다. .env 파일에 '{key}=...' 를 넣거나 "
                f"환경변수로 지정하세요."
            )
        self._used.add(value)
        return value

    def has(self, key: str) -> bool:
        return bool(os.environ.get(key) or self._file_values.get(key))

    def mask(self, text: str) -> str:
        """지금까지 사용된 비밀값을 문자열에서 가린다."""
        if not text:
            return text
        for value in self._used:
            if value and value in text:
                text = text.replace(value, self.MASK)
        return text
