"""Role-based answer safety."""

from __future__ import annotations

import re
from typing import Dict, List

from backend.app.parsers.base import KnowledgeDocument
from backend.app.utils.text import mask_sensitive


FORBIDDEN_PATTERNS = [
    re.compile(r"권한\s*우회"),
    re.compile(r"보안\s*로직\s*우회"),
    re.compile(r"운영\s*DB.*직접\s*수정"),
    re.compile(r"비밀번호|토큰|private_key|api_key", re.IGNORECASE),
]


def is_forbidden_question(question: str) -> bool:
    """Return true when the question requests disallowed guidance."""
    return any(pattern.search(question) for pattern in FORBIDDEN_PATTERNS)


def sanitize_answer(answer: str, user_role: str) -> str:
    """Mask sensitive strings and hide internals for branch users."""
    cleaned = mask_sensitive(answer)
    if user_role == "branch":
        cleaned = re.sub(r"/api/[A-Za-z0-9_./-]+", "[내부 경로]", cleaned)
        cleaned = re.sub(r"\bTB_[A-Z0-9_]+\b", "[내부 테이블]", cleaned)
        cleaned = re.sub(r"\b[A-Z][A-Za-z0-9_]+(?:Controller|Service|Mapper)\.[A-Za-z_]\w*", "[내부 처리 로직]", cleaned)
        cleaned = re.sub(r"\b[a-z][A-Za-z0-9_]*\.[A-Za-z_]\w*(?:\([^)]*\))?", "[내부 처리 로직]", cleaned)
        cleaned = re.sub(r"\b[A-Za-z0-9_]+\.(?:vue|java|xml|ts|tsx|js|jsx)(?:\s*>\s*[A-Za-z_]\w*)?", "화면/업무 근거", cleaned)
        cleaned = re.sub(r"STATUS\s*!=\s*'ACTIVE'", "계좌 상태가 정상 상태가 아닌 경우", cleaned)
        cleaned = re.sub(r"STATUS\s*=\s*'ACTIVE'", "계좌 상태가 정상인 경우", cleaned)
        cleaned = re.sub(r"USE_YN\s*=\s*'Y'", "사용 가능한 상태인 경우", cleaned)
        cleaned = re.sub(
            r"['\"]?(?:INACTIVE|EXPIRED|SUSPENDED|DORMANT|OVERDUE|NORMAL|LOST|COMPLETED)['\"]?",
            "정상 처리 가능 상태가 아닌 값",
            cleaned,
        )
        cleaned = re.sub(
            r"정상 상태가 아닌 경우\s*\(예:\s*정상 처리 가능 상태가 아닌 값(?:,\s*정상 처리 가능 상태가 아닌 값)*\s*등?\)",
            "정상 상태가 아닌 경우",
            cleaned,
        )
        cleaned = re.sub(r"정상 상태가 아닌 경우\s*\(예:\s*정상 처리 가능 상태가 아닌 경우\s*\)", "정상 상태가 아닌 경우", cleaned)
        cleaned = cleaned.replace("정상 상태가 아닌 경우 (예: 정상 처리 가능 상태가 아닌 경우)", "정상 상태가 아닌 경우")
        cleaned = cleaned.replace("정상 처리 가능 상태가 아닌 값, 정상 처리 가능 상태가 아닌 값 등", "정상 처리 가능 상태가 아닌 경우")
        cleaned = re.sub(r"(?<![A-Za-z0-9_])(?:STATUS|USE_YN|BALANCE|ACCOUNT_NO|FROM_ACCOUNT_NO|TO_ACCOUNT_NO|TRANSFER_DATE)(?![A-Za-z0-9_])", "[내부 상태값]", cleaned)
        cleaned = re.sub(r"'ACTIVE'", "정상 상태", cleaned)
        cleaned = re.sub(r"'Y'", "사용 가능", cleaned)
        cleaned = re.sub(r"'N'", "사용 불가", cleaned)
        cleaned = re.sub(r"(?<![A-Za-z0-9_])ACTIVE(?![A-Za-z0-9_])", "정상 상태", cleaned)
        cleaned = re.sub(r"(?<![A-Za-z0-9_])USE_YN(?![A-Za-z0-9_])", "사용 가능 여부", cleaned)
        cleaned = re.sub(r"(?<![A-Za-z0-9_])Y(?![A-Za-z0-9_])", "사용 가능", cleaned)
        cleaned = cleaned.replace("사용 여부([내부 상태값])", "사용 가능 여부")
        cleaned = cleaned.replace("사용 가능 여부가 사용 가능인지", "사용 가능한 상태인지")
        cleaned = cleaned.replace("사용 가능 여부가 사용 불가인 경우", "사용 가능한 상태가 아닌 경우")
        cleaned = cleaned.replace("출금계좌의 사용 가능 여부가 사용 가능한지", "출금계좌가 사용 가능한 상태인지")
        cleaned = cleaned.replace("출금계좌의 사용 가능 여부가 사용 불가인 경우", "출금계좌가 사용 가능한 상태가 아닌 경우")
        cleaned = cleaned.replace("출금계좌의 사용 가능한 상태인지", "출금계좌가 사용 가능한 상태인지")
        cleaned = cleaned.replace("출금계좌의 사용 가능한 상태가 아닌 경우", "출금계좌가 사용 가능한 상태가 아닌 경우")
        cleaned = cleaned.replace("계좌 [내부 상태값]", "계좌 사용 가능 여부")
        cleaned = cleaned.replace("출금계좌의 [내부 상태값]이 사용 가능가 아님", "출금계좌가 사용 가능한 상태가 아님")
        cleaned = cleaned.replace("출금계좌의 [내부 상태값]이 사용 가능인지 확인하세요", "출금계좌가 사용 가능한 상태인지 확인하세요")
        cleaned = cleaned.replace("[[내부 상태값] 확인 결과]", "[사용 가능 여부 확인 결과]")
        cleaned = cleaned.replace("[내부 테이블] table definition", "업무 데이터 정의")
        cleaned = cleaned.replace("[내부 테이블] 테이블", "업무 데이터")
        cleaned = cleaned.replace("[내부 상태값] 및 [내부 상태값] 컬럼", "계좌 상태와 사용 가능 여부")
        cleaned = cleaned.replace("[내부 상태값] 컬럼", "업무 상태값")
        cleaned = cleaned.replace("`[내부 테이블]` 테이블", "업무 데이터")
        cleaned = cleaned.replace("`[내부 상태값]` 및 `[내부 상태값]` 컬럼", "계좌 상태와 사용 가능 여부")
        cleaned = cleaned.replace("`[내부 상태값]` 컬럼", "업무 상태값")
        cleaned = cleaned.replace("`[내부 상태값]`", "업무 상태값")
        cleaned = cleaned.replace("`[내부 코드]`", "업무 식별값")
        cleaned = cleaned.replace("`[내부 처리 로직]`", "[내부 처리 로직]")
        cleaned = cleaned.replace("`화면/업무 근거`", "화면/업무 근거")
        cleaned = re.sub(r"\((?:business_logic|frontend_event|backend_controller|sql_mapper|table_definition|incident)\)", "", cleaned)
        cleaned = re.sub(r"\b[A-Z]+(?:_[A-Z0-9]+)+\b", "[내부 코드]", cleaned)
        cleaned = cleaned.replace("[내부 코드]", "업무 식별값")
        cleaned = cleaned.replace("사용 가능 여부을", "사용 가능 여부를")
        cleaned = cleaned.replace("업무 데이터의 업무 식별값, 업무 식별값, 업무 상태값", "업무 데이터의 업무 식별값과 상태값")
    return cleaned


