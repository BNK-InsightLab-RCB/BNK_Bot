from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

class Settings(BaseSettings):
    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection_name: str = "bnk_bot_collection"

    # LLM
    llm_api_key: str | None = None
    llm_model: str = "gpt-4o"

    # Paths
    base_dir: Path = Path(__file__).parent.parent
    data_dir: Path = base_dir / "data"
    raw_dir: Path = data_dir / "raw"
    processed_dir: Path = data_dir / "processed"
    chunks_dir: Path = data_dir / "chunks"
    failed_dir: Path = data_dir / "failed"
    logs_dir: Path = base_dir / "logs"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
