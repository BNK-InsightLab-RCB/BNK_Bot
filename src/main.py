"""FastAPI application entry point — the BNK Bot CS chatbot engine.

This is the API layer that sits ON TOP of the existing pipeline:
- chat domain  : POST /query   (질문 → 검색 → Qwen 답변; E2 검색 연결됨, E3~E5 예정)
- ingestion    : POST /admin/* (적재 트리거; E6에서 기존 pipeline 호출)

Heavy resources (KURE model, Qdrant client) are built ONCE at startup
(``lifespan``) and shared via ``app.state`` — a singleton, not per-request.

Run (dev):  uvicorn src.main:app --reload --port 8000
Docs:       http://localhost:8000/docs
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from src.chat.retriever import Retriever
from src.chat.router import router as chat_router
from src.config import settings
from src.ingestion.embedder import Embedder
from src.ingestion.qdrant import QdrantStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup: load the embedding model + vector store ONCE (singleton).
    logger.info("Loading KURE embedder + Qdrant client (startup)...")
    embedder = Embedder()
    store = QdrantStore(
        url=settings.qdrant_url,
        collection=settings.qdrant_collection_name,
        dim=embedder.dim,  # forces model load now, not on first request
        api_key=settings.qdrant_api_key,
    )
    app.state.retriever = Retriever(embedder, store)
    logger.success(f"Engine ready. collection points={store.count()}")
    yield
    # shutdown: nothing to release for now.


app = FastAPI(title="BNK Bot Engine", version="0.2.0", lifespan=lifespan)

app.include_router(chat_router)


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}
