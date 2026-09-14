"""브라우저를 열고 로그인 -> 클릭 순서 -> 엑셀 행 입력을 실행한다."""

from __future__ import annotations

import csv
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .config import Scenario, Step
from .errors import BotError, StepError
from .excel import ExcelRow, ExcelSource
from .secrets import SecretStore
from .steps import StepExecutor
from .templating import Context

logger = logging.getLogger(__name__)


@dataclass
class RowResult:
    row_number: int
    status: str                 # ok | failed | skipped
    message: str = ""


@dataclass
class RunSummary:
    scenario: str
    started_at: datetime
    finished_at: datetime | None = None
    results: list[RowResult] = field(default_factory=list)
    aborted_reason: str | None = None

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.status == "ok")

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if r.status == "failed")

    @property
    def skipped_count(self) -> int:
        return sum(1 for r in self.results if r.status == "skipped")

    def text_report(self) -> str:
        lines = [
            f"시나리오: {self.scenario}",
            f"성공 {self.ok_count}건 / 실패 {self.failed_count}건 / 건너뜀 {self.skipped_count}건",
        ]
        for result in self.results:
            if result.status != "ok":
                lines.append(f"  - {result.row_number}행 [{result.status}] {result.message}")
        if self.aborted_reason:
            lines.append(f"중단 사유: {self.aborted_reason}")
        return "\n".join(lines)


@dataclass
class RunOptions:
    dry_run: bool = False
    headless: bool | None = None      # None 이면 시나리오 설정을 따른다
    rows: str | None = None           # "2-10", "3,5,7" 형태
    limit: int | None = None
    resume: bool = False
    keep_open: bool = False           # 작업 후 브라우저를 닫지 않는다(디버깅용)


def parse_row_filter(spec: str | None) -> set[int] | None:
    """'2-10,15' 같은 문자열을 행 번호 집합으로 바꾼다. None 이면 전체."""
    if not spec:
        return None
    wanted: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start, _, end = chunk.partition("-")
            try:
                first, last = int(start), int(end)
            except ValueError as exc:
                raise BotError(f"--rows 값을 이해할 수 없습니다: '{chunk}'") from exc
            if last < first:
                raise BotError(f"--rows 범위가 거꾸로입니다: '{chunk}'")
            wanted.update(range(first, last + 1))
        else:
            try:
                wanted.add(int(chunk))
            except ValueError as exc:
                raise BotError(f"--rows 값을 이해할 수 없습니다: '{chunk}'") from exc
    return wanted or None


class Checkpoint:
    """중단된 작업을 이어서 할 수 있도록 완료된 행 번호를 저장한다."""

    def __init__(self, path: Path, scenario_name: str):
        self.path = path
        self.scenario_name = scenario_name
        self.done: set[int] = set()

    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("이어하기 파일을 읽지 못해 처음부터 실행합니다: %s", self.path)
            return
        if data.get("scenario") != self.scenario_name:
            logger.warning("이어하기 파일이 다른 시나리오의 것이라 무시합니다.")
            return
        self.done = {int(n) for n in data.get("done", [])}

    def mark(self, row_number: int) -> None:
        self.done.add(row_number)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "scenario": self.scenario_name,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "done": sorted(self.done),
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def clear(self) -> None:
        self.done.clear()
        if self.path.is_file():
            self.path.unlink()


