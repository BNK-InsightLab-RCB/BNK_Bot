from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter
from docling.document_converter import PdfFormatOption


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
    normalized = {
        key: value if isinstance(value, bool) else str(value).replace("\n", " ").strip()
        for key, value in metadata.items()
    }
    body = yaml.safe_dump(normalized, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{body}\n---"


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
    converter = create_pdf_converter()
    return [convert_pdf_to_markdown(pdf_path, markdown_dir, converter) for pdf_path in pdf_paths]


def create_pdf_converter() -> DocumentConverter:
    pipeline_options = PdfPipelineOptions()
    pipeline_options.accelerator_options = AcceleratorOptions(device="cpu")
    pipeline_options.do_ocr = False

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        }
    )
