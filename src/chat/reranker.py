"""검색 결과 재순위(cross-encoder reranker).

**왜 필요한가.** 실패를 분해해 보니(1,302문항 기준) 성격이 갈렸다:
    정답이 1등           80%
    top5 엔 있으나 1등 아님  7%   ← 여기
    top20 엔 있음          2%   ← 여기
    20위 안에도 없음        9%
즉 **실패의 약 3분의 1은 "이미 후보에 들어와 있는데 순서가 밀린 것"** 이다.
검색을 더 손댈 필요 없이 순서만 다시 매기면 되는 영역이고, 그게 리랭커다.

**dense 검색과 무엇이 다른가.** dense 는 질문과 문서를 **각각 따로** 벡터로 만들어
거리를 잰다(bi-encoder). 빠르지만 23만 개를 다 훑어야 하니 정밀도를 포기한 방식이다.
리랭커는 질문과 문서를 **한 쌍으로 같이** 모델에 넣어 관련도를 직접 매긴다
(cross-encoder). 훨씬 정확하지만 느려서 전수에는 못 쓴다.
→ **검색으로 후보 N개를 좁히고, 그 N개만 정밀 비교**하는 2단 구성이 표준이다.

모델: ``BAAI/bge-reranker-v2-m3`` — 임베딩 모델(KURE-v1)과 같은 BGE-M3 계열이라
한국어 금융 문서에 결이 맞고, 별도 학습 없이 쓸 수 있다.

⚠️ 점수 체계가 임베딩과 다르다(코사인 유사도가 아니라 logit). 그래서 **리랭커 점수를
`retrieval_score_threshold` 와 비교하면 안 된다.** 게이트(답할지 말지) 판정은 어디까지나
무필터 dense 점수로 하고, 리랭커는 **순서만** 바꾼다. 자세한 이유는 `retriever.py` 참조.
"""
from __future__ import annotations

import threading

from loguru import logger

_MODEL_NAME = "BAAI/bge-reranker-v2-m3"
_TRUNCATE = 512          # 토큰 상한. 길게 잡을수록 느려지는데 상품 식별엔 앞부분이면 충분하다.

_model = None
_lock = threading.Lock()


def _load():
    """모델을 지연 로딩한다(엔진 부팅을 늦추지 않기 위해).

    KURE-v1(약 2.2GB)이 이미 올라가 있는 상태에서 2.1GB 를 더 얹는다.
    18GB 머신에서는 여유가 많지 않으니, 리랭커를 끄는 설정을 반드시 남겨둔다.
    """
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from sentence_transformers import CrossEncoder

                # device 를 지정하지 않는다 — Embedder 와 동일하게 라이브러리
                # 자동 선택(MPS/CUDA/CPU)에 맡긴다.
                logger.info(f"리랭커 로딩: {_MODEL_NAME}")
                _model = CrossEncoder(_MODEL_NAME, max_length=_TRUNCATE)
                logger.info(f"리랭커 준비 완료 (device={_model.model.device})")
    return _model


def _passage(payload: dict) -> str:
    """리랭커에 넣을 문서 텍스트.

    payload ``body`` 만 넣으면 **상품이 뭔지 알 수 없는 조각**이 되는 경우가 많다
    (표 일부 등). 적재 때 임베딩에 들어간 것과 같은 형태로 헤더를 붙여 준다:
        ``[파일명] · 카테고리/문서종류``
    헤더는 payload 에 저장돼 있지 않으므로 저장된 필드로 재구성한다.
    """
    head = f"[{payload.get('source_file', '')}]"
    cat, dt = payload.get("category", ""), payload.get("doc_type", "")
    if cat or dt:
        head += f" · {cat}/{dt}".rstrip("/")
    return f"{head}\n{payload.get('body', '')}"


def rerank(question: str, hits: list, top_k: int) -> list:
    """``hits`` 를 질문과의 관련도로 다시 정렬해 상위 ``top_k`` 를 돌려준다.

    원본 점수(``hit.score``)는 **건드리지 않는다** — 감사 로그와 게이트가 그 값을
    쓰기 때문이다. 순서만 바꾼다.
    """
    if len(hits) <= 1:
        return hits[:top_k]
    model = _load()
    pairs = [(question, _passage(h.payload)) for h in hits]
    scores = model.predict(pairs, show_progress_bar=False)
    order = sorted(range(len(hits)), key=lambda i: -float(scores[i]))
    return [hits[i] for i in order[:top_k]]
