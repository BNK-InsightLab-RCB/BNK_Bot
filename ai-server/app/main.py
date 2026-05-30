from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import documents, health, refine, search
from app.config import get_settings
from llm.mlx_client import MlxQwenClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.elasticsearch_client = None
    app.state.embedder = None
    app.state.llm = MlxQwenClient(settings.qwen_model_path)
    yield


app = FastAPI(
    title="BNK_Bot AI Server",
    description="Local RAG PoC server for document conversion, Qwen refinement, and hybrid search.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(documents.router)
app.include_router(refine.router)
app.include_router(search.router)

