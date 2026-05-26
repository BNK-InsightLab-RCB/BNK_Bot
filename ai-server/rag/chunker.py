from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml


FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    section: str
    content: str
    source_file: str
    business_area: str
    customer_type: str
    channel: str
    version: str
    effective_date: str
    permission_level: str
    is_active: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "title": self.title,
            "section": self.section,
            "content": self.content,
            "source_file": self.source_file,
            "business_area": self.business_area,
            "customer_type": self.customer_type,
            "channel": self.channel,
            "version": self.version,
            "effective_date": self.effective_date,
            "permission_level": self.permission_level,
            "is_active": self.is_active,
        }


def parse_markdown(markdown_path: Path) -> tuple[dict[str, object], str]:
    text = markdown_path.read_text(encoding="utf-8")
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return _fallback_metadata(markdown_path), text

    metadata = yaml.safe_load(match.group(1)) or {}
    body = text[match.end() :]
    return {**_fallback_metadata(markdown_path), **metadata}, body


def split_markdown_sections(markdown: str) -> list[tuple[str, str]]:
    matches = list(HEADING_RE.finditer(markdown))
    if not matches:
        return [("본문", markdown.strip())] if markdown.strip() else []

    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        heading = match.group(2).strip()
        content = markdown[start:end].strip()
        if content:
            sections.append((heading, content))
    return sections


def split_text(text: str, max_chars: int, overlap: int) -> list[str]:
    cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(cleaned) <= max_chars:
        return [cleaned] if cleaned else []

    paragraphs = [paragraph.strip() for paragraph in cleaned.split("\n\n") if paragraph.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)
        current = paragraph

        while len(current) > max_chars:
            chunks.append(current[:max_chars].strip())
            current = current[max(0, max_chars - overlap) :].strip()

    if current:
        chunks.append(current)
    return chunks


def chunk_markdown_file(markdown_path: Path, max_chars: int, overlap: int) -> list[Chunk]:
    metadata, body = parse_markdown(markdown_path)
    doc_id = str(metadata["doc_id"])
    title = str(metadata["title"])
    chunks: list[Chunk] = []

    for section, section_text in split_markdown_sections(body):
        for text_chunk in split_text(section_text, max_chars, overlap):
            index = len(chunks) + 1
            chunks.append(
                Chunk(
                    chunk_id=f"{doc_id}:{index:04d}",
                    doc_id=doc_id,
                    title=title,
                    section=section,
                    content=_build_embedding_text(metadata, section, text_chunk),
                    source_file=str(metadata.get("source_file", markdown_path)),
                    business_area=str(metadata.get("business_area", "unknown")),
                    customer_type=str(metadata.get("customer_type", "unknown")),
                    channel=str(metadata.get("channel", "unknown")),
                    version=str(metadata.get("version", "unknown")),
                    effective_date=str(metadata.get("effective_date", "unknown")),
                    permission_level=str(metadata.get("permission_level", "internal")),
                    is_active=bool(metadata.get("is_active", True)),
                )
            )
    return chunks


def chunk_markdown_directory(markdown_dir: Path, max_chars: int, overlap: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    for markdown_path in sorted(markdown_dir.glob("*.md")):
        chunks.extend(chunk_markdown_file(markdown_path, max_chars, overlap))
    return chunks


def write_chunks_jsonl(chunks: Iterable[Chunk], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for chunk in chunks:
            file.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")


def _fallback_metadata(markdown_path: Path) -> dict[str, object]:
    stem = markdown_path.stem
    return {
        "doc_id": stem,
        "title": stem,
        "business_area": "unknown",
        "customer_type": "unknown",
        "channel": "unknown",
        "version": "unknown",
        "effective_date": "unknown",
        "permission_level": "internal",
        "is_active": True,
        "source_file": str(markdown_path),
    }


def _build_embedding_text(metadata: dict[str, object], section: str, content: str) -> str:
    return "\n".join(
        [
            f"문서명: {metadata.get('title', '')}",
            f"업무영역: {metadata.get('business_area', '')}",
            f"고객구분: {metadata.get('customer_type', '')}",
            f"채널: {metadata.get('channel', '')}",
            f"섹션: {section}",
            f"본문: {content}",
        ]
    ).strip()

