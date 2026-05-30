from __future__ import annotations

from fastapi import APIRouter, Request

from app.schemas import HealthResponse


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        elasticsearch_index=settings.elasticsearch_index,
        qwen_model_path=settings.qwen_model_path,
    )

