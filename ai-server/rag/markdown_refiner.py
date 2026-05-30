from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from llm.mlx_client import MlxQwenClient
from llm.prompts import build_refine_prompt


FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
HEADING_SPLIT_RE = re.compile(r"(?=^##\s+)", re.MULTILINE)


@dataclass(frozen=True)
class RefineResult:
    input_path: Path
    output_path: Path
    refined_by: str
    block_count: int


def refine_markdown_file(
    input_path: Path,
    output_dir: Path,
    llm: MlxQwenClient,
    max_tokens: int = 2048,
) -> RefineResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata, body = _split_front_matter(input_path.read_text(encoding="utf-8"))
    refined_blocks = []

    for block in _split_blocks(body):
        if _is_image_only_block(block):
            continue
        refined = llm.generate(build_refine_prompt(block), max_tokens=max_tokens).text
        cleaned = _select_refined_or_source(_clean_generated_markdown(refined), block)
        refined_blocks.append(cleaned)

    output_path = output_dir / input_path.name
    output_path.write_text(
        _render_front_matter(metadata, llm.model_path) + "\n\n" + "\n\n".join(refined_blocks).strip() + "\n",
        encoding="utf-8",
    )
    return RefineResult(
        input_path=input_path,
        output_path=output_path,
        refined_by=llm.model_path,
        block_count=len(refined_blocks),
    )


def refine_markdown_directory(
    input_dir: Path,
    output_dir: Path,
    llm: MlxQwenClient,
    max_tokens: int = 2048,
) -> list[RefineResult]:
    return [
        refine_markdown_file(markdown_path, output_dir, llm, max_tokens=max_tokens)
        for markdown_path in sorted(input_dir.glob("*.md"))
    ]


def _split_front_matter(text: str) -> tuple[str, str]:
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return "", text
    return match.group(1).strip(), text[match.end() :].strip()


def _render_front_matter(metadata: str, refined_by: str) -> str:
    lines = ["---"]
    if metadata:
        lines.extend(metadata.splitlines())
    lines.extend(
        [
            f"refined_by: {refined_by}",
            "refine_status: needs_review",
            "---",
        ]
    )
    return "\n".join(lines)


def _split_blocks(markdown: str) -> list[str]:
    parts = [part.strip() for part in HEADING_SPLIT_RE.split(markdown) if part.strip()]
    if not parts:
        return [markdown.strip()] if markdown.strip() else []
    return parts


def _is_image_only_block(markdown: str) -> bool:
    without_images = markdown.replace("<!-- image -->", "").strip()
    return not without_images


def _clean_generated_markdown(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"</?think>", "", cleaned)
    cleaned = cleaned.replace("<|im_start|>", "").replace("<|im_end|>", "")
    cleaned = re.sub(r"\A\s*```(?:markdown)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```\s*\Z", "", cleaned)
    cleaned = re.sub(r"(?m)^```(?:markdown)?\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?m)^```\s*$", "", cleaned)
    lines = [
        line.rstrip()
        for line in cleaned.splitlines()
        if "(이미지에서 추출된 텍스트)" not in line
    ]
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _clean_source_markdown(markdown: str) -> str:
    cleaned = markdown.replace("<!-- image -->", "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _select_refined_or_source(refined: str, source: str) -> str:
    source_cleaned = _clean_source_markdown(source)
    if not refined:
        return source_cleaned
    if len(source_cleaned) >= 1000 and len(refined) < len(source_cleaned) * 0.35:
        return source_cleaned
    return refined
