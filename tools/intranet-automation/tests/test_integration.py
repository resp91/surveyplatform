"""실제 브라우저로 로그인 -> 클릭 -> 엑셀 입력 전체 흐름을 검증한다.

테스트용 가짜 인트라넷(tests/fake_intranet)을 로컬 서버로 띄워 사용한다.
Playwright 브라우저가 설치돼 있지 않으면 통째로 건너뛴다.
"""

from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

import pytest
from openpyxl import Workbook

from intranet_bot.config import load_scenario
from intranet_bot.runner import RunOptions, Runner
from intranet_bot.secrets import SecretStore

playwright_api = pytest.importorskip("playwright.sync_api")

SITE_DIR = Path(__file__).parent / "fake_intranet"


@pytest.fixture(scope="module")
def site_url():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE_DIR))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _find_chromium() -> str | None:
    """설치된 크로미움을 찾는다.

    playwright 패키지 버전과 내려받은 브라우저 빌드 번호가 어긋난 환경
    (CI 이미지 등)에서는 기본 경로 대신 실제 실행 파일을 직접 지정해야 한다.
    반환값 None 은 '기본 경로로 실행 가능'을 뜻한다.
    """
    with playwright_api.sync_playwright() as p:
        try:
            p.chromium.launch(headless=True).close()
            return None
        except Exception:
            pass
        for candidate in sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"), reverse=True):
            try:
                p.chromium.launch(headless=True, executable_path=str(candidate)).close()
                return str(candidate)
            except Exception:
                continue
    pytest.skip("Playwright 크로미움을 찾을 수 없습니다. 'python -m playwright install chromium' 을 실행하세요.")


@pytest.fixture(scope="module")
def chromium_executable():
    return _find_chromium()


@pytest.fixture
def project(tmp_path, site_url, chromium_executable):
    book = tmp_path / "입력데이터.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["거래처명", "금액", "비고"])
    sheet.append(["가나상사", 1500000, "정기계약"])
    sheet.append(["다라물산", 230000, None])
    workbook.save(book)

    (tmp_path / ".env").write_text("INTRANET_ID=hong\nINTRANET_PW=secret1234\n", encoding="utf-8")

    scenario = tmp_path / "scenario.yaml"
    executable_line = (
        f'  executable_path: "{chromium_executable}"' if chromium_executable else ""
    )
    scenario.write_text(
        f"""
name: 통합테스트
browser:
  headless: true
{executable_line}
defaults:
  timeout_ms: 10000
run:
  on_error: stop
  output_dir: "./output"
vars:
  부서: "영업1팀"
login:
  url: "{site_url}/index.html"
  success_selector: "#gnb"
  steps:
    - action: fill
      selector: "#userId"
      value: "{{{{ secret.INTRANET_ID }}}}"
    - action: fill
      selector: "#userPw"
      value: "{{{{ secret.INTRANET_PW }}}}"
    - action: click
      selector: "button[type=submit]"
excel:
  path: "./입력데이터.xlsx"
  columns:
    거래처명: partner
    금액: amount
    비고: note
flow:
  per_row:
    - action: goto
      url: "{site_url}/form.html"
    - action: switch_frame
      selector: "iframe#contentFrame"
    - action: fill
      selector: "#partnerName"
      value: "{{{{ row.partner }}}}"
    - action: type
      selector: "#amount"
      value: "{{{{ row.amount }}}}"
    - action: select_option
      selector: "#deptCode"
      option_label: "{{{{ var.부서 }}}}"
    - action: fill
      selector: "#note"
      value: "{{{{ row.note }}}}"
      skip_if_empty: "row.note"
    - action: click
      selector: "#btn-save"
    - action: wait_for_text
      text: "저장되었습니다"
    - action: switch_frame
  teardown:
    - action: goto
      url: "{site_url}/saved.html"
    - action: assert_text
      selector: "#records"
      text: "가나상사 / 1500000 / S1 / 정기계약"
    - action: assert_text
      selector: "#records"
      text: "다라물산 / 230000 / S1 /"
""",
        encoding="utf-8",
    )
    return scenario, tmp_path / ".env"


def test_로그인부터_엑셀_입력까지_실제로_동작한다(project):
    scenario_path, env = project
    summary = Runner(load_scenario(scenario_path), SecretStore(env), RunOptions()).run()

    assert summary.aborted_reason is None
    assert summary.failed_count == 0
    assert summary.ok_count == 2


def test_로그인_실패는_명확한_메시지로_중단된다(project):
    scenario_path, env = project
    env.write_text("INTRANET_ID=hong\nINTRANET_PW=틀린비밀번호\n", encoding="utf-8")

    summary = Runner(load_scenario(scenario_path), SecretStore(env), RunOptions()).run()

    assert summary.aborted_reason is not None
    assert "로그인 확인에 실패" in summary.aborted_reason
    # 실패 화면이 증거로 남아야 한다.
    assert list((scenario_path.parent / "output" / "errors").glob("login-failed-*.png"))


def test_선택자가_틀리면_해당_행만_기록하고_멈춘다(project):
    scenario_path, env = project
    text = scenario_path.read_text(encoding="utf-8").replace("#partnerName", "#존재하지않는칸")
    scenario_path.write_text(text, encoding="utf-8")

    summary = Runner(load_scenario(scenario_path), SecretStore(env), RunOptions()).run()

    assert summary.failed_count == 1
    assert summary.results[0].status == "failed"
    assert "존재하지않는칸" in summary.results[0].message
