"""질의에서 '건초더미를 줄일' 어휘 필터 토큰을 고른다.

**왜 필요한가.** 코퍼스가 9개 카테고리 234,050청크가 되면서 카테고리 분포가 극단적으로
기울었다(펀드 78.5% · 보험 17.1% · 예금 1.2%). dense 검색만으로는 청크 10~20개짜리
희귀 상품이 펀드 문서 더미에 파묻힌다. 실측으로 "양도성예금증서(CD)" 같은 질문은
임계 0.0 · top_k 50 으로 넓혀도 정답이 안 나왔다.

**해법.** 질의에서 상품명일 가능성이 높은 토큰을 골라 ``body`` 전문검색 필터를 걸고,
**순위는 dense 가 정하게** 둔다. 어휘로 범위를 좁히고 의미로 줄을 세우는 방식이다.

**측정(scripts/eval_retrieval_v2.py · 1,302문항 카테고리 층화):**
                       dense        어휘필터
    전체 pass@1     730 (56%)   1042 (80%)
    전체 pass@5     899 (69%)   1146 (88%)
    정확형(468)     303 (64%)    426 (91%)   ← 상품명을 정확히 말한 질문
    실전형(834)     427 (51%)    616 (73%)   ← 띄어쓰기·꼬리표제거·부분명
질의당 0.18초. **정확형과 실전형을 섞어 하나의 수치로 보지 말 것** — 난이도가 다르다.

⚠️ **하지 말 것으로 확인된 변형들** (전부 실측해서 악화됨):
  - RRF 로 dense 와 융합           → pass@1 53%→40% (15문항셋).
    Qdrant 전문검색은 **불리언 필터라 랭킹이 없다**. 임의 순서 후보를 융합하면
    잡음이 상위로 올라온다. 진짜 BM25 는 sparse vector 가 있어야 한다.
  - product_name 을 should(OR)로 추가 → pass@1 74%→64%, 지연 0.05→0.20s.
    OR 는 필터를 넓혀 축소 효과를 없애고, product_name 은 keyword 인덱스라
    MatchText 가 전수 스캔을 유발한다.
  - 조사 제거형 + 원형을 둘 다 후보로 → pass@1 74%→62%.
    후보가 늘면 짧고 흔한 토큰이 먼저 df 조건을 통과해 필터가 무뎌진다.

전제: 컬렉션에 전문검색 인덱스가 있어야 한다 — ``body``(MULTILINGUAL) +
``source_file``(**PREFIX**). 토크나이저 선택 근거는 `qdrant.py TEXT_INDEXED_FIELDS` 참조.
없으면 필터가 걸리지 않는다. **재적재·재임베딩은 불필요하다**(색인 재생성 2초).
"""
from __future__ import annotations

import re

from qdrant_client import models as m

# 이 범위를 벗어나는 토큰은 필터로 쓰지 않는다.
# 너무 흔하면(>DF_MAX) 건초더미가 안 줄고, 0건이면 정답을 원천 차단한다.
DF_MIN = 1
DF_MAX = 20_000

_TAIL = ("은", "는", "이", "가", "을", "를", "의", "에", "로", "으로", "와", "과",
         "도", "만", "이야", "인가요", "한가요", "야")

# 질문 어디에나 나오거나(의문사·서술어), 문서 종류를 가리킬 뿐 상품 식별력이 없는 말.
# 1차 측정에서 실제로 필터로 뽑혀 정확도를 떨어뜨린 것들을 근거로 넣었다.
_STOP = {
    # 의문사·서술어
    "알려줘", "있어", "있나요", "되나요", "어떤", "누구야", "얼마야", "어떻게", "무엇",
    "뭐야", "어디", "언제", "얼마", "왜", "인가", "되나", "가능해", "가능한가요",
    # 금융 일반명사 (모든 상품에 공통이라 변별력이 없다)
    "상품", "펀드", "보험", "카드", "서비스", "조건", "대상", "내용", "방법", "기간",
    "가입", "이용", "혜택", "금리", "수수료", "보장", "신탁", "대출", "통화", "환전",
    "납입기간", "이체한도", "환매수수료", "투자위험등급", "중도해지", "중도상환수수료",
    "상환", "연회비", "예금", "적금", "통장",
    # 법률·제도 용어. 상품명이 아닌데 **상품명보다 길어서** 필터로 뽑히던 것들.
    # 실측 사례: "마이플랜 퇴직연금 예금자보호가 되나요?" 에서 '예금자보호'(5자)가
    # '마이플랜'(4자)을 제치고 선택 → 파일명에 '예금자보호법'이 든 보험 안내장
    # 144건으로 좁혀져 정답을 놓쳤다(필터를 끄면 dense 는 정확히 찾는다).
    "예금자보호", "예금자보호법", "비과세종합저축", "금융소비자보호법", "개인정보처리방침",
    "청약철회", "위험등급", "예금보험공사",
    # 문서 종류·꼬리표
    "약정서", "추가약정서", "규약", "약관", "설명서", "투자설명서", "상품설명서",
    "안내장", "준법심의필", "계약서", "신청서", "통지서", "이용약관", "핵심",
    "부산은행", "모바일용", "웹용", "최종", "대면", "비대면", "개정", "적용",
}

