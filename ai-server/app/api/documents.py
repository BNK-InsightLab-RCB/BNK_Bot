from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.config import ROOT_DIR
from app.deps import resolve_repo_path
from app.schemas import ConvertDocumentRequest, ConvertDocumentResponse
from rag.pdf_to_markdown import convert_pdf_to_markdown, create_pdf_converter


router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/convert", response_model=ConvertDocumentResponse)
def convert_document(request: ConvertDocumentRequest) -> ConvertDocumentResponse:
    try:
        pdf_path = resolve_repo_path(request.pdf_path)
        markdown_dir = resolve_repo_path(request.markdown_dir) if request.markdown_dir else ROOT_DIR / "data/markdown"
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"PDF not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    output_path = convert_pdf_to_markdown(pdf_path, markdown_dir, create_pdf_converter())
    return ConvertDocumentResponse(markdown_path=str(output_path))

