"""Chat domain — orchestration (E4). 검색 → 근거 프롬프트 → 생성 → 답변+출처.

Spring 의 ``@Service`` 대응. router(컨트롤러)는 얇게 두고 여기서 RAG 한 슬라이스를
지휘한다: retriever(E2)로 근거 청크를 찾고, 그 근거를 프롬프트로 조립해
generator(E3, Qwen)에 넘겨 답변을 만든 뒤 출처와 함께 돌려준다.

가드레일(E5)은 별도 단계가 아니라 **여기에 내장**한다(금융이라 처음부터):
- 근거강제: system 프롬프트로 "[근거] 안에서만 답하라" 지시.
- "모름" 경로: 검색 0건이면 LLM 호출 없이 즉시 모름 반환(환각 차단 + 비용 절약),
  근거가 있어도 답이 없으면 모델이 모름이라 말하도록 지시.
- 숫자 보존: 이율·금액은 근거 값 그대로 쓰고 계산/추정 금지(수치 변조 방지).
- 출처: 검색 청크를 Source 로 함께 반환(인용 검증용).
"""
from __future__ import annotations

import time

from loguru import logger

from src.chat.audit import record_query
from src.chat.generator import Generator
from src.chat.guardrails import number_violations, sources_text
from src.chat.retriever import Retriever
from src.chat.schemas import QueryRequest, QueryResponse, Source
from src.config import settings

_REFUSAL_MARK = "확인되지 않습니다"  # 거부 여부 로깅 판별용

# 가드레일 규칙(근거강제·"모름"·숫자보존·간결). 검색 근거는 [근거] 블록으로 user 에 붙는다.
SYSTEM_PROMPT = """너는 부산은행(BNK) 금융상품 고객상담 챗봇이다. 다음 규칙을 반드시 지켜라.

1. 답변은 오직 아래 [근거]에 있는 내용에만 기반한다. [근거]에 없는 내용은 지어내지 않는다.
2. [근거]에는 표(markdown)가 포함될 수 있고, 여러 상품의 자료가 섞여 있을 수 있다. 표의
   각 행·셀도 근거다(예: "| 양도 | 불가 |"). 답하기 전에 표 안까지 꼼꼼히 확인하고,
   질문이 특정 상품에 대한 것이면 그 상품의 근거로 답한다.
3. [근거]에서 답을 일부라도 찾을 수 있으면 반드시 그 내용으로 답한다. 답을 찾았다면
   "확인되지 않습니다" 같은 거부 문구를 절대 쓰지 않는다.
4. [근거]를 꼼꼼히 봐도 답이 전혀 없을 때만, 다른 말 없이 정확히 이 문장만 출력한다:
   "제공된 자료에서 확인되지 않습니다. 정확한 내용은 영업점 또는 고객센터로 문의해 주세요."
   이 거부 문장과 실제 답변을 동시에 내지 않는다 — 둘 중 하나만.
5. 이율·금액·기간·조건 등 숫자는 [근거]에 적힌 값을 그대로 사용한다. 계산·추정·반올림으로 바꾸지 않는다.
6. 한국어로, 간결하고 정확하게 답한다. 불필요한 인사말이나 사족은 넣지 않는다."""

# 검색 0건일 때 LLM 호출 없이 즉시 반환(규칙 2와 동일 문구).
_NO_CONTEXT_ANSWER = (
    "제공된 자료에서 확인되지 않습니다. "
    "정확한 내용은 영업점 또는 고객센터로 문의해 주세요."
)

# 방어: LLM 이 빈 content 를 줄 때(드묾, num_ctx 버그로 실제 겪음) 빈 문자열 노출 방지.
_EMPTY_FALLBACK = (
    "죄송합니다. 답변을 생성하지 못했습니다. "
    "정확한 내용은 영업점 또는 고객센터로 문의해 주세요."
)


