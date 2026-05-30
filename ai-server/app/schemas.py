from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    elasticsearch_index: str
    qwen_model_path: str


class ConvertDocumentRequest(BaseModel):
    pdf_path: str = Field(..., description="Path to a PDF file, relative to repo root or absolute.")
    markdown_dir: str | None = None


class ConvertDocumentResponse(BaseModel):
    markdown_path: str


class RefineMarkdownRequest(BaseModel):
    markdown_path: str = Field(..., description="Path to a Markdown file, relative to repo root or absolute.")
    output_dir: str | None = None
    max_tokens: int = 2048


class RefineMarkdownResponse(BaseModel):
    input_path: str
    output_path: str
    refined_by: str
    block_count: int
    status: str


class SearchRequest(BaseModel):
    query: str
    top_k: int = 10
    bm25_k: int = 20
    vector_k: int = 20


class SearchResultItem(BaseModel):
    chunk_id: str
    doc_id: str
    title: str
    section: str
    source_file: str
    rrf_score: float
    raw_score: float
    preview: str


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem]

