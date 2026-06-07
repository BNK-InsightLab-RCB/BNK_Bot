import sys
from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber
from loguru import logger

from src.ingestion.table_extractor import TABLE_SETTINGS, extract_markdown


class PDFParser:
    """PDF -> Markdown with a routed strategy.

    Korean financial PDFs (BNK 약관/설명서) are born-digital and wrap content in
    vector-ruled tables. Docling's vision-based TableFormer scrambles those
    line-bordered, merged-cell tables (dropped sub-tables, mismatched
    period<->rate), so for such PDFs we reconstruct tables deterministically
    from the ruling lines via pdfplumber (see ``table_extractor``).

    PDFs without a usable text layer (scanned) or without ruled tables (other
    layouts) fall back to Docling with a Korean OCR backend, keeping the parser
    general-purpose.
    """

    # A page needs at least this many text-layer chars to count as digital.
    MIN_CHARS_PER_PAGE = 50

    def __init__(self, output_base_dir: Path):
        self.output_base_dir = Path(output_base_dir)
        self.output_base_dir.mkdir(parents=True, exist_ok=True)
        self._docling = None  # lazily built; heavy model load

    # ----- strategy detection -------------------------------------------------
    def _profile(self, pdf_path: Path) -> tuple[bool, bool]:
        """Return (has_text_layer, has_ruled_tables)."""
        with fitz.open(pdf_path) as doc:
            if doc.page_count == 0:
                return False, False
            chars = sum(len(p.get_text("text").strip()) for p in doc)
            has_text = chars / doc.page_count >= self.MIN_CHARS_PER_PAGE
        has_tables = False
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                if page.find_tables(TABLE_SETTINGS):
                    has_tables = True
                    break
        return has_text, has_tables

    # ----- Docling fallback ---------------------------------------------------
    def _build_docling(self):
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions,
            RapidOcrOptions,
            TableFormerMode,
        )
        from docling.document_converter import DocumentConverter, PdfFormatOption

        po = PdfPipelineOptions()
        po.do_ocr = True  # recover text rendered as images (stamps, scans)
        po.ocr_options = RapidOcrOptions(lang=["korean", "english"])
        po.do_table_structure = True
        po.table_structure_options.mode = TableFormerMode.ACCURATE
        po.table_structure_options.do_cell_matching = True
        return DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=po)}
        )

    def _parse_with_docling(self, pdf_path: Path) -> str:
        if self._docling is None:
            logger.info("Loading Docling (RapidOCR) for fallback parsing...")
            self._docling = self._build_docling()
        result = self._docling.convert(pdf_path)
        return result.document.export_to_markdown()

    # ----- public API ---------------------------------------------------------
    def parse(self, pdf_path: str | Path, force: bool = False) -> Path:
        pdf_path = Path(pdf_path)
        result_dir = self.output_base_dir / pdf_path.stem
        result_dir.mkdir(parents=True, exist_ok=True)
        out_md = result_dir / f"{pdf_path.stem}.md"

        # Cache: skip the (slow, esp. Docling) parse if the MD already exists.
        # Makes re-ingestion fast and idempotent. Pass force=True to re-parse.
        if out_md.exists() and not force:
            logger.info(f"{pdf_path.name}: cached MD exists, skip parse")
            return out_md

        has_text, has_tables = self._profile(pdf_path)
        try:
            if has_text and has_tables:
                strategy = "lattice (pdfplumber)"
                md = extract_markdown(str(pdf_path))
            else:
                strategy = "docling+rapidocr"
                md = self._parse_with_docling(pdf_path)
        except Exception as e:
            logger.error(f"Error parsing {pdf_path.name}: {e}")
            raise

        logger.info(
            f"{pdf_path.name}: text_layer={has_text} ruled_tables={has_tables} "
            f"-> strategy={strategy}"
        )
        out_md = result_dir / f"{pdf_path.stem}.md"
        out_md.write_text(md, encoding="utf-8")
        logger.success(f"Converted: {pdf_path.name} -> {out_md} ({len(md)} chars)")
        return out_md


if __name__ == "__main__":
    sys.path.append(str(Path(__file__).parent.parent.parent))
    from src.config import settings

    parser = PDFParser(settings.processed_dir)
    raw_files = sorted(settings.raw_dir.rglob("*.pdf"))
    if not raw_files:
        logger.warning(f"No PDF files found in {settings.raw_dir}")
    else:
        test_file = next(
            (f for f in raw_files if "마이플랜퇴직연금정기예금" in f.name), raw_files[0]
        )
        logger.info(f"Testing with file: {test_file}")
        parser.parse(test_file)
