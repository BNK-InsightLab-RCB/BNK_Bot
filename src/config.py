from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection_name: str = "bnk_bot_collection"

    # LLM (답변 생성: Ollama 로컬, OpenAI 호환 엔드포인트로 호출.
    # 운영 전환 시 vLLM/GPU 로 base_url 만 교체하면 됨 — 코드 불변.)
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"  # Ollama 는 키 검증 안 함 (더미; OpenAI SDK 가 빈 키를 거부해서 채움)
    llm_model: str = "qwen3.5-bnk"  # Modelfile 파생(num_ctx=16384); base는 qwen3.5:9b
    llm_timeout_s: float = 120.0  # LLM 호출 타임아웃(초). 큰 표 답변 ~30s + 동시적재 슬로다운 여유

    # 검색 결과 채택 하한(cosine). 이 아래 점수는 '근거 없음'으로 보고 버린다.
    # → 무관 질문이 LLM 에 도달하기 전에 **결정론적으로** 거부된다(모델 협조에 의존 X).
    # 보정 근거(scripts/measure_score_threshold.py, 1551청크 기준):
    #   IN(답 가능 20문항)  min 0.6415 / median 0.7133
    #   OUT(도메인 밖 10문항) max 0.5063 / median 0.4575   → gap +0.135 로 분리됨
    # 0.55 는 OUT.max 위, IN.min 아래로 양쪽에 여유를 둔 값(정상 답변을 죽이는 쪽이
    # 더 나쁘므로 IN 쪽 여유를 크게: IN 까지 0.09, OUT 까지 0.04).
    # ⚠️ 코퍼스가 바뀌면 OUT.max 가 올라갈 수 있다 → **적재 후 반드시 재보정**.
    retrieval_score_threshold: float = 0.55

    # 답변 숫자가 근거에 없을 때(= 지어낸 수치 후보) 답변을 폐기하고 "모름"으로 돌릴지.
    # True = 사용자 확정 원칙("정확하거나 모른다")을 코드로 강제. False 로 두면 위반을
    # 로그·응답 필드로만 알리고 답변은 그대로 내보낸다(관찰 모드).
    guardrail_block_on_number_violation: bool = True

    # Paths
    base_dir: Path = Path(__file__).parent.parent
    data_dir: Path = base_dir / "data"
    # 원본 문서 루트. 적재가 닿을 수 있는 경로의 **상한(보안 경계)** 이기도 하다 —
    # `/admin/ingest` 의 root 는 반드시 이 아래여야 한다(임의 경로 스캔 차단).
    #
    # 기본값은 **프로젝트 기준 상대경로**(`BNK_Bot/../Data_PDF`). 특정 머신의 절대경로를
    # 박아두면 clone 한 쪽에서 조용히 깨진다. 다른 위치면 `.env` 의 `DATA_ROOT` 로 지정
    # (`.env.example` 참조).
    data_root: Path = base_dir.parent / "Data_PDF"
    # 기본 적재 대상. 지정하지 않으면 `data_root` 전체를 쓴다(아래 validator).
    # 일부만 적재하려면 `RAW_DIR` 로 하위 경로를 지정 — 단 `data_root` 안이어야 한다.
    raw_dir: Path | None = None
    processed_dir: Path = data_dir / "processed"
    chunks_dir: Path = data_dir / "chunks"
    failed_dir: Path = data_dir / "failed"
    logs_dir: Path = base_dir / "logs"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def _default_raw_dir(self):
        """`raw_dir` 미지정 시 `data_root` 를 따라가게 한다.

        ⚠️ 예전엔 `raw_dir: Path = data_root` 로 써뒀는데, 이건 **클래스 정의 시점의
        기본값을 복사**하는 것이라 `.env` 로 `DATA_ROOT` 를 바꿔도 `raw_dir` 은 옛 경로에
        머물렀다. 그러면 `/admin/ingest` 를 root 없이 호출했을 때 존재하지 않는 경로를
        적재하려 해 조용히 실패한다(경계 검사는 통과시키므로 원인도 안 보인다).
        """
        if self.raw_dir is None:
            self.raw_dir = self.data_root
        return self

settings = Settings()
