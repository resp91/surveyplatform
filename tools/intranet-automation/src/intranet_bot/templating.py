"""'{{ row.거래처 }}' 같은 치환식을 실제 값으로 바꾼다."""

from __future__ import annotations

import re
from datetime import date, datetime, time
from typing import Any

from .errors import ConfigError, SecretError
from .secrets import SecretStore

PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z_][\w]*)\.([^\s}]+?)\s*\}\}|\{\{\s*(row_index)\s*\}\}")

_NOW_FIELDS = {
    "date": "%Y-%m-%d",
    "date_compact": "%Y%m%d",
    "time": "%H:%M:%S",
    "datetime": "%Y-%m-%d %H:%M:%S",
    "year": "%Y",
    "month": "%m",
    "day": "%d",
}


class Context:
    """한 번의 실행(또는 한 행)에 유효한 치환 값 모음.

    지원하는 이름공간:
      {{ row.<변수명> }}   엑셀 현재 행
      {{ var.<이름> }}     시나리오 vars 블록
      {{ secret.<KEY> }}   .env / 환경변수 (로그에서 마스킹됨)
      {{ env.<KEY> }}      환경변수 (마스킹 안 함)
      {{ now.date }}       실행 시각
      {{ row_index }}      엑셀 행 번호
    """

    def __init__(
        self,
        secrets: SecretStore,
        variables: dict[str, Any] | None = None,
        row: dict[str, Any] | None = None,
        row_index: int | None = None,
        now: datetime | None = None,
    ):
        self.secrets = secrets
        self.variables = variables or {}
        self.row = row or {}
        self.row_index = row_index
        self.now = now or datetime.now()

    def with_row(self, row: dict[str, Any], row_index: int) -> "Context":
        return Context(self.secrets, self.variables, row, row_index, self.now)

    def _lookup(self, namespace: str, key: str) -> str:
        if namespace == "row":
            if key not in self.row:
                available = ", ".join(sorted(self.row)) or "(없음)"
                raise ConfigError(f"엑셀 행에 '{key}' 변수가 없습니다. 사용 가능: {available}")
            return _stringify(self.row[key])
        if namespace == "var":
            if key not in self.variables:
                raise ConfigError(f"vars 에 '{key}' 가 없습니다.")
            return _stringify(self.variables[key])
        if namespace == "secret":
            return self.secrets.get(key)
        if namespace == "env":
            import os

            value = os.environ.get(key)
            if value is None:
                raise SecretError(f"환경변수 '{key}' 가 설정되지 않았습니다.")
            return value
        if namespace == "now":
            if key not in _NOW_FIELDS:
                raise ConfigError(f"now.{key} 는 지원하지 않습니다. 사용 가능: {', '.join(_NOW_FIELDS)}")
            return self.now.strftime(_NOW_FIELDS[key])
        raise ConfigError(
            f"알 수 없는 치환 이름공간 '{namespace}'. 사용 가능: row, var, secret, env, now"
        )

    def render(self, value: Any) -> Any:
        """문자열/리스트/맵 안의 모든 치환식을 재귀적으로 치환한다."""
        if isinstance(value, str):
            return PLACEHOLDER.sub(self._replace, value)
        if isinstance(value, list):
            return [self.render(v) for v in value]
        if isinstance(value, dict):
            return {k: self.render(v) for k, v in value.items()}
        return value

    def _replace(self, match: re.Match[str]) -> str:
        if match.group(3):  # {{ row_index }}
            return "" if self.row_index is None else str(self.row_index)
        return self._lookup(match.group(1), match.group(2))


def _stringify(value: Any) -> str:
    """엑셀 셀 값을 화면 입력용 문자열로 바꾼다."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Y" if value else "N"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime):
        # 시각이 0시 0분이면 날짜만 쓰는 편이 사내 양식과 맞는 경우가 많다.
        if (value.hour, value.minute, value.second) == (0, 0, 0):
            return value.strftime("%Y-%m-%d")
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    return str(value)
