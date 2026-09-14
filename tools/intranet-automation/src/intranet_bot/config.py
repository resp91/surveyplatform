"""YAML 시나리오 파일을 읽어 검증된 설정 객체로 바꾼다."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError

# 액션별로 반드시 있어야 하는 필드와 선택 필드를 한 곳에서 정의한다.
# 여기에 항목을 추가하면 steps.py 의 핸들러와 문서(README)도 같이 맞춰야 한다.
ACTION_SPECS: dict[str, dict[str, tuple[str, ...]]] = {
    "goto":          {"required": ("url",),                "optional": ("wait_until",)},
    "click":         {"required": ("selector",),           "optional": ("nth", "force", "button")},
    "double_click":  {"required": ("selector",),           "optional": ("nth", "force")},
    "fill":          {"required": ("selector", "value"),   "optional": ("nth", "clear_first")},
    "type":          {"required": ("selector", "value"),   "optional": ("nth", "delay_ms", "clear_first")},
    "paste":         {"required": ("selector", "value"),   "optional": ("nth", "clear_first")},
    # 주의: 여기 필드 이름은 COMMON_STEP_FIELDS 와 겹치면 안 된다(겹치면 값이 설명으로 먹힌다).
    "select_option": {"required": ("selector",),           "optional": ("value", "option_label", "index", "nth")},
    "check":         {"required": ("selector",),           "optional": ("nth",)},
    "uncheck":       {"required": ("selector",),           "optional": ("nth",)},
    "press":         {"required": ("key",),                "optional": ("selector", "nth")},
    "upload":        {"required": ("selector", "path"),    "optional": ("nth",)},
    "wait_for":      {"required": ("selector",),           "optional": ("state", "nth")},
    "wait_for_text": {"required": ("text",),               "optional": ("selector",)},
    "wait_for_url":  {"required": ("url",),                "optional": ()},
    "wait":          {"required": ("ms",),                 "optional": ()},
    "switch_frame":  {"required": (),                      "optional": ("name", "url", "selector")},
    "screenshot":    {"required": (),                      "optional": ("path",)},
    "assert_text":   {"required": ("text",),               "optional": ("selector",)},
    "assert_visible":{"required": ("selector",),           "optional": ("nth",)},
    "handle_dialog": {"required": (),                      "optional": ("accept", "prompt_text")},
}

# 모든 액션이 공통으로 받을 수 있는 필드.
COMMON_STEP_FIELDS = ("action", "label", "timeout_ms", "optional", "skip_if_empty")


@dataclass
class Step:
    """시나리오의 단계 하나."""

    action: str
    params: dict[str, Any] = field(default_factory=dict)
    label: str | None = None
    timeout_ms: int | None = None
    optional: bool = False
    skip_if_empty: str | None = None

    def describe(self) -> str:
        if self.label:
            return self.label
        target = self.params.get("selector") or self.params.get("url") or self.params.get("text") or ""
        return f"{self.action} {target}".strip()


@dataclass
class BrowserConfig:
    channel: str | None = None          # "msedge", "chrome" 등. 없으면 번들 크로미움.
    executable_path: str | None = None
    headless: bool = False
    slow_mo_ms: int = 0
    ignore_https_errors: bool = True    # 사내 사설 인증서 대응
    viewport_width: int = 1440
    viewport_height: int = 900
    storage_state: str | None = None    # 로그인 세션 재사용 파일
    downloads_dir: str | None = None
    proxy_server: str | None = None


@dataclass
class LoginConfig:
    url: str
    steps: list[Step] = field(default_factory=list)
    success_selector: str | None = None
    skip_if_success_selector: bool = True   # 이미 로그인 상태면 건너뛴다


@dataclass
class ExcelConfig:
    path: str
    sheet: str | None = None
    header_row: int = 1
    start_row: int = 2
    end_row: int | None = None
    columns: dict[str, str] = field(default_factory=dict)   # 엑셀 헤더명 -> 변수명
    skip_empty_rows: bool = True


@dataclass
class RunConfig:
    on_error: str = "stop"              # stop | continue
    screenshot_on_error: bool = True
    output_dir: str = "./output"
    result_file: str | None = None      # 없으면 타임스탬프로 자동 생성
    checkpoint_file: str = "./output/checkpoint.json"
    delay_between_rows_ms: int = 0


@dataclass
class Scenario:
    name: str
    browser: BrowserConfig
    run: RunConfig
    login: LoginConfig | None
    excel: ExcelConfig | None
    setup: list[Step]
    per_row: list[Step]
    teardown: list[Step]
    vars: dict[str, Any]
    default_timeout_ms: int
    source_path: Path
    base_dir: str | None = None

    @property
    def base_path(self) -> Path:
        """시나리오 안의 상대경로가 기준으로 삼는 폴더."""
        if self.base_dir:
            return (self.source_path.parent / self.base_dir).resolve()
        return self.source_path.parent

    def resolve(self, relative: str) -> Path:
        """상대경로를 base_path 기준 절대경로로 바꾼다."""
        p = Path(relative).expanduser()
        if p.is_absolute():
            return p
        return (self.base_path / p).resolve()


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping or mapping[key] in (None, ""):
        raise ConfigError(f"{where}: '{key}' 항목이 필요합니다.")
    return mapping[key]


def _parse_step(raw: Any, where: str) -> Step:
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: 각 단계는 'action: ...' 형태의 맵이어야 합니다. (받은 값: {raw!r})")

    action = raw.get("action")
    if not action:
        raise ConfigError(f"{where}: 'action' 항목이 필요합니다. 사용 가능: {', '.join(sorted(ACTION_SPECS))}")
    if action not in ACTION_SPECS:
        raise ConfigError(
            f"{where}: 알 수 없는 action '{action}'. 사용 가능: {', '.join(sorted(ACTION_SPECS))}"
        )

    spec = ACTION_SPECS[action]
    allowed = set(spec["required"]) | set(spec["optional"]) | set(COMMON_STEP_FIELDS)
    unknown = set(raw) - allowed
    if unknown:
        raise ConfigError(
            f"{where}: action '{action}' 에서 쓸 수 없는 항목 {sorted(unknown)}. "
            f"사용 가능: {sorted(allowed - {'action'})}"
        )
    for required in spec["required"]:
        if required not in raw:
            raise ConfigError(f"{where}: action '{action}' 에는 '{required}' 항목이 필요합니다.")

    params = {k: v for k, v in raw.items() if k not in COMMON_STEP_FIELDS}
    return Step(
        action=action,
        params=params,
        label=raw.get("label"),
        timeout_ms=raw.get("timeout_ms"),
        optional=bool(raw.get("optional", False)),
        skip_if_empty=raw.get("skip_if_empty"),
    )


def _parse_steps(raw: Any, where: str) -> list[Step]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError(f"{where}: 단계 목록은 리스트여야 합니다.")
    return [_parse_step(item, f"{where}[{i}]") for i, item in enumerate(raw)]


def _parse_browser(raw: dict[str, Any]) -> BrowserConfig:
    viewport = raw.get("viewport") or {}
    return BrowserConfig(
        channel=raw.get("channel"),
        executable_path=raw.get("executable_path"),
        headless=bool(raw.get("headless", False)),
        slow_mo_ms=int(raw.get("slow_mo_ms", 0)),
        ignore_https_errors=bool(raw.get("ignore_https_errors", True)),
        viewport_width=int(viewport.get("width", 1440)),
        viewport_height=int(viewport.get("height", 900)),
        storage_state=raw.get("storage_state"),
        downloads_dir=raw.get("downloads_dir"),
        proxy_server=raw.get("proxy_server"),
    )


def _parse_login(raw: dict[str, Any] | None) -> LoginConfig | None:
    if not raw:
        return None
    return LoginConfig(
        url=_require(raw, "url", "login"),
        steps=_parse_steps(raw.get("steps"), "login.steps"),
        success_selector=raw.get("success_selector"),
        skip_if_success_selector=bool(raw.get("skip_if_success_selector", True)),
    )


def _parse_excel(raw: dict[str, Any] | None) -> ExcelConfig | None:
    if not raw:
        return None
    columns = raw.get("columns") or {}
    if not isinstance(columns, dict):
        raise ConfigError("excel.columns: '엑셀 헤더명: 변수명' 형태의 맵이어야 합니다.")
    header_row = int(raw.get("header_row", 1))
    start_row = int(raw.get("start_row", header_row + 1))
    end_row = raw.get("end_row")
    if end_row is not None and int(end_row) < start_row:
        raise ConfigError(f"excel.end_row({end_row})가 start_row({start_row})보다 작습니다.")
    return ExcelConfig(
        path=_require(raw, "path", "excel"),
        sheet=raw.get("sheet"),
        header_row=header_row,
        start_row=start_row,
        end_row=None if end_row is None else int(end_row),
        columns={str(k): str(v) for k, v in columns.items()},
        skip_empty_rows=bool(raw.get("skip_empty_rows", True)),
    )


def _parse_run(raw: dict[str, Any]) -> RunConfig:
    on_error = str(raw.get("on_error", "stop"))
    if on_error not in ("stop", "continue"):
        raise ConfigError("run.on_error 는 'stop' 또는 'continue' 만 가능합니다.")
    output_dir = str(raw.get("output_dir", "./output"))
    return RunConfig(
        on_error=on_error,
        screenshot_on_error=bool(raw.get("screenshot_on_error", True)),
        output_dir=output_dir,
        result_file=raw.get("result_file"),
        checkpoint_file=str(raw.get("checkpoint_file", f"{output_dir}/checkpoint.json")),
        delay_between_rows_ms=int(raw.get("delay_between_rows_ms", 0)),
    )


def load_scenario(path: str | Path) -> Scenario:
    """YAML 시나리오 파일을 읽어 검증한다."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ConfigError(f"시나리오 파일을 찾을 수 없습니다: {source}")

    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML 문법 오류: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("시나리오 파일의 최상위는 맵이어야 합니다.")

    known_top = {"name", "base_dir", "browser", "run", "login", "excel", "flow", "vars", "defaults"}
    unknown_top = set(raw) - known_top
    if unknown_top:
        raise ConfigError(f"알 수 없는 최상위 항목 {sorted(unknown_top)}. 사용 가능: {sorted(known_top)}")

    flow = raw.get("flow") or {}
    if not isinstance(flow, dict):
        raise ConfigError("flow: 'setup' / 'per_row' / 'teardown' 을 담은 맵이어야 합니다.")
    unknown_flow = set(flow) - {"setup", "per_row", "teardown"}
    if unknown_flow:
        raise ConfigError(f"알 수 없는 flow 항목 {sorted(unknown_flow)}.")

    defaults = raw.get("defaults") or {}
    scenario = Scenario(
        name=str(raw.get("name") or source.stem),
        browser=_parse_browser(raw.get("browser") or {}),
        run=_parse_run(raw.get("run") or {}),
        login=_parse_login(raw.get("login")),
        excel=_parse_excel(raw.get("excel")),
        setup=_parse_steps(flow.get("setup"), "flow.setup"),
        per_row=_parse_steps(flow.get("per_row"), "flow.per_row"),
        teardown=_parse_steps(flow.get("teardown"), "flow.teardown"),
        vars=dict(raw.get("vars") or {}),
        default_timeout_ms=int(defaults.get("timeout_ms", 15000)),
        source_path=source,
        base_dir=raw.get("base_dir"),
    )

    if not scenario.setup and not scenario.per_row and not scenario.login:
        raise ConfigError("실행할 것이 없습니다. login 또는 flow.setup / flow.per_row 중 하나는 채워야 합니다.")
    if scenario.per_row and not scenario.excel:
        raise ConfigError("flow.per_row 를 쓰려면 excel 설정이 필요합니다.")
    return scenario
