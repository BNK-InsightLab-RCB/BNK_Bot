from __future__ import annotations

from pathlib import Path
from typing import Optional

from docling.document_converter import DocumentConverter


def default_metadata(pdf_path: Path) -> dict[str, object]:
    stem = pdf_path.stem
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
        "source_file": str(pdf_path),
    }


def render_front_matter(metadata: dict[str, object]) -> str:
    lines = ["---"]
    for key, value in metadata.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value).replace("\n", " ").strip()
        lines.append(f"{key}: {rendered}")
    lines.append("---")
    return "\n".join(lines)


def convert_pdf_to_markdown(
    pdf_path: Path,
    markdown_dir: Path,
    converter: Optional[DocumentConverter] = None,
) -> Path:
    markdown_dir.mkdir(parents=True, exist_ok=True)
    output_path = markdown_dir / f"{pdf_path.stem}.md"

    document_converter = converter or DocumentConverter()
    result = document_converter.convert(str(pdf_path))
    md_body = result.document.export_to_markdown()

    metadata = default_metadata(pdf_path)
    output_path.write_text(
        f"{render_front_matter(metadata)}\n\n# {pdf_path.stem}\n\n{md_body.strip()}\n",
        encoding="utf-8",
    )
    return output_path


def convert_pdf_directory(pdf_dir: Path, markdown_dir: Path) -> list[Path]:
    pdf_paths = sorted(pdf_dir.glob("*.pdf"))
    converter = DocumentConverter()
    return [convert_pdf_to_markdown(pdf_path, markdown_dir, converter) for pdf_path in pdf_paths]
