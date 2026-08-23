"""Chat domain — answer generation (E3).

질문(E4 부터는 검색 근거 포함 프롬프트)을 받아 Qwen 으로 답변 문장을 만든다.
여기서 책임지는 건 **LLM 호출 어댑터** 하나뿐: Ollama 의 OpenAI 호환 엔드포인트로
호출하고, thinking 모드를 꺼서(추론 지연 절약) 최종 답변 텍스트만 돌려준다.

- thinking off: ``reasoning_effort="none"`` 으로 호출(OpenAI 표준 파라미터). E4
  진단에서 ``think=False`` / ``/no_think`` / ``chat_template_kwargs`` 는 Ollama
  OpenAI-compat 엔드포인트에서 무시됐고, ``reasoning_effort="none"`` 만 추론을
  실제로 껐다. 켜두면 답변당 5천 토큰을 추론에 써 90~230초가 걸린다(끄면 ~2초).
- num_ctx: 큰 표 근거가 4천 토큰을 넘어 Ollama 기본 창(4096)에선 답변이 비어
  나온다 → 파생 모델 ``qwen3.5-bnk``(Modelfile, num_ctx=16384)를 쓴다.
- 운영 전환: Ollama → vLLM/GPU 로 갈 때 ``config.llm_base_url`` 만 바꾸면 됨
  (둘 다 OpenAI 호환이라 이 코드는 불변. num_ctx 는 vLLM 의 --max-model-len 으로,
  reasoning_effort 는 동일 파라미터로 이어진다).
- E4 에서 RAG 프롬프트(검색 sources 를 컨텍스트로)를 만들어 ``generate`` 에 넘기고,
  E5 가드레일(근거강제 · "모름" 경로 등)을 ``system`` 지시로 주입한다.

싱글톤으로 ``main.lifespan`` 에서 1회 생성해 ``app.state.generator`` 로 공유한다
(생성자는 OpenAI 클라이언트만 만들어 가볍다 — 실제 모델은 Ollama 가 lazy 로드).
"""
from __future__ import annotations

from openai import APIError, OpenAI

from src.config import settings


class GeneratorError(RuntimeError):
    """LLM 호출 실패(타임아웃·연결 불가·서버 오류). router 에서 503 으로 매핑."""


class Generator:
    def __init__(self) -> None:
        # timeout: Ollama 가 느리거나 죽었을 때 /query 가 무한 대기하지 않도록 상한.
        self.client = OpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout=settings.llm_timeout_s,
        )
        self.model = settings.llm_model

    def generate(
        self, prompt: str, system: str | None = None, temperature: float = 0.0
    ) -> str:
        """프롬프트 → 답변 텍스트(``content`` 만, thinking 제외).

        **temperature 는 0.0(결정론)이 기본이다.** 원래 0.2 였는데, 같은 질문·같은 근거로
        5회 돌린 실측에서 답이 세 갈래로 갈렸고 그중 둘이 **틀렸다**:
          "저탄소실천적금 개인형 우대이율 최대?" → (3회) "최대 0.50%p" ✅
                                                → (2회) "탄소포인트제 0.20%p 가 가장 높으므로…" ❌
        후자는 **개별 항목의 최댓값을 전체 최대 우대이율로 오인**한 것이다. 게다가 `0.20` 은
        근거에 실재하는 숫자라 **숫자 가드레일을 그대로 통과**한다(= guardrails 가 못 잡는
        mis-selection 유형의 실제 사례). temperature 0.0 에서는 5/5 동일·정답이었다.

        금융 상담에서 온도를 두는 이득(표현 다양성)은 없고, 손실은 크다 —
        같은 질문에 다른 답이 나가면 재현·감사·회귀측정이 모두 무너진다.
        (평가 점수 자체도 실행마다 흔들려 회귀 판정이 불가능해진다.)

        ``system`` 은 역할/가드레일 지시 자리 — 근거강제 · "모름" 경로 등을 여기에.
        """
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                # 추론 비활성: 이 엔드포인트에선 reasoning_effort 만 먹힘(~2s vs 90s+).
                extra_body={"reasoning_effort": "none"},
            )
        except APIError as e:  # 타임아웃·연결불가·LLM 서버오류 → 도메인 예외로 변환
            raise GeneratorError(f"LLM call failed: {e}") from e
        return (resp.choices[0].message.content or "").strip()