class Runner:
    def __init__(self, scenario: Scenario, secrets: SecretStore, options: RunOptions | None = None):
        self.scenario = scenario
        self.secrets = secrets
        self.options = options or RunOptions()
        self.output_dir = scenario.resolve(scenario.run.output_dir)
        self.summary = RunSummary(scenario=scenario.name, started_at=datetime.now())

    # ------------------------------------------------------------- 진입점
    def run(self) -> RunSummary:
        rows = self._select_rows()
        if self.options.dry_run:
            self._dry_run(rows)
        else:
            self._live_run(rows)
        self.summary.finished_at = datetime.now()
        self._write_result_file()
        return self.summary

    # ------------------------------------------------------------ 행 선택
    def _select_rows(self) -> list[ExcelRow]:
        if not self.scenario.excel:
            # 엑셀 없이 클릭 순서만 자동화하는 경우: 가상의 1회 실행.
            return [ExcelRow(row_number=0, values={})]

        source = ExcelSource(self.scenario.excel, self.scenario.resolve(self.scenario.excel.path))
        rows = source.load()

        wanted = parse_row_filter(self.options.rows)
        if wanted is not None:
            rows = [r for r in rows if r.row_number in wanted]

        if self.options.resume:
            checkpoint = self._checkpoint()
            checkpoint.load()
            before = len(rows)
            rows = [r for r in rows if r.row_number not in checkpoint.done]
            if before != len(rows):
                logger.info("이어하기: 이미 끝난 %d행을 건너뜁니다.", before - len(rows))

        if self.options.limit is not None:
            rows = rows[: self.options.limit]
        return rows

    def _checkpoint(self) -> Checkpoint:
        return Checkpoint(self.scenario.resolve(self.scenario.run.checkpoint_file), self.scenario.name)

    # ---------------------------------------------------------- 모의 실행
    def _dry_run(self, rows: list[ExcelRow]) -> None:
        """브라우저 없이 시나리오와 엑셀을 검증하고 실행 계획을 보여준다."""
        logger.info("=== 모의 실행(--dry-run): 브라우저를 열지 않습니다 ===")
        base = Context(self.secrets, self.scenario.vars)

        if self.scenario.login:
            logger.info("[로그인] %s", self.scenario.login.url)
            self._preview_steps(self.scenario.login.steps, base)
        if self.scenario.setup:
            logger.info("[사전 작업]")
            self._preview_steps(self.scenario.setup, base)

        logger.info("[처리 대상] %d행", len(rows))
        for row in rows:
            context = base.with_row(row.values, row.row_number)
            label = f"{row.row_number}행" if row.row_number else "단일 실행"
            logger.info("--- %s ---", label)
            self._preview_steps(self.scenario.per_row, context)
            self.summary.results.append(RowResult(row.row_number, "skipped", "모의 실행"))

        if self.scenario.teardown:
            logger.info("[마무리 작업]")
            self._preview_steps(self.scenario.teardown, base)

    def _preview_steps(self, steps: Iterable[Step], context: Context) -> None:
        for index, step in enumerate(steps):
            try:
                if step.skip_if_empty and not str(context.render("{{ " + step.skip_if_empty + " }}")).strip():
                    logger.info("  [%02d] %s -> 건너뜀 (%s 가 비어 있음)",
                                index + 1, step.action, step.skip_if_empty)
                    continue
                rendered = context.render(step.params)
            except BotError as exc:
                logger.error("  [%02d] %s -> 치환 실패: %s", index + 1, step.describe(), exc)
                self.summary.aborted_reason = str(exc)
                continue
            detail = ", ".join(f"{k}={self.secrets.mask(str(v))}" for k, v in rendered.items())
            logger.info("  [%02d] %s(%s)", index + 1, step.action, detail)

    # ---------------------------------------------------------- 실제 실행
    def _live_run(self, rows: list[ExcelRow]) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - 설치 안내용
            raise BotError(
                "playwright 가 필요합니다. 'pip install -r requirements.txt' 후 "
                "'python -m playwright install chromium' 을 실행하세요."
            ) from exc

        browser_config = self.scenario.browser
        headless = self.options.headless if self.options.headless is not None else browser_config.headless
        self.output_dir.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as playwright:
            launch_args: dict[str, Any] = {"headless": headless, "slow_mo": browser_config.slow_mo_ms}
            if browser_config.channel:
                launch_args["channel"] = browser_config.channel
            if browser_config.executable_path:
                launch_args["executable_path"] = browser_config.executable_path
            if browser_config.proxy_server:
                launch_args["proxy"] = {"server": browser_config.proxy_server}

            browser = playwright.chromium.launch(**launch_args)
            context_args: dict[str, Any] = {
                "ignore_https_errors": browser_config.ignore_https_errors,
                "viewport": {"width": browser_config.viewport_width, "height": browser_config.viewport_height},
                "accept_downloads": True,
            }
            if browser_config.downloads_dir:
                self.scenario.resolve(browser_config.downloads_dir).mkdir(parents=True, exist_ok=True)
            state_path = self._storage_state_path()
            if state_path and state_path.is_file():
                context_args["storage_state"] = str(state_path)
                logger.info("저장된 로그인 세션을 사용합니다: %s", state_path)

            browser_context = browser.new_context(**context_args)
            try:
                browser_context.grant_permissions(["clipboard-read", "clipboard-write"])
            except Exception:
                logger.debug("클립보드 권한을 부여하지 못했습니다(붙여넣기는 직접 입력으로 대체됩니다).")

            page = browser_context.new_page()
            page.set_default_timeout(self.scenario.default_timeout_ms)
            executor = StepExecutor(page, self.output_dir, self.scenario.default_timeout_ms, self.secrets)
            base = Context(self.secrets, self.scenario.vars)

            try:
                self._do_login(executor, base)
                if state_path:
                    browser_context.storage_state(path=str(state_path))
                self._run_steps(executor, self.scenario.setup, base, "사전 작업")
                self._process_rows(executor, rows, base)
                self._run_steps(executor, self.scenario.teardown, base, "마무리 작업")
            except BotError as exc:
                self.summary.aborted_reason = self.secrets.mask(str(exc))
                self._capture_failure(page, "aborted")
                logger.error("실행을 중단했습니다: %s", self.summary.aborted_reason)
            finally:
                if self.options.keep_open and not headless:
                    logger.info("브라우저를 열어 둡니다. 확인 후 Enter 를 누르세요.")
                    try:
                        input()
                    except EOFError:
                        pass
                browser_context.close()
                browser.close()

    def _storage_state_path(self) -> Path | None:
        if not self.scenario.browser.storage_state:
            return None
        path = self.scenario.resolve(self.scenario.browser.storage_state)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    # -------------------------------------------------------------- 로그인
    def _do_login(self, executor: StepExecutor, context: Context) -> None:
        login = self.scenario.login
        if not login:
            return
        logger.info("[로그인] %s", login.url)
        executor.page.goto(login.url, timeout=self.scenario.default_timeout_ms, wait_until="load")

        if login.success_selector and login.skip_if_success_selector:
            # 저장된 세션으로 이미 로그인돼 있으면 로그인 단계를 건너뛴다.
            if executor.page.locator(login.success_selector).first.is_visible(timeout=2000):
                logger.info("이미 로그인된 상태라 로그인 단계를 건너뜁니다.")
                return

        self._run_steps(executor, login.steps, context, "로그인")

        if login.success_selector:
            try:
                executor.page.locator(login.success_selector).first.wait_for(
                    state="visible", timeout=self.scenario.default_timeout_ms
                )
            except Exception as exc:
                self._capture_failure(executor.page, "login-failed")
                raise BotError(
                    f"로그인 확인에 실패했습니다. success_selector('{login.success_selector}')가 "
                    f"나타나지 않았습니다. 아이디/비밀번호 또는 선택자를 확인하세요."
                ) from exc
        logger.info("로그인 완료")

    # ------------------------------------------------------------ 행 처리
    def _process_rows(self, executor: StepExecutor, rows: list[ExcelRow], base: Context) -> None:
        if not self.scenario.per_row:
            return
        checkpoint = self._checkpoint()
        if self.options.resume:
            checkpoint.load()

        total = len(rows)
        for position, row in enumerate(rows, start=1):
            label = f"{row.row_number}행" if row.row_number else "단일 실행"
            logger.info("[%d/%d] %s 처리", position, total, label)
            context = base.with_row(row.values, row.row_number)
            try:
                self._run_steps(executor, self.scenario.per_row, context, label)
            except StepError as exc:
                message = f"{exc.step_label or ''} 단계 실패: {exc}".strip()
                logger.error("  실패: %s", message)
                self.summary.results.append(RowResult(row.row_number, "failed", message))
                self._capture_failure(executor.page, f"row-{row.row_number}")
                if self.scenario.run.on_error == "stop":
                    raise BotError(f"{label}에서 중단했습니다. ({message})") from exc
                continue
            except BotError as exc:
                self.summary.results.append(RowResult(row.row_number, "failed", self.secrets.mask(str(exc))))
                raise

            self.summary.results.append(RowResult(row.row_number, "ok"))
            checkpoint.mark(row.row_number)
            if self.scenario.run.delay_between_rows_ms:
                time.sleep(self.scenario.run.delay_between_rows_ms / 1000)

    def _run_steps(self, executor: StepExecutor, steps: Iterable[Step], context: Context, where: str) -> None:
        for index, step in enumerate(steps):
            executor.execute(step, context, index)

    # -------------------------------------------------------------- 기록
    def _capture_failure(self, page: Any, tag: str) -> None:
        if not self.scenario.run.screenshot_on_error:
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        base = self.output_dir / "errors"
        base.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(base / f"{tag}-{stamp}.png"), full_page=True)
            (base / f"{tag}-{stamp}.html").write_text(page.content(), encoding="utf-8")
            logger.info("  오류 화면을 저장했습니다: %s", base / f"{tag}-{stamp}.png")
        except Exception:
            logger.debug("오류 화면 저장에 실패했습니다.", exc_info=True)

    def _write_result_file(self) -> None:
        if not self.summary.results:
            return
        name = self.scenario.run.result_file or (
            f"result-{self.summary.started_at.strftime('%Y%m%d-%H%M%S')}.csv"
        )
        # 파일 이름만 주면 output_dir 아래에, 경로를 주면 그 경로에 저장한다.
        path = self.scenario.resolve(name) if "/" in name else self.output_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        # 엑셀에서 바로 열리도록 BOM 을 붙인다(한글 깨짐 방지).
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["행번호", "상태", "메시지"])
            for result in self.summary.results:
                writer.writerow([result.row_number, result.status, result.message])
        logger.info("실행 결과를 저장했습니다: %s", path)
