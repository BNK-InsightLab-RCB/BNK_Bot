# AGENTS.md

## Goal

Build and maintain the Source-Aware Branch Support RAG Chatbot PoC.

## Constraints

- Use only the local Qwen OpenAI-compatible server for LLM calls.
- Do not add external hosted LLM APIs.
- Keep branch-role answers free of source code, internal API paths, database internals, secrets, and bypass instructions.
- Prefer static extraction first; use LLM summarization as an optional enhancer.
- Keep the sample end-to-end path runnable without production systems.

## Useful Commands

```bash
docker compose up -d elasticsearch
./scripts/run_qwen_server.sh
python -m backend.app.ingestion.pipeline --source-dir backend/examples/bank_sample --reset-index
uvicorn backend.app.main:app --reload --port 9000
cd frontend && npm install && npm run dev
pytest backend/tests
```

## Implementation Notes

- `backend/app/parsers` converts source files into structured `KnowledgeDocument` objects.
- `backend/app/ingestion/pipeline.py` owns scan, parse, enrich, embed, index, and graph persistence.
- `backend/app/retrieval` owns query analysis, exact/BM25/vector retrieval, RRF, graph expansion, and context building.
- `backend/app/rag` owns role-aware answer generation, citations, and safety.
- `backend/examples/bank_sample` must remain small and deterministic so tests are fast.
