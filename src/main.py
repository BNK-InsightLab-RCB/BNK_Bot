"""FastAPI application entry point — the BNK Bot CS chatbot engine.

This is the API layer that sits ON TOP of the existing pipeline:
- chat domain  : POST /query        (질문 → 검색 → Qwen 답변+출처; E1~E5)
- ingestion    : POST /admin/ingest (적재 비동기 트리거 + 상태조회; E6)

Heavy resources (KURE model, Qdrant client) are built ONCE at startup
(``lifespan``) and shared via ``app.state`` — a singleton, not per-request.

Run (dev):  uvicorn src.main:app --reload --port 8000
Docs:       http://localhost:8000/docs
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from src.chat.generator import Generator
from src.chat.retriever import Retriever
from src.chat.router import router as chat_router
from src.chat.service import ChatService
from src.config import settings
from src.ingestion.embedder import Embedder
from src.ingestion.jobs import JobRegistry
from src.ingestion.qdrant import QdrantStore
from src.ingestion.router import router as admin_router


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
    retriever = Retriever(embedder, store)
    # LLM 어댑터(가벼움; 클라이언트만 생성, 모델은 Ollama 가 첫 호출 시 lazy 로드).
    generator = Generator()
    app.state.retriever = retriever
    app.state.generator = generator
    # RAG 오케스트레이터(E4): 검색→근거 프롬프트→Qwen→답변+출처. router 가 이걸 호출.
    app.state.chat_service = ChatService(retriever, generator)
    # 적재 job 레지스트리(E6): /admin/ingest 가 적재를 별도 스레드로 돌리고 상태를 여기에.
    # 가벼움(자원 미로딩) — 적재 스레드가 자체 KURE/Qdrant 를 따로 만든다.
    app.state.ingest_jobs = JobRegistry()
    logger.success(
        f"Engine ready. collection points={store.count()} · LLM={settings.llm_model}"
    )
    yield
    # shutdown: nothing to release for now.


app = FastAPI(title="BNK Bot Engine", version="0.2.0", lifespan=lifespan)

app.include_router(chat_router)   # [고객] /query
app.include_router(admin_router)  # [관리자] /admin/ingest


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}