def sanitize_source(doc: KnowledgeDocument, user_role: str) -> Dict[str, object]:
    """Serialize a source citation safely for a user role."""
    data = {
        "doc_id": doc.id,
        "title": _safe_title(doc, user_role),
        "source_path": doc.source_path if user_role in {"it", "admin"} else "",
        "line_range": f"{doc.start_line}-{doc.end_line}",
        "reason": _safe_reason(doc, user_role),
        "retrieval_backend": doc.metadata.get("retrieval_backend"),
    }
    if user_role in {"it", "admin"}:
        data.update(
            {
                "api_path": doc.api_path,
                "class_name": doc.class_name,
                "method_name": doc.method_name,
                "sql_id": doc.sql_id,
                "tables": doc.tables,
            }
        )
    return data


def _safe_title(doc: KnowledgeDocument, user_role: str) -> str:
    if user_role in {"it", "admin"}:
        return doc.title
    if doc.screen_name:
        return f"{doc.screen_name} 관련 업무 규칙"
    if doc.doc_type == "sql_mapper":
        return "업무 데이터 조회 조건"
    if doc.doc_type == "business_logic":
        return "업무 처리 검증 규칙"
    return "업무 처리 근거"


def _safe_reason(doc: KnowledgeDocument, user_role: str) -> str:
    if user_role in {"it", "admin"}:
        return sanitize_answer(doc.summary, user_role)
    if doc.doc_type == "frontend_event":
        messages = ", ".join(doc.error_messages)
        return (
            "화면 입력값 확인과 사용자 안내 메시지를 근거로 확인했습니다."
            + (f" 표시 메시지: {messages}" if messages else "")
        )
    if doc.doc_type == "business_logic":
        return _business_logic_reason(doc)
    if doc.doc_type == "sql_mapper":
        return "업무 데이터 조회 또는 수정 조건을 근거로 확인했습니다."
    if doc.doc_type == "table_definition":
        return "업무 데이터 정의를 근거로 확인했습니다."
    if doc.doc_type == "backend_controller":
        return "화면 요청이 업무 처리 절차로 연결되는 근거가 있습니다."
    if doc.branch_guide:
        return sanitize_answer(doc.branch_guide, user_role)
    return sanitize_answer(doc.summary, user_role)


def _business_logic_reason(doc: KnowledgeDocument) -> str:
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
