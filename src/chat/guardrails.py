"""답변 가드레일 — 생성된 답변이 근거에 실제로 부합하는지 **프로그램으로** 검증 (E5 심화).

왜 필요한가
-----------
`service.SYSTEM_PROMPT` 의 "숫자는 근거 값 그대로" 는 **지시일 뿐 보증이 아니다** —
모델이 지키면 지켜지고 아니면 안 지켜진다(temperature 0.2 여도 확률적). 검색 임계
(`retriever`)는 *입력*을 통제하지만, *출력*이 그 입력에 부합하는지 확인하는 주체가
없었다. 이 모듈이 그 자리다: 유일하게 결정론적이고 **LLM 의 협조가 필요 없다**.

이 검증의 범위 (정직하게)
-------------------------
- ✅ **잡는 것**: 근거에 아예 없는 수치를 지어내는 것(fabrication).
- ❌ **못 잡는 것**: **근거에 있는 틀린 값을 고르는 것**(mis-selection). 근거에 40%와
  80%가 다 있으면 6개월 미만에 80%를 써도 통과한다. 표에서 행을 잘못 읽는 오류가
  정확히 이 유형이고, 하필 금융 문서에서 가장 흔한 실패다.
- ❌ **못 잡는 것**: 서술형 뒤집힘("양도 불가"→"양도 가능"). 숫자가 없어 검사에 안 걸린다.

→ 그러므로 이걸 통과했다고 "정확성 확보"라고 결론지으면 안 된다. 나머지는 검색 정밀도와
  **평가(`scripts/eval_answer.py`)** 로 관리한다.

구현 노트
---------
- 채점 스크립트와 **같은 구현을 공유**한다(`eval_answer.py` 가 이 모듈을 import).
  채점 기준과 운영 통제가 갈라지면 "평가는 통과하는데 운영은 막는" 상황이 생긴다.
- 허용 소스에 **질문 텍스트를 포함**한다. 답변이 질문의 "6개월 미만"을 되풀이하는
  것까지 위반으로 잡으면 false positive 가 나기 때문.
"""
from __future__ import annotations

import re

# 숫자 토큰(천단위 콤마·소수점 허용)과, 답변에서 '수치'로 취급할 단위.
_NUM = r"\d[\d,]*(?:\.\d+)?"
_UNIT = r"%|퍼센트|원|개월|년|일|회|만원|억"
_NUMUNIT = re.compile(rf"({_NUM})\s*(?:{_UNIT})")


def _norm(n: str) -> str:
    """천단위 콤마 제거 — 근거의 `1,000,000` 과 답변의 `1000000` 을 같게 본다."""
    return n.replace(",", "")


def number_violations(answer: str, sources_text: str, question: str = "") -> list[str]:
    """답변의 '숫자+단위' 중 근거·질문 어디에도 없는 값들(= 지어낸 수치 후보).

    근거 쪽은 단위를 요구하지 않고 **모든 숫자**를 허용 집합에 넣는다(관대한 판정).
    엄격하게 갈수록 false positive 가 늘고, 그건 곧 정상 답변이 거부로 죽는다는 뜻이라
    "지어낸 게 확실한 것만" 잡도록 의도적으로 느슨하게 뒀다.
    """
    allowed = {_norm(d) for d in re.findall(_NUM, sources_text)}
    allowed |= {_norm(d) for d in re.findall(_NUM, question)}
    return [m for m in _NUMUNIT.findall(answer) if _norm(m) not in allowed]


def sources_text(hits) -> str:
    """검증에 쓸 근거 원문(청크 body 전체를 이어붙임)."""
    return " ".join((h.payload.get("body", "") or "") for h in hits)
