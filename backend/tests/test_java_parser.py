from pathlib import Path

from backend.app.parsers.base import SourceFile
from backend.app.parsers.java_parser import JavaParser


def _source(path: str) -> SourceFile:
    file_path = Path(path)
    return SourceFile(path=file_path, language="java", text=file_path.read_text(encoding="utf-8"))


def test_java_parser_extracts_controller_mapping():
    docs = JavaParser().parse(_source("backend/examples/bank_sample/backend/CustomerController.java"))
    save = next(doc for doc in docs if doc.method_name == "saveCustomer")

    assert save.doc_type == "backend_controller"
    assert save.api_path == "/api/customer/save"
    assert save.http_method == "POST"
    assert "customerService.saveCustomer" in save.metadata["called_methods"]


def test_java_parser_extracts_business_rules_and_mapper_calls():
    docs = JavaParser().parse(_source("backend/examples/bank_sample/backend/CustomerService.java"))
    save = next(doc for doc in docs if doc.method_name == "saveCustomer")

    assert save.doc_type == "business_logic"
    assert "저장 권한이 없습니다." in save.error_messages
    assert "해지 고객은 수정할 수 없습니다." in save.error_messages
    assert "CustomerMapper.updateCustomer" in save.metadata["mapper_calls"]
    assert any("CUSTOMER_SAVE" in rule for rule in save.business_rules)
