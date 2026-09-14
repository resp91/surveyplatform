from datetime import date, datetime

import pytest

from intranet_bot.errors import ConfigError, SecretError
from intranet_bot.secrets import SecretStore
from intranet_bot.templating import Context


def make_context(tmp_path, **kwargs):
    env = tmp_path / ".env"
    env.write_text("INTRANET_ID=hong\nINTRANET_PW=p@ss word\n", encoding="utf-8")
    return Context(SecretStore(env), **kwargs)


def test_엑셀_행_값을_치환한다(tmp_path):
    ctx = make_context(tmp_path, row={"partner": "가나상사"}, row_index=3)
    assert ctx.render("거래처: {{ row.partner }} ({{ row_index }}행)") == "거래처: 가나상사 (3행)"


def test_비밀값을_치환하고_로그에서_가린다(tmp_path):
    ctx = make_context(tmp_path)
    assert ctx.render("{{ secret.INTRANET_PW }}") == "p@ss word"
    assert ctx.secrets.mask("입력값: p@ss word") == "입력값: ********"


def test_없는_열은_사용_가능한_열을_알려준다(tmp_path):
    ctx = make_context(tmp_path, row={"partner": "가나상사"})
    with pytest.raises(ConfigError, match="사용 가능: partner"):
        ctx.render("{{ row.없는열 }}")


def test_없는_비밀값은_안내와_함께_실패한다(tmp_path):
    ctx = make_context(tmp_path)
    with pytest.raises(SecretError, match="INTRANET_TOKEN"):
        ctx.render("{{ secret.INTRANET_TOKEN }}")


def test_숫자와_날짜를_화면_입력용_문자열로_바꾼다(tmp_path):
    ctx = make_context(
        tmp_path,
        row={
            "amount": 1500000.0,
            "contract_date": datetime(2026, 3, 2, 0, 0),
            "plain_date": date(2026, 3, 2),
            "flag": True,
        },
    )
    assert ctx.render("{{ row.amount }}") == "1500000"
    assert ctx.render("{{ row.contract_date }}") == "2026-03-02"
    assert ctx.render("{{ row.plain_date }}") == "2026-03-02"
    assert ctx.render("{{ row.flag }}") == "Y"


def test_빈_셀은_빈_문자열이_된다(tmp_path):
    ctx = make_context(tmp_path, row={"note": None})
    assert ctx.render("{{ row.note }}") == ""


def test_맵과_리스트도_재귀적으로_치환한다(tmp_path):
    ctx = make_context(tmp_path, row={"partner": "가나상사"})
    rendered = ctx.render({"selector": "#a", "value": "{{ row.partner }}", "list": ["{{ row.partner }}"]})
    assert rendered == {"selector": "#a", "value": "가나상사", "list": ["가나상사"]}


def test_시각_치환(tmp_path):
    ctx = make_context(tmp_path, now=datetime(2026, 9, 14, 8, 30, 0))
    assert ctx.render("{{ now.date }} {{ now.time }}") == "2026-09-14 08:30:00"


def test_with_row_는_비밀값과_고정값을_이어받는다(tmp_path):
    base = make_context(tmp_path, variables={"부서": "영업1팀"})
    row_ctx = base.with_row({"partner": "가나상사"}, 5)
    assert row_ctx.render("{{ var.부서 }}/{{ row.partner }}") == "영업1팀/가나상사"
