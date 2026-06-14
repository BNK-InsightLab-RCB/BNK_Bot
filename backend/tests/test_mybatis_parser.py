from pathlib import Path

from backend.app.parsers.base import SourceFile
from backend.app.parsers.mybatis_parser import MyBatisParser


def test_mybatis_parser_extracts_sql_metadata():
    path = Path("backend/examples/bank_sample/mapper/CustomerMapper.xml")
    docs = MyBatisParser().parse(SourceFile(path=path, language="xml", text=path.read_text(encoding="utf-8")))
    select = next(doc for doc in docs if doc.sql_id == "CustomerMapper.selectCustomer")
    update = next(doc for doc in docs if doc.sql_id == "CustomerMapper.updateCustomer")

    assert select.metadata["crud"] == "SELECT"
    assert "TB_CUSTOMER" in select.tables
    assert "customerNo" in select.metadata["parameters"]
    assert any("USE_YN" in rule for rule in select.business_rules)
    assert update.metadata["crud"] == "UPDATE"
    assert "STATUS" in update.columns
