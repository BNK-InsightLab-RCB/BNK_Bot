from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ROOT_DIR
from rag.pdfplumber_tables import extract_pdfplumber_tables, render_table_markdown


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract and clean PDF tables with pdfplumber.")
    parser.add_argument("pdf", nargs="?", help="PDF file path. Defaults to the first file in data/raw_pdfs.")
    parser.add_argument("--output-dir", default=str(ROOT_DIR / "data/table_extracts"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_path = Path(args.pdf) if args.pdf else _first_pdf()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    tables = extract_pdfplumber_tables(pdf_path)
    json_path = output_dir / f"{pdf_path.stem}.tables.json"
    markdown_path = output_dir / f"{pdf_path.stem}.tables.md"

    json_path.write_text(
        json.dumps(
            [
                {
                    "page_number": table.page_number,
                    "table_index": table.table_index,
                    "bbox": table.bbox,
                    "rows": table.rows,
                }
                for table in tables
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    markdown_parts = [f"# {pdf_path.stem} table extracts"]
    for table in tables:
        markdown_parts.extend(
            [
                "",
                f"## page {table.page_number} table {table.table_index}",
                "",
                f"bbox: {tuple(round(value, 2) for value in table.bbox)}",
                "",
                render_table_markdown(table.rows),
            ]
        )
    markdown_path.write_text("\n".join(markdown_parts).strip() + "\n", encoding="utf-8")

    print(f"Extracted tables: {len(tables)}")
    print(f"JSON: {json_path}")
    print(f"Markdown: {markdown_path}")


def _first_pdf() -> Path:
    pdfs = sorted((ROOT_DIR / "data/raw_pdfs").glob("*.pdf"))
    if not pdfs:
        raise SystemExit("No PDF files found in data/raw_pdfs.")
    return pdfs[0]


if __name__ == "__main__":
    main()
