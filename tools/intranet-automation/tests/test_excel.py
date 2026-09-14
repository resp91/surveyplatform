import pytest
from openpyxl import Workbook

from intranet_bot.config import ExcelConfig
from intranet_bot.errors import ExcelError
from intranet_bot.excel import ExcelSource


@pytest.fixture
def sample_book(tmp_path):
    path = tmp_path / "입력데이터.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet.append(["거래처명", "금액", "비고"])
    sheet.append(["가나상사", 1500000, "정기"])
    sheet.append(["다라물산", 230000, None])
    sheet.append([None, None, None])          # 빈 행
    sheet.append(["마바테크", 90000, "신규"])
    workbook.save(path)
    return path


def test_헤더명으로_열을_매핑한다(sample_book):
    config = ExcelConfig(path=str(sample_book), columns={"거래처명": "partner", "금액": "amount"})
    rows = ExcelSource(config, sample_book).load()
    assert [r.row_number for r in rows] == [2, 3, 5]
    assert rows[0].values == {"partner": "가나상사", "amount": 1500000}


def test_빈_행은_건너뛴다(sample_book):
    config = ExcelConfig(path=str(sample_book), columns={"거래처명": "partner"})
    rows = ExcelSource(config, sample_book).load()
    assert all(not r.is_empty() for r in rows)
    assert 4 not in [r.row_number for r in rows]


def test_열_문자로도_지정할_수_있다(sample_book):
    config = ExcelConfig(path=str(sample_book), columns={"A": "partner", "C": "note"})
    rows = ExcelSource(config, sample_book).load()
    assert rows[0].values == {"partner": "가나상사", "note": "정기"}


def test_columns_를_생략하면_헤더를_그대로_쓴다(sample_book):
    rows = ExcelSource(ExcelConfig(path=str(sample_book)), sample_book).load()
    assert set(rows[0].values) == {"거래처명", "금액", "비고"}


def test_행_범위를_제한한다(sample_book):
    config = ExcelConfig(path=str(sample_book), start_row=3, end_row=3, columns={"거래처명": "partner"})
    rows = ExcelSource(config, sample_book).load()
    assert [r.row_number for r in rows] == [3]


def test_없는_열은_있는_열을_알려준다(sample_book):
    config = ExcelConfig(path=str(sample_book), columns={"담당자": "owner"})
    with pytest.raises(ExcelError, match="있는 열: 거래처명, 금액, 비고"):
        ExcelSource(config, sample_book).load()


def test_없는_시트는_시트_목록을_알려준다(sample_book):
    config = ExcelConfig(path=str(sample_book), sheet="없는시트")
    with pytest.raises(ExcelError, match="있는 시트: Sheet1"):
        ExcelSource(config, sample_book).load()


def test_파일이_없으면_경로를_알려준다(tmp_path):
    missing = tmp_path / "없음.xlsx"
    with pytest.raises(ExcelError, match="찾을 수 없습니다"):
        ExcelSource(ExcelConfig(path=str(missing)), missing).load()


def test_머리글의_줄바꿈과_공백을_정리한다(tmp_path):
    path = tmp_path / "messy.xlsx"
    workbook = Workbook()
    workbook.active.append(["거래처\n명", "  금액  "])
    workbook.active.append(["가나상사", 100])
    workbook.save(path)
    config = ExcelConfig(path=str(path), columns={"거래처 명": "partner", "금액": "amount"})
    rows = ExcelSource(config, path).load()
    assert rows[0].values == {"partner": "가나상사", "amount": 100}
