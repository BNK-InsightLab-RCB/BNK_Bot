# BNK Bot - RAG-based CS Chatbot

## 📌 Project Status (Current)
- **Architecture Finalized:** Lean and modular ingestion-first structure established.
- **Environment Setup:** Python virtual environment (`.venv`) initialized and `requirements.txt` installed.
- **Git Baseline:** Initial commit completed with a robust `.gitignore` preventing environment/data leaks.

## 🏗️ Core Architecture
We prioritize high-quality data ingestion through a modular pipeline.

### Directory Structure
- `src/ingestion/`: Modular components for data processing.
    - `parser.py`: PDF → Markdown conversion (using MinerU).
    - `processor.py`: Data cleaning and sLLM-assisted semantic chunking.
    - `embedder.py`: Generating vector embeddings.
    - `qdrant.py`: Qdrant Vector DB client and collection management.
    - `pipeline.py`: Orchestrating the end-to-end ingestion flow.
- `src/config.py`: Centralized configuration management using `pydantic-settings`.
- `data/`: Multi-stage storage for debugging and quality control.
    - `raw/`: Original source PDFs.
    - `processed/`: Markdown outputs for verification.
    - `chunks/`: Final chunked data for retrieval tuning.
    - `failed/`: Quarantine for processing errors.

## 🛠️ Technical Conventions
- **Vector DB:** Qdrant (Primary). Designed for easy migration/extension to Elasticsearch.
- **Parsing:** MinerU for layout-preserving Markdown conversion.
- **Chunking:** sLLM-assisted refinement to ensure semantic integrity.
- **Settings:** All environment variables must be accessed via `src.config.settings`.

## 🚀 Next Steps (Action Plan)
1. **Parser Implementation:** Implement `src/ingestion/parser.py` using MinerU to process files in `data/raw/`.
2. **Qdrant Integration:** Develop `src/ingestion/qdrant.py` to handle collection schema and upsert logic.
3. **Pipeline Orchestration:** Connect components in `src/ingestion/pipeline.py` for automated batch processing.

## 💡 Handoff Notes
- **Virtual Env:** Always activate before working: `source .venv/bin/activate`
- **Dependencies:** If new libraries are added, update `requirements.txt` via `pip freeze`.
- **Modularity:** Keep embedding logic (`embedder.py`) and DB logic (`qdrant.py`) strictly separated as planned.
