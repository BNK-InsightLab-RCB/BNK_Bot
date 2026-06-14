from pathlib import Path

from backend.app.ingestion.scanner import SourceScanner
from backend.app.parsers.frontend_parser import FrontendParser


SAMPLE = Path("backend/examples/bank_sample/frontend/CustomerSearch.vue")


def test_frontend_parser_extracts_screen_button_and_api():
    source = SourceScanner().scan(str(SAMPLE.parent))[0]
    docs = FrontendParser().parse(source)

    screen = next(doc for doc in docs if doc.doc_type == "frontend_screen")
    save = next(doc for doc in docs if doc.method_name == "saveCustomer")

    assert screen.screen_id == "CUST_001"
    assert screen.screen_name == "고객조회"
    assert save.api_path == "/api/customer/save"
    assert save.http_method == "POST"
    assert "고객번호를 입력하세요." in save.error_messages
    assert save.metadata["button_name"] == "저장"
