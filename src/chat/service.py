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

from src.chat.generator import Generator
from src.chat.retriever import Retriever
from src.chat.schemas import QueryRequest, QueryResponse, Source

# 가드레일 규칙(근거강제·"모름"·숫자보존·간결). 검색 근거는 [근거] 블록으로 user 에 붙는다.
SYSTEM_PROMPT = """너는 부산은행(BNK) 금융상품 고객상담 챗봇이다. 다음 규칙을 반드시 지켜라.

1. 답변은 오직 아래 [근거]에 있는 내용에만 기반한다. [근거]에 없는 내용은 지어내지 않는다.
2. [근거]에는 표(markdown 형식)가 포함될 수 있다. 표의 각 행·셀도 근거이므로, 답하기
   전에 표 안의 항목까지 꼼꼼히 확인한다(예: "| 양도 | 불가 |" 같은 행).
3. [근거]를 충분히 확인해도 질문의 답이 없을 때만, 추측하지 말고 정확히 이렇게 답한다:
   "제공된 자료에서 확인되지 않습니다. 정확한 내용은 영업점 또는 고객센터로 문의해 주세요."
4. 이율·금액·기간·조건 등 숫자는 [근거]에 적힌 값을 그대로 사용한다. 계산·추정·반올림으로 바꾸지 않는다.
5. 한국어로, 간결하고 정확하게 답한다. 불필요한 인사말이나 사족은 넣지 않는다."""

# 검색 0건일 때 LLM 호출 없이 즉시 반환(규칙 2와 동일 문구).
_NO_CONTEXT_ANSWER = (
    "제공된 자료에서 확인되지 않습니다. "
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
        hits = self.retriever.retrieve(
            req.question,
            top_k=req.top_k,
            category=req.category,
            product=req.product,
            doc_type=req.doc_type,
        )
        # 가드레일: 근거가 없으면 LLM 부르지 않고 즉시 "모름"(환각 차단 + 비용 절약).
        if not hits:
            return QueryResponse(answer=_NO_CONTEXT_ANSWER, sources=[], used_chunks=0)

        sources = [
            Source(
                product_name=h.payload.get("product_name", ""),
                doc_type=h.payload.get("doc_type", ""),
                page=h.payload.get("page", 0),
                section=h.payload.get("section", ""),
                snippet=(h.payload.get("body", "") or "").replace("\n", " ")[:200],
                score=round(h.score, 3),
            )
            for h in hits
        ]
        prompt = _build_prompt(req.question, hits)
        answer = self.generator.generate(prompt, system=SYSTEM_PROMPT)
        return QueryResponse(answer=answer, sources=sources, used_chunks=len(sources))
