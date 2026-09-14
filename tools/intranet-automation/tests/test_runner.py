import json

import pytest
from openpyxl import Workbook

from intranet_bot.config import load_scenario
from intranet_bot.errors import BotError
from intranet_bot.runner import Checkpoint, RunOptions, Runner, parse_row_filter
from intranet_bot.secrets import SecretStore


@pytest.mark.parametrize(
    "spec,expected",
    [
        (None, None),
        ("", None),
        ("3", {3}),
        ("2-5", {2, 3, 4, 5}),
        ("2-4,7", {2, 3, 4, 7}),
        (" 2 , 4 ", {2, 4}),
    ],
)
def test_행_필터_파싱(spec, expected):
    assert parse_row_filter(spec) == expected


@pytest.mark.parametrize("spec", ["가-나", "5-2", "abc"])
def test_잘못된_행_필터는_거부한다(spec):
    with pytest.raises(BotError):
        parse_row_filter(spec)


def test_체크포인트는_완료_행을_기억한다(tmp_path):
    path = tmp_path / "checkpoint.json"
    checkpoint = Checkpoint(path, "시나리오A")
    checkpoint.mark(2)
    checkpoint.mark(3)

    reloaded = Checkpoint(path, "시나리오A")
    reloaded.load()
    assert reloaded.done == {2, 3}

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["scenario"] == "시나리오A"


def test_다른_시나리오의_체크포인트는_무시한다(tmp_path):
    path = tmp_path / "checkpoint.json"
    Checkpoint(path, "시나리오A").mark(2)

    other = Checkpoint(path, "시나리오B")
    other.load()
    assert other.done == set()


def test_깨진_체크포인트_파일은_처음부터_실행한다(tmp_path):
    path = tmp_path / "checkpoint.json"
    path.write_text("{깨진 JSON", encoding="utf-8")
    checkpoint = Checkpoint(path, "시나리오A")
    checkpoint.load()
    assert checkpoint.done == set()


@pytest.fixture
def project(tmp_path):
    """엑셀 + 시나리오 + .env 가 갖춰진 임시 작업 폴더."""
    book = tmp_path / "입력데이터.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["거래처명", "금액"])
    for name, amount in [("가나상사", 100), ("다라물산", 200), ("마바테크", 300)]:
        sheet.append([name, amount])
    workbook.save(book)

    env = tmp_path / ".env"
    env.write_text("INTRANET_ID=hong\nINTRANET_PW=secret1234\n", encoding="utf-8")

    scenario_path = tmp_path / "scenario.yaml"
    scenario_path.write_text(
        """
name: 테스트시나리오
run:
  output_dir: "./output"
login:
  url: https://example.test/login
  steps:
    - action: fill
      selector: "#id"
      value: "{{ secret.INTRANET_ID }}"
excel:
  path: "./입력데이터.xlsx"
  columns:
    거래처명: partner
    금액: amount
flow:
  per_row:
    - action: fill
      selector: "#partner"
      value: "{{ row.partner }}"
    - action: click
      selector: "#save"
""",
        encoding="utf-8",
    )
    return scenario_path, env


def test_모의_실행은_브라우저_없이_전체를_점검한다(project, caplog):
    scenario_path, env = project
    scenario = load_scenario(scenario_path)
    runner = Runner(scenario, SecretStore(env), RunOptions(dry_run=True))

    with caplog.at_level("INFO"):
        summary = runner.run()

    assert len(summary.results) == 3
    assert all(r.status == "skipped" for r in summary.results)
    assert "가나상사" in caplog.text
    # 비밀값은 모의 실행 로그에도 그대로 드러나면 안 된다.
    assert "secret1234" not in caplog.text
    assert "********" in caplog.text


def test_rows_와_limit_으로_대상_행을_좁힌다(project):
    scenario_path, env = project
    scenario = load_scenario(scenario_path)

    only_third = Runner(scenario, SecretStore(env), RunOptions(dry_run=True, rows="4")).run()
    assert [r.row_number for r in only_third.results] == [4]

    first_two = Runner(scenario, SecretStore(env), RunOptions(dry_run=True, limit=2)).run()
    assert [r.row_number for r in first_two.results] == [2, 3]


def test_이어하기는_끝난_행을_건너뛴다(project):
    scenario_path, env = project
    scenario = load_scenario(scenario_path)
    checkpoint = Checkpoint(scenario.resolve(scenario.run.checkpoint_file), scenario.name)
    checkpoint.mark(2)

    summary = Runner(scenario, SecretStore(env), RunOptions(dry_run=True, resume=True)).run()
    assert [r.row_number for r in summary.results] == [3, 4]


def test_실행_결과를_CSV로_남긴다(project):
    scenario_path, env = project
    scenario = load_scenario(scenario_path)
    Runner(scenario, SecretStore(env), RunOptions(dry_run=True)).run()

    files = list((scenario_path.parent / "output").glob("result-*.csv"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8-sig")
    assert content.splitlines()[0] == "행번호,상태,메시지"
