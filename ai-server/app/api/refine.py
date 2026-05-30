from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.deps import get_llm, resolve_repo_path
from app.schemas import RefineMarkdownRequest, RefineMarkdownResponse
from rag.markdown_refiner import refine_markdown_file


router = APIRouter(prefix="/documents", tags=["refine"])


@router.post("/refine", response_model=RefineMarkdownResponse)
def refine_document(request: Request, payload: RefineMarkdownRequest) -> RefineMarkdownResponse:
    try:
        markdown_path = resolve_repo_path(payload.markdown_path)
        output_dir = resolve_repo_path(payload.output_dir) if payload.output_dir else request.app.state.settings.refined_markdown_dir
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not markdown_path.exists():
        raise HTTPException(status_code=404, detail=f"Markdown not found: {markdown_path}")
    if markdown_path.suffix.lower() != ".md":
        raise HTTPException(status_code=400, detail="Only Markdown files are supported.")

    result = refine_markdown_file(markdown_path, output_dir, get_llm(request), max_tokens=payload.max_tokens)
    return RefineMarkdownResponse(
        input_path=str(result.input_path),
        output_path=str(result.output_path),
        refined_by=result.refined_by,
        block_count=result.block_count,
        status="needs_review",
    )

