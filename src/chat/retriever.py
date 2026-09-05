"""Chat domain — retrieval. Question → top-k chunks from Qdrant.

Thin wrapper that reuses the ingestion-side infra (``Embedder`` + ``QdrantStore``)
for the READ path. Held as a singleton in ``app.state`` (built once at startup
in ``main.lifespan``) so the heavy KURE model is loaded only once.
"""
from __future__ import annotations

from loguru import logger

from src.chat import lexical
from src.config import settings
from src.ingestion.embedder import Embedder
from src.ingestion.qdrant import QdrantStore


class Retriever:
    """질문 → top-k 근거 청크.

    ``score_threshold`` 를 항상 적용한다(기본 ``settings.retrieval_score_threshold``).
    이게 **"모르면 모른다"의 결정론적 절반**이다 — 임계 아래면 빈 리스트가 되고
    ``ChatService`` 가 LLM 호출 없이 즉시 거부한다. 임계가 없던 시절엔 무관 질문에도
    항상 5청크가 붙어 나가서, 거부 여부가 전적으로 모델 판단에 맡겨져 있었다.

    **어휘 필터(hybrid).** 코퍼스가 234,050청크가 되면서 카테고리가 극단적으로
    기울어(펀드 78.5% · 예금 1.2%) 희귀 상품이 dense 검색에서 파묻힌다.
    질의에서 상품명일 만한 토큰을 골라 ``body`` 전문검색으로 범위를 좁힌 뒤
    dense 로 순위를 매긴다. 근거·측정치·**하면 안 되는 변형들**은 ``lexical.py`` 참조.
    """

    def __init__(self, embedder: Embedder, store: QdrantStore,
                 score_threshold: float | None = None,
                 use_lexical: bool | None = None,
                 use_reranker: bool | None = None):
        self.embedder = embedder
        self.store = store
        self.score_threshold = (
            settings.retrieval_score_threshold if score_threshold is None else score_threshold
        )
        self.use_lexical = (
            settings.retrieval_use_lexical_filter if use_lexical is None else use_lexical
        )
        self.use_reranker = (
            settings.retrieval_use_reranker if use_reranker is None else use_reranker
        )
        self._df: dict[str, int] = {}      # 토큰 문서빈도 캐시(질의마다 재계산 방지)
        if self.use_lexical and not lexical.ensure_text_index(store):
            logger.warning("body 전문검색 인덱스를 만들지 못했다 — 어휘 필터가 무력화된다")

    def _count(self, key: str, tok: str, make) -> int:
        ck = f"{key}:{tok}"
        if ck not in self._df:
            try:
                self._df[ck] = self.store.client.count(
                    self.store.collection, exact=True, count_filter=make(tok)).count
            except Exception as e:                     # 인덱스 부재 등
                logger.debug(f"어휘 필터 df 조회 실패({key},{tok}): {e}")
                self._df[ck] = -1
        return self._df[ck]

    def _pick_filter(self, question: str):
        """쓸 만한 어휘 필터를 고른다. 없으면 ``None``(= dense 단독으로 폴백).

        **파일명(source_file) 을 먼저 본다.** 청크 헤더가 임베딩에만 들어가고 payload
        ``body`` 에는 없어서, body 만 보면 상품명이 본문에 안 나오는 문서를 못 찾는다.
        실측: pass@1 실패 28건 중 24건이 그 경우였다(`lexical.source_filter` 참조).
        파일명이 걸리면 상품이 특정된 것이므로 body 보다 신뢰도가 높다.

        폴백이 중요한 이유: 필터가 빗나가면 정답을 **원천 차단**한다.
        좁혀서 못 찾느니 넓게라도 찾는 편이 낫다.
        """
        toks = lexical.candidate_tokens(question)[:4]
        for key, make in (("source_file", lexical.source_filter),
                          ("body", lexical.body_filter)):
            # 길이 내림차순으로 보되, **df 상한을 필드별로 다르게** 건다.
            #
            # 왜 길이 우선을 유지하나: 상품명은 대체로 질의에서 가장 긴 토큰이다.
            # df 최소로 바꿔 봤더니 특정 사례는 고쳐졌지만 전체는 86%→85% 로 내려갔다.
            #
            # 왜 df 상한이 필요한가: 길이 경험칙이 깨지는 사례가 있다.
            #   "마이플랜 퇴직연금 예금자보호가 되나요?"
            #     → '예금자보호'(5자) 가 '마이플랜'(4자) 보다 길어 선택되는데,
            #       그건 상품명이 아니라 **일반 법률용어**다(파일명 144건에 등장).
            #       보험 안내장 더미로 좁혀져 정답을 놓쳤다.
            # 해결책으로 시도했다가 **기각한 것들**(전부 실측):
            #   df 최소 토큰 선택        → 86%→85%  (희귀하지만 엉뚱한 조각이 뽑힌다)
            #   파일명 df 상한 100      → 86%→83%  (정당한 상품명까지 잘린다)
            # 채택: 길이 우선을 유지하고, '예금자보호' 같은 **일반 용어는 _STOP 으로**
            # 걸러낸다(lexical.py). 그 목록에 이미 약관·설명서 등이 같은 이유로 들어 있다.
            for tok in toks:
                n = self._count(key, tok, make)
                if lexical.DF_MIN <= n <= lexical.DF_MAX:
                    return make(tok), f"{tok}@{key}"
        return None

    def retrieve(
        self,
        question: str,
        top_k: int = 5,
        category: str | None = None,
        product: str | None = None,
        doc_type: str | None = None,
        score_threshold: float | None = None,
        use_lexical: bool | None = None,
        use_reranker: bool | None = None,
    ):
        """Return Qdrant ScoredPoints (payload + score) for the question.

        Optional exact-match payload filters (category/doc_type are folder-derived
        values like 예금/설명서; product must match stored product_name exactly).
        ``score_threshold`` 를 명시하면 이번 호출만 다른 하한을 쓴다(보정·측정용).
        ``use_reranker=False`` 면 이번 호출만 재순위를 끈다(A/B 측정용).
        ``use_lexical=False`` 면 이번 호출만 어휘 필터를 끈다 — **임계 보정 도구는
        게이트(무필터 dense)를 재야 하므로 반드시 이걸 쓴다.** 필터된 결과의 점수로
        임계를 잡으면 게이트가 실제로 하는 일과 다른 것을 재게 된다.
        """
        lex_on = self.use_lexical if use_lexical is None else use_lexical
        flt = QdrantStore.build_filter(
            category=category, product_name=product, doc_type=doc_type
        )
        query_vec = self.embedder.embed_query(question)
        thr = self.score_threshold if score_threshold is None else score_threshold

        # ── 게이트와 검색을 **분리**한다. 이유(실측):
        # 어휘 필터를 켜면 IN 질문의 top1 점수가 내려간다(min 0.6245 → 0.4664).
        # 좁힌 집합 안의 최고점은 전역 최고점보다 낮을 수밖에 없기 때문이다.
        # 그래서 필터 결과에 임계를 그대로 적용하면 **정상 질문이 거부된다**
        # (임계를 0.44 로 낮추면 무관 질문 차단이 9/10 → 4/10 으로 무너진다).
        #
        # 두 질문은 원래 별개다:
        #   ① "코퍼스에 관련된 게 있기는 한가"  → 무필터 dense + 임계 (게이트)
        #   ② "그중 어느 청크가 가장 맞나"      → 어휘 필터 + dense (검색)
        # ①로 답할지 말지를 정하고, ②로 무엇을 근거로 줄지 정한다.
        # 리랭커를 쓸 때는 후보를 넉넉히 뽑아 둔다 — 재정렬은 **가져온 것 안에서만**
        # 순서를 바꾸므로, top_k 만 가져오면 건질 게 없다.
        rr_on = self.use_reranker if use_reranker is None else use_reranker
        n_cand = max(top_k, settings.retrieval_rerank_candidates) if rr_on else top_k

        gate = self.store.search(query_vec, top_k=n_cand, flt=flt, score_threshold=thr)

        lex_hits, tok = None, None
        if lex_on and flt is None:
            picked = self._pick_filter(question)
            if picked:
                lex_flt, tok = picked
                # 게이트 판정과 별개로 좁힌 집합에서도 뽑아 둔다.
                # 임계를 걸지 않는 이유: 게이트가 이미 관련성을 판정했고,
                # 질의 토큰이 본문에 실재한다는 것 자체가 강한 신호이기 때문.
                lex_hits = self.store.search(query_vec, top_k=n_cand, flt=lex_flt,
                                             score_threshold=0.0)

        if not gate:
            # ── 구제 경로. 게이트는 전역 dense 라, 청크 10~20개짜리 희귀 상품은
            # 23만 청크 평균에 눌려 임계를 못 넘는다(실측: "회전플러스정기예금 특징?"
            # 게이트 탈락 → 어휘 필터 안에서는 0.787).
            # **좁힌 집합에서 임계를 넘으면** 관련 문서가 있다는 증거로 인정한다.
            # 구제에도 같은 임계를 걸어야 무관 질문이 새지 않는다 — 실측으로 OUT 중
            # 희귀 토큰을 가진 3건(파이썬 df=1 · 아이폰 df=3 · KTX df=5)은 필터 후
            # 점수가 0.32~0.54 라 전부 차단된다.
            if lex_hits and lex_hits[0].score >= thr:
                logger.debug(f"게이트 탈락 → 어휘 필터 '{tok}' 로 구제 "
                             f"(top1={lex_hits[0].score:.3f})")
                return self._finish(question, lex_hits, top_k, rr_on)
            return []                      # 결정론적 거부 — LLM 호출 없음

        if lex_hits:
            logger.debug(f"어휘 필터 '{tok}' 적용 → {len(lex_hits)}건")
            return self._finish(question, lex_hits, top_k, rr_on)
        return self._finish(question, gate, top_k, rr_on)

    def _finish(self, question: str, hits: list, top_k: int, rr_on: bool) -> list:
        """후보를 최종 top_k 로 줄인다. 리랭커가 켜져 있으면 순서를 다시 매긴다.

        ⚠️ **게이트 판정이 끝난 뒤에만** 부른다. 리랭커 점수는 코사인 유사도가 아니라
        logit 이라 `retrieval_score_threshold` 와 비교하면 안 된다 — "답할지 말지"는
        무필터 dense 점수로 이미 정해졌고, 여기서는 **순서만** 바꾼다.
        """
        if not rr_on or len(hits) <= 1:
            return hits[:top_k]
        try:
            from src.chat import reranker
            return reranker.rerank(question, hits, top_k)
        except Exception as e:
            # 리랭커는 **품질 향상 장치이지 필수 경로가 아니다.** 모델 로딩 실패나
            # 메모리 부족으로 챗봇 전체가 멈추면 안 되므로 원래 순서로 폴백한다.
            logger.warning(f"리랭킹 실패 — 원래 순서 사용: {e}")
            return hits[:top_k]
