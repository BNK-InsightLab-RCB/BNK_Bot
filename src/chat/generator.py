"""Chat domain — answer generation (E3).

질문(E4 부터는 검색 근거 포함 프롬프트)을 받아 Qwen 으로 답변 문장을 만든다.
여기서 책임지는 건 **LLM 호출 어댑터** 하나뿐: Ollama 의 OpenAI 호환 엔드포인트로
호출하고, thinking 모드를 꺼서(``content`` 오염 방지 + 추론 지연 절약) 최종 답변
텍스트만 돌려준다.

- thinking off: Ollama 는 추론을 별도 ``reasoning_content`` 필드로 분리하므로 끄지
  않아도 ``content`` 엔 ``<think>`` 가 안 섞이지만, 불필요한 추론 토큰/지연을 막기
  위해 ``think=False`` 로 호출한다.
- 운영 전환: Ollama → vLLM/GPU 로 갈 때 ``config.llm_base_url`` 만 바꾸면 됨
  (둘 다 OpenAI 호환이라 이 코드는 불변).
- E4 에서 RAG 프롬프트(검색 sources 를 컨텍스트로)를 만들어 ``generate`` 에 넘기고,
  E5 가드레일(근거강제 · "모름" 경로 등)을 ``system`` 지시로 주입한다.

싱글톤으로 ``main.lifespan`` 에서 1회 생성해 ``app.state.generator`` 로 공유한다
(생성자는 OpenAI 클라이언트만 만들어 가볍다 — 실제 모델은 Ollama 가 lazy 로드).
"""
from __future__ import annotations

from openai import OpenAI

from src.config import settings


class Generator:
    def __init__(self) -> None:
        self.client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
        self.model = settings.llm_model

    def generate(
        self, prompt: str, system: str | None = None, temperature: float = 0.2
    ) -> str:
        """프롬프트 → 답변 텍스트(``content`` 만, thinking 제외).

        temperature 는 금융 답변 일관성을 위해 낮게(기본 0.2). ``system`` 은 역할/
        가드레일 지시 자리 — E4~E5 에서 근거강제 · "모름" 경로 · 출처표시 등을 여기에.
        """
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            extra_body={"think": False},  # 추론 비활성 — 지연↓, content 오염 방지
        )
        return (resp.choices[0].message.content or "").strip()
