from __future__ import annotations

from pathlib import Path

from fastapi import Request

from app.config import ROOT_DIR, Settings
from rag.elastic_index import create_client
from rag.embedder import KureEmbedder


def resolve_repo_path(path_value: str) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = ROOT_DIR / path
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT_DIR.resolve())
    except ValueError as exc:
        raise ValueError(f"Path must be inside repository root: {path_value}") from exc
    return resolved


def get_settings_from_app(request: Request) -> Settings:
    return request.app.state.settings


def get_elasticsearch_client(request: Request):
    client = getattr(request.app.state, "elasticsearch_client", None)
    if client is None:
        client = create_client(request.app.state.settings.elasticsearch_url)
        request.app.state.elasticsearch_client = client
    return client


def get_embedder(request: Request) -> KureEmbedder:
    embedder = getattr(request.app.state, "embedder", None)
    if embedder is None:
        embedder = KureEmbedder(request.app.state.settings.kure_model_path)
        request.app.state.embedder = embedder
    return embedder


def get_llm(request: Request):
    return request.app.state.llm