_NUMERIC = re.compile(r"^[0-9]+$")
_WORD = re.compile(r"[가-힣A-Za-z0-9]{2,}")


def _strip_tail(t: str) -> str:
    for s in sorted(_TAIL, key=len, reverse=True):
        if len(t) > len(s) + 1 and t.endswith(s):
            return t[: -len(s)]
    return t


def candidate_tokens(question: str) -> list[str]:
    """상품명일 가능성이 높은 순으로 후보 토큰을 돌려준다.

    형태소 분석기를 쓰지 않는다(의존성 추가 없이 동작해야 하므로). 대신
    긴 토큰일수록 상품명일 확률이 높다는 경험칙을 쓴다.
    """
    raw = {_strip_tail(w) for w in _WORD.findall(question)}
    toks = [
        t for t in raw
        if t not in _STOP and len(t) >= 2 and not _NUMERIC.match(t)
        # 한글 3자 이상이거나 영문 약어(HF·BNK 등)여야 상품명일 가능성이 있다.
        and (len(re.findall(r"[가-힣]", t)) >= 3 or re.fullmatch(r"[A-Za-z]{2,}", t))
    ]
    # 길이 내림차순 · 동점은 사전순. set 순회 순서에 기대면 실행마다 결과가 달라진다
    # (실측: 같은 코드로 78/108 과 79/108 이 번갈아 나왔다).
    return sorted(set(toks), key=lambda t: (-len(t), t))


def body_filter(token: str) -> m.Filter:
    return m.Filter(must=[m.FieldCondition(key="body", match=m.MatchText(text=token))])


def source_filter(token: str) -> m.Filter:
    """파일명(= 컨텍스트 헤더의 상품 식별자)으로 좁히는 필터.

    **왜 body 보다 먼저 보는가.** 청크 헤더 ``[파일명] · 카테고리/문서종류`` 는
    임베딩 텍스트에만 들어가고 payload ``body`` 에는 없다. 그래서 body 만 검색하면
    **상품명이 본문에 등장하지 않는 문서를 영원히 못 찾는다** — 보험 안내장, 카드
    리플렛, 외환 약정서가 전부 그렇다(상품명이 파일명에만 있다).
    실측: pass@1 실패 28건 중 **24건**이 "body 에는 없고 파일명에는 있는" 경우였다.

    파일명 매칭이 성공하면 그 자체로 상품이 특정되므로 body 매칭보다 신뢰도가 높다.
    """
    return m.Filter(must=[m.FieldCondition(key="source_file", match=m.MatchText(text=token))])


def ensure_text_index(store) -> bool:
    """전문검색 인덱스(`TEXT_INDEXED_FIELDS`)를 보장한다. 있으면 아무 것도 안 한다.

    23만 청크 기준 body 20초 · source_file 2초. **재적재·재임베딩은 필요 없다** —
    payload 색인은 벡터와 완전히 별개다.
    클라이언트가 타임아웃으로 예외를 던져도 서버는 계속 만들고 있을 수 있으므로,
    예외를 삼키고 호출부에서 존재 여부로 판단한다.
    """
    from src.ingestion.qdrant import TEXT_INDEXED_FIELDS

    schema = store.client.get_collection(store.collection).payload_schema or {}
    missing = [f for f in TEXT_INDEXED_FIELDS if f not in schema]
    if not missing:
        return True
    for field in missing:
        try:
            store.client.create_payload_index(
                store.collection, field_name=field,
                field_schema=m.TextIndexParams(
                    type="text", tokenizer=TEXT_INDEXED_FIELDS[field],
                    min_token_len=2, max_token_len=30, lowercase=True),
            )
        except Exception:  # 타임아웃이어도 서버 쪽에서는 생성 중일 수 있다
            return False
    return True
