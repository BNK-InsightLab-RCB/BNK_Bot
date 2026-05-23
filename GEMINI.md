# BNK Bot - RAG-based CS Chatbot

## Project Overview
A Customer Service (CS) chatbot powered by Retrieval-Augmented Generation (RAG).

## Core Architecture (Data Ingestion Focus)
The project is currently focused on the high-quality data ingestion pipeline.

### Directory Structure
- `src/ingestion/`: Modular pipeline for processing data.
    - `parser.py`: PDF to Markdown conversion (using MinerU).
    - `processor.py`: Data cleaning and semantic chunking (using sLLM).
    - `embedder.py`: Generating vector embeddings.
    - `qdrant.py`: Qdrant Vector DB interactions.
    - `pipeline.py`: Orchestrating the ingestion flow.
- `src/config.py`: Centralized configuration management.
- `data/`: Data storage with intermediate stages for debugging.
    - `raw/`: Original PDF files.
    - `processed/`: Markdown output from parser.
    - `chunks/`: Processed chunks for quality verification.
    - `failed/`: Files that failed during processing.

## Technical Conventions
- **Vector DB:** Qdrant.
- **Parsing:** MinerU.
- **Chunking Strategy:** sLLM-assisted semantic chunking.
- **Configuration:** Use `src/config.py` with `pydantic-settings`. Do not use `os.getenv` directly in business logic.

## Development Workflow
1. **Research & Strategy:** Validate tool configurations (Qdrant, MinerU).
2. **Execution:** Surgical updates with mandatory testing for data processing scripts.
3. **Validation:** Ensure chunk quality by inspecting `data/chunks/`.
