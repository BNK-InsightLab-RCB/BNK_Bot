from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    elasticsearch_url: str
    elasticsearch_index: str
    kure_model_path: str
    qwen_model_path: str
    refined_markdown_dir: Path
    embedding_dim: int
    chunk_size: int
    chunk_overlap: int


def get_settings() -> Settings:
    load_dotenv(ROOT_DIR / ".env")
    model_path = os.getenv("KURE_MODEL_PATH", "models/KURE-v1")
    resolved_model_path = Path(model_path)
    if not resolved_model_path.is_absolute():
        resolved_model_path = ROOT_DIR / resolved_model_path
    refined_markdown_dir = Path(os.getenv("REFINED_MARKDOWN_DIR", "data/refined_markdown"))
    if not refined_markdown_dir.is_absolute():
        refined_markdown_dir = ROOT_DIR / refined_markdown_dir

    return Settings(
        elasticsearch_url=os.getenv("ELASTICSEARCH_URL", "http://localhost:9200"),
        elasticsearch_index=os.getenv("ELASTICSEARCH_INDEX", "bnk_bot_chunks"),
        kure_model_path=str(resolved_model_path),
        qwen_model_path=os.getenv("QWEN_MODEL_PATH", "Qwen/Qwen3-14B-MLX-4bit"),
        refined_markdown_dir=refined_markdown_dir,
        embedding_dim=int(os.getenv("EMBEDDING_DIM", "1024")),
        chunk_size=int(os.getenv("CHUNK_SIZE", "1000")),
        chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "120")),
    )
