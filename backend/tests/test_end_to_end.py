from pathlib import Path

from backend.app.ingestion.pipeline import IngestionPipeline
from backend.app.parsers.base import KnowledgeDocument
from backend.app.rag.answer_generator import AnswerGenerator
from backend.app.rag.safety import sanitize_answer
from backend.app.retrieval.elastic_searcher import HybridSearcher
from backend.app.retrieval.graph_store import GraphExpander
from backend.app.retrieval.query_analyzer import QueryAnalyzer
from backend.app.storage.elastic import KnowledgeIndex


def test_sample_end_to_end_customer_save(tmp_path):
    index_path = tmp_path / "ops_knowledge.json"
    sqlite_path = tmp_path / "ops_rag.sqlite3"
    pipeline = IngestionPipeline(index_path=str(index_path), sqlite_path=str(sqlite_path))

    result = pipeline.run(
        source_dir="backend/examples/bank_sample",
        reset_index=True,
        generate_summaries=False,
    )

    assert result.indexed_count >= 10

    analyzer = QueryAnalyzer()
    intent = analyzer.analyze("고객조회 화면에서 저장이 안돼요.")
    index = KnowledgeIndex(local_path=str(index_path))
    ranked = HybridSearcher(index=index).search(intent, top_k=8)
    seed_docs = [doc for doc, _ in ranked]
    expanded = GraphExpander(sqlite_path=str(sqlite_path)).expand(seed_docs, index.load_documents())
    titles = {doc.title for doc in expanded}
    sql_ids = {doc.sql_id for doc in expanded if doc.sql_id}
    tables = {table for doc in expanded for table in doc.tables}

    assert "CustomerService.saveCustomer" in titles
    assert "CustomerMapper.updateCustomer" in sql_ids
    assert "TB_CUSTOMER" in tables

    branch = AnswerGenerator().generate("고객조회 화면에서 저장이 안돼요.", expanded, user_role="branch")
    assert "가능성이 있습니다" in branch["answer"]
    assert "[조치 후 재시도]" in branch["answer"]
    assert "다시 시도해 주세요" in branch["answer"]
    assert "CustomerService.saveCustomer" not in branch["answer"]
    assert "TB_CUSTOMER" not in branch["answer"]
    assert "CUSTOMER_SAVE" not in branch["answer"]
    assert "CustomerService.saveCustomer" not in str(branch["sources"])
    assert "TB_CUSTOMER" not in str(branch["sources"])
    assert "/api/customer/save" not in str(branch["sources"])
    assert "customerMapper" not in branch["answer"]
    assert "user.hasRole" not in branch["answer"]
    assert "customerMapper" not in str(branch["sources"])
    assert "user.hasRole" not in str(branch["sources"])

    it = AnswerGenerator().generate("고객조회 화면에서 저장이 안돼요.", expanded, user_role="it")
    assert "CustomerService.saveCustomer" in it["answer"]
    assert "CustomerMapper.updateCustomer" in it["answer"] or "CustomerMapper.updateCustomer" in str(it["it_summary"])
    assert "TB_CUSTOMER" in it["answer"] or "TB_CUSTOMER" in str(it["it_summary"])


def test_sample_questions_return_results(tmp_path):
    index_path = tmp_path / "ops_knowledge.json"
    sqlite_path = tmp_path / "ops_rag.sqlite3"
    pipeline = IngestionPipeline(index_path=str(index_path), sqlite_path=str(sqlite_path))
    pipeline.run("backend/examples/bank_sample", reset_index=True, generate_summaries=False)
    index = KnowledgeIndex(local_path=str(index_path))
    searcher = HybridSearcher(index=index)
    analyzer = QueryAnalyzer()
    questions = [
        "고객조회 화면에서 저장이 안돼요.",
        "고객번호 넣었는데 고객이 조회되지 않아요.",
        "저장 권한이 없다고 나오는데 어떻게 해야 하나요?",
        "해지 고객 수정이 안되는 이유가 뭐예요?",
    ]

    for question in questions:
        ranked = searcher.search(analyzer.analyze(question), top_k=3)
        assert ranked, question
        assert any(Path(doc.source_path).exists() for doc, _ in ranked)


def test_generated_ops_source_scenarios_are_searchable(tmp_path):
    index_path = tmp_path / "ops_knowledge.json"
    sqlite_path = tmp_path / "ops_rag.sqlite3"
    pipeline = IngestionPipeline(index_path=str(index_path), sqlite_path=str(sqlite_path))
    result = pipeline.run("backend/examples/bank_sample", reset_index=True, generate_summaries=False)

    assert result.indexed_count >= 90

    question = "자동이체 등록 화면에서 출금계좌가 만료되었거나 사용 불가 상태라고 나와요. 납부자번호는 입력했습니다."
    intent = QueryAnalyzer().analyze(question)
    index = KnowledgeIndex(local_path=str(index_path))
    ranked = HybridSearcher(index=index).search(intent, user_role="branch", top_k=8)
    titles = [doc.title for doc, _ in ranked]
    source_paths = [doc.source_path for doc, _ in ranked]

    assert "BranchOpsScenarioService.registerAutoDebit" in titles
    assert "AutoDebitRegister.vue > registerAutoDebit" in titles
    assert any("AutoDebitRegister.vue" in path for path in source_paths)

    expanded = GraphExpander(sqlite_path=str(sqlite_path)).expand(
        [doc for doc, _ in ranked], index.load_documents()
    )
    expanded_titles = {doc.title for doc in expanded}
    assert "TransferService.executeTransfer" not in expanded_titles

    branch = AnswerGenerator().generate(question, expanded, user_role="branch")
    assert "납부자번호" in branch["answer"]
    assert "출금일" in branch["answer"]
    assert "OTP" not in branch["answer"]
    assert "이체금액" not in branch["answer"]


def test_branch_answer_masks_method_calls_and_rewrites_retry_tail():
    assert "account.getBalance" not in sanitize_answer("account.getBalance() 조건 확인", "branch")
    sanitized_status = sanitize_answer(
        "출금계좌의 사용 여부(USE_YN)가 'N'인 경우 TB_ACCOUNT 테이블의 `STATUS` 및 `USE_YN` 컬럼을 확인합니다.",
        "branch",
    )
    assert "[내부 상태값]" not in sanitized_status
    assert "TB_ACCOUNT" not in sanitized_status

    class StubClient:
        def chat(self, *args, **kwargs):
            return (
                "[가능한 원인]\n잔액 또는 계좌 상태 문제일 수 있습니다.\n\n"
                "[먼저 확인할 사항]\n1. 잔액을 확인하세요.\n\n"
                "[계속 오류가 발생하는 경우]\nIT부서에 전달하세요.\n\n"
                "[IT부서 전달용 정보]\n오류 문구와 발생 시각\n\n"
                "[근거]\naccount.getBalance() 조건을 확인합니다.\n\n"
                "[조치 후 재시도]\n동일 오류가 계속되면 IT부서에"
            )

    doc = KnowledgeDocument(
        doc_type="business_logic",
        title="TransferService.executeTransfer",
        source_path="backend/examples/bank_sample/backend/TransferService.java",
        summary="계좌이체 처리 로직",
        error_messages=["잔액이 부족합니다."],
    )

    response = AnswerGenerator(client=StubClient()).generate(
        "계좌이체 화면에서 잔액이 부족합니다.", [doc], user_role="branch", use_llm=True
    )

    assert "account.getBalance" not in response["answer"]
    assert response["answer"].rstrip().endswith("IT부서에 전달해 주세요.")
    assert "동일 오류가 계속되면 IT부서에" not in response["answer"]
