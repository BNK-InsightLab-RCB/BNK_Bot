"""Lightweight Korean branch-support query analyzer."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from backend.app.utils.text import unique_keep_order


SCREEN_HINTS = [
    "고객조회",
    "전표승인",
    "계좌이체",
    "휴면계좌 해제",
    "이체한도 변경",
    "체크카드 재발급",
    "대출 만기연장",
    "펀드 환매",
    "외화송금",
    "고액현금 인출 승인",
    "자동이체 등록",
    "기업뱅킹 사용자 등록",
    "잔액증명서 발급",
]
ACTION_HINTS = ["저장", "조회", "승인", "수정", "취소", "등록", "발급", "변경", "해제", "연장", "환매", "송금"]


@dataclass
class QueryIntent:
    """Structured query hints for retrieval."""

    query: str
    screen_name: Optional[str] = None
    screen_id: Optional[str] = None
    action: Optional[str] = None
    error_message: Optional[str] = None
    api_path: Optional[str] = None
    keywords: List[str] = field(default_factory=list)


class QueryAnalyzer:
    """Extract common banking UI troubleshooting hints from a question."""

    def analyze(self, question: str, screen_id: Optional[str] = None, screen_name: Optional[str] = None) -> QueryIntent:
        """Analyze a user question."""
        api_match = re.search(r"/api/[A-Za-z0-9_./-]+", question)
        quoted = re.findall(r"['\"]([^'\"]+)['\"]", question)
        detected_screen = screen_name or next((hint for hint in SCREEN_HINTS if hint in question), None)
        detected_action = next((hint for hint in ACTION_HINTS if hint in question), None)
        error_message = quoted[0] if quoted else _detect_error_message(question)
        keywords = unique_keep_order(re.findall(r"[A-Za-z0-9_]+|[가-힣]{2,}", question))
        return QueryIntent(
            query=question,
            screen_name=detected_screen,
            screen_id=screen_id,
            action=detected_action,
            error_message=error_message,
            api_path=api_match.group(0) if api_match else None,
            keywords=keywords,
        )


def _detect_error_message(question: str) -> Optional[str]:
    if "권한" in question:
        return "권한"
    if "조회되지" in question or "조회 안" in question:
        return "조회"
    if "해지" in question:
        return "해지"
    if "저장" in question and ("안" in question or "오류" in question):
        return "저장"
    return None
