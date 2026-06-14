"""Application configuration.

The loader intentionally avoids requiring python-dotenv at import time so the
core parser tests can run in a bare Python environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


def _load_dotenv(path: str = ".env") -> Dict[str, str]:
    """Load a tiny subset of dotenv syntax without adding a hard dependency."""
    env_path = Path(path)
    values: Dict[str, str] = {}
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _get(name: str, default: str, dotenv_values: Dict[str, str]) -> str:
    return os.getenv(name, dotenv_values.get(name, default))


def _bool(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    """Runtime settings for local PoC services."""

    app_env: str = "local"
    app_port: int = 9000
    elastic_url: str = "http://localhost:9200"
    elastic_username: str = ""
    elastic_password: str = ""
    elastic_index: str = "ops_knowledge"
    sqlite_path: str = "./data/ops_rag.sqlite3"
    local_index_path: str = "./data/ops_knowledge.json"
    llm_base_url: str = "http://localhost:8000/v1"
    llm_api_key: str = "EMPTY"
    llm_model: str = "Qwen/Qwen3-14B-MLX-4bit"
    llm_timeout_seconds: int = 60
    embedding_model: str = "BAAI/bge-m3"
    embedding_batch_size: int = 4
    embedding_cache_path: str = "./data/embedding_cache.sqlite3"
    embedding_fallback_dim: int = 384
    max_retrieved_chunks: int = 12
    max_context_chars: int = 24000
    default_user_role: str = "branch"
    enable_llm_summary: bool = True
    enable_llm_chat: bool = False
    use_elasticsearch_search: bool = True
    enable_thinking_for_summary: bool = True
    enable_thinking_for_chat: bool = False
    mask_source_for_branch: bool = True


def load_settings() -> Settings:
    """Build settings from `.env` and environment variables."""
    dotenv_values = _load_dotenv()
    return Settings(
        app_env=_get("APP_ENV", "local", dotenv_values),
        app_port=int(_get("APP_PORT", "9000", dotenv_values)),
        elastic_url=_get("ELASTIC_URL", "http://localhost:9200", dotenv_values),
        elastic_username=_get("ELASTIC_USERNAME", "", dotenv_values),
        elastic_password=_get("ELASTIC_PASSWORD", "", dotenv_values),
        elastic_index=_get("ELASTIC_INDEX", "ops_knowledge", dotenv_values),
        sqlite_path=_get("SQLITE_PATH", "./data/ops_rag.sqlite3", dotenv_values),
        local_index_path=_get("LOCAL_INDEX_PATH", "./data/ops_knowledge.json", dotenv_values),
        llm_base_url=_get("LLM_BASE_URL", "http://localhost:8000/v1", dotenv_values),
        llm_api_key=_get("LLM_API_KEY", "EMPTY", dotenv_values),
        llm_model=_get("LLM_MODEL", "Qwen/Qwen3-14B-MLX-4bit", dotenv_values),
        llm_timeout_seconds=int(_get("LLM_TIMEOUT_SECONDS", "60", dotenv_values)),
        embedding_model=_get("EMBEDDING_MODEL", "BAAI/bge-m3", dotenv_values),
        embedding_batch_size=int(_get("EMBEDDING_BATCH_SIZE", "4", dotenv_values)),
        embedding_cache_path=_get(
            "EMBEDDING_CACHE_PATH", "./data/embedding_cache.sqlite3", dotenv_values
        ),
        embedding_fallback_dim=int(_get("EMBEDDING_FALLBACK_DIM", "384", dotenv_values)),
        max_retrieved_chunks=int(_get("MAX_RETRIEVED_CHUNKS", "12", dotenv_values)),
        max_context_chars=int(_get("MAX_CONTEXT_CHARS", "24000", dotenv_values)),
        default_user_role=_get("DEFAULT_USER_ROLE", "branch", dotenv_values),
        enable_llm_summary=_bool(_get("ENABLE_LLM_SUMMARY", "true", dotenv_values)),
        enable_llm_chat=_bool(_get("ENABLE_LLM_CHAT", "false", dotenv_values)),
        use_elasticsearch_search=_bool(
            _get("USE_ELASTICSEARCH_SEARCH", "true", dotenv_values)
        ),
        enable_thinking_for_summary=_bool(
            _get("ENABLE_THINKING_FOR_SUMMARY", "true", dotenv_values)
        ),
        enable_thinking_for_chat=_bool(_get("ENABLE_THINKING_FOR_CHAT", "false", dotenv_values)),
        mask_source_for_branch=_bool(_get("MASK_SOURCE_FOR_BRANCH", "true", dotenv_values)),
    )


settings = load_settings()
