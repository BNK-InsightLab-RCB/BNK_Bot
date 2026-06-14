"""Role-aware RAG answer generation."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from backend.app.config import settings
from backend.app.llm.prompts import ANSWER_PROMPT
from backend.app.llm.qwen_client import QwenClient
from backend.app.parsers.base import KnowledgeDocument
from backend.app.rag.citation_builder import CitationBuilder
from backend.app.rag.safety import is_forbidden_question, sanitize_answer
from backend.app.retrieval.context_builder import ContextBuilder
from backend.app.utils.text import unique_keep_order


class AnswerGenerator:
    """Generate branch and IT answers from retrieved documents."""

    def __init__(
        self,
        context_builder: Optional[ContextBuilder] = None,
        citation_builder: Optional[CitationBuilder] = None,
        client: Optional[QwenClient] = None,
    ) -> None:
        self.context_builder = context_builder or ContextBuilder()
        self.citation_builder = citation_builder or CitationBuilder()
        self.client = client or QwenClient()

    def generate(
        self,
        question: str,
        docs: Iterable[KnowledgeDocument],
        user_role: str = "branch",
        use_llm: bool = False,
    ) -> Dict[str, object]:
        """Return a structured chat response."""
        doc_list = list(docs)
        if is_forbidden_question(question):
            answer = (
                "[가능한 원인]\n요청하신 내용은 보안 정책상 안내할 수 없습니다.\n\n"
                "[먼저 확인할 사항]\n정상 권한 신청 절차와 승인된 업무 매뉴얼을 확인해 주세요.\n\n"
                "[계속 오류가 발생하는 경우]\nIT부서에 오류 문구와 화면명을 전달해 주세요.\n\n"
                "[IT부서 전달용 정보]\n보안 우회 또는 직접 수정 요청이 아닌 정상 장애 문의로 접수해야 합니다.\n\n"
                "[근거]\n보안 정책"
            )
            return self._response(answer, doc_list, user_role, confidence=0.2)

        context = self.context_builder.build(doc_list, user_role=user_role)
        answer = None
        if use_llm:
            prompt = ANSWER_PROMPT.format(question=question, user_role=user_role, context=context)
            answer = self.client.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.1,
                enable_thinking=settings.enable_thinking_for_chat,
            )
        if not answer:
            answer = self._fallback_answer(question, doc_list, user_role)
        answer = _ensure_retry_section(answer, doc_list)
        return self._response(answer, doc_list, user_role, confidence=_confidence(doc_list))

    def _response(
        self, answer: str, docs: List[KnowledgeDocument], user_role: str, confidence: float
    ) -> Dict[str, object]:
        sanitized = sanitize_answer(answer, user_role)
        return {
            "answer": sanitized,
            "branch_guide": _branch_guide_payload(docs),
            "it_summary": _it_summary_payload(docs) if user_role in {"it", "admin"} else {},
            "confidence": confidence,
            "sources": self.citation_builder.build(docs, user_role),
        }

    def _fallback_answer(self, question: str, docs: List[KnowledgeDocument], user_role: str) -> str:
        causes = _possible_causes(docs)
        checklist = _checklist(docs)
        screens = unique_keep_order(doc.screen_name or "" for doc in docs)
        screen_text = ", ".join(screens) if screens else "문의 화면"
        answer = [
            "[가능한 원인]",
            "검색된 근거 기준으로 원인을 확정할 수는 없지만, "
            + (", ".join(causes) if causes else "입력값, 권한, 상태값 조건 문제")
            + " 가능성이 있습니다.",
            "",
            "[먼저 확인할 사항]",
        ]
        answer.extend(f"{index}. {item}" for index, item in enumerate(checklist, start=1))
        answer.extend(
            [
                "",
                "[계속 오류가 발생하는 경우]",
                f"동일 오류가 계속되면 {_contact_summary(docs)} 정보를 정리해 IT부서에 전달해 주세요.",
                "",
                "[IT부서 전달용 정보]",
                f"- 화면명: {screen_text}",
                f"- 사용자 문의: {question}",
                "- 수행 작업: 저장/조회/승인 등 실제 누른 버튼",
                "- 오류 문구: 화면에 표시된 문구",
            ]
        )
        if user_role in {"it", "admin"}:
            it = _it_summary_payload(docs)
            answer.extend(
                [
                    f"- API: {it.get('api_path') or '-'}",
                    f"- Service: {it.get('service') or '-'}",
                    f"- SQL: {', '.join(it.get('sql_ids', [])) or '-'}",
                    f"- Table: {', '.join(it.get('tables', [])) or '-'}",
                ]
            )
        answer.extend(["", "[근거]"])
        for doc in docs[:5]:
            if user_role in {"it", "admin"}:
                answer.append(f"- {doc.title}: {doc.summary}")
            else:
                answer.append(f"- {_branch_source_label(doc)}: {_branch_source_reason(doc)}")
        return "\n".join(answer)


def _possible_causes(docs: List[KnowledgeDocument]) -> List[str]:
    causes: List[str] = []
    for doc in docs:
        for error in doc.possible_errors:
            message = str(error.get("message", ""))
            condition = str(error.get("condition", ""))
            if "권한" in message or "권한" in condition:
                causes.append("처리 권한이 없을 수 있습니다")
            elif "고객번호" in message or "customerNo" in condition:
                causes.append("고객번호가 누락되었을 수 있습니다")
            elif "해지" in message or "CLOSED" in condition:
                causes.append("고객 상태가 해지 또는 수정 제한 상태일 수 있습니다")
            elif message:
                causes.append(f"{message} 조건일 수 있습니다")
        for rule in doc.business_rules:
            if "USE_YN" in rule:
                causes.append("사용 여부 조건 때문에 조회되지 않을 수 있습니다")
    return unique_keep_order(causes)[:5]


def _checklist(docs: List[KnowledgeDocument]) -> List[str]:
    text = " ".join(doc.searchable_text() for doc in docs)
    is_auto_debit = "자동이체" in text or "AUTO_DEBIT" in text or "납부자번호" in text
    is_transfer = not is_auto_debit and (
        "계좌이체" in text or "이체금액" in text or "이체한도" in text or "잔액" in text
    )
    is_slip = "전표" in text or "SLIP" in text
    is_customer = "고객" in text or "CUSTOMER" in text
    items = ["화면에 표시된 오류 문구를 그대로 확인해 주세요."]
    if is_auto_debit:
        items.insert(0, "출금계좌, 납부자번호, 출금일이 정상적으로 입력되어 있는지 확인해 주세요.")
    elif is_transfer:
        items.insert(0, "출금계좌, 입금계좌, 이체금액이 정상적으로 입력되어 있는지 확인해 주세요.")
    elif is_slip:
        items.insert(0, "전표번호와 승인 대상 정보가 정상적으로 입력되어 있는지 확인해 주세요.")
    elif is_customer:
        items.insert(0, "고객번호가 정상적으로 입력되어 있는지 확인해 주세요.")
    else:
        items.insert(0, "업무 처리 대상 정보가 정상적으로 입력되어 있는지 확인해 주세요.")
    if "CLOSED" in text or "해지" in text:
        items.append("고객 상태가 해지 또는 수정 제한 상태인지 확인해 주세요.")
    if "권한" in text or "CUSTOMER_SAVE" in text or "SLIP_APPROVE" in text:
        items.append("본인 계정에 해당 업무 처리 권한이 있는지 확인해 주세요.")
    if "USE_YN" in text:
        if is_auto_debit:
            items.append("자동이체 출금계좌가 사용 가능한 상태인지 확인해 주세요.")
        elif is_transfer:
            items.append("출금계좌가 사용 가능한 상태인지 확인해 주세요.")
        elif is_customer:
            items.append("조회 대상 고객이 사용 가능한 상태인지 확인해 주세요.")
        else:
            items.append("조회 대상 정보가 사용 가능한 상태인지 확인해 주세요.")
    if is_auto_debit:
        items.extend(
            [
                "출금계좌가 만료되었거나 거래 제한 상태인지 확인해 주세요.",
                "납부자번호가 기관에서 요구하는 형식과 길이에 맞는지 확인해 주세요.",
                "출금일이 1일부터 28일 사이로 선택되어 있는지 확인해 주세요.",
                "동일 출금계좌와 납부자번호로 이미 등록된 자동이체가 있는지 확인해 주세요.",
            ]
        )
    if is_transfer:
        items.extend(
            [
                "출금계좌 잔액이 이체금액보다 큰지 확인해 주세요.",
                "이체금액이 0보다 큰 정상 금액인지 확인해 주세요.",
                "일일 이체한도와 금일 누적 이체금액을 확인해 주세요.",
                "OTP 번호가 정상 입력되었고 인증 가능한 상태인지 확인해 주세요.",
            ]
        )
    if is_slip:
        items.extend(
            [
                "전표번호가 정상적으로 입력되어 있는지 확인해 주세요.",
                "전표 상태가 승인 가능한 상태인지 확인해 주세요.",
                "본인 계정에 전표 승인 권한이 있는지 확인해 주세요.",
            ]
        )
    return unique_keep_order(items)


def _branch_guide_payload(docs: List[KnowledgeDocument]) -> Dict[str, object]:
    return {
        "possible_causes": _possible_causes(docs),
        "checklist": _checklist(docs),
        "it_contact_summary": f"{_contact_summary(docs)} 정보를 함께 전달해 주세요.",
    }


def _it_summary_payload(docs: List[KnowledgeDocument]) -> Dict[str, object]:
    return {
        "screen_id": _first(doc.screen_id for doc in docs),
        "api_path": _first(doc.api_path for doc in docs),
        "controller": _first(doc.title for doc in docs if doc.doc_type == "backend_controller"),
        "service": _first(doc.title for doc in docs if doc.doc_type == "business_logic"),
        "sql_ids": unique_keep_order(doc.sql_id or "" for doc in docs),
        "tables": unique_keep_order(table for doc in docs for table in doc.tables),
    }


def _first(values: Iterable[Optional[str]]) -> Optional[str]:
    for value in values:
        if value:
            return value
    return None


def _confidence(docs: List[KnowledgeDocument]) -> float:
    if not docs:
        return 0.1
    if len(docs) >= 5:
        return 0.78
    return min(0.7, 0.3 + len(docs) * 0.1)


def _branch_source_label(doc: KnowledgeDocument) -> str:
    if doc.screen_name:
        return f"{doc.screen_name} 업무 규칙"
    if doc.doc_type == "sql_mapper":
        return "업무 데이터 조건"
    return "업무 처리 기준"


def _branch_source_reason(doc: KnowledgeDocument) -> str:
    if doc.doc_type == "frontend_event":
        messages = ", ".join(doc.error_messages)
        return (
            "화면 입력값 확인과 사용자 안내 메시지를 근거로 확인했습니다."
            + (f" 표시 메시지: {messages}" if messages else "")
        )
    if doc.doc_type == "business_logic":
        text = doc.searchable_text()
        if "자동이체" in text or "AUTO_DEBIT" in text or "납부자번호" in text:
            return "업무 처리 과정에서 출금계좌 상태, 납부자번호 형식, 출금일, 중복 등록 여부를 검증하는 근거가 있습니다."
        if "기업뱅킹" in text or "CORP_USER" in text or "사업자번호" in text:
            return "업무 처리 과정에서 사업자번호 상태, 관리자 승인, OTP 등록 정보, 사용자 중복 여부를 검증하는 근거가 있습니다."
        if "계좌이체" in text or "이체금액" in text or "이체한도" in text or "잔액" in text:
            return "업무 처리 과정에서 출금계좌 상태, 잔액, 이체금액, 이체한도, OTP 인증을 검증하는 근거가 있습니다."
        if "전표" in text or "승인" in text:
            return "업무 처리 과정에서 전표 상태와 승인 권한을 검증하는 근거가 있습니다."
        return "업무 처리 과정에서 권한, 고객번호, 고객 상태를 검증하는 근거가 있습니다."
    if doc.doc_type == "sql_mapper":
        return "업무 데이터 조회 또는 수정 조건을 근거로 확인했습니다."
    if doc.doc_type == "table_definition":
        return "업무 데이터 정의를 근거로 확인했습니다."
    if doc.branch_guide:
        return doc.branch_guide
    return "관련 업무 규칙을 근거로 확인했습니다."


def _ensure_retry_section(answer: str, docs: List[KnowledgeDocument]) -> str:
    base = _strip_existing_retry_section(answer)
    base = _strip_incomplete_retry_tail(base).rstrip()
    return base + "\n\n" + _retry_section(docs)


def _strip_existing_retry_section(answer: str) -> str:
    markers = ["\n[조치 후 재시도]", "\n## 조치 후 재시도", "\n### 조치 후 재시도"]
    for marker in markers:
        index = answer.rfind(marker)
        if index != -1:
            return answer[:index]
    return answer


def _strip_incomplete_retry_tail(answer: str) -> str:
    markers = ["\n[조치", "\n## 조치", "\n### 조치"]
    for marker in markers:
        index = answer.rfind(marker)
        if index != -1 and len(answer) - index < 400:
            tail = answer[index:]
            if "조치 후 재시도" not in tail:
                return answer[:index]
    return answer


def _retry_section(docs: List[KnowledgeDocument]) -> str:
    checklist = _checklist(docs)
    lines = [
        "[조치 후 재시도]",
        "위 조건을 확인한 뒤 같은 화면에서 다시 시도해 주세요.",
    ]
    if checklist:
        lines.append("")
        lines.extend(f"{index}. {item}" for index, item in enumerate(checklist[:5], start=1))
    lines.extend(
        [
            "",
            f"조건을 확인했는데도 동일 오류가 계속되면 {_contact_summary(docs)} 정보를 정리해 IT부서에 전달해 주세요.",
        ]
    )
    return "\n".join(lines)


def _contact_summary(docs: List[KnowledgeDocument]) -> str:
    text = " ".join(doc.searchable_text() for doc in docs)
    common = "화면명, 수행 작업, 발생 시각, 오류 문구"
    if "자동이체" in text or "AUTO_DEBIT" in text or "납부자번호" in text:
        return f"{common}, 출금계좌 뒤 4자리, 납부자번호, 출금일"
    if "계좌이체" in text or "이체금액" in text or "이체한도" in text or "잔액" in text:
        return f"{common}, 출금계좌 뒤 4자리, 이체금액"
    if "전표" in text or "승인" in text:
        return f"{common}, 전표번호"
    if "고객" in text or "CUSTOMER" in text:
        return f"{common}, 고객번호 뒤 4자리"
    return common
