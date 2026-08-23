"""질의 감사 기록 (최소선).

금융 상담 시스템은 "무엇을 묻고, 어떤 근거로, 무엇을 답했는가"가 사후에 재구성돼야
한다. 다만 **감사 로그의 형식·보존기간·저장소는 납품처 규격에 종속**이라 지금 확정하면
재작업이 된다.

그래서 여기서 정하는 건 형식이 아니라 **"무엇을 남길지"** 다(그건 우리 몫):
질문 · 검색 근거(문서·점수) · 답변 · 거부/검증 결과 · 지연. 형식은 JSONL 한 줄로
두고, 납품처 규격이 정해지면 **이 모듈만 교체**한다(DB·Kafka·감사 API 등).

주의: 개인정보는 남기지 않는다 — 질문 본문 외 사용자 식별자를 다루지 않으며,
사용자 식별이 필요해지면 그건 규격 확정 시 상위(SpringBoot)에서 결정할 사안이다.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from loguru import logger

from src.config import settings

_AUDIT_FILE = "query_audit.jsonl"


def record_query(
    *,
    question: str,
    answer: str,
    hits,
    grounded: bool,
    violations: list[str],
    refused: bool,
    latency_s: float,
) -> None:
    """질의 1건을 JSONL 한 줄로 append. 실패해도 응답을 막지 않는다."""
    try:
        event = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "question": question,
            "answer": answer,
            "refused": refused,
            "grounded": grounded,
            "violations": violations,
            "used_chunks": len(hits),
            "top1_score": round(hits[0].score, 4) if hits else None,
            # 근거 식별자 — 답변 재현·검증용(본문은 남기지 않는다: 용량/중복).
            "evidence": [
                {
                    "source_file": h.payload.get("source_file", ""),
                    "chunk_index": h.payload.get("chunk_index"),
                    "product_name": h.payload.get("product_name", ""),
                    "page": h.payload.get("page"),
                    "score": round(h.score, 4),
                }
                for h in hits
            ],
            "latency_s": round(latency_s, 2),
            "llm_model": settings.llm_model,
            "score_threshold": settings.retrieval_score_threshold,
        }
        settings.logs_dir.mkdir(parents=True, exist_ok=True)
        with (settings.logs_dir / _AUDIT_FILE).open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:  # 감사 기록 실패가 고객 응답을 깨뜨리면 안 된다
        logger.error(f"audit write failed: {e}")


def audit_path() -> Path:
    return settings.logs_dir / _AUDIT_FILE
