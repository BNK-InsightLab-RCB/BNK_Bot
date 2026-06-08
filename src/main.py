"""FastAPI application entry point — the BNK Bot CS chatbot engine.

This is the API layer that sits ON TOP of the existing pipeline:
- chat domain  : POST /query   (질문 → 검색 → Qwen 답변, E2~E5에서 채움)
- ingestion    : POST /admin/* (적재 트리거; E6에서 기존 pipeline 호출)

Ingestion/RAG logic lives in their own domains (src/ingestion, src/chat);
this module only wires routers and app-level concerns.

Run (dev):  uvicorn src.main:app --reload --port 8000
Docs:       http://localhost:8000/docs
"""
from __future__ import annotations

from fastapi import FastAPI

from src.chat.router import router as chat_router

app = FastAPI(title="BNK Bot Engine", version="0.1.0")

app.include_router(chat_router)


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}