def _build_prompt(question: str, hits) -> str:
    """검색 청크들을 번호 매긴 [근거] 블록 + [질문] 으로 조립.

    근거에는 청크 '본문 전체'를 넣는다(표·숫자 보존이 답변 정확도의 핵심) — 응답의
    ``Source.snippet``(200자 표시용)과 달리 여기선 자르지 않는다.
    """
    blocks = []
    for i, h in enumerate(hits, 1):
        p = h.payload
        head = f"[{p.get('product_name', '')} / {p.get('doc_type', '')} p.{p.get('page', 0)}]"
        body = (p.get("body", "") or "").strip()
        blocks.append(f"({i}) {head}\n{body}")
    context = "\n\n".join(blocks)
    return f"[근거]\n{context}\n\n[질문]\n{question}"


class ChatService:
    """RAG 오케스트레이터. retriever(E2)+generator(E3) 싱글톤을 주입받는다."""

    def __init__(self, retriever: Retriever, generator: Generator):
        self.retriever = retriever
        self.generator = generator

    def answer(self, req: QueryRequest) -> QueryResponse:
        t0 = time.time()
        hits = self.retriever.retrieve(
            req.question,
            top_k=req.top_k,
            category=req.category,
            product=req.product,
            doc_type=req.doc_type,
        )
        # 가드레일: 근거가 없으면 LLM 부르지 않고 즉시 "모름"(환각 차단 + 비용 절약).
        if not hits:
            logger.info(f"/query no-context refused q={req.question[:50]!r} {time.time()-t0:.1f}s")
            record_query(
                question=req.question, answer=_NO_CONTEXT_ANSWER, hits=[],
                grounded=True, violations=[], refused=True, latency_s=time.time() - t0,
            )
            return QueryResponse(answer=_NO_CONTEXT_ANSWER, sources=[], used_chunks=0)

        sources = [
            Source(
                product_name=h.payload.get("product_name", ""),
                doc_type=h.payload.get("doc_type", ""),
                source_file=h.payload.get("source_file", ""),
                page=h.payload.get("page", 0),
                section=h.payload.get("section", ""),
                snippet=(h.payload.get("body", "") or "").replace("\n", " ")[:200],
                score=round(h.score, 3),
            )
            for h in hits
        ]
        prompt = _build_prompt(req.question, hits)
        answer = self.generator.generate(prompt, system=SYSTEM_PROMPT)  # GeneratorError → router 503
        if not answer:  # 방어: 빈 content 면 안내문으로 폴백(빈 답변 노출 금지).
            logger.warning(f"/query empty-content fallback q={req.question[:50]!r}")
            answer = _EMPTY_FALLBACK

        # 가드레일(출력 통제): 답변의 수치가 근거에 실재하는지 프로그램 검증.
        # 프롬프트 지시와 달리 이건 모델 협조가 필요 없다. 위반이면 "정확하거나 모른다"
        # 원칙에 따라 **답변을 폐기**한다(추측을 내보내느니 모른다고 하는 편이 낫다).
        violations = number_violations(answer, sources_text(hits), req.question)
        grounded = not violations
        if violations:
            logger.warning(
                f"/query NUMBER-VIOLATION q={req.question[:50]!r} values={violations} "
                f"block={settings.guardrail_block_on_number_violation}"
            )
            if settings.guardrail_block_on_number_violation:
                answer = _NO_CONTEXT_ANSWER

        logger.info(
            f"/query q={req.question[:50]!r} chunks={len(sources)} "
            f"refused={_REFUSAL_MARK in answer} grounded={grounded} {time.time()-t0:.1f}s"
        )
        record_query(
            question=req.question, answer=answer, hits=hits,
            grounded=grounded, violations=violations,
            refused=_REFUSAL_MARK in answer, latency_s=time.time() - t0,
        )
        return QueryResponse(
            answer=answer, sources=sources, used_chunks=len(sources),
            grounded=grounded, violations=violations,
        )
