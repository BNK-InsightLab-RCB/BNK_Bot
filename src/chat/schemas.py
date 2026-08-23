"""Chat domain DTOs (request/response). FastAPI's equivalent of Spring DTOs."""
from __future__ import annotations

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="고객 질문")
    top_k: int = Field(5, ge=1, le=20, description="검색할 청크 수")
    # optional payload filters (Qdrant) — 상품/카테고리/문서종류 한정 검색
    category: str | None = None
    product: str | None = None
    doc_type: str | None = None


class Source(BaseModel):
    """답변 근거(출처) — payload에서 채움. 환각 검증·인용 표시에 사용.

    ``source_file`` 을 포함하는 이유: 문서의 **현행 여부는 엔진이 판단하지 않는다.**
    `(개정전)`/`(개정후)` 같은 건 파일명 라벨일 뿐이고 문서 본문에는 시행일조차 없는
    경우가 많다(실측). 엔진이 추측으로 자료를 걸러내면 멀쩡한 현행 약관을 근거 없이
    버릴 수 있으므로, **자료는 전부 색인하고 어느 파일에서 나왔는지를 노출**해
    운영자·상위 시스템이 판단하게 한다.
    """

    product_name: str
    doc_type: str
    source_file: str    # 원본 파일명 — 판본 식별의 유일한 단서
    page: int
    section: str
    snippet: str
    score: float


class QueryResponse(BaseModel):
    """답변 + 출처 + **검증 결과**.

    `grounded`/`violations` 는 가드레일의 관측 창이다 — 상위(SpringBoot·관리자 화면)가
    "이 답변이 근거 검증을 통과했는가"를 판단하거나 감사 로그에 남길 수 있게 한다.
    (필드 구성은 납품처 API 규격 확정 시 바뀔 수 있는 부분.)
    """

    answer: str
    sources: list[Source] = []
    used_chunks: int = 0
    grounded: bool = True          # 숫자 검증 통과 여부
    violations: list[str] = []     # 근거에 없던 수치(있으면 답변이 폐기됐을 수 있음)
