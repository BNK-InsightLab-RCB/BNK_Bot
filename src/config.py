from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

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

    # Paths
    base_dir: Path = Path(__file__).parent.parent
    data_dir: Path = base_dir / "data"
    raw_dir: Path = Path("/Users/jhyeong/Project/InsightLab/Data_PDF/예금")
    processed_dir: Path = data_dir / "processed"
    chunks_dir: Path = data_dir / "chunks"
    failed_dir: Path = data_dir / "failed"
    logs_dir: Path = base_dir / "logs"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
