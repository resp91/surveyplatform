import pytest

from intranet_bot.config import load_scenario
from intranet_bot.errors import ConfigError

MINIMAL = """
name: 테스트
login:
  url: https://example.test/login
  steps:
    - action: fill
      selector: "#id"
      value: "{{ secret.ID }}"
"""


def write(tmp_path, text, name="scenario.yaml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_최소_시나리오를_읽는다(tmp_path):
    scenario = load_scenario(write(tmp_path, MINIMAL))
    assert scenario.name == "테스트"
    assert scenario.login is not None
    assert scenario.login.steps[0].action == "fill"
    assert scenario.default_timeout_ms == 15000


def test_알수없는_action_은_거부한다(tmp_path):
    text = MINIMAL.replace("action: fill", "action: 클릭해줘")
    with pytest.raises(ConfigError, match="알 수 없는 action"):
        load_scenario(write(tmp_path, text))


def test_필수_항목이_빠지면_거부한다(tmp_path):
    text = """
name: 테스트
login:
  url: https://example.test/login
  steps:
    - action: fill
      selector: "#id"
"""
    with pytest.raises(ConfigError, match="'value' 항목이 필요합니다"):
        load_scenario(write(tmp_path, text))


def test_오타난_항목을_알려준다(tmp_path):
    text = MINIMAL + """
      selecter: "#typo"
"""
    with pytest.raises(ConfigError, match="쓸 수 없는 항목"):
        load_scenario(write(tmp_path, text))


def test_per_row_에는_excel_이_필요하다(tmp_path):
    text = """
name: 테스트
flow:
  per_row:
    - action: click
      selector: "#btn"
"""
    with pytest.raises(ConfigError, match="excel 설정이 필요합니다"):
        load_scenario(write(tmp_path, text))


def test_상대경로는_시나리오_파일_기준으로_푼다(tmp_path):
    scenario = load_scenario(write(tmp_path, MINIMAL))
    assert scenario.resolve("./output/a.png") == (tmp_path / "output/a.png").resolve()


def test_실행할_내용이_없으면_거부한다(tmp_path):
    with pytest.raises(ConfigError, match="실행할 것이 없습니다"):
        load_scenario(write(tmp_path, "name: 빈시나리오\n"))


def test_액션_필드는_공통_필드와_겹치지_않는다():
    """겹치면 사용자가 넘긴 값이 단계 설명으로 먹혀 조용히 무시된다."""
    from intranet_bot.config import ACTION_SPECS, COMMON_STEP_FIELDS

    reserved = set(COMMON_STEP_FIELDS) - {"action"}
    for action, spec in ACTION_SPECS.items():
        clashes = (set(spec["required"]) | set(spec["optional"])) & reserved
        assert not clashes, f"action '{action}' 의 필드 {sorted(clashes)} 가 공통 필드와 겹칩니다."


def test_모든_액션에_실행_핸들러가_있다():
    from intranet_bot.config import ACTION_SPECS
    from intranet_bot.steps import StepExecutor

    missing = [a for a in ACTION_SPECS if not hasattr(StepExecutor, f"_do_{a}")]
    assert not missing, f"핸들러가 없는 action: {missing}"


def test_base_dir_로_상대경로_기준을_바꾼다(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    path = config_dir / "scenario.yaml"
    path.write_text(MINIMAL + '\nbase_dir: ".."\n', encoding="utf-8")

    scenario = load_scenario(path)
    assert scenario.resolve("./data/a.xlsx") == (tmp_path / "data/a.xlsx").resolve()
