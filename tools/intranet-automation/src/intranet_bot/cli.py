"""명령줄 진입점."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import load_scenario
from .errors import BotError
from .excel import ExcelSource
from .runner import RunOptions, Runner
from .secrets import SecretStore

logger = logging.getLogger("intranet_bot")


def _setup_logging(verbose: bool, log_file: Path | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-s", "--scenario", default="config/scenario.yaml", help="시나리오 YAML 경로")
    parser.add_argument("-e", "--env-file", default="config/.env", help="아이디/비밀번호가 담긴 .env 경로")
    parser.add_argument("-v", "--verbose", action="store_true", help="자세한 로그 출력")
    parser.add_argument("--log-file", help="로그를 파일로도 남길 경로")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="intranet-bot",
        description="인트라넷 로그인 -> 지정된 순서 클릭 -> 엑셀 내용 입력을 자동으로 반복합니다.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="시나리오를 실행합니다")
    _add_common_args(run)
    run.add_argument("--dry-run", action="store_true", help="브라우저 없이 시나리오와 엑셀만 점검합니다")
    run.add_argument("--headless", dest="headless", action="store_true", help="브라우저 창 없이 실행")
    run.add_argument("--headed", dest="headless", action="store_false", help="브라우저 창을 띄워 실행")
    run.set_defaults(headless=None)
    run.add_argument("--rows", help="처리할 엑셀 행 (예: 2-10 또는 3,5,7)")
    run.add_argument("--limit", type=int, help="앞에서부터 N행만 처리")
    run.add_argument("--resume", action="store_true", help="지난번에 끝낸 행은 건너뛰고 이어서 실행")
    run.add_argument("--keep-open", action="store_true", help="끝나도 브라우저를 닫지 않음")

    validate = sub.add_parser("validate", help="시나리오 문법과 비밀값 설정만 점검합니다")
    _add_common_args(validate)

    rows = sub.add_parser("rows", help="엑셀에서 읽어올 내용을 미리 봅니다")
    _add_common_args(rows)
    rows.add_argument("--limit", type=int, default=10, help="미리 볼 행 수 (기본 10)")

    codegen = sub.add_parser("record", help="브라우저를 켜서 클릭 순서와 선택자를 기록합니다")
    codegen.add_argument("url", help="기록을 시작할 인트라넷 주소")
    codegen.add_argument("--channel", help="사용할 브라우저 (msedge, chrome 등)")
    return parser


def _resolve_env_file(raw: str, scenario) -> Path | None:
    """현재 위치 기준으로 먼저 찾고, 없으면 시나리오 파일 옆에서 찾는다."""
    candidates = [Path(raw).expanduser()]
    if not candidates[0].is_absolute():
        candidates.append((scenario.source_path.parent / raw).resolve())
        candidates.append((scenario.source_path.parent.parent / raw).resolve())
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _load(args: argparse.Namespace):
    scenario = load_scenario(args.scenario)
    env_file = _resolve_env_file(args.env_file, scenario)
    if env_file:
        logger.debug("비밀값 파일: %s", env_file)
    return scenario, SecretStore(env_file)


def cmd_run(args: argparse.Namespace) -> int:
    scenario, secrets = _load(args)
    options = RunOptions(
        dry_run=args.dry_run,
        headless=args.headless,
        rows=args.rows,
        limit=args.limit,
        resume=args.resume,
        keep_open=args.keep_open,
    )
    summary = Runner(scenario, secrets, options).run()
    print()
    print(summary.text_report())
    return 1 if (summary.failed_count or summary.aborted_reason) else 0


def cmd_validate(args: argparse.Namespace) -> int:
    scenario, secrets = _load(args)
    logger.info("시나리오 '%s' 문법 확인 완료", scenario.name)

    missing = [key for key in _referenced_secrets(scenario) if not secrets.has(key)]
    if missing:
        logger.error("다음 비밀값이 설정되지 않았습니다: %s", ", ".join(missing))
        logger.error(".env 파일에 'KEY=값' 형태로 넣어 주세요.")
        return 1

    if scenario.excel:
        path = scenario.resolve(scenario.excel.path)
        rows = ExcelSource(scenario.excel, path).load()
        logger.info("엑셀 확인 완료: %s (%d행)", path, len(rows))
    logger.info("점검 결과 이상 없습니다.")
    return 0


def cmd_rows(args: argparse.Namespace) -> int:
    scenario, _ = _load(args)
    if not scenario.excel:
        logger.error("이 시나리오에는 excel 설정이 없습니다.")
        return 1
    rows = ExcelSource(scenario.excel, scenario.resolve(scenario.excel.path)).load()
    logger.info("총 %d행 중 앞 %d행:", len(rows), min(args.limit, len(rows)))
    for row in rows[: args.limit]:
        detail = ", ".join(f"{k}={v!r}" for k, v in row.values.items())
        print(f"  {row.row_number}행: {detail}")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    """Playwright 의 코드 기록기를 띄워 실제 클릭을 선택자로 받아 적게 한다."""
    import subprocess

    command = [sys.executable, "-m", "playwright", "codegen"]
    if args.channel:
        command += ["--channel", args.channel]
    command.append(args.url)
    print("브라우저에서 실제로 클릭해 보세요. 창에 뜨는 선택자를 시나리오에 옮겨 적으면 됩니다.")
    return subprocess.call(command)


def _referenced_secrets(scenario) -> list[str]:
    """시나리오 안에서 참조한 {{ secret.KEY }} 목록을 모은다."""
    import re

    pattern = re.compile(r"\{\{\s*secret\.([^\s}]+)\s*\}\}")
    found: list[str] = []
    groups = [scenario.setup, scenario.per_row, scenario.teardown]
    if scenario.login:
        groups.append(scenario.login.steps)
    for steps in groups:
        for step in steps:
            for value in step.params.values():
                for key in pattern.findall(str(value)):
                    if key not in found:
                        found.append(key)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(getattr(args, "verbose", False),
                   Path(args.log_file) if getattr(args, "log_file", None) else None)

    handlers = {"run": cmd_run, "validate": cmd_validate, "rows": cmd_rows, "record": cmd_record}
    try:
        return handlers[args.command](args)
    except BotError as exc:
        logger.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        logger.warning("사용자가 중단했습니다. --resume 으로 이어서 실행할 수 있습니다.")
        return 130
